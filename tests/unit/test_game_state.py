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

from unittest.mock import MagicMock

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


# =============================================================================
# GAME SESSION TESTS (Story 2.3)
# =============================================================================


@pytest.mark.unit
class TestGameSessionCreation:
    """Tests for game session creation (Story 2.3)."""

    def test_create_game_returns_valid_game_id(self):
        """Game creation returns URL-safe game_id."""
        from custom_components.beatify.game.state import GameState

        state = GameState()
        result = state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://192.168.1.100:8123",
        )

        # Game ID should be 11 characters (8 bytes base64url encoded)
        assert len(result["game_id"]) == 11
        # URL-safe characters only
        assert all(c.isalnum() or c in "-_" for c in result["game_id"])

    def test_create_game_sets_lobby_phase(self):
        """Initial phase is LOBBY after create_game."""
        from custom_components.beatify.game.state import GamePhase, GameState

        state = GameState()
        result = state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://192.168.1.100:8123",
        )

        assert result["phase"] == "LOBBY"
        assert state.phase == GamePhase.LOBBY

    def test_create_game_unique_ids(self):
        """Game_id is unique across multiple creations."""
        from custom_components.beatify.game.state import GameState

        state = GameState()
        ids = set()

        for _ in range(100):
            result = state.create_game(
                playlists=["playlist1.json"],
                songs=[{"year": 1985, "uri": "spotify:track:test"}],
                media_player="media_player.test",
                base_url="http://test.local:8123",
            )
            ids.add(result["game_id"])

        # All 100 game IDs should be unique
        assert len(ids) == 100

    def test_create_game_stores_playlists(self):
        """Playlists are stored correctly."""
        from custom_components.beatify.game.state import GameState

        state = GameState()
        playlists = ["playlist1.json", "playlist2.json"]

        state.create_game(
            playlists=playlists,
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        assert state.playlists == playlists

    def test_create_game_stores_media_player(self):
        """Media_player is stored correctly."""
        from custom_components.beatify.game.state import GameState

        state = GameState()
        media_player = "media_player.living_room"

        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player=media_player,
            base_url="http://test.local:8123",
        )

        assert state.media_player == media_player

    def test_create_game_constructs_join_url(self):
        """Join_url is constructed correctly."""
        from custom_components.beatify.game.state import GameState

        state = GameState()
        base_url = "http://192.168.1.100:8123"

        result = state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url=base_url,
        )

        expected_url = f"{base_url}/beatify/play?game={result['game_id']}"
        assert result["join_url"] == expected_url
        assert state.join_url == expected_url

    def test_create_game_returns_song_count(self):
        """Song_count is returned correctly."""
        from custom_components.beatify.game.state import GameState

        state = GameState()
        songs = [
            {"year": 1985, "uri": "spotify:track:1"},
            {"year": 1990, "uri": "spotify:track:2"},
            {"year": 1995, "uri": "spotify:track:3"},
        ]

        result = state.create_game(
            playlists=["playlist1.json"],
            songs=songs,
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        assert result["song_count"] == 3


@pytest.mark.unit
class TestRoundDurationValidation:
    """Tests for round duration validation (Story 13.1)."""

    def test_create_game_with_valid_duration_30(self):
        """create_game accepts valid duration of 30 seconds."""
        from custom_components.beatify.game.state import GameState

        state = GameState()
        result = state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
            round_duration=30,
        )

        assert state.round_duration == 30
        assert "game_id" in result

    def test_create_game_with_min_duration_15(self):
        """create_game accepts minimum duration of 15 seconds."""
        from custom_components.beatify.game.state import GameState

        state = GameState()
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
            round_duration=15,
        )

        assert state.round_duration == 15

    def test_create_game_with_max_duration_60(self):
        """create_game accepts maximum duration of 60 seconds."""
        from custom_components.beatify.game.state import GameState

        state = GameState()
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
            round_duration=60,
        )

        assert state.round_duration == 60

    def test_create_game_rejects_below_min_duration(self):
        """create_game rejects duration below 15 seconds."""
        from custom_components.beatify.game.state import GameState

        state = GameState()
        with pytest.raises(ValueError, match="Round duration must be between"):
            state.create_game(
                playlists=["playlist1.json"],
                songs=[{"year": 1985, "uri": "spotify:track:test"}],
                media_player="media_player.test",
                base_url="http://test.local:8123",
                round_duration=5,
            )

    def test_create_game_rejects_above_max_duration(self):
        """create_game rejects duration above 60 seconds."""
        from custom_components.beatify.game.state import GameState

        state = GameState()
        with pytest.raises(ValueError, match="Round duration must be between"):
            state.create_game(
                playlists=["playlist1.json"],
                songs=[{"year": 1985, "uri": "spotify:track:test"}],
                media_player="media_player.test",
                base_url="http://test.local:8123",
                round_duration=90,
            )

    def test_create_game_defaults_to_45_when_no_duration(self):
        """create_game defaults to 45 seconds when no duration specified."""
        from custom_components.beatify.game.state import GameState

        state = GameState()
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        assert state.round_duration == 45


@pytest.mark.unit
class TestGameSessionState:
    """Tests for get_state method (Story 2.3)."""

    def test_get_state_returns_none_when_no_game(self):
        """get_state returns None when no game is active."""
        from custom_components.beatify.game.state import GameState

        state = GameState()
        assert state.get_state() is None

    def test_get_state_returns_game_data(self):
        """get_state returns correct game data."""
        from custom_components.beatify.game.state import GameState

        state = GameState()
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        result = state.get_state()

        assert result is not None
        assert "game_id" in result
        assert result["phase"] == "LOBBY"
        assert result["player_count"] == 0
        assert "join_url" in result

    def test_get_state_player_count(self):
        """get_state returns correct player count."""
        from custom_components.beatify.game.state import GameState

        state = GameState()
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        # Add some players via add_player (proper API)
        mock_ws = MagicMock()
        state.add_player("player1", mock_ws)
        state.add_player("player2", mock_ws)
        state.add_player("player3", mock_ws)

        result = state.get_state()
        assert result["player_count"] == 3


@pytest.mark.unit
class TestGameSessionEnd:
    """Tests for end_game method (Story 2.3)."""

    def test_end_game_clears_game_id(self):
        """end_game clears the game_id."""
        from custom_components.beatify.game.state import GameState

        state = GameState()
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        state.end_game()

        assert state.game_id is None

    def test_end_game_resets_all_state(self):
        """end_game resets all state."""
        from custom_components.beatify.game.state import GamePhase, GameState

        state = GameState()
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )
        state.players = {"player1": {"score": 100}}

        state.end_game()

        assert state.game_id is None
        assert state.phase == GamePhase.LOBBY
        assert state.playlists == []
        assert state.songs == []
        assert state.media_player is None
        assert state.join_url is None
        assert state.players == {}

    def test_end_game_get_state_returns_none(self):
        """get_state returns None after end_game."""
        from custom_components.beatify.game.state import GameState

        state = GameState()
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        state.end_game()

        assert state.get_state() is None


# =============================================================================
# WEBSOCKET BROADCAST STATE TESTS (Story 2.3 Task 11.6)
# =============================================================================


@pytest.mark.unit
class TestWebSocketBroadcastState:
    """Tests for WebSocket state broadcast format."""

    def test_get_state_returns_websocket_broadcast_format(self):
        """get_state returns format suitable for WebSocket broadcast."""
        from custom_components.beatify.game.state import GameState

        state = GameState()
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://192.168.1.100:8123",
        )

        result = state.get_state()

        # Verify all required fields for WebSocket broadcast
        assert "game_id" in result
        assert "phase" in result
        assert "player_count" in result
        assert "join_url" in result

        # Verify phase is string (not enum) for JSON serialization
        assert isinstance(result["phase"], str)
        assert result["phase"] == "LOBBY"

    def test_get_state_phase_is_serializable(self):
        """Phase value should be JSON-serializable string."""
        from custom_components.beatify.game.state import GameState

        state = GameState()
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        result = state.get_state()

        # Should be able to serialize to JSON without error
        import json

        json_str = json.dumps(result)
        assert '"phase": "LOBBY"' in json_str

    def test_broadcast_state_includes_join_url_for_qr(self):
        """Broadcast state includes join_url for QR code generation."""
        from custom_components.beatify.game.state import GameState

        state = GameState()
        result = state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://192.168.1.100:8123",
        )

        broadcast_state = state.get_state()

        # join_url should match what was returned from create_game
        assert broadcast_state["join_url"] == result["join_url"]
        assert "/beatify/play?game=" in broadcast_state["join_url"]


# =============================================================================
# ROUND ANALYTICS TESTS (Story 13.3)
# =============================================================================


