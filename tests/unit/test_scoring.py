"""
Unit Tests: Scoring Logic

Tests the point calculation system for Beatify:
- Accuracy scoring (exact match, ±3 years, ±5 years)
- Speed bonus (early submission)
- Streak multiplier (consecutive correct)
- Bet mechanics (double or nothing)

These tests validate the SCORING MATRIX from the architecture:
| Accuracy   | Base | Speed | Streak | Bet (2x) |
|------------|------|-------|--------|----------|
| Exact      | 20   | 1-5   | 1.5x   | 2x       |
| ±3 years   | 10   | 1-3   | 1.25x  | 2x       |
| ±5 years   | 5    | 1-2   | 1.1x   | 2x       |
| Wrong      | 0    | 0     | Reset  | -10      |
"""

from __future__ import annotations

import pytest

# Placeholder: Import actual scoring module when implemented
# from custom_components.beatify.game.scoring import calculate_score, ScoreResult


# =============================================================================
# SCORING FUNCTION PLACEHOLDER
# =============================================================================
# TODO: Replace with actual implementation import


def calculate_score(
    guess: int,
    correct_year: int,
    time_remaining_pct: float,  # 0.0 to 1.0
    current_streak: int,
    bet: bool,
) -> dict:
    """
    Placeholder scoring function.

    Replace with import from custom_components.beatify.game.scoring
    """
    diff = abs(guess - correct_year)

    # Base points
    if diff == 0:
        base = 20
        accuracy = "exact"
    elif diff <= 3:
        base = 10
        accuracy = "close"
    elif diff <= 5:
        base = 5
        accuracy = "near"
    else:
        # Wrong guess
        return {
            "base": 0,
            "speed_bonus": 0,
            "streak_multiplier": 1.0,
            "bet_modifier": -10 if bet else 0,
            "total": -10 if bet else 0,
            "accuracy": "wrong",
            "new_streak": 0,
        }

    # Speed bonus (scales with accuracy tier)
    if accuracy == "exact":
        speed_bonus = int(time_remaining_pct * 5)
    elif accuracy == "close":
        speed_bonus = int(time_remaining_pct * 3)
    else:
        speed_bonus = int(time_remaining_pct * 2)

    # Streak multiplier
    if current_streak >= 3:
        if accuracy == "exact":
            multiplier = 1.5
        elif accuracy == "close":
            multiplier = 1.25
        else:
            multiplier = 1.1
    else:
        multiplier = 1.0

    # Calculate total
    subtotal = int((base + speed_bonus) * multiplier)
    bet_modifier = subtotal if bet else 0  # Double points if bet
    total = subtotal + bet_modifier

    return {
        "base": base,
        "speed_bonus": speed_bonus,
        "streak_multiplier": multiplier,
        "bet_modifier": bet_modifier,
        "total": total,
        "accuracy": accuracy,
        "new_streak": current_streak + 1,
    }


# =============================================================================
# EXACT MATCH TESTS
# =============================================================================


@pytest.mark.unit
class TestExactMatch:
    """Tests for exact year matches (20 base points)."""

    def test_exact_match_base_points(self):
        """Exact match should award 20 base points."""
        result = calculate_score(
            guess=1984,
            correct_year=1984,
            time_remaining_pct=0.0,  # No speed bonus
            current_streak=0,
            bet=False,
        )
        assert result["base"] == 20
        assert result["accuracy"] == "exact"

    def test_exact_match_max_speed_bonus(self):
        """Full time remaining should give +5 speed bonus for exact match."""
        result = calculate_score(
            guess=1984,
            correct_year=1984,
            time_remaining_pct=1.0,  # Max speed bonus
            current_streak=0,
            bet=False,
        )
        assert result["speed_bonus"] == 5
        assert result["total"] == 25  # 20 + 5

    def test_exact_match_half_speed_bonus(self):
        """50% time remaining should give +2 speed bonus."""
        result = calculate_score(
            guess=1984,
            correct_year=1984,
            time_remaining_pct=0.5,
            current_streak=0,
            bet=False,
        )
        assert result["speed_bonus"] == 2
        assert result["total"] == 22  # 20 + 2

    def test_exact_match_with_streak(self):
        """3+ streak should apply 1.5x multiplier for exact match."""
        result = calculate_score(
            guess=1984,
            correct_year=1984,
            time_remaining_pct=0.0,
            current_streak=3,  # Streak threshold
            bet=False,
        )
        assert result["streak_multiplier"] == 1.5
        assert result["total"] == 30  # 20 * 1.5

    def test_exact_match_with_bet(self):
        """Bet should double the total points."""
        result = calculate_score(
            guess=1984,
            correct_year=1984,
            time_remaining_pct=0.0,
            current_streak=0,
            bet=True,
        )
        assert result["bet_modifier"] == 20  # Doubles base
        assert result["total"] == 40  # 20 + 20


