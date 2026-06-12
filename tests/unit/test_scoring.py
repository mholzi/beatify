"""Tests for Beatify scoring logic (custom_components/beatify/game/scoring.py)."""

from __future__ import annotations

import pytest

from unittest.mock import MagicMock

from custom_components.beatify.game.scoring import (
    ScoringService,
    apply_bet_multiplier,
    calculate_accuracy_score,
    calculate_round_score,
    calculate_speed_multiplier,
    calculate_streak_bonus,
)
from custom_components.beatify.game.player import PlayerSession


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
    """Betting is exact-or-nothing (#1004): a bet wins only on the exact
    year (x3), and any non-exact guess forfeits the round score."""

    def test_no_bet_unchanged(self):
        score, outcome = apply_bet_multiplier(10, False, is_exact=True)
        assert score == 10
        assert outcome is None

    def test_bet_won_on_exact(self):
        score, outcome = apply_bet_multiplier(10, True, is_exact=True)
        assert score == 30
        assert outcome == "won"

    def test_bet_lost_when_not_exact_forfeits_score(self):
        # A close guess that would have scored 5 — betting forfeits it.
        score, outcome = apply_bet_multiplier(5, True, is_exact=False)
        assert score == 0
        assert outcome == "lost"

    def test_bet_lost_zero_score(self):
        score, outcome = apply_bet_multiplier(0, True, is_exact=False)
        assert score == 0
        assert outcome == "lost"

    def test_no_bet_zero_score(self):
        score, outcome = apply_bet_multiplier(0, False, is_exact=False)
        assert score == 0
        assert outcome is None

    def test_bet_won_large_score(self):
        score, outcome = apply_bet_multiplier(50, True, is_exact=True)
        assert score == 150
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
# ScoringService.apply_closest_wins
# ---------------------------------------------------------------------------


def _make_player(name: str, guess: int, round_score: int, **kwargs) -> PlayerSession:
    """Create a minimal PlayerSession for closest-wins tests."""
    ws = MagicMock()
    p = PlayerSession(name=name, ws=ws)
    p.submitted = True
    p.current_guess = guess
    p.round_score = round_score
    p.score = round_score  # assume only this round's score so far
    p.round_scores = [round_score]
    for k, v in kwargs.items():
        setattr(p, k, v)
    return p


