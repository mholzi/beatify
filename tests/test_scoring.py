"""Tests for custom_components.beatify.game.scoring — Phase 1."""

from __future__ import annotations

import pytest

from custom_components.beatify.game.scoring import (
    POINTS_ARTIST_EXACT,
    POINTS_ARTIST_PARTIAL,
    POINTS_EXACT,
    POINTS_WRONG,
    ScoringService,
    _get_decade_label,
    apply_bet_multiplier,
    calculate_accuracy_score,
    calculate_artist_score,
    calculate_round_score,
    calculate_speed_multiplier,
    calculate_streak_bonus,
    calculate_years_off_text,
)
from custom_components.beatify.const import (
    DIFFICULTY_EASY,
    DIFFICULTY_HARD,
    DIFFICULTY_NORMAL,
    STREAK_MILESTONES,
)
from tests.conftest import make_player


# =========================================================================
# calculate_accuracy_score
# =========================================================================

class TestCalculateAccuracyScore:
    """Accuracy scoring across all difficulty tiers."""

    # --- Normal difficulty ---
    def test_exact_match_normal(self):
        assert calculate_accuracy_score(1985, 1985) == POINTS_EXACT

    def test_close_range_normal(self):
        # Within ±3 years → 5 pts
        assert calculate_accuracy_score(1983, 1985) == 5
        assert calculate_accuracy_score(1988, 1985) == 5

    def test_near_range_normal(self):
        # Within ±5 years → 1 pt
        assert calculate_accuracy_score(1980, 1985) == 1

    def test_out_of_range_normal(self):
        assert calculate_accuracy_score(1970, 1985) == POINTS_WRONG

    # --- Easy difficulty ---
    def test_exact_match_easy(self):
        assert calculate_accuracy_score(2000, 2000, DIFFICULTY_EASY) == POINTS_EXACT

    def test_close_range_easy(self):
        # ±7 years → 5
        assert calculate_accuracy_score(1993, 2000, DIFFICULTY_EASY) == 5

    def test_near_range_easy(self):
        # ±10 years → 1
        assert calculate_accuracy_score(1990, 2000, DIFFICULTY_EASY) == 1

    def test_out_of_range_easy(self):
        assert calculate_accuracy_score(1980, 2000, DIFFICULTY_EASY) == POINTS_WRONG

    # --- Hard difficulty ---
    def test_exact_match_hard(self):
        assert calculate_accuracy_score(2000, 2000, DIFFICULTY_HARD) == POINTS_EXACT

    def test_close_range_hard(self):
        # ±2 years → 3
        assert calculate_accuracy_score(1998, 2000, DIFFICULTY_HARD) == 3
        assert calculate_accuracy_score(2002, 2000, DIFFICULTY_HARD) == 3

    def test_out_of_range_hard(self):
        # Hard has near_range=0, so anything beyond ±2 is 0
        assert calculate_accuracy_score(1997, 2000, DIFFICULTY_HARD) == POINTS_WRONG

    # --- Unknown difficulty fallback ---
    def test_unknown_difficulty_falls_back_to_default(self):
        # Should use normal scoring
        assert calculate_accuracy_score(1985, 1985, "extreme") == POINTS_EXACT
        assert calculate_accuracy_score(1982, 1985, "extreme") == 5

    # --- Edge: exact boundary ---
    def test_boundary_normal_close(self):
        # diff == 3 exactly (close_range for normal)
        assert calculate_accuracy_score(1982, 1985, DIFFICULTY_NORMAL) == 5

    def test_boundary_normal_near(self):
        # diff == 5 exactly (near_range for normal)
        assert calculate_accuracy_score(1980, 1985, DIFFICULTY_NORMAL) == 1

    def test_boundary_normal_just_outside(self):
        # diff == 6 → 0
        assert calculate_accuracy_score(1979, 1985, DIFFICULTY_NORMAL) == POINTS_WRONG


# =========================================================================
# calculate_speed_multiplier
# =========================================================================

