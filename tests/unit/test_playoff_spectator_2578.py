"""#2578: a playoff spectator is not an eliminated player.

`maybe_start_finale_playoff` set `eliminated = True` on every non-leader, to
reuse the Sudden-Death scoring skip. Convenient for the arithmetic, wrong for
everything else:

* the TV drew a skull and greyed out the row — eight players with two in the
  playoff showed **six skulls**, though nobody had been knocked out,
* the leaderboard sorted them below the cut line,
* `_superlative_last_one_standing` counted them, so with Sudden Death *and* a
  playoff the winner got "Last One Standing" with the wrong number.

`playoff_spectator` now carries "sits this round out", `eliminated` keeps "is
out for good", and `out_of_play` is the union the scoring paths ask for.
"""

from __future__ import annotations


from custom_components.beatify.game.player import PlayerSession
from custom_components.beatify.game.scoring import _superlative_last_one_standing


def _p(name, **kw):
    p = PlayerSession(name=name, ws=None, session_id=name)
    for k, v in kw.items():
        setattr(p, k, v)
    return p


class TestOutOfPlay:
    def test_the_two_states_are_independent(self):
        p = _p("Clara")
        assert p.out_of_play is False

        p.playoff_spectator = True
        assert p.out_of_play is True
        assert p.eliminated is False, "a spectator must not read as eliminated"

        p.playoff_spectator = False
        p.eliminated = True
        assert p.out_of_play is True

    def test_reset_clears_the_spectator_flag(self):
        """A rematch must not carry the previous playoff into the new game."""
        p = _p("Clara", playoff_spectator=True)
        p.reset_for_new_game()
        assert p.playoff_spectator is False


class TestLastOneStanding:
    """The superlative counts eliminations, so it must ignore spectators."""

    def test_a_playoff_alone_hands_out_nothing(self):
        spieler = [
            _p("Anna"),
            _p("Ben"),
            _p("Clara", playoff_spectator=True),
            _p("David", playoff_spectator=True),
        ]
        assert _superlative_last_one_standing(spieler) is None, (
            "a playoff must not hand out Last One Standing — nobody was eliminated"
        )

    def test_sudden_death_plus_playoff_counts_only_the_real_cuts(self):
        """The case from the issue: with both active, the winner used to get
        the award with the spectators added to the count."""
        spieler = [
            _p("Anna"),
            _p("Ben", playoff_spectator=True),
            _p("Clara", playoff_spectator=True),
            _p("David", eliminated=True, eliminated_round=3),
            _p("Eva", eliminated=True, eliminated_round=5),
        ]
        award = _superlative_last_one_standing(spieler)
        # Three players are not eliminated, so the 1v1 conclusion never
        # happened and no award is due — the old code saw one survivor and
        # four "eliminated".
        assert award is None

    def test_a_real_sudden_death_finish_still_gets_it(self):
        spieler = [
            _p("Anna"),
            _p("Ben", eliminated=True, eliminated_round=4),
            _p("Clara", eliminated=True, eliminated_round=6),
        ]
        award = _superlative_last_one_standing(spieler)
        assert award is not None
        assert award["player_name"] == "Anna"
        assert award["value"] == 2