# =============================================================================
# CLOSE MATCH TESTS (±3 YEARS)
# =============================================================================


@pytest.mark.unit
class TestCloseMatch:
    """Tests for ±3 year matches (10 base points)."""

    @pytest.mark.parametrize("diff", [-3, -2, -1, 1, 2, 3])
    def test_close_match_range(self, diff):
        """Years within ±3 should award 10 base points."""
        correct = 1984
        result = calculate_score(
            guess=correct + diff,
            correct_year=correct,
            time_remaining_pct=0.0,
            current_streak=0,
            bet=False,
        )
        assert result["base"] == 10
        assert result["accuracy"] == "close"

    def test_close_match_max_speed_bonus(self):
        """Close match should get +3 max speed bonus."""
        result = calculate_score(
            guess=1985,
            correct_year=1984,
            time_remaining_pct=1.0,
            current_streak=0,
            bet=False,
        )
        assert result["speed_bonus"] == 3
        assert result["total"] == 13

    def test_close_match_with_streak(self):
        """3+ streak should apply 1.25x multiplier for close match."""
        result = calculate_score(
            guess=1985,
            correct_year=1984,
            time_remaining_pct=0.0,
            current_streak=3,
            bet=False,
        )
        assert result["streak_multiplier"] == 1.25
        assert result["total"] == 12  # 10 * 1.25 = 12.5 -> 12


# =============================================================================
# NEAR MATCH TESTS (±5 YEARS)
# =============================================================================


@pytest.mark.unit
class TestNearMatch:
    """Tests for ±5 year matches (5 base points)."""

    @pytest.mark.parametrize("diff", [-5, -4, 4, 5])
    def test_near_match_range(self, diff):
        """Years within ±4-5 should award 5 base points."""
        correct = 1984
        result = calculate_score(
            guess=correct + diff,
            correct_year=correct,
            time_remaining_pct=0.0,
            current_streak=0,
            bet=False,
        )
        assert result["base"] == 5
        assert result["accuracy"] == "near"


# =============================================================================
# WRONG GUESS TESTS
# =============================================================================


@pytest.mark.unit
class TestWrongGuess:
    """Tests for wrong guesses (>5 years off)."""

    @pytest.mark.parametrize("diff", [-10, -6, 6, 10, 20])
    def test_wrong_guess_no_points(self, diff):
        """Guesses >5 years off should award 0 points."""
        correct = 1984
        result = calculate_score(
            guess=correct + diff,
            correct_year=correct,
            time_remaining_pct=1.0,  # Even with max time
            current_streak=5,  # Even with streak
            bet=False,
        )
        assert result["total"] == 0
        assert result["accuracy"] == "wrong"

    def test_wrong_guess_resets_streak(self):
        """Wrong guess should reset streak to 0."""
        result = calculate_score(
            guess=1900,
            correct_year=1984,
            time_remaining_pct=0.0,
            current_streak=10,  # High streak
            bet=False,
        )
        assert result["new_streak"] == 0

    def test_wrong_guess_with_bet_penalty(self):
        """Wrong guess with bet should incur -10 penalty."""
        result = calculate_score(
            guess=1900,
            correct_year=1984,
            time_remaining_pct=0.0,
            current_streak=0,
            bet=True,
        )
        assert result["total"] == -10
        assert result["bet_modifier"] == -10


# =============================================================================
# STREAK MECHANICS
# =============================================================================


@pytest.mark.unit
class TestStreakMechanics:
    """Tests for streak accumulation and multipliers."""

    def test_streak_increments_on_correct(self):
        """Correct guess should increment streak."""
        result = calculate_score(
            guess=1984,
            correct_year=1984,
            time_remaining_pct=0.0,
            current_streak=2,
            bet=False,
        )
        assert result["new_streak"] == 3

    def test_streak_threshold_is_3(self):
        """Multiplier should only apply at streak >= 3."""
        # Streak = 2 (no multiplier)
        result_2 = calculate_score(
            guess=1984,
            correct_year=1984,
            time_remaining_pct=0.0,
            current_streak=2,
            bet=False,
        )
        assert result_2["streak_multiplier"] == 1.0

        # Streak = 3 (multiplier applies)
        result_3 = calculate_score(
            guess=1984,
            correct_year=1984,
            time_remaining_pct=0.0,
            current_streak=3,
            bet=False,
        )
        assert result_3["streak_multiplier"] == 1.5