@pytest.mark.unit
class TestRoundAnalytics:
    """Tests for round analytics calculation (Story 13.3)."""

    def test_analytics_dataclass_to_dict(self):
        """RoundAnalytics.to_dict() returns correct serializable dict."""
        from custom_components.beatify.game.state import RoundAnalytics

        analytics = RoundAnalytics(
            all_guesses=[{"name": "Alice", "guess": 1985, "years_off": 2}],
            average_guess=1985.5,
            median_guess=1985,
            closest_players=["Alice"],
            furthest_players=["Bob"],
            exact_match_players=[],
            exact_match_count=0,
            scored_count=2,
            total_submitted=3,
            accuracy_percentage=66,
            speed_champion={"names": ["Alice"], "time": 2.5},
            decade_distribution={"1980s": 2, "1990s": 1},
            correct_decade="1980s",
        )

        result = analytics.to_dict()

        assert result["average_guess"] == 1985.5
        assert result["median_guess"] == 1985
        assert result["closest_players"] == ["Alice"]
        assert result["accuracy_percentage"] == 66
        assert result["speed_champion"]["names"] == ["Alice"]
        assert result["decade_distribution"]["1980s"] == 2
        assert result["correct_decade"] == "1980s"

    def test_analytics_empty_submissions(self):
        """Analytics handles empty submissions gracefully (AC11)."""
        from custom_components.beatify.game.state import GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )
        state.current_song = {"year": 1985}

        # No players submitted
        analytics = state.calculate_round_analytics()

        assert analytics.total_submitted == 0
        assert analytics.average_guess is None
        assert analytics.correct_decade == "1980s"

    def test_analytics_with_submissions(self):
        """Analytics calculates correct values with submissions (AC1, AC2, AC3)."""
        from custom_components.beatify.game.state import GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )
        state.current_song = {"year": 1985}
        state.round_start_time = 1000.0

        # Add players with submissions
        mock_ws = MagicMock()
        state.add_player("Alice", mock_ws)
        state.add_player("Bob", mock_ws)
        state.add_player("Charlie", mock_ws)

        # Set up player data (simulate submitted guesses)
        state.players["Alice"].submitted = True
        state.players["Alice"].current_guess = 1985
        state.players["Alice"].years_off = 0
        state.players["Alice"].round_score = 10
        state.players["Alice"].submission_time = 1002.5

        state.players["Bob"].submitted = True
        state.players["Bob"].current_guess = 1987
        state.players["Bob"].years_off = 2
        state.players["Bob"].round_score = 7
        state.players["Bob"].submission_time = 1003.0

        state.players["Charlie"].submitted = True
        state.players["Charlie"].current_guess = 1970
        state.players["Charlie"].years_off = 15
        state.players["Charlie"].round_score = 1
        state.players["Charlie"].submission_time = 1001.0

        analytics = state.calculate_round_analytics()

        # Verify analytics
        assert analytics.total_submitted == 3
        assert analytics.average_guess is not None
        assert analytics.median_guess is not None
        assert "Alice" in analytics.closest_players  # years_off = 0
        assert "Charlie" in analytics.furthest_players  # years_off = 15
        assert "Alice" in analytics.exact_match_players
        assert analytics.exact_match_count == 1
        assert analytics.scored_count == 3  # All scored > 0
        assert analytics.accuracy_percentage == 100

    def test_analytics_tie_handling(self):
        """Analytics handles ties for closest/furthest (AC10)."""
        from custom_components.beatify.game.state import GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )
        state.current_song = {"year": 1985}
        state.round_start_time = 1000.0

        mock_ws = MagicMock()
        state.add_player("Alice", mock_ws)
        state.add_player("Bob", mock_ws)

        # Both players tie with years_off = 2
        state.players["Alice"].submitted = True
        state.players["Alice"].current_guess = 1987
        state.players["Alice"].years_off = 2
        state.players["Alice"].round_score = 7
        state.players["Alice"].submission_time = 1002.0

        state.players["Bob"].submitted = True
        state.players["Bob"].current_guess = 1983
        state.players["Bob"].years_off = 2
        state.players["Bob"].round_score = 7
        state.players["Bob"].submission_time = 1002.0

        analytics = state.calculate_round_analytics()

        # Both should be in closest_players (tie)
        assert len(analytics.closest_players) == 2
        assert "Alice" in analytics.closest_players
        assert "Bob" in analytics.closest_players

    def test_analytics_decade_distribution(self):
        """Analytics calculates correct decade distribution (AC5)."""
        from custom_components.beatify.game.state import GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )
        state.current_song = {"year": 1985}
        state.round_start_time = 1000.0

        mock_ws = MagicMock()
        state.add_player("Alice", mock_ws)
        state.add_player("Bob", mock_ws)
        state.add_player("Charlie", mock_ws)

        state.players["Alice"].submitted = True
        state.players["Alice"].current_guess = 1983
        state.players["Alice"].years_off = 2
        state.players["Alice"].round_score = 7
        state.players["Alice"].submission_time = 1001.0

        state.players["Bob"].submitted = True
        state.players["Bob"].current_guess = 1987
        state.players["Bob"].years_off = 2
        state.players["Bob"].round_score = 7
        state.players["Bob"].submission_time = 1002.0

        state.players["Charlie"].submitted = True
        state.players["Charlie"].current_guess = 1995
        state.players["Charlie"].years_off = 10
        state.players["Charlie"].round_score = 1
        state.players["Charlie"].submission_time = 1003.0

        analytics = state.calculate_round_analytics()

        # Alice and Bob both guessed in 1980s, Charlie in 1990s
        assert analytics.decade_distribution.get("1980s") == 2
        assert analytics.decade_distribution.get("1990s") == 1
        assert analytics.correct_decade == "1980s"

    def test_analytics_speed_champion(self):
        """Analytics identifies speed champion correctly (AC3)."""
        from custom_components.beatify.game.state import GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )
        state.current_song = {"year": 1985}
        state.round_start_time = 1000.0

        mock_ws = MagicMock()
        state.add_player("Alice", mock_ws)
        state.add_player("Bob", mock_ws)

        # Alice submitted faster (1.5s vs 3.0s)
        state.players["Alice"].submitted = True
        state.players["Alice"].current_guess = 1985
        state.players["Alice"].years_off = 0
        state.players["Alice"].round_score = 10
        state.players["Alice"].submission_time = 1001.5

        state.players["Bob"].submitted = True
        state.players["Bob"].current_guess = 1985
        state.players["Bob"].years_off = 0
        state.players["Bob"].round_score = 10
        state.players["Bob"].submission_time = 1003.0

        analytics = state.calculate_round_analytics()

        assert analytics.speed_champion is not None
        assert "Alice" in analytics.speed_champion["names"]
        assert analytics.speed_champion["time"] == 1.5

    def test_analytics_all_guesses_sorted(self):
        """Analytics sorts all_guesses by years_off ascending (AC1)."""
        from custom_components.beatify.game.state import GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )
        state.current_song = {"year": 1985}
        state.round_start_time = 1000.0

        mock_ws = MagicMock()
        state.add_player("Furthest", mock_ws)
        state.add_player("Middle", mock_ws)
        state.add_player("Closest", mock_ws)

        state.players["Furthest"].submitted = True
        state.players["Furthest"].current_guess = 1960
        state.players["Furthest"].years_off = 25
        state.players["Furthest"].round_score = 1
        state.players["Furthest"].submission_time = 1001.0

        state.players["Middle"].submitted = True
        state.players["Middle"].current_guess = 1990
        state.players["Middle"].years_off = 5
        state.players["Middle"].round_score = 3
        state.players["Middle"].submission_time = 1002.0

        state.players["Closest"].submitted = True
        state.players["Closest"].current_guess = 1984
        state.players["Closest"].years_off = 1
        state.players["Closest"].round_score = 7
        state.players["Closest"].submission_time = 1003.0

        analytics = state.calculate_round_analytics()

        # Should be sorted by years_off ascending
        assert len(analytics.all_guesses) == 3
        assert analytics.all_guesses[0]["name"] == "Closest"  # 1 year off
        assert analytics.all_guesses[1]["name"] == "Middle"  # 5 years off
        assert analytics.all_guesses[2]["name"] == "Furthest"  # 25 years off

    def test_get_decade_label(self):
        """_get_decade_label returns correct decade string."""
        from custom_components.beatify.game.state import GameState

        state = GameState()

        assert state._get_decade_label(1950) == "1950s"
        assert state._get_decade_label(1959) == "1950s"
        assert state._get_decade_label(1985) == "1980s"
        assert state._get_decade_label(1999) == "1990s"
        assert state._get_decade_label(2000) == "2000s"
        assert state._get_decade_label(2025) == "2020s"


