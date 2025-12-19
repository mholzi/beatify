"""
Unit Tests: Scoring Logic (Story 4.6)

Tests the MVP accuracy-based scoring system:
- Exact match: 10 points
- Within ±3 years: 5 points
- Within ±5 years: 1 point
- More than 5 years off: 0 points

NOTE: Advanced scoring (speed bonus, streaks, betting) is in Epic 5.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

# Mock homeassistant before importing beatify modules
sys.modules["homeassistant"] = MagicMock()
sys.modules["homeassistant.core"] = MagicMock()
sys.modules["homeassistant.components"] = MagicMock()
sys.modules["homeassistant.components.http"] = MagicMock()

from custom_components.beatify.game.scoring import (
    calculate_accuracy_score,
    calculate_years_off_text,
)


# =============================================================================
# EXACT MATCH TESTS (10 points)
# =============================================================================


@pytest.mark.unit
class TestExactMatch:
    """Tests for exact year matches (10 base points)."""

    def test_exact_match_returns_10(self):
        """Exact match (0 years off) returns 10 points."""
        assert calculate_accuracy_score(1985, 1985) == 10

    def test_exact_match_various_years(self):
        """Exact match works for any year."""
        assert calculate_accuracy_score(1950, 1950) == 10
        assert calculate_accuracy_score(2000, 2000) == 10
        assert calculate_accuracy_score(2025, 2025) == 10


# =============================================================================
# CLOSE MATCH TESTS (±3 years = 5 points)
# =============================================================================


@pytest.mark.unit
class TestCloseMatch:
    """Tests for ±3 year matches (5 base points)."""

    def test_1_year_off_returns_5(self):
        """1 year off returns 5 points."""
        assert calculate_accuracy_score(1986, 1985) == 5
        assert calculate_accuracy_score(1984, 1985) == 5

    def test_2_years_off_returns_5(self):
        """2 years off returns 5 points."""
        assert calculate_accuracy_score(1987, 1985) == 5
        assert calculate_accuracy_score(1983, 1985) == 5

    def test_3_years_off_returns_5(self):
        """3 years off returns 5 points (boundary of ±3)."""
        assert calculate_accuracy_score(1988, 1985) == 5
        assert calculate_accuracy_score(1982, 1985) == 5


# =============================================================================
# NEAR MATCH TESTS (±5 years = 1 point)
# =============================================================================


@pytest.mark.unit
class TestNearMatch:
    """Tests for ±4-5 year matches (1 base point)."""

    def test_4_years_off_returns_1(self):
        """4 years off returns 1 point."""
        assert calculate_accuracy_score(1989, 1985) == 1
        assert calculate_accuracy_score(1981, 1985) == 1

    def test_5_years_off_returns_1(self):
        """5 years off returns 1 point (boundary of ±5)."""
        assert calculate_accuracy_score(1990, 1985) == 1
        assert calculate_accuracy_score(1980, 1985) == 1


# =============================================================================
# WRONG GUESS TESTS (>5 years = 0 points)
# =============================================================================


@pytest.mark.unit
class TestWrongGuess:
    """Tests for wrong guesses (>5 years off)."""

    def test_6_years_off_returns_0(self):
        """6 years off returns 0 points."""
        assert calculate_accuracy_score(1991, 1985) == 0
        assert calculate_accuracy_score(1979, 1985) == 0

    def test_10_years_off_returns_0(self):
        """10 years off returns 0 points."""
        assert calculate_accuracy_score(1995, 1985) == 0
        assert calculate_accuracy_score(1975, 1985) == 0

    def test_100_years_off_returns_0(self):
        """100 years off returns 0 points."""
        assert calculate_accuracy_score(2085, 1985) == 0
        assert calculate_accuracy_score(1885, 1985) == 0


# =============================================================================
# BOUNDARY TESTS
# =============================================================================


@pytest.mark.unit
class TestScoringBoundaries:
    """Tests for scoring boundary conditions."""

    def test_boundary_3_to_4_years(self):
        """Test transition from 5 points (3 years) to 1 point (4 years)."""
        # 3 years off = 5 points
        assert calculate_accuracy_score(1988, 1985) == 5
        # 4 years off = 1 point
        assert calculate_accuracy_score(1989, 1985) == 1

    def test_boundary_5_to_6_years(self):
        """Test transition from 1 point (5 years) to 0 points (6 years)."""
        # 5 years off = 1 point
        assert calculate_accuracy_score(1990, 1985) == 1
        # 6 years off = 0 points
        assert calculate_accuracy_score(1991, 1985) == 0


# =============================================================================
# YEARS OFF TEXT TESTS
# =============================================================================


@pytest.mark.unit
class TestYearsOffText:
    """Tests for calculate_years_off_text function."""

    def test_exact_returns_exact_text(self):
        """0 years off returns 'Exact!'."""
        assert calculate_years_off_text(0) == "Exact!"

    def test_1_year_singular(self):
        """1 year off uses singular form."""
        assert calculate_years_off_text(1) == "1 year off"

    def test_2_years_plural(self):
        """2+ years off uses plural form."""
        assert calculate_years_off_text(2) == "2 years off"

    def test_10_years_plural(self):
        """10 years off uses plural form."""
        assert calculate_years_off_text(10) == "10 years off"

    def test_100_years_plural(self):
        """Large values use plural form."""
        assert calculate_years_off_text(100) == "100 years off"


# =============================================================================
# INTEGRATION TESTS: SCORING WITH GAMESTATE
# =============================================================================


@pytest.mark.unit
class TestScoringIntegration:
    """Tests for scoring integration with GameState."""

    @pytest.mark.asyncio
    async def test_end_round_calculates_scores(self):
        """end_round calculates accuracy scores for submitted players."""
        from custom_components.beatify.game.state import GameState

        state = GameState(time_fn=lambda: 1000.0)
        songs = [{"year": 1985, "uri": "spotify:track:1", "fun_fact": "Fact 1"}]
        state.create_game(
            playlists=["playlist1.json"],
            songs=songs,
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        # Add player and simulate submission
        mock_ws = MagicMock()
        state.add_player("TestPlayer", mock_ws)
        state.players["TestPlayer"].submit_guess(year=1985, timestamp=1000.0)

        # Set current song (normally done by start_round)
        state.current_song = {"year": 1985, "uri": "spotify:track:1"}

        await state.end_round()

        # Check exact match score
        player = state.players["TestPlayer"]
        assert player.round_score == 10
        assert player.years_off == 0
        assert player.missed_round is False

    @pytest.mark.asyncio
    async def test_end_round_calculates_close_match(self):
        """end_round calculates close match (5 points)."""
        from custom_components.beatify.game.state import GameState

        state = GameState(time_fn=lambda: 1000.0)
        songs = [{"year": 1985, "uri": "spotify:track:1", "fun_fact": "Fact 1"}]
        state.create_game(
            playlists=["playlist1.json"],
            songs=songs,
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        mock_ws = MagicMock()
        state.add_player("TestPlayer", mock_ws)
        state.players["TestPlayer"].submit_guess(year=1988, timestamp=1000.0)  # 3 years off
        state.current_song = {"year": 1985, "uri": "spotify:track:1"}

        await state.end_round()

        player = state.players["TestPlayer"]
        assert player.round_score == 5
        assert player.years_off == 3

    @pytest.mark.asyncio
    async def test_end_round_updates_total_score(self):
        """end_round adds round_score to total score."""
        from custom_components.beatify.game.state import GameState

        state = GameState(time_fn=lambda: 1000.0)
        songs = [{"year": 1985, "uri": "spotify:track:1", "fun_fact": "Fact 1"}]
        state.create_game(
            playlists=["playlist1.json"],
            songs=songs,
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        mock_ws = MagicMock()
        state.add_player("TestPlayer", mock_ws)
        state.players["TestPlayer"].score = 50  # Pre-existing score
        state.players["TestPlayer"].submit_guess(year=1985, timestamp=1000.0)
        state.current_song = {"year": 1985, "uri": "spotify:track:1"}

        await state.end_round()

        # Total should be previous (50) + round (10) = 60
        assert state.players["TestPlayer"].score == 60

    @pytest.mark.asyncio
    async def test_end_round_increments_streak_on_points(self):
        """end_round increments streak when player earns points."""
        from custom_components.beatify.game.state import GameState

        state = GameState(time_fn=lambda: 1000.0)
        songs = [{"year": 1985, "uri": "spotify:track:1", "fun_fact": "Fact 1"}]
        state.create_game(
            playlists=["playlist1.json"],
            songs=songs,
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        mock_ws = MagicMock()
        state.add_player("TestPlayer", mock_ws)
        state.players["TestPlayer"].streak = 2
        state.players["TestPlayer"].submit_guess(year=1988, timestamp=1000.0)  # 3 years off
        state.current_song = {"year": 1985, "uri": "spotify:track:1"}

        await state.end_round()

        # Streak should increment (earned 5 points)
        assert state.players["TestPlayer"].streak == 3

    @pytest.mark.asyncio
    async def test_end_round_breaks_streak_on_zero_points(self):
        """end_round resets streak when player earns 0 points."""
        from custom_components.beatify.game.state import GameState

        state = GameState(time_fn=lambda: 1000.0)
        songs = [{"year": 1985, "uri": "spotify:track:1", "fun_fact": "Fact 1"}]
        state.create_game(
            playlists=["playlist1.json"],
            songs=songs,
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        mock_ws = MagicMock()
        state.add_player("TestPlayer", mock_ws)
        state.players["TestPlayer"].streak = 5
        state.players["TestPlayer"].submit_guess(year=1970, timestamp=1000.0)  # 15 years off
        state.current_song = {"year": 1985, "uri": "spotify:track:1"}

        await state.end_round()

        # Streak should reset (earned 0 points)
        assert state.players["TestPlayer"].streak == 0

    @pytest.mark.asyncio
    async def test_end_round_non_submitter_gets_zero(self):
        """end_round gives non-submitters 0 points and breaks streak."""
        from custom_components.beatify.game.state import GameState

        state = GameState(time_fn=lambda: 1000.0)
        songs = [{"year": 1985, "uri": "spotify:track:1", "fun_fact": "Fact 1"}]
        state.create_game(
            playlists=["playlist1.json"],
            songs=songs,
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        mock_ws = MagicMock()
        state.add_player("TestPlayer", mock_ws)
        state.players["TestPlayer"].streak = 3
        state.players["TestPlayer"].score = 50
        # No submission
        state.current_song = {"year": 1985, "uri": "spotify:track:1"}

        await state.end_round()

        player = state.players["TestPlayer"]
        assert player.round_score == 0
        assert player.years_off is None
        assert player.missed_round is True
        assert player.streak == 0
        assert player.score == 50  # Total unchanged


# =============================================================================
# REVEAL STATE TESTS
# =============================================================================


@pytest.mark.unit
class TestRevealState:
    """Tests for reveal state including scoring data."""

    @pytest.mark.asyncio
    async def test_reveal_state_includes_years_off(self):
        """Reveal state includes years_off for each player."""
        from custom_components.beatify.game.state import GameState

        state = GameState(time_fn=lambda: 1000.0)
        songs = [{"year": 1985, "uri": "spotify:track:1", "fun_fact": "Fact 1"}]
        state.create_game(
            playlists=["playlist1.json"],
            songs=songs,
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        mock_ws = MagicMock()
        state.add_player("TestPlayer", mock_ws)
        state.players["TestPlayer"].submit_guess(year=1988, timestamp=1000.0)
        state.current_song = {"year": 1985, "uri": "spotify:track:1"}

        await state.end_round()

        reveal_state = state.get_reveal_players_state()
        player_data = reveal_state[0]

        assert player_data["years_off"] == 3

    @pytest.mark.asyncio
    async def test_reveal_players_sorted_by_score(self):
        """Reveal state sorts players by total score descending."""
        from custom_components.beatify.game.state import GameState

        state = GameState(time_fn=lambda: 1000.0)
        songs = [{"year": 1985, "uri": "spotify:track:1", "fun_fact": "Fact 1"}]
        state.create_game(
            playlists=["playlist1.json"],
            songs=songs,
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        # Add players with different scores
        mock_ws = MagicMock()
        state.add_player("Low", mock_ws)
        state.add_player("High", mock_ws)
        state.add_player("Mid", mock_ws)

        state.players["Low"].score = 10
        state.players["High"].score = 100
        state.players["Mid"].score = 50

        reveal_state = state.get_reveal_players_state()

        # Should be sorted high to low
        assert reveal_state[0]["name"] == "High"
        assert reveal_state[1]["name"] == "Mid"
        assert reveal_state[2]["name"] == "Low"