class TestApplyClosestWins:
    """Tests for ScoringService.apply_closest_wins."""

    def test_basic_three_players_only_closest_keeps(self):
        """Only the player closest to correct year keeps their points."""
        p1 = _make_player("Alice", 2000, 10)  # 0 off
        p2 = _make_player("Bob", 1998, 8)  # 2 off
        p3 = _make_player("Carol", 1990, 5)  # 10 off

        ScoringService.apply_closest_wins([p1, p2, p3], 2000)

        assert p1.round_score == 10
        assert p1.score == 10
        assert p2.round_score == 0
        assert p2.score == 0
        assert p3.round_score == 0
        assert p3.score == 0

    def test_ties_both_keep(self):
        """Two players equally close both keep their points."""
        p1 = _make_player("Alice", 2002, 8)  # 2 off
        p2 = _make_player("Bob", 1998, 6)  # 2 off
        p3 = _make_player("Carol", 1990, 5)  # 10 off

        ScoringService.apply_closest_wins([p1, p2, p3], 2000)

        assert p1.round_score == 8
        assert p1.score == 8
        assert p2.round_score == 6
        assert p2.score == 6
        assert p3.round_score == 0
        assert p3.score == 0

    def test_single_submitter_keeps_score(self):
        """A single submitter always keeps their score."""
        p1 = _make_player("Alice", 1995, 5)

        ScoringService.apply_closest_wins([p1], 2000)

        assert p1.round_score == 5
        assert p1.score == 5

    def test_no_submitters_no_crash(self):
        """No submitted players — function returns without error."""
        p1 = _make_player("Alice", 2000, 0)
        p1.submitted = False

        ScoringService.apply_closest_wins([p1], 2000)

        assert p1.round_score == 0

    def test_bet_multiplied_score_zeroed(self):
        """Player with bet-doubled score is correctly zeroed."""
        p1 = _make_player("Alice", 2000, 20)  # 0 off, bet-doubled
        p2 = _make_player("Bob", 1995, 14)  # 5 off, bet-doubled

        ScoringService.apply_closest_wins([p1, p2], 2000)

        assert p1.round_score == 20
        assert p1.score == 20
        assert p2.round_score == 0
        assert p2.score == 0

    def test_round_scores_list_patched(self):
        """Zeroed player's round_scores[-1] is also set to 0."""
        p1 = _make_player("Alice", 2000, 10)
        p2 = _make_player("Bob", 1990, 8)
        # Give Bob a history so we can verify last element is patched
        p2.round_scores = [5, 3, 8]

        ScoringService.apply_closest_wins([p1, p2], 2000)

        assert p2.round_scores[-1] == 0
        assert p2.round_scores == [5, 3, 0]
        # Winner's list unchanged
        assert p1.round_scores == [10]

    def test_streak_break_for_non_closest(self):
        """Non-closest player's streak resets to 0.

        The streak value on the loser is the *incremented* streak that
        _apply_streak produced for this (now-voided) scoring round, so
        previous_streak rolls back to the pre-round value (streak - 1), #1375.
        """
        p1 = _make_player("Alice", 2000, 10, streak=3, streak_bonus=20)
        p1.score = 10 + 20  # round_score + streak_bonus already added
        p2 = _make_player("Bob", 1990, 5, streak=4, streak_bonus=0)

        ScoringService.apply_closest_wins([p1, p2], 2000)

        # Winner keeps streak
        assert p1.streak == 3
        assert p1.streak_bonus == 20
        # Loser's streak is broken; previous_streak = pre-round value (4 - 1).
        assert p2.streak == 0
        assert p2.streak_bonus == 0
        assert p2.previous_streak == 3
        assert p2.round_score == 0

    def test_best_streak_rolled_back_when_round_voided(self):
        """A voided streak round must not leave best_streak inflated (#1375)."""
        # Alice wins; Bob scored this round (streak 3) and set best_streak=3.
        p1 = _make_player("Alice", 2000, 10)
        p2 = _make_player("Bob", 1990, 5, streak=3, best_streak=3)

        ScoringService.apply_closest_wins([p1, p2], 2000)

        # The streak Bob built this round is revoked, so the record it set is
        # rolled back to the pre-round value.
        assert p2.streak == 0
        assert p2.best_streak == 2

    def test_best_streak_kept_when_earlier_peak_higher(self):
        """best_streak from an earlier, higher peak survives the rollback."""
        p1 = _make_player("Alice", 2000, 10)
        p2 = _make_player("Bob", 1990, 5, streak=3, best_streak=7)

        ScoringService.apply_closest_wins([p1, p2], 2000)

        assert p2.streak == 0
        assert p2.best_streak == 7  # untouched — earlier round peaked higher

    def test_milestone_counter_decremented(self):
        """A voided round that hit a milestone decrements the shared counter."""
        # Bob's streak reached 3, ticking the streak_3 milestone last round.
        p1 = _make_player("Alice", 2000, 10)
        p2 = _make_player("Bob", 1990, 5, streak=3)
        achievements = {"streak_3": 1, "streak_5": 0}

        ScoringService.apply_closest_wins([p1, p2], 2000, achievements)

        assert achievements["streak_3"] == 0
        assert achievements["streak_5"] == 0

    def test_milestone_counter_not_below_zero(self):
        """No milestone bucket for this streak → counter untouched, no crash."""
        p1 = _make_player("Alice", 2000, 10)
        p2 = _make_player("Bob", 1990, 5, streak=2)  # streak_2 not a milestone
        achievements = {"streak_3": 1}

        ScoringService.apply_closest_wins([p1, p2], 2000, achievements)

        assert achievements["streak_3"] == 1  # unrelated bucket untouched

    def test_steal_unlock_revoked_when_newly_unlocked(self):
        """Steal unlocked by the voided streak round is revoked (#1375)."""
        from custom_components.beatify.const import STEAL_UNLOCK_STREAK

        p1 = _make_player("Alice", 2000, 10)
        p2 = _make_player(
            "Bob",
            1990,
            5,
            streak=STEAL_UNLOCK_STREAK,
            steal_available=True,
            steal_used=False,
        )

        ScoringService.apply_closest_wins([p1, p2], 2000)

        assert p2.streak == 0
        assert p2.steal_available is False

    def test_used_steal_not_revoked(self):
        """An already-USED steal stays used; only the credit can be revoked."""
        from custom_components.beatify.const import STEAL_UNLOCK_STREAK

        p1 = _make_player("Alice", 2000, 10)
        p2 = _make_player(
            "Bob",
            1990,
            5,
            streak=STEAL_UNLOCK_STREAK,
            steal_available=False,
            steal_used=True,
        )

        ScoringService.apply_closest_wins([p1, p2], 2000)

        assert p2.steal_used is True
        assert p2.steal_available is False

    def test_previous_streak_preserved_for_zero_score_player(self):
        """A player who scored 0 this round keeps their real previous_streak.

        _apply_streak already broke their streak and saved the pre-break value
        in previous_streak; apply_closest_wins must not overwrite it with 0
        (which would break the "lost X-streak" reveal display), #1375.
        """
        p1 = _make_player("Alice", 2000, 10)
        # Bob guessed badly, scored 0, _apply_streak set streak=0 and saved
        # previous_streak=6 ("lost a 6-streak"). He's also non-closest here.
        p2 = _make_player("Bob", 1980, 0, streak=0, previous_streak=6)

        ScoringService.apply_closest_wins([p1, p2], 2000)

        assert p2.round_score == 0
        assert p2.streak == 0
        # Real previous_streak preserved — NOT clobbered to 0.
        assert p2.previous_streak == 6