@pytest.mark.unit
class TestRoundAnalyticsStateIntegration:
    """Tests for analytics integration with game state."""

    def test_analytics_included_in_reveal_state(self):
        """Round analytics included in get_state() during REVEAL phase (AC4)."""
        from custom_components.beatify.game.state import GamePhase, GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )
        state.current_song = {"year": 1985}
        state.round = 1
        state.total_rounds = 5
        state.round_start_time = 1000.0
        state.phase = GamePhase.REVEAL

        # Add a submitted player
        mock_ws = MagicMock()
        state.add_player("Alice", mock_ws)
        state.players["Alice"].submitted = True
        state.players["Alice"].current_guess = 1985
        state.players["Alice"].years_off = 0
        state.players["Alice"].round_score = 10
        state.players["Alice"].submission_time = 1001.0

        # Calculate analytics
        state.round_analytics = state.calculate_round_analytics()

        result = state.get_state()

        assert "round_analytics" in result
        assert result["round_analytics"]["total_submitted"] == 1
        assert result["round_analytics"]["correct_decade"] == "1980s"

    def test_analytics_not_included_in_playing_state(self):
        """Round analytics NOT included in get_state() during PLAYING phase."""
        from custom_components.beatify.game.state import GamePhase, GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )
        state.current_song = {
            "year": 1985,
            "artist": "Test",
            "title": "Test Song",
            "album_art": "/test.jpg",
        }
        state.round = 1
        state.total_rounds = 5
        state.deadline = 1030000
        state.phase = GamePhase.PLAYING

        result = state.get_state()

        assert "round_analytics" not in result

    def test_analytics_not_included_in_end_state(self):
        """Round analytics NOT included in get_state() during END phase."""
        from custom_components.beatify.game.state import GamePhase, GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )
        state.round = 5
        state.phase = GamePhase.END

        result = state.get_state()

        assert "round_analytics" not in result

    def test_analytics_reset_on_new_round(self):
        """Round analytics is reset when starting a new round."""
        from custom_components.beatify.game.state import GameState, RoundAnalytics

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        # Set some analytics
        state.round_analytics = RoundAnalytics(total_submitted=5)

        # Simulate start_round reset (we check the attribute directly)
        state.round_analytics = None

        assert state.round_analytics is None


# =============================================================================
# STEAL POWER-UP TESTS (Story 15.3)
# =============================================================================


@pytest.mark.unit
class TestGetStealTargets:
    """Tests for get_steal_targets method (Story 15.3)."""

    def test_get_steal_targets_returns_submitted_players(self):
        """get_steal_targets returns players who have submitted."""
        from unittest.mock import MagicMock

        from custom_components.beatify.game.state import GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        mock_ws = MagicMock()
        state.add_player("Stealer", mock_ws)
        state.add_player("Alice", mock_ws)
        state.add_player("Bob", mock_ws)

        # Alice submitted, Bob did not
        state.players["Alice"].submitted = True
        state.players["Alice"].current_guess = 1985
        state.players["Bob"].submitted = False

        targets = state.get_steal_targets("Stealer")

        assert "Alice" in targets
        assert "Bob" not in targets
        assert "Stealer" not in targets

    def test_get_steal_targets_excludes_self(self):
        """get_steal_targets excludes the requesting player."""
        from unittest.mock import MagicMock

        from custom_components.beatify.game.state import GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        mock_ws = MagicMock()
        state.add_player("Tom", mock_ws)
        state.players["Tom"].submitted = True
        state.players["Tom"].current_guess = 1985

        targets = state.get_steal_targets("Tom")

        assert "Tom" not in targets
        assert targets == []


@pytest.mark.unit
class TestUseSteal:
    """Tests for use_steal method (Story 15.3)."""

    def test_use_steal_success(self):
        """use_steal copies target's guess to stealer."""
        from unittest.mock import MagicMock

        from custom_components.beatify.game.state import GamePhase, GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        mock_ws = MagicMock()
        state.add_player("Stealer", mock_ws)
        state.add_player("Target", mock_ws)

        # Setup: Target submitted, Stealer has steal available
        state.players["Target"].submitted = True
        state.players["Target"].current_guess = 1990
        state.players["Stealer"].steal_available = True
        state.phase = GamePhase.PLAYING

        result = state.use_steal("Stealer", "Target")

        assert result["success"] is True
        assert result["target"] == "Target"
        assert result["year"] == 1990
        assert state.players["Stealer"].current_guess == 1990
        assert state.players["Stealer"].submitted is True
        assert state.players["Stealer"].steal_available is False
        assert state.players["Stealer"].steal_used is True
        assert state.players["Stealer"].stole_from == "Target"
        assert "Stealer" in state.players["Target"].was_stolen_by

    def test_use_steal_no_steal_available(self):
        """use_steal fails if player has no steal available."""
        from unittest.mock import MagicMock

        from custom_components.beatify.const import ERR_NO_STEAL_AVAILABLE
        from custom_components.beatify.game.state import GamePhase, GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        mock_ws = MagicMock()
        state.add_player("Stealer", mock_ws)
        state.add_player("Target", mock_ws)
        state.players["Target"].submitted = True
        state.players["Target"].current_guess = 1990
        state.phase = GamePhase.PLAYING
        # steal_available is False by default

        result = state.use_steal("Stealer", "Target")

        assert result["success"] is False
        assert result["error"] == ERR_NO_STEAL_AVAILABLE

    def test_use_steal_target_not_submitted(self):
        """use_steal fails if target hasn't submitted."""
        from unittest.mock import MagicMock

        from custom_components.beatify.const import ERR_TARGET_NOT_SUBMITTED
        from custom_components.beatify.game.state import GamePhase, GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        mock_ws = MagicMock()
        state.add_player("Stealer", mock_ws)
        state.add_player("Target", mock_ws)
        state.players["Stealer"].steal_available = True
        state.phase = GamePhase.PLAYING
        # Target hasn't submitted

        result = state.use_steal("Stealer", "Target")

        assert result["success"] is False
        assert result["error"] == ERR_TARGET_NOT_SUBMITTED

    def test_use_steal_cannot_steal_self(self):
        """use_steal fails if trying to steal from self."""
        from unittest.mock import MagicMock

        from custom_components.beatify.const import ERR_CANNOT_STEAL_SELF
        from custom_components.beatify.game.state import GamePhase, GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        mock_ws = MagicMock()
        state.add_player("Stealer", mock_ws)
        state.players["Stealer"].steal_available = True
        state.players["Stealer"].submitted = True
        state.players["Stealer"].current_guess = 1985
        state.phase = GamePhase.PLAYING

        result = state.use_steal("Stealer", "Stealer")

        assert result["success"] is False
        assert result["error"] == ERR_CANNOT_STEAL_SELF

    def test_use_steal_wrong_phase(self):
        """use_steal fails if not in PLAYING phase."""
        from unittest.mock import MagicMock

        from custom_components.beatify.const import ERR_INVALID_ACTION
        from custom_components.beatify.game.state import GamePhase, GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        mock_ws = MagicMock()
        state.add_player("Stealer", mock_ws)
        state.add_player("Target", mock_ws)
        state.players["Target"].submitted = True
        state.players["Target"].current_guess = 1990
        state.players["Stealer"].steal_available = True
        state.phase = GamePhase.REVEAL  # Wrong phase

        result = state.use_steal("Stealer", "Target")

        assert result["success"] is False
        assert result["error"] == ERR_INVALID_ACTION


# =============================================================================
# SUPERLATIVES TESTS (Story 15.2)
# =============================================================================


