"""Comeback Token tests (Issue #1724).

Opt-in, default-off rubber-banding power-up. The Steal power-up normally
unlocks at a 3-streak — i.e. it is handed to players already winning, while its
effect helps strugglers. The Comeback Token instead hands a one-time steal to
the trailing third of players right after the halfway round completes, reusing
the existing ``unlock_steal`` path.

Guarantees under test:
  * granted only after the halfway round (``ceil(total_rounds / 2)``),
  * granted only to the bottom ``floor(n / 3)`` active players (by score),
  * granted only when the setting is on,
  * never to a player who already has / has spent a steal,
  * at most once per player per game (per-player ``comeback_token_granted``),
  * off = behavior byte-for-byte unchanged (no steal handed out),
  * eliminated (Sudden Death) players are excluded from the pool,
  * ties at the cut-line are broken deterministically by name.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from tests.conftest import make_game_state, make_songs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _add_live_player(gs, name: str) -> None:
    ws = MagicMock()
    ws.closed = False
    gs.add_player(name, ws)
    gs.get_player(name).connected = True


def _make_game(names, *, songs=10, **create_kwargs):
    gs = make_game_state()
    gs.create_game(
        playlists=["t.json"],
        songs=make_songs(songs),
        media_player="media_player.x",
        base_url="http://h",
        **create_kwargs,
    )
    gs.platform = "music_assistant"
    for n in names:
        _add_live_player(gs, n)
    return gs


def _setup(names_scores, *, total_rounds, round_no, enabled=True, **create_kwargs):
    """Build a game, set scores, place it at ``round_no`` of ``total_rounds``."""
    gs = _make_game(
        list(names_scores),
        songs=total_rounds,
        comeback_token_enabled=enabled,
        **create_kwargs,
    )
    gs.total_rounds = total_rounds
    gs.round = round_no
    for name, score in names_scores.items():
        gs.get_player(name).score = score
    return gs


def _granted_names(gs) -> set[str]:
    return {p.name for p in gs.players.values() if p.steal_available}


# ---------------------------------------------------------------------------
# Halfway-round math
# ---------------------------------------------------------------------------


class TestHalfwayRound:
    def test_even_total(self):
        # 10 rounds → halfway is round 5 (5 rounds remain).
        from custom_components.beatify.game.state import GameState

        assert GameState._halfway_round(10) == 5

    def test_odd_total(self):
        # 9 rounds → halfway is round 5, the true middle (rounds 6-9 remain).
        from custom_components.beatify.game.state import GameState

        assert GameState._halfway_round(9) == 5
        assert GameState._halfway_round(7) == 4


# ---------------------------------------------------------------------------
# Grant behaviour
# ---------------------------------------------------------------------------


class TestGrant:
    def test_granted_to_bottom_third_after_halfway(self):
        # 6 players → floor(6/3) = 2 tokens, to the two lowest scorers.
        gs = _setup(
            {"A": 60, "B": 50, "C": 40, "D": 30, "E": 20, "F": 10},
            total_rounds=10,
            round_no=5,
        )
        granted = gs._maybe_grant_comeback_tokens()
        assert set(granted) == {"E", "F"}
        assert _granted_names(gs) == {"E", "F"}
        # The granted players are flagged so a re-run cannot re-grant.
        assert gs.get_player("E").comeback_token_granted is True
        assert gs.get_player("F").comeback_token_granted is True

    def test_not_granted_before_halfway(self):
        gs = _setup({"A": 60, "B": 40, "C": 10}, total_rounds=10, round_no=4)
        assert gs._maybe_grant_comeback_tokens() == []
        assert _granted_names(gs) == set()

    def test_not_granted_after_halfway_round_passed(self):
        # Only fires ON the halfway round, not on later rounds.
        gs = _setup({"A": 60, "B": 40, "C": 10}, total_rounds=10, round_no=7)
        assert gs._maybe_grant_comeback_tokens() == []
        assert _granted_names(gs) == set()

    def test_not_granted_when_disabled(self):
        gs = _setup(
            {"A": 60, "B": 40, "C": 10},
            total_rounds=10,
            round_no=5,
            enabled=False,
        )
        assert gs._maybe_grant_comeback_tokens() == []
        assert _granted_names(gs) == set()

    def test_off_is_byte_for_byte_unchanged(self):
        # With the flag off, no player state changes at all on the halfway round.
        gs = _setup(
            {"A": 60, "B": 40, "C": 10},
            total_rounds=10,
            round_no=5,
            enabled=False,
        )
        before = {
            p.name: (p.steal_available, p.steal_used, p.comeback_token_granted)
            for p in gs.players.values()
        }
        gs._maybe_grant_comeback_tokens()
        after = {
            p.name: (p.steal_available, p.steal_used, p.comeback_token_granted)
            for p in gs.players.values()
        }
        assert before == after

    def test_skips_player_who_already_has_steal(self):
        # 3 players → floor(3/3) = 1 token, to the lowest (C). But C already
        # unlocked a steal via streak → no comeback token, flag stays False.
        gs = _setup({"A": 60, "B": 40, "C": 10}, total_rounds=10, round_no=5)
        gs.get_player("C").steal_available = True
        granted = gs._maybe_grant_comeback_tokens()
        assert granted == []
        assert gs.get_player("C").comeback_token_granted is False

    def test_skips_player_who_used_steal(self):
        gs = _setup({"A": 60, "B": 40, "C": 10}, total_rounds=10, round_no=5)
        c = gs.get_player("C")
        c.steal_used = True
        granted = gs._maybe_grant_comeback_tokens()
        assert granted == []
        assert c.steal_available is False
        assert c.comeback_token_granted is False

    def test_at_most_once_per_game(self):
        gs = _setup({"A": 60, "B": 40, "C": 10}, total_rounds=10, round_no=5)
        assert gs._maybe_grant_comeback_tokens() == ["C"]
        # Player spends the steal, then the grant is somehow re-invoked on the
        # same round — the per-player flag prevents a second token.
        c = gs.get_player("C")
        c.steal_available = False
        c.steal_used = True
        assert gs._maybe_grant_comeback_tokens() == []
        assert c.steal_available is False

    def test_tiny_game_bottom_third_rounds_to_zero(self):
        # 2 players → floor(2/3) = 0 → nobody qualifies, no grant.
        gs = _setup({"A": 60, "B": 10}, total_rounds=10, round_no=5)
        assert gs._maybe_grant_comeback_tokens() == []
        assert _granted_names(gs) == set()

    def test_tie_at_cutline_broken_by_name(self):
        # 6 players, a 3-way tie for last (D=E=F=10). floor(6/3)=2, so exactly
        # two of the tied trio are granted. Ordering is (-score, name), and the
        # bottom slice takes the LAST two by name → E and F (D is spared).
        gs = _setup(
            {"A": 60, "B": 50, "C": 40, "D": 10, "E": 10, "F": 10},
            total_rounds=10,
            round_no=5,
        )
        granted = gs._maybe_grant_comeback_tokens()
        assert set(granted) == {"E", "F"}
        assert gs.get_player("D").steal_available is False

    def test_eliminated_players_excluded(self):
        # 6 total, but B is eliminated (Sudden Death). Pool = 5 active →
        # floor(5/3) = 1 token, to the lowest ACTIVE scorer (F). The eliminated
        # player never counts toward the pool nor receives a token.
        gs = _setup(
            {"A": 60, "B": 5, "C": 40, "D": 30, "E": 20, "F": 10},
            total_rounds=10,
            round_no=5,
        )
        gs.get_player("B").eliminated = True
        granted = gs._maybe_grant_comeback_tokens()
        assert granted == ["F"]
        assert gs.get_player("B").steal_available is False

    def test_one_round_game_never_grants(self):
        # total_rounds < 2 → no meaningful halfway.
        gs = _setup({"A": 10, "B": 5, "C": 1}, total_rounds=1, round_no=1)
        assert gs._maybe_grant_comeback_tokens() == []


# ---------------------------------------------------------------------------
# Plumbing
# ---------------------------------------------------------------------------


class TestPlumbing:
    def test_create_game_sets_flag(self):
        gs = _make_game(["A"], comeback_token_enabled=True)
        assert gs.comeback_token_enabled is True

    def test_default_is_off(self):
        gs = _make_game(["A"])
        assert gs.comeback_token_enabled is False

    def test_serializer_exposes_flag(self):
        from custom_components.beatify.game.serializers import GameStateSerializer

        gs = _make_game(["A", "B"], comeback_token_enabled=True)
        state = GameStateSerializer.serialize(gs)
        assert state["comeback_token_enabled"] is True

    def test_reset_for_new_game_clears_granted_flag(self):
        gs = _make_game(["A"])
        p = gs.get_player("A")
        p.comeback_token_granted = True
        p.reset_for_new_game()
        assert p.comeback_token_granted is False

    def test_rematch_preserves_setting(self):
        gs = _setup({"A": 10, "B": 5}, total_rounds=6, round_no=3)
        assert gs.comeback_token_enabled is True
        gs.rematch_game()
        assert gs.comeback_token_enabled is True
