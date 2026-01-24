"""Tests for guess submission handling (Story 4.3, 4.4)."""

from __future__ import annotations

import sys
import time
from unittest.mock import MagicMock

# Mock homeassistant module before importing beatify
sys.modules["homeassistant"] = MagicMock()
sys.modules["homeassistant.core"] = MagicMock()
sys.modules["homeassistant.components.http"] = MagicMock()
sys.modules["homeassistant.helpers.aiohttp_client"] = MagicMock()


import pytest

from custom_components.beatify.game.player import PlayerSession


class TestPlayerSessionSubmission:
    """Tests for PlayerSession submission methods."""

    def test_submit_guess_sets_submitted_flag(self):
        """submit_guess sets submitted to True."""
        ws = MagicMock()
        player = PlayerSession(name="Test", ws=ws)

        assert player.submitted is False
        player.submit_guess(year=1985, timestamp=1000.0)
        assert player.submitted is True

    def test_submit_guess_records_year(self):
        """submit_guess records the guessed year."""
        ws = MagicMock()
        player = PlayerSession(name="Test", ws=ws)

        player.submit_guess(year=1985, timestamp=1000.0)
        assert player.current_guess == 1985

    def test_submit_guess_records_timestamp(self):
        """submit_guess records the submission timestamp."""
        ws = MagicMock()
        player = PlayerSession(name="Test", ws=ws)

        player.submit_guess(year=1985, timestamp=1234.567)
        assert player.submission_time == 1234.567

    def test_reset_round_clears_submission_state(self):
        """reset_round clears all submission-related state."""
        ws = MagicMock()
        player = PlayerSession(name="Test", ws=ws)

        # Submit a guess
        player.submit_guess(year=1985, timestamp=1000.0)
        player.round_score = 100
        player.years_off = 2
        player.missed_round = False

        # Reset for new round
        player.reset_round()

        assert player.submitted is False
        assert player.current_guess is None
        assert player.submission_time is None
        assert player.round_score == 0
        assert player.years_off is None
        assert player.missed_round is False

    def test_reset_round_preserves_total_score(self):
        """reset_round does not affect total score or streak."""
        ws = MagicMock()
        player = PlayerSession(name="Test", ws=ws, score=500, streak=3)

        player.submit_guess(year=1985, timestamp=1000.0)
        player.reset_round()

        assert player.score == 500
        assert player.streak == 3


class TestPlayerSessionDefaults:
    """Tests for PlayerSession default values."""

    def test_new_player_not_submitted(self):
        """New player has submitted=False by default."""
        ws = MagicMock()
        player = PlayerSession(name="Test", ws=ws)

        assert player.submitted is False

    def test_new_player_no_guess(self):
        """New player has current_guess=None by default."""
        ws = MagicMock()
        player = PlayerSession(name="Test", ws=ws)

        assert player.current_guess is None

    def test_new_player_no_submission_time(self):
        """New player has submission_time=None by default."""
        ws = MagicMock()
        player = PlayerSession(name="Test", ws=ws)

        assert player.submission_time is None


class TestSubmissionValidation:
    """Tests for submission timing validation."""

    def test_submission_before_deadline_valid(self):
        """Submission before deadline should be accepted."""
        # This tests the logic that would be in websocket handler
        deadline_ms = int((time.time() + 30) * 1000)  # 30 seconds from now
        now_ms = int(time.time() * 1000)

        is_expired = now_ms > deadline_ms
        assert is_expired is False

    def test_submission_after_deadline_invalid(self):
        """Submission after deadline should be rejected."""
        # This tests the logic that would be in websocket handler
        deadline_ms = int((time.time() - 5) * 1000)  # 5 seconds ago
        now_ms = int(time.time() * 1000)

        is_expired = now_ms > deadline_ms
        assert is_expired is True


class TestYearValidation:
    """Tests for year range validation."""

    def test_year_within_range_valid(self):
        """Year within 1950-2025 range is valid."""
        from custom_components.beatify.const import YEAR_MAX, YEAR_MIN

        valid_years = [1950, 1985, 2000, 2025]
        for year in valid_years:
            is_valid = isinstance(year, int) and YEAR_MIN <= year <= YEAR_MAX
            assert is_valid is True, f"Year {year} should be valid"

    def test_year_below_range_invalid(self):
        """Year below 1950 is invalid."""
        from custom_components.beatify.const import YEAR_MAX, YEAR_MIN

        year = 1949
        is_valid = isinstance(year, int) and YEAR_MIN <= year <= YEAR_MAX
        assert is_valid is False

    def test_year_above_range_invalid(self):
        """Year above 2025 is invalid."""
        from custom_components.beatify.const import YEAR_MAX, YEAR_MIN

        year = 2026
        is_valid = isinstance(year, int) and YEAR_MIN <= year <= YEAR_MAX
        assert is_valid is False

    def test_non_integer_year_invalid(self):
        """Non-integer year is invalid."""
        from custom_components.beatify.const import YEAR_MAX, YEAR_MIN

        year = "1985"
        is_valid = isinstance(year, int) and YEAR_MIN <= year <= YEAR_MAX
        assert is_valid is False


class TestAllSubmitted:
    """Tests for all_submitted() method (Story 4.4)."""

    def test_all_submitted_returns_false_when_some_not_submitted(self):
        """all_submitted returns False when some players haven't submitted."""
        from custom_components.beatify.game.state import GameState

        state = GameState()
        ws1 = MagicMock()
        ws2 = MagicMock()

        state.add_player("Alice", ws1)
        state.add_player("Bob", ws2)

        # Only Alice submits
        state.players["Alice"].submitted = True

        assert state.all_submitted() is False

    def test_all_submitted_returns_true_when_all_submitted(self):
        """all_submitted returns True when all players have submitted."""
        from custom_components.beatify.game.state import GameState

        state = GameState()
        ws1 = MagicMock()
        ws2 = MagicMock()

        state.add_player("Alice", ws1)
        state.add_player("Bob", ws2)

        # Both submit
        state.players["Alice"].submitted = True
        state.players["Bob"].submitted = True

        assert state.all_submitted() is True

    def test_all_submitted_returns_false_for_empty_player_list(self):
        """all_submitted returns False when no players."""
        from custom_components.beatify.game.state import GameState

        state = GameState()
        assert state.all_submitted() is False

    def test_all_submitted_ignores_disconnected_players(self):
        """all_submitted only considers connected players."""
        from custom_components.beatify.game.state import GameState

        state = GameState()
        ws1 = MagicMock()
        ws2 = MagicMock()

        state.add_player("Alice", ws1)
        state.add_player("Bob", ws2)

        # Alice submits, Bob disconnects without submitting
        state.players["Alice"].submitted = True
        state.players["Bob"].connected = False

        # Should be True since only connected player (Alice) has submitted
        assert state.all_submitted() is True

    def test_all_submitted_single_player(self):
        """all_submitted works with single player."""
        from custom_components.beatify.game.state import GameState

        state = GameState()
        ws = MagicMock()

        state.add_player("Solo", ws)
        state.players["Solo"].submitted = True

        assert state.all_submitted() is True