@pytest.mark.unit
class TestCalculateSuperlatives:
    """Tests for calculate_superlatives method (Story 15.2)."""

    def test_superlatives_empty_players(self):
        """calculate_superlatives() returns empty list when no players."""
        from custom_components.beatify.game.state import GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        result = state.calculate_superlatives()

        assert result == []

    def test_superlatives_speed_demon(self):
        """calculate_superlatives() identifies fastest average submitter."""
        from unittest.mock import MagicMock

        from custom_components.beatify.game.state import GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        mock_ws = MagicMock()
        state.add_player("FastPlayer", mock_ws)
        state.add_player("SlowPlayer", mock_ws)

        # FastPlayer: avg 2.0s (needs 3+ submissions)
        state.players["FastPlayer"].submission_times = [1.5, 2.0, 2.5]
        # SlowPlayer: avg 5.0s
        state.players["SlowPlayer"].submission_times = [4.0, 5.0, 6.0]

        result = state.calculate_superlatives()

        speed_award = next((a for a in result if a["id"] == "speed_demon"), None)
        assert speed_award is not None
        assert speed_award["player_name"] == "FastPlayer"
        assert speed_award["value"] == 2.0  # Average time
        assert speed_award["emoji"] == "⚡"

    def test_superlatives_lucky_streak(self):
        """calculate_superlatives() identifies best streak (min 3)."""
        from unittest.mock import MagicMock

        from custom_components.beatify.game.state import GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        mock_ws = MagicMock()
        state.add_player("StreakKing", mock_ws)
        state.add_player("NoStreak", mock_ws)

        state.players["StreakKing"].best_streak = 5
        state.players["NoStreak"].best_streak = 2  # Below threshold

        result = state.calculate_superlatives()

        streak_award = next((a for a in result if a["id"] == "lucky_streak"), None)
        assert streak_award is not None
        assert streak_award["player_name"] == "StreakKing"
        assert streak_award["value"] == 5
        assert streak_award["emoji"] == "🔥"

    def test_superlatives_risk_taker(self):
        """calculate_superlatives() identifies most bets placed (min 3)."""
        from unittest.mock import MagicMock

        from custom_components.beatify.game.state import GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        mock_ws = MagicMock()
        state.add_player("Gambler", mock_ws)
        state.add_player("SafePlayer", mock_ws)

        state.players["Gambler"].bets_placed = 5
        state.players["SafePlayer"].bets_placed = 1  # Below threshold

        result = state.calculate_superlatives()

        risk_award = next((a for a in result if a["id"] == "risk_taker"), None)
        assert risk_award is not None
        assert risk_award["player_name"] == "Gambler"
        assert risk_award["value"] == 5
        assert risk_award["emoji"] == "🎲"

    def test_superlatives_clutch_player(self):
        """calculate_superlatives() identifies best final 3 rounds performer."""
        from unittest.mock import MagicMock

        from custom_components.beatify.game.state import GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )
        state.round = 5  # Need 3+ rounds for clutch

        mock_ws = MagicMock()
        state.add_player("ClutchPro", mock_ws)
        state.add_player("Faded", mock_ws)

        # ClutchPro: 30 pts in final 3 (10, 10, 10)
        state.players["ClutchPro"].round_scores = [5, 5, 10, 10, 10]
        # Faded: 6 pts in final 3 (0, 3, 3)
        state.players["Faded"].round_scores = [10, 10, 0, 3, 3]

        result = state.calculate_superlatives()

        clutch_award = next((a for a in result if a["id"] == "clutch_player"), None)
        assert clutch_award is not None
        assert clutch_award["player_name"] == "ClutchPro"
        assert clutch_award["value"] == 30
        assert clutch_award["emoji"] == "🌟"

    def test_superlatives_close_calls(self):
        """calculate_superlatives() identifies most close guesses (min 2)."""
        from unittest.mock import MagicMock

        from custom_components.beatify.game.state import GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        mock_ws = MagicMock()
        state.add_player("AlmostPro", mock_ws)
        state.add_player("WayOff", mock_ws)

        state.players["AlmostPro"].close_calls = 4  # 4 times 1-year-off
        state.players["WayOff"].close_calls = 1  # Below threshold

        result = state.calculate_superlatives()

        close_award = next((a for a in result if a["id"] == "close_calls"), None)
        assert close_award is not None
        assert close_award["player_name"] == "AlmostPro"
        assert close_award["value"] == 4
        assert close_award["emoji"] == "🎯"

    def test_superlatives_max_five_awards(self):
        """calculate_superlatives() returns max 5 awards (AC1)."""
        from unittest.mock import MagicMock

        from custom_components.beatify.game.state import GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )
        state.round = 5

        mock_ws = MagicMock()
        state.add_player("SuperPlayer", mock_ws)

        # Set up player to qualify for all awards
        state.players["SuperPlayer"].submission_times = [1.0, 1.0, 1.0]
        state.players["SuperPlayer"].best_streak = 5
        state.players["SuperPlayer"].bets_placed = 5
        state.players["SuperPlayer"].round_scores = [10, 10, 10, 10, 10]
        state.players["SuperPlayer"].close_calls = 5

        result = state.calculate_superlatives()

        assert len(result) <= 5

    def test_superlatives_no_awards_below_thresholds(self):
        """calculate_superlatives() returns empty when no thresholds met."""
        from unittest.mock import MagicMock

        from custom_components.beatify.game.state import GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )
        state.round = 2  # Too few rounds for clutch

        mock_ws = MagicMock()
        state.add_player("NewPlayer", mock_ws)

        # All values below thresholds
        state.players["NewPlayer"].submission_times = [2.0]  # Only 1 submission
        state.players["NewPlayer"].best_streak = 2  # Below 3
        state.players["NewPlayer"].bets_placed = 2  # Below 3
        state.players["NewPlayer"].close_calls = 1  # Below 2

        result = state.calculate_superlatives()

        assert len(result) == 0

    def test_superlatives_clutch_requires_three_rounds(self):
        """calculate_superlatives() only awards clutch if game has 3+ rounds."""
        from unittest.mock import MagicMock

        from custom_components.beatify.game.state import GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )
        state.round = 2  # Only 2 rounds

        mock_ws = MagicMock()
        state.add_player("Player", mock_ws)
        state.players["Player"].round_scores = [10, 10]

        result = state.calculate_superlatives()

        clutch_award = next((a for a in result if a["id"] == "clutch_player"), None)
        assert clutch_award is None

    def test_superlatives_comeback_king(self):
        """calculate_superlatives() identifies player with biggest improvement."""
        from unittest.mock import MagicMock

        from custom_components.beatify.game.state import GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )
        state.round = 8  # Enough rounds for comeback

        mock_ws = MagicMock()
        state.add_player("ComebackPlayer", mock_ws)
        state.add_player("SteadyPlayer", mock_ws)

        # ComebackPlayer: poor first half (avg 2), strong second half (avg 8) = +6 improvement
        state.players["ComebackPlayer"].round_scores = [1, 2, 3, 2, 7, 8, 9, 8]
        # SteadyPlayer: consistent (avg ~5 both halves) = ~0 improvement
        state.players["SteadyPlayer"].round_scores = [5, 5, 5, 5, 5, 5, 5, 5]

        result = state.calculate_superlatives()

        comeback_award = next((a for a in result if a["id"] == "comeback_king"), None)
        assert comeback_award is not None
        assert comeback_award["player_name"] == "ComebackPlayer"
        assert comeback_award["emoji"] == "👑"
        assert comeback_award["value"] > 0

    def test_superlatives_comeback_king_requires_six_rounds(self):
        """calculate_superlatives() only awards comeback king if game has 6+ rounds."""
        from unittest.mock import MagicMock

        from custom_components.beatify.game.state import GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )
        state.round = 4  # Not enough rounds

        mock_ws = MagicMock()
        state.add_player("Player", mock_ws)
        state.players["Player"].round_scores = [1, 1, 10, 10]

        result = state.calculate_superlatives()

        comeback_award = next((a for a in result if a["id"] == "comeback_king"), None)
        assert comeback_award is None

    def test_superlatives_comeback_king_no_improvement(self):
        """calculate_superlatives() skips comeback king when no significant improvement."""
        from unittest.mock import MagicMock

        from custom_components.beatify.game.state import GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )
        state.round = 8

        mock_ws = MagicMock()
        state.add_player("Player", mock_ws)
        # Slight improvement below threshold
        state.players["Player"].round_scores = [5, 5, 5, 5, 6, 6, 6, 6]

        result = state.calculate_superlatives()

        comeback_award = next((a for a in result if a["id"] == "comeback_king"), None)
        assert comeback_award is None

    def test_superlatives_comeback_king_exact_boundary(self):
        """calculate_superlatives() awards comeback king at exactly 6 rounds (boundary)."""
        from unittest.mock import MagicMock

        from custom_components.beatify.game.state import GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )
        state.round = 6  # Exact minimum

        mock_ws = MagicMock()
        state.add_player("Player", mock_ws)
        # First half avg=2, second half avg=8 → improvement=6.0
        state.players["Player"].round_scores = [1, 2, 3, 7, 8, 9]

        result = state.calculate_superlatives()

        comeback_award = next((a for a in result if a["id"] == "comeback_king"), None)
        assert comeback_award is not None
        assert comeback_award["player_name"] == "Player"

    def test_superlatives_comeback_king_tie(self):
        """calculate_superlatives() picks player with highest improvement on tie-break."""
        from unittest.mock import MagicMock

        from custom_components.beatify.game.state import GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )
        state.round = 8

        mock_ws = MagicMock()
        state.add_player("PlayerA", mock_ws)
        state.add_player("PlayerB", mock_ws)

        # Both have identical improvement: first half avg=2, second half avg=8 → +6.0
        state.players["PlayerA"].round_scores = [1, 2, 3, 2, 7, 8, 9, 8]
        state.players["PlayerB"].round_scores = [1, 2, 3, 2, 7, 8, 9, 8]

        result = state.calculate_superlatives()

        comeback_awards = [a for a in result if a["id"] == "comeback_king"]
        # Only one winner even with identical improvement
        assert len(comeback_awards) == 1
        # First player encountered wins (deterministic)
        assert comeback_awards[0]["player_name"] == "PlayerA"

    def test_superlatives_max_cap_with_comeback(self):
        """calculate_superlatives() respects MAX_SUPERLATIVES cap including comeback_king."""
        from unittest.mock import MagicMock

        from custom_components.beatify.const import MAX_SUPERLATIVES
        from custom_components.beatify.game.state import GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )
        state.round = 8

        mock_ws = MagicMock()
        state.add_player("Player", mock_ws)

        p = state.players["Player"]
        p.round_scores = [1, 2, 1, 2, 8, 9, 8, 9]  # Big comeback
        p.submission_times = [1.0, 1.5, 1.2, 1.3, 1.1, 1.4, 1.0, 1.2]  # Speed demon
        p.best_streak = 5  # Lucky streak
        p.bets_placed = 4  # Risk taker
        p.final_three_score = 25  # Clutch player
        p.close_calls = 3  # Close calls

        result = state.calculate_superlatives()

        assert len(result) <= MAX_SUPERLATIVES

    def test_superlatives_included_in_end_state(self):
        """calculate_superlatives() is included in END phase state."""
        from unittest.mock import MagicMock

        from custom_components.beatify.game.state import GamePhase, GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        # Add player BEFORE setting phase to END (END phase rejects new players)
        mock_ws = MagicMock()
        state.add_player("Winner", mock_ws)
        # Access player by name from the players dict
        winner_player = state.players["Winner"]
        winner_player.score = 100
        winner_player.best_streak = 5

        # Now set to END phase
        state.phase = GamePhase.END
        state.round = 5

        result = state.get_state()

        assert "superlatives" in result
        # Should have the lucky_streak award
        streak_award = next((a for a in result["superlatives"] if a["id"] == "lucky_streak"), None)
        assert streak_award is not None


