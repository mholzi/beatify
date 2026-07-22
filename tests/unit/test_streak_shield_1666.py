"""Streak-Shield: one wrong answer does not break a long run (#1666).

A milestone hands the player a shield; the next miss spends it instead of
resetting the streak. These tests pin the grant, the spend, the accounting
(the shield protects the run, NOT the points), and the lifetimes — per-round
vs. per-game — because getting those wrong is how a power-up becomes either
useless or permanent.
"""

from __future__ import annotations

from custom_components.beatify.const import STREAK_MILESTONES
from custom_components.beatify.game.player import PlayerSession
from custom_components.beatify.game.scoring import _apply_streak


def _player(**kwargs) -> PlayerSession:
    p = PlayerSession(name="Alice", ws=None)
    for k, v in kwargs.items():
        setattr(p, k, v)
    return p


def _correct(p, achievements=None):
    _apply_streak(p, speed_score=10, streak_achievements=achievements or {})


def _wrong(p, achievements=None):
    _apply_streak(p, speed_score=0, streak_achievements=achievements or {})


class TestGrant:
    def test_milestone_grants_a_shield(self):
        p = _player(streak=2)
        _correct(p)  # -> 3, the first milestone
        assert p.streak == 3
        assert p.streak_shield is True

    def test_non_milestone_grants_nothing(self):
        p = _player(streak=0)
        _correct(p)  # -> 1
        assert p.streak == 1
        assert p.streak_shield is False

    def test_milestones_come_from_the_shared_table(self):
        # Pinning the source, not the numbers: the grant must read the same
        # STREAK_MILESTONES the bonus reads, so "milestone" cannot come to mean
        # two different things.
        for milestone in sorted(STREAK_MILESTONES):
            p = _player(streak=milestone - 1)
            _correct(p)
            assert p.streak_shield is True, milestone

    def test_second_milestone_does_not_stack(self):
        p = _player(streak=2)
        _correct(p)  # 3 -> shield
        for _ in range(2):
            _correct(p)  # 4, 5 -> 5 is a milestone too
        assert p.streak == 5
        # Still exactly one shield — the flag is a bool on purpose.
        assert p.streak_shield is True


class TestSpend:
    def test_shield_absorbs_the_miss_and_keeps_the_streak(self):
        p = _player(streak=7, streak_shield=True)
        _wrong(p)
        assert p.streak == 7, "streak must survive the miss"
        assert p.streak_shield is False, "shield must be spent"
        assert p.streak_shield_used_this_round is True

    def test_without_a_shield_the_streak_still_breaks(self):
        p = _player(streak=7, streak_shield=False)
        _wrong(p)
        assert p.streak == 0
        assert p.previous_streak == 7
        assert p.streak_bonus == 0

    def test_shield_is_gone_after_one_use(self):
        p = _player(streak=7, streak_shield=True)
        _wrong(p)  # absorbed
        _wrong(p)  # nothing left to absorb
        assert p.streak == 0
        assert p.previous_streak == 7

    def test_absorbed_miss_pays_no_streak_bonus(self):
        # The shield protects the run, not the points: the answer was still
        # wrong. `reset_round` zeroes streak_bonus each round and the absorb
        # path must leave it there — paying a bonus for a wrong answer would
        # turn the shield into a scoring exploit.
        p = _player(streak=7, streak_shield=True, streak_bonus=0)
        _wrong(p)
        assert p.streak_bonus == 0

    def test_absorbed_miss_reports_no_lost_streak(self):
        # `previous_streak` drives the "lost your X-streak" reveal line. Nothing
        # was lost, so it must not be set — otherwise the UI mourns a streak the
        # player still has.
        p = _player(streak=7, streak_shield=True, previous_streak=0)
        _wrong(p)
        assert p.previous_streak == 0

    def test_run_continues_after_an_absorbed_miss(self):
        p = _player(streak=3, streak_shield=True)
        _wrong(p)
        _correct(p)
        assert p.streak == 4, "the next correct answer continues the run"


class TestLifetimes:
    def test_shield_survives_reset_round(self):
        # The whole point is to carry into a later round. Clearing it here
        # would make the shield unreachable in practice.
        p = _player(streak=3, streak_shield=True)
        p.reset_round()
        assert p.streak_shield is True

    def test_used_flag_is_per_round(self):
        p = _player(streak=3, streak_shield=True)
        _wrong(p)
        assert p.streak_shield_used_this_round is True
        p.reset_round()
        assert p.streak_shield_used_this_round is False

    def test_new_game_clears_the_shield(self):
        p = _player(streak=3, streak_shield=True, streak_shield_used_this_round=True)
        p.reset_for_new_game()
        assert p.streak_shield is False
        assert p.streak_shield_used_this_round is False
