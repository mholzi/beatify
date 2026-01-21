"""Media player discovery and control service for Beatify."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from ..const import MEDIA_CONTENT_TYPES, MEDIA_CONTENT_TYPE_DEFAULT

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


def get_media_content_type(uri: str) -> str:
    """
    Determine the appropriate media_content_type for a given URI.

    Different media players (especially Alexa) require provider-specific
    content types. For example, Alexa devices return "Sorry, direct music
    streaming isn't supported" when using generic "music" type for Spotify URIs.

    For Apple Music via Music Assistant, URIs use the "applemusic://" scheme.
    Music Assistant handles the actual routing to Apple Music internally,
    so the content type "music" is appropriate.

    Args:
        uri: Media content URI (e.g., "spotify:track:xxx", "applemusic://track/123")

    Returns:
        Provider-specific content type (e.g., "spotify") or default "music"

    Examples:
        >>> get_media_content_type("spotify:track:abc123")
        'spotify'
        >>> get_media_content_type("applemusic://track/123456789")
        'music'
        >>> get_media_content_type("http://example.com/song.mp3")
        'music'

    """
    # Extract provider prefix from URI (e.g., "spotify" from "spotify:track:xxx")
    if ":" in uri:
        provider = uri.split(":")[0].lower()
        content_type = MEDIA_CONTENT_TYPES.get(provider, MEDIA_CONTENT_TYPE_DEFAULT)
        _LOGGER.debug(
            "URI '%s' detected as provider '%s', using content_type '%s'",
            uri,
            provider,
            content_type,
        )
        return content_type

    return MEDIA_CONTENT_TYPE_DEFAULT

# Timeout for pre-flight connectivity check (seconds)
PREFLIGHT_TIMEOUT = 5.0

# Timeout for waiting for metadata to update after playing (seconds)
METADATA_WAIT_TIMEOUT = 5.0
METADATA_POLL_INTERVAL = 0.3


class MediaPlayerService:
    """Service for controlling HA media player."""

    def __init__(self, hass: HomeAssistant, entity_id: str) -> None:
        """
        Initialize with HomeAssistant and entity_id.

        Args:
            hass: Home Assistant instance
            entity_id: Media player entity ID

        """
        self._hass = hass
        self._entity_id = entity_id

    async def play_song(self, uri: str) -> bool:
        """
        Play a song by URI.

        Args:
            uri: Media content URI (e.g., spotify:track:xxx)

        Returns:
            True if playback started successfully, False otherwise

        """
        try:
            # Determine content type from URI prefix (Story 16.2)
            # Alexa devices require "spotify" content type, not generic "music"
            content_type = get_media_content_type(uri)

            await self._hass.services.async_call(
                "media_player",
                "play_media",
                {
                    "entity_id": self._entity_id,
                    "media_content_id": uri,
                    "media_content_type": content_type,
                },
                blocking=True,
            )
            return True  # noqa: TRY300
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to play song %s: %s", uri, err)  # noqa: TRY400
            return False

    async def get_metadata(self) -> dict[str, Any]:
        """
        Get current track metadata from media player entity.

        Returns:
            Dict with artist, title, album_art keys

        """
        state = self._hass.states.get(self._entity_id)
        if not state:
            return {
                "artist": "Unknown Artist",
                "title": "Unknown Title",
                "album_art": "/beatify/static/img/no-artwork.svg",
            }

        return {
            "artist": state.attributes.get("media_artist", "Unknown Artist"),
            "title": state.attributes.get("media_title", "Unknown Title"),
            "album_art": state.attributes.get(
                "entity_picture", "/beatify/static/img/no-artwork.svg"
            ),
        }

    async def wait_for_metadata_update(self, uri: str) -> dict[str, Any]:
        """
        Wait for media player to update metadata after playing a song.

        Polls until media_content_id contains the track ID from the URI,
        or timeout is reached.

        Args:
            uri: The Spotify URI that was just played (e.g., spotify:track:xxx)

        Returns:
            Dict with artist, title, album_art keys

        """
        # Extract track ID from URI (spotify:track:xxx -> xxx)
        track_id = uri.split(":")[-1] if ":" in uri else uri

        # Get initial state for comparison
        initial_state = self._hass.states.get(self._entity_id)
        initial_title = (
            initial_state.attributes.get("media_title")
            if initial_state
            else None
        )

        elapsed = 0.0
        while elapsed < METADATA_WAIT_TIMEOUT:
            state = self._hass.states.get(self._entity_id)
            if state:
                # Check if media_content_id contains our track ID
                content_id = state.attributes.get("media_content_id", "")
                if track_id in content_id:
                    _LOGGER.debug(
                        "Metadata updated after %.1fs (matched track ID)",
                        elapsed,
                    )
                    return self._extract_metadata(state)

                # Also check if title changed (fallback)
                current_title = state.attributes.get("media_title")
                if current_title and current_title != initial_title:
                    _LOGGER.debug(
                        "Metadata updated after %.1fs (title changed)",
                        elapsed,
                    )
                    return self._extract_metadata(state)

            await asyncio.sleep(METADATA_POLL_INTERVAL)
            elapsed += METADATA_POLL_INTERVAL

        # Timeout - return whatever we have
        _LOGGER.warning(
            "Metadata not updated within %.1fs, using current state",
            METADATA_WAIT_TIMEOUT,
        )
        return await self.get_metadata()

    def _extract_metadata(self, state: Any) -> dict[str, Any]:
        """Extract metadata dict from state object."""
        return {
            "artist": state.attributes.get("media_artist", "Unknown Artist"),
            "title": state.attributes.get("media_title", "Unknown Title"),
            "album_art": state.attributes.get(
                "entity_picture", "/beatify/static/img/no-artwork.svg"
            ),
        }

    async def stop(self) -> bool:
        """
        Stop playback.

        Returns:
            True if successful, False otherwise

        """
        try:
            await self._hass.services.async_call(
                "media_player",
                "media_stop",
                {"entity_id": self._entity_id},
            )
            return True  # noqa: TRY300
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to stop playback: %s", err)  # noqa: TRY400
            return False

    def get_volume(self) -> float:
        """
        Get current volume level from media player.

        Returns:
            Volume level 0.0 to 1.0, or 0.5 if unavailable

        """
        state = self._hass.states.get(self._entity_id)
        if not state:
            return 0.5
        volume = state.attributes.get("volume_level")
        if volume is None:
            return 0.5
        return float(volume)

    async def set_volume(self, level: float) -> bool:
        """
        Set volume level.

        Args:
            level: Volume level 0.0 to 1.0

        Returns:
            True if successful

        """
        try:
            await self._hass.services.async_call(
                "media_player",
                "volume_set",
                {
                    "entity_id": self._entity_id,
                    "volume_level": max(0.0, min(1.0, level)),
                },
            )
            return True  # noqa: TRY300
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to set volume: %s", err)  # noqa: TRY400
            return False

    def is_available(self) -> bool:
        """
        Check if media player is available.

        Returns:
            True if media player is available

        """
        state = self._hass.states.get(self._entity_id)
        return state is not None and state.state != "unavailable"

    async def verify_responsive(self) -> bool:
        """
        Verify media player is actually responsive (pre-flight check).

        Sends a lightweight command to wake up the speaker and verify
        it responds within PREFLIGHT_TIMEOUT seconds.

        Returns:
            True if media player responded, False if timeout or error

        """
        try:
            # Use volume_set with current volume as a lightweight ping
            # This wakes up sleeping speakers without changing anything
            current_volume = self.get_volume()

            async with asyncio.timeout(PREFLIGHT_TIMEOUT):
                await self._hass.services.async_call(
                    "media_player",
                    "volume_set",
                    {
                        "entity_id": self._entity_id,
                        "volume_level": current_volume,
                    },
                    blocking=True,
                )
            _LOGGER.debug("Media player %s is responsive", self._entity_id)
            return True
        except TimeoutError:
            _LOGGER.warning(
                "Media player %s not responsive (timeout after %.1fs)",
                self._entity_id,
                PREFLIGHT_TIMEOUT,
            )
            return False
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning(
                "Media player %s not responsive: %s", self._entity_id, err
            )
            return False


async def async_get_media_players(hass: HomeAssistant) -> list[dict]:
    """Get all available media player entities."""
    media_players = [
        {
            "entity_id": state.entity_id,
            "friendly_name": state.attributes.get("friendly_name", state.entity_id),
            "state": state.state,
        }
        for state in hass.states.async_all("media_player")
    ]

    _LOGGER.debug("Found %d media players", len(media_players))
    return media_players
