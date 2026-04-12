"""Media player discovery and control service for Beatify."""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if sys.version_info >= (3, 11):
    from asyncio import timeout as async_timeout
else:
    from async_timeout import timeout as async_timeout

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from custom_components.beatify.analytics import AnalyticsStorage

_LOGGER = logging.getLogger(__name__)


# Platform capability definitions for multi-platform routing
# Resolves GitHub issues #38 (Nest Audio) and #39 (Google TV Streamer)
PLATFORM_CAPABILITIES: dict[str, dict[str, Any]] = {
    "music_assistant": {
        "supported": True,
        "spotify": True,
        "apple_music": True,
        "youtube_music": True,
        "tidal": True,
        "deezer": True,
        "method": "uri",
        "warning": "Premium account must be configured in Music Assistant",
    },
    "sonos": {
        "supported": True,
        "spotify": True,
        "apple_music": False,
        "youtube_music": False,
        "tidal": False,
        "method": "uri",
        "warning": "Spotify must be linked in Sonos app",
    },
    "alexa_media": {
        "supported": True,
        "spotify": True,
        "apple_music": True,
        "youtube_music": False,
        "tidal": False,
        "method": "text_search",
        "warning": "Service must be linked in Alexa app",
        "caveat": "Uses voice search - may occasionally play different version",
    },
    "cast": {
        "supported": False,
        "reason": "Cast devices require Music Assistant",
    },
}


def get_platform_capabilities(platform: str) -> dict[str, Any]:
    """
    Get playback capabilities for a platform.

    Args:
        platform: Platform identifier from entity registry (e.g., "music_assistant", "sonos")

    Returns:
        Dict with supported, spotify, apple_music, method, warning, caveat, reason keys

    """
    # Handle alexa as alias for alexa_media
    if platform == "alexa":
        platform = "alexa_media"

    return PLATFORM_CAPABILITIES.get(
        platform,
        {"supported": False, "reason": "Unknown player type"},
    )


# Timeout for pre-flight connectivity check (seconds)
PREFLIGHT_TIMEOUT = 3.0

# Timeout for play_song service calls (seconds) - prevents long hangs (#179)
PLAYBACK_TIMEOUT = 8.0

# Timeout for waiting for metadata to update after playing (seconds)
METADATA_WAIT_TIMEOUT = 5.0
METADATA_POLL_INTERVAL = 0.3


