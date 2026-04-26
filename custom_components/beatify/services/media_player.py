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

from homeassistant.exceptions import HomeAssistantError, ServiceNotFound
from homeassistant.helpers.event import async_track_state_change_event

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

# Music Assistant playback timeout. Higher than PLAYBACK_TIMEOUT because MA
# routes through the speaker's own buffering layer and AirPlay (HomePods,
# Denon AirPlay, some MA-wrapped Sonos setups) can take 10-12s to acknowledge
# a new track on the first round. #777 showed 8s was too aggressive — rounds
# advanced before the track had actually swapped on the speaker.
MA_PLAYBACK_TIMEOUT = 15.0

# Timeout for waiting for metadata to update after playing (seconds)
METADATA_WAIT_TIMEOUT = 5.0

# Candidate URI fields on a song, in default fallback order for MA (#768).
# Primary always comes from `_resolved_uri`; these are the alternates we walk
# when the user's selected provider isn't configured in Music Assistant.
_URI_FIELDS: tuple[str, ...] = (
    "uri_spotify",
    "uri",
    "uri_apple_music",
    "uri_youtube_music",
    "uri_tidal",
    "uri_deezer",
)


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
        # Which URI field last succeeded against MA — used to reorder the
        # candidate list so subsequent songs don't pay the primary-attempt
        # timeout on every round (#768).
        self._ma_preferred_uri_field: str | None = None

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
        except (HomeAssistantError, ServiceNotFound, ConnectionError, OSError) as err:  # noqa: BLE001
            _LOGGER.error("Playback failed for %s: %s", uri, err)  # noqa: TRY400
            self._record_error("PLAYBACK_FAILURE", f"Failed to play {uri}: {err}")
            return False

    @staticmethod
    def _convert_uri_for_ma(uri: str) -> str:
        """
        Convert Beatify-internal URIs to formats Music Assistant understands.

        Beatify playlists store URIs in internal formats:
        - applemusic://track/<id>  → apple_music://track/<id>  (MA native, #772)
        - deezer://track/<id>      → unchanged (MA native, #797)
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
            # MA's Deezer provider has domain "deezer". The previous
            # https://www.deezer.com/track/<id> form was being routed to the
            # "builtin" provider via MA's generic http(s):// branch — and
            # builtin doesn't know Deezer, so playback failed with
            # "No playable items found". Pass through the native form. (#797)
            return uri

        if uri.startswith("applemusic://track/"):
            # MA's Apple Music provider has domain "apple_music". Use MA's native
            # provider-URI form; the short "music.apple.com/song/<id>" URL fails
            # MA's parser (needs storefront+slug, 6+ path parts). (#772)
            track_id = uri.removeprefix("applemusic://track/")
            return f"apple_music://track/{track_id}"

        if uri.startswith("tidal://track/"):
            track_id = uri.removeprefix("tidal://track/")
            return f"https://tidal.com/browse/track/{track_id}"

        if uri.startswith("https://music.youtube.com/watch?v="):
            track_id = uri.removeprefix("https://music.youtube.com/watch?v=")
            return f"ytmusic://track/{track_id}"

        # spotify:track:<id> and https:// URLs are passed through unchanged
        return uri

    def _get_ma_uri_candidates(
        self, song: dict[str, Any]
    ) -> list[tuple[str | None, str]]:
        """
        Build the ordered list of MA-ready URIs to try for this song (#768).

        Order: previously-successful field (if any) first, then the user's
        selected URI (`_resolved_uri`), then every other `uri_*` on the song.
        URIs are converted for MA and deduped by their converted form.

        Returns:
            List of `(field_name, converted_uri)`. `field_name` is `None` for
            the `_resolved_uri` entry, a `uri_*` field name otherwise.

        """
        seen: set[str] = set()
        candidates: list[tuple[str | None, str]] = []

        def _add(field: str | None, raw: str | None) -> None:
            if not raw:
                return
            converted = self._convert_uri_for_ma(raw)
            if not converted or converted in seen:
                return
            seen.add(converted)
            candidates.append((field, converted))

        # Learned preference — if a specific field worked last time, try it
        # first so Apple-Music-only setups stop paying the Spotify timeout.
        if self._ma_preferred_uri_field:
            _add(self._ma_preferred_uri_field, song.get(self._ma_preferred_uri_field))

        # Primary: the URI Beatify picked based on the user's selected provider.
        _add(None, song.get("_resolved_uri"))

        # Remaining alternates.
        for field in _URI_FIELDS:
            if field != self._ma_preferred_uri_field:
                _add(field, song.get(field))

        return candidates

    async def _play_via_music_assistant(self, song: dict[str, Any]) -> bool:
        """
        Play via Music Assistant, falling back through alternate-provider URIs (#768).

        Without this fallback, users whose MA has e.g. only Apple Music see
        `Could not resolve spotify:track:... to playable media item` on every
        round. We try the user-selected URI first, then walk the other URIs
        present on the track, and remember the first field that succeeds so
        subsequent songs start with the right one.
        """
        candidates = self._get_ma_uri_candidates(song)
        if not candidates:
            _LOGGER.error(
                "MA playback: no URIs for %s - %s",
                song.get("artist"),
                song.get("title"),
            )
            return False

        expected_title = song.get("title") or ""
        if not expected_title:
            _LOGGER.warning(
                "MA playback: no expected title — skipping title verification"
            )

        for idx, (field, uri) in enumerate(candidates):
            if idx > 0:
                _LOGGER.info(
                    "MA fallback %d/%d: trying %s (prior URI did not resolve) (#768)",
                    idx + 1,
                    len(candidates),
                    uri,
                )
            success = await self._try_ma_play(uri, expected_title)
            if success:
                if field and field != self._ma_preferred_uri_field:
                    _LOGGER.debug("MA preferred URI field now: %s (#768)", field)
                    self._ma_preferred_uri_field = field
                return True

        _LOGGER.error(
            "MA playback: all %d URI candidate(s) failed for %s - %s (#768)",
            len(candidates),
            song.get("artist"),
            song.get("title"),
        )
        return False

    async def _try_ma_play(self, uri: str, expected_title: str) -> bool:
        """
        Attempt a single MA `play_media` call and wait for playback confirmation.

        Returns False on hard failure (speaker idle/unavailable, or the track
        clearly never swapped on the speaker) so the caller can try the next
        URI. Returns True both when playback is confirmed AND when the speaker
        is showing ambiguous-but-changing state (MA may still be buffering —
        preserving the #345 tolerance so we don't chase flaky retries).
        """
        _LOGGER.debug("MA playback: %s on %s", uri, self._entity_id)

        # Snapshot speaker state before the call — we need both fields to
        # distinguish #345 slow-buffer (one of them changed during the wait)
        # from #777 silent failure (neither changed, speaker still on prior
        # track).
        state_before = self._hass.states.get(self._entity_id)
        if state_before is not None:
            title_before = state_before.attributes.get("media_title", "")
            position_updated_before = state_before.attributes.get(
                "media_position_updated_at"
            )
        else:
            title_before = ""
            position_updated_before = None

        # Fire-and-forget the service call — blocking=True hangs on MA+YTMusic
        await self._hass.services.async_call(
            "music_assistant",
            "play_media",
            {"media_id": uri, "media_type": "track"},
            target={"entity_id": self._entity_id},
            blocking=False,
        )

        # Wait for the EXPECTED song to actually play on the speaker:
        # - media_title contains expected title (the strongest single signal —
        #   speaker explicitly identifies our requested track)
        # - media_position_updated_at changed (MA is actively reporting state)
        #
        # We used to also require media_position >= 1 here as a guard against
        # MA reporting `state=playing` while a track was only queued. In
        # practice that case shows itself by `media_position_updated_at`
        # *not* changing — the queued track's position never updates. So
        # `position_fresh` already filters it out, and the position-value
        # check was needlessly delaying confirmation.
        #
        # Ziigmund84 reported (#803) on cold MA start the speaker shows
        # state=playing + correct title within seconds, but media_position
        # lags at 0 for 10-15s. Old fast-path didn't fire; user heard music
        # while UI sat in REVEAL waiting for the timeout.
        expected_lower = expected_title.lower()

        confirmed = asyncio.Event()
        start_time = asyncio.get_event_loop().time()

        def _check_state(state) -> bool:
            """Return True if the state confirms expected playback."""
            if not state or state.state != "playing":
                return False
            try:
                current_title = state.attributes.get("media_title", "")
                position_updated = state.attributes.get("media_position_updated_at")

                position_fresh = position_updated != position_updated_before
                title_matches = (not expected_lower) or (
                    expected_lower in current_title.lower() if current_title else False
                )
                return title_matches and position_fresh
            except (AttributeError, KeyError):
                return False

        def _state_changed(ev):
            new_state = ev.data.get("new_state")
            if _check_state(new_state):
                confirmed.set()

        unsub = async_track_state_change_event(
            self._hass, [self._entity_id], _state_changed
        )
        try:
            # Check current state first — may already be playing
            current = self._hass.states.get(self._entity_id)
            if _check_state(current):
                elapsed = asyncio.get_event_loop().time() - start_time
                _LOGGER.debug(
                    "MA playback confirmed after %.1fs: %s (pos=%.1f)",
                    elapsed,
                    current.attributes.get("media_title", ""),
                    current.attributes.get("media_position", 0),
                )
                return True

            await asyncio.wait_for(confirmed.wait(), timeout=MA_PLAYBACK_TIMEOUT)
            elapsed = asyncio.get_event_loop().time() - start_time
            final = self._hass.states.get(self._entity_id)
            _LOGGER.debug(
                "MA playback confirmed after %.1fs: %s (pos=%.1f)",
                elapsed,
                final.attributes.get("media_title", "") if final else "?",
                final.attributes.get("media_position", 0) if final else 0,
            )
            return True
        except asyncio.TimeoutError:
            pass
        finally:
            unsub()

        current_state = self._hass.states.get(self._entity_id)
        speaker_state = current_state.state if current_state else "unknown"

        # Hard failure: speaker is idle/unavailable/off — song won't play
        if speaker_state in ("idle", "unavailable", "off", "unknown"):
            _LOGGER.error(
                "MA playback failed after %.1fs for %s (state: %s)",
                MA_PLAYBACK_TIMEOUT,
                uri,
                speaker_state,
            )
            return False

        # Hard failure: speaker title did not advance. If the title field is
        # identical to what it was before we called play_media, the new track
        # never started on the speaker — even if media_position_updated_at
        # changed (that just means the *prior* track is still ticking).
        #
        # #777 originally caught only "title unchanged AND position unchanged"
        # (everything frozen), but #795 surfaced the more common pattern:
        # the prior track keeps playing, position advances, and the #345
        # tolerance below would falsely return True. Levtos's playthrough
        # had the speaker stuck on 'Sugar, Sugar' then 'Lazy Sunday (Mono)'
        # for multiple rounds while UI advanced into "guess the year of
        # SongX" with no actual SongX audio.
        #
        # Title-must-advance is the right invariant: if a new track really
        # started, the title field must eventually become *something*
        # different. Position alone is not proof of a new track.
        title_after = (
            current_state.attributes.get("media_title", "") if current_state else ""
        )
        position_updated_after = (
            current_state.attributes.get("media_position_updated_at")
            if current_state
            else None
        )
        title_advanced = title_after != title_before
        if not title_advanced:
            position_changed = position_updated_after != position_updated_before
            _LOGGER.error(
                "MA playback failed after %.1fs for %s — speaker still on "
                "prior track %r (position timestamp %s); skipping (#795, was #777)",
                MA_PLAYBACK_TIMEOUT,
                uri,
                title_before,
                "advanced — prior track still playing"
                if position_changed
                else "also unchanged",
            )
            # #801: Hard-stop the speaker so the prior track doesn't keep
            # playing while the fallback cascade tries the next URI. Without
            # this, Levtos's setup heard 'Kill Bill' continuing for multiple
            # rounds while the UI advanced — strict-detection was rejecting
            # candidates correctly but nobody was telling the speaker to
            # actually stop. Best-effort: failure here doesn't change the
            # outcome (we're already returning False).
            try:
                await self._hass.services.async_call(
                    "media_player",
                    "media_stop",
                    {"entity_id": self._entity_id},
                    blocking=False,
                )
            except (HomeAssistantError, ServiceNotFound, ConnectionError, OSError):
                _LOGGER.debug(
                    "media_stop call after stale-title detect failed for %s",
                    self._entity_id,
                )
            return False

        # #345 slow-buffer tolerance, narrowed to "title genuinely changed":
        # title is now different from what it was before the call, so MA is
        # making progress on *some* new track. We still don't require the
        # title to match expected_title (AirPlay sometimes delivers
        # remasters/alternates with mismatched-but-valid titles), but we do
        # require title evidence of forward motion. Returning False here
        # would re-trigger the race condition #345 was originally filed for.
        _LOGGER.warning(
            "MA playback not confirmed after %.1fs for %s (state: %s). "
            "Title moved %r → %r. Continuing anyway — MA may still be "
            "buffering. (#345)",
            MA_PLAYBACK_TIMEOUT,
            uri,
            speaker_state,
            title_before,
            title_after,
        )
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

        Listens for state changes until media_content_id contains the track ID
        from the URI, or timeout is reached.

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

        matched = asyncio.Event()
        matched_metadata: dict[str, Any] = {}
        start_time = asyncio.get_event_loop().time()

        def _check_state(state) -> dict[str, Any] | None:
            """Return extracted metadata if state matches, else None."""
            if not state:
                return None
            # Check if media_content_id contains our track ID
            content_id = state.attributes.get("media_content_id", "")
            if track_id in content_id:
                return self._extract_metadata(state)
            # Also check if title changed (fallback)
            current_title = state.attributes.get("media_title")
            if current_title and current_title != initial_title:
                return self._extract_metadata(state)
            return None

        def _state_changed(ev):
            new_state = ev.data.get("new_state")
            result = _check_state(new_state)
            if result is not None:
                matched_metadata.update(result)
                matched.set()

        unsub = async_track_state_change_event(
            self._hass, [self._entity_id], _state_changed
        )
        try:
            # Check current state first — metadata may already be updated
            current = self._hass.states.get(self._entity_id)
            result = _check_state(current)
            if result is not None:
                elapsed = asyncio.get_event_loop().time() - start_time
                _LOGGER.debug(
                    "Metadata updated after %.1fs (immediate check)",
                    elapsed,
                )
                return result

            await asyncio.wait_for(matched.wait(), timeout=METADATA_WAIT_TIMEOUT)
            elapsed = asyncio.get_event_loop().time() - start_time
            current_state = self._hass.states.get(self._entity_id)
            content_id = (
                current_state.attributes.get("media_content_id", "")
                if current_state
                else ""
            )
            reason = "matched track ID" if track_id in content_id else "title changed"
            _LOGGER.debug(
                "Metadata updated after %.1fs (%s)",
                elapsed,
                reason,
            )
            return matched_metadata
        except asyncio.TimeoutError:
            _LOGGER.warning(
                "Metadata not updated within %.1fs, using current state",
                METADATA_WAIT_TIMEOUT,
            )
            return await self.get_metadata()
        finally:
            unsub()

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
        except (HomeAssistantError, ServiceNotFound) as err:  # noqa: BLE001
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
        except (HomeAssistantError, ServiceNotFound) as err:  # noqa: BLE001
            _LOGGER.error("Failed to resume playback: %s", err)  # noqa: TRY400
            self._record_error("MEDIA_PLAYER_ERROR", f"Failed to resume: {err}")
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
        except (HomeAssistantError, ServiceNotFound) as err:  # noqa: BLE001
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
        except (HomeAssistantError, ServiceNotFound, ValueError, TypeError) as err:  # noqa: BLE001
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
        except (HomeAssistantError, ServiceNotFound, ConnectionError, OSError) as err:  # noqa: BLE001
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