# ---------------------------------------------------------------------------
# Title & Artist mode scoring (Issue #1180)
# ---------------------------------------------------------------------------


class _FakeTitleArtistManager:
    """Minimal stand-in matching the ChallengeManager title/artist surface."""

    def __init__(
        self, points_by_player, title_status_by_player, artist_status_by_player=None
    ):
        self._points = points_by_player
        self._title_status = title_status_by_player
        self._artist_status = artist_status_by_player or {}

    def title_artist_points(self, player_name):
        return self._points.get(player_name, (0, 0))

    def title_artist_status(self, player_name, field="title"):
        if field == "artist":
            return self._artist_status.get(player_name, "skipped")
        return self._title_status.get(player_name, "skipped")


class _FakeMovieChallenge:
    """Minimal stand-in exposing the get_player_bonus surface."""

    def __init__(self, bonus_by_player):
        self._bonus = bonus_by_player

    def get_player_bonus(self, player_name):
        return self._bonus.get(player_name, 0)


def _score_title_artist(player, manager, movie_challenge=None):
    """Invoke score_player_round in title/artist mode with sane defaults."""
    ScoringService.score_player_round(
        player,
        correct_year=1975,
        round_start_time=0.0,
        round_duration=30.0,
        difficulty="normal",
        artist_challenge=None,
        movie_challenge=movie_challenge,
        is_intro_round=False,
        intro_round_start_time=None,
        all_players=[player],
        streak_achievements={},
        bet_tracking={"total_bets": 0, "bets_won": 0},
        title_artist_manager=manager,
    )