class TestCalculateSpeedMultiplier:
    def test_instant_submission(self):
        assert calculate_speed_multiplier(0.0, 30.0) == 2.0

    def test_at_deadline(self):
        assert calculate_speed_multiplier(30.0, 30.0) == 1.0

    def test_half_way(self):
        assert calculate_speed_multiplier(15.0, 30.0) == pytest.approx(1.5)

    def test_negative_elapsed_clamped(self):
        # Should clamp to 0 ratio → 2.0
        assert calculate_speed_multiplier(-5.0, 30.0) == 2.0

    def test_over_deadline_clamped(self):
        # Should clamp to 1.0 ratio → 1.0
        assert calculate_speed_multiplier(60.0, 30.0) == 1.0

    def test_zero_duration(self):
        assert calculate_speed_multiplier(10.0, 0.0) == 1.0

    def test_negative_duration(self):
        assert calculate_speed_multiplier(10.0, -5.0) == 1.0


# =========================================================================
# calculate_round_score
# =========================================================================

class TestCalculateRoundScore:
    def test_exact_instant(self):
        final, base, mult = calculate_round_score(2000, 2000, 0.0, 30.0)
        assert base == 10
        assert mult == 2.0
        assert final == 20

    def test_exact_at_deadline(self):
        final, base, mult = calculate_round_score(2000, 2000, 30.0, 30.0)
        assert base == 10
        assert mult == 1.0
        assert final == 10

    def test_wrong_guess(self):
        final, base, mult = calculate_round_score(1950, 2000, 5.0, 30.0)
        assert base == 0
        assert final == 0

    def test_difficulty_passed_through(self):
        # Hard: ±2 → 3 pts
        final, base, mult = calculate_round_score(1998, 2000, 0.0, 30.0, DIFFICULTY_HARD)
        assert base == 3
        assert final == 6  # 3 * 2.0


# =========================================================================
# apply_bet_multiplier
# =========================================================================

class TestApplyBetMultiplier:
    def test_no_bet(self):
        score, outcome = apply_bet_multiplier(10, False)
        assert score == 10
        assert outcome is None

    def test_bet_won(self):
        score, outcome = apply_bet_multiplier(10, True)
        assert score == 20
        assert outcome == "won"

    def test_bet_lost(self):
        score, outcome = apply_bet_multiplier(0, True)
        assert score == 0
        assert outcome == "lost"

    def test_bet_with_zero_no_bet(self):
        score, outcome = apply_bet_multiplier(0, False)
        assert score == 0
        assert outcome is None


# =========================================================================
# calculate_streak_bonus
# =========================================================================

class TestCalculateStreakBonus:
    def test_no_milestone(self):
        assert calculate_streak_bonus(1) == 0
        assert calculate_streak_bonus(2) == 0
        assert calculate_streak_bonus(4) == 0

    def test_all_milestones(self):
        for streak, bonus in STREAK_MILESTONES.items():
            assert calculate_streak_bonus(streak) == bonus

    def test_past_max_milestone(self):
        assert calculate_streak_bonus(30) == 0


# =========================================================================
# calculate_years_off_text
# =========================================================================

class TestCalculateYearsOffText:
    def test_exact(self):
        assert calculate_years_off_text(0) == "Exact!"

    def test_one_year(self):
        assert calculate_years_off_text(1) == "1 year off"

    def test_multiple_years(self):
        assert calculate_years_off_text(5) == "5 years off"


# =========================================================================
# calculate_artist_score
# =========================================================================

class TestCalculateArtistScore:
    def test_exact_match(self):
        pts, match = calculate_artist_score("Queen", "Queen")
        assert pts == POINTS_ARTIST_EXACT
        assert match == "exact"

    def test_exact_case_insensitive(self):
        pts, match = calculate_artist_score("queen", "Queen")
        assert pts == POINTS_ARTIST_EXACT
        assert match == "exact"

    def test_partial_match_substring(self):
        pts, match = calculate_artist_score("Queen", "Queen & David Bowie")
        assert pts == POINTS_ARTIST_PARTIAL
        assert match == "partial"

    def test_partial_match_reverse(self):
        pts, match = calculate_artist_score("The Beatles Band", "Beatles")
        assert pts == POINTS_ARTIST_PARTIAL
        assert match == "partial"

    def test_no_match(self):
        pts, match = calculate_artist_score("Metallica", "Queen")
        assert pts == 0
        assert match is None

    def test_empty_guess(self):
        pts, match = calculate_artist_score("", "Queen")
        assert pts == 0
        assert match is None

    def test_none_guess(self):
        pts, match = calculate_artist_score(None, "Queen")
        assert pts == 0
        assert match is None

    def test_whitespace_guess(self):
        pts, match = calculate_artist_score("  ", "Queen")
        assert pts == 0
        assert match is None

    def test_whitespace_trimming(self):
        pts, match = calculate_artist_score("  Queen  ", "  Queen  ")
        assert pts == POINTS_ARTIST_EXACT
        assert match == "exact"


