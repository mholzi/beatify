"""Regression tests for #2543 and #2546 (round clock vs. announcements/splash)."""

from __future__ import annotations

import asyncio

import pytest

from custom_components.beatify.game.round_manager import RoundManager


def _make_rm(now: float = 1_000_000.0) -> RoundManager:
    rm = RoundManager(lambda: now)
    rm.round_duration = 15
    return rm


class TestIntroSplashKeepsTheClock:
    """#2543: an unconfirmed intro splash must not get a running timer."""

    @pytest.mark.asyncio
    async def test_start_timer_at_playback_is_a_noop_while_splash_pending(self):
        now = 1_000_000.0
        rm = _make_rm(now)
        rm._intro_splash_pending = True
        rm.defer_deadline()
        placeholder = int(now * 1000)
        rm.deadline = placeholder

        rm.start_timer_at_playback(lambda _d: asyncio.sleep(0))

        assert rm.deadline == placeholder, "deadline was re-stamped during the splash"
        assert rm._timer_task is None, "a countdown was armed for an unplayed song"
        assert rm._deadline_deferred is True, "the deferral must survive for confirm"

    @pytest.mark.asyncio
    async def test_pending_splash_never_reports_the_deadline_as_passed(self):
        now = 1_000_000.0
        rm = _make_rm(now)
        rm._intro_splash_pending = True
        rm.defer_deadline()
        rm.deadline = int((now - 999) * 1000)

        rm.start_timer_at_playback(lambda _d: asyncio.sleep(0))

        assert rm.is_deadline_passed() is False

    @pytest.mark.asyncio
    async def test_confirm_consumes_the_deferral(self):
        now = 1_000_000.0
        rm = _make_rm(now)
        rm._intro_splash_pending = True
        rm._intro_splash_deferred_song = None
        rm.defer_deadline()

        async def _played(_song):
            return True

        await rm.confirm_intro_splash(_played, None, lambda _d: asyncio.sleep(0))
        rm.cancel_timer()

        assert rm._deadline_deferred is False
        assert rm.is_deadline_passed() is False
        assert rm.deadline == int(now * 1000) + rm.round_duration * 1000


class TestAnnouncementBudgetSurvivesTheRestamp:
    """#2546: the announcement budget must not be dropped by the re-stamp."""

    @pytest.mark.asyncio
    async def test_extra_seconds_extend_the_deadline(self):
        now = 1_000_000.0
        rm = _make_rm(now)
        rm.defer_deadline()

        rm.start_timer_at_playback(lambda _d: asyncio.sleep(0), 6.0)
        rm.cancel_timer()

        assert rm.deadline == int(now * 1000) + 15_000 + 6_000

    @pytest.mark.asyncio
    async def test_no_extra_keeps_the_plain_round_duration(self):
        now = 1_000_000.0
        rm = _make_rm(now)
        rm.defer_deadline()

        rm.start_timer_at_playback(lambda _d: asyncio.sleep(0))
        rm.cancel_timer()

        assert rm.deadline == int(now * 1000) + 15_000

    @pytest.mark.asyncio
    async def test_negative_extra_is_ignored(self):
        now = 1_000_000.0
        rm = _make_rm(now)
        rm.defer_deadline()

        rm.start_timer_at_playback(lambda _d: asyncio.sleep(0), -5.0)
        rm.cancel_timer()

        assert rm.deadline == int(now * 1000) + 15_000
