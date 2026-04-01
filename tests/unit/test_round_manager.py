"""Tests for RoundManager (custom_components/beatify/game/round_manager.py)."""

from __future__ import annotations

import time

import pytest

from custom_components.beatify.const import DEFAULT_ROUND_DURATION
from custom_components.beatify.game.round_manager import RoundManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rm(time_fn=None) -> RoundManager:
    """Create a fresh RoundManager with optional injected time function."""
    return RoundManager(time_fn or time.time)


# ---------------------------------------------------------------------------
# RoundManager.__init__
# ---------------------------------------------------------------------------


class TestRoundManagerInit:
    def test_defaults(self):
        rm = _make_rm()
        assert rm.round == 0
        assert rm.total_rounds == 0
        assert rm.deadline is None
        assert rm.current_song is None
        assert rm.last_round is False
        assert rm.round_start_time is None
        assert rm.round_duration == DEFAULT_ROUND_DURATION
        assert rm.song_stopped is False
        assert rm.intro_mode_enabled is False
        assert rm.is_intro_round is False
        assert rm.intro_stopped is False
        assert rm.metadata_pending is False
        assert rm._early_reveal is False
        assert rm._intro_splash_pending is False
        assert rm._intro_splash_shown is False
        assert rm.round_analytics is None


# ---------------------------------------------------------------------------
# RoundManager.is_deadline_passed
# ---------------------------------------------------------------------------


class TestIsDeadlinePassed:
    def test_no_deadline_returns_false(self):
        rm = _make_rm()
        assert rm.is_deadline_passed() is False

    def test_past_deadline_returns_true(self):
        now = 1_000_000.0
        rm = _make_rm(time_fn=lambda: now)
        rm.deadline = int((now - 10) * 1000)
        assert rm.is_deadline_passed() is True

    def test_future_deadline_returns_false(self):
        now = 1_000_000.0
        rm = _make_rm(time_fn=lambda: now)
        rm.deadline = int((now + 30) * 1000)
        assert rm.is_deadline_passed() is False


# ---------------------------------------------------------------------------
# RoundManager.cancel_timer
# ---------------------------------------------------------------------------


class TestCancelTimer:
    def test_cancel_when_no_timer(self):
        rm = _make_rm()
        rm.cancel_timer()  # Should not raise
        assert rm._timer_task is None

    def test_cancel_clears_task(self):
        import asyncio

        async def _run():
            rm = _make_rm()
            rm._timer_task = asyncio.create_task(asyncio.sleep(100))
            rm.cancel_timer()
            assert rm._timer_task is None

        asyncio.run(_run())


# ---------------------------------------------------------------------------
# RoundManager.reset
# ---------------------------------------------------------------------------


class TestRoundManagerReset:
    def test_reset_clears_round_state(self):
        rm = _make_rm()
        rm.round = 5
        rm.total_rounds = 10
        rm.deadline = 99999
        rm.current_song = {"year": 2000}
        rm.last_round = True
        rm.round_start_time = 1000.0
        rm.round_duration = 15
        rm.song_stopped = True
        rm._early_reveal = True
        rm.round_analytics = {"something": True}
        rm.metadata_pending = True
        rm.is_intro_round = True
        rm.intro_stopped = True
        rm._intro_round_start_time = 500.0
        rm._intro_splash_shown = True
        rm._intro_splash_pending = True
        rm._intro_splash_deferred_song = {"uri": "test"}

        rm.reset()

        assert rm.round == 0
        assert rm.total_rounds == 0
        assert rm.deadline is None
        assert rm.current_song is None
        assert rm.last_round is False
        assert rm.round_start_time is None
        assert rm.round_duration == DEFAULT_ROUND_DURATION
        assert rm.song_stopped is False
        assert rm._early_reveal is False
        assert rm.round_analytics is None
        assert rm.metadata_pending is False
        assert rm.is_intro_round is False
        assert rm.intro_stopped is False
        assert rm._intro_round_start_time is None
        assert rm._intro_splash_shown is False
        assert rm._intro_splash_pending is False
        assert rm._intro_splash_deferred_song is None


# ---------------------------------------------------------------------------
# RoundManager.prepare_intro_round
# ---------------------------------------------------------------------------


class TestPrepareIntroRound:
    def test_disabled_returns_false(self):
        rm = _make_rm()
        rm.intro_mode_enabled = False
        rm.round = 5
        result = rm.prepare_intro_round({"duration_ms": 300000}, None)
        assert result is False
        assert rm.is_intro_round is False

    def test_too_early_returns_false(self):
        rm = _make_rm()
        rm.intro_mode_enabled = True
        rm.round = 1  # Must be >= 3
        result = rm.prepare_intro_round({"duration_ms": 300000}, None)
        assert result is False
