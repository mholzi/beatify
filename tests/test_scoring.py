"""Tests for Beatify scoring logic (custom_components/beatify/game/scoring.py)."""

from __future__ import annotations

import pytest

from custom_components.beatify.game.scoring import (
    apply_bet_multiplier,
    calculate_accuracy_score,
    calculate_artist_score,
    calculate_round_score,
    calculate_speed_multiplier,
    calculate_streak_bonus,
    calculate_years_off_text,
)


# ---------------------------------------------------------------------------
# calculate_accuracy_score
# ---------------------------------------------------------------------------


class TestAccuracyScoreNormal:
    """Normal difficulty (default)."""

    def test_exact_match(self):
        assert calculate_accuracy_score(1985, 1985) == 10

    def test_within_close_range(self):
        # ±3 → 5 pts
        assert calculate_accuracy_score(1982, 1985) == 5
        assert calculate_accuracy_score(1988, 1985) == 5

    def test_at_close_boundary(self):
        assert calculate_accuracy_score(1982, 1985) == 5  # exactly 3 off

    def test_within_near_range(self):
        # ±4 or ±5 → 1 pt
        assert calculate_accuracy_score(1981, 1985) == 1  # 4 off
        assert calculate_accuracy_score(1980, 1985) == 1  # 5 off

    def test_at_near_boundary(self):
        assert calculate_accuracy_score(1980, 1985) == 1  # exactly 5 off

    def test_beyond_near_range(self):
        assert calculate_accuracy_score(1979, 1985) == 0  # 6 off

    def test_far_off(self):
        assert calculate_accuracy_score(1950, 2020) == 0


class TestAccuracyScoreEasy:
    """Easy difficulty — wider windows."""

    def test_exact(self):
        assert calculate_accuracy_score(1990, 1990, "easy") == 10

    def test_close_7_years(self):
        assert calculate_accuracy_score(1983, 1990, "easy") == 5  # exactly 7 off

    def test_close_within_7(self):
        assert calculate_accuracy_score(1985, 1990, "easy") == 5

    def test_near_up_to_10(self):
        assert calculate_accuracy_score(1982, 1990, "easy") == 1  # 8 off
        assert calculate_accuracy_score(1980, 1990, "easy") == 1  # exactly 10 off

    def test_beyond_10(self):
        assert calculate_accuracy_score(1979, 1990, "easy") == 0  # 11 off


class TestAccuracyScoreHard:
    """Hard difficulty — tight window, no near tier."""

    def test_exact(self):
        assert calculate_accuracy_score(2000, 2000, "hard") == 10

    def test_within_2(self):
        assert calculate_accuracy_score(1999, 2000, "hard") == 3
        assert calculate_accuracy_score(1998, 2000, "hard") == 3  # exactly 2 off

    def test_3_or_more(self):
        assert calculate_accuracy_score(1997, 2000, "hard") == 0
        assert calculate_accuracy_score(1990, 2000, "hard") == 0


class TestAccuracyScoreFallback:
    """Unknown difficulty falls back to NORMAL."""

    def test_unknown_difficulty_uses_normal(self):
        # Same as normal: exact=10, ±3=5, ±5=1, beyond=0
        assert calculate_accuracy_score(1985, 1985, "extreme") == 10
        assert calculate_accuracy_score(1982, 1985, "extreme") == 5
        assert calculate_accuracy_score(1980, 1985, "extreme") == 1
        assert calculate_accuracy_score(1979, 1985, "extreme") == 0


# ---------------------------------------------------------------------------
# calculate_speed_multiplier
# ---------------------------------------------------------------------------


class TestSpeedMultiplier:
    def test_instant_submission(self):
        assert calculate_speed_multiplier(0.0, 30.0) == pytest.approx(2.0)

    def test_at_deadline(self):
        assert calculate_speed_multiplier(30.0, 30.0) == pytest.approx(1.0)

    def test_halfway(self):
        assert calculate_speed_multiplier(15.0, 30.0) == pytest.approx(1.5)

    def test_over_deadline_clamped(self):
        # More than round_duration → clamped to 1.0
        assert calculate_speed_multiplier(45.0, 30.0) == pytest.approx(1.0)

    def test_negative_time_clamped(self):
        # Negative elapsed → clamped to 2.0
        assert calculate_speed_multiplier(-5.0, 30.0) == pytest.approx(2.0)

    def test_zero_round_duration(self):
        # Division by zero guard → returns 1.0
        assert calculate_speed_multiplier(5.0, 0.0) == pytest.approx(1.0)

    def test_custom_duration(self):
        assert calculate_speed_multiplier(0.0, 60.0) == pytest.approx(2.0)
        assert calculate_speed_multiplier(60.0, 60.0) == pytest.approx(1.0)
        assert calculate_speed_multiplier(30.0, 60.0) == pytest.approx(1.5)


