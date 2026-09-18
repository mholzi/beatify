"""Regression tests for #2875: intro splash confirmed after round_duration.

confirm_intro_splash used to clear the splash/deferral flags before awaiting
play_deferred_song and re-stamp the deadline only afterwards. While Music
Assistant confirmed playback, is_deadline_passed() compared against the
placeholder deadline from initialize_round, which a host who sat on the splash
had already run past - so the backstop ended the round as all-missed before a
note played, and the timer armed afterwards leaked into the next round.
"""

from __future__ import annotations

import asyncio

import pytest

from custom_components.beatify.game.round_manager import RoundManager


class _Clock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _init_round(rm: RoundManager, countdown, *, defer: bool) -> None:
    rm.initialize_round(
        song={"uri": "spotify:track:x", "year": 1999},
        metadata={},
        resolved_uri="spotify:track:x",
        will_defer_for_splash=defer,
        playlist_manager=None,
        challenge_manager=None,
        players={},
        timer_countdown=countdown,
        on_round_end=None,
    )


async def _sleep_forever(_delay: float) -> None:
    await asyncio.sleep(3600)


def _splash_round(clock: _Clock) -> RoundManager:
    rm = RoundManager(clock)
    rm.round_duration = 45
    rm._intro_splash_pending = True
    rm._intro_splash_deferred_song = {"uri": "spotify:track:x"}
    _init_round(rm, _sleep_forever, defer=True)
    return rm


class TestLateConfirmKeepsTheRound:
    @pytest.mark.asyncio
    async def test_deadline_not_passed_while_song_is_starting(self):
        clock = _Clock()
        rm = _splash_round(clock)
        clock.now += 60  # host sat on the splash past round_duration

        observed: list[bool] = []

        async def _slow_play(_song):
            # MA takes a while to confirm playback; the backstop ticks meanwhile.
            for _ in range(3):
                clock.now += 5
                observed.append(rm.is_deadline_passed())
                await asyncio.sleep(0)
            return True

        await rm.confirm_intro_splash(_slow_play, None, _sleep_forever)
        try:
            assert observed == [False, False, False]
            assert rm._intro_playback_pending is False
            assert rm.deadline == int(clock.now * 1000) + 45_000
            assert rm.is_deadline_passed() is False
            assert rm._timer_task is not None and not rm._timer_task.done()
        finally:
            rm.cancel_timer()
            rm._cancel_intro_timer()

    @pytest.mark.asyncio
    async def test_failed_playback_clears_the_pending_flag(self):
        clock = _Clock()
        rm = _splash_round(clock)

        async def _boom(_song):
            raise RuntimeError("speaker gone")

        with pytest.raises(RuntimeError):
            await rm.confirm_intro_splash(_boom, None, _sleep_forever)
        assert rm._intro_playback_pending is False

    @pytest.mark.asyncio
    async def test_no_timer_armed_when_round_left_playing(self):
        clock = _Clock()
        rm = _splash_round(clock)
        placeholder = rm.deadline

        async def _play(_song):
            return True

        await rm.confirm_intro_splash(
            _play, None, _sleep_forever, is_playing=lambda: False
        )
        assert rm._timer_task is None
        assert rm._intro_stop_task is None
        assert rm.deadline == placeholder


class TestNoOrphanedTimer:
    @pytest.mark.asyncio
    async def test_initialize_round_cancels_the_previous_timer(self):
        clock = _Clock()
        rm = RoundManager(clock)
        rm.round_duration = 45
        _init_round(rm, _sleep_forever, defer=False)
        stale = rm._timer_task
        assert stale is not None

        _init_round(rm, _sleep_forever, defer=True)
        await asyncio.sleep(0)
        try:
            assert stale.cancelled()
            assert rm._timer_task is None
        finally:
            rm.cancel_timer()

    @pytest.mark.asyncio
    async def test_timer_from_late_confirm_does_not_survive_next_round(self):
        clock = _Clock()
        rm = _splash_round(clock)

        async def _play(_song):
            return True

        await rm.confirm_intro_splash(_play, None, _sleep_forever)
        leaked = rm._timer_task
        rm._cancel_intro_timer()

        _init_round(rm, _sleep_forever, defer=False)
        new = rm._timer_task
        await asyncio.sleep(0)
        try:
            assert leaked is not None and leaked.cancelled()
            assert new is not leaked and not new.done()
        finally:
            rm.cancel_timer()
