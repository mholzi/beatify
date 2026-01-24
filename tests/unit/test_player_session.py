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


# =============================================================================
# SESSION ID TESTS (Story 11.1)
# =============================================================================


@pytest.mark.unit
class TestSessionIdGeneration:
    """Tests for session ID generation (Story 11.1)."""

    def test_player_session_has_session_id(self, mock_ws):
        """PlayerSession creates unique session_id on instantiation."""
        from custom_components.beatify.game.player import PlayerSession

        player = PlayerSession(name="Tom", ws=mock_ws)

        assert player.session_id is not None
        assert isinstance(player.session_id, str)
        assert len(player.session_id) == 36  # UUID format: 8-4-4-4-12

    def test_session_id_uniqueness(self, mock_ws):
        """Each PlayerSession gets a unique session_id."""
        from custom_components.beatify.game.player import PlayerSession

        player1 = PlayerSession(name="Alice", ws=mock_ws)
        player2 = PlayerSession(name="Bob", ws=mock_ws)
        player3 = PlayerSession(name="Charlie", ws=mock_ws)

        session_ids = [player1.session_id, player2.session_id, player3.session_id]
        assert len(set(session_ids)) == 3  # All unique


@pytest.mark.unit
class TestSessionMapping:
    """Tests for GameState session mapping (Story 11.1)."""

    def test_add_player_registers_session(self, game_state_with_game, mock_ws):
        """add_player registers session_id in _sessions mapping."""
        game_state_with_game.add_player("Tom", mock_ws)

        player = game_state_with_game.get_player("Tom")
        assert player.session_id in game_state_with_game._sessions
        assert game_state_with_game._sessions[player.session_id] == "Tom"

    def test_get_player_by_session_id(self, game_state_with_game, mock_ws):
        """get_player_by_session_id returns correct player."""
        game_state_with_game.add_player("Tom", mock_ws)
        player = game_state_with_game.get_player("Tom")

        found_player = game_state_with_game.get_player_by_session_id(player.session_id)

        assert found_player is not None
        assert found_player.name == "Tom"
        assert found_player.session_id == player.session_id

    def test_get_player_by_session_id_not_found(self, game_state_with_game):
        """get_player_by_session_id returns None for unknown session_id."""
        result = game_state_with_game.get_player_by_session_id("nonexistent-session-id")

        assert result is None

    def test_remove_player_cleans_session(self, game_state_with_game, mock_ws):
        """remove_player removes session from _sessions mapping."""
        game_state_with_game.add_player("Tom", mock_ws)
        player = game_state_with_game.get_player("Tom")
        session_id = player.session_id

        game_state_with_game.remove_player("Tom")

        assert session_id not in game_state_with_game._sessions
        assert game_state_with_game.get_player_by_session_id(session_id) is None

    def test_multiple_players_session_mapping(self, game_state_with_game, mock_ws):
        """Multiple players each have their session registered."""
        game_state_with_game.add_player("Alice", mock_ws)
        game_state_with_game.add_player("Bob", mock_ws)
        game_state_with_game.add_player("Charlie", mock_ws)

        alice = game_state_with_game.get_player("Alice")
        bob = game_state_with_game.get_player("Bob")
        charlie = game_state_with_game.get_player("Charlie")

        assert game_state_with_game.get_player_by_session_id(alice.session_id) == alice
        assert game_state_with_game.get_player_by_session_id(bob.session_id) == bob
        assert game_state_with_game.get_player_by_session_id(charlie.session_id) == charlie


@pytest.mark.unit
class TestSessionIdNotInBroadcast:
    """Tests that session_id is NOT leaked in broadcast state (Story 11.1)."""

    def test_session_id_not_in_get_players_state(self, game_state_with_game, mock_ws):
        """session_id is not included in get_players_state serialization."""
        game_state_with_game.add_player("Tom", mock_ws)

        result = game_state_with_game.get_players_state()

        assert len(result) == 1
        assert "session_id" not in result[0]

    def test_session_id_not_in_get_state(self, game_state_with_game, mock_ws):
        """session_id is not included in get_state players array."""
        import json

        game_state_with_game.add_player("Tom", mock_ws)

        state = game_state_with_game.get_state()

        # Check players array
        for player in state.get("players", []):
            assert "session_id" not in player

        # Double-check via JSON dump
        json_str = json.dumps(state)
        assert "session_id" not in json_str


@pytest.mark.unit
class TestSessionResetOnNewGame:
    """Tests that sessions are reset on new game (Story 11.1)."""

    def test_create_game_resets_sessions(self, mock_ws):
        """create_game clears _sessions mapping."""
        from custom_components.beatify.game.state import GameState

        state = GameState()

        # First game
        state.create_game(
            playlists=["p1.json"],
            songs=[{"year": 1985, "uri": "uri1"}],
            media_player="media_player.test",
            base_url="http://localhost:8123",
        )
        state.add_player("Tom", mock_ws)
        tom_session = state.get_player("Tom").session_id

        # New game
        state.create_game(
            playlists=["p2.json"],
            songs=[{"year": 1990, "uri": "uri2"}],
            media_player="media_player.test",
            base_url="http://localhost:8123",
        )

        # Old session should be cleared
        assert tom_session not in state._sessions
        assert state.get_player_by_session_id(tom_session) is None
        assert len(state._sessions) == 0

    def test_end_game_clears_sessions(self, game_state_with_game, mock_ws):
        """end_game clears _sessions mapping."""
        game_state_with_game.add_player("Tom", mock_ws)
        tom_session = game_state_with_game.get_player("Tom").session_id

        game_state_with_game.end_game()

        assert len(game_state_with_game._sessions) == 0
        assert game_state_with_game.get_player_by_session_id(tom_session) is None


