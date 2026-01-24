"""Unit tests for early reveal functionality (Story 20.9)."""

from unittest.mock import MagicMock

import pytest

from custom_components.beatify.game.player import PlayerSession
from custom_components.beatify.game.state import GamePhase, GameState


@pytest.fixture
def mock_ws():
    """Mock WebSocket connection."""
    return MagicMock()


class TestHasArtistGuessField:
    """Test has_artist_guess field on PlayerSession (Task 1)."""

    def test_has_artist_guess_default_false(self, mock_ws):
        """Test has_artist_guess field defaults to False."""
        player = PlayerSession(name="Test", ws=mock_ws)
        assert player.has_artist_guess is False

    def test_has_artist_guess_can_be_set(self, mock_ws):
        """Test has_artist_guess field can be set to True."""
        player = PlayerSession(name="Test", ws=mock_ws)
        player.has_artist_guess = True
        assert player.has_artist_guess is True

    def test_has_artist_guess_reset_in_reset_round(self, mock_ws):
        """Test has_artist_guess is reset to False in reset_round()."""
        player = PlayerSession(name="Test", ws=mock_ws)
        player.has_artist_guess = True
        player.reset_round()
        assert player.has_artist_guess is False


class TestCheckAllGuessesComplete:
    """Test check_all_guesses_complete() method (Task 2)."""

    @pytest.fixture
    def game_state(self, mock_ws):
        """Create a game state with two players."""
        state = GameState()
        state.create_game(
            playlists=["test.json"],
            songs=[{"year": 2000, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://localhost:8123",
        )
        state.add_player("Alice", mock_ws)
        state.add_player("Bob", mock_ws)
        # Mark both as connected
        state.players["Alice"].connected = True
        state.players["Bob"].connected = True
        state.phase = GamePhase.PLAYING
        return state

    def test_all_year_guesses_no_artist_challenge(self, game_state):
        """Test returns True when all year guesses submitted, artist challenge OFF."""
        game_state.artist_challenge_enabled = False
        game_state.artist_challenge = None

        # Both submit year guesses
        game_state.players["Alice"].submitted = True
        game_state.players["Bob"].submitted = True

        assert game_state.check_all_guesses_complete() is True

    def test_partial_year_guesses_returns_false(self, game_state):
        """Test returns False when not all year guesses submitted."""
        game_state.artist_challenge_enabled = False

        # Only Alice submits
        game_state.players["Alice"].submitted = True
        game_state.players["Bob"].submitted = False

        assert game_state.check_all_guesses_complete() is False

    def test_all_guesses_with_artist_challenge(self, game_state):
        """Test returns True when all year AND artist guesses submitted."""
        from custom_components.beatify.game.state import ArtistChallenge

        game_state.artist_challenge_enabled = True
        game_state.artist_challenge = ArtistChallenge(
            correct_artist="Test Artist",
            options=["Test Artist", "Decoy 1", "Decoy 2", "Decoy 3"],
        )

        # Both submit year and artist
        game_state.players["Alice"].submitted = True
        game_state.players["Alice"].has_artist_guess = True
        game_state.players["Bob"].submitted = True
        game_state.players["Bob"].has_artist_guess = True

        assert game_state.check_all_guesses_complete() is True

    def test_year_submitted_artist_missing_returns_false(self, game_state):
        """Test returns False when year submitted but artist missing (challenge ON)."""
        from custom_components.beatify.game.state import ArtistChallenge

        game_state.artist_challenge_enabled = True
        game_state.artist_challenge = ArtistChallenge(
            correct_artist="Test Artist",
            options=["Test Artist", "Decoy 1", "Decoy 2", "Decoy 3"],
        )

        # Both submit year, only Alice submits artist
        game_state.players["Alice"].submitted = True
        game_state.players["Alice"].has_artist_guess = True
        game_state.players["Bob"].submitted = True
        game_state.players["Bob"].has_artist_guess = False

        assert game_state.check_all_guesses_complete() is False

    def test_disconnected_players_excluded(self, game_state):
        """Test disconnected players are excluded from check."""
        game_state.artist_challenge_enabled = False

        # Alice connected and submitted, Bob disconnected
        game_state.players["Alice"].submitted = True
        game_state.players["Alice"].connected = True
        game_state.players["Bob"].submitted = False
        game_state.players["Bob"].connected = False

        assert game_state.check_all_guesses_complete() is True

    def test_single_player_returns_true(self, mock_ws):
        """Test single player game returns True when submitted."""
        state = GameState()
        state.create_game(
            playlists=["test.json"],
            songs=[{"year": 2000, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://localhost:8123",
        )
        state.add_player("Solo", mock_ws)
        state.players["Solo"].connected = True
        state.players["Solo"].submitted = True
        state.phase = GamePhase.PLAYING
        state.artist_challenge_enabled = False

        assert state.check_all_guesses_complete() is True

    def test_zero_connected_returns_false(self, game_state):
        """Test returns False when zero connected players."""
        # Disconnect all players
        game_state.players["Alice"].connected = False
        game_state.players["Bob"].connected = False

        assert game_state.check_all_guesses_complete() is False


class TestEarlyRevealFlag:
    """Test _early_reveal flag lifecycle (Task 3)."""

    def test_early_reveal_flag_default_false(self):
        """Test _early_reveal flag defaults to False."""
        state = GameState()
        assert state._early_reveal is False

    def test_early_reveal_flag_in_reveal_state(self, mock_ws):
        """Test early_reveal flag included in REVEAL state when True."""
        state = GameState()
        state.create_game(
            playlists=["test.json"],
            songs=[{"year": 2000, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://localhost:8123",
        )
        state.add_player("Test", mock_ws)
        state.phase = GamePhase.REVEAL
        state._early_reveal = True
        state.current_song = {"title": "Test", "artist": "Artist", "year": 2000}

        game_state = state.get_state()
        assert game_state.get("early_reveal") is True

    def test_early_reveal_flag_not_in_state_when_false(self, mock_ws):
        """Test early_reveal flag NOT included when False."""
        state = GameState()
        state.create_game(
            playlists=["test.json"],
            songs=[{"year": 2000, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://localhost:8123",
        )
        state.add_player("Test", mock_ws)
        state.phase = GamePhase.REVEAL
        state._early_reveal = False
        state.current_song = {"title": "Test", "artist": "Artist", "year": 2000}

        game_state = state.get_state()
        assert "early_reveal" not in game_state

    def test_early_reveal_flag_reset_in_end_game(self):
        """Test _early_reveal flag is reset in end_game()."""
        state = GameState()
        state.create_game(
            playlists=["test.json"],
            songs=[{"year": 2000, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://localhost:8123",
        )
        state._early_reveal = True
        state.end_game()
        assert state._early_reveal is False


class TestTriggerEarlyReveal:
    """Test _trigger_early_reveal() method (Task 3)."""

    @pytest.fixture
    def game_state_playing(self, mock_ws):
        """Create a game state in PLAYING phase."""
        state = GameState()
        state.create_game(
            playlists=["test.json"],
            songs=[{"year": 2000, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://localhost:8123",
        )
        state.add_player("Alice", mock_ws)
        state.players["Alice"].connected = True
        state.phase = GamePhase.PLAYING
        state.round = 1
        state.current_song = {"title": "Test", "artist": "Artist", "year": 2000}
        return state

    @pytest.mark.asyncio
    async def test_trigger_early_reveal_sets_flag(self, game_state_playing):
        """Test _trigger_early_reveal() sets _early_reveal flag."""
        await game_state_playing._trigger_early_reveal()
        assert game_state_playing._early_reveal is True

    @pytest.mark.asyncio
    async def test_trigger_early_reveal_transitions_to_reveal(self, game_state_playing):
        """Test _trigger_early_reveal() transitions to REVEAL phase."""
        await game_state_playing._trigger_early_reveal()
        assert game_state_playing.phase == GamePhase.REVEAL

    @pytest.mark.asyncio
    async def test_trigger_early_reveal_cancels_timer(self, game_state_playing):
        """Test _trigger_early_reveal() cancels timer."""
        import asyncio

        # Create a mock timer task
        async def mock_timer():
            await asyncio.sleep(100)

        game_state_playing._timer_task = asyncio.create_task(mock_timer())

        await game_state_playing._trigger_early_reveal()

        # Timer should be cancelled (task done or cancelled)
        assert (
            game_state_playing._timer_task is None
            or game_state_playing._timer_task.done()
            or game_state_playing._timer_task.cancelled()
        )
