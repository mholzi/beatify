"""Music Assistant playback (#2636).

By far the largest of the three strategies, and the reason the split was worth
doing: everything below — the URI cascade of #768/#805/#1379, the confirmation
paths of #345/#795/#1381/#2333/#2616, the cold-start budget of #1936, the
failure classification of #808/#1363/#1863 — is Music Assistant's alone. In the
old 2300-line ``MediaPlayerService`` it shared a class body with Sonos and
Alexa, so a Sonos change was reviewed against all of it.

Split out of :mod:`custom_components.beatify.services.media_player`; the code
moved unchanged.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, ClassVar

from homeassistant.exceptions import HomeAssistantError, ServiceNotFound
from homeassistant.helpers.event import async_track_state_change_event

from ...providers import name_fallback_providers, provider_uri_fields
from .base import PlaybackStrategy
from .uris import convert_uri_for_ma, uri_match_tokens

_LOGGER = logging.getLogger(__name__)


# Music Assistant playback timeout. Higher than PLAYBACK_TIMEOUT because MA
# routes through the speaker's own buffering layer and AirPlay (HomePods,
# Denon AirPlay, some MA-wrapped Sonos setups) can take 10-12s to acknowledge
# a new track on the first round. #777 showed 8s was too aggressive — rounds
# advanced before the track had actually swapped on the speaker.
#
# #2682 raised it from 15.0s, and the number comes from Music Assistant's own
# retry schedule rather than from rounding up. 23 starts were timed on the real
# installation during the v4.4.3-rc1 live test: median 4s to first audio, and
# one at 14.6s — 0.4s inside the old deadline. The Music Assistant add-on log
# named the cause: its Apple Music rate limiter had failed and slept 1.0s, then
# 2.0s, then 4.3s, on an exponential schedule that runs to 8 attempts.
#
# That schedule is the whole arithmetic. Sleeping before attempt N costs
# 2^(N-1) - 1 seconds, and the 4.3s observed for a nominal 4.0s puts the real
# figure about 7% above nominal:
#
#     attempt 2 at   1.1s      attempt 5 at  16.1s
#     attempt 3 at   3.2s      attempt 6 at  33.3s
#     attempt 4 at   7.5s      attempt 7 at  67.7s
#
# On top of that sits the cost of the failed API calls (~0.8s each, so ~3s by
# attempt 5) and the speaker's own start, which the same run measured at a 4s
# median warm. So a start that only succeeds on Music Assistant's FIFTH attempt
# is audible at about 16.1 + 3 + 4 = 23s, and one that needs the SIXTH at about
# 33.3 + 3 + 4 = 40s.
#
# The budget is therefore set past attempt 5 and deliberately short of attempt
# 6. 40 seconds of silence in front of guests is worse for the room than
# skipping the song and drawing another one — and with
# MAX_CONSECUTIVE_PLAYBACK_FAILURES the game would spend two minutes on it
# before saying anything. 25.0 clears attempt 5 with ~2s to spare, and turns
# the measured 14.6s start from 0.4s of headroom into 10.4s.
#
# The cost is paid by a genuinely dead URI, which now waits 25s instead of 15
# before the cascade moves on. That is the trade #2682 asked for explicitly: a
# longer deadline costs nothing when playback is fast, and the failure it slows
# down is the one the log now names (see MA_SLOW_START_SECONDS below).
MA_PLAYBACK_TIMEOUT = 25.0

# #1936: the FIRST play of a game gets a third more time (25.0s → 33.3s). A
# speaker idle for a while was measured at 10.1s to first audio (Sonos via MA,
# Apple Music) — close enough to the deadline that a cold start regularly lost
# the race and the game paused before a single note had played. Later rounds
# keep the shorter deadline: by then the speaker is warm and a longer wait is
# just silence in front of the players.
#
# The factor still holds after #2682 raised the base, and for the same reason
# the base was raised: a cold speaker (10.1s) that is ALSO throttled to Music
# Assistant's fifth attempt (16.1s of backoff plus ~3s of failed calls) is
# audible at ~29s, which 25.0 alone would not cover and 33.3 does.
#
# Expressed as a FACTOR, not a second absolute constant, so the one existing
# patch point still governs both budgets — eight tests patch
# MA_PLAYBACK_TIMEOUT down to keep the suite fast, and a separate absolute
# constant would have silently made each of them wait the full budget.
MA_FIRST_PLAY_TIMEOUT_FACTOR = 4 / 3

# #2682: how slow a CONFIRMED start has to be before it is worth a WARNING.
#
# This is the second half of the ticket, and the more useful half. A start that
# is being throttled and a start whose URI is dead end at the same deadline
# with the same message, and until now the only place the difference was
# visible was the Music Assistant add-on log — a separate file most people
# never open. But the two are not actually symmetric: throttling produces
# something a dead URI never produces, namely a start that SUCCEEDS and takes
# far too long. That is exactly what #2682 was written from.
#
# So the slow success is logged, loudly, at the moment it happens. Twice the
# measured 4s median is a threshold no healthy warm start reaches and every
# throttled one does (the run that produced the ticket sat at 14.6s).
MA_SLOW_START_SECONDS = 8.0

# #2682: how long a slow start stays evidence that the provider is throttling.
#
# Throttling is a property of the minute, not of the track — Apple was leaning
# on that household for a window, and every start inside it paid. A dead URI is
# the opposite: a property of one song, with the songs on either side of it
# starting in four seconds. So "was a recent start slow?" is what separates the
# two once a timeout has actually happened, and this is how far back to look.
#
# Long enough to span the gap between two consecutive starts, or it would
# forget between rounds and never fire: a round is up to 60s of music and the
# reveal dwell can be a full 90s auto-advance, so 150s is the gap to cover.
MA_THROTTLE_MEMORY_SECONDS = 180.0

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

# Providers whose missing/failed URI may be retried by asking Music Assistant to
# resolve the track from name + artist. `ma_library` has done this since the
# Crate Digger work; `tidal` joins because its URIs can no longer be refreshed —
# Odesli's public API, the only source they ever came from, was retired on
# 2026-07-31 and now answers 401. Which providers those are is a property of the
# provider, so it is declared there (#2713).
_NAME_FALLBACK_PROVIDERS = name_fallback_providers()

# Words that mark a *different recording of the same song*. A name search is
# free to return any of them, which is exactly the risk this fallback carries:
# measured against ~2000 catalogue tracks with a known Deezer id, a plain
# "artist title" search returned the wrong edition for 2 % of mainstream tracks
# but 19 % of EDM ones ("Satisfaction" → "Satisfaction (Uk Radio Edit)",
# "Scary Monsters and Nice Sprites" → "… (Zedd Remix)").
#
# `_titles_plausibly_match` does NOT catch these: it accepts a normalized
# prefix, and the expected title is always a prefix of its own remix. That
# leniency is deliberate and load-bearing for #1381 ("Das Modell" vs "The
# Model"), so it stays — the stricter check below is applied only on the name
# fallback path, where the extra risk actually lives.
_EDITION_MARKERS = re.compile(
    r"\b("
    r"radio edit|extended|club mix|original mix|dub mix|"
    r"remix|re-?edit|mixed|karaoke|instrumental|acapella|a cappella|"
    r"acoustic|unplugged|live|demo|cover|tribute|playback|"
    r"edit|mix|version"
    r")\b",
    re.IGNORECASE,
)


def _edition_markers(text: str) -> set[str]:
    """Edition words present in a title, lower-cased."""
    return {m.group(0).lower() for m in _EDITION_MARKERS.finditer(text or "")}


def _edition_matches(expected_title: str, played_title: str) -> bool:
    """False when the played title carries an edition the expected title lacks.

    Deliberately one-directional. A catalogue entry named "Waves - Robin Schulz
    Radio Edit" may legitimately play back as plain "Waves" (the provider drops
    the suffix), so markers the *expected* side has are not required on the
    played side. The reverse is the failure we are guarding against: plain
    "Burn" must not be satisfied by "Burn (Aybsent Mynded Remix)".

    This matters more for Beatify than it would for a music player. The game
    asks players to guess the release *year*; a 2014 remix standing in for a
    1998 original does not merely sound different, it makes the round's correct
    answer wrong — and nothing on screen reveals that.
    """
    if not expected_title or not played_title:
        return True
    return not (_edition_markers(played_title) - _edition_markers(expected_title))


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


def _content_id_advanced(
    content_id: str, content_id_before: str, match_tokens: list[str]
) -> bool:
    """True when media_content_id proves the REQUESTED track is now loaded (#2616).

    `media_title` is not a track identity. Two different songs can share one
    title — round N plays "Hello" (Adele), round N+1 draws "Hello" (Lionel
    Richie) — and the title-must-change invariant (#2333/#795) then reads a
    perfectly successful switch as "the speaker never left the prior track".

    `media_content_id` IS an identity, and `_uri_match_tokens` already knows
    how to recognise our URI inside it (#1380). Two conditions, both required:

      * the id contains a token of the URI we just asked for — so an unrelated
        auto-advance of the prior queue cannot qualify, and
      * the id differs from the one playing before the call — so the #2333
        failure (MA never switched, prior track keeps running) still cannot
        qualify, not even when the prior round happened to play this same URI.

    Anything the speaker does not report (`media_content_id` missing on this
    platform) yields False and leaves the title comparison in sole charge, as
    before.
    """
    if not content_id or not match_tokens:
        return False
    if content_id == content_id_before:
        return False
    return any(token in content_id for token in match_tokens)


# Candidate URI fields on a song, by user-selected provider (#805).
#
# Each provider lists its own playable URI fields in priority order. The
# fallback cascade in `uri_candidates` only walks the fields for the user's
# provider — never tries a different provider's URI.
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
#
# #2713: the mapping now comes from the provider registry. Every provider gets
# an entry, so `None` below still means "provider Beatify has never heard of"
# while an empty tuple still means "this provider stores no catalogue URI"
# (amazon_music plays by Alexa text search; ytmusic_free's URI is derived from
# `uri_youtube_music` by `get_song_uri`, so `_resolved_uri` already holds it).
_PROVIDER_URI_FIELDS: dict[str, tuple[str, ...]] = provider_uri_fields()


class MusicAssistantStrategy(PlaybackStrategy):
    """Play through Music Assistant, and prove the speaker actually followed."""

    platforms: ClassVar[tuple[str, ...]] = ("music_assistant",)
    setup_warning: ClassVar[str | None] = (
        "Premium account must be configured in Music Assistant"
    )

    def __init__(self, context) -> None:
        super().__init__(context)
        # Which URI field last succeeded against MA — used to reorder the
        # candidate list so subsequent songs don't pay the primary-attempt
        # timeout on every round (#768).
        self._ma_preferred_uri_field: str | None = None
        # #1381: which acceptance path confirmed the most recent successful
        # try_play. 1 = expected-title substring (Path 1, strongest), 2 =
        # similarity/artist gate (Path 2), 0 = post-timeout #345 tolerance.
        # Only Path 1 is strong enough to promote a URI field to preferred.
        self._last_confirm_path: int = 0
        # #1936: True until the first playback attempt of this game has been
        # made. Drives the longer cold-start budget in try_play.
        self._first_play_pending: bool = True
        # #1363: set when Beatify itself issues a same-song media_stop after a
        # stale-title detect. The stop forces the speaker to 'idle'; if the
        # NEXT cascade candidate also fails to resolve, the idle-failure branch
        # must NOT misread that self-induced idle as a systemic 'error' (which
        # pauses the game). Reset before each song.
        self._stopped_for_cascade: bool = False
        # #2682: when a start last took longer than MA_SLOW_START_SECONDS, and
        # how long it took. A slow SUCCESS is the only in-band evidence that
        # Music Assistant's provider is backing off — a dead URI never produces
        # one — so it is remembered and used to explain the next timeout.
        # NOT reset per song: throttling spans songs, which is the point.
        self._last_slow_start: tuple[float, float] | None = None

    # -- #2682: telling a throttled start apart from a dead URI --------------

    def _note_start_duration(
        self, elapsed: float, uri: str, timeout: float, *, first_play: bool
    ) -> None:
        """Log a confirmed start, loudly when it was slow (#2682).

        The fast case stays at DEBUG, where it has always been. A start past
        MA_SLOW_START_SECONDS is the throttling fingerprint and is raised to
        WARNING, because the person who needs it is reading Beatify's log after
        a party and would otherwise have to open the Music Assistant add-on log
        to learn that anything was wrong at all.

        The first play of a game is exempted from the *memory*, not from the
        warning: a cold speaker was measured at 10.1s in #1936 with nothing
        throttling it, so treating it as evidence would arm the throttle
        explanation at the start of every game.
        """
        if elapsed < MA_SLOW_START_SECONDS:
            return
        if first_play:
            _LOGGER.info(
                "MA playback confirmed after %.1fs for %s — slow, but this is "
                "the first start of the game and a cold speaker was measured "
                "at ~10s on its own (#1936). Not counting it as evidence that "
                "the provider is throttling.",
                elapsed,
                uri,
            )
            return
        self._last_slow_start = (asyncio.get_event_loop().time(), elapsed)
        _LOGGER.warning(
            "MA playback confirmed after %.1fs for %s — past the %.0fs "
            "slow-start mark, on a %.0fs budget (a healthy warm start is about "
            "4s). Nothing failed, but Music Assistant's provider is very "
            "likely backing off: its Apple Music rate limiter retries on an "
            "exponential schedule (1s, 2s, 4s, 8s, ...) and that wait lands on "
            "top of every start. The next one may not fit in the budget. "
            "Confirm it in the Music Assistant add-on log — look for 'Rate "
            "Limiter'. (#2682)",
            elapsed,
            uri,
            MA_SLOW_START_SECONDS,
            timeout,
        )

    def _recent_slow_start(self) -> tuple[float, float] | None:
        """``(seconds ago, how long it took)`` of a recent slow start (#2682).

        None when there was none inside MA_THROTTLE_MEMORY_SECONDS — which is
        the reading that says "the provider was answering promptly for the
        other songs", i.e. this failure is about THIS track or the speaker.
        """
        if self._last_slow_start is None:
            return None
        when, elapsed = self._last_slow_start
        ago = asyncio.get_event_loop().time() - when
        if ago > MA_THROTTLE_MEMORY_SECONDS:
            return None
        return ago, elapsed

    def uri_candidates(self, song: dict[str, Any]) -> list[tuple[str | None, str]]:
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
            converted = convert_uri_for_ma(raw)
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

    async def capture_queue(self) -> dict[str, Any] | None:
        """Read what the speaker is playing right now (#2143).

        The snapshot comes from MA's ``get_queue``, which no other platform
        provides — hence the base class default of None and this override.
        Idempotence ("capture only once per game") is NOT decided here: it is a
        game-lifecycle question and lives with the shell, which calls this at
        most once.

        A failure is deliberately swallowed and reported as ``{}``: not being
        able to remember the queue must never stop the round from playing.
        """
        try:
            response = await self._hass.services.async_call(
                "music_assistant",
                "get_queue",
                {"entity_id": self._entity_id},
                blocking=True,
                return_response=True,
            )
        except (HomeAssistantError, ServiceNotFound, TypeError) as err:
            # TypeError guards older MA versions whose get_queue takes no
            # response — there is nothing to remember then, and pretending
            # otherwise would make restore_queue play a phantom track.
            _LOGGER.debug("Queue snapshot unavailable on %s: %s", self._entity_id, err)
            return {}

        # HA hands back None when a service has no response payload, and older
        # cores ignore `return_response` outright — neither is an error worth a
        # log line, but both must not be walked as if they were the mapping.
        if not isinstance(response, dict):
            return {}
        data = response.get(self._entity_id)
        if not isinstance(data, dict):
            return {}
        media_item = (data.get("current_item") or {}).get("media_item") or {}
        uri = media_item.get("uri")
        if not uri:
            # Idle speaker: captured, but there is nothing to hand back.
            # Reported as {} rather than None so the shell records the capture
            # and round two doesn't try again.
            _LOGGER.debug("Queue snapshot on %s: speaker idle", self._entity_id)
            return {}

        snapshot = {
            "uri": uri,
            "name": media_item.get("name") or "",
            "elapsed_time": float(data.get("elapsed_time") or 0),
            "shuffle": bool(data.get("shuffle_enabled")),
            "repeat_mode": data.get("repeat_mode"),
        }
        _LOGGER.debug(
            "Queue snapshot on %s: %s at %.0fs",
            self._entity_id,
            uri,
            snapshot["elapsed_time"],
        )
        return snapshot

    async def play(self, song: dict[str, Any]) -> bool:
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

        candidates = self.uri_candidates(song)
        expected_title = song.get("title") or ""
        expected_artist = song.get("artist") or ""

        # The name fallback below needs both fields; without them there is
        # nothing to search for and nothing to verify the result against.
        name_fallback = bool(
            self._provider in _NAME_FALLBACK_PROVIDERS
            and expected_title
            and expected_artist
        )

        if not candidates and not name_fallback:
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
            success = await self.try_play(uri, expected_title, expected_artist)
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

        # Last resort: let MA resolve the track from name + artist.
        #
        # `ma_library`: the stored URI is normally exact, but the item may have
        # moved or changed since the pool was built.
        # `tidal`: the URI may be absent entirely and can no longer be obtained
        # — Odesli, the only source Beatify ever had for Tidal ids, retired its
        # public API on 2026-07-31. This path is a safety net *behind* the
        # stored URIs, never a replacement for them: the loop above has already
        # run, so a song that carries a working `uri_tidal` never reaches here.
        if name_fallback:
            _LOGGER.info(
                "MA name fallback (%s): resolving by name -- %s - %s",
                self._provider,
                expected_artist,
                expected_title,
            )
            if await self.try_play(
                expected_title,
                expected_title,
                expected_artist,
                artist_filter=expected_artist,
            ):
                # A name search can land on a remix, a live take or a karaoke
                # version of the right song. `try_play` will happily accept
                # those (its title gate is a prefix/token check by design), so
                # the edition is checked here instead.
                state = self.context.state()
                played_title = (
                    state.attributes.get("media_title", "") if state else ""
                ) or ""
                if not _edition_matches(expected_title, played_title):
                    _LOGGER.warning(
                        "MA name fallback: rejecting wrong edition — wanted %r, "
                        "got %r (%s)",
                        expected_title,
                        played_title,
                        expected_artist,
                    )
                    self.last_failure_reason = "wrong_track"
                    return False
                self.last_failure_reason = None
                return True

        _LOGGER.error(
            "MA playback: all %d URI candidate(s) failed for %s - %s (#768)",
            len(candidates),
            song.get("artist"),
            song.get("title"),
        )
        # last_failure_reason carries the classification of the last
        # try_play attempt (set by that method); start_round reads it.
        return False

    async def try_play(
        self,
        uri: str,
        expected_title: str,
        expected_artist: str = "",
        artist_filter: str | None = None,
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
        # #1927 follow-up: remember what we are about to play, so a failure is
        # reported with the URI that was really tried.
        self.last_attempted_uri = uri
        # #1936: cold-start budget for the very first attempt of a game only.
        first_play = self._first_play_pending
        timeout = MA_PLAYBACK_TIMEOUT * (
            MA_FIRST_PLAY_TIMEOUT_FACTOR if first_play else 1
        )
        self._first_play_pending = False
        _LOGGER.debug(
            "MA playback: %s on %s (budget %.0fs)", uri, self._entity_id, timeout
        )

        # Snapshot speaker state before the call — we need both fields to
        # distinguish #345 slow-buffer (one of them changed during the wait)
        # from #777 silent failure (neither changed, speaker still on prior
        # track).
        state_before = self.context.state()
        if state_before is not None:
            title_before = state_before.attributes.get("media_title", "")
            position_updated_before = state_before.attributes.get(
                "media_position_updated_at"
            )
            # #2616: the title alone cannot tell "same song still playing"
            # apart from "different song, same title". The content id can.
            content_id_before = state_before.attributes.get("media_content_id") or ""
        else:
            title_before = ""
            position_updated_before = None
            content_id_before = ""

        # #2616: the substrings that identify THIS uri inside MA's
        # media_content_id — the same tokens wait_for_metadata_update matches
        # on (#1380).
        match_tokens = uri_match_tokens(uri)

        # #2143: remember the host's own queue BEFORE the replace below wipes
        # it. Idempotent, so this only costs a get_queue call in round one.
        await self.context.save_queue()

        # Fire-and-forget the service call — blocking=True hangs on MA+YTMusic
        # enqueue=replace: each round's track REPLACES the queue. Without it
        # MA keeps prior rounds queued, and after a TTS announcement the queue
        # resume can advance into stale entries — observed as the player
        # returning to PREVIOUS rounds' songs, sometimes mid-round.
        service_data: dict[str, Any] = {
            "media_id": uri,
            "media_type": "track",
            "enqueue": "replace",
        }
        # Crate Digger name fallback: when a stored library URI no longer
        # resolves (library rebuilds change item ids), media_id carries the
        # track NAME and the artist disambiguates it inside MA's resolver.
        if artist_filter:
            service_data["artist"] = artist_filter
        await self._hass.services.async_call(
            "music_assistant",
            "play_media",
            service_data,
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

                # #2333: the track has to have actually changed. The
                # docstring above promised this of BOTH paths, and Path 2
                # honoured it while Path 1 did not — it accepted a substring
                # match against whatever was playing, including the song from
                # the previous round still running.
                #
                # `position_fresh` above is no help: a track that simply keeps
                # playing keeps advancing its own position.
                #
                # The failure it allowed: round N plays "Stay With Me", round
                # N+1 draws "Stay" whose URI is missing from the household's
                # storefront, MA never switches, and `"stay" in "stay with
                # me"` confirms success within a second. The room then guesses
                # a song they already heard.
                #
                # Substring containment makes that reachable well beyond one
                # example — covers, "One", "Hurt", remaster suffixes.
                #
                # An empty `title_before` (nothing was playing) still passes,
                # which is the cold-start case and genuinely a change.
                title_changed = current_title != title_before

                # #2616: a changed title is sufficient proof of a new track,
                # but it is not necessary. Two different songs can carry the
                # same title ("Hello" by Adele, then "Hello" by Lionel
                # Richie), and #2333's title check then rejects a switch that
                # actually happened. `media_content_id` settles it: if it now
                # carries the id of the URI we requested AND differs from what
                # was loaded before, the speaker demonstrably moved to OUR
                # track. The #2333 failure stays rejected — there MA never
                # switched, so the content id never changes either.
                content_id = state.attributes.get("media_content_id") or ""
                track_changed = title_changed or _content_id_advanced(
                    content_id, content_id_before, match_tokens
                )

                # Path 1: exact-ish title match (substring) — strongest signal,
                # the only path strong enough to learn a preferred URI field.
                if (
                    track_changed
                    and expected_lower
                    and expected_lower in current_title.lower()
                ):
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
                if current_title and track_changed:
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
            current = self.context.state()
            if _check_state(current):
                elapsed = asyncio.get_event_loop().time() - start_time
                _LOGGER.debug(
                    "MA playback confirmed after %.1fs: %s (pos=%.1f)",
                    elapsed,
                    current.attributes.get("media_title", ""),
                    current.attributes.get("media_position", 0),
                )
                self._note_start_duration(elapsed, uri, timeout, first_play=first_play)
                return True

            await asyncio.wait_for(confirmed.wait(), timeout=timeout)
            elapsed = asyncio.get_event_loop().time() - start_time
            final = self.context.state()
            _LOGGER.debug(
                "MA playback confirmed after %.1fs: %s (pos=%.1f)",
                elapsed,
                final.attributes.get("media_title", "") if final else "?",
                final.attributes.get("media_position", 0) if final else 0,
            )
            self._note_start_duration(elapsed, uri, timeout, first_play=first_play)
            return True
        except asyncio.TimeoutError:
            pass
        finally:
            unsub()

        current_state = await self.context.state_with_retry()
        speaker_state = current_state.state if current_state else "unknown"

        # #2682: the one question this timeout cannot answer on its own —
        # was the provider throttling us in this window? A slow but successful
        # start inside MA_THROTTLE_MEMORY_SECONDS says yes, and nothing else
        # available on this side of the boundary does. See _recent_slow_start.
        slow = self._recent_slow_start()

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
                    timeout,
                    uri,
                )
                self.last_failure_reason = "unavailable"
                return False
            if slow is not None:
                # #2682: a rate-limited start used to be indistinguishable
                # from a dead URI here — same deadline, same sentence, and the
                # only place the difference showed was the Music Assistant
                # add-on log. It is distinguishable now, because a recent
                # start already ran long and finished: the provider was
                # answering slowly in this window, so this timeout is very
                # likely the same backoff one step further along its curve.
                _LOGGER.error(
                    "MA playback failed after %.1fs for %s (state: %s) — and a "
                    "start %.0fs ago already took %.1fs, so Music Assistant's "
                    "provider was backing off during this window. Read this as "
                    "rate limiting, NOT as a missing track and NOT as a "
                    "provider that needs re-authenticating: the schedule "
                    "doubles (1s, 2s, 4s, 8s, ...) and a start that lands one "
                    "step further along it outlasts any budget worth waiting "
                    "in front of guests. Nothing to fix — confirm it in the "
                    "Music Assistant add-on log by searching for 'Rate "
                    "Limiter'. (#2682)",
                    timeout,
                    uri,
                    speaker_state,
                    slow[0],
                    slow[1],
                )
                # Counts exactly as "error" does in state_lifecycle (only
                # "unavailable" skips without counting), so the game behaves
                # as it did: skip, and pause once
                # MAX_CONSECUTIVE_PLAYBACK_FAILURES land in a row. The value
                # is separate so the reason survives the boundary instead of
                # being flattened into the same word as a dead speaker.
                self.last_failure_reason = "rate_limited"
                return False
            _LOGGER.error(
                "MA playback failed after %.1fs for %s (state: %s). "
                "Either the speaker is offline, MA's provider is unauthenticated, "
                "or the track is not available in your provider's catalog. If this "
                "happens for many tracks, re-authenticate your music provider in MA. "
                "No start in the last %.0fs ran long, so the provider was "
                "answering promptly for the other songs — this is about this "
                "track or this speaker, not about rate limiting. (#2682)",
                timeout,
                uri,
                speaker_state,
                MA_THROTTLE_MEMORY_SECONDS,
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
        content_id_after = (
            (current_state.attributes.get("media_content_id") or "")
            if current_state
            else ""
        )
        title_advanced = title_after != title_before
        # #2616: same reasoning as in the fast path — an unchanged title is
        # only evidence of a stuck speaker when the content id has not moved
        # to the track we asked for. Stopping the speaker here is what made
        # the collision audible: the room heard the correct song for the full
        # budget, then silence, then a different song.
        track_advanced = title_advanced or _content_id_advanced(
            content_id_after, content_id_before, match_tokens
        )
        if not track_advanced:
            position_changed = position_updated_after != position_updated_before
            # #808 follow-up: this is the storefront/region-mismatch
            # signature — MA accepted the URI but couldn't resolve a stream
            # for it, so the speaker just keeps playing the prior track.
            # @Levtos hit this for `apple_music://track/302229811` (US-only
            # 'All Together Now' on a DE-storefront MA), and the iTunes
            # Lookup confirmed: track in US catalog, NOT in DE catalog.
            # #2682: this branch is where the two failures are easiest to
            # confuse. "Speaker still on the prior track" is the storefront-gap
            # signature #795 was filed for, but it is ALSO what a throttled
            # start looks like from here: Music Assistant is still sleeping
            # between retries, so it never swapped the track either. A recent
            # slow-but-successful start is what separates them.
            position_note = (
                "advanced — prior track still playing"
                if position_changed
                else "also unchanged"
            )
            if slow is not None:
                _LOGGER.warning(
                    "MA playback failed after %.1fs for %s — speaker still on "
                    "prior track %r (position timestamp %s). A start %.0fs ago "
                    "already took %.1fs, so read this as Music Assistant's "
                    "provider rate-limiting us rather than the track being "
                    "missing from your catalog/storefront: MA is still sleeping "
                    "between retries and has not swapped the track yet. Search "
                    "the Music Assistant add-on log for 'Rate Limiter' to "
                    "confirm. Skipping this song silently — the game will try "
                    "the next one, and there is nothing to re-authenticate. "
                    "(#795, #2682)",
                    timeout,
                    uri,
                    title_before,
                    position_note,
                    slow[0],
                    slow[1],
                )
            else:
                _LOGGER.warning(
                    "MA playback failed after %.1fs for %s — speaker still on "
                    "prior track %r (position timestamp %s). No start in the "
                    "last %.0fs ran long, so the provider was answering "
                    "promptly: the track is likely not available in your "
                    "provider's catalog/storefront, OR your provider needs "
                    "re-authentication in MA. Skipping this song silently — "
                    "game will try the next one. (#795, #2682)",
                    timeout,
                    uri,
                    title_before,
                    position_note,
                    MA_THROTTLE_MEMORY_SECONDS,
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

        if not title_advanced:
            _LOGGER.debug(
                "MA playback: title stayed %r for %s, but media_content_id "
                "moved to %r — the requested track IS loaded, the two songs "
                "merely share a title. Not a stale-title failure. (#2616)",
                title_before,
                uri,
                content_id_after,
            )

        # #1863: "still buffering" requires that Music Assistant actually owns
        # this player. An MA-platform entity reports the queue it is playing
        # from in `active_queue`; while MA is buffering a track it has already
        # taken the queue, so `active_queue` is set. A *null* `active_queue`
        # means MA never accepted the play_media call for this player at all —
        # the entity is only mirroring whatever the underlying speaker was
        # doing before the game (in the report: a leftover Spotify context,
        # `state: paused`, `media_position: 0`). That is a silent failure, not
        # slow buffering, and the #345 tolerance below would wave it through as
        # success: the round then starts, the timer arms, and the players get a
        # silent PLAYING phase with no music and no error.
        #
        # Deliberately narrow: only when the attribute is PRESENT and falsy. If
        # a Music Assistant / HA version does not expose `active_queue` at all
        # the key is missing, and we keep the old tolerance rather than turning
        # every slow buffer on that version into a failure.
        attrs_after = current_state.attributes if current_state else {}
        if "active_queue" in attrs_after and not attrs_after.get("active_queue"):
            _LOGGER.error(
                "MA playback failed after %.1fs for %s — the player reports no "
                "active Music Assistant queue (state: %s, title %r → %r). MA "
                "never took ownership of this speaker, so nothing was ever "
                "dispatched. Check that the speaker is exposed to Music "
                "Assistant and that your provider is authenticated there. "
                "(#1863)",
                timeout,
                uri,
                speaker_state,
                title_before,
                title_after,
            )
            # Systemic, not a per-track catalog gap: MA declined the whole
            # play_media call, so the next song would fail identically.
            # Classify as "error" so start_round pauses the game and shows the
            # recovery banner within seconds instead of silently burning
            # through the playlist one unplayable song at a time.
            self.last_failure_reason = "error"
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
            timeout,
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
