"""
Unit Tests: Game State Machine

Tests the game state transitions and invariants:
- LOBBY → PLAYING → REVEAL → END lifecycle
- Player management (join, reconnect, disconnect)
- Round progression
- Timer mechanics with time injection

State Machine (from architecture):
    LOBBY ─[start_game]─► PLAYING ─[reveal]─► REVEAL ─[next_round]─┐
      ▲                                          │                 │
      │                                          ▼                 │
      └────────────────────[end_game]──────────END◄────────────────┘
"""

from __future__ import annotations

import pytest

from tests.support.factories import create_player


# =============================================================================
# STATE TRANSITION TESTS
# =============================================================================


@pytest.mark.unit
class TestStateTransitions:
    """Tests for valid state machine transitions."""

    def test_initial_state_is_lobby(self, game_state):
        """New game should start in LOBBY phase."""
        assert game_state.phase == "LOBBY"
        assert game_state.round == 0

    def test_cannot_start_without_players(self, game_state):
        """Starting game with no players should raise error."""
        with pytest.raises(ValueError, match="at least 2 players"):
            game_state.start_game()

    def test_cannot_start_with_one_player(self, game_state):
        """Starting game with 1 player should raise error."""
        game_state.add_player("Alice", "session-1")
        with pytest.raises(ValueError, match="at least 2 players"):
            game_state.start_game()

    def test_start_game_with_two_players(self, game_state):
        """Game should start with 2+ players."""
        game_state.add_player("Alice", "session-1")
        game_state.add_player("Bob", "session-2")
        game_state.start_game()

        assert game_state.phase == "PLAYING"
        assert game_state.round == 1

    def test_cannot_start_twice(self, game_state):
        """Starting an already-started game should raise error."""
        game_state.add_player("Alice", "session-1")
        game_state.add_player("Bob", "session-2")
        game_state.start_game()

        with pytest.raises(ValueError, match="Cannot start game from phase"):
            game_state.start_game()


# =============================================================================
# PLAYER MANAGEMENT TESTS
# =============================================================================


@pytest.mark.unit
class TestPlayerManagement:
    """Tests for player join/leave/reconnect."""

    def test_add_player(self, game_state):
        """Adding a player should create player entry."""
        player = game_state.add_player("Alice", "session-1")

        assert player["name"] == "Alice"
        assert player["session_id"] == "session-1"
        assert player["score"] == 0
        assert player["connected"] is True

    def test_add_multiple_players(self, game_state):
        """Multiple players should be tracked."""
        game_state.add_player("Alice", "session-1")
        game_state.add_player("Bob", "session-2")
        game_state.add_player("Charlie", "session-3")

        assert len(game_state.players) == 3
        names = [p["name"] for p in game_state.players]
        assert "Alice" in names
        assert "Bob" in names
        assert "Charlie" in names


# =============================================================================
# SERIALIZATION TESTS
# =============================================================================


@pytest.mark.unit
class TestStateSerialization:
    """Tests for state → dict conversion (WebSocket broadcast)."""

    def test_to_dict_basic(self, game_state):
        """Basic serialization should include core fields."""
        state_dict = game_state.to_dict()

        assert "phase" in state_dict
        assert "round" in state_dict
        assert "total_rounds" in state_dict
        assert "players" in state_dict

    def test_to_dict_with_players(self, game_state):
        """Serialization should include player data."""
        game_state.add_player("Alice", "session-1")
        game_state.add_player("Bob", "session-2")

        state_dict = game_state.to_dict()

        assert len(state_dict["players"]) == 2
        assert state_dict["players"][0]["name"] == "Alice"


# =============================================================================
# TIME INJECTION TESTS
# =============================================================================


@pytest.mark.unit
class TestTimeInjection:
    """Tests for deterministic time control."""

    def test_frozen_time(self, game_state, frozen_time):
        """Game state should use injected time function."""
        assert game_state._now() == frozen_time
        assert game_state._now() == 1000.0

    def test_time_does_not_advance(self, game_state):
        """Frozen time should remain constant (no real time passing)."""
        time1 = game_state._now()
        # Simulate some operations
        game_state.add_player("Alice", "session-1")
        game_state.add_player("Bob", "session-2")
        time2 = game_state._now()

        assert time1 == time2  # Time didn't advance


# =============================================================================
# FACTORY INTEGRATION TESTS
# =============================================================================


@pytest.mark.unit
class TestFactoryIntegration:
    """Tests demonstrating factory usage with game state."""

    def test_factory_players_unique(self):
        """Factory should generate unique players."""
        player1 = create_player()
        player2 = create_player()

        assert player1.session_id != player2.session_id
        assert player1.name != player2.name

    def test_factory_with_overrides(self):
        """Factory overrides should be applied."""
        player = create_player(name="Custom", score=100)

        assert player.name == "Custom"
        assert player.score == 100

    def test_add_factory_player_to_game(self, game_state):
        """Factory-created players should integrate with game state."""
        player = create_player(name="TestPlayer")
        game_state.add_player(player.name, player.session_id)

        assert len(game_state.players) == 1
        assert game_state.players[0]["name"] == "TestPlayer"