# =========================================================================
# _get_decade_label
# =========================================================================

class TestGetDecadeLabel:
    def test_various_years(self):
        assert _get_decade_label(1985) == "1980s"
        assert _get_decade_label(1990) == "1990s"
        assert _get_decade_label(2001) == "2000s"
        assert _get_decade_label(1959) == "1950s"


# =========================================================================
# ScoringService.calculate_superlatives
# =========================================================================

class TestCalculateSuperlatives:
    def test_empty_players(self):
        assert ScoringService.calculate_superlatives([], rounds_played=5) == []

    def test_speed_demon_award(self):
        fast = make_player("Speedy")
        fast.submission_times = [1.0, 1.5, 2.0]
        slow = make_player("Slowpoke")
        slow.submission_times = [10.0, 11.0, 12.0]
        awards = ScoringService.calculate_superlatives([fast, slow], rounds_played=5)
        speed_awards = [a for a in awards if a["id"] == "speed_demon"]
        assert len(speed_awards) == 1
        assert speed_awards[0]["player_name"] == "Speedy"

    def test_lucky_streak_award(self):
        p = make_player("Streaker")
        p.best_streak = 5
        awards = ScoringService.calculate_superlatives([p], rounds_played=5)
        streak_awards = [a for a in awards if a["id"] == "lucky_streak"]
        assert len(streak_awards) == 1
        assert streak_awards[0]["player_name"] == "Streaker"

    def test_risk_taker_award(self):
        p = make_player("Gambler")
        p.bets_placed = 5
        awards = ScoringService.calculate_superlatives([p], rounds_played=5)
        bet_awards = [a for a in awards if a["id"] == "risk_taker"]
        assert len(bet_awards) == 1

    def test_clutch_player_award(self):
        p = make_player("Clutch")
        p.round_scores = [0, 0, 0, 10, 15, 20]
        awards = ScoringService.calculate_superlatives([p], rounds_played=6)
        clutch = [a for a in awards if a["id"] == "clutch_player"]
        assert len(clutch) == 1

    def test_close_calls_award(self):
        p = make_player("Almost")
        p.close_calls = 3
        awards = ScoringService.calculate_superlatives([p], rounds_played=5)
        close = [a for a in awards if a["id"] == "close_calls"]
        assert len(close) == 1

    def test_film_buff_award(self):
        p = make_player("Cinephile")
        p.movie_bonus_total = 5
        awards = ScoringService.calculate_superlatives(
            [p], rounds_played=5, movie_quiz_enabled=True
        )
        film = [a for a in awards if a["id"] == "film_buff"]
        assert len(film) == 1

    def test_intro_master_award(self):
        p = make_player("IntroKing")
        p.intro_speed_bonuses = 2
        awards = ScoringService.calculate_superlatives(
            [p], rounds_played=5, intro_mode_enabled=True
        )
        intro = [a for a in awards if a["id"] == "intro_master"]
        assert len(intro) == 1

    def test_comeback_king_award(self):
        p = make_player("Phoenix")
        # First half avg 1, second half avg 10 → improvement 9
        p.round_scores = [0, 1, 1, 10, 10, 10]
        awards = ScoringService.calculate_superlatives([p], rounds_played=6)
        comeback = [a for a in awards if a["id"] == "comeback_king"]
        assert len(comeback) == 1

    def test_max_superlatives_capped(self):
        """Awards are capped at MAX_SUPERLATIVES."""
        from custom_components.beatify.const import MAX_SUPERLATIVES

        # Create a player who qualifies for many awards
        p = make_player("Hero")
        p.submission_times = [1.0, 1.0, 1.0]
        p.best_streak = 5
        p.bets_placed = 5
        p.close_calls = 3
        p.round_scores = [0, 0, 0, 20, 20, 20]
        p.movie_bonus_total = 5
        p.intro_speed_bonuses = 2
        awards = ScoringService.calculate_superlatives(
            [p],
            rounds_played=6,
            movie_quiz_enabled=True,
            intro_mode_enabled=True,
        )
        assert len(awards) <= MAX_SUPERLATIVES