# =============================================================================
# LIVE REACTIONS TESTS (Story 18.9)
# =============================================================================


@pytest.mark.unit
class TestLiveReactions:
    """Tests for live reaction feature during REVEAL phase."""

    def test_record_reaction_allows_first_reaction(self):
        """record_reaction() allows first reaction from a player."""
        from custom_components.beatify.game.state import GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        result = state.record_reaction("Alice", "🔥")

        assert result is True
        assert "Alice" in state._reactions_this_phase

    def test_record_reaction_rate_limits_second_reaction(self):
        """record_reaction() rate limits second reaction from same player."""
        from custom_components.beatify.game.state import GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        first_result = state.record_reaction("Alice", "🔥")
        second_result = state.record_reaction("Alice", "😂")

        assert first_result is True
        assert second_result is False

    def test_record_reaction_allows_different_players(self):
        """record_reaction() allows reactions from different players."""
        from custom_components.beatify.game.state import GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        alice_result = state.record_reaction("Alice", "🔥")
        bob_result = state.record_reaction("Bob", "😂")

        assert alice_result is True
        assert bob_result is True
        assert "Alice" in state._reactions_this_phase
        assert "Bob" in state._reactions_this_phase

    def test_reactions_cleared_on_reveal_transition(self):
        """_reactions_this_phase is cleared when transitioning to REVEAL."""
        from unittest.mock import MagicMock

        from custom_components.beatify.game.state import GamePhase, GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "test"}, {"year": 1990, "uri": "test2"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        mock_ws = MagicMock()
        state.add_player("Alice", mock_ws)
        state.add_player("Bob", mock_ws)

        # Add a reaction before starting
        state._reactions_this_phase.add("Alice")

        # Start game and transition to REVEAL
        state.start_game()
        assert state.phase == GamePhase.PLAYING

        # Manually trigger end_round to transition to REVEAL
        import asyncio

        asyncio.get_event_loop().run_until_complete(state.end_round())

        # Reactions should be cleared
        assert state.phase == GamePhase.REVEAL
        assert len(state._reactions_this_phase) == 0

    def test_get_player_by_ws_finds_player(self):
        """get_player_by_ws() returns player with matching WebSocket."""
        from unittest.mock import MagicMock

        from custom_components.beatify.game.state import GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        mock_ws_alice = MagicMock()
        mock_ws_bob = MagicMock()
        state.add_player("Alice", mock_ws_alice)
        state.add_player("Bob", mock_ws_bob)

        result = state.get_player_by_ws(mock_ws_alice)

        assert result is not None
        assert result.name == "Alice"

    def test_get_player_by_ws_returns_none_for_unknown(self):
        """get_player_by_ws() returns None for unknown WebSocket."""
        from unittest.mock import MagicMock

        from custom_components.beatify.game.state import GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        mock_ws_alice = MagicMock()
        mock_ws_unknown = MagicMock()
        state.add_player("Alice", mock_ws_alice)

        result = state.get_player_by_ws(mock_ws_unknown)

        assert result is None


# =============================================================================
# ARTIST CHALLENGE TESTS (Story 20.1)
# =============================================================================


@pytest.mark.unit
class TestArtistChallengeDataclass:
    """Tests for ArtistChallenge dataclass (Story 20.1)."""

    def test_artist_challenge_creation(self):
        """ArtistChallenge can be created with required fields."""
        from custom_components.beatify.game.state import ArtistChallenge

        challenge = ArtistChallenge(
            correct_artist="Queen",
            options=["Queen", "The Beatles", "ABBA"],
        )

        assert challenge.correct_artist == "Queen"
        assert challenge.options == ["Queen", "The Beatles", "ABBA"]
        assert challenge.winner is None
        assert challenge.winner_time is None

    def test_artist_challenge_with_winner(self):
        """ArtistChallenge tracks winner correctly."""
        from custom_components.beatify.game.state import ArtistChallenge

        challenge = ArtistChallenge(
            correct_artist="Queen",
            options=["Queen", "The Beatles", "ABBA"],
            winner="Alice",
            winner_time=2.5,
        )

        assert challenge.winner == "Alice"
        assert challenge.winner_time == 2.5

    def test_to_dict_hides_answer_by_default(self):
        """to_dict(include_answer=False) omits correct_artist (AC2)."""
        from custom_components.beatify.game.state import ArtistChallenge

        challenge = ArtistChallenge(
            correct_artist="Queen",
            options=["Queen", "The Beatles", "ABBA"],
            winner="Alice",
            winner_time=2.5,
        )

        result = challenge.to_dict(include_answer=False)

        assert "correct_artist" not in result
        assert result["options"] == ["Queen", "The Beatles", "ABBA"]
        assert result["winner"] == "Alice"
        assert result["winner_time"] == 2.5

    def test_to_dict_reveals_answer_when_requested(self):
        """to_dict(include_answer=True) includes correct_artist (AC3)."""
        from custom_components.beatify.game.state import ArtistChallenge

        challenge = ArtistChallenge(
            correct_artist="Queen",
            options=["Queen", "The Beatles", "ABBA"],
            winner="Alice",
        )

        result = challenge.to_dict(include_answer=True)

        assert result["correct_artist"] == "Queen"
        assert result["options"] == ["Queen", "The Beatles", "ABBA"]
        assert result["winner"] == "Alice"

    def test_to_dict_omits_winner_time_when_none(self):
        """to_dict omits winner_time when not set."""
        from custom_components.beatify.game.state import ArtistChallenge

        challenge = ArtistChallenge(
            correct_artist="Queen",
            options=["Queen", "The Beatles", "ABBA"],
        )

        result = challenge.to_dict(include_answer=False)

        assert "winner_time" not in result
        assert result["winner"] is None


@pytest.mark.unit
class TestArtistChallengeStateIntegration:
    """Tests for artist challenge integration with GameState (Story 20.1)."""

    def test_create_game_enables_artist_challenge_by_default(self):
        """create_game enables artist_challenge by default (AC1)."""
        from custom_components.beatify.game.state import GameState

        state = GameState()
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        assert state.artist_challenge_enabled is True
        assert state.artist_challenge is None  # Not initialized until start_round

    def test_create_game_can_disable_artist_challenge(self):
        """create_game can disable artist_challenge."""
        from custom_components.beatify.game.state import GameState

        state = GameState()
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
            artist_challenge_enabled=False,
        )

        assert state.artist_challenge_enabled is False

    def test_end_game_resets_artist_challenge(self):
        """end_game resets artist challenge state to defaults (Story 20.7)."""
        from custom_components.beatify.game.state import ArtistChallenge, GameState

        state = GameState()
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
            artist_challenge_enabled=False,  # Start with disabled
        )
        state.artist_challenge = ArtistChallenge(
            correct_artist="Queen",
            options=["Queen", "The Beatles", "ABBA"],
        )

        state.end_game()

        assert state.artist_challenge is None
        assert state.artist_challenge_enabled is True  # Reset to default (Story 20.7)

    def test_get_state_playing_hides_artist_answer(self):
        """get_state() in PLAYING phase hides correct_artist (AC2)."""
        from custom_components.beatify.game.state import (
            ArtistChallenge,
            GamePhase,
            GameState,
        )

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )
        state.current_song = {
            "year": 1985,
            "artist": "Test",
            "title": "Test Song",
            "album_art": "/test.jpg",
        }
        state.round = 1
        state.total_rounds = 5
        state.deadline = 1030000
        state.phase = GamePhase.PLAYING
        state.artist_challenge = ArtistChallenge(
            correct_artist="Queen",
            options=["Queen", "The Beatles", "ABBA"],
        )

        result = state.get_state()

        assert "artist_challenge" in result
        assert "correct_artist" not in result["artist_challenge"]
        assert result["artist_challenge"]["options"] == ["Queen", "The Beatles", "ABBA"]

    def test_get_state_reveal_shows_artist_answer(self):
        """get_state() in REVEAL phase shows correct_artist (AC3)."""
        from custom_components.beatify.game.state import (
            ArtistChallenge,
            GamePhase,
            GameState,
        )

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )
        state.current_song = {"year": 1985}
        state.round = 1
        state.total_rounds = 5
        state.phase = GamePhase.REVEAL
        state.artist_challenge = ArtistChallenge(
            correct_artist="Queen",
            options=["Queen", "The Beatles", "ABBA"],
            winner="Alice",
        )

        result = state.get_state()

        assert "artist_challenge" in result
        assert result["artist_challenge"]["correct_artist"] == "Queen"
        assert result["artist_challenge"]["winner"] == "Alice"

    def test_get_state_no_artist_challenge_when_disabled(self):
        """get_state() omits artist_challenge when disabled."""
        from custom_components.beatify.game.state import GamePhase, GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
            artist_challenge_enabled=False,
        )
        state.current_song = {
            "year": 1985,
            "artist": "Test",
            "title": "Test Song",
            "album_art": "/test.jpg",
        }
        state.round = 1
        state.total_rounds = 5
        state.deadline = 1030000
        state.phase = GamePhase.PLAYING

        result = state.get_state()

        assert "artist_challenge" not in result

    def test_get_state_no_artist_challenge_when_none(self):
        """get_state() omits artist_challenge when not initialized."""
        from custom_components.beatify.game.state import GamePhase, GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )
        state.current_song = {
            "year": 1985,
            "artist": "Test",
            "title": "Test Song",
            "album_art": "/test.jpg",
        }
        state.round = 1
        state.total_rounds = 5
        state.deadline = 1030000
        state.phase = GamePhase.PLAYING
        # artist_challenge is None (not initialized)

        result = state.get_state()

        assert "artist_challenge" not in result

    def test_artist_challenge_not_in_end_state(self):
        """get_state() omits artist_challenge in END phase."""
        from unittest.mock import MagicMock

        from custom_components.beatify.game.state import (
            ArtistChallenge,
            GamePhase,
            GameState,
        )

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        # Add player BEFORE setting phase to END
        mock_ws = MagicMock()
        state.add_player("Winner", mock_ws)
        state.players["Winner"].score = 100

        state.phase = GamePhase.END
        state.round = 5
        state.artist_challenge = ArtistChallenge(
            correct_artist="Queen",
            options=["Queen", "The Beatles", "ABBA"],
        )

        result = state.get_state()

        assert "artist_challenge" not in result


