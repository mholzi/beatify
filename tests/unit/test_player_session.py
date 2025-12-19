"""
Unit Tests: Player Session Management (Story 3.2)

Tests player session operations in GameState:
- add_player: success, duplicate (case-insensitive), invalid name, MAX_PLAYERS
- get_player: existing, non-existing
- remove_player: existing, non-existing
- get_players_state: serialization for broadcast
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


# =============================================================================
# FIXTURES
# =============================================================================


@pytest.fixture
def game_state_with_game():
    """Game state with active game for player tests."""
    from custom_components.beatify.game.state import GameState

    state = GameState()
    state.create_game(
        playlists=["playlist.json"],
        songs=[{"year": 1985, "uri": "spotify:track:test"}],
        media_player="media_player.test",
        base_url="http://localhost:8123",
    )
    return state


@pytest.fixture
def mock_ws():
    """Mock WebSocket connection."""
    return MagicMock()


# =============================================================================
# ADD PLAYER TESTS
# =============================================================================


@pytest.mark.unit
class TestAddPlayer:
    """Tests for add_player method."""

    def test_add_player_success(self, game_state_with_game, mock_ws):
        """Player can be added with valid name."""
        success, error = game_state_with_game.add_player("Tom", mock_ws)

        assert success is True
        assert error is None
        assert "Tom" in game_state_with_game.players
        assert game_state_with_game.players["Tom"].name == "Tom"
        assert game_state_with_game.players["Tom"].ws == mock_ws
        assert game_state_with_game.players["Tom"].score == 0
        assert game_state_with_game.players["Tom"].connected is True

    def test_add_player_trims_whitespace(self, game_state_with_game, mock_ws):
        """Player name should be trimmed."""
        success, error = game_state_with_game.add_player("  Alice  ", mock_ws)

        assert success is True
        assert error is None
        # Name is stored trimmed
        assert "Alice" in game_state_with_game.players

    def test_add_multiple_players(self, game_state_with_game, mock_ws):
        """Multiple players can be added."""
        game_state_with_game.add_player("Alice", mock_ws)
        game_state_with_game.add_player("Bob", mock_ws)
        game_state_with_game.add_player("Charlie", mock_ws)

        assert len(game_state_with_game.players) == 3
        assert "Alice" in game_state_with_game.players
        assert "Bob" in game_state_with_game.players
        assert "Charlie" in game_state_with_game.players


@pytest.mark.unit
class TestAddPlayerDuplicate:
    """Tests for duplicate name rejection."""

    def test_add_player_duplicate_rejected(self, game_state_with_game, mock_ws):
        """Duplicate names are rejected."""
        from custom_components.beatify.const import ERR_NAME_TAKEN

        game_state_with_game.add_player("Tom", mock_ws)
        success, error = game_state_with_game.add_player("Tom", mock_ws)

        assert success is False
        assert error == ERR_NAME_TAKEN
        # Only one player should exist
        assert len(game_state_with_game.players) == 1

    def test_add_player_case_insensitive(self, game_state_with_game, mock_ws):
        """Name check is case-insensitive."""
        from custom_components.beatify.const import ERR_NAME_TAKEN

        game_state_with_game.add_player("Tom", mock_ws)
        success, error = game_state_with_game.add_player("tom", mock_ws)

        assert success is False
        assert error == ERR_NAME_TAKEN

    def test_add_player_case_insensitive_mixed(self, game_state_with_game, mock_ws):
        """Mixed case variations are rejected."""
        from custom_components.beatify.const import ERR_NAME_TAKEN

        game_state_with_game.add_player("Alice", mock_ws)

        # Try various case combinations
        for variant in ["alice", "ALICE", "aLiCe", "AliCE"]:
            success, error = game_state_with_game.add_player(variant, mock_ws)
            assert success is False
            assert error == ERR_NAME_TAKEN


@pytest.mark.unit
class TestAddPlayerValidation:
    """Tests for name validation."""

    def test_add_player_empty_rejected(self, game_state_with_game, mock_ws):
        """Empty name is rejected."""
        from custom_components.beatify.const import ERR_NAME_INVALID

        success, error = game_state_with_game.add_player("", mock_ws)

        assert success is False
        assert error == ERR_NAME_INVALID

    def test_add_player_whitespace_rejected(self, game_state_with_game, mock_ws):
        """Whitespace-only name is rejected."""
        from custom_components.beatify.const import ERR_NAME_INVALID

        success, error = game_state_with_game.add_player("   ", mock_ws)

        assert success is False
        assert error == ERR_NAME_INVALID

    def test_add_player_too_long_rejected(self, game_state_with_game, mock_ws):
        """Name longer than 20 characters is rejected."""
        from custom_components.beatify.const import ERR_NAME_INVALID

        long_name = "A" * 21
        success, error = game_state_with_game.add_player(long_name, mock_ws)

        assert success is False
        assert error == ERR_NAME_INVALID

    def test_add_player_max_length_accepted(self, game_state_with_game, mock_ws):
        """Name exactly 20 characters is accepted."""
        max_name = "A" * 20
        success, error = game_state_with_game.add_player(max_name, mock_ws)

        assert success is True
        assert error is None

    def test_add_player_single_char_accepted(self, game_state_with_game, mock_ws):
        """Single character name is accepted."""
        success, error = game_state_with_game.add_player("X", mock_ws)

        assert success is True
        assert error is None


@pytest.mark.unit
class TestAddPlayerMaxPlayers:
    """Tests for MAX_PLAYERS limit."""

    def test_add_player_max_players_rejected(self, game_state_with_game, mock_ws):
        """Cannot exceed MAX_PLAYERS."""
        from custom_components.beatify.const import ERR_GAME_FULL, MAX_PLAYERS

        # Add MAX_PLAYERS players
        for i in range(MAX_PLAYERS):
            success, error = game_state_with_game.add_player(f"Player{i}", mock_ws)
            assert success is True, f"Failed to add Player{i}"

        # Try to add one more
        success, error = game_state_with_game.add_player("OneMore", mock_ws)

        assert success is False
        assert error == ERR_GAME_FULL
        assert len(game_state_with_game.players) == MAX_PLAYERS

    def test_add_player_at_limit_minus_one(self, game_state_with_game, mock_ws):
        """Can add player when at MAX_PLAYERS - 1."""
        from custom_components.beatify.const import MAX_PLAYERS

        # Add MAX_PLAYERS - 1 players
        for i in range(MAX_PLAYERS - 1):
            game_state_with_game.add_player(f"Player{i}", mock_ws)

        # Should be able to add one more
        success, error = game_state_with_game.add_player("LastPlayer", mock_ws)

        assert success is True
        assert error is None
        assert len(game_state_with_game.players) == MAX_PLAYERS


# =============================================================================
# GET PLAYER TESTS
# =============================================================================


@pytest.mark.unit
class TestGetPlayer:
    """Tests for get_player method."""

    def test_get_player_existing(self, game_state_with_game, mock_ws):
        """Get existing player returns PlayerSession."""
        game_state_with_game.add_player("Tom", mock_ws)

        player = game_state_with_game.get_player("Tom")

        assert player is not None
        assert player.name == "Tom"
        assert player.ws == mock_ws

    def test_get_player_non_existing(self, game_state_with_game):
        """Get non-existing player returns None."""
        player = game_state_with_game.get_player("NonExistent")

        assert player is None

    def test_get_player_case_sensitive(self, game_state_with_game, mock_ws):
        """get_player is case-sensitive (uses exact key)."""
        game_state_with_game.add_player("Tom", mock_ws)

        # Exact match works
        assert game_state_with_game.get_player("Tom") is not None
        # Case variations don't match (stored by original name)
        assert game_state_with_game.get_player("tom") is None
        assert game_state_with_game.get_player("TOM") is None


# =============================================================================
# REMOVE PLAYER TESTS
# =============================================================================


@pytest.mark.unit
class TestRemovePlayer:
    """Tests for remove_player method."""

    def test_remove_player(self, game_state_with_game, mock_ws):
        """Player can be removed."""
        game_state_with_game.add_player("Tom", mock_ws)
        assert "Tom" in game_state_with_game.players

        game_state_with_game.remove_player("Tom")

        assert "Tom" not in game_state_with_game.players

    def test_remove_player_non_existing(self, game_state_with_game):
        """Removing non-existing player doesn't error."""
        # Should not raise
        game_state_with_game.remove_player("NonExistent")

    def test_remove_player_allows_rejoin(self, game_state_with_game, mock_ws):
        """After removal, same name can be used again."""
        game_state_with_game.add_player("Tom", mock_ws)
        game_state_with_game.remove_player("Tom")

        success, error = game_state_with_game.add_player("Tom", mock_ws)

        assert success is True
        assert error is None


