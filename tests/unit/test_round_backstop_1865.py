"""Regression tests for #1865 (server round timer did not fire).

The round timer is a single ``asyncio`` task that sleeps to the deadline and
then ends the round. When that task is cancelled, raises, or blocks in the
time-up announcement, nothing on the server notices — in the reported game the
round was only ended because a *client's* countdown nudged it
(``handle_round_timeout``), which a TV-only setup or a locked phone does not
provide.

``GameState.force_end_round_if_overdue`` is the server-side backstop, driven by
a periodic tick owned by the config entry (see ``_async_supervise_round``) and
therefore independent of the round's own task. These tests pin both halves:
when it must act, and — just as important for a thing that runs every two
seconds — when it must keep its hands off.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.beatify.const import (
    DOMAIN,
    ROUND_OVERDUE_GRACE_SECONDS,
)
from custom_components.beatify.game.state import GamePhase
from tests.conftest import make_game_state, make_songs


class _Clock:
    """Injectable time source; tests move it explicitly."""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _stub_media_service() -> MagicMock:
    svc = MagicMock()
    svc.is_available.return_value = True
    svc.play_song = AsyncMock(return_value=True)
    svc.verify_responsive = AsyncMock(return_value=(True, None))
    return svc


async def _playing_game(clock: _Clock, duration: int = 30):
    """A game sitting in PLAYING with its round timer task removed.

    Cancelling the timer task is the point: it reproduces the reported state
    (deadline set, phase PLAYING, nothing left that will ever end the round)
    without waiting on real time.
    """
    gs = make_game_state(time_fn=clock)
    gs.create_game(
        playlists=["t.json"],
        songs=make_songs(3),
        media_player="media_player.x",
        base_url="http://h",
        round_duration=duration,
    )
    gs._media_player_service = _stub_media_service()
    gs.platform = "music_assistant"
    gs.add_player("Alice", MagicMock())
    gs.get_player("Alice").connected = True
    await gs.start_round()
    assert gs.phase == GamePhase.PLAYING

    # Kill the round's own timer, the way #1865 saw it die.
    gs.cancel_timer()
    # end_round is exercised for real, but its announcements are not.
    gs.announce_time_up = AsyncMock()
    return gs


class TestBackstopActs:
    async def test_ends_a_round_left_past_its_deadline(self):
        clock = _Clock()
        gs = await _playing_game(clock)

        clock.advance(30 + ROUND_OVERDUE_GRACE_SECONDS + 0.5)
        acted = await gs.force_end_round_if_overdue()

        assert acted is True
        assert gs.phase is GamePhase.REVEAL
        gs._cancel_auto_advance()

    async def test_broadcasts_once_so_clients_leave_the_guessing_ui(self):
        """Players' screens must be pushed the REVEAL, and pushed it once.

        The push comes from ``end_round`` itself. This pins that, because the
        obvious-looking alternative — mirroring the client watchdog, which
        calls ``broadcast_state()`` after ``end_round()`` — sends the same
        state twice. An earlier draft of this fix did exactly that.
        """
        clock = _Clock()
        gs = await _playing_game(clock)
        broadcast = AsyncMock()
        gs.set_round_end_callback(broadcast)

        clock.advance(40)
        await gs.force_end_round_if_overdue()

        broadcast.assert_awaited_once()
        gs._cancel_auto_advance()

    async def test_second_call_is_a_no_op(self):
        """It runs every two seconds; it must not re-end an ended round."""
        clock = _Clock()
        gs = await _playing_game(clock)

        clock.advance(40)
        assert await gs.force_end_round_if_overdue() is True
        assert await gs.force_end_round_if_overdue() is False

        gs._cancel_auto_advance()


class TestBackstopKeepsOut:
    async def test_silent_before_the_deadline(self):
        clock = _Clock()
        gs = await _playing_game(clock)

        clock.advance(10)

        assert await gs.force_end_round_if_overdue() is False
        assert gs.phase is GamePhase.PLAYING

    async def test_silent_inside_the_grace_period(self):
        """The real timer running a little late must still be the one to fire.

        Ending the round from here first would add a second path to debug for
        a round that was about to end correctly anyway.
        """
        clock = _Clock()
        gs = await _playing_game(clock)

        clock.advance(30 + ROUND_OVERDUE_GRACE_SECONDS - 0.5)

        assert await gs.force_end_round_if_overdue() is False
        assert gs.phase is GamePhase.PLAYING

    @pytest.mark.parametrize("phase", [GamePhase.REVEAL, GamePhase.PAUSED])
    async def test_silent_outside_playing(self, phase):
        """REVEAL is a normally-ended round; PAUSED is a deliberately held one."""
        clock = _Clock()
        gs = await _playing_game(clock)
        gs.phase = phase

        clock.advance(120)

        assert await gs.force_end_round_if_overdue() is False
        assert gs.phase is phase

    async def test_silent_while_an_intro_splash_is_pending(self):
        """The deadline is only a placeholder until the splash is confirmed.

        Same blind spot #1699 closed for the client watchdog: the song has not
        played yet, so the round has not really started and must not be ended.
        """
        clock = _Clock()
        gs = await _playing_game(clock)
        gs._round_manager._intro_splash_pending = True

        clock.advance(120)

        assert await gs.force_end_round_if_overdue() is False
        assert gs.phase is GamePhase.PLAYING
        gs._round_manager._intro_splash_pending = False

    async def test_silent_with_no_game_running(self):
        """A fresh GameState has no deadline; the tick must not throw."""
        gs = make_game_state()

        assert await gs.force_end_round_if_overdue() is False


class TestSupervisorTick:
    """The wiring in ``__init__.py`` that drives the backstop."""

    async def test_resolves_the_game_from_hass_data_each_tick(self):
        """It must not close over a GameState an entry reload has replaced."""
        from custom_components.beatify import _async_supervise_round

        stale, fresh = MagicMock(), MagicMock()
        stale.force_end_round_if_overdue = AsyncMock(return_value=False)
        fresh.force_end_round_if_overdue = AsyncMock(return_value=False)

        hass = MagicMock()
        hass.data = {DOMAIN: {"game": stale}}
        await _async_supervise_round(hass)

        hass.data = {DOMAIN: {"game": fresh}}
        await _async_supervise_round(hass)

        stale.force_end_round_if_overdue.assert_awaited_once()
        fresh.force_end_round_if_overdue.assert_awaited_once()

    @pytest.mark.parametrize("data", [{}, {DOMAIN: {}}, {DOMAIN: "not-a-dict"}])
    async def test_tolerates_a_half_set_up_or_unloaded_entry(self, data):
        """The tick outlives the entry's own data; it must not raise."""
        from custom_components.beatify import _async_supervise_round

        hass = MagicMock()
        hass.data = data

        await _async_supervise_round(hass)  # must not raise

    async def test_swallows_errors_so_it_keeps_ticking(self):
        """A stuck round must not also emit a traceback every two seconds."""
        from custom_components.beatify import _async_supervise_round

        game = MagicMock()
        game.force_end_round_if_overdue = AsyncMock(side_effect=RuntimeError("boom"))
        hass = MagicMock()
        hass.data = {DOMAIN: {"game": game}}

        await _async_supervise_round(hass)  # must not raise
