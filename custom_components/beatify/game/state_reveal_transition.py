"""Round-timer & REVEAL/terminal-transition subsystem for :class:`GameState`.

Issue #1271 next-increment extraction (off ``main``): the **round-timer +
REVEAL/terminal-transition** cluster is pulled out of the ``game/state.py``
God-Object into this ``RevealTransitionMixin``.

The cluster is the forward-flow machinery that carries a round from "all
guesses in / timer expired" through the REVEAL phase to the terminal END
phase. It is **behavior-preserving**: it carries the exact same methods that
previously lived on ``GameState``, so its public API and every caller / test
are unchanged.

* ``check_all_guesses_complete`` — the early-reveal gate: ``True`` once every
  connected player has submitted all guesses required by the active modes
  (year, artist challenge, movie quiz, title/artist), the predicate
  ``trigger_early_reveal_if_complete`` checks before short-circuiting the round
  timer.
* ``_trigger_early_reveal`` — short-circuit the round timer when all guesses are
  in (Story 20.9): under ``_score_lock`` it re-checks the phase, cancels the
  timer, sets the early-reveal flag and calls ``_end_round_unlocked``.
* ``trigger_early_reveal_if_complete`` — the public WebSocket-side entry point
  that fires the early reveal only while PLAYING and all guesses are complete.
* ``_timer_countdown`` — the round timer task: wraps
  ``RoundManager._timer_countdown`` with the phase-aware end-of-round call,
  announcing time-up (#471) and ending the round only if still PLAYING. Clears
  the RoundManager timer-task handle BEFORE ``end_round`` (#1029) so the
  subsequent ``cancel_timer`` cannot self-cancel the running task mid-REVEAL.
* ``cancel_timer`` — cancel the round timer (delegates to ``RoundManager``).
* ``force_end_round_if_overdue`` — the server-side backstop (#1865): ends a
  round whose deadline has passed by more than the grace period while the
  phase is still PLAYING. Driven by a periodic tick in ``__init__.py``, so it
  does not depend on the per-round timer task surviving, and unlike the client
  watchdog it does not depend on a browser being open.
* ``_transition_to_reveal`` — REVEAL phase 4 (#1272): fire the combined REVEAL
  announcement BEFORE the visible state change (audio leads), clear per-phase
  reactions, then flip the phase to REVEAL through the ``_set_phase``
  chokepoint (which stamps ``reveal_started_at`` and notifies observers).
* ``_apply_reveal_lights`` — REVEAL phase 6 (#1272): set the REVEAL party-light
  phase, then flash gold (exact) or green (within one year) on the event.
* ``confirm_intro_splash`` — admin confirmation of the intro splash (#292/#403);
  delegates to ``RoundManager`` with the deferred-song / round-end / timer hooks.
* ``is_deadline_passed`` — whether the round deadline has elapsed (delegates to
  ``RoundManager``).
* ``advance_to_end`` — the terminal transition (#321): cancel timers + the #1012
  auto-advance, flip the phase to END through ``_set_phase`` (clearing
  ``reveal_started_at`` and notifying), celebrate + disable the party lights, and
  announce the winner + podium.

Why the cut stops here: ``_score_all_players``, ``_end_round_unlocked``,
``_schedule_reveal_advance`` and the ``_set_phase`` transition chokepoint
(#1273) — the round-end / phase SSOT — stay on ``GameState``. This mixin owns
only the timer task and the REVEAL/terminal *transition* helpers, all of which
the round-end orchestrator (which stays on ``GameState``) calls via ``self``.

The mixin relies on attributes / methods the host class owns and that live on
``self`` at runtime:

* ``self.phase`` — the PLAYING / REVEAL re-checks; the phase SSOT stays on
  ``GameState``.
* ``self._set_phase`` — the transition chokepoint (#1273) the REVEAL / END
  flips go through; stays on ``GameState``.
* ``self._score_lock`` — the round-end mutex the early-reveal path acquires.
* ``self._end_round_unlocked`` — the round-end orchestrator the early-reveal
  path drives (the caller holds ``_score_lock``); stays on ``GameState``.
* ``self._round_manager`` — the timer / deadline / intro-splash delegate.
* ``self.players`` / ``self.all_submitted`` — the guess-completeness checks.
* ``self.artist_challenge`` / ``self.movie_challenge`` /
  ``self.title_artist_challenge`` and their ``*_enabled`` / ``title_artist_mode``
  flags — the per-mode guess gates.
* ``self._player_registry`` — the per-phase reaction reset on REVEAL entry.
* ``self._announce_reveal`` / ``self.announce_time_up`` / ``self.announce_winner``
  / ``self.announce_podium`` — the TTS hooks (live on ``TtsAnnouncerMixin``).
* ``self._lights_set_phase`` / ``self._lights_flash`` / ``self._party_lights`` /
  ``self.disable_party_lights`` — the party-light hooks (live on
  ``MediaControlMixin``).
* ``self._cancel_auto_advance`` — the #1012 REVEAL auto-advance cancel hook
  (lives on ``RevealAutoAdvanceMixin``).
* ``self.end_round`` / ``self.play_deferred_song`` / ``self._on_round_end`` —
  the round-end + deferred-playback callbacks the timer / intro-splash paths use.

It carries no state of its own. ``GamePhase`` is imported lazily inside the
methods that need it (``# noqa: PLC0415``) to avoid a top-level circular import
back into ``state.py``.
"""