# =============================================================================
# GET PLAYERS STATE TESTS
# =============================================================================


@pytest.mark.unit
class TestGetPlayersState:
    """Tests for get_players_state method."""

    def test_get_players_state_empty(self, game_state_with_game):
        """Empty player list returns empty array."""
        result = game_state_with_game.get_players_state()

        assert result == []

    def test_get_players_state_single_player(self, game_state_with_game, mock_ws):
        """Single player state is serialized correctly."""
        game_state_with_game.add_player("Tom", mock_ws)

        result = game_state_with_game.get_players_state()

        assert len(result) == 1
        assert result[0]["name"] == "Tom"
        assert result[0]["score"] == 0
        assert result[0]["connected"] is True
        assert result[0]["streak"] == 0
        # WebSocket should NOT be in serialized state
        assert "ws" not in result[0]

    def test_get_players_state_multiple_players(self, game_state_with_game, mock_ws):
        """Multiple players are serialized correctly."""
        game_state_with_game.add_player("Alice", mock_ws)
        game_state_with_game.add_player("Bob", mock_ws)
        game_state_with_game.add_player("Charlie", mock_ws)

        result = game_state_with_game.get_players_state()

        assert len(result) == 3
        names = [p["name"] for p in result]
        assert "Alice" in names
        assert "Bob" in names
        assert "Charlie" in names