class MediaPlayerService:
    """Service for controlling HA media player."""

    def __init__(
        self,
        hass: HomeAssistant,
        entity_id: str,
        platform: str = "unknown",
        provider: str = "spotify",
    ) -> None:
        """
        Initialize with HomeAssistant and entity_id.

        Args:
            hass: Home Assistant instance
            entity_id: Media player entity ID
            platform: Platform identifier (music_assistant, sonos, alexa_media, etc.)
            provider: Music provider (spotify or apple_music)

        """
        self._hass = hass
        self._entity_id = entity_id
        self._platform = platform
        self._provider = provider
        self._analytics: AnalyticsStorage | None = None
        self._preflight_verified: bool = False

    def set_analytics(self, analytics: AnalyticsStorage) -> None:
        """
        Set analytics storage for error recording (Story 19.1 AC: #2).

        Args:
            analytics: AnalyticsStorage instance

        """
        self._analytics = analytics

    def _record_error(self, error_type: str, message: str) -> None:
        """
        Record error event to analytics (Story 19.1 AC: #2).

        Args:
            error_type: Error type constant
            message: Human-readable error message

        """
        if self._analytics:
            self._analytics.record_error(error_type, message)

    async def play_song(self, song: dict[str, Any]) -> bool:
        """
        Play a song using appropriate method for platform.

        Routes playback based on platform:
        - music_assistant: Uses music_assistant.play_media with URI
        - sonos: Uses media_player.play_media with Spotify URI
        - alexa_media: Uses media_player.play_media with text search

        Args:
            song: Song dict with _resolved_uri, artist, title keys

        Returns:
            True if playback started successfully, False otherwise

        """
        uri = song.get("_resolved_uri") or song.get("uri")
        if not uri:
            _LOGGER.error(
                "Song has no URI to play: %s - %s",
                song.get("artist"),
                song.get("title"),
            )
            self._record_error("PLAYBACK_FAILURE", "Song has no URI")
            return False

        try:
            if self._platform == "music_assistant":
                return await self._play_via_music_assistant(song)
            if self._platform == "sonos":
                return await self._play_via_sonos(song)
            if self._platform in ("alexa_media", "alexa"):
                return await self._play_via_alexa(song)
            _LOGGER.error("Unsupported platform: %s", self._platform)
            return False
        except TimeoutError:
            _LOGGER.error(
                "Playback timed out after %ss for %s: %s",
                PLAYBACK_TIMEOUT,
                uri,
                song.get("title", "?"),
            )
            self._record_error("PLAYBACK_TIMEOUT", f"Timed out playing: {uri}")
            return False
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Playback failed for %s: %s", uri, err)  # noqa: TRY400
            self._record_error("PLAYBACK_FAILURE", f"Failed to play {uri}: {err}")
            return False

    @staticmethod
    def _convert_uri_for_ma(uri: str) -> str:
        """
        Convert Beatify-internal URIs to formats Music Assistant understands.

        Beatify playlists store URIs in internal formats:
        - applemusic://track/<id>  → https://music.apple.com/song/<id>
        - tidal://track/<id>       → https://tidal.com/browse/track/<id>
        - spotify:track:<id>       → unchanged (MA native format)
        - https://music.youtube.com/... → unchanged (already a URL)

        Args:
            uri: Beatify-internal URI string

        Returns:
            URI converted to a format Music Assistant can resolve

        """
        if not uri:
            return uri

        if uri.startswith("deezer://track/"):
            track_id = uri.removeprefix("deezer://track/")
            return f"https://www.deezer.com/track/{track_id}"

        if uri.startswith("applemusic://track/"):
            track_id = uri.removeprefix("applemusic://track/")
            return f"https://music.apple.com/song/{track_id}"

        if uri.startswith("tidal://track/"):
            track_id = uri.removeprefix("tidal://track/")
            return f"https://tidal.com/browse/track/{track_id}"

        if uri.startswith("https://music.youtube.com/watch?v="):
            track_id = uri.removeprefix("https://music.youtube.com/watch?v=")
            return f"ytmusic://track/{track_id}"

        # spotify:track:<id> and https:// URLs are passed through unchanged
        return uri

    async def _play_via_music_assistant(self, song: dict[str, Any]) -> bool:
        """Play via Music Assistant (non-blocking + wait for actual playback)."""
        raw_uri = song.get("_resolved_uri")
        uri = self._convert_uri_for_ma(raw_uri)
        if uri != raw_uri:
            _LOGGER.debug("MA URI converted: %s → %s", raw_uri, uri)
        _LOGGER.debug("MA playback: %s on %s", uri, self._entity_id)

        expected_title = song.get("title") or ""

        # Capture state before to detect actual song change on speaker
        state_before = self._hass.states.get(self._entity_id)
        position_updated_before = (
            state_before.attributes.get("media_position_updated_at")
            if state_before
            else None
        )

        # Fire-and-forget the service call — blocking=True hangs on MA+YTMusic
        await self._hass.services.async_call(
            "music_assistant",
            "play_media",
            {"media_id": uri, "media_type": "track"},
            target={"entity_id": self._entity_id},
            blocking=False,
        )

        # Wait for the EXPECTED song to actually play on the speaker:
        # - media_title contains expected title (not just "any change" — prevents
        #   race condition where a previous slow song arrives during retry)
        # - media_position >= 1 (pos=0 means only queued in MA, not yet playing)
        # - media_position_updated_at changed (speaker is actively reporting)
        expected_lower = expected_title.lower()
        if not expected_lower:
            _LOGGER.warning("MA playback: no expected title — skipping title verification")
        elapsed = 0.0
        while elapsed < PLAYBACK_TIMEOUT:
            try:
                state = self._hass.states.get(self._entity_id)
            except Exception:
                _LOGGER.debug("MA poll: state read failed, retrying")
                await asyncio.sleep(0.5)
                elapsed += 0.5
                continue
            if state and state.state == "playing":
                current_title = state.attributes.get("media_title", "")
                position = state.attributes.get("media_position", 0)
                position_updated = state.attributes.get("media_position_updated_at")

                position_fresh = position_updated != position_updated_before
                actually_playing = isinstance(position, (int, float)) and position >= 1
                # Match expected title (substring, case-insensitive) — MA may
                # append suffixes like "(Official HD Video)" or "(7″ mix)"
                title_matches = (
                    (not expected_lower)  # no title to verify — accept any
                    or (expected_lower in current_title.lower() if current_title else False)
                )

                if title_matches and position_fresh and actually_playing:
                    _LOGGER.debug(
                        "MA playback confirmed after %.1fs: %s (pos=%.1f)",
                        elapsed,
                        current_title,
                        position,
                    )
                    return True
            await asyncio.sleep(0.5)
            elapsed += 0.5

        current_state = self._hass.states.get(self._entity_id)
        speaker_state = current_state.state if current_state else "unknown"

        # Hard failure: speaker is idle/unavailable/off — song won't play
        if speaker_state in ("idle", "unavailable", "off", "unknown"):
            _LOGGER.error(
                "MA playback failed after %.1fs for %s (state: %s)",
                PLAYBACK_TIMEOUT, uri, speaker_state,
            )
            return False

        _LOGGER.warning(
            "MA playback not confirmed after %.1fs for %s (state: %s). "
            "Continuing anyway — MA may still be buffering. (#345)",
            PLAYBACK_TIMEOUT, uri, speaker_state,
        )
        # Return True: don't skip the song — MA+YTMusic can take >8s to buffer.
        # Returning False would trigger retries that cause race conditions (#345).
        return True

    async def _play_via_sonos(self, song: dict[str, Any]) -> bool:
        """Play via Sonos (URI-based)."""
        uri = song.get("_resolved_uri")
        _LOGGER.debug("Sonos playback: %s on %s", uri, self._entity_id)

        async with async_timeout(PLAYBACK_TIMEOUT):
            await self._hass.services.async_call(
                "media_player",
                "play_media",
                {
                    "entity_id": self._entity_id,
                    "media_content_id": uri,
                    "media_content_type": "music",
                },
                blocking=True,
            )
        return True

    async def _play_via_alexa(self, song: dict[str, Any]) -> bool:
        """Play via Alexa (text search-based)."""
        search_text = self._get_alexa_search_text(song)
        content_type = "SPOTIFY" if self._provider == "spotify" else "APPLE_MUSIC"

        _LOGGER.debug(
            "Alexa playback: '%s' (%s) on %s",
            search_text,
            content_type,
            self._entity_id,
        )

        async with async_timeout(PLAYBACK_TIMEOUT):
            await self._hass.services.async_call(
                "media_player",
                "play_media",
                {
                    "entity_id": self._entity_id,
                    "media_content_id": search_text,
                    "media_content_type": content_type,
                },
                blocking=True,
            )
        return True

    def _get_alexa_search_text(self, song: dict[str, Any]) -> str:
        """Generate Alexa-compatible search text from song metadata."""
        artist = song.get("artist", "")
        title = song.get("title", "")

        if artist and title:
            return f"{title} by {artist}"
        if title:
            return title
        _LOGGER.warning("Song missing artist/title for Alexa search")
        return "unknown song"

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
        # Extract track ID from URI — Issue #422: platform-aware parsing
        if uri.startswith("spotify:"):
            track_id = uri.split(":")[-1]
        else:
            track_id = uri

        # Get initial state for comparison
        initial_state = self._hass.states.get(self._entity_id)
        initial_title = (
            initial_state.attributes.get("media_title") if initial_state else None
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
            self._record_error("MEDIA_PLAYER_ERROR", f"Failed to stop: {err}")
            return False

    async def play(self) -> bool:
        """
        Resume playback (e.g. after intro pause).

        Returns:
            True if successful, False otherwise

        """
        try:
            await self._hass.services.async_call(
                "media_player",
                "media_play",
                {"entity_id": self._entity_id},
            )
            return True  # noqa: TRY300
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to resume playback: %s", err)  # noqa: TRY400
            self._record_error("MEDIA_PLAYER_ERROR", f"Failed to resume: {err}")
            return False

    async def pause(self) -> bool:
        """
        Pause playback (e.g. for intro mode stop).

        Returns:
            True if successful, False otherwise

        """
        try:
            await self._hass.services.async_call(
                "media_player",
                "media_pause",
                {"entity_id": self._entity_id},
            )
            return True  # noqa: TRY300
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to pause playback: %s", err)  # noqa: TRY400
            self._record_error("MEDIA_PLAYER_ERROR", f"Failed to pause: {err}")
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
            self._record_error("MEDIA_PLAYER_ERROR", f"Failed to set volume: {err}")
            return False

    async def seek_forward(self, seconds: int) -> bool:
        """Seek media forward by given seconds (#498).

        Reads current position from HA state and seeks to position + seconds.
        """
        try:
            state = self._hass.states.get(self._entity_id)
            if not state:
                return False
            current_pos = state.attributes.get("media_position", 0) or 0
            # Adjust for stale cached position — HA only updates
            # media_position at media_position_updated_at
            updated_at = state.attributes.get("media_position_updated_at")
            if updated_at:
                if isinstance(updated_at, str):
                    updated_at = datetime.fromisoformat(updated_at)
                elapsed = (datetime.now(timezone.utc) - updated_at).total_seconds()
                if elapsed > 0:
                    current_pos += elapsed
            new_pos = current_pos + seconds
            await self._hass.services.async_call(
                "media_player",
                "media_seek",
                {
                    "entity_id": self._entity_id,
                    "seek_position": new_pos,
                },
            )
            return True  # noqa: TRY300
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("Failed to seek media: %s", err)  # noqa: TRY400
            self._record_error("MEDIA_PLAYER_ERROR", f"Failed to seek: {err}")
            return False

    def is_available(self) -> bool:
        """
        Check if media player is available.

        Returns:
            True if media player is available

        """
        state = self._hass.states.get(self._entity_id)
        return state is not None and state.state != "unavailable"

    async def verify_responsive(self) -> tuple[bool, str]:
        """
        Verify media player is actually responsive (pre-flight check).

        Sends a lightweight command to wake up the speaker and verify
        it responds within PREFLIGHT_TIMEOUT seconds.
        After first successful verification, subsequent calls are cached
        to avoid repeated blocking waits during a game session (#179).

        Returns:
            Tuple of (success, error_detail) - error_detail is empty on success

        """
        # Skip if already verified this session (#179)
        if self._preflight_verified:
            _LOGGER.debug(
                "Media player %s already verified, skipping preflight", self._entity_id
            )
            return True, ""

        # First check basic availability
        state = self._hass.states.get(self._entity_id)
        if not state:
            msg = f"Entity {self._entity_id} not found"
            _LOGGER.warning(msg)
            return False, msg

        if state.state == "unavailable":
            msg = f"Media player is unavailable (state: {state.state})"
            _LOGGER.warning("Media player %s: %s", self._entity_id, msg)
            return False, msg

        try:
            # Use volume_set with current volume as a lightweight ping
            # This wakes up sleeping speakers without changing anything
            current_volume = self.get_volume()

            async with async_timeout(PREFLIGHT_TIMEOUT):
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
            self._preflight_verified = True
            return True, ""
        except TimeoutError:
            msg = f"Timeout after {PREFLIGHT_TIMEOUT}s - speaker may be sleeping or offline"
            _LOGGER.warning(
                "Media player %s not responsive: %s",
                self._entity_id,
                msg,
            )
            return False, msg
        except Exception as err:  # noqa: BLE001
            msg = str(err)
            _LOGGER.warning("Media player %s not responsive: %s", self._entity_id, msg)
            return False, msg


async def async_get_media_players(hass: HomeAssistant) -> list[dict[str, Any]]:
    """
    Get all available media player entities with platform and capability info.

    Filters out unsupported platforms (raw Cast devices without Music Assistant).

    Returns:
        List of media player dicts with entity_id, friendly_name, state,
        platform, supports_spotify, supports_apple_music, playback_method,
        warning, caveat fields.

    """
    # Late import: homeassistant.helpers.entity_registry is not available in
    # the test environment without a full HA setup, so we import it here to
    # avoid ImportError during unit tests.  (noqa: PLC0415)
    from homeassistant.helpers import entity_registry as er  # noqa: PLC0415

    # Get entity registry to check which platform created each entity
    ent_reg = er.async_get(hass)

    media_players = []
    for state in hass.states.async_all("media_player"):
        entity_entry = ent_reg.async_get(state.entity_id)
        platform = entity_entry.platform if entity_entry else "unknown"

        # Determine capabilities based on platform
        capabilities = get_platform_capabilities(platform)

        # Skip unsupported platforms (Cast without MA)
        if not capabilities.get("supported"):
            _LOGGER.debug(
                "Skipping unsupported player: %s (platform=%s, reason=%s)",
                state.entity_id,
                platform,
                capabilities.get("reason", "unknown"),
            )
            continue

        media_players.append(
            {
                "entity_id": state.entity_id,
                "friendly_name": state.attributes.get("friendly_name", state.entity_id),
                "state": state.state,
                "platform": platform,
                "supports_spotify": capabilities.get("spotify", False),
                "supports_apple_music": capabilities.get("apple_music", False),
                "supports_youtube_music": capabilities.get("youtube_music", False),
                "supports_tidal": capabilities.get("tidal", False),
                "supports_deezer": capabilities.get("deezer", False),
                "playback_method": capabilities.get("method", "uri"),
                "warning": capabilities.get("warning"),
                "caveat": capabilities.get("caveat"),
            }
        )

    _LOGGER.debug("Found %d compatible media players", len(media_players))
    return media_players
