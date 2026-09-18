"""#2883 — a pause stops the round clock.

``pause_game`` used to cancel the timer task but leave ``deadline`` running, so
``resume_game`` computed ``deadline - now`` and a pause longer than the time
left ended the round on resume: phase straight to REVEAL, every player without
a banked guess scored as missed. The live test of v4.7.2-rc1 hit it with a
15 s round and a 20 s pizza pause.

The pause now freezes the time left and the resume re-stamps the deadline from
it, for every pause reason.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.beatify.const import (
    ADMIN_DISCONNECT_PAUSE_REASON,
    HOST_PAUSE_REASON,
    HOST_PAUSE_REASON_FOOD,
)
from custom_components.beatify.game.state import GamePhase
from tests.conftest import make_songs
from tests.unit.conftest import make_game_state

ROUND_DURATION = 15.0
T0 = 1_000_000.0


class _Clock:
    def __init__(self, t: float = T0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def _playing_round(clock: _Clock):
    """A game one round in: PLAYING, 15 s round started at ``T0``."""
    state = make_game_state(time_fn=clock)
    state.create_game(
        playlists=["test.json"],
        songs=make_songs(5),
        media_player="media_player.test",
        base_url="http://localhost:8123",
    )
    state.add_player("Host", MagicMock())
    state.set_admin("Host")
    state.add_player("Guest", MagicMock())
    state.phase = GamePhase.PLAYING
    state.current_song = {"year": 1984, "title": "Big in Japan", "artist": "Alphaville"}
    state._round_manager.round_duration = ROUND_DURATION
    state.round_start_time = T0
    state.deadline = int(T0 * 1000) + int(ROUND_DURATION * 1000)
    speaker = MagicMock()
    speaker.stop = AsyncMock()
    speaker.play = AsyncMock()
    state._media_player_service = speaker
    return state


def _seconds_left(state, clock: _Clock) -> float:
    return (state.deadline - int(clock() * 1000)) / 1000.0


async def _cleanup(state) -> None:
    state.cancel_timer()
    state._round_manager._cancel_intro_timer()
    await asyncio.sleep(0)


class TestLongPauseKeepsTheRound:
    @pytest.mark.parametrize(
        "reason",
        [HOST_PAUSE_REASON, HOST_PAUSE_REASON_FOOD, ADMIN_DISCONNECT_PAUSE_REASON],
    )
    async def test_resume_after_a_pause_longer_than_the_round(self, reason):
        clock = _Clock()
        state = _playing_round(clock)
        end_round = AsyncMock()
        state.end_round = end_round

        clock.t = T0 + 1.0
        assert await state.pause_game(reason)
        clock.t = T0 + 1.0 + 60.0  # four times the round, e.g. a pizza break
        assert await state.resume_game()

        assert state.phase == GamePhase.PLAYING
        assert _seconds_left(state, clock) == pytest.approx(ROUND_DURATION - 1.0)
        assert state.is_deadline_passed() is False
        end_round.assert_not_awaited()
        assert state._round_manager._timer_task is not None
        state._media_player_service.play.assert_awaited_once_with()
        await _cleanup(state)

    async def test_nobody_is_scored_as_missed(self):
        """Real end_round, not a mock: the resume must not reach it at all."""
        clock = _Clock()
        state = _playing_round(clock)

        clock.t = T0 + 1.0
        await state.pause_game(HOST_PAUSE_REASON_FOOD)
        clock.t = T0 + 21.4  # the rc1 repro: 20.4 s pause on a 15 s round
        await state.resume_game()

        assert state.phase == GamePhase.PLAYING
        for player in state.players.values():
            assert player.missed_round is False
            assert player.score == 0
        await _cleanup(state)

    async def test_the_new_deadline_is_what_the_clients_get(self):
        """The broadcast after resume serializes ``deadline`` / seconds left."""
        clock = _Clock()
        state = _playing_round(clock)

        clock.t = T0 + 1.0
        await state.pause_game(HOST_PAUSE_REASON)
        clock.t = T0 + 50.0
        await state.resume_game()

        payload = state.get_state()
        assert payload["deadline"] == state.deadline
        assert payload["deadline"] == int(clock() * 1000) + 14_000
        await _cleanup(state)

    async def test_the_pause_does_not_count_against_the_speed_bonus(self):
        """Round start and guesses banked before the pause move with the clock."""
        clock = _Clock()
        state = _playing_round(clock)
        guest = state.get_player("Guest")
        guest.submit_guess(1984, T0 + 0.5)

        clock.t = T0 + 1.0
        await state.pause_game(HOST_PAUSE_REASON)
        clock.t = T0 + 31.0
        await state.resume_game()

        assert state.round_start_time == pytest.approx(T0 + 30.0)
        assert guest.submission_time - state.round_start_time == pytest.approx(0.5)
        await _cleanup(state)


class TestShortPauseUnchanged:
    async def test_a_two_second_pause_resumes_with_the_same_time_left(self):
        clock = _Clock()
        state = _playing_round(clock)

        clock.t = T0 + 5.0
        await state.pause_game(HOST_PAUSE_REASON)
        clock.t = T0 + 7.0
        await state.resume_game()

        assert state.phase == GamePhase.PLAYING
        assert _seconds_left(state, clock) == pytest.approx(ROUND_DURATION - 5.0)
        await _cleanup(state)

    async def test_a_round_already_out_of_time_still_ends(self):
        """Pausing a round whose clock had already run out ends it on resume."""
        clock = _Clock()
        state = _playing_round(clock)
        state.end_round = AsyncMock()

        clock.t = T0 + ROUND_DURATION + 0.5
        await state.pause_game(HOST_PAUSE_REASON)
        clock.t += 1.0
        await state.resume_game()

        state.end_round.assert_awaited_once()


class TestOtherPhasesUnchanged:
    async def test_reveal_pause_takes_no_round_clock_snapshot(self):
        clock = _Clock()
        state = _playing_round(clock)
        state.phase = GamePhase.REVEAL
        old_deadline = state.deadline

        await state.pause_game(HOST_PAUSE_REASON)
        assert state._paused_round_remaining_ms is None
        clock.t += 60.0
        state._schedule_song_end_auto_advance = MagicMock()
        await state.resume_game()

        assert state.phase == GamePhase.REVEAL
        assert state.deadline == old_deadline


class TestPauseWhileIntroSongStarting:
    """#2875 window: confirm_intro_splash is awaiting play_deferred_song."""

    async def test_resume_gets_a_full_round(self):
        clock = _Clock()
        state = _playing_round(clock)
        rm = state._round_manager
        rm.is_intro_round = True
        # initialize_round's placeholder, long past: the host sat on the splash.
        state.deadline = int((T0 - 100.0) * 1000)
        rm._intro_splash_pending = True

        started = asyncio.Event()
        release = asyncio.Event()

        async def _slow_play(_song):
            started.set()
            await release.wait()
            return True

        state.play_deferred_song = _slow_play
        rm._intro_splash_deferred_song = state.current_song
        confirm = asyncio.create_task(state.confirm_intro_splash())
        await started.wait()
        assert rm._intro_playback_pending is True

        clock.t = T0 + 2.0
        await state.pause_game(HOST_PAUSE_REASON)
        release.set()
        await confirm  # sees PAUSED, arms no timer (#2875)
        assert rm._timer_task is None

        clock.t = T0 + 40.0
        state.end_round = AsyncMock()
        await state.resume_game()

        assert state.phase == GamePhase.PLAYING
        state.end_round.assert_not_awaited()
        assert _seconds_left(state, clock) == pytest.approx(ROUND_DURATION)
        assert state.round_start_time == pytest.approx(clock())
        assert rm._intro_round_start_time == pytest.approx(clock())
        assert rm._timer_task is not None
        assert rm._intro_stop_task is not None
        await _cleanup(state)