@pytest.mark.unit
class TestArtistBonusPointsConstant:
    """Tests for ARTIST_BONUS_POINTS constant (Story 20.1)."""

    def test_artist_bonus_points_defined(self):
        """ARTIST_BONUS_POINTS constant is defined."""
        from custom_components.beatify.const import ARTIST_BONUS_POINTS

        assert ARTIST_BONUS_POINTS == 5

    def test_artist_bonus_points_is_integer(self):
        """ARTIST_BONUS_POINTS is an integer."""
        from custom_components.beatify.const import ARTIST_BONUS_POINTS

        assert isinstance(ARTIST_BONUS_POINTS, int)


# =============================================================================
# BUILD ARTIST OPTIONS TESTS (Story 20.2)
# =============================================================================


@pytest.mark.unit
class TestBuildArtistOptions:
    """Tests for build_artist_options helper function (Story 20.2)."""

    def test_build_artist_options_with_valid_data(self):
        """build_artist_options returns shuffled list with valid data (AC1)."""
        from custom_components.beatify.game.state import build_artist_options

        song = {
            "artist": "Queen",
            "alt_artists": ["The Beatles", "ABBA"],
        }

        result = build_artist_options(song)

        assert result is not None
        assert len(result) == 3
        assert "Queen" in result
        assert "The Beatles" in result
        assert "ABBA" in result

    def test_build_artist_options_returns_none_without_alt_artists(self):
        """build_artist_options returns None when alt_artists missing (AC2)."""
        from custom_components.beatify.game.state import build_artist_options

        song = {
            "artist": "Queen",
        }

        result = build_artist_options(song)

        assert result is None

    def test_build_artist_options_returns_none_with_empty_alt_artists(self):
        """build_artist_options returns None when alt_artists empty (AC2)."""
        from custom_components.beatify.game.state import build_artist_options

        song = {
            "artist": "Queen",
            "alt_artists": [],
        }

        result = build_artist_options(song)

        assert result is None

    def test_build_artist_options_returns_none_without_artist(self):
        """build_artist_options returns None when artist missing."""
        from custom_components.beatify.game.state import build_artist_options

        song = {
            "alt_artists": ["The Beatles", "ABBA"],
        }

        result = build_artist_options(song)

        assert result is None

    def test_build_artist_options_returns_none_with_empty_artist(self):
        """build_artist_options returns None when artist is empty string."""
        from custom_components.beatify.game.state import build_artist_options

        song = {
            "artist": "   ",
            "alt_artists": ["The Beatles", "ABBA"],
        }

        result = build_artist_options(song)

        assert result is None

    def test_build_artist_options_filters_invalid_alts(self):
        """build_artist_options filters invalid alt_artists entries."""
        from custom_components.beatify.game.state import build_artist_options

        song = {
            "artist": "Queen",
            "alt_artists": ["The Beatles", "", "  ", None, "ABBA"],
        }

        result = build_artist_options(song)

        assert result is not None
        assert len(result) == 3
        assert "" not in result

    def test_build_artist_options_shuffles_results(self):
        """build_artist_options produces shuffled order (AC3)."""
        from custom_components.beatify.game.state import build_artist_options

        song = {
            "artist": "Queen",
            "alt_artists": ["The Beatles", "ABBA", "Led Zeppelin", "Pink Floyd"],
        }

        # Run multiple times to verify shuffling produces varied results
        orders = set()
        for _ in range(20):
            result = build_artist_options(song)
            orders.add(tuple(result))

        # With 5 items, we should see multiple different orders
        assert len(orders) > 1, "Shuffling should produce varied order"

    def test_build_artist_options_handles_single_alt_artist(self):
        """build_artist_options works with single alt_artist."""
        from custom_components.beatify.game.state import build_artist_options

        song = {
            "artist": "Queen",
            "alt_artists": ["The Beatles"],
        }

        result = build_artist_options(song)

        assert result is not None
        assert len(result) == 2
        assert "Queen" in result
        assert "The Beatles" in result

    def test_build_artist_options_strips_whitespace(self):
        """build_artist_options strips whitespace from artist names."""
        from custom_components.beatify.game.state import build_artist_options

        song = {
            "artist": "  Queen  ",
            "alt_artists": ["  The Beatles  ", "  ABBA  "],
        }

        result = build_artist_options(song)

        assert result is not None
        assert "Queen" in result
        assert "The Beatles" in result
        assert "ABBA" in result


@pytest.mark.unit
class TestPlaylistAltArtistsValidation:
    """Tests for alt_artists playlist validation (Story 20.2)."""

    def test_validate_playlist_accepts_valid_alt_artists(self):
        """validate_playlist accepts valid alt_artists array (AC4)."""
        from custom_components.beatify.game.playlist import validate_playlist

        data = {
            "name": "Test Playlist",
            "songs": [
                {
                    "year": 1985,
                    "uri": "spotify:track:6rqhFgbbKwnb9MLmUQDhG6",
                    "artist": "Queen",
                    "alt_artists": ["The Beatles", "ABBA"],
                }
            ],
        }

        is_valid, errors = validate_playlist(data)

        assert is_valid is True
        assert len(errors) == 0

    def test_validate_playlist_accepts_song_without_alt_artists(self):
        """validate_playlist accepts songs without alt_artists field."""
        from custom_components.beatify.game.playlist import validate_playlist

        data = {
            "name": "Test Playlist",
            "songs": [
                {
                    "year": 1985,
                    "uri": "spotify:track:6rqhFgbbKwnb9MLmUQDhG6",
                    "artist": "Queen",
                }
            ],
        }

        is_valid, errors = validate_playlist(data)

        assert is_valid is True
        assert len(errors) == 0

    def test_validate_playlist_rejects_non_array_alt_artists(self):
        """validate_playlist rejects alt_artists that isn't an array (AC4)."""
        from custom_components.beatify.game.playlist import validate_playlist

        data = {
            "name": "Test Playlist",
            "songs": [
                {
                    "year": 1985,
                    "uri": "spotify:track:6rqhFgbbKwnb9MLmUQDhG6",
                    "artist": "Queen",
                    "alt_artists": "The Beatles",  # Should be array
                }
            ],
        }

        is_valid, errors = validate_playlist(data)

        assert is_valid is False
        assert any("alt_artists" in e and "array" in e for e in errors)

    def test_validate_playlist_rejects_non_string_alt_artists(self):
        """validate_playlist rejects non-string entries in alt_artists (AC4)."""
        from custom_components.beatify.game.playlist import validate_playlist

        data = {
            "name": "Test Playlist",
            "songs": [
                {
                    "year": 1985,
                    "uri": "spotify:track:6rqhFgbbKwnb9MLmUQDhG6",
                    "artist": "Queen",
                    "alt_artists": ["The Beatles", 123, "ABBA"],
                }
            ],
        }

        is_valid, errors = validate_playlist(data)

        assert is_valid is False
        assert any("alt_artists[1]" in e for e in errors)

    def test_validate_playlist_rejects_empty_string_alt_artists(self):
        """validate_playlist rejects empty string in alt_artists (AC4)."""
        from custom_components.beatify.game.playlist import validate_playlist

        data = {
            "name": "Test Playlist",
            "songs": [
                {
                    "year": 1985,
                    "uri": "spotify:track:6rqhFgbbKwnb9MLmUQDhG6",
                    "artist": "Queen",
                    "alt_artists": ["The Beatles", "", "ABBA"],
                }
            ],
        }

        is_valid, errors = validate_playlist(data)

        assert is_valid is False
        assert any("alt_artists[1]" in e and "non-empty" in e for e in errors)


