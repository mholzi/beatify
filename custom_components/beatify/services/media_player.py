"""Media player discovery and control service for Beatify.

Playback itself lives in :mod:`custom_components.beatify.services.playback` —
one strategy per platform behind one dispatch point (#2636). What stays here is
what is not per-platform: discovery, the album-art proxy, analytics, volume
save/restore, the metadata wait, the pre-flight check, and the game-lifecycle
bookkeeping that decides WHEN the host's queue is captured and handed back.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import hmac
import logging
import secrets
from asyncio import timeout as async_timeout
from collections.abc import Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from homeassistant.exceptions import HomeAssistantError, ServiceNotFound
from homeassistant.helpers.event import async_track_state_change_event

from custom_components.beatify.game.playlist import get_playback_uri
from custom_components.beatify.providers import (
    normalise_platform,
    platform_provider_flags,
    supports_keys,
)

from .playback import (
    MaQueueRestorer,
    PlayerContext,
    build_strategy,
    strategy_for_platform,
    supported_platforms,
    uri_match_tokens,
)
from .playback.base import PLAYBACK_TIMEOUT

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from custom_components.beatify.analytics import AnalyticsStorage

_LOGGER = logging.getLogger(__name__)


# Why a platform Beatify knows about still cannot play. Only platforms a user
# is likely to pick need a line here; everything else gets the generic reason.
# Resolves GitHub issues #38 (Nest Audio) and #39 (Google TV Streamer).
_UNSUPPORTED_PLATFORM_REASONS: dict[str, str] = {
    "cast": "Cast devices require Music Assistant",
}

_UNKNOWN_PLATFORM_REASON = "Unknown player type"


def _capabilities_for(platform: str) -> dict[str, Any]:
    """Build one platform's capability row from the two registries (#2713).

    The provider columns come from ``providers.py`` — one entry per provider,
    for every platform, so the table can never fall a provider behind again.
    The platform half (is it supported at all, does it play by URI or by voice,
    what has to be set up first) comes from the strategy that implements it,
    which is what #2678 asked for: ``build_strategy`` and this table no longer
    answer "which platforms exist" separately.
    """
    strategy = strategy_for_platform(platform)
    if strategy is None:
        return {
            "supported": False,
            "reason": _UNSUPPORTED_PLATFORM_REASONS.get(
                platform, _UNKNOWN_PLATFORM_REASON
            ),
        }
    row: dict[str, Any] = {
        "supported": True,
        **platform_provider_flags(platform),
        "method": strategy.playback_method,
        "warning": strategy.setup_warning,
    }
    if strategy.setup_caveat is not None:
        row["caveat"] = strategy.setup_caveat
    return row


#: Platform capability definitions for multi-platform routing. Derived, not
#: written: see :func:`_capabilities_for`. Kept as a module-level mapping
#: because callers read it directly.
PLATFORM_CAPABILITIES: dict[str, dict[str, Any]] = {
    platform: _capabilities_for(platform)
    for platform in (*supported_platforms(), *_UNSUPPORTED_PLATFORM_REASONS)
    # "alexa" is an alias of "alexa_media"; normalise_platform folds it.
    if normalise_platform(platform) == platform
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
    platform = normalise_platform(platform)

    return PLATFORM_CAPABILITIES.get(
        platform,
        {"supported": False, "reason": _UNKNOWN_PLATFORM_REASON},
    )


def resolve_entity_platform(hass: HomeAssistant, entity_id: str) -> str:
    """The integration that owns ``entity_id``, straight from the entity registry.

    #2693: the platform is what :func:`~.playback.build_strategy` dispatches on,
    so it must describe the speaker that is actually about to play — not
    whatever was written next to a previous selection. Reading it from the
    registry at the moment the speaker is used makes it impossible for the two
    to disagree.

    Returns ``"unknown"`` when the entity has no registry entry (a YAML-only
    player, a test double) or when the registry is unreadable; every caller
    treats that the same way it always has.
    """
    # Late import: mirrors async_get_media_players — entity_registry is not
    # importable in the unit-test env without a full HA setup. (noqa: PLC0415)
    from homeassistant.helpers import entity_registry as er

    try:
        entry = er.async_get(hass).async_get(entity_id)
    except Exception as err:  # noqa: BLE001 — a registry read must never abort a game
        _LOGGER.warning(
            "Entity registry lookup for %s raised %s; platform unknown",
            entity_id,
            err,
        )
        return "unknown"
    return entry.platform if entry else "unknown"


# Timeout for pre-flight connectivity check (seconds)
PREFLIGHT_TIMEOUT = 3.0
# Timeout for waiting for metadata to update after playing (seconds)
# Wait up to 2s for MA to push fresh metadata (album art, etc.) after a
# playback transition. Reduced from 5s — that earlier value was the
# dominant secondary cause of "UI lag after pressing next" (after the 15s
# playback-confirm wait, addressed by the title_advanced fast-path).
# When this times out, Beatify falls back to the playlist's existing
# album_art / title / artist fields; the visible cost is briefly stale
# album art at the top of a round, which the speaker corrects on its own
# state callback within a few seconds.
METADATA_WAIT_TIMEOUT = 2.0

# After detecting that the new song has started (content_id / title match),
# wait up to this many additional seconds for entity_picture to also update.
# entity_picture reliably lags behind content_id and media_title on most
# platforms (Spotify, Music Assistant, etc.) — reading it at the moment of
# content_id/title match returns the previous song's artwork (issue #1260).
# If entity_picture hasn't changed within this window (same-album or platform
# doesn't update it) we fall back to the current state, which is correct.
ENTITY_PICTURE_WAIT = 1.0

# Same-origin placeholder shown when a player reports no artwork. During a
# track transition entity_picture can briefly clear to None or flip to this
# placeholder before the real cover loads — Phase 2 must NOT treat that
# transient as "the new art has arrived" (issue #1260 follow-up).
NO_ARTWORK_PLACEHOLDER = "/beatify/static/img/no-artwork.svg"


# Process-global key used to sign the absolute URLs that the album-art proxy
# is allowed to fetch (#1356). It is minted fresh on every HA start: only URLs
# that *this* integration produced via ``proxy_album_art`` carry a valid
# signature, which is what stops AlbumArtView from being an open SSRF proxy. A
# restart simply invalidates previously-signed URLs — clients 403 once and pick
# up the freshly-signed URL from the next state broadcast.
_ALBUM_ART_SIGNING_KEY = secrets.token_bytes(32)


def _album_art_signature(url: str) -> str:
    """Return the hex HMAC-SHA256 signature for an album-art proxy URL (#1356)."""
    return hmac.new(
        _ALBUM_ART_SIGNING_KEY, url.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def album_art_signature_is_valid(url: str, signature: str) -> bool:
    """Verify, in constant time, that ``signature`` matches ``url`` (#1356)."""
    if not signature:
        return False
    return hmac.compare_digest(_album_art_signature(url), signature)


def proxy_album_art(url: str) -> str:
    """Route an absolute album-art URL through the same-origin proxy (#933).

    Music Assistant exposes ``entity_picture`` as an absolute URL on the MA
    server's LAN address (e.g. ``http://192.168.x.x:8095/imageproxy?...``). A
    player who joined via the nabu.casa remote URL is on a public origin, so
    the browser's Private Network Access policy blocks the LAN request and
    album art never loads. Wrapping such URLs in ``/beatify/api/albumart`` lets
    the HA server fetch the image (it can reach the LAN) and re-serve it
    same-origin.

    The wrapped URL carries an HMAC signature (#1356) so the proxy only ever
    fetches URLs the integration itself produced — without it the endpoint
    would be an unauthenticated server-side request forge.

    Relative URLs — HA's own signed media-player proxy path, the
    ``no-artwork.svg`` fallback — are already same-origin and pass through
    unchanged.
    """
    if url and url.startswith(("http://", "https://")):
        return (
            "/beatify/api/albumart?url="
            + quote(url, safe="")
            + "&sig="
            + _album_art_signature(url)
        )
    return url


class MediaPlayerService:
    """Service for controlling HA media player."""

    def __init__(
        self,
        hass: HomeAssistant,
        entity_id: str,
        platform: str = "unknown",
        provider: str = "spotify",
        inherited_states: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        """
        Initialize with HomeAssistant and entity_id.

        Args:
            hass: Home Assistant instance
            entity_id: Media player entity ID
            platform: Platform identifier (music_assistant, sonos, alexa_media, etc.)
            provider: Music provider (spotify or apple_music)
            inherited_states: what earlier speakers of this game still owe their
                owners, as ``{entity_id: {"volume": …, "queue": …}}`` (#2143).
                A speaker switch throws this service away and builds a new one;
                without carrying the snapshots the game would silently forget
                to hand the previous speaker back.

        """
        self._hass = hass
        self._entity_id = entity_id
        self._analytics: AnalyticsStorage | None = None
        self._preflight_verified: bool = False

        # #2636: everything platform-specific now lives behind one interface.
        # The context is the speaker; the strategy is the platform; the
        # dispatch happened once, in `build_strategy`, instead of in an
        # `if self._platform ==` chain spread over five methods.
        #
        # `save_queue` is handed over as a callback rather than called from
        # here because only the strategy knows the moment the host's queue is
        # about to be replaced (#2143) — while the bookkeeping around it
        # (capture once, hand back at game end, survive a speaker switch) is
        # game lifecycle and stays below.
        self._context = PlayerContext(
            hass,
            entity_id,
            platform=platform,
            provider=provider,
            save_queue=self.save_queue,
        )
        self._strategy = build_strategy(self._context)
        self._restorer = MaQueueRestorer(hass)

        # #1516: the speaker's volume as it was BEFORE Beatify first changed it
        # this game. Captured once (via save_volume) on the first in-game volume
        # change so the host's original listening level can be handed back at
        # game end. None = nothing to restore (Beatify never touched the volume).
        self._saved_volume: float | None = None

        # #2143: what the speaker was playing before Beatify claimed the queue.
        # The MA strategy sends `enqueue: "replace"`, which wipes whatever the
        # host had queued — in EVERY round, for every Music Assistant user,
        # whether or not they use Crate Digger. Captured once per game (like
        # `_saved_volume`) and handed back at game end.
        #
        # Three shapes, deliberately distinct:
        #   None — not captured yet (or already restored)
        #   {}   — captured, but the speaker was idle: nothing to hand back
        #   {…}  — the track, its position, shuffle and repeat mode
        #
        # What CANNOT be captured: the queue behind the current track. MA's
        # `get_queue` reports `items` as a COUNT, not a list, and exposes only
        # `current_item` / `next_item` — measured against a live queue on
        # 2026-08-13. Restoring "the first entry with replace, the rest with
        # add" (the original plan in #2143) is therefore not implementable.
        self._saved_queue: dict[str, Any] | None = None

        # Speakers this game already touched and then switched away from —
        # {entity_id: {"volume": …, "queue": …}}. Our OWN entity's snapshot is
        # adopted into the fields above instead of living here, so a switch
        # back to a speaker does not re-capture an already-Beatify-altered
        # level as if it were the host's original.
        self._inherited_states: dict[str, dict[str, Any]] = {
            eid: dict(snap) for eid, snap in (inherited_states or {}).items()
        }
        own_snapshot = self._inherited_states.pop(entity_id, None)
        if own_snapshot:
            self._saved_volume = own_snapshot.get("volume")
            self._saved_queue = own_snapshot.get("queue")

    @property
    def _platform(self) -> str:
        """The speaker's platform. Lives on the context so the strategy and the
        shell can never disagree about which speaker this is."""
        return self._context.platform

    @property
    def _provider(self) -> str:
        """The music provider the wizard settled on."""
        return self._context.provider

    @property
    def last_failure_reason(self) -> str | None:
        """Why the most recent play failed — set by whichever strategy ran.

        #808 follow-up: classify the most recent failure mode so the caller
        (``game/state.py:start_round``) can decide whether to count this
        against MAX_SONG_RETRIES (real failure) or skip silently (track
        unavailable in the user's catalog/storefront).

        Values:
          None          — last call succeeded or hasn't been called yet
          "unavailable" — MA accepted the URI but speaker stayed on the prior
                          track. Almost always means the track ID isn't in the
                          user's Apple Music storefront, or MA's provider needs
                          re-authentication for this track. Skipping silently
                          lets the game continue with whatever subset IS
                          playable.
          "error"       — speaker idle/off/unavailable, or hard speaker
                          problem. Counts toward MAX_SONG_RETRIES so the game
                          pauses on systemic issues (offline speaker, broken
                          provider auth across the board).
        """
        return self._context.last_failure_reason

    @last_failure_reason.setter
    def last_failure_reason(self, value: str | None) -> None:
        self._context.last_failure_reason = value

    @property
    def last_attempted_uri(self) -> str | None:
        """The URI actually handed to the player for the most recent attempt.

        #1927 follow-up: `state_lifecycle` used to log `song["uri"]` on a
        playback failure — the song's Spotify base field — so an Apple Music
        attempt was reported as `spotify:track:…` and every reader was sent
        hunting in the wrong provider. None until the first attempt.
        """
        return self._context.last_attempted_uri

    @last_attempted_uri.setter
    def last_attempted_uri(self, value: str | None) -> None:
        self._context.last_attempted_uri = value

    def snapshot_saved_states(self) -> dict[str, dict[str, Any]]:
        """Everything this game still owes the user's speakers (#1516/#2143).

        Mirrors ``PartyLightsService.snapshot_saved_states``: a mid-game
        speaker switch discards this service, and the caller hands the result
        of this method to the replacement so the promise survives the switch.
        """
        states = {eid: dict(snap) for eid, snap in self._inherited_states.items()}
        own: dict[str, Any] = {}
        if self._saved_volume is not None:
            own["volume"] = self._saved_volume
        if self._saved_queue:
            own["queue"] = dict(self._saved_queue)
        if own:
            states[self._entity_id] = own
        return states

    def save_volume(self) -> None:
        """Remember the speaker's current volume for later restore (#1516).

        Idempotent: only the FIRST call per game captures a value. Subsequent
        calls are no-ops so that repeated in-game volume adjustments don't
        overwrite the genuine pre-game level with an already-Beatify-altered
        one. ``restore_volume`` clears the capture, so the next game re-captures
        fresh.
        """
        if self._saved_volume is None:
            self._saved_volume = self.get_volume()

    async def restore_volume(self) -> bool:
        """Restore the volume captured by :meth:`save_volume` (#1516).

        Also hands back every speaker this game switched AWAY from (#2143) —
        each at its own captured level, never at this speaker's. Restoring the
        old speaker's volume onto the new one would be a different bug.

        Returns:
            True if at least one saved volume was applied, False if there was
            nothing to restore (Beatify never changed any volume this game).
        """
        applied = False
        for entity_id, snapshot in list(self._inherited_states.items()):
            level = snapshot.pop("volume", None)
            if level is None:
                continue
            if await self._set_volume_on(entity_id, level):
                applied = True
        if self._saved_volume is None:
            return applied
        level = self._saved_volume
        # Clear BEFORE the await so a re-entrant call can't double-restore, and
        # so the next game starts from a clean (uncaptured) slate.
        self._saved_volume = None
        return await self._set_volume_on(self._entity_id, level) or applied

    async def save_queue(self) -> None:
        """Remember what the speaker was playing before Beatify took it (#2143).

        Idempotent in the same way as :meth:`save_volume`: only the FIRST call
        per game captures. Round two would otherwise "capture" Beatify's own
        track and hand the host that instead of their music.

        WHAT is remembered is the platform's business — only Music Assistant
        can report it, and only its strategy overrides
        :meth:`~.playback.base.PlaybackStrategy.capture_queue`. WHEN it is
        remembered is this shell's, which is why the guard below stayed here
        (#2636). A strategy that reports None (every platform but MA, and a
        platform Beatify cannot play on at all) leaves ``_saved_queue`` unset,
        so ``restore_queue`` hands nothing back — exactly as before.
        """
        if self._saved_queue is not None or self._strategy is None:
            return
        snapshot = await self._strategy.capture_queue()
        if snapshot is not None:
            self._saved_queue = snapshot

    async def restore_queue(self) -> bool:
        """Hand the speaker back what it was playing before the game (#2143).

        Restores this speaker and every speaker the game switched away from.
        The track comes back PAUSED at its old position: the host ended the
        game, so starting their music unasked would be its own surprise.

        Only the track that was playing returns. What sat behind it in the
        queue is gone — MA's ``get_queue`` never exposed it (see the
        ``_saved_queue`` comment in ``__init__``).

        Returns:
            True if at least one speaker got something back.
        """
        restored = False
        for entity_id, snapshot in list(self._inherited_states.items()):
            queue = snapshot.pop("queue", None)
            if await self._restorer.restore_on(entity_id, queue):
                restored = True
        queue = self._saved_queue
        # Clear BEFORE the awaits so a re-entrant call can't double-restore.
        self._saved_queue = None
        return await self._restorer.restore_on(self._entity_id, queue) or restored

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

        The platform was resolved once, at construction, into a
        :class:`~.playback.base.PlaybackStrategy` (#2636):

        - music_assistant: Uses music_assistant.play_media with URI
        - sonos: Uses media_player.play_media with Spotify URI
        - alexa_media: Uses media_player.play_media with text search

        What is left here is what every platform shares: the URI precondition,
        the timeout and error log lines, and the analytics record.

        Args:
            song: Song dict with _resolved_uri, artist, title keys

        Returns:
            True if playback started successfully, False otherwise

        """
        uri = get_playback_uri(song)
        # #1927 follow-up: start each song with a clean attempt record, then seed
        # it with the dispatcher's URI. The MA path overwrites it per candidate
        # (it walks several URI fields); sonos/alexa play exactly this one.
        self.last_attempted_uri = uri or None
        if not uri:
            _LOGGER.error(
                "Song has no URI to play: %s - %s",
                song.get("artist"),
                song.get("title"),
            )
            self._record_error("PLAYBACK_FAILURE", "Song has no URI")
            return False

        if self._strategy is None:
            _LOGGER.error("Unsupported platform: %s", self._platform)
            return False

        try:
            return await self._strategy.play(song)
        except (TimeoutError, asyncio.TimeoutError):
            _LOGGER.error(
                "Playback timed out after %ss for %s: %s",
                PLAYBACK_TIMEOUT,
                uri,
                song.get("title", "?"),
            )
            self._record_error("PLAYBACK_TIMEOUT", f"Timed out playing: {uri}")
            return False
        except (HomeAssistantError, ServiceNotFound, ConnectionError, OSError) as err:
            _LOGGER.error("Playback failed for %s: %s", uri, err)  # noqa: TRY400
            self._record_error("PLAYBACK_FAILURE", f"Failed to play {uri}: {err}")
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
            "album_art": proxy_album_art(
                state.attributes.get(
                    "entity_picture", "/beatify/static/img/no-artwork.svg"
                )
            ),
        }

    async def wait_for_metadata_update(self, uri: str) -> dict[str, Any]:
        """
        Wait for media player to update metadata after playing a song.

        Listens for state changes until media_content_id contains the track ID
        from the URI, or timeout is reached.

        Two-phase approach (issue #1260 — stale album art):
        Phase 1 — wait for content_id / title to match the new song.
        Phase 2 — wait up to ENTITY_PICTURE_WAIT more seconds for
                   entity_picture to also change (it reliably lags behind
                   content_id/title on Spotify, Music Assistant, etc.).
                   If entity_picture doesn't change (same-album or platform
                   doesn't update it) we fall back to the current state,
                   which is still correct for same-album art.

        Args:
            uri: The Spotify URI that was just played (e.g., spotify:track:xxx)

        Returns:
            Dict with artist, title, album_art keys

        """
        # Build the substring tokens to look for in MA's media_content_id.
        # Issue #1380: for non-Spotify providers the raw Beatify-internal URI
        # (applemusic://track/123, tidal://track/123,
        # https://music.youtube.com/watch?v=ABC) never appears in MA's
        # content_id, because MA reports its own form derived from
        # _convert_uri_for_ma (apple_music://track/123,
        # https://tidal.com/browse/track/123, ytmusic://track/ABC). Match
        # against the MA-converted URI AND the bare track ID (the last path/ID
        # segment), which is stable across both forms.
        match_tokens = uri_match_tokens(uri)

        # Get initial state for comparison
        initial_state = self._hass.states.get(self._entity_id)
        initial_title = (
            initial_state.attributes.get("media_title") if initial_state else None
        )
        initial_entity_picture = (
            initial_state.attributes.get("entity_picture") if initial_state else None
        )

        # Phase 1: song started (content_id / title match)
        song_matched = asyncio.Event()
        # Phase 2: entity_picture also changed
        art_changed = asyncio.Event()

        art_metadata: dict[str, Any] = {}
        start_time = asyncio.get_event_loop().time()

        def _song_started(state) -> bool:
            """Return True if state signals the new song has started."""
            if not state:
                return False
            content_id = state.attributes.get("media_content_id", "")
            if any(token in content_id for token in match_tokens):
                return True
            current_title = state.attributes.get("media_title")
            return bool(current_title and current_title != initial_title)

        def _is_new_art(ep) -> bool:
            """True if entity_picture is a real cover that differs from initial.

            A transient clear to None/empty or to the no-artwork placeholder
            during the track transition is NOT the new art — keep waiting for
            the real cover (issue #1260 follow-up).
            """
            if ep == initial_entity_picture:
                return False
            return bool(ep) and ep != NO_ARTWORK_PLACEHOLDER

        def _state_changed(ev):
            new_state = ev.data.get("new_state")
            if new_state is None:
                return
            if not song_matched.is_set() and _song_started(new_state):
                song_matched.set()
            # Track entity_picture change regardless — it may arrive in a
            # later event than the content_id/title change.
            if not art_changed.is_set():
                ep = new_state.attributes.get("entity_picture")
                if _is_new_art(ep):
                    art_metadata.update(self._extract_metadata(new_state))
                    art_changed.set()

        unsub = async_track_state_change_event(
            self._hass, [self._entity_id], _state_changed
        )
        try:
            # ── Phase 1: check current state / wait for song to start ──────
            current = self._hass.states.get(self._entity_id)
            if current:
                if _song_started(current):
                    song_matched.set()
                ep = current.attributes.get("entity_picture")
                if _is_new_art(ep):
                    art_metadata.update(self._extract_metadata(current))
                    art_changed.set()

            if not song_matched.is_set():
                try:
                    await asyncio.wait_for(
                        song_matched.wait(), timeout=METADATA_WAIT_TIMEOUT
                    )
                except asyncio.TimeoutError:
                    # Issue #1380: if entity_picture already advanced to a real
                    # new cover during the wait, honor that captured metadata
                    # (the #1260 two-phase freshness) instead of discarding it.
                    if art_changed.is_set():
                        _LOGGER.warning(
                            "Song match not detected within %.1fs, but new album "
                            "art arrived — using captured metadata",
                            METADATA_WAIT_TIMEOUT,
                        )
                        return art_metadata
                    _LOGGER.warning(
                        "Metadata not updated within %.1fs, using current state",
                        METADATA_WAIT_TIMEOUT,
                    )
                    return await self.get_metadata()

            elapsed = asyncio.get_event_loop().time() - start_time
            current_state = self._hass.states.get(self._entity_id)
            content_id = (
                current_state.attributes.get("media_content_id", "")
                if current_state
                else ""
            )
            reason = (
                "matched track ID"
                if any(token in content_id for token in match_tokens)
                else "title changed"
            )
            _LOGGER.debug("Song started after %.1fs (%s)", elapsed, reason)

            # ── Phase 2: wait for entity_picture to also update ───────────
            if art_changed.is_set():
                elapsed = asyncio.get_event_loop().time() - start_time
                _LOGGER.debug("Album art updated after %.1fs (same event)", elapsed)
                return art_metadata

            try:
                await asyncio.wait_for(art_changed.wait(), timeout=ENTITY_PICTURE_WAIT)
                elapsed = asyncio.get_event_loop().time() - start_time
                _LOGGER.debug("Album art updated after %.1fs total", elapsed)
                return art_metadata
            except asyncio.TimeoutError:
                # entity_picture didn't change within ENTITY_PICTURE_WAIT.
                # Either same-album art or the platform doesn't update it —
                # read the current state, which is correct in both cases.
                elapsed = asyncio.get_event_loop().time() - start_time
                _LOGGER.debug(
                    "Entity picture unchanged after %.1fs extra wait "
                    "(same album art or platform unchanged) — using current state",
                    ENTITY_PICTURE_WAIT,
                )
                return await self.get_metadata()

        finally:
            unsub()

    def _extract_metadata(self, state: Any) -> dict[str, Any]:
        """Extract metadata dict from state object."""
        return {
            "artist": state.attributes.get("media_artist", "Unknown Artist"),
            "title": state.attributes.get("media_title", "Unknown Title"),
            "album_art": proxy_album_art(
                state.attributes.get(
                    "entity_picture", "/beatify/static/img/no-artwork.svg"
                )
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
            return True
        except (HomeAssistantError, ServiceNotFound) as err:
            _LOGGER.error("Failed to stop playback: %s", err)  # noqa: TRY400
            self._record_error("MEDIA_PLAYER_ERROR", f"Failed to stop: {err}")
            return False

    async def play(self, *, blocking: bool = False) -> bool:
        """
        Resume playback (e.g. after intro pause).

        Args:
            blocking: wait for the service call to complete. The resume
                watchdog (#2710) needs this — it re-reads the player one
                second later and must not race its own kick. Everyone else
                fires and forgets, which is what the call has always done.

        Returns:
            True if successful, False otherwise

        """
        try:
            await self._hass.services.async_call(
                "media_player",
                "media_play",
                {"entity_id": self._entity_id},
                blocking=blocking,
            )
            return True
        except (HomeAssistantError, ServiceNotFound) as err:
            _LOGGER.error("Failed to resume playback: %s", err)  # noqa: TRY400
            self._record_error("MEDIA_PLAYER_ERROR", f"Failed to resume: {err}")
            return False

    async def resume_after_announcement(
        self,
        *,
        lead_seconds: float,
        should_continue: Callable[[], bool],
    ) -> None:
        """Watch the speaker through a TTS announcement and press play if it
        does not resume on its own (#2710).

        Announcements interrupt the just-started song, and some devices
        (observed: Music Assistant voice satellites) never come back — the
        player sits ``paused`` or ``idle``-with-a-title until a human presses
        play. This walks a ~20 second window after the announcement chain and
        kicks the speaker on its behalf, at most three times.

        It lives here, not in ``game/state_lifecycle.py``, because every line
        of it is a conversation with one speaker: read the state, press play,
        undo a volume ratchet. Running it from the game logic meant a second,
        analytics-free way to press play — a platform quirk fixed in
        :meth:`play` was absent from the watchdog — and made the whole path
        invisible to the injected fake from #2638.

        Args:
            lead_seconds: how long the announcements are still expected to
                occupy the speaker. The caller owns that estimate (it is the
                TTS queue's own reservation); we only wait it out and then
                kick immediately instead of spending three more ticks
                confirming what we already expect.
            should_continue: asked once per tick, BEFORE the player is read.
                False means playback stopped on purpose — the host tapped
                "stop song", or the game paused — and the watchdog must not
                undo that (#2576). Deciding after the read would still fire
                one kick on the very tick the host stopped the song.

        """
        # v0.7.22 — triggers verified on hardware via the narrating build:
        # * VA satellites stick in state='idle' after an announcement (HA
        #   never reports 'paused' even while MA's UI shows the paused track)
        #   -> sustained idle WITH a loaded title is the kick signature.
        # * 'playing' is healthy, full stop: media_position on MA entities is
        #   a snapshot+timestamp, not a live counter, so the old
        #   frozen-position stall heuristic false-positived on a perfectly
        #   playing ShieldTV. Removed.
        # v0.7.30 — ANTICIPATE instead of observe. Playback starts BEFORE the
        # announcements are fired, so every announcement interrupts the song
        # and the device has to resume. Waiting for 3 consecutive idle ticks
        # to prove that meant a 3-4s silence after "…3, 2, 1, go" (reported).

        # The level as it is BEFORE the announcements duck and restore it, so
        # the ratchet guard below can undo an upward drift.
        vol_before: float | None = None
        with contextlib.suppress(Exception):
            st_before = self._hass.states.get(self._entity_id)
            level = st_before.attributes.get("volume_level") if st_before else None
            if isinstance(level, (int, float)):
                vol_before = float(level)

        kicks = 0
        idle_streak = 0
        vol_restored = False

        if lead_seconds > 0:
            await asyncio.sleep(lead_seconds + 0.4)
            st0 = self._hass.states.get(self._entity_id)
            if st0 is not None and st0.state in ("idle", "paused"):
                kicks += 1
                _LOGGER.info(
                    "Resume watchdog: announcement window over, resuming "
                    "immediately (state=%s)",
                    st0.state,
                )
                with contextlib.suppress(Exception):
                    await self.play(blocking=True)
            elif st0 is not None and st0.state == "playing":
                # Device resumed on its own (ShieldTV behaviour) — nothing to
                # do, but keep polling as a safety net.
                pass

        for tick in range(20):
            await asyncio.sleep(1.0)
            # #2576: der Wachhund darf nur wiederbeleben, was von allein
            # stehengeblieben ist — nie etwas, das jemand absichtlich
            # angehalten hat. Der Aufrufer kennt den Unterschied, wir nicht.
            if not should_continue():
                return
            st = self._hass.states.get(self._entity_id)
            if st is None:
                _LOGGER.info("Resume watchdog: entity vanished — exit")
                return
            title = st.attributes.get("media_title")
            _LOGGER.info(
                "Resume watchdog[%02d]: state=%s title=%s",
                tick,
                st.state,
                title,
            )

            # Volume ratchet guard. Music Assistant raises the volume for an
            # announcement and restores it afterwards; on a ShieldTV feeding
            # an AV receiver the restore wrote back a HIGHER level each round,
            # so the music grew painfully loud within a few rounds. Beatify
            # itself never changes volume here, but it is the only component
            # positioned to notice — so undo an upward drift once per round,
            # inside the announcement window only, leaving the host's own
            # volume buttons alone for the rest of the round.
            if vol_before is not None and not vol_restored and tick <= 10:
                cur = st.attributes.get("volume_level")
                if isinstance(cur, (int, float)) and float(cur) > vol_before + 0.05:
                    vol_restored = True
                    _LOGGER.warning(
                        "Volume rose from %.2f to %.2f across the TTS "
                        "announcement — restoring (announcement "
                        "duck/restore ratchet)",
                        vol_before,
                        float(cur),
                    )
                    with contextlib.suppress(Exception):
                        await self._set_volume_on(
                            self._entity_id, vol_before, blocking=True
                        )
            if st.state == "idle" and title:
                idle_streak += 1
            else:
                idle_streak = 0
            # 2 ticks, not 3: the anticipatory kick above handles the normal
            # case, so this fallback should react faster to the cases it
            # misses. Satellites flap idle<->playing for SINGLE ticks during
            # healthy playback, so 2 consecutive remains the floor — and a
            # spurious media_play on a playing device is a no-op anyway.
            if st.state == "paused" or idle_streak >= 2:
                kicks += 1
                idle_streak = 0
                _LOGGER.warning(
                    "Media player %s after TTS announcement — "
                    "resuming playback (kick %d)",
                    "paused" if st.state == "paused" else "idle-stuck",
                    kicks,
                )
                try:
                    kicked = await self.play(blocking=True)
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("Resume watchdog: media_play failed: %s", err)
                    return
                if not kicked:
                    # play() has already logged it and recorded the analytics
                    # event the old inline watchdog never produced.
                    _LOGGER.warning("Resume watchdog: media_play failed — exit")
                    return
                if kicks >= 3:
                    _LOGGER.info("Resume watchdog: 3 kicks — exit")
                    return
            elif st.state == "off":
                _LOGGER.info("Resume watchdog: player off — exit")
                return
        _LOGGER.info("Resume watchdog: 20s window elapsed — exit")

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
        return await self._set_volume_on(self._entity_id, level)

    async def _set_volume_on(
        self, entity_id: str, level: float, *, blocking: bool = False
    ) -> bool:
        """Set the volume of an explicit entity.

        Split out of :meth:`set_volume` so ``restore_volume`` can hand back a
        speaker the game has since switched away from (#2143) — that one is no
        longer ``self._entity_id``. ``blocking`` exists for the same reason as
        on :meth:`play` (#2710).
        """
        try:
            await self._hass.services.async_call(
                "media_player",
                "volume_set",
                {
                    "entity_id": entity_id,
                    "volume_level": max(0.0, min(1.0, level)),
                },
                blocking=blocking,
            )
            return True
        except (HomeAssistantError, ServiceNotFound) as err:
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
            return True
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

    def get_playback_state(self) -> str | None:
        """Return the player's current state string ("playing", "paused",
        "idle", ...), or None if unavailable.

        Used by the REVEAL auto-advance (#1012) to tell when the round's
        song has finished — the player drops out of "playing" once the
        track ends.
        """
        state = self._context.state()
        return state.state if state else None

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
            # Read the *real* reported volume — NOT get_volume(), which masks
            # an unreported volume_level as a hard-coded 0.5. Writing that 0.5
            # back via volume_set would physically blast an idle speaker (the
            # very speakers this ping targets) to 50%, instead of being the
            # promised no-op (#1382).
            reported_volume = state.attributes.get("volume_level")

            async with async_timeout(PREFLIGHT_TIMEOUT):
                if reported_volume is not None:
                    # Genuine no-op ping: re-set the speaker to its own volume.
                    await self._hass.services.async_call(
                        "media_player",
                        "volume_set",
                        {
                            "entity_id": self._entity_id,
                            "volume_level": float(reported_volume),
                        },
                        blocking=True,
                    )
                else:
                    # No volume reported (sleeping/idle speaker): use a truly
                    # read-only refresh as the ping so we never change volume.
                    await self._hass.services.async_call(
                        "homeassistant",
                        "update_entity",
                        {"entity_id": self._entity_id},
                        blocking=True,
                    )
            _LOGGER.debug("Media player %s is responsive", self._entity_id)
            self._preflight_verified = True
            return True, ""
        except (TimeoutError, asyncio.TimeoutError):
            msg = f"Timeout after {PREFLIGHT_TIMEOUT}s - speaker may be sleeping or offline"
            _LOGGER.warning(
                "Media player %s not responsive: %s",
                self._entity_id,
                msg,
            )
            return False, msg
        except (HomeAssistantError, ServiceNotFound, ConnectionError, OSError) as err:
            msg = str(err)
            _LOGGER.warning("Media player %s not responsive: %s", self._entity_id, msg)
            return False, msg


def _collect_ma_twin_maps(
    ent_reg: Any,
) -> tuple[dict[str, str], dict[str, str]]:
    """Walk the entity registry ONCE and derive both Music Assistant twin maps.

    #1709: ``async_get_media_players`` and ``async_get_native_twin_remap`` used
    to iterate ``ent_reg.entities`` 3-4 times per status request to rebuild
    essentially the same data. This single pass builds them both:

    - ``ma_by_unique_id``: ``{unique_id: ma_entity_id}`` for every
      music_assistant-owned media_player (its keys are the MA unique-id set used
      to hide native twins from the picker, #1627/#1628).
    - ``native_twin_remap``: ``{native_entity_id: ma_entity_id}`` for every
      native-platform media_player that shares a unique_id with an MA twin
      (#1627 follow-up — heals stale saved selections).

    A native entity can appear before its MA twin in the registry, so natives
    are collected in the same pass and resolved against the completed MA map
    afterwards (no second full registry walk).
    """
    ma_by_unique_id: dict[str, str] = {}
    native_media_players: list[tuple[str, str]] = []  # (entity_id, unique_id)
    for entry in ent_reg.entities.values():
        if entry.domain != "media_player" or not entry.unique_id:
            continue
        if entry.platform == "music_assistant":
            ma_by_unique_id[entry.unique_id] = entry.entity_id
        else:
            native_media_players.append((entry.entity_id, entry.unique_id))

    native_twin_remap = {
        entity_id: ma_by_unique_id[unique_id]
        for entity_id, unique_id in native_media_players
        if unique_id in ma_by_unique_id
    }
    return ma_by_unique_id, native_twin_remap


# #1866: the compatibility scan below runs on EVERY /beatify/api/status call,
# and the admin polls that endpoint roughly every 3 s. Its per-entity skip
# reasons ("unsupported platform", "native twin of an MA player") are static for
# the lifetime of an entity, so re-emitting them per request produced ~10 DEBUG
# records every 3 s from this one code path. HA writes log records synchronously
# on the event loop, so that is loop time: with `custom_components.beatify:
# debug` a status call took 2-15 s instead of 0.03 s and the server-side round
# timer missed its deadline (#1865).
#
# We therefore remember the last line emitted per entity and only log again when
# it actually changes. Bookkeeping happens ONLY while DEBUG is enabled — if we
# populated the cache while logging was off, enabling debug later would show
# nothing until something changed, which is exactly when the user needs it.
_SCAN_LOG_STATE: dict[str, tuple[Any, ...]] = {}

#: Cache key for the "Found N compatible media players" summary line.
_SCAN_COUNT_KEY = "__scan_count__"


def _log_scan_change(
    key: str, signature: tuple[Any, ...], msg: str, *args: Any
) -> None:
    """Emit a compatibility-scan DEBUG line only when it changed (#1866).

    ``key`` identifies the line (an entity_id, or :data:`_SCAN_COUNT_KEY`) and
    ``signature`` is the tuple of values that would make the line differ.
    Building the signature is cheap; the message itself is still formatted
    lazily by the logging module.
    """
    if not _LOGGER.isEnabledFor(logging.DEBUG):
        return
    if _SCAN_LOG_STATE.get(key) == signature:
        return
    _SCAN_LOG_STATE[key] = signature
    _LOGGER.debug(msg, *args)


def _prune_scan_log_state(live_keys: set[str]) -> None:
    """Forget remembered scan lines for entities that no longer exist (#1866).

    Without this a removed-and-re-added entity would stay silent, and the dict
    would grow across HA's lifetime.
    """
    if not _SCAN_LOG_STATE:
        return
    for stale in [k for k in _SCAN_LOG_STATE if k not in live_keys]:
        del _SCAN_LOG_STATE[stale]


def _reset_scan_log_state() -> None:
    """Drop all remembered scan lines (test seam — module state must not leak)."""
    _SCAN_LOG_STATE.clear()


def _build_media_player_list(
    hass: HomeAssistant, ma_by_unique_id: dict[str, str]
) -> list[dict[str, Any]]:
    """Build the compatible-player list from live states + precomputed twin map.

    Factored out of :func:`async_get_media_players` (#1709) so the player list
    and the native-twin remap can be produced from a single registry walk (see
    :func:`async_get_media_players_with_remap`). ``ma_by_unique_id`` keys are the
    MA unique-id set used to drop native twins (#1627/#1628).
    """
    # Late import mirrors the callers: entity_registry isn't importable in the
    # unit-test env without a full HA setup. (noqa: PLC0415)
    from homeassistant.helpers import entity_registry as er

    ent_reg = er.async_get(hass)

    media_players = []
    # #1866: entity_ids seen this pass, so stale cache entries can be dropped.
    scanned_keys: set[str] = {_SCAN_COUNT_KEY}
    for state in hass.states.async_all("media_player"):
        scanned_keys.add(state.entity_id)
        # async_get is an O(1) dict lookup, not a registry walk.
        entity_entry = ent_reg.async_get(state.entity_id)
        platform = entity_entry.platform if entity_entry else "unknown"

        # Determine capabilities based on platform
        capabilities = get_platform_capabilities(platform)

        # Skip unsupported platforms (Cast without MA)
        if not capabilities.get("supported"):
            reason = capabilities.get("reason", "unknown")
            # #1866: logged once per entity, not once per status request.
            _log_scan_change(
                state.entity_id,
                ("unsupported", platform, reason),
                "Skipping unsupported player: %s (platform=%s, reason=%s)",
                state.entity_id,
                platform,
                reason,
            )
            continue

        # #1627: Skip the native-platform twin of a Music Assistant speaker.
        # Runs independently of the supported-platform check above so a native
        # twin is dropped even when its own platform (sonos) is supported —
        # picking it would route provider URIs to a player that can't resolve
        # them (UPnP Error 800). The MA twin (same unique_id) is kept.
        if (
            platform != "music_assistant"
            and entity_entry is not None
            and entity_entry.unique_id in ma_by_unique_id
        ):
            # #1866: logged once per entity, not once per status request.
            _log_scan_change(
                state.entity_id,
                ("native-twin", platform, entity_entry.unique_id),
                "Skipping native twin of MA player: %s (platform=%s, unique_id=%s)",
                state.entity_id,
                platform,
                entity_entry.unique_id,
            )
            continue

        media_players.append(
            {
                "entity_id": state.entity_id,
                "friendly_name": state.attributes.get("friendly_name", state.entity_id),
                "state": state.state,
                "platform": platform,
                # One `supports_<provider>` key per registered provider (#2713).
                # Written out by hand until this issue, which is how
                # `supports_amazon_music` came to be consumed by the admin but
                # never sent: the Amazon Music chip could not enable even on an
                # Echo. Crate Digger and ytmusic_free are here for the same
                # reason — the wizard greys out a provider the speaker cannot
                # serve, and it can only do that for a key it receives.
                **supports_keys(platform),
                "playback_method": capabilities.get("method", "uri"),
                "warning": capabilities.get("warning"),
                "caveat": capabilities.get("caveat"),
            }
        )

    # #1866: only when the count actually moves, not on every poll.
    _log_scan_change(
        _SCAN_COUNT_KEY,
        (len(media_players),),
        "Found %d compatible media players",
        len(media_players),
    )
    _prune_scan_log_state(scanned_keys)
    return media_players


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
    from homeassistant.helpers import entity_registry as er

    # Get entity registry to check which platform created each entity
    ent_reg = er.async_get(hass)

    # #1627: A speaker exposed through Music Assistant appears in the registry
    # twice with the SAME unique_id — once on its native platform (e.g. sonos)
    # and once on music_assistant. Both are the same physical speaker, but only
    # the MA twin can stream Beatify's provider URIs (spotify:track:… etc.); the
    # native twin throws "UPnP Error 800" and the game pauses with
    # media_player_error. Collect the unique_ids owned by an MA media_player so
    # we can drop the native twins below (even when the native platform — sonos
    # — is itself "supported"). Single registry walk (#1709).
    ma_by_unique_id, _ = _collect_ma_twin_maps(ent_reg)
    return _build_media_player_list(hass, ma_by_unique_id)


async def async_get_media_players_with_remap(
    hass: HomeAssistant,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Return the player list AND the native→MA twin remap from ONE walk (#1709).

    Callers that need both (e.g. the status path) should prefer this over
    calling :func:`async_get_media_players` and
    :func:`async_get_native_twin_remap` back to back, which repeats the entity
    registry walk. Behaviour of the two returned values is identical to calling
    those functions individually.
    """
    from homeassistant.helpers import entity_registry as er

    ent_reg = er.async_get(hass)
    ma_by_unique_id, native_twin_remap = _collect_ma_twin_maps(ent_reg)
    players = _build_media_player_list(hass, ma_by_unique_id)
    return players, native_twin_remap


async def async_get_native_twin_remap(hass: HomeAssistant) -> dict[str, str]:
    """Map each native-platform media_player entity_id to the Music Assistant
    entity_id for the same physical speaker (same unique_id). #1627 follow-up.

    #1628 made :func:`async_get_media_players` *hide* the native-platform twin
    of a Music Assistant speaker from the picker (a native ``sonos`` entity and
    a ``music_assistant`` entity that share a ``unique_id`` are the same physical
    speaker; only the MA twin can stream provider URIs — the native one throws
    "UPnP Error 800"). That fixes the live picker list, but NOT a *saved*
    selection (``localStorage.beatify_last_player`` or a direct API call) that
    still points at the now-hidden native twin. This map lets the wizard
    hydration AND the game-start path heal such a stale id by substituting the
    MA twin.

    Returns:
        ``{native_entity_id: ma_entity_id}`` for every twin pair found. Empty
        when no Music Assistant twins exist.
    """
    # Late import: mirrors async_get_media_players — entity_registry is not
    # importable in the unit-test env without a full HA setup. (noqa: PLC0415)
    from homeassistant.helpers import entity_registry as er

    ent_reg = er.async_get(hass)

    # Single registry walk (#1709): previously two full passes (MA map + remap).
    _, remap = _collect_ma_twin_maps(ent_reg)
    return remap
