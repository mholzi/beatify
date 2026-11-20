"""Tests for the game simulation harness (scripts/sim/).

The cross-check class is the important one: it replays scenarios taken from
test_scoring.py through the sim and pins the exact points. If the sim ever
computed points with its own math instead of calling the real scoring code,
these would fail (scripts/sim/mutation_divergent_math.patch demonstrates it).
"""

from __future__ import annotations

import sys
from pathlib import Path
from random import Random

import pytest

_SIM_DIR = Path(__file__).resolve().parents[2] / "scripts" / "sim"
if str(_SIM_DIR) not in sys.path:
    sys.path.insert(0, str(_SIM_DIR))

import fun_sim  # noqa: E402
import metrics  # noqa: E402
import profiles  # noqa: E402
from fun_sim import Decision  # noqa: E402

DURATION = 30.0


def _round(decisions, year, *, closest_wins=False, players=None, trackers=None):
    players = players or fun_sim.make_players([f"P{i}" for i in range(len(decisions))])
    streaks, bets = trackers or fun_sim.new_trackers()
    deltas = fun_sim.play_round(
        players,
        decisions,
        year,
        streak_achievements=streaks,
        bet_tracking=bets,
        round_duration=DURATION,
        closest_wins=closest_wins,
    )
    return deltas, players, (streaks, bets)


class TestCrossCheckAgainstScoringTests:
    """Same scenarios as test_scoring.py; the expected numbers are pinned."""

    def test_close_guess_with_speed_bonus(self):
        # test_scoring: 1983 vs 1985, 15 s of 30 s -> base 5 x 1.75 -> 9
        deltas, _, _ = _round([Decision(1983, 15.0)], 1985)
        assert deltas == [9]

    def test_exact_instant_and_hard_difficulty(self):
        # test_scoring: exact + instant -> 10 x 2.0 = 20
        deltas, _, _ = _round([Decision(1985, 0.0)], 1985)
        assert deltas == [20]
        # test_scoring: hard, 1983 vs 1985 instant -> 3 x 2.0 = 6
        players = fun_sim.make_players(["A"])
        streaks, bets = fun_sim.new_trackers()
        hard = fun_sim.play_round(
            players,
            [Decision(1983, 0.0)],
            1985,
            streak_achievements=streaks,
            bet_tracking=bets,
            round_duration=DURATION,
            difficulty="hard",
        )
        assert hard == [6]

    def test_bet_won_triples_and_lost_forfeits(self):
        # exact + instant = 20; won bet x3 = 60 (test_bet_won_on_exact)
        deltas, _, _ = _round([Decision(1985, 0.0, bet=True)], 1985)
        assert deltas == [60]
        # close guess + bet that is not exact -> forfeited (test_bet_lost_*)
        deltas, _, _ = _round([Decision(1983, 0.0, bet=True)], 1985)
        assert deltas == [0]

    def test_streak_milestone_bonus_at_three(self):
        # 3 exact answers at (almost) the deadline: 10 + 10 + (10 + 20 bonus)
        players = fun_sim.make_players(["A"])
        trackers = fun_sim.new_trackers()
        totals = []
        for _ in range(3):
            deltas, players, trackers = _round(
                [Decision(1985, 29.999)], 1985, players=players, trackers=trackers
            )
            totals.append(deltas[0])
        assert totals == [10, 10, 30]
        assert players[0].streak == 3

    def test_closest_wins_only_closest_keeps_points(self):
        # test_basic_three_players_only_closest_keeps (deadline-edge speed = 1.0x)
        deltas, _, _ = _round(
            [Decision(2000, 29.999), Decision(1998, 29.999), Decision(1990, 29.999)],
            2000,
            closest_wins=True,
        )
        assert deltas == [10, 0, 0]

    def test_missed_deadline_scores_nothing(self):
        deltas, players, _ = _round([Decision(1985, 31.0)], 1985)
        assert deltas == [0]
        assert players[0].missed_round is True


class TestProfiles:
    def test_profile_numbers_are_pinned(self):
        # Changing a profile changes the measuring instrument; do not.
        p = profiles.PROFILES
        assert (p["Kenner"].error_spread, p["Kenner"].submit_max) == (2.0, 14.0)
        assert p["Gelegenheit"].error_spread == 8.0
        assert (p["Rater"].error_kind, p["Rater"].error_spread) == ("uniform", 20.0)
        assert (p["Zoegerer"].error_spread, p["Zoegerer"].submit_min) == (3.0, 32.0)
        assert (p["Zocker"].error_spread, p["Zocker"].bet_prob) == (6.0, 0.5)

    def test_rater_stays_within_twenty_years(self):
        rng = Random(1)
        for _ in range(500):
            assert abs(profiles.RATER.guess(rng, 1990) - 1990) <= 20

    def test_roster_size_between_three_and_eight(self):
        rng = Random(2)
        sizes = {len(profiles.draw_roster(rng, "default")) for _ in range(300)}
        assert min(sizes) >= 3
        assert max(sizes) <= 8


class TestMetrics:
    def test_objective_weights_sum_to_one(self):
        assert sum(w for w, _, _ in metrics.OBJECTIVE_TERMS.values()) == pytest.approx(
            1.0
        )

    def test_lead_changes_and_podium_gap(self):
        rec = metrics.GameRecord(
            profiles=["Kenner", "Rater", "Gelegenheit"],
            final_scores=[30, 20, 10],
            score_history=[[10, 0, 0], [10, 20, 0], [30, 20, 10]],
            round_deltas=[[10, 0, 0], [0, 20, 0], [20, 0, 10]],
            award_winner_seats={0},
        )
        stats = metrics.game_stats(rec)
        assert stats["lead_changes"] == 2.0  # 0 -> 1 -> 0
        assert stats["podium_gap_pct"] == pytest.approx(66.6667, rel=1e-3)
        assert stats["open_to_last"] is True  # seat 1 led before the last round
        assert stats["zero_round_share"] == pytest.approx(5 / 9)
        assert stats["award_coverage"] == pytest.approx(1 / 3)

    def test_ties_keep_previous_leader(self):
        assert metrics._leader_after_round([5, 5], previous=1) == 1
        assert metrics._leader_after_round([5, 5], previous=None) == 0


class TestBatch:
    def test_same_seed_same_result(self):
        years = fun_sim.load_song_years()
        a = fun_sim.run_batch(40, 7, song_years=years)
        b = fun_sim.run_batch(40, 7, song_years=years)
        assert a == b

    def test_different_seed_differs(self):
        years = fun_sim.load_song_years()
        assert fun_sim.run_batch(40, 1, song_years=years) != fun_sim.run_batch(
            40, 2, song_years=years
        )

    def test_song_years_come_from_real_playlists(self):
        years = fun_sim.load_song_years()
        assert len(years) > 1000
        assert 1900 < min(years) and max(years) <= 2030

    def test_objective_is_within_range(self):
        result = fun_sim.run_batch(30, 3)
        assert 0.0 <= result["objective"]["score"] <= 100.0  # type: ignore[index]