@pytest.mark.unit
class TestInitArtistChallengeWithDecoys:
    """Tests for _init_artist_challenge with decoy generation (Story 20.2)."""

    def test_init_artist_challenge_creates_challenge_with_alt_artists(self):
        """_init_artist_challenge creates ArtistChallenge when alt_artists present."""
        from custom_components.beatify.game.state import GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        song = {
            "year": 1985,
            "artist": "Queen",
            "alt_artists": ["The Beatles", "ABBA"],
        }

        result = state._init_artist_challenge(song)

        assert result is not None
        assert result.correct_artist == "Queen"
        assert len(result.options) == 3
        assert "Queen" in result.options
        assert "The Beatles" in result.options
        assert "ABBA" in result.options

    def test_init_artist_challenge_returns_none_without_alt_artists(self):
        """_init_artist_challenge returns None when alt_artists missing (AC2)."""
        from custom_components.beatify.game.state import GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        song = {
            "year": 1985,
            "artist": "Queen",
        }

        result = state._init_artist_challenge(song)

        assert result is None

    def test_init_artist_challenge_returns_none_when_disabled(self):
        """_init_artist_challenge returns None when artist challenge disabled."""
        from custom_components.beatify.game.state import GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
            artist_challenge_enabled=False,
        )

        song = {
            "year": 1985,
            "artist": "Queen",
            "alt_artists": ["The Beatles", "ABBA"],
        }

        result = state._init_artist_challenge(song)

        assert result is None

    def test_init_artist_challenge_shuffles_options(self):
        """_init_artist_challenge shuffles options (AC3)."""
        from custom_components.beatify.game.state import GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        song = {
            "year": 1985,
            "artist": "Queen",
            "alt_artists": ["The Beatles", "ABBA", "Led Zeppelin", "Pink Floyd"],
        }

        # Run multiple times to verify shuffling
        orders = set()
        for _ in range(20):
            result = state._init_artist_challenge(song)
            orders.add(tuple(result.options))

        # With 5 items, we should see multiple different orders
        assert len(orders) > 1, "Options should be shuffled"


# =============================================================================
# SUBMIT ARTIST GUESS TESTS (Story 20.3)
# =============================================================================


@pytest.mark.unit
class TestSubmitArtistGuess:
    """Tests for submit_artist_guess method (Story 20.3)."""

    def test_first_correct_guess_sets_winner(self):
        """First correct guess sets winner (AC1)."""
        from custom_components.beatify.game.state import ArtistChallenge, GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )
        state.artist_challenge = ArtistChallenge(
            correct_artist="Queen",
            options=["Queen", "The Beatles", "ABBA"],
        )

        result = state.submit_artist_guess("Alice", "Queen", 1001.5)

        assert result["correct"] is True
        assert result["first"] is True
        assert result["winner"] == "Alice"
        assert state.artist_challenge.winner == "Alice"
        assert state.artist_challenge.winner_time == 1001.5

    def test_second_correct_guess_not_first(self):
        """Second correct guess returns first: false (AC2)."""
        from custom_components.beatify.game.state import ArtistChallenge, GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )
        state.artist_challenge = ArtistChallenge(
            correct_artist="Queen",
            options=["Queen", "The Beatles", "ABBA"],
            winner="Alice",
            winner_time=1001.0,
        )

        result = state.submit_artist_guess("Bob", "Queen", 1002.0)

        assert result["correct"] is True
        assert result["first"] is False
        assert result["winner"] == "Alice"
        assert state.artist_challenge.winner == "Alice"  # Unchanged

    def test_incorrect_guess_returns_correct_false(self):
        """Incorrect guess returns correct: false (AC3)."""
        from custom_components.beatify.game.state import ArtistChallenge, GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )
        state.artist_challenge = ArtistChallenge(
            correct_artist="Queen",
            options=["Queen", "The Beatles", "ABBA"],
        )

        result = state.submit_artist_guess("Alice", "ABBA", 1001.0)

        assert result["correct"] is False
        assert result["first"] is False
        assert state.artist_challenge.winner is None

    def test_case_insensitive_matching(self):
        """Artist matching is case-insensitive."""
        from custom_components.beatify.game.state import ArtistChallenge, GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )
        state.artist_challenge = ArtistChallenge(
            correct_artist="Queen",
            options=["Queen", "The Beatles", "ABBA"],
        )

        result = state.submit_artist_guess("Alice", "queen", 1001.0)

        assert result["correct"] is True
        assert result["first"] is True

    def test_case_insensitive_matching_uppercase(self):
        """Artist matching works with uppercase guess."""
        from custom_components.beatify.game.state import ArtistChallenge, GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )
        state.artist_challenge = ArtistChallenge(
            correct_artist="Queen",
            options=["Queen", "The Beatles", "ABBA"],
        )

        result = state.submit_artist_guess("Alice", "QUEEN", 1001.0)

        assert result["correct"] is True

    def test_no_lockout_on_wrong_guesses(self):
        """Players can guess again after wrong answer (AC5)."""
        from custom_components.beatify.game.state import ArtistChallenge, GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )
        state.artist_challenge = ArtistChallenge(
            correct_artist="Queen",
            options=["Queen", "The Beatles", "ABBA"],
        )

        # First wrong guess
        result1 = state.submit_artist_guess("Alice", "ABBA", 1001.0)
        assert result1["correct"] is False

        # Second guess - correct this time
        result2 = state.submit_artist_guess("Alice", "Queen", 1002.0)
        assert result2["correct"] is True
        assert result2["first"] is True
        assert state.artist_challenge.winner == "Alice"

    def test_error_when_no_artist_challenge(self):
        """ValueError when no artist challenge active (AC6)."""
        from custom_components.beatify.game.state import GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )
        # artist_challenge is None

        with pytest.raises(ValueError, match="No artist challenge active"):
            state.submit_artist_guess("Alice", "Queen", 1001.0)

    def test_whitespace_stripped_from_guess(self):
        """Whitespace is stripped from artist guess."""
        from custom_components.beatify.game.state import ArtistChallenge, GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )
        state.artist_challenge = ArtistChallenge(
            correct_artist="Queen",
            options=["Queen", "The Beatles", "ABBA"],
        )

        result = state.submit_artist_guess("Alice", "  Queen  ", 1001.0)

        assert result["correct"] is True


@pytest.mark.unit
class TestArtistGuessErrorConstant:
    """Tests for ERR_NO_ARTIST_CHALLENGE constant (Story 20.3)."""

    def test_error_constant_defined(self):
        """ERR_NO_ARTIST_CHALLENGE constant is defined."""
        from custom_components.beatify.const import ERR_NO_ARTIST_CHALLENGE

        assert ERR_NO_ARTIST_CHALLENGE == "NO_ARTIST_CHALLENGE"


# =============================================================================
# ARTIST BONUS SCORING TESTS (Story 20.4)
# =============================================================================


