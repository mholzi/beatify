"""Pause / resume subsystem for :class:`GameState`.

Issue #1271 next-increment extraction (stacked on the round-lifecycle cut
:class:`~custom_components.beatify.game.state_lifecycle.RoundLifecycleMixin`):
the **pause / resume** cluster is pulled out of the ``game/state.py``
God-Object into this ``PauseResumeMixin``.

The cluster is the "freeze the game and thaw it back to where it was" pair: a
game pause (typically an admin disconnect, but also any server-side pause such
as ``media_player_error`` / ``no_songs_available``) snapshots the live phase,
stops the timers + media playback, and flips to ``PAUSED``; the resume restores
the snapshotted phase, restarts the round/intro timers against the *remaining*
deadline and resumes media playback. It is **behavior-preserving**: it carries
the exact same methods that previously lived on ``GameState``, so its public API
and every caller / test are unchanged.

* ``pause_game`` — the PLAYING/REVEAL→PAUSED gate. Stores the live phase in
  ``_previous_phase`` for the resume, records the ``pause_reason`` and (for any
  reason, #790) the disconnected admin's name so a later admin-WS drop stays
  recoverable, supersedes the unattended REVEAL auto-advance (#1012), and — only
  when pausing out of PLAYING — cancels the round + intro timers (#23) and stops
  media playback before flipping to ``PAUSED`` through the single ``_set_phase``
  chokepoint (#1273).
* ``resume_game`` — the PAUSED→(previous phase) restore. Restarts the round
  timer against the *remaining* deadline (and the #416/#496 intro-stop timer
  against actual playing time) and resumes media playback when resuming to
  PLAYING; if the deadline already elapsed during the pause it restores the
  phase and ends the round immediately. The phase write always routes through
  ``_set_phase(restore=True)`` so a resume-to-REVEAL does **not** re-stamp
  ``reveal_started_at`` (the auto-advance countdown must not restart, #1273).

Why the cut stops here: the ``_set_phase`` transition chokepoint (#1273) stays
on ``GameState`` — pause/resume only *call* it. ``_timer_countdown``,
``_cancel_auto_advance``, ``cancel_timer`` and ``end_round`` stay on
``GameState`` too (the round-end / REVEAL path); this mixin references them via
``self`` and moves none of them.

The mixin relies on attributes / methods the host class owns and that live on
``self`` at runtime:

* ``self.phase`` / ``self._set_phase`` — phase read + the single transition
  chokepoint (``restore=True`` resume write); stays on ``GameState``.
* ``self._previous_phase`` / ``self.pause_reason`` /
  ``self.disconnected_admin_name`` — the pause snapshot, initialised in
  ``create_game`` and owned by ``GameState``; read/written across the pair.
* ``self.players`` — the admin-name capture loop in ``pause_game``.
* ``self._cancel_auto_advance`` / ``self.cancel_timer`` — supersede the pending
  REVEAL auto-advance and the round timer on pause; stay on ``GameState``.
* ``self._timer_countdown`` / ``self.end_round`` — round-end callbacks the
  resume restarts / triggers; stay on ``GameState`` (REVEAL coupling).
* ``self._round_manager`` — the :class:`RoundManager` whose intro timer is
  cancelled on pause and whose round/intro timer tasks are restarted on resume.
* ``self._media_player_service`` — playback stop on pause / play on resume.
* ``self.deadline`` / ``self.current_song`` / ``self.is_intro_round`` /
  ``self.intro_stopped`` / ``self._now`` — round state read across the resume
  timer-restore math.

It carries no state of its own. ``GamePhase`` is imported lazily inside the
methods that need it (``# noqa: PLC0415``) to avoid a top-level circular import
back into ``state.py``; ``_log_timer_task_failure`` is likewise imported lazily
inside ``resume_game`` (matching the original).
"""

from __future__ import annotations

import asyncio
import logging

from custom_components.beatify.const import INTRO_DURATION_SECONDS

_LOGGER = logging.getLogger(__name__)


