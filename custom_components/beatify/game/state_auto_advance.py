"""REVEAL auto-advance subsystem for :class:`GameState`.

Issue #1271 next-increment extraction (off ``main`` after the pause/resume
cut landed): the **REVEAL auto-advance** cluster is pulled out of the
``game/state.py`` God-Object into this ``RevealAutoAdvanceMixin``.

The cluster is the #1012 "carry REVEAL to the next round on its own" machinery:
once a round ends and the phase flips to REVEAL, an unattended task either
advances to the next round (on song-end, or after a configured dwell), or — when
nobody guessed — holds the game on REVEAL after stopping playback. It is
**behavior-preserving**: it carries the exact same methods that previously lived
on ``GameState``, so its public API and every caller / test are unchanged.

* ``_cancel_auto_advance`` — supersede the pending REVEAL auto-advance task, if
  any. Called from the round-end / pause / game-end / vote-window paths (all of
  which reference it via ``self``).
* ``_song_finished`` — poll helper: ``True`` once the round's song is no longer
  playing (the media player drops out of "playing"/"buffering"), the song-end
  signal both auto-advance tasks wait on.
* ``_reveal_auto_advance`` — the auto-advance task: advances to the next round on
  whichever comes first, song-end or the configured ``timer_seconds`` dwell
  (0 = wait for song-end), with a generous hard cap so an undetectable song-end
  can never stall the game. Clears its own handle before advancing so
  ``start_round``'s ``_cancel_auto_advance`` cannot cancel the running task,
  re-checks the phase to make a late firing a no-op, and mirrors the manual
  next-round broadcast (``_on_round_end``) so the new PLAYING state actually
  reaches clients.
* ``_reveal_idle_halt`` — the zero-guesses task (#1012 follow-up): let the song
  finish, stop the speaker, and hold on REVEAL rather than burning through the
  playlist unattended. Re-checks the phase after clearing its handle (#1123) so a
  manual "Next round" in the narrow song-finished→stop window can't silence the
  newly-started next song.

Why the cut stops here: ``_score_all_players``, ``_end_round_unlocked`` and the
``_set_phase`` transition chokepoint (#1273) — the round-end / phase SSOT — stay
on ``GameState``. The scheduling decision (``_schedule_reveal_advance``) that
*starts* these tasks also stays on ``GameState`` (it sits inside the round-end
orchestration); this mixin owns only the tasks themselves, which it references
via ``self``.

The mixin relies on attributes / methods the host class owns and that live on
``self`` at runtime:

* ``self.phase`` — the REVEAL re-check that makes a late firing a no-op; stays
  on ``GameState``.
* ``self._auto_advance_task`` — the task handle the cancel / clear paths read
  and write; owned by ``GameState`` (initialised in ``__init__`` / ``create_game``).
* ``self._media_player_service`` — the playback-state poll (``_song_finished``)
  and the idle-halt ``stop()``.
* ``self.players`` — not read here directly (the submitted-guess check lives in
  the scheduler), but the broadcast path depends on the host's player state.
* ``self.reveal_auto_advance`` — the configured REVEAL dwell (seconds; 0 = off)
  passed into ``_reveal_auto_advance``.
* ``self.start_round`` — the next-round trigger the auto-advance fires.
* ``self._on_round_end`` — the async WebSocket broadcast callback mirrored after
  the auto-advance ``start_round`` so the new PLAYING state reaches clients.
* ``self._on_game_end`` — the terminal game-end callback (#1753), wired by the
  WS handler to ``_finalize_and_end`` (claim + record_game + advance_to_end).
  The auto-advance final round routes through it so the unattended end records
  stats + fires the podium TTS through the SAME one-shot claim as the two admin
  sockets. Falls back to ``self.advance_to_end`` when unset (REST/service path
  or tests).
* ``self.advance_to_end`` — the terminal game-end ceremony (party-light
  celebration + winner/podium TTS + END transition; lives on
  ``RevealTransitionMixin``). Run when the auto-advance carries the final round
  and ``start_round`` exhausts the playlist (#1360) and no ``_on_game_end`` is
  wired, so the unattended end still fires the same ceremony + broadcast as the
  manual ``admin_next_round`` game-end.

It carries no state of its own. ``GamePhase`` is imported lazily inside the
methods that need it (``# noqa: PLC0415``) to avoid a top-level circular import
back into ``state.py``.
"""

