"""Round-lifecycle / round-start subsystem for :class:`GameState`.

Issue #1271 next-increment extraction (stacked on the state-serialization cut
:class:`~custom_components.beatify.game.state_serialization.StateSerializationMixin`):
the **round-start / round-setup orchestration** cluster is pulled out of the
``game/state.py`` God-Object into this ``RoundLifecycleMixin``.

The cluster is the "kick off the game and set up each new round" half of the
class: the full ``start_round`` orchestration (song selection, playback
dispatch, metadata build, round-state commit) and its setup helpers.

#2717: there used to be a ``start_game`` here as well — a synchronous
LOBBY→PLAYING flip with its own phase + minimum-player gate. Nothing in
production ever called it (both start paths go straight to ``start_round``),
and it could not be adopted either: ``start_round`` keys the sabotage grant and
the crate-digger pre-start hook on ``self.phase == GamePhase.LOBBY``, so
flipping to PLAYING first would silently skip both. It is gone; the phase flip
belongs to ``_initialize_round`` and the start gate to the two handlers a host
actually reaches (``ws_handlers/admin.admin_start_game`` and
``server/game_views.StartGameplayView``).

* ``start_round`` — the round-start orchestrator (#390): pulls the next
  playable song from the :class:`PlaylistManager`, skips/retries songs with no
  provider URI (capped at ``MAX_SONG_RETRIES``), dispatches playback through
  the lazily-created :class:`MediaPlayerService` (classifying ``unavailable``
  storefront skips vs. systemic playback failures per #808 / #949), builds the
  round metadata, commits the round state, flips the lights and fires the
  round-start TTS announcements (#471 / #841 / #842). The single entry point
  every "advance to the next round" caller (``ws_handlers``, ``game_views``)
  hits.
* ``_ensure_media_player_service`` — lazily builds the media-player service on
  the first round via the injected factory (#2638) and wires analytics for
  error recording (Story 19.1), so the service is only created once a media
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
  chokepoint used by ``start_round`` / ``_initialize_round``.
* ``self.players`` — the sabotage-grant recipients and the per-player round
  reset list passed to ``RoundManager.initialize_round``.
* ``self._playlist_manager`` — next-song selection, remaining-count
  (``last_round``) and ``mark_played`` for skipped songs.
* ``self.provider`` / ``self.storefront`` / ``self.platform`` /
  ``self.media_player`` — URI resolution and media-player dispatch context.
* ``self._media_player_service`` / ``self._stats_service`` — lazily-built
  playback service + the analytics sink wired into it.
* ``self._service_factories`` — the #2638 injection bundle; supplies the
  media-player factory ``_ensure_media_player_service`` calls.
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
back into ``state.py``. The concrete ``MediaPlayerService`` is no longer
imported here at all (#2638) — ``_ensure_media_player_service`` calls the
injected factory, so the import graph stays acyclic without a lazy import.

#2710: the post-announcement resume watchdog used to run here too — 215 lines
of ``hass.states.get`` / ``hass.services.async_call("media_player", …)`` inside
``_start_round_locked``, which is why "the game logic does not know Home
Assistant exists" was false on every round with TTS enabled. The loop now lives
on the media-player port (``resume_after_announcement``), next to every other
way this game presses play; what stays here is the announcement budget, the
"was this stopped on purpose" answer only the game can give, and the task.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging

from custom_components.beatify.const import MAX_CONSECUTIVE_PLAYBACK_FAILURES

from .playlist import get_playback_uri, get_song_uri

_LOGGER = logging.getLogger(__name__)


class RoundLifecycleMixin:
    """Round-start / round-setup behavior for :class:`GameState`.

    Carries the full ``start_round`` orchestration and its round-setup
    helpers (#1271 extraction). See the module docstring for the full
    attribute / method contract this mixin expects on ``self`` at runtime.
    """

    def _grant_sabotage_tokens(self) -> None:
        """Hand every player their single sabotage token (#1665).

        Unlike the steal (unlocked by a streak), the sabotage token exists from
        round 1 — a token you have to earn first would rarely be spent in a
        short game. No-op when the setting is off, so default games are
        unchanged, and idempotent, so being called twice cannot hand out two.

        #2497: this used to live inline in a ``start_game()`` that no
        production path called — both real start paths go straight to
        ``start_round()``. The grant moved to the LOBBY transition there;
        #2717 then deleted ``start_game()`` itself, so this method now has a
        single caller and the drift it was factored out to prevent is gone.
        """
        if not self.sabotage_enabled:
            return
        for player in self.players.values():
            player.unlock_sabotage()

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
        # #2497: the sabotage grant belongs to the LOBBY -> first-round
        # transition, and this is the only place both start paths pass through.
        # It used to sit in a start_game() that nothing in production called
        # (#2717 deleted it): the websocket admin handler and the REST start
        # view both call start_round() directly and the phase flip happens
        # inside _initialize_round. Note that this guard and the pre-start hook
        # below both read GamePhase.LOBBY — any caller that flipped the phase
        # before start_round would skip the grant AND the crate-digger hook.
        if self.phase == GamePhase.LOBBY and _retry_count == 0:
            self._grant_sabotage_tokens()

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
        # #2503: the encore offer belongs to the reveal that preceded this
        # round and to no other moment. Closing it here is what makes the
        # finale final — the whole reason this option was chosen over a chip on
        # the last reveal, which could be tapped again on each new last round.
        self._encore_window = False
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
                # #2711: a plain read. The port declares this attribute, so
                # a `getattr(..., None)` guard would only hide a fake that
                # does not — by classifying its failures as "error" and
                # quietly disabling the skip logic below.
                failure_reason = self._media_player_service.last_failure_reason
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
                # on its OWN exponential backoff, which can outlast whatever
                # deadline we gave it. Pausing the whole game on that first
                # timeout ended the evening for a provider that was working,
                # and handed the host a re-authenticate banner for a problem
                # they did not have.
                #
                # #2682 moved the deadline out to 25s so a start throttled to
                # MA's fifth retry (~23s) now lands instead of timing out, and
                # made the log say which cause it was — `last_failure_reason`
                # is "rate_limited" when a recent start was measurably slow,
                # "error" when none was. Both count here, deliberately: past
                # the fifth retry the next one is ~16s away, and skipping the
                # song beats holding the room in silence for it.
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
                attempted_uri = (
                    self._media_player_service.last_attempted_uri or song.get("uri")
                )
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
        #
        # #2710: the watching itself is a conversation with one speaker, so it
        # lives on the media-player port (``resume_after_announcement``) next
        # to every other way this game presses play. What stays here is what
        # only the game knows — how long the announcements still run, whether
        # playback stopped on purpose, and who owns the task.
        #
        # The old `self._hass` in this condition went with the old body. It
        # meant "we are running under Home Assistant, so there is a state
        # machine to poll"; nothing below polls one any more, and keeping it
        # would have left the whole path reachable only from a `hass` stub —
        # which is the #2638 complaint this change exists to answer.
        if self._tts_service and self.media_player:
            import asyncio as _asyncio

            # The song is (or is about to be) audible: start the round clock
            # from here rather than from initialize_round, so players get the
            # full round duration of MUSIC.
            # #2543: on an intro-splash round the clock belongs to
            # confirm_intro_splash — the song has not played yet, so there is
            # nothing to start here and the "clock started" log would lie.
            start_now = getattr(self._round_manager, "start_timer_at_playback", None)
            if callable(start_now) and not will_defer_for_splash:
                with contextlib.suppress(Exception):
                    # #2546: hand the remaining announcement budget along. The
                    # announce_* calls above queue their phrases (see
                    # _tts_announce) instead of blocking until the speaker is
                    # free, so "the song is audible" is not yet true when we get
                    # here. announcement_busy_seconds() is what the queue itself
                    # believes is left, and _tts_pre_round_delay is the user's
                    # manual #1211 allowance for device overhead we cannot see.
                    _extra = 0.0
                    with contextlib.suppress(Exception):
                        busy = getattr(self, "announcement_busy_seconds", None)
                        if callable(busy):
                            _extra += max(0.0, float(busy()))
                    _extra += max(0.0, float(self._tts_pre_round_delay or 0.0))
                    start_now(self._timer_countdown, _extra)
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

            # How long the speaker is still expected to be busy announcing.
            # The TTS queue's own reservation, capped: the watchdog waits it
            # out and then kicks immediately, rather than spending three more
            # seconds confirming a hang we already expect.
            lead = 0.0
            _busy = getattr(self, "announcement_busy_seconds", None)
            if callable(_busy):
                with contextlib.suppress(Exception):
                    lead = min(float(_busy()), 15.0)

            def _watchdog_should_continue() -> bool:
                """False once playback stopped on purpose (#2576).

                Two *wanted* states are indistinguishable from a hang when you
                only look at the speaker: the host taps "stop song"
                (``media_stop`` leaves a Music Assistant player ``idle`` WITH a
                title — exactly the stuck signature), and the game pauses
                (``pause_game`` stops the speaker). Only the game can tell the
                difference, so the port asks before every read.
                """
                from .state import GamePhase  # noqa: PLC0415 — Zirkelbezug

                if self.phase != GamePhase.PLAYING or getattr(
                    self, "song_stopped", False
                ):
                    _LOGGER.info(
                        "Resume watchdog: phase=%s song_stopped=%s — exit "
                        "(playback stopped on purpose)",
                        self.phase,
                        getattr(self, "song_stopped", None),
                    )
                    return False
                return True

            service = self._media_player_service
            if service is not None:
                _LOGGER.info("TTS resume watchdog armed for %s", self.media_player)
                # Retain the task reference: asyncio's loop keeps only WEAK
                # refs, so an unreferenced task can be garbage-collected before
                # running.
                prev = getattr(self, "_tts_resume_task", None)
                if prev is not None and not prev.done():
                    prev.cancel()
                self._tts_resume_task = _asyncio.create_task(
                    service.resume_after_announcement(
                        lead_seconds=lead,
                        should_continue=_watchdog_should_continue,
                    )
                )
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

    # ------------------------------------------------------------------
    # Encore — five more rounds, asked one round early (#2503)
    # ------------------------------------------------------------------

    ENCORE_ROUNDS = 5

    def encore_available(self) -> bool:
        """True while the host may still add five rounds to THIS game (#2503).

        The window is the reveal of the second-to-last round, and only that.
        Four options were drawn for this; the one chosen moves the offer back
        one round rather than putting it on the final reveal or on the end
        screen. The reason is that a last round which can be revoked while it
        is being revealed was never a last round — tap it again on the new
        final round and the ending keeps receding. Asking one round early
        leaves the actual finale undisturbed and still gives the host a whole
        song to think during.

        Three conditions, all of them:

        * REVEAL — the standings are on screen and the room is between songs.
        * ``_encore_window``, decided once on the way into this reveal and
          cleared when the next round starts. It is a flag rather than a live
          re-derivation because the first tap moves the finish line: "one song
          left" stops being true the moment the host uses the offer, and a
          re-derived condition would take the control away under their finger.
          The drawn option annotates that a second tap makes it thirty, so the
          offer has to survive its own use and die only when the round starts.
          Set from the pool rather than from ``round >= total_rounds`` for the
          same reason ``last_round`` is (#2421): a song dropped by a playback
          failure is marked played without a round being committed, so the
          counter falls behind reality while the pool does not.
        * the reserve still holds songs. A game whose playlist ran out has
          nothing to extend with, and offering five more rounds that cannot be
          delivered is worse than offering nothing.
        """
        from .state import GamePhase

        if self.phase is not GamePhase.REVEAL:
            return False
        if not getattr(self, "_encore_window", False):
            return False
        manager = getattr(self, "_playlist_manager", None)
        return manager is not None and manager.reserve_count() > 0

    def extend_rounds(self, count: int | None = None) -> int:
        """Add up to ``count`` more rounds to the running game (#2503).

        Returns the number of rounds actually added; 0 means the offer was not
        open or the reserve could not cover a single round, and nothing was
        touched.

        The scores are not reset and are not recomputed — that is the whole
        point of the feature, and it is why the control says so itself rather
        than putting the promise in a confirmation dialog after the tap. The
        issue assumed the cap threw the unplayed songs away; since #2547 it
        does not, so an encore is a release from the reserve plus a raised cap,
        not a new game.

        Fewer than ``count`` songs in the reserve still counts as an encore:
        three more rounds is a better answer to "play a bit longer" than a
        refusal because the reserve was two short.
        """
        if not self.encore_available():
            return 0
        wanted = self.ENCORE_ROUNDS if count is None else count
        if wanted <= 0:
            return 0
        released = self._playlist_manager.release_reserved_songs(
            wanted, reason="Encore (#2503)"
        )
        if not released:
            return 0
        # The cap governs normal play, so it has to move with the pool —
        # otherwise a later manager rebuild (a lobby option patch, a rematch)
        # would sample the game straight back down to the old count.
        self.max_rounds = self.max_rounds + released if self.max_rounds else 0
        self.total_rounds = self._playlist_manager.get_total_count()
        _LOGGER.info(
            "Encore: +%d round(s) on the host's request, now %d total (#2503)",
            released,
            self.total_rounds,
        )
        return released

    def _ensure_media_player_service(self) -> None:
        """Create the media-player service lazily on first round.

        Idempotent: if the service was already built (e.g. by the #1540 LOBBY
        pre-warm — see :meth:`prewarm_media_player_service`), the
        ``not self._media_player_service`` guard makes this a no-op, so the
        round path keeps working unchanged whether or not the pre-warm ran.

        #2638: the concrete class is no longer named here. The injected
        ``media_player`` factory builds it; with no factory wired (a game-logic
        unit test) the game simply has no speaker, which every caller of
        ``self._media_player_service`` already guards for.
        """
        factory = self._service_factories.media_player
        if factory is None:
            _LOGGER.debug("No media-player factory wired — playback unavailable")
            return

        if self.media_player and not self._media_player_service:
            self._media_player_service = factory(
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