class TestTitleArtistScoring:
    """Round score = title_pts + artist_pts; streak keyed on title."""

    def _player(self, name="Alice"):
        p = PlayerSession(name=name, ws=MagicMock())
        p.submitted = True
        p.current_guess = 1980  # ignored in title/artist mode
        p.submission_time = 5.0
        return p

    def test_full_points_replace_year_score(self):
        mgr = _FakeTitleArtistManager({"Alice": (10, 5)}, {"Alice": "exact"})
        p = self._player()
        _score_title_artist(p, mgr)
        assert p.round_score == 15
        assert p.base_score == 15
        assert p.score == 15
        assert p.streak == 1  # title exact -> correct
        assert p.missed_round is False
        assert p.round_scores == [15]

    def test_partial_points(self):
        mgr = _FakeTitleArtistManager(
            {"Alice": (5, 3)}, {"Alice": "near_miss_accepted"}
        )
        p = self._player()
        _score_title_artist(p, mgr)
        assert p.round_score == 8
        assert p.streak == 1  # near_miss_accepted title -> correct

    def test_fuzzy_title_counts_for_streak(self):
        mgr = _FakeTitleArtistManager({"Alice": (10, 0)}, {"Alice": "fuzzy"})
        p = self._player()
        _score_title_artist(p, mgr)
        assert p.round_score == 10
        assert p.streak == 1

    def test_wrong_title_breaks_streak(self):
        mgr = _FakeTitleArtistManager({"Alice": (0, 5)}, {"Alice": "near_miss"})
        p = self._player()
        p.streak = 4  # had a streak going
        _score_title_artist(p, mgr)
        assert p.round_score == 5  # artist still scores
        assert p.streak == 0  # title not correct -> streak broken
        assert p.previous_streak == 4

    def test_streak_milestone_bonus_applies(self):
        mgr = _FakeTitleArtistManager({"Alice": (10, 5)}, {"Alice": "exact"})
        p = self._player()
        p.streak = 2  # this round makes it 3 -> +20 milestone
        _score_title_artist(p, mgr)
        assert p.streak == 3
        assert p.streak_bonus == 20
        assert p.score == 15 + 20

    def test_no_speed_bet_intro_in_title_artist_mode(self):
        mgr = _FakeTitleArtistManager({"Alice": (10, 5)}, {"Alice": "exact"})
        p = self._player()
        p.bet = True  # bets must not multiply in this mode
        _score_title_artist(p, mgr)
        assert p.round_score == 15  # not multiplied
        assert p.speed_multiplier == 1.0
        assert p.intro_bonus == 0
        assert p.bet_outcome is None

    def test_not_submitted_scores_zero(self):
        mgr = _FakeTitleArtistManager({}, {})
        p = self._player()
        p.submitted = False
        _score_title_artist(p, mgr)
        assert p.round_score == 0
        assert p.missed_round is True
        assert p.streak == 0
        assert p.round_scores == [0]

    def test_not_submitted_no_movie_challenge_keeps_zero_bonus(self):
        # Regression guard: when there is no movie challenge, a skipped TA
        # guess must still record a zero movie bonus.
        mgr = _FakeTitleArtistManager({}, {})
        p = self._player()
        p.submitted = False
        _score_title_artist(p, mgr, movie_challenge=None)
        assert p.movie_bonus == 0
        assert p.movie_bonus_total == 0
        assert p.score == 0

    def test_not_submitted_preserves_earned_movie_bonus(self):
        # #1376: skipping the title/artist guess must NOT forfeit a correctly
        # earned movie-quiz bonus — it stacks independently of the TA score.
        mgr = _FakeTitleArtistManager({}, {})
        movie = _FakeMovieChallenge({"Alice": 30})
        p = self._player()
        p.submitted = False
        _score_title_artist(p, mgr, movie_challenge=movie)
        assert p.round_score == 0  # TA guess still missed
        assert p.missed_round is True
        assert p.movie_bonus == 30  # earned bonus surfaced
        assert p.score == 30  # and added to the score
        assert p.movie_bonus_total == 30  # Film Buff superlative credited

    def test_not_submitted_no_movie_win_keeps_score_zero(self):
        # A skipped TA guess with a movie challenge present but no win for this
        # player leaves the score and totals untouched.
        mgr = _FakeTitleArtistManager({}, {})
        movie = _FakeMovieChallenge({"Bob": 30})  # Alice did not win
        p = self._player()
        p.submitted = False
        _score_title_artist(p, mgr, movie_challenge=movie)
        assert p.movie_bonus == 0
        assert p.movie_bonus_total == 0
        assert p.score == 0