from __future__ import annotations

import asyncio
import logging

_LOGGER = logging.getLogger(__name__)


class RevealAutoAdvanceMixin:
    """REVEAL auto-advance behavior for :class:`GameState`.

    Carries the #1012 unattended REVEAL→next-round machinery: the auto-advance
    task, the zero-guesses idle-halt task, their shared song-end poll helper and
    the cancel hook (#1271 extraction). See the module docstring for the full
    attribute / method contract this mixin expects on ``self`` at runtime.
    """

    def _cancel_auto_advance(self) -> None:
        """Cancel the pending REVEAL auto-advance task, if any (#1012)."""
        if self._auto_advance_task is not None:
            self._auto_advance_task.cancel()
            self._auto_advance_task = None

    def _song_finished(self) -> bool:
        """True once the round's song is no longer playing (#1012).

        The song keeps playing through REVEAL; when the track ends the
        media player drops out of "playing", which is the song-end
        signal for the auto-advance.

        #1374: a transient ``"unavailable"``/``None`` read (Sonos/Cast
        network handoff, Music Assistant reload — common during the
        multi-minute REVEAL dwell) is NOT a song-end. Treating it as one
        would make the auto-advance jump to the next round mid-song (or
        the idle-halt silence the speaker). Mirror the conservative
        exception branch below and stay on "still playing" for an unknown
        state — the hard cap still guarantees the game can never stall.
        """
        if not self._media_player_service:
            return False
        try:
            pstate = self._media_player_service.get_playback_state()
        except Exception:  # noqa: BLE001 — defensive: never let a poll error stall
            _LOGGER.debug(
                "song-finished poll: get_playback_state raised; treating as "
                "still playing",
                exc_info=True,
            )
            return False
        if pstate is None or pstate == "unavailable":
            _LOGGER.debug(
                "song-finished poll: player state %r — transient blip, "
                "treating as still playing (#1374)",
                pstate,
            )
            return False
        return pstate not in ("playing", "buffering")

    async def _reveal_auto_advance(self, timer_seconds: int) -> None:
        """Auto-advance from REVEAL to the next round (#1012).

        Advances on whichever comes first: the round's song finishing,
        or — when ``timer_seconds`` > 0 — that many seconds elapsing.
        ``timer_seconds == 0`` ("Off") means wait for the song to end.
        A generous hard cap guarantees the game can never stall even if
        song-end is undetectable. A manual next_round, pause or game-end
        cancels this task; the phase re-check makes a late firing a no-op.
        """
        from .state import GamePhase  # noqa: PLC0415 — avoid circular import

        poll = 2.0
        # Even in song-end mode, never wait longer than this (songs run
        # ~3-5 min) so an undetectable song-end can't stall the game.
        hard_cap = timer_seconds if timer_seconds > 0 else 360
        try:
            elapsed = 0.0
            while True:
                await asyncio.sleep(poll)
                elapsed += poll
                if self.phase != GamePhase.REVEAL:
                    return  # advanced / paused / ended elsewhere
                if self._song_finished() or elapsed >= hard_cap:
                    break
            # Clear the handle before advancing so start_round's own
            # _cancel_auto_advance() doesn't cancel this running task.
            self._auto_advance_task = None
            _LOGGER.info(
                "REVEAL auto-advance (timer=%ss, %.0fs elapsed) — next round",
                timer_seconds,
                elapsed,
            )
            # #1697: honors the round-start lock transitively — start_round()
            # acquires _round_start_lock and no-ops (returns True) if a manual
            # admin_next_round already advanced to PLAYING, so this auto-advance
            # can't pull a second song / double-increment the round.
            success = await self.start_round()
            # #1360: when the playlist is exhausted, start_round() flips the
            # phase to END and returns False (a bare _set_phase(END), NOT the
            # advance_to_end() terminal path). On this unattended final round
            # the manual admin_next_round game-end ceremony never runs, so
            # without intervention here the game ends with: no party-light
            # celebration, no announce_winner/announce_podium TTS, and — because
            # success is False — no broadcast, leaving every client frozen on
            # REVEAL.
            #
            # #1753: route through the shared game-end gate (_on_game_end =
            # ws_handler._finalize_and_end) rather than calling advance_to_end()
            # directly. The old direct call (a) never recorded stats on the
            # unattended final round and (b) never claimed the game_id, so a
            # concurrently-parked admin_next_round could still win the claim and
            # fire a SECOND record_game + advance_to_end (double podium TTS).
            # The gate claims once, records stats, and runs advance_to_end (which
            # re-sets END idempotently, celebrates the lights, announces the
            # winner/podium); whichever terminal path claims first wins. When no
            # handler is wired (REST/service path or tests) fall back to the bare
            # ceremony so the unattended end still fires.
            if not success and self.phase == GamePhase.END:
                _LOGGER.info(
                    "REVEAL auto-advance reached the final round — running "
                    "game-end ceremony"
                )
                if self._on_game_end is not None:
                    await self._on_game_end()
                else:
                    await self.advance_to_end()
                success = True
            # start_round() only fires sync state-callbacks via
            # _notify_state_callbacks; the async WebSocket broadcast
            # (`_on_round_end` = ws_handler.broadcast_state) is what actually
            # pushes the new PLAYING (or END) state to clients. The manual
            # admin_next_round path explicitly awaits handler.broadcast_state()
            # after start_round / advance_to_end — mirror that here, otherwise
            # music starts (or the game ends) but the admin + player UIs stay
            # frozen on REVEAL.
            if success and self._on_round_end:
                try:
                    await self._on_round_end()
                except (ConnectionError, OSError, TypeError) as err:
                    _LOGGER.error("Auto-advance broadcast failed: %s", err)
        except asyncio.CancelledError:
            _LOGGER.debug("REVEAL auto-advance cancelled")
            raise

    async def _reveal_idle_halt(self) -> None:
        """Hold the game when a round ends with zero guesses (#1012 follow-up).

        A round where nobody submitted a guess means the party is idle —
        rather than auto-advancing through the playlist unattended, let the
        round's song play out, stop the speaker, and hold on REVEAL without
        starting a new round. The host's manual "Next round" still resumes;
        a pause or game-end cancels this task, and the phase re-check makes
        a late firing a no-op.
        """
        from .state import GamePhase  # noqa: PLC0415 — avoid circular import

        poll = 2.0
        # Never poll forever if song-end is undetectable (songs run ~3-5 min).
        hard_cap = 360
        try:
            elapsed = 0.0
            while True:
                await asyncio.sleep(poll)
                elapsed += poll
                if self.phase != GamePhase.REVEAL:
                    return  # host advanced / paused / ended elsewhere
                if self._song_finished() or elapsed >= hard_cap:
                    break
            # Clear the handle before stopping so a manual start_round's
            # _cancel_auto_advance() doesn't cancel this running task.
            self._auto_advance_task = None
            # #1123: re-check phase after clearing the handle.  The admin may have
            # clicked "Next Round" in the narrow window between the song-finished
            # detection (loop exit) and this stop() call.  Without the guard,
            # stop() would silence the newly-started next song even though the
            # game has already advanced to PLAYING.
            if self.phase != GamePhase.REVEAL:
                _LOGGER.debug(
                    "Idle halt: phase left REVEAL before stop() — skipping stop"
                )
                return
            if self._media_player_service:
                try:
                    await self._media_player_service.stop()
                except Exception as err:  # noqa: BLE001 — a stop error must not raise
                    _LOGGER.warning("Idle-halt stop playback failed: %s", err)
            _LOGGER.info(
                "REVEAL idle halt — no guesses this round; game holds on REVEAL"
            )
        except asyncio.CancelledError:
            _LOGGER.debug("REVEAL idle halt cancelled")
            raise