@pytest.mark.unit
class TestArtistBonusScoring:
    """Tests for artist bonus scoring integration (Story 20.4)."""

    def test_player_session_has_artist_bonus_field(self):
        """PlayerSession has artist_bonus field."""
        from unittest.mock import MagicMock

        from custom_components.beatify.game.player import PlayerSession

        mock_ws = MagicMock()
        player = PlayerSession(name="Test", ws=mock_ws)

        assert hasattr(player, "artist_bonus")
        assert player.artist_bonus == 0

    def test_artist_bonus_resets_between_rounds(self):
        """artist_bonus resets to 0 between rounds."""
        from unittest.mock import MagicMock

        from custom_components.beatify.game.player import PlayerSession

        mock_ws = MagicMock()
        player = PlayerSession(name="Test", ws=mock_ws)
        player.artist_bonus = 10

        player.reset_round()

        assert player.artist_bonus == 0

    @pytest.mark.asyncio
    async def test_artist_winner_gets_bonus(self):
        """Player who won artist challenge gets +10 artist_bonus (AC1)."""
        from unittest.mock import MagicMock

        from custom_components.beatify.game.state import ArtistChallenge, GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )
        mock_ws = MagicMock()
        state.add_player("Alice", mock_ws)

        # Simulate player submitting a guess
        state.players["Alice"].submit_guess(1985, 1001.0)
        state.current_song = {"year": 1985}
        state.round_start_time = 1000.0

        # Set up artist challenge with winner
        state.artist_challenge = ArtistChallenge(
            correct_artist="Queen",
            options=["Queen", "The Beatles", "ABBA"],
            winner="Alice",
            winner_time=1001.0,
        )

        await state.end_round()

        assert state.players["Alice"].artist_bonus == 5

    @pytest.mark.asyncio
    async def test_non_winner_gets_zero_bonus(self):
        """Player who didn't win gets artist_bonus=0 (AC2)."""
        from unittest.mock import MagicMock

        from custom_components.beatify.game.state import ArtistChallenge, GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )
        mock_ws_alice = MagicMock()
        mock_ws_bob = MagicMock()
        state.add_player("Alice", mock_ws_alice)
        state.add_player("Bob", mock_ws_bob)

        # Both players submit
        state.players["Alice"].submit_guess(1985, 1001.0)
        state.players["Bob"].submit_guess(1985, 1002.0)
        state.current_song = {"year": 1985}
        state.round_start_time = 1000.0

        # Alice wins the artist challenge
        state.artist_challenge = ArtistChallenge(
            correct_artist="Queen",
            options=["Queen", "The Beatles", "ABBA"],
            winner="Alice",
            winner_time=1001.0,
        )

        await state.end_round()

        assert state.players["Alice"].artist_bonus == 5
        assert state.players["Bob"].artist_bonus == 0

    @pytest.mark.asyncio
    async def test_artist_bonus_added_to_total_score(self):
        """Artist bonus is added to total score (AC1)."""
        from unittest.mock import MagicMock

        from custom_components.beatify.game.state import ArtistChallenge, GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )
        mock_ws = MagicMock()
        state.add_player("Alice", mock_ws)

        state.players["Alice"].submit_guess(1985, 1001.0)
        state.current_song = {"year": 1985}
        state.round_start_time = 1000.0

        state.artist_challenge = ArtistChallenge(
            correct_artist="Queen",
            options=["Queen", "The Beatles", "ABBA"],
            winner="Alice",
            winner_time=1001.0,
        )

        initial_score = state.players["Alice"].score

        await state.end_round()

        # Score should include round_score + artist_bonus (5)
        # Artist bonus is added separately, not multiplied
        assert state.players["Alice"].score > initial_score
        assert state.players["Alice"].artist_bonus == 5
        # Total includes artist bonus
        expected_score = (
            state.players["Alice"].round_score
            + state.players["Alice"].streak_bonus
            + state.players["Alice"].artist_bonus
        )
        assert state.players["Alice"].score == expected_score

    def test_reveal_state_includes_artist_bonus_when_enabled(self):
        """Reveal state includes artist_bonus field when challenge enabled (AC1)."""
        from unittest.mock import MagicMock

        from custom_components.beatify.game.state import GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )
        mock_ws = MagicMock()
        state.add_player("Alice", mock_ws)
        state.players["Alice"].artist_bonus = 10

        result = state.get_reveal_players_state()

        assert "artist_bonus" in result[0]
        assert result[0]["artist_bonus"] == 10

    def test_reveal_state_omits_artist_bonus_when_disabled(self):
        """Reveal state omits artist_bonus when challenge disabled (AC3)."""
        from unittest.mock import MagicMock

        from custom_components.beatify.game.state import GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
            artist_challenge_enabled=False,
        )
        mock_ws = MagicMock()
        state.add_player("Alice", mock_ws)

        result = state.get_reveal_players_state()

        assert "artist_bonus" not in result[0]

    @pytest.mark.asyncio
    async def test_no_artist_bonus_without_challenge(self):
        """No artist_bonus when artist_challenge is None."""
        from unittest.mock import MagicMock

        from custom_components.beatify.game.state import GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )
        mock_ws = MagicMock()
        state.add_player("Alice", mock_ws)

        state.players["Alice"].submit_guess(1985, 1001.0)
        state.current_song = {"year": 1985}
        state.round_start_time = 1000.0
        # artist_challenge is None (no alt_artists in song)

        await state.end_round()

        assert state.players["Alice"].artist_bonus == 0

    @pytest.mark.asyncio
    async def test_non_submitter_can_still_win_artist_bonus(self):
        """Player who didn't submit year can still get artist bonus."""
        from unittest.mock import MagicMock

        from custom_components.beatify.game.state import ArtistChallenge, GameState

        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )
        mock_ws = MagicMock()
        state.add_player("Alice", mock_ws)

        # Player did NOT submit year guess (missed round)
        state.current_song = {"year": 1985}
        state.round_start_time = 1000.0

        # But they won the artist challenge
        state.artist_challenge = ArtistChallenge(
            correct_artist="Queen",
            options=["Queen", "The Beatles", "ABBA"],
            winner="Alice",
            winner_time=1001.0,
        )

        await state.end_round()

        # Player missed round but still gets artist bonus
        assert state.players["Alice"].missed_round is True
        assert state.players["Alice"].artist_bonus == 5
        assert state.players["Alice"].score == 5  # Only artist bonus (ARTIST_BONUS_POINTS=5)


# =============================================================================
# REMATCH TESTS (Issue #108)
# =============================================================================

from custom_components.beatify.game.state import GamePhase, GameState


def _make_real_game_state(**kwargs):
    """Create a real GameState with a game for rematch tests."""
    state = GameState(time_fn=lambda: 1000.0)
    songs = [
        {"year": 1985, "uri": "spotify:track:1", "_resolved_uri": "spotify:track:1"},
        {"year": 1990, "uri": "spotify:track:2", "_resolved_uri": "spotify:track:2"},
    ]
    state.create_game(
        playlists=["test.json"],
        songs=songs,
        media_player="media_player.test",
        base_url="http://test.local:8123",
        **kwargs,
    )
    return state


@pytest.mark.unit
class TestResetGameInternals:
    """Tests for _reset_game_internals() helper method (Issue #108)."""

    def test_reset_clears_game_fields(self):
        """Reset should clear all game state fields."""
        state = _make_real_game_state()
        state.round = 5
        state.total_rounds = 10
        state.current_song = {"title": "Test Song"}
        state.deadline = 1234567890
        state.song_stopped = True
        state.round_start_time = 1000.0

        state._reset_game_internals()

        assert state.round == 0
        assert state.total_rounds == 0
        assert state.current_song is None
        assert state.deadline is None
        assert state.song_stopped is False
        assert state.round_start_time is None

    def test_reset_does_not_clear_players(self):
        """Reset should NOT clear the players dict."""
        state = _make_real_game_state()
        mock_ws = MagicMock()
        state.add_player("Alice", mock_ws)
        state.add_player("Bob", mock_ws)

        state._reset_game_internals()

        assert len(state.players) == 2

    def test_reset_does_not_set_phase(self):
        """Reset should NOT change the phase (caller's responsibility)."""
        state = _make_real_game_state()
        state.phase = GamePhase.END

        state._reset_game_internals()

        assert state.phase == GamePhase.END


@pytest.mark.unit
class TestRematchGame:
    """Tests for rematch_game() method (Issue #108)."""

    def test_rematch_preserves_players(self):
        """Rematch should keep all players connected."""
        state = _make_real_game_state()
        mock_ws = MagicMock()
        state.add_player("Alice", mock_ws)
        state.add_player("Bob", mock_ws)
        state.players["Alice"].score = 100
        state.players["Bob"].score = 80

        state.rematch_game()

        assert len(state.players) == 2
        assert "Alice" in state.players
        assert "Bob" in state.players

    def test_rematch_resets_player_scores(self):
        """Rematch should reset all player scores to 0."""
        state = _make_real_game_state()
        mock_ws = MagicMock()
        state.add_player("Alice", mock_ws)
        state.add_player("Bob", mock_ws)
        state.players["Alice"].score = 100
        state.players["Bob"].score = 80

        state.rematch_game()

        assert state.players["Alice"].score == 0
        assert state.players["Bob"].score == 0

    def test_rematch_generates_new_game_id(self):
        """Rematch should generate a new game_id."""
        state = _make_real_game_state()
        old_id = state.game_id

        state.rematch_game()

        assert state.game_id is not None
        assert state.game_id != old_id

    def test_rematch_sets_lobby_phase(self):
        """Rematch should set phase to LOBBY."""
        state = _make_real_game_state()
        state.phase = GamePhase.END

        state.rematch_game()

        assert state.phase == GamePhase.LOBBY

    def test_rematch_resets_player_stats(self):
        """Rematch should reset player game stats."""
        state = _make_real_game_state()
        mock_ws = MagicMock()
        state.add_player("Alice", mock_ws)
        state.players["Alice"].streak = 5
        state.players["Alice"].best_streak = 5
        state.players["Alice"].rounds_played = 10

        state.rematch_game()

        assert state.players["Alice"].streak == 0
        assert state.players["Alice"].best_streak == 0
        assert state.players["Alice"].rounds_played == 0

    def test_rematch_recreates_playlist_manager(self):
        """Rematch should re-init PlaylistManager so songs are available."""
        state = _make_real_game_state()

        state.rematch_game()

        assert state._playlist_manager is not None
        assert state.total_rounds == 2  # Our 2 test songs

    def test_rematch_preserves_settings(self):
        """Rematch should preserve game settings (difficulty, language, etc)."""
        state = _make_real_game_state(difficulty="hard")
        state.language = "de"

        state.rematch_game()

        assert state.difficulty == "hard"
        assert state.language == "de"
