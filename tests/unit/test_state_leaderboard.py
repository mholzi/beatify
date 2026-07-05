"""Focused unit tests for the LeaderboardMixin (#1587).

The leaderboard / ranking cluster was extracted into ``LeaderboardMixin``
(``game/state_leaderboard.py``) by the #1271 mixin refactor. ``test_state.py``
covers only the ``get_leaderboard`` happy path (sort order + tie ranks). The
rank-*movement* logic (``previous_rank`` → ``rank_change``), the
``_store_previous_ranks`` snapshot pass, and ``get_final_leaderboard``'s
end-of-game stat block (``best_streak`` / ``rounds_played`` / ``bets_won``)
had no dedicated tests. This module closes that gap.

All tests drive the mixin through a real ``GameState`` instance (the host
class) so the assertions exercise the actual inheritance wiring, not a
stand-in.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from tests.conftest import make_game_state


def _create_fresh_game(state) -> None:
    """Create a minimal game so the registry/round subsystems are wired up."""
    state.create_game(
        playlists=["test.json"],
        songs=[
            {
                "year": 1990,
                "title": "Song",
                "artist": "Artist",
                "_resolved_uri": "spotify:track:x",
                "uri": "spotify:track:x",
            }
        ],
        media_player="media_player.test",
        base_url="http://localhost:8123",
    )


def _add(state, name: str, score: int = 0, **attrs) -> None:
    """Add a player and force-set leaderboard-relevant attributes."""
    state.add_player(name, MagicMock())
    player = state.get_player(name)
    player.score = score
    for key, value in attrs.items():
        setattr(player, key, value)


# ---------------------------------------------------------------------------
# _store_previous_ranks — snapshot pass before scoring
# ---------------------------------------------------------------------------


class TestStorePreviousRanks:
    def setup_method(self):
        self.state = make_game_state()
        _create_fresh_game(self.state)

    def test_stamps_each_player_with_current_rank(self):
        _add(self.state, "Alice", score=100)
        _add(self.state, "Bob", score=50)
        _add(self.state, "Carol", score=10)

        self.state._store_previous_ranks()

        assert self.state.get_player("Alice").previous_rank == 1
        assert self.state.get_player("Bob").previous_rank == 2
        assert self.state.get_player("Carol").previous_rank == 3

    def test_tied_players_share_previous_rank_and_skip(self):
        # scores [100, 80, 80, 50] -> ranks [1, 2, 2, 4]
        _add(self.state, "Alice", score=100)
        _add(self.state, "Bob", score=80)
        _add(self.state, "Carol", score=80)
        _add(self.state, "Dave", score=50)

        self.state._store_previous_ranks()

        ranks = {p.name: p.previous_rank for p in self.state.players.values()}
        assert ranks == {"Alice": 1, "Bob": 2, "Carol": 2, "Dave": 4}

    def test_overwrites_stale_previous_rank(self):
        _add(self.state, "Alice", score=10, previous_rank=99)
        _add(self.state, "Bob", score=20, previous_rank=99)

        self.state._store_previous_ranks()

        # Bob leads now; both stale 99s replaced with the fresh snapshot.
        assert self.state.get_player("Bob").previous_rank == 1
        assert self.state.get_player("Alice").previous_rank == 2


# ---------------------------------------------------------------------------
# get_leaderboard — rank_change movement (previous_rank -> rank_change)
# ---------------------------------------------------------------------------


class TestLeaderboardRankChange:
    def setup_method(self):
        self.state = make_game_state()
        _create_fresh_game(self.state)

    def test_no_previous_rank_yields_zero_change(self):
        # Fresh players have previous_rank=None -> rank_change must stay 0.
        _add(self.state, "Alice", score=50)
        _add(self.state, "Bob", score=30)

        lb = {e["name"]: e["rank_change"] for e in self.state.get_leaderboard()}

        assert lb == {"Alice": 0, "Bob": 0}

    def test_positive_change_when_moving_up(self):
        # Alice was 3rd, now 1st -> rank_change = 3 - 1 = +2 (moved up).
        _add(self.state, "Alice", score=100, previous_rank=3)
        _add(self.state, "Bob", score=50, previous_rank=1)
        _add(self.state, "Carol", score=10, previous_rank=2)

        lb = {e["name"]: e["rank_change"] for e in self.state.get_leaderboard()}

        assert lb["Alice"] == 2  # 3 -> 1
        assert lb["Bob"] == -1  # 1 -> 2
        assert lb["Carol"] == -1  # 2 -> 3

    def test_no_movement_yields_zero(self):
        _add(self.state, "Alice", score=100, previous_rank=1)
        _add(self.state, "Bob", score=50, previous_rank=2)

        lb = {e["name"]: e["rank_change"] for e in self.state.get_leaderboard()}

        assert lb["Alice"] == 0
        assert lb["Bob"] == 0

    def test_round_trip_store_then_score_then_change(self):
        """End-to-end: snapshot ranks, mutate scores, then read movement."""
        _add(self.state, "Alice", score=10)
        _add(self.state, "Bob", score=20)
        _add(self.state, "Carol", score=30)

        # Snapshot: Carol 1st, Bob 2nd, Alice 3rd.
        self.state._store_previous_ranks()

        # Alice surges to the top, Carol drops to the bottom.
        self.state.get_player("Alice").score = 100
        self.state.get_player("Carol").score = 5

        lb = {e["name"]: e for e in self.state.get_leaderboard()}

        assert lb["Alice"]["rank"] == 1
        assert lb["Alice"]["rank_change"] == 2  # 3 -> 1
        assert lb["Bob"]["rank"] == 2
        assert lb["Bob"]["rank_change"] == 0  # 2 -> 2
        assert lb["Carol"]["rank"] == 3
        assert lb["Carol"]["rank_change"] == -2  # 1 -> 3


# ---------------------------------------------------------------------------
# get_leaderboard — payload shape & deterministic tie-break ordering
# ---------------------------------------------------------------------------


class TestLeaderboardPayload:
    def setup_method(self):
        self.state = make_game_state()
        _create_fresh_game(self.state)

    def test_entry_is_slim_rank_name_change_only(self):
        # #1765: the in-round leaderboard carries ONLY {rank, name, rank_change}.
        # The per-player fields (score, streak, is_admin, connected, eliminated,
        # eliminated_round) are already in the frame's players array and are
        # re-attached client-side (BeatifyUtils.hydrateLeaderboard) — they must
        # NOT be duplicated here.
        _add(
            self.state,
            "Alice",
            score=42,
            streak=3,
            is_admin=True,
            connected=False,
        )

        (entry,) = self.state.get_leaderboard()

        assert entry == {"rank": 1, "name": "Alice", "rank_change": 0}
        for dropped in (
            "score",
            "streak",
            "is_admin",
            "connected",
            "eliminated",
            "eliminated_round",
        ):
            assert dropped not in entry

    def test_ties_break_by_name_for_stable_display(self):
        # Equal scores -> alphabetical name order, equal rank.
        _add(self.state, "Charlie", score=50)
        _add(self.state, "Alice", score=50)
        _add(self.state, "Bob", score=50)

        order = [e["name"] for e in self.state.get_leaderboard()]
        ranks = {e["name"]: e["rank"] for e in self.state.get_leaderboard()}

        assert order == ["Alice", "Bob", "Charlie"]
        assert ranks == {"Alice": 1, "Bob": 1, "Charlie": 1}


# ---------------------------------------------------------------------------
# get_final_leaderboard — end-of-game stat block (Story 5.6)
# ---------------------------------------------------------------------------


class TestFinalLeaderboard:
    def setup_method(self):
        self.state = make_game_state()
        _create_fresh_game(self.state)

    def test_includes_cumulative_final_stats(self):
        _add(
            self.state,
            "Alice",
            score=120,
            best_streak=5,
            rounds_played=8,
            bets_won=2,
            is_admin=True,
            connected=True,
        )

        (entry,) = self.state.get_final_leaderboard()

        assert entry["rank"] == 1
        assert entry["name"] == "Alice"
        assert entry["score"] == 120
        assert entry["best_streak"] == 5
        assert entry["rounds_played"] == 8
        assert entry["bets_won"] == 2
        assert entry["is_admin"] is True
        assert entry["connected"] is True

    def test_final_omits_live_only_fields(self):
        # streak / rank_change are live-leaderboard concepts; the final board
        # carries the end-of-game stat block instead.
        _add(self.state, "Alice", score=10, streak=4)

        (entry,) = self.state.get_final_leaderboard()

        assert "streak" not in entry
        assert "rank_change" not in entry
        assert "best_streak" in entry

    def test_sorted_with_tie_rank_skip(self):
        # scores [90, 90, 40] -> ranks [1, 1, 3]
        _add(self.state, "Bob", score=90)
        _add(self.state, "Alice", score=90)
        _add(self.state, "Carol", score=40)

        board = self.state.get_final_leaderboard()

        assert [e["name"] for e in board] == ["Alice", "Bob", "Carol"]
        assert [e["rank"] for e in board] == [1, 1, 3]

    def test_empty_game_returns_empty_list(self):
        assert self.state.get_final_leaderboard() == []
