"""#2886 — a pause while the intro song is still starting controls the media.

``confirm_intro_splash`` waits for Music Assistant to confirm the deferred
intro song (2-25 s). A ``pause_game`` from a second admin device inside that
window used to send ``media_stop`` straight into MA's start. Depending on the
timing MA either ignored it (the intro then played to the room through the
whole pause) or it killed the start (25 s later the confirm failed with
misleading provider ERRORs, and the round after resume ran in silence, since
resume only sent a bare ``media_play``).

Now the pause leaves the pending start alone, ``confirm_intro_splash`` stops
the song as soon as the start has settled, and the resume plays the deferred
song again from the beginning.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.beatify.const import HOST_PAUSE_REASON
from custom_components.beatify.game.state import GamePhase
from tests.conftest import make_songs
from tests.unit.conftest import make_game_state

ROUND_DURATION = 15.0
T0 = 1_000_000.0
SONG = {"year": 1984, "title": "Two Hearts", "artist": "Phil Collins"}


class _Clock:
    def __init__(self, t: float = T0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


def _intro_round_awaiting_confirm(clock: _Clock):
    state = make_game_state(time_fn=clock)
    state.create_game(
        playlists=["test.json"],
        songs=make_songs(5),
        media_player="media_player.test",
        base_url="http://localhost:8123",
    )
    state.add_player("Host", MagicMock())
    state.set_admin("Host")
    state.phase = GamePhase.PLAYING
    state.current_song = dict(SONG)
    rm = state._round_manager
    rm.round_duration = ROUND_DURATION
    rm.is_intro_round = True
    state.round_start_time = T0
    state.deadline = int(T0 * 1000) + int(ROUND_DURATION * 1000)
    rm._intro_splash_pending = True
    rm._intro_splash_deferred_song = dict(SONG)

    events: list[str] = []
    speaker = MagicMock()
    speaker.stop = AsyncMock(side_effect=lambda: events.append("stop"))
    speaker.play = AsyncMock(side_effect=lambda **_: events.append("play"))
    state._media_player_service = speaker
    return state, events


async def _cleanup(state) -> None:
    state.cancel_timer()
    state._round_manager._cancel_intro_timer()
    await asyncio.sleep(0)


class TestPauseWhileIntroSongStarts:
    async def _pause_inside_the_start(self, state, events, clock):
        rm = state._round_manager
        started = asyncio.Event()
        release = asyncio.Event()
        plays: list[dict] = []

        async def _slow_play(song):
            plays.append(song)
            events.append("play_song")
            if len(plays) == 1:
                started.set()
                await release.wait()
            events.append("confirmed")
            return True

        state.play_deferred_song = _slow_play
        confirm = asyncio.create_task(state.confirm_intro_splash())
        await started.wait()
        assert rm._intro_playback_pending is True

        clock.t = T0 + 0.4
        assert await state.pause_game(HOST_PAUSE_REASON) is True
        return confirm, release, plays

    async def test_no_stop_is_sent_into_the_pending_start(self):
        clock = _Clock()
        state, events = _intro_round_awaiting_confirm(clock)
        confirm, release, _ = await self._pause_inside_the_start(state, events, clock)

        # A media_stop here races MA's start: ignored or fatal to it.
        assert "stop" not in events

        release.set()
        await confirm
        await _cleanup(state)

    async def test_the_song_is_stopped_once_the_start_settles(self):
        clock = _Clock()
        state, events = _intro_round_awaiting_confirm(clock)
        confirm, release, _ = await self._pause_inside_the_start(state, events, clock)

        release.set()
        await confirm

        assert state.phase == GamePhase.PAUSED
        assert events == ["play_song", "confirmed", "stop"]
        assert state._round_manager._timer_task is None
        await _cleanup(state)

    async def test_resume_restarts_the_intro_song_from_the_start(self):
        clock = _Clock()
        state, events = _intro_round_awaiting_confirm(clock)
        confirm, release, plays = await self._pause_inside_the_start(
            state, events, clock
        )
        release.set()
        await confirm

        clock.t = T0 + 20.0
        state.end_round = AsyncMock()
        assert await state.resume_game() is True

        rm = state._round_manager
        assert state.phase == GamePhase.PLAYING
        # The deferred song is played again (a fresh start at 0), not a bare
        # media_play that MA ignores or that has nothing to resume.
        assert len(plays) == 2
        assert plays[1]["title"] == SONG["title"]
        assert "play" not in events
        state.end_round.assert_not_awaited()
        assert (state.deadline - int(clock() * 1000)) / 1000.0 == pytest.approx(
            ROUND_DURATION
        )
        assert rm._timer_task is not None
        assert rm._intro_stop_task is not None
        assert not rm._intro_splash_pending
        await _cleanup(state)

    async def test_resume_before_the_start_settles_leaves_it_to_confirm(self):
        clock = _Clock()
        state, events = _intro_round_awaiting_confirm(clock)
        confirm, release, plays = await self._pause_inside_the_start(
            state, events, clock
        )

        clock.t = T0 + 1.0
        assert await state.resume_game() is True
        assert state.phase == GamePhase.PLAYING

        release.set()
        await confirm

        rm = state._round_manager
        # One start, no stop, no bare play: the pending start just carries on.
        assert len(plays) == 1
        assert events == ["play_song", "confirmed"]
        assert rm._timer_task is not None
        await _cleanup(state)
