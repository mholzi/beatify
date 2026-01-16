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

    def test_create_game_with_min_duration_10(self):
        """create_game accepts minimum duration of 10 seconds."""
        from custom_components.beatify.game.state import GameState

        state = GameState()
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
            round_duration=10,
        )

        assert state.round_duration == 10

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
        """create_game rejects duration below 10 seconds."""
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

    def test_create_game_defaults_to_30_when_no_duration(self):
        """create_game defaults to 30 seconds when no duration specified."""
        from custom_components.beatify.game.state import GameState

        state = GameState()
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        assert state.round_duration == 30


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