# =========================================================================
# ScoringService.calculate_round_analytics
# =========================================================================

class TestCalculateRoundAnalytics:
    def test_no_correct_year(self):
        analytics = ScoringService.calculate_round_analytics([], None, None)
        assert analytics.total_submitted == 0

    def test_no_submissions(self):
        p = make_player("NoGuess")
        p.submitted = False
        analytics = ScoringService.calculate_round_analytics([p], 1985, 1000.0)
        assert analytics.total_submitted == 0
        assert analytics.correct_decade == "1980s"

    def test_basic_analytics(self):
        p1 = make_player("Alice")
        p1.submitted = True
        p1.current_guess = 1985
        p1.years_off = 0
        p1.round_score = 10
        p1.submission_time = 1002.0

        p2 = make_player("Bob")
        p2.submitted = True
        p2.current_guess = 1990
        p2.years_off = 5
        p2.round_score = 1
        p2.submission_time = 1005.0

        analytics = ScoringService.calculate_round_analytics([p1, p2], 1985, 1000.0)
        assert analytics.total_submitted == 2
        assert analytics.exact_match_count == 1
        assert "Alice" in analytics.exact_match_players
        assert "Alice" in analytics.closest_players
        assert "Bob" in analytics.furthest_players
        assert analytics.accuracy_percentage == 100  # both scored > 0
        assert analytics.speed_champion is not None
        assert "Alice" in analytics.speed_champion["names"]
        assert analytics.correct_decade == "1980s"


# =========================================================================
# ScoringService.score_player_round
# =========================================================================

class TestScorePlayerRound:
    def _score(self, player, correct_year=2000, **kwargs):
        defaults = dict(
            correct_year=correct_year,
            round_start_time=1000.0,
            round_duration=30.0,
            difficulty=DIFFICULTY_NORMAL,
            artist_challenge=None,
            movie_challenge=None,
            is_intro_round=False,
            intro_round_start_time=None,
            all_players=[player],
            streak_achievements={"streak_3": 0, "streak_5": 0, "streak_7": 0, "streak_15": 0, "streak_20": 0, "streak_25": 0},
            bet_tracking={"total_bets": 0, "bets_won": 0},
        )
        defaults.update(kwargs)
        ScoringService.score_player_round(player, **defaults)

    def test_correct_guess_scores(self):
        p = make_player("Alice")
        p.submitted = True
        p.current_guess = 2000
        p.submission_time = 1015.0  # halfway
        self._score(p)
        assert p.base_score == 10
        assert p.round_score > 0
        assert p.score > 0
        assert p.streak == 1
        assert p.years_off == 0

    def test_wrong_guess_resets_streak(self):
        p = make_player("Bob", streak=5)
        p.submitted = True
        p.current_guess = 1950
        p.submission_time = 1010.0
        self._score(p)
        assert p.streak == 0
        assert p.previous_streak == 5

    def test_missed_round(self):
        p = make_player("Carol", streak=3)
        p.submitted = False
        self._score(p)
        assert p.missed_round is True
        assert p.round_score == 0
        assert p.streak == 0
        assert p.previous_streak == 3

    def test_bet_doubles_score(self):
        p = make_player("Dave")
        p.submitted = True
        p.current_guess = 2000
        p.submission_time = 1015.0
        p.bet = True
        bet_tracking = {"total_bets": 0, "bets_won": 0}
        self._score(p, bet_tracking=bet_tracking)
        assert p.bet_outcome == "won"
        assert bet_tracking["total_bets"] == 1
        assert bet_tracking["bets_won"] == 1

    def test_streak_milestone_bonus(self):
        p = make_player("Eve", streak=2)
        p.submitted = True
        p.current_guess = 2000
        p.submission_time = 1015.0
        self._score(p)
        assert p.streak == 3
        assert p.streak_bonus == 20  # milestone at 3

    def test_close_call_tracking(self):
        p = make_player("Frank")
        p.submitted = True
        p.current_guess = 2001  # 1 year off
        p.submission_time = 1015.0
        self._score(p)
        assert p.close_calls == 1

    def test_rounds_played_incremented(self):
        p = make_player("Grace")
        p.submitted = True
        p.current_guess = 2000
        p.submission_time = 1015.0
        self._score(p)
        assert p.rounds_played == 1
        assert len(p.round_scores) == 1
