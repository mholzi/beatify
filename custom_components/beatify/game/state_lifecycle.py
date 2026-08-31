"""Round-lifecycle / round-start subsystem for :class:`GameState`.

Issue #1271 next-increment extraction (stacked on the state-serialization cut
:class:`~custom_components.beatify.game.state_serialization.StateSerializationMixin`):
the **round-start / round-setup orchestration** cluster is pulled out of the
``game/state.py`` God-Object into this ``RoundLifecycleMixin``.

The cluster is the "kick off the game and set up each new round" half of the
class: the LOBBY→PLAYING start gate plus the full ``start_round`` orchestration
(song selection, playback dispatch, metadata build, round-state commit). It is
**behavior-preserving**: it carries the exact same methods that previously
lived on ``GameState``, so its public API and every caller / test are
unchanged.

* ``start_game`` — the LOBBY→PLAYING start gate: validates the phase and the
  minimum player count, then flips to PLAYING (#390 precursor). Called by the
  admin ``start_game`` WebSocket / view handlers.
* ``start_round`` — the round-start orchestrator (#390): pulls the next
  playable song from the :class:`PlaylistManager`, skips/retries songs with no
  provider URI (capped at ``MAX_SONG_RETRIES``), dispatches playback through
  the lazily-created :class:`MediaPlayerService` (classifying ``unavailable``
  storefront skips vs. systemic playback failures per #808 / #949), builds the
  round metadata, commits the round state, flips the lights and fires the
  round-start TTS announcements (#471 / #841 / #842). The single entry point
  every "advance to the next round" caller (``ws_handlers``, ``game_views``,
  ``GameService``) hits.
* ``_ensure_media_player_service`` — lazily constructs the
  :class:`MediaPlayerService` on the first round (and wires analytics for
  error recording, Story 19.1) so the service is only created once a media
  player is configured.
* ``_prepare_intro_round`` — thin pass-through to
  ``RoundManager.prepare_intro_round`` (intro-splash deferral decision).
* ``_build_round_metadata`` — thin pass-through to
  ``RoundManager.build_round_metadata`` (initial wire-metadata dict, wiring the
  async metadata fetch coroutine).
* ``_initialize_round`` — commits all round state via
  ``RoundManager.initialize_round`` (timer/deadline, challenge setup, per-player
  round reset), clears ``round_analytics`` and flips to PLAYING through the
  single ``_set_phase`` chokepoint.

Why the cut stops here: the round-*end* path stays on ``GameState``. The shared
``_score_all_players`` loop and ``_end_round_unlocked`` are bound to the
vote-window / scoring coupling and are deliberately NOT moved (see
:class:`~custom_components.beatify.game.state_scoring.RoundScoringMixin`). The
REVEAL transition / auto-advance / reveal-lights helpers
(``_transition_to_reveal``, ``_schedule_reveal_advance``,
``_apply_reveal_lights``) also stay on ``GameState`` — they couple to the TTS,
vote-window and party-lights subsystems. The pause/resume + early-reveal +
``advance_to_end`` terminal helpers stay too; this cut is strictly the forward
round-*start* path.

The mixin relies on attributes / methods the host class owns and that live on
``self`` at runtime:

* ``self.phase`` / ``self._set_phase`` — phase read + the single transition
  chokepoint used by ``start_game`` / ``start_round`` / ``_initialize_round``.
* ``self.players`` — minimum-player-count gate (``start_game``) and the
  per-player round reset list passed to ``RoundManager.initialize_round``.
* ``self._playlist_manager`` — next-song selection, remaining-count
  (``last_round``) and ``mark_played`` for skipped songs.
* ``self.provider`` / ``self.storefront`` / ``self.platform`` /
  ``self.media_player`` — URI resolution and media-player dispatch context.
* ``self._media_player_service`` / ``self._stats_service`` — lazily-built
  playback service + the analytics sink wired into it.
* ``self._round_manager`` — the :class:`RoundManager` the intro/metadata/commit
  helpers delegate to; also supplies ``_timer_countdown`` / ``_on_round_end``
  callbacks.
* ``self._timer_countdown`` / ``self._on_round_end`` / ``self._fetch_metadata_async``
  — round-end + metadata-fetch callbacks/coroutines wired into ``RoundManager``;
  all stay on ``GameState`` (REVEAL coupling) and are referenced via ``self``.
* ``self._tts_service`` / ``self._tts_pre_round_delay`` — the #1211 pre-round
  TTS deadline shift.
* ``self._cancel_auto_advance`` — supersedes a pending REVEAL auto-advance on a
  new round start (#1012); stays on ``GameState``.
* ``self._lights_set_phase`` — party-light phase sync (owned by
  :class:`~custom_components.beatify.game.state_media.MediaControlMixin`).
* ``self.announce_round_start`` / ``self.announce_countdown`` /
  ``self.announce_last_round`` / ``self.announce_intro_round`` — round-start TTS
  announcements (owned by
  :class:`~custom_components.beatify.game.state_tts.TtsAnnouncerMixin`).
* ``self.deadline`` / ``self.round`` / ``self.current_song`` /
  ``self.last_round`` / ``self.round_analytics`` / ``self.is_intro_round`` /
  ``self.total_rounds`` / ``self.last_error_detail`` / ``self._now`` — round
  state read/written across the orchestration.

It carries no state of its own. ``GamePhase`` is imported lazily inside the
methods that need it (``# noqa: PLC0415``) to avoid a top-level circular import
back into ``state.py``; ``MediaPlayerService`` is likewise imported lazily
inside ``_ensure_media_player_service`` (matching the original).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from custom_components.beatify.const import (
    ERR_GAME_ALREADY_STARTED,
    ERR_GAME_NOT_STARTED,
    MAX_CONSECUTIVE_PLAYBACK_FAILURES,
    MIN_PLAYERS,
)

from .playlist import get_playback_uri, get_song_uri

_LOGGER = logging.getLogger(__name__)


class RoundLifecycleMixin:
    """Round-start / round-setup behavior for :class:`GameState`.

    Carries the LOBBY→PLAYING start gate plus the full ``start_round``
    orchestration and its round-setup helpers (#1271 extraction). See the
    module docstring for the full attribute / method contract this mixin
    expects on ``self`` at runtime.
    """

    def start_game(self) -> tuple[bool, str | None]:
        """
        Start the game, transitioning from LOBBY to PLAYING.

        Returns:
            (success, error_code) - error_code is None on success

        """
        from .state import GamePhase

        if self.phase != GamePhase.LOBBY:
            return False, ERR_GAME_ALREADY_STARTED

        if len(self.players) < MIN_PLAYERS:
            return False, ERR_GAME_NOT_STARTED  # Need at least MIN_PLAYERS to play

        self._set_phase(GamePhase.PLAYING)

        # Issue #1665: hand every player their single sabotage token. Unlike the
        # steal (unlocked by a streak), the sabotage token exists from round 1 —
        # a token you have to earn first would rarely be spent in a short game.
        # No-op when the setting is off, so default games are unchanged.
        if self.sabotage_enabled:
            for player in self.players.values():
                player.unlock_sabotage()

        # Round and song selection will be implemented in Epic 4
        _LOGGER.info("Game started: %d players", len(self.players))
        return True, None

    def _get_round_start_lock(self) -> asyncio.Lock:
        """Get (lazily creating) the #1697 round-start serialization lock.

        The lock is not created in ``GameState.__init__`` (that file owns the
        attribute set but the mixin must stay self-contained); it is built on
        first use instead. Creation is a plain ``getattr``/``setattr`` pair with
        no ``await`` in between, so two coroutines entering ``start_round`` in the
        same event-loop tick still share a single lock instance.
        """
        lock = getattr(self, "_round_start_lock", None)
        if lock is None:
            lock = asyncio.Lock()
            self._round_start_lock = lock
        return lock

    async def start_round(self, _retry_count: int = 0) -> bool:
        """Start a new round with song playback (#390).

        #1697: serialized behind ``_round_start_lock`` so a manual
        ``admin_next_round`` and the REVEAL ``_reveal_auto_advance`` (which both
        call this method) can never drive a round-start concurrently. Before the
        lock existed, the auto-advance parked in ``start_round``'s long awaits
        while the phase was still REVEAL, and an admin tapping "Next" passed its
        own REVEAL check and launched a second concurrent ``start_round`` — two
        songs pulled/marked played, the round incremented twice, two
        ``play_media`` calls, an orphaned timer cutting the round short. Holding
        the lock also serializes the internal skip/retry recursion (it stays a
        single logical round-start). After acquiring, a phase re-check makes the
        losing caller a no-op if the winner already reached PLAYING.

        Args:
            _retry_count: Internal counter for failed song attempts (max 3)

        Returns:
            True if round started successfully, False otherwise

        """
        from .state import GamePhase

        # Snapshot the phase BEFORE we contend for the lock. The double-advance
        # bug is specifically: this caller entered while the phase was still
        # REVEAL (or LOBBY for round 1), parked waiting for the lock, and the
        # race winner flipped it to PLAYING in the meantime. Bailing only when
        # the phase changed to PLAYING *under us* keeps legitimate PLAYING-phase
        # entries working (e.g. the Sudden-Death auto-end check runs inside
        # start_round, and the #1358 ghost-round guard tests drive it directly).
        entry_phase = self.phase
        async with self._get_round_start_lock():
            if (
                _retry_count == 0
                and entry_phase != GamePhase.PLAYING
                and self.phase == GamePhase.PLAYING
            ):
                _LOGGER.info(
                    "start_round: race winner already advanced to PLAYING while "
                    "we held for the lock — skipping duplicate round-start (#1697)"
                )
                return True
            return await self._start_round_locked(_retry_count)

    async def _start_round_locked(self, _retry_count: int = 0) -> bool:
        """Round-start orchestration body, run under ``_round_start_lock`` (#1697).

        Carries the exact pre-#1697 ``start_round`` logic. The skip/retry paths
        recurse into *this* method (not the public ``start_round``) so the
        non-reentrant lock is acquired once per logical round-start.
        """
        from .state import GamePhase

        MAX_SONG_RETRIES = 3

        # Crate Digger: regenerate the game's songs from the
        # CURRENT settings on the LOBBY -> first-round transition, and re-apply
        # the persisted output settings. A room freezes its parameters at
        # creation, but the lobby's reset button creates the next room
        # immediately, so anything changed afterwards missed its own game.
        # This lives here rather than in the REST start view because the
        # websocket admin handler calls start_round() directly and bypasses
        # that view entirely — hooking the view fixed one path and left the
        # other broken. Fires once; a hook failure must never block a game, so
        # the worst case is the room keeping its creation-time songs.
        hook = getattr(self, "pre_start_hook", None)
        if hook is not None and self.phase == GamePhase.LOBBY and _retry_count == 0:
            self.pre_start_hook = None
            try:
                await hook(self)
            except Exception:  # noqa: BLE001 - a hook must never block a game
                _LOGGER.warning("Pre-start hook failed", exc_info=True)

        # #1358: snapshot the game-identity epoch at entry. start_round parks in
        # long awaits (verify_responsive, play_song — play_song waits a full
        # Music Assistant timeout). If end_game / rematch_game / create_game runs
        # while we're parked, the epoch advances and we must abort instead of
        # resuming onto a torn-down or replaced game (game_id=None, no players,
        # phase LOBBY) — see _round_start_aborted.
        start_epoch = self._game_epoch

        # #1012: a (manual or auto) round start supersedes any pending
        # REVEAL auto-advance.
        if _retry_count == 0:
            self._cancel_auto_advance()

        if not self._playlist_manager:
            _LOGGER.error("No playlist manager configured")
            return False

        # Issue #827: Sudden Death — when only one player is left standing, the
        # game is over. Carry the just-finished round's REVEAL through to END
        # rather than starting another round. round >= 2 guards against ending
        # a fresh game (round 1 never eliminates).
        if (
            self.sudden_death_mode
            and self.round >= 2
            and len(self.non_eliminated_players()) <= 1
        ):
            _LOGGER.info("Sudden Death: one player remains — ending game")
            self._set_phase(GamePhase.END)
            return False

        # Get next playable song (skip songs without URI for selected provider)
        song = self._playlist_manager.get_next_song()
        if not song:
            _LOGGER.info("All songs exhausted, ending game")
            self._set_phase(GamePhase.END)
            return False

        resolved_uri = song.get("_resolved_uri")
        if not resolved_uri:
            _LOGGER.warning(
                "Skipping song (year %s) - no URI for provider", song.get("year", "?")
            )
            self._playlist_manager.mark_played(
                get_song_uri(song, self.provider, self.storefront) or song.get("uri")
            )
            if _retry_count >= MAX_SONG_RETRIES:
                _LOGGER.error(
                    "No playable songs found after %d attempts, pausing game",
                    MAX_SONG_RETRIES,
                )
                await self.pause_game("no_songs_available")
                return False
            return await self._start_round_locked(_retry_count + 1)

        # #2421: one rule decides whether this is the last round, and it lives
        # here. The flag counts what is left in the pool; the TTS announcement
        # used to re-derive the same question from `round >= total_rounds`, and
        # the two disagree as soon as a song is dropped mid-game — the
        # playback-failure path below marks a song played without a round being
        # committed, so `round` falls behind while the remaining count keeps
        # pace with reality. Measured on a five-song game with one song
        # dropped: round 4 really is the last, the flag said so, and the spoken
        # cue never came.
        #
        # The `total_rounds > 1` guard moved here from the announcement. It is
        # the reason a one-song game no longer raises the flag at all: opening
        # a game with "final round!" is noise, and that judgement now applies
        # to the banner and the announcement alike instead of only to the one
        # that happened to carry the guard.
        self.last_round = (
            self.total_rounds > 1 and self._playlist_manager.get_remaining_count() <= 1
        )
        self._ensure_media_player_service()
        will_defer_for_splash = self._prepare_intro_round(song)

        # Play song via media player (skip if deferred for intro splash)
        if self._media_player_service and not will_defer_for_splash:
            if not self._media_player_service.is_available():
                self.last_error_detail = (
                    f"Media player {self.media_player} is unavailable"
                )
                _LOGGER.error(
                    "Media player %s is not available, pausing game", self.media_player
                )
                await self.pause_game("media_player_error")
                return False

            # Additional responsiveness check for non-MA players
            if self.platform != "music_assistant":
                (
                    responsive,
                    error_detail,
                ) = await self._media_player_service.verify_responsive()
                # #1358: the game may have been torn down / replaced while we
                # waited on verify_responsive — bail before play_song so we
                # don't start music on a dead game.
                if await self._round_start_aborted(start_epoch):
                    return False
                if not responsive:
                    self.last_error_detail = error_detail
                    _LOGGER.error(
                        "Media player not responsive: %s, pausing game", error_detail
                    )
                    await self.pause_game("media_player_error")
                    return False

            # Don't start a song into a speaker that is still announcing.
            # MA queues announcements per player; starting playback while the
            # queue drains means play_song's verification window observes the
            # announcement instead of the expected track, times out after the
            # full MA timeout, and the round loses its song (reported: songs
            # skipped ONLY with TTS enabled). Bounded so a bad estimate can
            # never stall a round.
            busy = 0.0
            get_busy = getattr(self, "announcement_busy_seconds", None)
            if callable(get_busy):
                with contextlib.suppress(Exception):
                    busy = min(float(get_busy()), 8.0)
            # Start slightly BEFORE the estimate expires: MA needs a moment to
            # resolve and buffer the track anyway, so waiting the full
            # estimate left an audible 1-2s gap after "…3, 2, 1, go"
            # (reported). 80% of the estimate overlaps that buffering with the
            # tail of the announcement without racing it.
            busy *= 0.8
            if busy > 0.2:
                _LOGGER.info(
                    "Round %s: waiting %.1fs for the speaker to finish announcing "
                    "before starting playback",
                    getattr(self, "round", "?"),
                    busy,
                )
                await asyncio.sleep(busy)

            success = await self._media_player_service.play_song(song)
            if not success:
                # #808 follow-up: classify the failure. "unavailable" means
                # MA accepted the URI but the speaker stayed on the prior
                # track — typically a region/storefront mismatch (the track
                # ID isn't in the user's catalog). Skip silently and try the
                # next song without counting against MAX_SONG_RETRIES; the
                # user can't fix individual track availability and the game
                # should keep playing the subset that IS available.
                #
                # "error" / unset → systemic failure (speaker offline, MA
                # provider broken). Count toward MAX_SONG_RETRIES so the
                # recovery banner kicks in for real problems.
                failure_reason = getattr(
                    self._media_player_service, "last_failure_reason", None
                )
                self._playlist_manager.mark_played(get_playback_uri(song))

                if failure_reason == "unavailable":
                    _LOGGER.info(
                        "Skipping unavailable song silently: %s (likely not in "
                        "your provider's storefront/catalog) — trying next song",
                        song.get("title") or song.get("uri"),
                    )
                    await asyncio.sleep(0.2)
                    return await self._start_round_locked(_retry_count)

                # #1936: a timeout is not proof of a broken system. Music
                # Assistant's Apple Music provider rate-limits and then retries
                # after its OWN backoff — measured at 15.7s, i.e. longer than
                # the deadline we just gave it. Pausing the whole game on that
                # first timeout ended the evening for a provider that was
                # working, and handed the host a re-authenticate banner for a
                # problem they did not have.
                #
                # So the first failures skip the song, exactly like a
                # storefront gap; only MAX_CONSECUTIVE_PLAYBACK_FAILURES in a
                # row still means systemic and pauses. An offline speaker or a
                # genuinely dead provider therefore still reaches the recovery
                # banner — a few songs later instead of instantly, which is the
                # deliberate price for not ending a game over one slow start.
                self._consecutive_playback_failures = (
                    getattr(self, "_consecutive_playback_failures", 0) + 1
                )
                if (
                    self._consecutive_playback_failures
                    < MAX_CONSECUTIVE_PLAYBACK_FAILURES
                ):
                    # Stop the speaker BEFORE moving on. MA may still be
                    # retrying the track we just gave up on; without this it can
                    # start mid-way through the *next* round and play the wrong
                    # song under a live question. This does not provably cancel
                    # MA's internal retry — it is the strongest lever this side
                    # of the boundary has.
                    try:
                        await self._media_player_service.stop()
                    except Exception as err:  # noqa: BLE001 — must not raise
                        _LOGGER.warning("Stop before skip failed: %s (#1936)", err)
                    _LOGGER.warning(
                        "Playback timed out for %s — skipping this song "
                        "(failure %d of %d in a row; the provider may be "
                        "rate-limiting). Trying the next song. (#1936)",
                        song.get("title") or song.get("uri"),
                        self._consecutive_playback_failures,
                        MAX_CONSECUTIVE_PLAYBACK_FAILURES,
                    )
                    await asyncio.sleep(0.2)
                    return await self._start_round_locked(_retry_count)

                # #949: a systemic playback failure — the speaker stayed idle,
                # or the Music Assistant provider is unauthenticated — does not
                # fix itself by retrying. play_song already waited a full MA
                # timeout. Retrying it ~3x more meant ~2 minutes of a silent
                # "Starting..." button before the admin saw anything. Pause
                # now so the recovery banner (which names the provider to
                # re-authenticate) appears within seconds; its Resume button
                # is the manual retry if it really was a transient blip.
                # #1927 follow-up: report the URI that was ACTUALLY tried, not
                # the song's Spotify base field. An Apple Music attempt used to
                # be logged as `spotify:track:…`, which reads like a Spotify
                # defect and sends the next reader into the wrong provider.
                # Falls back to the base field when no attempt was recorded
                # (e.g. the song carried no playable URI at all).
                attempted_uri = getattr(
                    self._media_player_service, "last_attempted_uri", None
                ) or song.get("uri")
                # #1927: name the speaker too. The pause banner used to explain
                # *what* failed and *which provider* to re-authenticate, but
                # never *where* it was playing — the whole reason a game running
                # on the wrong speaker looked like a provider outage.
                self.last_error_detail = (
                    f"{song.get('artist')} — {song.get('title')} "
                    f"on {self.media_player} ({attempted_uri})"
                )
                _LOGGER.error(
                    "Playback failed for %s on %s — speaker unreachable, pausing game",
                    attempted_uri,
                    self.media_player,
                )
                # #1936: the budget is spent — reset it so the Resume button
                # gets a full one rather than pausing again on the next timeout.
                self._consecutive_playback_failures = 0
                await self.pause_game("media_player_error")
                return False

            # #1936: a confirmed start clears the streak. Only CONSECUTIVE
            # timeouts mean systemic; one bad song between two good ones does
            # not accumulate toward the pause.
            self._consecutive_playback_failures = 0

            # #1358: play_song just succeeded, but it parks for a full Music
            # Assistant timeout — long enough for the admin to end the game
            # (or a rematch / new game) in the meantime. If the game we started
            # for is gone, stop the playback we just kicked off and bail BEFORE
            # _initialize_round stamps PLAYING onto the torn-down game.
            if await self._round_start_aborted(start_epoch, stop_playback=True):
                return False

        metadata = self._build_round_metadata(song, resolved_uri, will_defer_for_splash)
        # Issue #1211: when TTS pre-round announcements are active, shift the
        # deadline forward so the timer doesn't count down during the TTS
        # overhead (e.g. Google Home chime → announcement → chime before music
        # resumes). Default is 0 ms (no change); users configure this via the
        # TTS settings "Timer delay" field.
        extra_ms = 0
        if self._tts_service and self._tts_pre_round_delay > 0:
            extra_ms = int(self._tts_pre_round_delay * 1000)
        # The round-start announcements fire AFTER this point but the deadline
        # starts counting now, so a 60s round was reaching the music with ~49s
        # left (reported). Shift the deadline by the estimated cost of the
        # announcements that are actually enabled — this is what #1211's
        # "Timer delay" asks the user to guess, derived automatically instead.
        # Any user-set Timer delay still applies on top: it stays the manual
        # override for device overhead we can't see (chimes, attention tones).
        # Prefer DEFERRING the deadline over estimating the announcement cost:
        # the estimate is a guess that gets proportionally worse as rounds get
        # shorter (a 15s round loses most of its music to a spoken round
        # number plus a countdown) and in languages whose phrases are longer.
        # Deferral re-stamps the deadline the moment the song is audible,
        # exactly as upstream already does for intro splashes (#1699). The
        # estimate stays as the fallback for the deferral path failing.
        defer = getattr(self._round_manager, "defer_deadline", None)
        if self._tts_service and callable(defer):
            with contextlib.suppress(Exception):
                defer()

        estimator = getattr(self, "estimate_round_start_announcements", None)
        if callable(estimator):
            with contextlib.suppress(Exception):
                announce_s = float(estimator())
                if announce_s > 0:
                    extra_ms += int(announce_s * 1000)
                    _LOGGER.info(
                        "Round %s: +%.1fs deadline for round-start announcements",
                        getattr(self, "round", "?"),
                        announce_s,
                    )
        self._initialize_round(
            song,
            metadata,
            resolved_uri,
            will_defer_for_splash,
            extra_deadline_ms=extra_ms,
        )

        delay_seconds = (self.deadline - int(self._now() * 1000)) / 1000.0
        await self._lights_set_phase(GamePhase.PLAYING)
        _LOGGER.info(
            "Round %d started: %s - %s (%.1fs timer)",
            self.round,
            self.current_song.get("artist"),
            self.current_song.get("title"),
            delay_seconds,
        )

        # Issue #471 Phase 1: Game Flow announcements at round start.
        # Fired AFTER lights/log so the audio aligns with the user-visible
        # transition. countdown is opt-in (default off) — chained after
        # round_start when both are enabled.
        await self.announce_round_start()
        await self.announce_countdown()
        # Issue #841 Phase 3: flag the final round (use case 17).
        # #2421: read the flag rather than re-deriving the condition, so the
        # speaker, the banner, the admin's button and the Finale Double guard
        # all answer to the same rule.
        if self.last_round:
            await self.announce_last_round()
        # Issue #842 Phase 4: flag an intro-mode round (use case 21).
        if self.is_intro_round:
            await self.announce_intro_round()

        # Post-announcement RESUME WATCHDOG: announcements interrupt the
        # just-started song, and some devices (observed: MA voice satellites)
        # fail to auto-resume afterwards — the player sits "paused" until a
        # human presses play. Verify playback shortly after the announcement
        # chain and press play on the device's behalf if needed.
        if self._tts_service and self._hass and self.media_player:
            import asyncio as _asyncio

            # Snapshot the level BEFORE announcements duck/restore it, so the
            # watchdog below can undo an upward ratchet.
            _vol_before = None
            with contextlib.suppress(Exception):
                _st0 = self._hass.states.get(self.media_player)
                _v = _st0.attributes.get("volume_level") if _st0 else None
                if isinstance(_v, (int, float)):
                    _vol_before = float(_v)

            # The song is (or is about to be) audible: start the round clock
            # from here rather than from initialize_round, so players get the
            # full round duration of MUSIC.
            start_now = getattr(self._round_manager, "start_timer_at_playback", None)
            if callable(start_now):
                with contextlib.suppress(Exception):
                    start_now(self._timer_countdown)
                    _LOGGER.info(
                        "Round %s: clock started at playback (%.0fs of music)",
                        getattr(self, "round", "?"),
                        float(getattr(self._round_manager, "round_duration", 0) or 0),
                    )
                    # Push the new deadline so client counters restart from
                    # the corrected value instead of continuing to run down
                    # the placeholder.
                    with contextlib.suppress(Exception):
                        self._notify_state_callbacks()

            _LOGGER.info("TTS resume watchdog armed for %s", self.media_player)

            async def _resume_watchdog() -> None:
                # v0.7.22 — triggers verified on hardware via the narrating
                # build:
                # * VA satellites stick in state='idle' after an announcement
                #   (HA never reports 'paused' even while MA's UI shows the
                #   paused track) -> sustained idle WITH a loaded title is
                #   the kick signature.
                # * 'playing' is healthy, full stop: media_position on MA
                #   entities is a snapshot+timestamp, not a live counter, so
                #   the old frozen-position stall heuristic false-positived
                #   on a perfectly playing ShieldTV. Removed.
                # v0.7.30 — ANTICIPATE instead of observe. Playback starts
                # BEFORE the announcements are fired, so every announcement
                # interrupts the song and the device has to resume. Waiting
                # for 3 consecutive idle ticks to prove that meant a 3-4s
                # silence after "…3, 2, 1, go" (reported). We now know how
                # long the announcements should take, so: wait out that
                # window, then kick IMMEDIATELY if the speaker isn't playing,
                # instead of spending three more seconds confirming what we
                # already expect.
                kicks = 0
                idle_streak = 0
                vol_restored = False
                lead = 0.0
                _busy = getattr(self, "announcement_busy_seconds", None)
                if callable(_busy):
                    with contextlib.suppress(Exception):
                        lead = min(float(_busy()), 15.0)
                if lead > 0:
                    await _asyncio.sleep(lead + 0.4)
                    st0 = self._hass.states.get(self.media_player)
                    if st0 is not None and st0.state in ("idle", "paused"):
                        kicks += 1
                        _LOGGER.info(
                            "Resume watchdog: announcement window over, resuming "
                            "immediately (state=%s)",
                            st0.state,
                        )
                        with contextlib.suppress(Exception):
                            await self._hass.services.async_call(
                                "media_player",
                                "media_play",
                                {"entity_id": self.media_player},
                                blocking=True,
                            )
                    elif st0 is not None and st0.state == "playing":
                        # Device resumed on its own (ShieldTV behaviour) —
                        # nothing to do, but keep polling as a safety net.
                        pass
                for tick in range(20):
                    await _asyncio.sleep(1.0)
                    st = self._hass.states.get(self.media_player)
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

                    # Volume ratchet guard. Music Assistant raises the volume
                    # for an announcement and restores it afterwards; on a
                    # ShieldTV feeding an AV receiver the restore wrote back a
                    # HIGHER level each round, so the music grew painfully
                    # loud within a few rounds. Beatify itself never changes
                    # volume here, but it is the only component positioned to
                    # notice — so undo an upward drift once per round, inside
                    # the announcement window only, leaving the host's own
                    # volume buttons alone for the rest of the round.
                    if _vol_before is not None and not vol_restored and tick <= 10:
                        cur = st.attributes.get("volume_level")
                        if (
                            isinstance(cur, (int, float))
                            and float(cur) > _vol_before + 0.05
                        ):
                            vol_restored = True
                            _LOGGER.warning(
                                "Volume rose from %.2f to %.2f across the TTS "
                                "announcement — restoring (announcement "
                                "duck/restore ratchet)",
                                _vol_before,
                                float(cur),
                            )
                            with contextlib.suppress(Exception):
                                await self._hass.services.async_call(
                                    "media_player",
                                    "volume_set",
                                    {
                                        "entity_id": self.media_player,
                                        "volume_level": _vol_before,
                                    },
                                    blocking=True,
                                )
                    if st.state == "idle" and title:
                        idle_streak += 1
                    else:
                        idle_streak = 0
                    # 2 ticks, not 3: the anticipatory kick above handles the
                    # normal case, so this fallback should react faster to the
                    # cases it misses. Satellites flap idle<->playing for
                    # SINGLE ticks during healthy playback, so 2 consecutive
                    # remains the floor — and a spurious media_play on a
                    # playing device is a no-op anyway.
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
                            await self._hass.services.async_call(
                                "media_player",
                                "media_play",
                                {"entity_id": self.media_player},
                                blocking=True,
                            )
                        except Exception as err:  # noqa: BLE001
                            _LOGGER.warning(
                                "Resume watchdog: media_play failed: %s", err
                            )
                            return
                        if kicks >= 3:
                            _LOGGER.info("Resume watchdog: 3 kicks — exit")
                            return
                    elif st.state == "off":
                        _LOGGER.info("Resume watchdog: player off — exit")
                        return
                _LOGGER.info("Resume watchdog: 20s window elapsed — exit")

            # Retain the task reference: asyncio's loop keeps only WEAK refs,
            # so an unreferenced task can be garbage-collected before running.
            prev = getattr(self, "_tts_resume_task", None)
            if prev is not None and not prev.done():
                prev.cancel()
            self._tts_resume_task = _asyncio.create_task(_resume_watchdog())
            self._tts_resume_task.add_done_callback(
                lambda _t: setattr(self, "_tts_resume_task", None)
            )

        return True

    async def _round_start_aborted(
        self, start_epoch: int, *, stop_playback: bool = False
    ) -> bool:
        """Decide whether an in-flight ``start_round`` must bail (#1358).

        Re-validates, after a long await, that the game ``start_round`` was
        launched for is still the live, playable game. Returns ``True`` (abort)
        when either:

        * the game-identity epoch has advanced — ``create_game`` / ``end_game``
          / ``rematch_game`` ran while we were parked (the original game is gone
          or has been replaced; ``end_game``/``rematch`` flip the phase to
          ``LOBBY`` without bumping it back), or
        * the phase has moved to ``PAUSED`` or ``END`` — a concurrent
          ``pause_game`` (which does NOT bump the epoch) or a game-end that
          ``_initialize_round``'s unconditional ``_set_phase(PLAYING)`` would
          otherwise silently undo.

        ``LOBBY`` is deliberately NOT a stand-alone abort trigger: the very
        first round of a game is started straight from ``LOBBY`` (no epoch
        change), so checking ``LOBBY`` directly would abort every legitimate
        first round. An ``end_game``/``rematch`` that lands on ``LOBBY`` is
        instead caught by the epoch bump.

        When ``stop_playback`` is set and we abort, the playback this round
        already started is stopped so the speaker doesn't keep playing on a
        torn-down game.
        """
        from .state import GamePhase

        if self._game_epoch == start_epoch and self.phase not in (
            GamePhase.END,
            GamePhase.PAUSED,
        ):
            return False

        _LOGGER.info(
            "Aborting start_round: game changed during await (epoch %s→%s, phase %s)",
            start_epoch,
            self._game_epoch,
            self.phase.value,
        )
        if stop_playback and self._media_player_service:
            try:
                await self._media_player_service.stop()
            except Exception as err:  # noqa: BLE001 — a stop error must not raise
                _LOGGER.warning("start_round abort: stop playback failed: %s", err)
        return True

    def _ensure_media_player_service(self) -> None:
        """Create MediaPlayerService lazily on first round.

        Idempotent: if the service was already built (e.g. by the #1540 LOBBY
        pre-warm — see :meth:`prewarm_media_player_service`), the
        ``not self._media_player_service`` guard makes this a no-op, so the
        round path keeps working unchanged whether or not the pre-warm ran.
        """
        # Lazy import: only the concrete class for instantiation; type hints
        # use MediaPlayerProtocol (module-level) to keep the import graph acyclic.
        from custom_components.beatify.services.media_player import (
            MediaPlayerService,
        )

        if self.media_player and not self._media_player_service:
            self._media_player_service = MediaPlayerService(
                self._hass,
                self.media_player,
                platform=self.platform,
                provider=self.provider,
                # #2143: carry the promises made to earlier speakers of this
                # game into the new service, so a mid-game switch doesn't lose
                # them. The new service takes ownership — clearing here keeps a
                # later release/build cycle from restoring the same speaker
                # twice.
                inherited_states=self._pending_speaker_states or None,
            )
            self._pending_speaker_states = {}
            # Connect analytics for error recording (Story 19.1 AC: #2)
            if self._stats_service and hasattr(self._stats_service, "_analytics"):
                self._media_player_service.set_analytics(self._stats_service._analytics)

    def schedule_media_player_prewarm(self) -> None:
        """Pre-warm the MediaPlayerService during LOBBY (#1540).

        Follow-up to #803: ``_ensure_media_player_service`` builds the service
        lazily on the first round, so on a cold Music Assistant start the first
        round pays the construction + first-call (preflight) latency. This kicks
        that work off in the background as soon as ``create_game`` has a media
        player selected, so Round 1 starts without the cold-start lag.

        Best-effort and non-blocking: ``create_game`` MUST NOT wait on this.
        Requires ``_hass`` (the event loop owner) and a selected media player;
        otherwise it silently no-ops and the lazy round path stays the fallback.
        The actual warming runs in :meth:`prewarm_media_player_service`.
        """
        if not (self._hass and self.media_player):
            return

        # #1540 review: supersede any still-running pre-warm from a prior
        # create_game before scheduling a new one, so a stale warm-up can't
        # race the fresh game's first round.
        self._cancel_prewarm()

        async def _runner() -> None:
            try:
                await self.prewarm_media_player_service()
            except asyncio.CancelledError:
                # A game reset/recreate cancelled the warm-up — expected, not a
                # failure. Re-raise so the task is marked cancelled, not errored.
                raise
            except Exception as err:  # noqa: BLE001 — pre-warm must never raise
                # #1540 review: warn (not debug) so a permanently offline
                # speaker surfaces in the log instead of being silently masked.
                _LOGGER.warning("Media player pre-warm failed (best-effort): %s", err)

        # Use HA's tracked task helper when available so the warm-up is tied to
        # the integration's lifecycle; fall back to a bare task otherwise (e.g.
        # the slimmed-down hass stub used in unit tests). Keep the handle so the
        # reset path can cancel it.
        creator = getattr(self._hass, "async_create_background_task", None)
        if callable(creator):
            self._prewarm_task = creator(_runner(), name="beatify_media_player_prewarm")
        else:
            self._prewarm_task = asyncio.create_task(_runner())

    def _cancel_prewarm(self) -> None:
        """Cancel the pending LOBBY media-player pre-warm task, if any (#1540)."""
        if self._prewarm_task is not None:
            self._prewarm_task.cancel()
            self._prewarm_task = None

    async def prewarm_media_player_service(self) -> None:
        """Construct + warm the MediaPlayerService ahead of Round 1.

        Builds the service via the idempotent :meth:`_ensure_media_player_service`
        (so a later round-path call recycles this instance). For non-Music-
        Assistant players it then issues ``verify_responsive`` — a *blocking*
        speaker service call — so the first real playback isn't the cold one,
        mirroring the round path (``start_round``), which only probes non-MA
        players. For Music Assistant it deliberately skips the probe: firing a
        speaker service call in the LOBBY would be a wasted (and potentially
        wake-on-LAN-triggering) call, and the round path doesn't probe MA
        either. Any probe failure propagates to the runner, which warns; the
        round path re-checks availability and surfaces real errors there.
        """
        self._ensure_media_player_service()
        service = self._media_player_service
        if service is None:
            return
        # #1540 review: match the round path — only non-MA players get the
        # blocking verify_responsive probe.
        if self.platform == "music_assistant":
            return
        probe = getattr(service, "verify_responsive", None)
        if callable(probe):
            await probe()

    def _prepare_intro_round(self, song: dict) -> bool:
        """Determine if this is an intro round. Delegates to RoundManager."""
        return self._round_manager.prepare_intro_round(song, self._hass)

    def _build_round_metadata(
        self, song: dict, resolved_uri: str, will_defer_for_splash: bool
    ) -> dict:
        """Build initial metadata dict. Delegates to RoundManager."""
        return self._round_manager.build_round_metadata(
            song,
            resolved_uri,
            will_defer_for_splash,
            self._media_player_service,
            # #1402 B2: pass a factory, NOT an eagerly-created coroutine.
            # On intro-splash-deferred rounds (or when no media player is
            # configured) build_round_metadata sets metadata_coro=None — an
            # eagerly-created coroutine would then be dropped un-awaited,
            # leaking it (RuntimeWarning: coroutine never awaited). The factory
            # is only invoked when the fetch is actually needed.
            lambda: self._fetch_metadata_async(resolved_uri),
        )

    def _initialize_round(
        self,
        song: dict,
        metadata: dict,
        resolved_uri: str,
        will_defer_for_splash: bool,
        extra_deadline_ms: int = 0,
    ) -> None:
        """Commit all round state. Delegates to RoundManager."""
        from .state import GamePhase

        self._round_manager.initialize_round(
            song,
            metadata,
            resolved_uri,
            will_defer_for_splash,
            self._playlist_manager,
            self._challenge_manager,
            self.players,
            self._timer_countdown,
            self._on_round_end,
            extra_deadline_ms=extra_deadline_ms,
        )
        self.round_analytics = None
        # #1273: transition clears reveal_started_at (#1048) + notifies (#441).
        self._set_phase(GamePhase.PLAYING)
