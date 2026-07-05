"""PR-2 tests (#1664): PlayerRegistry keyed by player_id (== session_id).

Covers the registry-key migration from display-name to the stable
``player_id``, the retained name-based reconnect fallback, the F6 case-fix
(get_player / remove_player / set_admin share one case-insensitive semantic),
steal targeting after the key change, and the player_id exposure in the
state broadcast.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.beatify.const import ERR_NAME_TAKEN
from custom_components.beatify.game.state import GamePhase, GameState
from tests.conftest import make_game_state, make_songs


def _create_fresh_game(state: GameState) -> None:
    state.create_game(
        playlists=["test.json"],
        songs=make_songs(5),
        media_player="media_player.test",
        base_url="http://localhost:8123",
    )


def _healthy_ws() -> MagicMock:
    ws = MagicMock()
    ws.closed = False
    return ws


class TestRegistryKeyedByPlayerId:
    def setup_method(self):
        self.state = make_game_state()
        _create_fresh_game(self.state)

    def test_players_dict_keyed_by_player_id(self):
        self.state.add_player("Alice", _healthy_ws())
        player = self.state.get_player("Alice")
        assert player is not None
        # The dict key is the stable player_id (== session_id), not the name.
        assert player.player_id in self.state.players
        assert self.state.players[player.player_id] is player
        assert "Alice" not in self.state.players

    def test_get_players_state_exposes_player_id(self):
        self.state.add_player("Alice", _healthy_ws())
        rows = self.state.get_players_state()
        assert len(rows) == 1
        row = rows[0]
        assert row["name"] == "Alice"
        assert row["player_id"] == self.state.get_player("Alice").player_id


class TestSessionIdReconnect:
    """(b) Reconnect by session_id hits the record despite case / rename."""

    def setup_method(self):
        self.state = make_game_state()
        _create_fresh_game(self.state)

    def test_session_id_lookup_is_direct(self):
        self.state.add_player("Alice", _healthy_ws())
        player = self.state.get_player("Alice")
        assert self.state.get_player_by_session_id(player.session_id) is player

    def test_session_id_survives_rename(self):
        self.state.add_player("Alice", _healthy_ws())
        player = self.state.get_player("Alice")
        sid = player.session_id
        # Display-name change must not detach the record from its session_id.
        player.name = "Alicia"
        assert self.state.get_player_by_session_id(sid) is player

    def test_unknown_session_id_returns_none(self):
        assert self.state.get_player_by_session_id("does-not-exist") is None


class TestNameUniquenessAndFallback:
    """(a) Same-name handling — uniqueness retained + fallback reconnect."""

    def setup_method(self):
        self.state = make_game_state()
        _create_fresh_game(self.state)

    def test_duplicate_name_with_live_ws_rejected(self):
        self.state.add_player("Alice", _healthy_ws())
        ok, err = self.state.add_player("Alice", _healthy_ws())
        assert ok is False
        assert err == ERR_NAME_TAKEN

    def test_name_fallback_reconnect_reactivates_same_record(self):
        ws1 = _healthy_ws()
        self.state.add_player("Alice", ws1)
        original = self.state.get_player("Alice")
        original_id = original.player_id
        original.connected = False

        ws2 = _healthy_ws()
        ok, err = self.state.add_player("Alice", ws2)
        assert ok is True
        assert err is None
        # Same underlying record reactivated — no duplicate, id preserved.
        reconnected = self.state.get_player("Alice")
        assert reconnected is original
        assert reconnected.player_id == original_id
        assert reconnected.ws is ws2
        assert reconnected.connected is True
        assert len(self.state.players) == 1


class TestF6CaseConsistency:
    """(c) get_player / remove_player / set_admin share one case semantic."""

    def setup_method(self):
        self.state = make_game_state()
        _create_fresh_game(self.state)
        self.state.add_player("Alice", _healthy_ws())

    def test_get_player_case_insensitive(self):
        assert self.state.get_player("alice") is self.state.get_player("Alice")
        assert self.state.get_player("ALICE") is self.state.get_player("Alice")

    def test_set_admin_case_insensitive(self):
        assert self.state.set_admin("ALICE") is True
        assert self.state.get_player("Alice").is_admin is True

    def test_remove_player_case_insensitive(self):
        assert self.state.get_player("Alice") is not None
        self.state.remove_player("ALICE")
        assert self.state.get_player("Alice") is None
        assert len(self.state.players) == 0

    def test_remove_player_clears_session_and_name_index(self):
        player = self.state.get_player("Alice")
        sid = player.session_id
        self.state.remove_player("alice")
        assert self.state.get_player_by_session_id(sid) is None
        # A fresh join under the same name works again (index freed).
        ok, err = self.state.add_player("Alice", _healthy_ws())
        assert ok is True
        assert err is None


class TestStealTargetingAfterKeyChange:
    """(d) Steal targeting still resolves stealer + target by name."""

    def setup_method(self):
        self.state = make_game_state()
        _create_fresh_game(self.state)
        self.state.add_player("Alice", _healthy_ws())
        self.state.add_player("Bob", _healthy_ws())
        self.state.phase = GamePhase.PLAYING

    def test_get_steal_targets_returns_submitted_names(self):
        self.state.get_player("Bob").submitted = True
        targets = self.state.get_steal_targets("Alice")
        assert targets == ["Bob"]

    def test_get_steal_targets_excludes_self(self):
        self.state.get_player("Alice").submitted = True
        self.state.get_player("Bob").submitted = True
        assert self.state.get_steal_targets("Alice") == ["Bob"]

    def test_use_steal_resolves_by_name(self):
        self.state.get_player("Alice").steal_available = True
        self.state.get_player("Bob").submitted = True
        self.state.get_player("Bob").current_guess = 1990
        result = self.state.use_steal("Alice", "Bob")
        assert result["success"] is True
        assert result["year"] == 1990
        assert self.state.get_player("Alice").current_guess == 1990