# ---------------------------------------------------------------------------
# calculate_round_score
# ---------------------------------------------------------------------------


class TestRoundScore:
    def test_exact_instant_submission(self):
        final, base, multiplier = calculate_round_score(1985, 1985, 0.0, 30.0)
        assert base == 10
        assert multiplier == pytest.approx(2.0)
        assert final == 20  # 10 * 2.0

    def test_exact_at_deadline(self):
        final, base, multiplier = calculate_round_score(1985, 1985, 30.0, 30.0)
        assert base == 10
        assert multiplier == pytest.approx(1.0)
        assert final == 10  # 10 * 1.0

    def test_wrong_guess_no_bonus(self):
        final, base, multiplier = calculate_round_score(1950, 1985, 0.0, 30.0)
        assert base == 0
        assert final == 0  # 0 * 2.0 = 0

    def test_close_guess_with_speed_bonus(self):
        final, base, multiplier = calculate_round_score(1983, 1985, 15.0, 30.0)
        assert base == 5
        assert multiplier == pytest.approx(1.5)
        assert final == 7  # int(5 * 1.5) = 7

    def test_hard_difficulty(self):
        final, base, _ = calculate_round_score(1983, 1985, 0.0, 30.0, "hard")
        assert base == 3  # hard: ±2 → 3pts
        assert final == 6  # 3 * 2.0 = 6


# ---------------------------------------------------------------------------
# apply_bet_multiplier
# ---------------------------------------------------------------------------


class TestBetMultiplier:
    def test_no_bet_unchanged(self):
        score, outcome = apply_bet_multiplier(10, False)
        assert score == 10
        assert outcome is None

    def test_bet_won(self):
        score, outcome = apply_bet_multiplier(10, True)
        assert score == 20
        assert outcome == "won"

    def test_bet_lost_zero_score(self):
        score, outcome = apply_bet_multiplier(0, True)
        assert score == 0
        assert outcome == "lost"

    def test_no_bet_zero_score(self):
        score, outcome = apply_bet_multiplier(0, False)
        assert score == 0
        assert outcome is None

    def test_bet_won_large_score(self):
        score, outcome = apply_bet_multiplier(50, True)
        assert score == 100
        assert outcome == "won"


# ---------------------------------------------------------------------------
# calculate_streak_bonus
# ---------------------------------------------------------------------------


class TestStreakBonus:
    @pytest.mark.parametrize(
        "streak,expected",
        [
            (1, 0),
            (2, 0),
            (3, 20),
            (4, 0),
            (5, 50),
            (6, 0),
            (10, 100),
            (15, 150),
            (20, 250),
            (25, 400),
            (30, 0),  # Not a milestone
        ],
    )
    def test_milestones(self, streak, expected):
        assert calculate_streak_bonus(streak) == expected


# ---------------------------------------------------------------------------
# calculate_years_off_text
# ---------------------------------------------------------------------------


class TestYearsOffText:
    def test_exact(self):
        assert calculate_years_off_text(0) == "Exact!"

    def test_one_year(self):
        assert calculate_years_off_text(1) == "1 year off"

    def test_multiple_years(self):
        assert calculate_years_off_text(5) == "5 years off"
        assert calculate_years_off_text(30) == "30 years off"


# ---------------------------------------------------------------------------
# calculate_artist_score
# ---------------------------------------------------------------------------


class TestArtistScore:
    def test_exact_match(self):
        points, match_type = calculate_artist_score("The Beatles", "The Beatles")
        assert points == 10
        assert match_type == "exact"

    def test_exact_match_case_insensitive(self):
        points, match_type = calculate_artist_score("the beatles", "The Beatles")
        assert points == 10
        assert match_type == "exact"

    def test_exact_match_with_whitespace(self):
        points, match_type = calculate_artist_score("  The Beatles  ", "The Beatles")
        assert points == 10
        assert match_type == "exact"

    def test_partial_match_substring(self):
        points, match_type = calculate_artist_score("Beatles", "The Beatles")
        assert points == 5
        assert match_type == "partial"

    def test_partial_match_reverse(self):
        # actual in guess
        points, match_type = calculate_artist_score("The Beatles Rock", "The Beatles")
        assert points == 5
        assert match_type == "partial"

    def test_no_match(self):
        points, match_type = calculate_artist_score("Rolling Stones", "The Beatles")
        assert points == 0
        assert match_type is None

    def test_empty_guess(self):
        points, match_type = calculate_artist_score("", "The Beatles")
        assert points == 0
        assert match_type is None

    def test_none_guess(self):
        points, match_type = calculate_artist_score(None, "The Beatles")
        assert points == 0
        assert match_type is None

    def test_whitespace_only_guess(self):
        points, match_type = calculate_artist_score("   ", "The Beatles")
        assert points == 0
        assert match_type is None