class PauseResumeMixin:
    """Pause / resume behavior for :class:`GameState`.

    Carries the PLAYING/REVEAL→PAUSED pause gate plus the PAUSED→(previous
    phase) resume restore (#1271 extraction). See the module docstring for the
    full attribute / method contract this mixin expects on ``self`` at runtime.
    """

    async def pause_game(self, reason: str) -> bool:
        """
        Pause the game (typically due to admin disconnect).

        Args:
            reason: Pause reason code (e.g., "admin_disconnected")

        Returns:
            True if successfully paused, False if already paused/ended

        """
        from .state import GamePhase  # noqa: PLC0415 — avoid circular import

        if self.phase == GamePhase.PAUSED:
            return False  # Already paused
        if self.phase == GamePhase.END:
            return False  # Can't pause ended game

        # Store current phase for resume
        self._previous_phase = self.phase
        self.pause_reason = reason

        # Store admin name for rejoin verification (Story 7-2). #790: capture
        # this for ANY pause reason, not just "admin_disconnected" — when the
        # pause is triggered server-side (media_player_error, no_songs_available)
        # the admin's WS may still be open, but if it later drops they need a
        # path back. Without this, ws_handlers.py:113 rejects all admin claims
        # during non-LOBBY phases and the game becomes unrecoverable.
        for player in self.players.values():
            if player.is_admin:
                self.disconnected_admin_name = player.name
                break

        # #1012: a pause stops the unattended REVEAL auto-advance too.
        self._cancel_auto_advance()

        # Stop timer if in PLAYING
        if self.phase == GamePhase.PLAYING:
            self.cancel_timer()
            # Issue #23: Cancel intro timer if running
            self._round_manager._cancel_intro_timer()
            # Stop media playback
            if self._media_player_service:
                await self._media_player_service.stop()

        # Transition to PAUSED (clears reveal_started_at + notifies, #1273)
        self._set_phase(GamePhase.PAUSED)
        _LOGGER.info("Game paused: %s", reason)

        return True

    async def resume_game(self) -> bool:
        """
        Resume game from PAUSED state.

        Returns:
            True if successfully resumed, False if not paused

        """
        from .state import GamePhase  # noqa: PLC0415 — avoid circular import

        if self.phase != GamePhase.PAUSED:
            return False
        if self._previous_phase is None:
            _LOGGER.error("Cannot resume: no previous phase stored")
            return False

        previous = self._previous_phase

        # Restart timer if resuming to PLAYING and deadline still valid
        if previous == GamePhase.PLAYING and self.deadline:
            now_ms = int(self._now() * 1000)
            remaining_ms = self.deadline - now_ms

            if remaining_ms > 0:
                remaining_seconds = remaining_ms / 1000.0
                # Local import to avoid module-level cycle.
                from custom_components.beatify.game.round_manager import (  # noqa: PLC0415
                    _log_timer_task_failure,
                )

                self._round_manager._timer_task = asyncio.create_task(
                    self._timer_countdown(remaining_seconds)
                )
                self._round_manager._timer_task.add_done_callback(
                    _log_timer_task_failure
                )
                _LOGGER.info("Timer restarted with %.1fs remaining", remaining_seconds)

                # Issue #416: Restart intro stop timer if this was an intro round
                # Issue #496: Use actual playing time (excludes pause duration)
                if (
                    self.is_intro_round
                    and not self.intro_stopped
                    and self._round_manager._intro_round_start_time is not None
                ):
                    elapsed_intro = (
                        self._round_manager.round_duration - remaining_seconds
                    )
                    remaining_intro = INTRO_DURATION_SECONDS - elapsed_intro
                    if remaining_intro > 0:
                        self._round_manager._intro_stop_task = asyncio.create_task(
                            self._round_manager._intro_auto_stop(
                                remaining_intro, self._on_round_end
                            )
                        )
                        _LOGGER.info(
                            "Intro stop timer restarted with %.1fs remaining",
                            remaining_intro,
                        )

                # Resume media playback if it was stopped
                if self._media_player_service and self.current_song:
                    await self._media_player_service.play()
                    _LOGGER.info("Media playback resumed")
            else:
                # Timer expired during pause — end the round immediately.
                # #1273: resume *restores* a saved phase rather than making a
                # forward transition, so it routes through _set_phase with
                # restore=True — that writes the phase + notifies but leaves
                # reveal_started_at untouched, so a resume-to-REVEAL does NOT
                # re-stamp it (the auto-advance countdown must not restart).
                _LOGGER.info("Timer expired during pause, ending round")
                self._set_phase(previous, restore=True)
                self.pause_reason = None
                self.disconnected_admin_name = None
                self._previous_phase = None
                await self.end_round()
                return True

        # Restore previous phase via _set_phase(restore=True) — see the
        # timer-expired branch above and the _set_phase ``restore`` docstring:
        # a resume must not re-stamp reveal_started_at on a resume-to-REVEAL.
        self._set_phase(previous, restore=True)
        self.pause_reason = None
        self.disconnected_admin_name = None
        self._previous_phase = None

        _LOGGER.info("Game resumed to phase: %s", previous.value)

        return True