# =============================================================================
# STEAL POWER-UP TESTS (Story 15.3)
# =============================================================================


@pytest.mark.unit
class TestStealFields:
    """Tests for steal power-up fields on PlayerSession (Story 15.3)."""

    def test_player_session_has_steal_fields(self, mock_ws):
        """PlayerSession has steal tracking fields."""
        from custom_components.beatify.game.player import PlayerSession

        player = PlayerSession(name="Tom", ws=mock_ws)

        assert hasattr(player, "steal_available")
        assert hasattr(player, "steal_used")
        assert hasattr(player, "stole_from")
        assert hasattr(player, "was_stolen_by")

    def test_steal_fields_default_values(self, mock_ws):
        """Steal fields have correct default values."""
        from custom_components.beatify.game.player import PlayerSession

        player = PlayerSession(name="Tom", ws=mock_ws)

        assert player.steal_available is False
        assert player.steal_used is False
        assert player.stole_from is None
        assert player.was_stolen_by == []


@pytest.mark.unit
class TestUnlockSteal:
    """Tests for unlock_steal method (Story 15.3)."""

    def test_unlock_steal_success(self, mock_ws):
        """unlock_steal sets steal_available to True."""
        from custom_components.beatify.game.player import PlayerSession

        player = PlayerSession(name="Tom", ws=mock_ws)
        result = player.unlock_steal()

        assert result is True
        assert player.steal_available is True
        assert player.steal_used is False

    def test_unlock_steal_already_available(self, mock_ws):
        """unlock_steal returns False if already available."""
        from custom_components.beatify.game.player import PlayerSession

        player = PlayerSession(name="Tom", ws=mock_ws)
        player.steal_available = True

        result = player.unlock_steal()

        assert result is False
        assert player.steal_available is True

    def test_unlock_steal_already_used(self, mock_ws):
        """unlock_steal returns False if already used."""
        from custom_components.beatify.game.player import PlayerSession

        player = PlayerSession(name="Tom", ws=mock_ws)
        player.steal_used = True

        result = player.unlock_steal()

        assert result is False
        assert player.steal_available is False


@pytest.mark.unit
class TestConsumeSteal:
    """Tests for consume_steal method (Story 15.3)."""

    def test_consume_steal_success(self, mock_ws):
        """consume_steal marks steal as used and records target."""
        from custom_components.beatify.game.player import PlayerSession

        player = PlayerSession(name="Tom", ws=mock_ws)
        player.steal_available = True

        player.consume_steal("Alice")

        assert player.steal_available is False
        assert player.steal_used is True
        assert player.stole_from == "Alice"

    def test_consume_steal_records_target_name(self, mock_ws):
        """consume_steal records target name correctly."""
        from custom_components.beatify.game.player import PlayerSession

        player = PlayerSession(name="Tom", ws=mock_ws)
        player.steal_available = True

        player.consume_steal("Charlie")

        assert player.stole_from == "Charlie"


@pytest.mark.unit
class TestResetRoundClearsSteal:
    """Tests for reset_round clearing steal fields (Story 15.3)."""

    def test_reset_round_clears_per_round_steal_fields(self, mock_ws):
        """reset_round clears stole_from and was_stolen_by but NOT steal_available."""
        from custom_components.beatify.game.player import PlayerSession

        player = PlayerSession(name="Tom", ws=mock_ws)
        player.steal_available = True
        player.stole_from = "Alice"
        player.was_stolen_by = ["Bob", "Charlie"]

        player.reset_round()

        # Per-round fields should be cleared
        assert player.stole_from is None
        assert player.was_stolen_by == []
        # Game-level fields should remain
        assert player.steal_available is True

    def test_reset_round_preserves_steal_used(self, mock_ws):
        """reset_round preserves steal_used flag."""
        from custom_components.beatify.game.player import PlayerSession

        player = PlayerSession(name="Tom", ws=mock_ws)
        player.steal_used = True

        player.reset_round()

        assert player.steal_used is True


@pytest.mark.unit
class TestGetPlayersStateIncludesSteal:
    """Tests that get_players_state includes steal_available (Story 15.3)."""

    def test_get_players_state_includes_steal_available(self, game_state_with_game, mock_ws):
        """get_players_state includes steal_available field."""
        game_state_with_game.add_player("Tom", mock_ws)
        player = game_state_with_game.get_player("Tom")
        player.steal_available = True

        result = game_state_with_game.get_players_state()

        assert len(result) == 1
        assert "steal_available" in result[0]
        assert result[0]["steal_available"] is True

    def test_get_players_state_steal_available_default_false(self, game_state_with_game, mock_ws):
        """get_players_state shows steal_available as False by default."""
        game_state_with_game.add_player("Tom", mock_ws)

        result = game_state_with_game.get_players_state()

        assert result[0]["steal_available"] is False