@pytest.mark.unit
class TestGetStateIncludesPlayers:
    """Tests that get_state includes players array."""

    def test_get_state_includes_players(self, game_state_with_game, mock_ws):
        """get_state includes players array."""
        game_state_with_game.add_player("Tom", mock_ws)

        state = game_state_with_game.get_state()

        assert "players" in state
        assert len(state["players"]) == 1
        assert state["players"][0]["name"] == "Tom"
        assert state["player_count"] == 1

    def test_get_state_players_serializable(self, game_state_with_game, mock_ws):
        """get_state players array is JSON serializable."""
        import json

        game_state_with_game.add_player("Tom", mock_ws)
        game_state_with_game.add_player("Alice", mock_ws)

        state = game_state_with_game.get_state()

        # Should not raise
        json_str = json.dumps(state)
        assert '"players"' in json_str
        assert '"Tom"' in json_str
        assert '"Alice"' in json_str


# =============================================================================
# ADMIN FLAG TESTS (Story 3.3)
# =============================================================================


@pytest.mark.unit
class TestLateJoin:
    """Tests for late join functionality (Story 3.6)."""

    def test_add_player_during_playing_phase(self, game_state_with_game, mock_ws):
        """Player can join during PLAYING phase."""
        from custom_components.beatify.game.state import GamePhase

        # Transition to PLAYING
        game_state_with_game.add_player("Admin", mock_ws)
        game_state_with_game.phase = GamePhase.PLAYING

        # Late joiner
        success, error = game_state_with_game.add_player("LatePlayer", mock_ws)

        assert success is True
        assert error is None
        assert "LatePlayer" in game_state_with_game.players
        assert game_state_with_game.players["LatePlayer"].joined_late is True

    def test_add_player_during_reveal_phase(self, game_state_with_game, mock_ws):
        """Player can join during REVEAL phase."""
        from custom_components.beatify.game.state import GamePhase

        # Transition to REVEAL
        game_state_with_game.add_player("Admin", mock_ws)
        game_state_with_game.phase = GamePhase.REVEAL

        # Late joiner
        success, error = game_state_with_game.add_player("LatePlayer", mock_ws)

        assert success is True
        assert error is None
        assert "LatePlayer" in game_state_with_game.players
        assert game_state_with_game.players["LatePlayer"].joined_late is True

    def test_add_player_during_end_phase_rejected(self, game_state_with_game, mock_ws):
        """Player cannot join during END phase."""
        from custom_components.beatify.const import ERR_GAME_ENDED
        from custom_components.beatify.game.state import GamePhase

        # Transition to END
        game_state_with_game.phase = GamePhase.END

        # Try to join
        success, error = game_state_with_game.add_player("TooLate", mock_ws)

        assert success is False
        assert error == ERR_GAME_ENDED
        assert "TooLate" not in game_state_with_game.players

    def test_late_joiner_has_zero_score_and_streak(self, game_state_with_game, mock_ws):
        """Late joiner starts with score=0 and streak=0."""
        from custom_components.beatify.game.state import GamePhase

        # Transition to PLAYING
        game_state_with_game.add_player("Admin", mock_ws)
        game_state_with_game.phase = GamePhase.PLAYING

        # Late joiner
        game_state_with_game.add_player("LatePlayer", mock_ws)

        player = game_state_with_game.players["LatePlayer"]
        assert player.score == 0
        assert player.streak == 0
        assert player.joined_late is True

    def test_lobby_joiner_not_marked_late(self, game_state_with_game, mock_ws):
        """Player joining during LOBBY is not marked as late."""
        success, error = game_state_with_game.add_player("EarlyPlayer", mock_ws)

        assert success is True
        assert game_state_with_game.players["EarlyPlayer"].joined_late is False


