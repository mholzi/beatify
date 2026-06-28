"""Media player discovery and control service for Beatify."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import secrets
from asyncio import timeout as async_timeout
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from homeassistant.exceptions import HomeAssistantError, ServiceNotFound
from homeassistant.helpers.event import async_track_state_change_event

from custom_components.beatify.game.playlist import get_playback_uri

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
        "amazon_music": False,
        "method": "uri",
        "warning": "Premium account must be configured in Music Assistant",
    },
    "sonos": {
        "supported": True,
        "spotify": True,
        "apple_music": False,
        "youtube_music": False,
        "tidal": False,
        "amazon_music": False,
        "method": "uri",
        "warning": "Spotify must be linked in Sonos app",
    },
    "alexa_media": {
        "supported": True,
        "spotify": True,
        "apple_music": True,
        "youtube_music": False,
        "tidal": False,
        "amazon_music": True,
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

# #1381: Fast-path Path 2 (title-advanced-without-exact-match) must not
# instant-accept an *arbitrary* title change. If a requested URI fails to
# resolve in MA while the speaker's prior queue naturally auto-advances to its
# next track within the wait window, the title changes to an unrelated song and
# the old code confirmed it as success in ~1s — silently running a round whose
# audio is the wrong track (the #795 failure class). Path 2 now requires cheap
# evidence that the new title is plausibly OUR track: either a token overlap
# with the expected title (remaster/translation tolerance, e.g. "Das Modell"
# vs "The Model" share no tokens but the artist matches) OR the expected artist
# appearing in the speaker's media_artist. The unbounded "any new title"
# acceptance is reserved for the post-timeout #345 branch, where it is logged.
_TITLE_TOKEN_MIN_LEN = 3


def _normalize_for_match(text: str) -> str:
    """Lower-case and strip non-alphanumeric to ASCII-ish tokens for matching."""
    return "".join(c if c.isalnum() else " " for c in text.lower())


def _title_tokens(text: str) -> set[str]:
    """Significant word tokens of a title (drops short noise words/suffixes)."""
    return {
        tok
        for tok in _normalize_for_match(text).split()
        if len(tok) >= _TITLE_TOKEN_MIN_LEN
    }


def _titles_plausibly_match(expected_title: str, current_title: str) -> bool:
    """Cheap similarity gate for fast-path Path 2 (#1381).

    True when the two titles share at least one significant token, or one
    normalized title is a prefix of the other (covers "(Remastered)" suffixes
    and minor punctuation differences). False for genuinely unrelated titles
    (e.g. the prior queue auto-advancing to a different song).
    """
    exp_norm = _normalize_for_match(expected_title).strip()
    cur_norm = _normalize_for_match(current_title).strip()
    if not exp_norm or not cur_norm:
        return False
    if cur_norm.startswith(exp_norm) or exp_norm.startswith(cur_norm):
        return True
    return bool(_title_tokens(expected_title) & _title_tokens(current_title))


def _artist_matches(expected_artist: str, media_artist: str) -> bool:
    """True when the expected artist is plausibly present in media_artist (#1381)."""
    exp = _normalize_for_match(expected_artist).strip()
    cur = _normalize_for_match(media_artist).strip()
    if not exp or not cur:
        return False
    if exp in cur or cur in exp:
        return True
    return bool(_title_tokens(expected_artist) & _title_tokens(media_artist))


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

# Candidate URI fields on a song, by user-selected provider (#805).
#
# Each provider lists its own playable URI fields in priority order. The
# fallback cascade in `_get_ma_uri_candidates` only walks the fields for
# `self._provider` — never tries a different provider's URI.
#
# Why: prior to #805 the cascade walked ALL six URI fields regardless of
# which provider the user picked in the wizard. On Levtos's Apple-Music-only
# MA setup, every round paid 4×15s of timeouts on Spotify/YT/Tidal URIs that
# his MA had no provider configured for, before getting to the Apple Music
# URI that actually worked. After 3 cumulative play_song failures the game
# was force-paused and the admin couldn't recover.
#
# The "fall through to other providers when primary fails" intent of #768
# only makes sense when the user's MA actually has those other providers
# configured — which the wizard already gates. If the user picked Apple
# Music, they're saying "this is the provider MA is set up for". Trust
# them.
_PROVIDER_URI_FIELDS: dict[str, tuple[str, ...]] = {
    "spotify": ("uri_spotify", "uri"),
    "apple_music": ("uri_apple_music",),
    "youtube_music": ("uri_youtube_music",),
    "tidal": ("uri_tidal",),
    "deezer": ("uri_deezer",),
    # Amazon Music uses Alexa text search — no URI fields; playback via
    # _play_via_alexa() with content_type="AMAZON_MUSIC".
    "amazon_music": (),
}


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
        # #1381: which acceptance path confirmed the most recent successful
        # _try_ma_play. 1 = expected-title substring (Path 1, strongest), 2 =
        # similarity/artist gate (Path 2), 0 = post-timeout #345 tolerance.
        # Only Path 1 is strong enough to promote a URI field to preferred.
        self._last_confirm_path: int = 0
        # #808 follow-up: classify the most recent failure mode so the
        # caller (game/state.py:start_round) can decide whether to count
        # this against MAX_SONG_RETRIES (real failure) or skip silently
        # (track unavailable in the user's catalog/storefront).
        #
        # Values:
        #   None         — last call succeeded or hasn't been called yet
        #   "unavailable" — MA accepted the URI but speaker stayed on the
        #                   prior track. Almost always means the track ID
        #                   isn't in the user's Apple Music storefront, or
        #                   MA's provider needs re-authentication for this
        #                   track. Skipping silently lets the game continue
        #                   with whatever subset IS playable.
        #   "error"       — speaker idle/off/unavailable, or hard speaker
        #                   problem. Counts toward MAX_SONG_RETRIES so the
        #                   game pauses on systemic issues (offline speaker,
        #                   broken provider auth across the board).
        self.last_failure_reason: str | None = None

        # #1363: set when Beatify itself issues a same-song media_stop after a
        # stale-title detect (line ~729). The stop forces the speaker to
        # 'idle'; if the NEXT cascade candidate also fails to resolve, the
        # idle-failure branch must NOT misread that self-induced idle as a
        # systemic 'error' (which pauses the game). Reset before each song.
        self._stopped_for_cascade: bool = False

        # #1516: the speaker's volume as it was BEFORE Beatify first changed it
        # this game. Captured once (via save_volume) on the first in-game volume
        # change so the host's original listening level can be handed back at
        # game end. None = nothing to restore (Beatify never touched the volume).
        self._saved_volume: float | None = None

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

        Returns:
            True if a saved volume was applied, False if there was nothing to
            restore (Beatify never changed the volume this game).
        """
        if self._saved_volume is None:
            return False
        level = self._saved_volume
        # Clear BEFORE the await so a re-entrant call can't double-restore, and
        # so the next game starts from a clean (uncaptured) slate.
        self._saved_volume = None
        return await self.set_volume(level)

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

    def _safe_state(self):
        """Read entity state, return None on any exception.

        Resilience for the playback-confirmation read sites in `_play_via_ma`.
        A transient exception from `hass.states.get()` (rare but possible during
        HA restarts / state-machine reload) used to propagate up and abort the
        whole song play, even though the existing code paths gracefully handle
        a None return. Catching here lets the flow downgrade to "state unknown"
        and continue. (#777 follow-up — the polling-resilience scope flagged in
        TestMAPollingResilience.)
        """
        try:
            return self._hass.states.get(self._entity_id)
        except Exception as err:  # noqa: BLE001 — defensive read of HA state
            _LOGGER.warning(
                "hass.states.get(%s) raised %s; treating as unknown",
                self._entity_id,
                err,
            )
            return None

    async def _safe_state_with_retry(self, retries: int = 3, delay: float = 0.5):
        """Read entity state with short retry loop; for the post-timeout site
        where having a state is critical for the title-advance check.

        Most reads succeed on attempt 1; this only kicks in when HA's state
        machine is briefly unreadable (HA restart edge, MA reload). Returns
        None if all attempts return None.
        """
        for attempt in range(retries):
            state = self._safe_state()
            if state is not None:
                return state
            if attempt < retries - 1:
                await asyncio.sleep(delay)
        return None

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
        uri = get_playback_uri(song)
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
        except (TimeoutError, asyncio.TimeoutError):
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

    @classmethod
    def _uri_match_tokens(cls, uri: str) -> list[str]:
        """Tokens to look for in MA's media_content_id to confirm playback.

        Issue #1380: the raw Beatify-internal URI is not what MA reports in
        media_content_id — MA echoes the _convert_uri_for_ma form. To reliably
        detect that the requested track started, match against BOTH the
        MA-converted URI and the bare track ID (last path/ID segment), which is
        identical across the internal and the MA-converted form for every
        provider (Spotify, Apple Music, Tidal, YT Music, Deezer).

        Args:
            uri: The Beatify-internal URI that was requested.

        Returns:
            Ordered, deduped, non-empty substring tokens.

        """
        tokens: list[str] = []

        def _add(token: str | None) -> None:
            if token and token not in tokens:
                tokens.append(token)

        # The form MA actually reports.
        _add(cls._convert_uri_for_ma(uri))
        # The raw form too, in case a provider echoes the internal URI verbatim.
        _add(uri)

        # Bare track ID — stable across both forms.
        if uri.startswith("spotify:"):
            _add(uri.split(":")[-1])
        elif "watch?v=" in uri:
            # https://music.youtube.com/watch?v=<id>[&extra]
            _add(uri.split("watch?v=", 1)[-1].split("&", 1)[0])
        elif "://" in uri:
            # applemusic://track/<id>, tidal://track/<id>, deezer://track/<id>,
            # and plain https URLs — the bare ID is the last "/"-segment.
            tail = uri.rstrip("/").rsplit("/", 1)[-1]
            _add(tail.split("?", 1)[0])

        return tokens

    def _get_ma_uri_candidates(
        self, song: dict[str, Any]
    ) -> list[tuple[str | None, str]]:
        """
        Build the ordered list of MA-ready URIs to try for this song (#805).

        Only walks URI fields belonging to the user's selected provider
        (`self._provider`). The wizard's provider choice represents what's
        actually configured in MA — trying URIs from other providers when
        the user said "Apple Music only" just buys 15s timeouts per
        unsupported provider before MA reports `MediaNotFoundError`.

        Order: the user's selected URI (`_resolved_uri`, storefront-resolved by
        the caller) ALWAYS first, then the previously-successful field (if any),
        then any remaining provider URI fields. URIs are converted for MA and
        deduped by their converted form.

        For apple_music, the legacy `uri_apple_music` field (a single,
        historically US-storefront ID) is dropped from the alternates whenever
        the song carries a `uri_apple_music_by_region` map — otherwise a non-US
        user would re-pay the wrong-storefront timeout #808 eliminated, and a
        cross-storefront-lucky US hit could become the learned preferred field
        and bypass region-correct resolution for the rest of the session (#1379).

        Returns:
            List of `(field_name, converted_uri)`. `field_name` is `None` for
            the `_resolved_uri` entry, a `uri_*` field name otherwise.

        """
        seen: set[str] = set()
        candidates: list[tuple[str | None, str]] = []
        # Validate the dispatch key explicitly (#1276). An unknown provider
        # (key absent from the table) is a config-level mismatch — the wizard
        # is supposed to gate it, but if it slips through, `.get(..., ())`
        # would silently yield zero candidates and playback would fail with
        # no actionable diagnostic. This is the silent-fail pattern behind
        # #768/#808. A KNOWN provider mapped to `()` (e.g. amazon_music, which
        # plays via Alexa text-search, not URIs) is intentional and stays
        # quiet. `_resolved_uri` is still honored below as a last resort so an
        # unexpected provider doesn't hard-fail when the song does carry a URI.
        provider_fields = _PROVIDER_URI_FIELDS.get(self._provider)
        if provider_fields is None:
            _LOGGER.warning(
                "MA dispatch: unknown provider %r — no URI field mapping; "
                "falling back to _resolved_uri only for %s - %s (#1276)",
                self._provider,
                song.get("artist"),
                song.get("title"),
            )
            provider_fields = ()

        def _add(field: str | None, raw: str | None) -> None:
            if not raw:
                return
            converted = self._convert_uri_for_ma(raw)
            if not converted or converted in seen:
                return
            seen.add(converted)
            candidates.append((field, converted))

        # #1379: storefront-unaware fallback guard. For apple_music, the legacy
        # `uri_apple_music` field holds a single (historically US-storefront)
        # track ID. The caller (`get_song_uri`) already resolves `_resolved_uri`
        # storefront-aware from `uri_apple_music_by_region` when that map exists.
        # Appending the legacy US field as an alternate for a non-US user
        # re-introduces exactly the wrong-storefront 15s stale-title timeout that
        # #808 eliminated — and if that US ID ever resolves cross-storefront, it
        # becomes the learned preferred field and systematically outranks the
        # region-correct URI for the rest of the session. When a regional map is
        # present, drop the legacy field entirely so only `_resolved_uri` (the
        # region-correct ID, or None when unavailable) is tried.
        skip_legacy_apple = self._provider == "apple_music" and bool(
            song.get("uri_apple_music_by_region")
        )

        def _field_eligible(field: str) -> bool:
            return not (skip_legacy_apple and field == "uri_apple_music")

        # #1379: `_resolved_uri` is ALWAYS tried first — it is the URI Beatify
        # resolved for the user's selected provider AND storefront. The learned
        # preference must never outrank it (a US ID that resolved once must not
        # systematically bypass storefront-correct resolution); the preference is
        # used only to order the REMAINING alternates below.
        _add(None, song.get("_resolved_uri"))

        # Learned preference — but only if it's a field belonging to the
        # current provider (the cache survives across games where provider
        # may have changed) and not a legacy field we're skipping for storefront
        # reasons (#1379). Ordered ahead of the other alternates, behind primary.
        if (
            self._ma_preferred_uri_field
            and self._ma_preferred_uri_field in provider_fields
            and _field_eligible(self._ma_preferred_uri_field)
        ):
            _add(self._ma_preferred_uri_field, song.get(self._ma_preferred_uri_field))

        # Remaining alternates within the same provider.
        for field in provider_fields:
            if field != self._ma_preferred_uri_field and _field_eligible(field):
                _add(field, song.get(field))

        return candidates

    async def _play_via_music_assistant(self, song: dict[str, Any]) -> bool:
        """
        Play via Music Assistant, walking the user-provider's URI fields (#805).

        Only candidates from `_PROVIDER_URI_FIELDS[self._provider]` are tried —
        the wizard's provider choice represents what MA is configured for, so
        attempting other providers' URIs just burns 15s timeouts per
        unsupported provider before MA reports `MediaNotFoundError`. This was
        the originating bug for #805 (Levtos's Apple-Music-only setup paid
        4×15s of Spotify/YT/Tidal timeouts on every failed round).
        """
        # #808 follow-up: clear stale failure classification before each
        # attempt so start_round reads only the result of THIS song.
        self.last_failure_reason = None
        # #1363: clear the cascade-stop flag at the start of each song so a
        # stop from a PRIOR song never leaks into this song's classification.
        self._stopped_for_cascade = False

        candidates = self._get_ma_uri_candidates(song)
        if not candidates:
            # #1276: surface the provider so a missing-URI miss is debuggable
            # (which provider was selected vs. which fields the song carries).
            _LOGGER.warning(
                "MA playback: no playable URI for provider %r — %s - %s (#1276)",
                self._provider,
                song.get("artist"),
                song.get("title"),
            )
            self.last_failure_reason = "unavailable"
            return False

        expected_title = song.get("title") or ""
        expected_artist = song.get("artist") or ""
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
            success = await self._try_ma_play(uri, expected_title, expected_artist)
            if success:
                # #1381: only learn a candidate's URI field as the new preferred
                # one when an EXPECTED-TITLE substring match (Path 1) confirmed
                # it. A weaker confirmation (artist/token gate, or the
                # post-timeout #345 tolerance) is not strong enough proof that
                # THIS field actually resolved our track — promoting it would
                # reorder future candidates wrongly for a field that never
                # really worked.
                if (
                    field
                    and field != self._ma_preferred_uri_field
                    and self._last_confirm_path == 1
                ):
                    _LOGGER.debug("MA preferred URI field now: %s (#768)", field)
                    self._ma_preferred_uri_field = field
                self.last_failure_reason = None
                return True

        _LOGGER.error(
            "MA playback: all %d URI candidate(s) failed for %s - %s (#768)",
            len(candidates),
            song.get("artist"),
            song.get("title"),
        )
        # last_failure_reason carries the classification of the last
        # _try_ma_play attempt (set by that method); start_round reads it.
        return False

    async def _try_ma_play(
        self, uri: str, expected_title: str, expected_artist: str = ""
    ) -> bool:
        """
        Attempt a single MA `play_media` call and wait for playback confirmation.

        Returns False on hard failure (speaker idle/unavailable, or the track
        clearly never swapped on the speaker) so the caller can try the next
        URI. Returns True both when playback is confirmed AND when the speaker
        is showing ambiguous-but-changing state (MA may still be buffering —
        preserving the #345 tolerance so we don't chase flaky retries).

        `expected_artist` (#1381) feeds the fast-path Path 2 similarity gate so
        an arbitrary title change from the prior queue auto-advancing is not
        instant-accepted as our track.
        """
        _LOGGER.debug("MA playback: %s on %s", uri, self._entity_id)

        # Snapshot speaker state before the call — we need both fields to
        # distinguish #345 slow-buffer (one of them changed during the wait)
        # from #777 silent failure (neither changed, speaker still on prior
        # track).
        state_before = self._safe_state()
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
            """Return True if the state confirms expected playback.

            Two acceptance paths:
              1. Title contains expected (substring) — the strongest signal.
              2. Title moved to a *plausibly-our-track* new title — MA is
                 making progress on a new track that shares a token with the
                 expected title, or whose artist matches the expected artist.

            Path 2 was previously only reachable via the 15-second slow-buffer
            tolerance below. Levtos reported that pressing "next" caused the
            UI to lag while the music had already started: the playlist had
            a song with a slightly different title format (e.g. German
            "Das Modell" vs MA's English "The Model", or "(Remastered)"
            suffix mismatches) so the substring-match in path 1 failed and
            the wait timed out. With path 2 in the fast-path, the UI now
            returns within ~1s of MA actually starting playback.

            #1381 tightened Path 2: it used to accept ANY title that differed
            from `title_before`. If the requested URI failed to resolve in MA
            while the speaker's prior queue auto-advanced to its next track
            during the 15s window, that unrelated title was instant-confirmed
            as success — the #795 "guess the year of SongX with no SongX audio"
            class, but silently. Path 2 now requires a cheap similarity gate
            (token overlap / normalized-prefix vs expected_title, OR expected
            artist present in media_artist). The unbounded "any new title"
            acceptance is reserved for the post-timeout #345 branch, where it
            is logged.

            #795 invariant still holds: if the title is unchanged from
            before the call (`title_before`), neither path fires and we
            fall through to the title-must-advance hard-failure check.
            """
            if not state or state.state != "playing":
                return False
            try:
                current_title = state.attributes.get("media_title", "") or ""
                current_artist = state.attributes.get("media_artist", "") or ""
                position_updated = state.attributes.get("media_position_updated_at")

                position_fresh = position_updated != position_updated_before
                if not position_fresh:
                    return False

                # Path 1: exact-ish title match (substring) — strongest signal,
                # the only path strong enough to learn a preferred URI field.
                if expected_lower and expected_lower in current_title.lower():
                    self._last_confirm_path = 1
                    return True
                # If no expected title was supplied, position-fresh alone is
                # all the signal we have — accept (matches old behavior).
                if not expected_lower:
                    self._last_confirm_path = 2
                    return True

                # Path 2 (#1381): title moved to a DIFFERENT title AND that
                # title is plausibly our track (shared token / prefix) OR the
                # artist matches. A bare "any different title" no longer
                # qualifies — that is the prior-queue auto-advance trap.
                if current_title and current_title != title_before:
                    if _titles_plausibly_match(
                        expected_title, current_title
                    ) or _artist_matches(expected_artist, current_artist):
                        self._last_confirm_path = 2
                        return True

                return False
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
            current = self._safe_state()
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
            final = self._safe_state()
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

        current_state = await self._safe_state_with_retry()
        speaker_state = current_state.state if current_state else "unknown"

        # Hard failure: speaker is idle/unavailable/off — song won't play
        if speaker_state in ("idle", "unavailable", "off", "unknown"):
            # #1363: if the speaker is 'idle' only because WE stopped it after a
            # prior same-song stale-title detect, this is a storefront-gap
            # cascade (e.g. apple_music's `_resolved_uri` and a differing
            # `uri_apple_music` both point at an unavailable catalog entry), NOT
            # a systemic speaker/provider failure. Misclassifying it as 'error'
            # makes state_lifecycle pause the whole game on a per-track gap —
            # the exact #805/#808 regression. Keep it 'unavailable' so the game
            # skips the song silently and tries the next one.
            if self._stopped_for_cascade and speaker_state == "idle":
                _LOGGER.warning(
                    "MA playback failed after %.1fs for %s — speaker idle, but "
                    "Beatify stopped it after a same-song stale-title detect. "
                    "Treating as a storefront/catalog gap (unavailable), not a "
                    "systemic error — game will skip this song silently. (#1363)",
                    MA_PLAYBACK_TIMEOUT,
                    uri,
                )
                self.last_failure_reason = "unavailable"
                return False
            _LOGGER.error(
                "MA playback failed after %.1fs for %s (state: %s). "
                "Either the speaker is offline, MA's provider is unauthenticated, "
                "or the track is not available in your provider's catalog. If this "
                "happens for many tracks, re-authenticate your music provider in MA.",
                MA_PLAYBACK_TIMEOUT,
                uri,
                speaker_state,
            )
            # Conservative: speaker-idle failures could be systemic (provider
            # broken across the board) so we keep counting them toward
            # MAX_SONG_RETRIES. The recovery banner will guide the user to
            # the re-auth fix once 3 land in a row.
            self.last_failure_reason = "error"
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
            # #808 follow-up: this is the storefront/region-mismatch
            # signature — MA accepted the URI but couldn't resolve a stream
            # for it, so the speaker just keeps playing the prior track.
            # @Levtos hit this for `apple_music://track/302229811` (US-only
            # 'All Together Now' on a DE-storefront MA), and the iTunes
            # Lookup confirmed: track in US catalog, NOT in DE catalog.
            _LOGGER.warning(
                "MA playback failed after %.1fs for %s — speaker still on "
                "prior track %r (position timestamp %s). Track is likely "
                "not available in your provider's catalog/storefront, OR "
                "your provider needs re-authentication in MA. Skipping "
                "this song silently — game will try the next one. (#795)",
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
                # #1363: record that the next cascade candidate will see an
                # 'idle' speaker WE caused, so its idle-failure isn't
                # misclassified as a systemic 'error'.
                self._stopped_for_cascade = True
            except (HomeAssistantError, ServiceNotFound, ConnectionError, OSError):
                _LOGGER.debug(
                    "media_stop call after stale-title detect failed for %s",
                    self._entity_id,
                )
            # #808 follow-up: classify as "unavailable" so start_round skips
            # silently without counting against MAX_SONG_RETRIES. Storefront
            # gaps shouldn't pause the game — the user can't fix individual
            # track availability and the game should keep playing whatever
            # subset IS in their catalog.
            self.last_failure_reason = "unavailable"
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
        # #1381: a post-timeout #345 tolerance confirmation is the weakest
        # acceptance — it must NOT promote this candidate's URI field to
        # preferred (it never proved THIS field actually resolved our track).
        self._last_confirm_path = 0
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
        if self._provider == "spotify":
            content_type = "SPOTIFY"
        elif self._provider == "amazon_music":
            content_type = "AMAZON_MUSIC"
        elif self._provider == "apple_music":
            content_type = "APPLE_MUSIC"
        else:
            # Unknown provider slipped past the wizard gate. Previously every
            # non-spotify/non-amazon provider was silently mapped to
            # APPLE_MUSIC, so a deezer/tidal/ytmusic mismatch played the wrong
            # catalog with no diagnostic — the same silent-fail class as
            # #768/#808. Surface it (mirrors the #1276 dispatch warning) before
            # falling back to APPLE_MUSIC. (#1402)
            _LOGGER.warning(
                "Alexa dispatch: unexpected provider %r — no Alexa content-type "
                "mapping; falling back to APPLE_MUSIC for %s - %s (#1402)",
                self._provider,
                song.get("artist"),
                song.get("title"),
            )
            content_type = "APPLE_MUSIC"

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

        # Playlists may store multiple artists as "A;B" — use only the first.
        if artist and ";" in artist:
            artist = artist.split(";")[0].strip()

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
        match_tokens = self._uri_match_tokens(uri)

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

    def get_playback_state(self) -> str | None:
        """Return the player's current state string ("playing", "paused",
        "idle", ...), or None if unavailable.

        Used by the REVEAL auto-advance (#1012) to tell when the round's
        song has finished — the player drops out of "playing" once the
        track ends.
        """
        state = self._safe_state()
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

    # #1627: A speaker exposed through Music Assistant appears in the registry
    # twice with the SAME unique_id — once on its native platform (e.g. sonos)
    # and once on music_assistant. Both are the same physical speaker, but only
    # the MA twin can stream Beatify's provider URIs (spotify:track:… etc.); the
    # native twin throws "UPnP Error 800" and the game pauses with
    # media_player_error. Collect the unique_ids owned by an MA media_player so
    # we can drop the native twins below (even when the native platform — sonos
    # — is itself "supported").
    ma_unique_ids = {
        entry.unique_id
        for entry in ent_reg.entities.values()
        if entry.domain == "media_player"
        and entry.platform == "music_assistant"
        and entry.unique_id
    }

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

        # #1627: Skip the native-platform twin of a Music Assistant speaker.
        # Runs independently of the supported-platform check above so a native
        # twin is dropped even when its own platform (sonos) is supported —
        # picking it would route provider URIs to a player that can't resolve
        # them (UPnP Error 800). The MA twin (same unique_id) is kept.
        if (
            platform != "music_assistant"
            and entity_entry is not None
            and entity_entry.unique_id in ma_unique_ids
        ):
            _LOGGER.debug(
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
