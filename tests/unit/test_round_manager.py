"""Tests for RoundManager (custom_components/beatify/game/round_manager.py)."""

from __future__ import annotations

import time

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

    def test_pending_intro_splash_never_passed(self):
        """#1699: while an intro splash is pending the stamped deadline is only a
        placeholder (the timer starts on confirm_intro_splash). Report it as
        not-passed so the client watchdog can't end_round a round whose song
        never played, even if the placeholder deadline has 'elapsed'.
        """
        now = 1_000_000.0
        rm = _make_rm(time_fn=lambda: now)
        rm.deadline = int((now - 10) * 1000)  # would be 'passed' normally
        rm._intro_splash_pending = True
        assert rm.is_deadline_passed() is False
        # Once the splash is confirmed the deadline is honoured again.
        rm._intro_splash_pending = False
        assert rm.is_deadline_passed() is True


# ---------------------------------------------------------------------------
# RoundManager.cancel_timer
# ---------------------------------------------------------------------------


class TestCancelTimer:
    def test_cancel_when_no_timer(self):
        rm = _make_rm()
        rm.cancel_timer()  # Should not raise
        assert rm._timer_task is None

    async def test_cancel_clears_task(self):
        import asyncio

        # Must be an async test (asyncio_mode=auto manages the loop). A bare
        # asyncio.run() here calls set_event_loop(None) on exit, poisoning the
        # global loop policy so every later async test in the suite errors
        # with "There is no current event loop".
        rm = _make_rm()
        rm._timer_task = asyncio.create_task(asyncio.sleep(100))
        rm.cancel_timer()
        assert rm._timer_task is None


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
# RoundManager.initialize_round — extra_deadline_ms (#1211)
# ---------------------------------------------------------------------------


class TestInitializeRoundExtraDeadline:
    """extra_deadline_ms shifts the deadline so TTS overhead doesn't eat the timer."""

    def _call_initialize(self, rm, extra_deadline_ms=0):
        """Helper: call initialize_round with minimal stubs."""

        async def _noop_timer(_delay):
            pass

        rm.initialize_round(
            song={
                "year": 2000,
                "uri": "spotify:track:abc",
                "_resolved_uri": "spotify:track:abc",
            },
            metadata={
                "metadata_pending": False,
                "metadata_coro": None,
                "resolved_uri": "spotify:track:abc",
            },
            resolved_uri="spotify:track:abc",
            will_defer_for_splash=True,  # deferred — avoids creating asyncio tasks
            playlist_manager=None,
            challenge_manager=None,
            players={},
            timer_countdown=_noop_timer,
            on_round_end=None,
            extra_deadline_ms=extra_deadline_ms,
        )

    def test_zero_extra_ms_sets_normal_deadline(self):
        now = 1_000_000.0
        rm = _make_rm(time_fn=lambda: now)
        rm.round_duration = 30.0
        self._call_initialize(rm, extra_deadline_ms=0)
        expected = int(now * 1000) + 30_000
        assert rm.deadline == expected

    def test_extra_ms_extends_deadline(self):
        now = 1_000_000.0
        rm = _make_rm(time_fn=lambda: now)
        rm.round_duration = 30.0
        self._call_initialize(rm, extra_deadline_ms=10_000)
        expected = int(now * 1000) + 30_000 + 10_000
        assert rm.deadline == expected

    def test_default_extra_ms_is_zero(self):
        """Calling without extra_deadline_ms must be backward-compatible."""
        now = 1_000_000.0
        rm = _make_rm(time_fn=lambda: now)
        rm.round_duration = 30.0
        self._call_initialize(rm)  # no extra_deadline_ms arg
        expected = int(now * 1000) + 30_000
        assert rm.deadline == expected


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