from __future__ import annotations

import asyncio
import logging

from ..const import ROUND_OVERDUE_GRACE_SECONDS

_LOGGER = logging.getLogger(__name__)


class RevealTransitionMixin:
    """Round-timer & REVEAL/terminal-transition behavior for :class:`GameState`.

    Carries the early-reveal gate, the round-timer task, the REVEAL transition
    helpers and the terminal ``advance_to_end`` (#1271 extraction). See the
    module docstring for the full attribute / method contract this mixin
    expects on ``self`` at runtime.
    """

    def check_all_guesses_complete(self) -> bool:
        """
        Check if all connected players have submitted all required guesses (Story 20.9).

        For early reveal: checks year guesses, and if artist challenge is active,
        also checks artist guesses.

        Returns:
            True if all connected players have completed all required guesses

        """
        # First check year guesses using existing method
        # Note: all_submitted() already returns False for zero connected players
        if not self.all_submitted():
            return False

        # If artist challenge enabled and active, check artist guesses
        # Skip check if challenge already has a winner (buttons disabled for others)
        # or if no one has guessed yet (don't block early reveal for ignored challenges)
        if self.artist_challenge_enabled and self.artist_challenge:
            has_winner = getattr(self.artist_challenge, "winner", None) is not None
            anyone_guessed = any(
                p.has_artist_guess for p in self.players.values() if p.is_active
            )
            if not has_winner and anyone_guessed:
                for player in self.players.values():
                    if player.is_active and not player.has_artist_guess:
                        return False

        # Issue #28: If movie quiz enabled and active, check movie guesses
        # Skip check if challenge already has correct guesses or no one interacted
        if self.movie_quiz_enabled and self.movie_challenge:
            has_correct = len(self.movie_challenge.correct_guesses) > 0
            anyone_guessed = any(
                p.has_movie_guess for p in self.players.values() if p.is_active
            )
            if not has_correct and anyone_guessed:
                for player in self.players.values():
                    if player.is_active and not player.has_movie_guess:
                        return False

        # #1180: In Title & Artist mode, wait for every active player to submit
        # their title/artist guess before auto-advancing. This mode replaces the
        # year guess, so there is no "winner" short-circuit — each player guesses
        # independently and we hold PLAYING until all are in.
        if self.title_artist_mode and self.title_artist_challenge:
            for player in self.players.values():
                if player.is_active and not player.has_title_artist_guess:
                    return False

        return True

    async def _trigger_early_reveal(self) -> None:
        """
        Trigger early transition to reveal when all guesses are in (Story 20.9).

        Cancels timer, sets early_reveal flag, and calls end_round.
        Uses _score_lock to prevent concurrent invocations from racing
        when multiple players submit simultaneously (AF2-013).

        """
        from .state import GamePhase  # noqa: PLC0415 — avoid circular import

        async with self._score_lock:
            # Re-check phase under lock — another coroutine may have already
            # transitioned to REVEAL between our caller's check and acquiring
            # the lock.
            if self.phase != GamePhase.PLAYING:
                _LOGGER.debug(
                    "Early reveal skipped — phase already %s", self.phase.value
                )
                return

            _LOGGER.info(
                "All guesses complete - triggering early reveal (phase=%s, callback=%s)",
                self.phase.value,
                self._on_round_end is not None,
            )
            self.cancel_timer()
            self._round_manager._early_reveal = True
            await self._end_round_unlocked()
            _LOGGER.info("Early reveal complete - phase now %s", self.phase.value)

    async def trigger_early_reveal_if_complete(self) -> None:
        """Trigger early reveal if the round is playing and all guesses are in."""
        from .state import GamePhase  # noqa: PLC0415 — avoid circular import

        if self.phase == GamePhase.PLAYING and self.check_all_guesses_complete():
            await self._trigger_early_reveal()

    async def _timer_countdown(self, delay_seconds: float) -> None:
        """Wait for round to end, then trigger reveal.

        Wraps RoundManager._timer_countdown with phase-aware end_round call.
        """
        from .state import GamePhase  # noqa: PLC0415 — avoid circular import

        try:
            await self._round_manager._timer_countdown(delay_seconds)
            # #1029: release the timer-task handle BEFORE invoking end_round.
            # end_round → _end_round_unlocked calls self.cancel_timer(), which
            # would cancel `_timer_task` — and `_timer_task` IS the currently
            # running task. A self-cancel schedules CancelledError on the next
            # real yield, interrupting the REVEAL broadcast (and historically
            # the phase transition itself before fake-await chains masked it).
            # _log_timer_task_failure treats cancellations as silent, so the
            # round froze on PLAYING with no diagnostic. Clearing the handle
            # here makes the subsequent cancel_timer() a no-op for this task.
            self._round_manager._timer_task = None
            # Timer completed normally — check phase and end round
            if self.phase == GamePhase.PLAYING:
                # #471 Phase 1: announce time-up only when timer ran to zero
                # (not on early-reveal). Done before end_round so the audio
                # leads the REVEAL transition.
                await self.announce_time_up()
                await self.end_round()
            else:
                _LOGGER.debug(
                    "Timer expired but phase already changed to %s", self.phase
                )
        except asyncio.CancelledError:
            _LOGGER.debug("Timer task cancelled")
            raise

    async def force_end_round_if_overdue(self) -> bool:
        """End a round the round-timer task failed to end (#1865).

        The round timer is a single ``asyncio`` task that sleeps to the
        deadline and then calls ``end_round``. Everything downstream of that
        sleep is a way for the round to never end: the task can be cancelled,
        it can raise, or it can block in ``announce_time_up`` waiting on a TTS
        service call. Until now the only thing that noticed was the countdown
        running in a player's browser (``handle_round_timeout``) — so a host
        who locked their phone, or a TV-only setup, sat on PLAYING forever.

        This is the same nudge, driven from the server instead. It is called
        from a periodic tick that is not owned by the round, so it survives
        the round's own task dying. It does *not* make the round immune to a
        blocked event loop — nothing in-process can — but a loop that stalls
        and recovers now gets the round moved on by the next tick rather than
        needing an open client.

        ``end_round`` is idempotent, so racing the real timer is harmless: the
        loser no-ops once the phase has moved on.

        Returns:
            True if this call ended the round, False if there was nothing to do.

        """
        from .state import GamePhase  # noqa: PLC0415 — avoid circular import

        if self.phase != GamePhase.PLAYING:
            return False
        # Also covers the intro-splash case: while a splash is pending the
        # deadline is only a placeholder and this reports not-passed (#1699).
        if not self._round_manager.is_deadline_passed():
            return False

        deadline = self._round_manager.deadline
        if deadline is None:
            return False
        overdue = (int(self._round_manager._now() * 1000) - deadline) / 1000.0
        # The grace period keeps this a backstop rather than a competitor: the
        # timer task firing a few hundred milliseconds late is normal, and
        # ending the round from here first would only add a second code path
        # to debug for a round that was about to end correctly anyway.
        if overdue < ROUND_OVERDUE_GRACE_SECONDS:
            return False

        _LOGGER.warning(
            "Round %d still PLAYING %.1fs past its deadline — server backstop "
            "forcing end_round (the round timer task did not fire)",
            self.round,
            overdue,
        )
        # No broadcast follows: end_round already fires `_on_round_end` (and
        # swallows its errors) on the way out. The client watchdog calls
        # `handler.broadcast_state()` on top of it, which is a second push of
        # the same state — not copied here.
        await self.end_round()
        return True

    async def _transition_to_reveal(self, correct_year: int | None) -> None:
        """Announce the reveal and flip the phase to REVEAL (#1272).

        Fires the combined REVEAL announcement (before the visible state
        change so audio leads), clears per-phase reactions, sets phase +
        reveal_started_at, and notifies state callbacks. Caller holds
        _score_lock.
        """
        from .state import GamePhase  # noqa: PLC0415 — avoid circular import

        # The per-round REVEAL announcements (correct answer, accuracy,
        # streaks, bets, steal unlocks, standings) collected into ONE
        # combined utterance — see _announce_reveal. Fired BEFORE the phase
        # transition so the audio leads the visible state change, and
        # wrapped so a TTS hiccup never blocks REVEAL below.
        try:
            await self._announce_reveal(correct_year)
        except (KeyError, AttributeError, TypeError, ValueError) as err:
            _LOGGER.error("REVEAL announcement failed: %s", err)

        # Transition to REVEAL
        self._player_registry._reactions_this_phase = (
            set()
        )  # Story 18.9: Clear for new reveal phase
        # #1273: _set_phase stamps reveal_started_at on REVEAL entry (#1048 —
        # so the admin client can render the auto-advance countdown on the
        # sticky Next button) and notifies observers (#441).
        self._set_phase(GamePhase.REVEAL)

    async def _apply_reveal_lights(self, correct_year: int | None) -> None:
        """Update party lights for REVEAL + flash on exact/correct (#1272).

        Caller holds _score_lock. Sets the REVEAL light phase, then flashes
        gold when any player was exact (years_off == 0) or green when any was
        within one year.
        """
        from .state import GamePhase  # noqa: PLC0415 — avoid circular import

        # Issue #331/#517: Update Party Lights for reveal phase + event flashes
        await self._lights_set_phase(GamePhase.REVEAL)
        if correct_year is not None:
            has_exact = False
            has_correct = False
            for p in self.players.values():
                if p.submitted and p.years_off is not None:
                    if p.years_off == 0:
                        has_exact = True
                    elif p.years_off <= 1:
                        has_correct = True
            if has_exact:
                await self._lights_flash("gold")
            elif has_correct:
                await self._lights_flash("green")

    def cancel_timer(self) -> None:
        """Cancel the round timer. Delegates to RoundManager."""
        self._round_manager.cancel_timer()

    async def confirm_intro_splash(self) -> None:
        """Handle admin confirmation of intro splash (Issue #292, #403).

        Delegates to RoundManager.
        """
        await self._round_manager.confirm_intro_splash(
            self.play_deferred_song, self._on_round_end, self._timer_countdown
        )

    def is_deadline_passed(self) -> bool:
        """Check if the round deadline has passed. Delegates to RoundManager."""
        return self._round_manager.is_deadline_passed()

    async def advance_to_end(self) -> None:
        """Transition to END phase with proper cleanup (#321).

        Use this instead of setting ``phase = GamePhase.END`` directly.
        Cancels timers so no stale callbacks fire after the game ends.
        Does NOT clear players (they stay for rematch/end screen).
        """
        from .state import GamePhase  # noqa: PLC0415 — avoid circular import

        self.cancel_timer()
        self._round_manager._cancel_intro_timer()
        self._cancel_auto_advance()  # #1012
        # #1273: transition clears reveal_started_at (#1048) + notifies (#441).
        self._set_phase(GamePhase.END)

        # Issue #331: Celebrate with Party Lights, then stop (#553)
        if self._party_lights:
            try:
                await self._party_lights.celebrate()
            except Exception:  # noqa: BLE001
                _LOGGER.warning("Party Lights celebration failed")
            await self.disable_party_lights()

        # Issue #447: Announce winner via TTS
        await self.announce_winner()
        # Issue #841 Phase 3: read out the podium (use case 19).
        await self.announce_podium()

        _LOGGER.info("Game advanced to END phase")