class TestTitleArtistSuperlativeCounters:
    """Per-field cumulative counters that drive the TA superlatives (#1180)."""

    def _player(self, name="Alice"):
        p = PlayerSession(name=name, ws=MagicMock())
        p.submitted = True
        p.submission_time = 5.0
        return p

    def test_exact_title_and_artist_increments_all(self):
        mgr = _FakeTitleArtistManager(
            {"Alice": (10, 5)}, {"Alice": "exact"}, {"Alice": "exact"}
        )
        p = self._player()
        _score_title_artist(p, mgr)
        assert p.exact_titles == 1
        assert p.correct_artists == 1
        assert p.perfect_pairs == 1
        assert p.near_misses == 0

    def test_fuzzy_title_not_counted_as_exact_but_pairs(self):
        mgr = _FakeTitleArtistManager(
            {"Alice": (10, 5)}, {"Alice": "fuzzy"}, {"Alice": "fuzzy"}
        )
        p = self._player()
        _score_title_artist(p, mgr)
        assert p.exact_titles == 0  # fuzzy is correct but not "exact"
        assert p.correct_artists == 1
        assert p.perfect_pairs == 1  # both fields correct

    def test_near_miss_on_both_fields_counts_twice(self):
        mgr = _FakeTitleArtistManager(
            {"Alice": (0, 0)}, {"Alice": "near_miss"}, {"Alice": "near_miss"}
        )
        p = self._player()
        _score_title_artist(p, mgr)
        assert p.near_misses == 2
        assert p.perfect_pairs == 0
        assert p.correct_artists == 0

    def test_accepted_near_miss_artist_counts_as_correct(self):
        mgr = _FakeTitleArtistManager(
            {"Alice": (10, 3)},
            {"Alice": "exact"},
            {"Alice": "near_miss_accepted"},
        )
        p = self._player()
        _score_title_artist(p, mgr)
        assert p.correct_artists == 1
        assert p.perfect_pairs == 1
        assert p.near_misses == 0

    def test_counters_accumulate_across_rounds(self):
        p = self._player()
        exact = _FakeTitleArtistManager(
            {"Alice": (10, 5)}, {"Alice": "exact"}, {"Alice": "exact"}
        )
        _score_title_artist(p, exact)
        _score_title_artist(p, exact)
        assert p.exact_titles == 2
        assert p.perfect_pairs == 2


class TestTitleArtistSuperlatives:
    """calculate_superlatives surfaces the TA awards only in TA mode (#1180)."""

    def _player(self, name, **counters):
        p = PlayerSession(name=name, ws=MagicMock())
        for key, val in counters.items():
            setattr(p, key, val)
        return p

    def _ids(self, players, **kwargs):
        awards = ScoringService.calculate_superlatives(
            players, rounds_played=5, **kwargs
        )
        return {a["id"] for a in awards}

    def test_ta_awards_present_in_ta_mode(self):
        players = [
            self._player(
                "Alice",
                exact_titles=3,
                correct_artists=3,
                perfect_pairs=3,
                near_misses=3,
            )
        ]
        ids = self._ids(players, title_artist_mode_enabled=True)
        assert {
            "perfect_pair",
            "name_dropper",
            "artist_whisperer",
            "so_close",
        } <= ids

    def test_ta_awards_absent_when_mode_off(self):
        players = [
            self._player(
                "Alice",
                exact_titles=3,
                correct_artists=3,
                perfect_pairs=3,
                near_misses=3,
            )
        ]
        ids = self._ids(players, title_artist_mode_enabled=False)
        assert not (
            {"perfect_pair", "name_dropper", "artist_whisperer", "so_close"} & ids
        )

    def test_below_threshold_does_not_award(self):
        players = [
            self._player(
                "Alice",
                exact_titles=1,
                correct_artists=1,
                perfect_pairs=1,
                near_misses=1,
            )
        ]
        ids = self._ids(players, title_artist_mode_enabled=True)
        assert not (
            {"perfect_pair", "name_dropper", "artist_whisperer", "so_close"} & ids
        )

    def test_awarded_to_highest_counter(self):
        players = [
            self._player("Alice", exact_titles=2),
            self._player("Bob", exact_titles=5),
        ]
        awards = ScoringService.calculate_superlatives(
            players, rounds_played=5, title_artist_mode_enabled=True
        )
        name_dropper = next(a for a in awards if a["id"] == "name_dropper")
        assert name_dropper["player_name"] == "Bob"
        assert name_dropper["value"] == 5