@pytest.mark.unit
class TestAdminFlag:
    """Tests for is_admin field and set_admin method."""

    def test_player_default_not_admin(self, game_state_with_game, mock_ws):
        """New player is not admin by default."""
        game_state_with_game.add_player("Tom", mock_ws)

        player = game_state_with_game.get_player("Tom")
        assert player.is_admin is False

    def test_set_admin_success(self, game_state_with_game, mock_ws):
        """set_admin marks player as admin."""
        game_state_with_game.add_player("Tom", mock_ws)

        result = game_state_with_game.set_admin("Tom")

        assert result is True
        player = game_state_with_game.get_player("Tom")
        assert player.is_admin is True

    def test_set_admin_non_existing_player(self, game_state_with_game):
        """set_admin returns False for non-existing player."""
        result = game_state_with_game.set_admin("NonExistent")

        assert result is False

    def test_get_players_state_includes_is_admin(self, game_state_with_game, mock_ws):
        """get_players_state includes is_admin field."""
        game_state_with_game.add_player("Tom", mock_ws)
        game_state_with_game.add_player("Alice", mock_ws)
        game_state_with_game.set_admin("Tom")

        result = game_state_with_game.get_players_state()

        tom_state = next(p for p in result if p["name"] == "Tom")
        alice_state = next(p for p in result if p["name"] == "Alice")

        assert tom_state["is_admin"] is True
        assert alice_state["is_admin"] is False

    def test_get_state_includes_is_admin(self, game_state_with_game, mock_ws):
        """get_state includes is_admin in players array."""
        import json

        game_state_with_game.add_player("Tom", mock_ws)
        game_state_with_game.set_admin("Tom")

        state = game_state_with_game.get_state()

        # Verify JSON serializable
        json_str = json.dumps(state)
        assert '"is_admin": true' in json_str.lower() or '"is_admin":true' in json_str.lower()
