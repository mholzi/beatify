"""Unit tests for movie quiz challenge feature (Issue #28)."""

from unittest.mock import MagicMock

import pytest

from custom_components.beatify.const import MOVIE_BONUS_TIERS
from custom_components.beatify.game.player import PlayerSession
from custom_components.beatify.game.state import (
    GamePhase,
    GameState,
    MovieChallenge,
    build_movie_options,
)


@pytest.fixture
def mock_ws():
    """Mock WebSocket connection."""
    return MagicMock()


# =============================================================================
# MovieChallenge Dataclass Tests
# =============================================================================


class TestMovieChallengeDataclass:
    """Tests for MovieChallenge dataclass (Issue #28)."""

    def test_creation(self):
        """MovieChallenge can be created with required fields."""
        challenge = MovieChallenge(
            correct_movie="The Bodyguard",
            options=["The Bodyguard", "Titanic", "Dirty Dancing"],
        )

        assert challenge.correct_movie == "The Bodyguard"
        assert challenge.options == ["The Bodyguard", "Titanic", "Dirty Dancing"]
        assert challenge.correct_guesses == []
        assert challenge.wrong_guesses == []

    def test_to_dict_hides_answer_by_default(self):
        """to_dict(include_answer=False) omits correct_movie and results."""
        challenge = MovieChallenge(
            correct_movie="The Bodyguard",
            options=["The Bodyguard", "Titanic", "Dirty Dancing"],
        )

        result = challenge.to_dict(include_answer=False)

        assert "correct_movie" not in result
        assert "results" not in result
        assert result["options"] == ["The Bodyguard", "Titanic", "Dirty Dancing"]

    def test_to_dict_reveals_answer(self):
        """to_dict(include_answer=True) includes correct_movie and results."""
        challenge = MovieChallenge(
            correct_movie="The Bodyguard",
            options=["The Bodyguard", "Titanic", "Dirty Dancing"],
        )

        result = challenge.to_dict(include_answer=True)

        assert result["correct_movie"] == "The Bodyguard"
        assert result["options"] == ["The Bodyguard", "Titanic", "Dirty Dancing"]
        assert "results" in result
        assert "winners" in result["results"]
        assert "wrong_guesses" in result["results"]

    def test_build_results_with_winners(self):
        """_build_results returns winners with tiered bonus and wrong guesses."""
        challenge = MovieChallenge(
            correct_movie="The Bodyguard",
            options=["The Bodyguard", "Titanic", "Dirty Dancing"],
            correct_guesses=[
                {"name": "Alice", "time": 2.5},
                {"name": "Bob", "time": 4.1},
                {"name": "Charlie", "time": 6.0},
            ],
            wrong_guesses=[
                {"name": "Dave", "guess": "Titanic"},
            ],
        )

        results = challenge._build_results()

        assert len(results["winners"]) == 3
        assert results["winners"][0] == {"name": "Alice", "time": 2.5, "bonus": 5}
        assert results["winners"][1] == {"name": "Bob", "time": 4.1, "bonus": 3}
        assert results["winners"][2] == {"name": "Charlie", "time": 6.0, "bonus": 1}
        assert results["wrong_guesses"] == [{"name": "Dave", "guess": "Titanic"}]

    def test_build_results_empty(self):
        """_build_results returns empty lists when no guesses."""
        challenge = MovieChallenge(
            correct_movie="The Bodyguard",
            options=["The Bodyguard", "Titanic", "Dirty Dancing"],
        )

        results = challenge._build_results()

        assert results["winners"] == []
        assert results["wrong_guesses"] == []

    def test_get_player_bonus_first(self):
        """First correct guesser gets 5 bonus points."""
        challenge = MovieChallenge(
            correct_movie="The Bodyguard",
            options=["The Bodyguard", "Titanic", "Dirty Dancing"],
            correct_guesses=[
                {"name": "Alice", "time": 2.5},
                {"name": "Bob", "time": 4.1},
                {"name": "Charlie", "time": 6.0},
            ],
        )

        assert challenge.get_player_bonus("Alice") == 5

    def test_get_player_bonus_second(self):
        """Second correct guesser gets 3 bonus points."""
        challenge = MovieChallenge(
            correct_movie="The Bodyguard",
            options=["The Bodyguard", "Titanic", "Dirty Dancing"],
            correct_guesses=[
                {"name": "Alice", "time": 2.5},
                {"name": "Bob", "time": 4.1},
                {"name": "Charlie", "time": 6.0},
            ],
        )

        assert challenge.get_player_bonus("Bob") == 3

    def test_get_player_bonus_third(self):
        """Third correct guesser gets 1 bonus point."""
        challenge = MovieChallenge(
            correct_movie="The Bodyguard",
            options=["The Bodyguard", "Titanic", "Dirty Dancing"],
            correct_guesses=[
                {"name": "Alice", "time": 2.5},
                {"name": "Bob", "time": 4.1},
                {"name": "Charlie", "time": 6.0},
            ],
        )

        assert challenge.get_player_bonus("Charlie") == 1

    def test_get_player_bonus_not_found(self):
        """Player not in correct_guesses gets 0 bonus."""
        challenge = MovieChallenge(
            correct_movie="The Bodyguard",
            options=["The Bodyguard", "Titanic", "Dirty Dancing"],
            correct_guesses=[
                {"name": "Alice", "time": 2.5},
            ],
        )

        assert challenge.get_player_bonus("Unknown") == 0


# =============================================================================
# MovieChallenge State Integration Tests
# =============================================================================


class TestMovieChallengeStateIntegration:
    """Tests for movie challenge integration with GameState (Issue #28)."""

    def test_create_game_with_movie_quiz_enabled(self):
        """create_game enables movie_quiz by default."""
        state = GameState()
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        assert state.movie_quiz_enabled is True
        assert state.movie_challenge is None  # Not initialized until start_round

    def test_create_game_with_movie_quiz_disabled(self):
        """create_game can disable movie_quiz."""
        state = GameState()
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
            movie_quiz_enabled=False,
        )

        assert state.movie_quiz_enabled is False

    def test_end_game_resets_movie_state(self):
        """end_game resets movie challenge state to defaults."""
        state = GameState()
        state.create_game(
            playlists=["playlist1.json"],
            songs=[{"year": 1985, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
            movie_quiz_enabled=False,
        )
        state.movie_challenge = MovieChallenge(
            correct_movie="The Bodyguard",
            options=["The Bodyguard", "Titanic", "Dirty Dancing"],
        )

        state.end_game()

        assert state.movie_challenge is None
        assert state.movie_quiz_enabled is True  # Reset to default


# =============================================================================
# build_movie_options Tests
# =============================================================================


class TestBuildMovieOptions:
    """Tests for build_movie_options() function (Issue #28)."""

    def test_valid_movie_choices(self):
        """Valid song with movie and movie_choices returns shuffled list."""
        song = {
            "movie": "The Bodyguard",
            "movie_choices": ["The Bodyguard", "Titanic", "Dirty Dancing"],
        }

        result = build_movie_options(song)

        assert result is not None
        assert len(result) == 3
        assert set(result) == {"The Bodyguard", "Titanic", "Dirty Dancing"}

    def test_missing_movie_choices_returns_none(self):
        """Song without movie_choices returns None."""
        song = {"movie": "The Bodyguard"}

        result = build_movie_options(song)

        assert result is None

    def test_invalid_movie_choices_returns_none(self):
        """Song with invalid movie_choices (not a list) returns None."""
        song = {"movie": "The Bodyguard", "movie_choices": "not a list"}

        result = build_movie_options(song)

        assert result is None

    def test_missing_movie_returns_none(self):
        """Song without movie field returns None."""
        song = {"movie_choices": ["A", "B", "C"]}

        result = build_movie_options(song)

        assert result is None

    def test_empty_movie_returns_none(self):
        """Song with empty movie string returns None."""
        song = {"movie": "", "movie_choices": ["A", "B", "C"]}

        result = build_movie_options(song)

        assert result is None

    def test_too_few_valid_choices_returns_none(self):
        """Song with fewer than 2 valid choices returns None."""
        song = {"movie": "The Bodyguard", "movie_choices": ["The Bodyguard"]}

        result = build_movie_options(song)

        assert result is None

    def test_correct_movie_added_if_missing_from_choices(self):
        """If correct movie not in movie_choices, it gets added."""
        song = {
            "movie": "The Bodyguard",
            "movie_choices": ["Titanic", "Dirty Dancing", "Grease"],
        }

        result = build_movie_options(song)

        assert result is not None
        assert "The Bodyguard" in result


# =============================================================================
# submit_movie_guess Tests
# =============================================================================


class TestSubmitMovieGuess:
    """Tests for GameState.submit_movie_guess() method (Issue #28)."""

    @pytest.fixture
    def game_with_movie(self, mock_ws):
        """Create a game state with an active movie challenge."""
        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["test.json"],
            songs=[{"year": 2000, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://localhost:8123",
            movie_quiz_enabled=True,
        )
        state.add_player("Alice", mock_ws)
        state.add_player("Bob", mock_ws)
        state.add_player("Charlie", mock_ws)
        state.phase = GamePhase.PLAYING
        state.round = 1
        state.round_start_time = 1000.0
        state.movie_challenge = MovieChallenge(
            correct_movie="The Bodyguard",
            options=["The Bodyguard", "Titanic", "Dirty Dancing"],
        )
        return state

    def test_correct_guess_first(self, game_with_movie):
        """First correct guess returns rank=1 and bonus=5."""
        result = game_with_movie.submit_movie_guess("Alice", "The Bodyguard", 1002.5)

        assert result["correct"] is True
        assert result["already_guessed"] is False
        assert result["rank"] == 1
        assert result["bonus"] == 5

    def test_correct_guess_second(self, game_with_movie):
        """Second correct guess returns rank=2 and bonus=3."""
        game_with_movie.submit_movie_guess("Alice", "The Bodyguard", 1002.5)
        result = game_with_movie.submit_movie_guess("Bob", "The Bodyguard", 1004.0)

        assert result["correct"] is True
        assert result["rank"] == 2
        assert result["bonus"] == 3

    def test_correct_guess_third(self, game_with_movie):
        """Third correct guess returns rank=3 and bonus=1."""
        game_with_movie.submit_movie_guess("Alice", "The Bodyguard", 1002.5)
        game_with_movie.submit_movie_guess("Bob", "The Bodyguard", 1004.0)
        result = game_with_movie.submit_movie_guess("Charlie", "The Bodyguard", 1006.0)

        assert result["correct"] is True
        assert result["rank"] == 3
        assert result["bonus"] == 1

    def test_wrong_guess(self, game_with_movie):
        """Wrong guess returns correct=False and bonus=0."""
        result = game_with_movie.submit_movie_guess("Alice", "Titanic", 1002.5)

        assert result["correct"] is False
        assert result["already_guessed"] is False
        assert result["rank"] is None
        assert result["bonus"] == 0

    def test_duplicate_correct_guess(self, game_with_movie):
        """Duplicate correct guess returns already_guessed=True."""
        game_with_movie.submit_movie_guess("Alice", "The Bodyguard", 1002.5)
        result = game_with_movie.submit_movie_guess("Alice", "The Bodyguard", 1005.0)

        assert result["already_guessed"] is True
        assert result["correct"] is True
        assert result["bonus"] == 0

    def test_duplicate_wrong_guess(self, game_with_movie):
        """Duplicate wrong guess returns already_guessed=True."""
        game_with_movie.submit_movie_guess("Alice", "Titanic", 1002.5)
        result = game_with_movie.submit_movie_guess("Alice", "Dirty Dancing", 1005.0)

        assert result["already_guessed"] is True
        assert result["correct"] is False
        assert result["bonus"] == 0

    def test_case_insensitive_comparison(self, game_with_movie):
        """Movie guess comparison is case-insensitive."""
        result = game_with_movie.submit_movie_guess("Alice", "the bodyguard", 1002.5)

        assert result["correct"] is True
        assert result["rank"] == 1

    def test_no_challenge_raises_error(self, mock_ws):
        """submit_movie_guess raises ValueError when no challenge active."""
        state = GameState()
        state.create_game(
            playlists=["test.json"],
            songs=[{"year": 2000, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://localhost:8123",
        )
        state.movie_challenge = None

        with pytest.raises(ValueError, match="No movie challenge active"):
            state.submit_movie_guess("Alice", "Movie", 1000.0)


# =============================================================================
# Movie Quiz Early Reveal Tests
# =============================================================================


class TestMovieQuizEarlyReveal:
    """Tests for check_all_guesses_complete with movie quiz (Issue #28)."""

    @pytest.fixture
    def game_state(self, mock_ws):
        """Create a game state with two connected players."""
        state = GameState()
        state.create_game(
            playlists=["test.json"],
            songs=[{"year": 2000, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://localhost:8123",
        )
        state.add_player("Alice", mock_ws)
        state.add_player("Bob", mock_ws)
        state.players["Alice"].connected = True
        state.players["Bob"].connected = True
        state.phase = GamePhase.PLAYING
        return state

    def test_all_complete_with_movie_guesses(self, game_state):
        """Returns True when all players have submitted year and movie guesses."""
        game_state.movie_quiz_enabled = True
        game_state.artist_challenge_enabled = False
        game_state.artist_challenge = None
        game_state.movie_challenge = MovieChallenge(
            correct_movie="The Bodyguard",
            options=["The Bodyguard", "Titanic", "Dirty Dancing"],
        )

        # Both submit year and movie
        game_state.players["Alice"].submitted = True
        game_state.players["Alice"].has_movie_guess = True
        game_state.players["Bob"].submitted = True
        game_state.players["Bob"].has_movie_guess = True

        assert game_state.check_all_guesses_complete() is True

    def test_incomplete_without_movie_guess(self, game_state):
        """Returns False when year submitted but movie guess missing."""
        game_state.movie_quiz_enabled = True
        game_state.artist_challenge_enabled = False
        game_state.artist_challenge = None
        game_state.movie_challenge = MovieChallenge(
            correct_movie="The Bodyguard",
            options=["The Bodyguard", "Titanic", "Dirty Dancing"],
        )

        # Both submit year, only Alice submits movie
        game_state.players["Alice"].submitted = True
        game_state.players["Alice"].has_movie_guess = True
        game_state.players["Bob"].submitted = True
        game_state.players["Bob"].has_movie_guess = False

        assert game_state.check_all_guesses_complete() is False

    def test_disconnected_player_skipped(self, game_state):
        """Disconnected players are excluded from movie guess check."""
        game_state.movie_quiz_enabled = True
        game_state.artist_challenge_enabled = False
        game_state.artist_challenge = None
        game_state.movie_challenge = MovieChallenge(
            correct_movie="The Bodyguard",
            options=["The Bodyguard", "Titanic", "Dirty Dancing"],
        )

        # Alice connected and complete, Bob disconnected
        game_state.players["Alice"].submitted = True
        game_state.players["Alice"].has_movie_guess = True
        game_state.players["Bob"].connected = False
        game_state.players["Bob"].submitted = False

        assert game_state.check_all_guesses_complete() is True


# =============================================================================
# Movie Bonus Scoring Tests
# =============================================================================


class TestMovieBonusScoring:
    """Tests for movie bonus tiered scoring in end_round (Issue #28)."""

    @pytest.fixture
    def game_with_scored_movie(self, mock_ws):
        """Create a game state with movie challenge and submitted guesses."""
        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["test.json"],
            songs=[{"year": 2000, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://localhost:8123",
            movie_quiz_enabled=True,
        )
        state.add_player("Alice", mock_ws)
        state.add_player("Bob", mock_ws)
        state.add_player("Charlie", mock_ws)
        state.phase = GamePhase.PLAYING
        state.round = 1
        state.round_start_time = 1000.0
        state.current_song = {"year": 2000, "artist": "Test", "title": "Song"}
        state.artist_challenge_enabled = False
        state.artist_challenge = None

        # Set up movie challenge with correct guesses
        state.movie_challenge = MovieChallenge(
            correct_movie="The Bodyguard",
            options=["The Bodyguard", "Titanic", "Dirty Dancing"],
            correct_guesses=[
                {"name": "Alice", "time": 2.5},
                {"name": "Bob", "time": 4.1},
                {"name": "Charlie", "time": 6.0},
            ],
        )

        # All players submit year guesses
        for name in ["Alice", "Bob", "Charlie"]:
            state.players[name].submitted = True
            state.players[name].current_guess = 2000
            state.players[name].submission_time = 1005.0

        return state

    @pytest.mark.asyncio
    async def test_tiered_bonus_in_end_round(self, game_with_scored_movie):
        """end_round awards tiered movie bonus: 5/3/1 to top 3."""
        await game_with_scored_movie.end_round()

        assert game_with_scored_movie.players["Alice"].movie_bonus == 5
        assert game_with_scored_movie.players["Bob"].movie_bonus == 3
        assert game_with_scored_movie.players["Charlie"].movie_bonus == 1

    @pytest.mark.asyncio
    async def test_no_bonus_when_disabled(self, mock_ws):
        """No movie bonus awarded when movie_quiz_enabled is False."""
        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["test.json"],
            songs=[{"year": 2000, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://localhost:8123",
            movie_quiz_enabled=False,
        )
        state.add_player("Alice", mock_ws)
        state.phase = GamePhase.PLAYING
        state.round = 1
        state.round_start_time = 1000.0
        state.current_song = {"year": 2000, "artist": "Test", "title": "Song"}
        state.artist_challenge_enabled = False
        state.artist_challenge = None

        state.players["Alice"].submitted = True
        state.players["Alice"].current_guess = 2000
        state.players["Alice"].submission_time = 1005.0

        await state.end_round()

        assert state.players["Alice"].movie_bonus == 0


# =============================================================================
# PlayerSession Movie Fields Tests
# =============================================================================


class TestPlayerSessionMovieFields:
    """Tests for movie-related fields on PlayerSession (Issue #28)."""

    def test_defaults(self, mock_ws):
        """Movie fields default to zero/False."""
        player = PlayerSession(name="Test", ws=mock_ws)

        assert player.movie_bonus == 0
        assert player.has_movie_guess is False
        assert player.movie_bonus_total == 0

    def test_reset_round_clears_movie_fields(self, mock_ws):
        """reset_round() resets movie_bonus and has_movie_guess but not total."""
        player = PlayerSession(name="Test", ws=mock_ws)
        player.movie_bonus = 5
        player.has_movie_guess = True
        player.movie_bonus_total = 8

        player.reset_round()

        assert player.movie_bonus == 0
        assert player.has_movie_guess is False
        assert player.movie_bonus_total == 8  # Cumulative, NOT reset

    def test_movie_bonus_total_accumulates(self, mock_ws):
        """movie_bonus_total accumulates across rounds."""
        player = PlayerSession(name="Test", ws=mock_ws)

        # Simulate round 1: earned 5 bonus
        player.movie_bonus = 5
        player.movie_bonus_total += player.movie_bonus

        # Reset for round 2
        player.reset_round()

        # Simulate round 2: earned 3 bonus
        player.movie_bonus = 3
        player.movie_bonus_total += player.movie_bonus

        assert player.movie_bonus_total == 8


# =============================================================================
# Film Buff Superlative Tests
# =============================================================================


class TestFilmBuffSuperlative:
    """Tests for Film Buff superlative award (Issue #28)."""

    def test_film_buff_awarded(self, mock_ws):
        """Film Buff superlative is awarded to player with most movie bonus."""
        state = GameState()
        state.create_game(
            playlists=["test.json"],
            songs=[{"year": 2000, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://localhost:8123",
            movie_quiz_enabled=True,
        )
        state.add_player("Alice", mock_ws)
        state.add_player("Bob", mock_ws)

        # Alice has more movie bonus total
        state.players["Alice"].movie_bonus_total = 10
        state.players["Bob"].movie_bonus_total = 3

        superlatives = state.calculate_superlatives()

        film_buff = [s for s in superlatives if s["id"] == "film_buff"]
        assert len(film_buff) == 1
        assert film_buff[0]["player_name"] == "Alice"
        assert film_buff[0]["value"] == 10
        assert film_buff[0]["emoji"] == "🎬"

    def test_film_buff_not_awarded_when_zero(self, mock_ws):
        """Film Buff is not awarded when no player has movie bonus."""
        state = GameState()
        state.create_game(
            playlists=["test.json"],
            songs=[{"year": 2000, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://localhost:8123",
            movie_quiz_enabled=True,
        )
        state.add_player("Alice", mock_ws)
        state.add_player("Bob", mock_ws)

        # No movie bonus for anyone
        state.players["Alice"].movie_bonus_total = 0
        state.players["Bob"].movie_bonus_total = 0

        superlatives = state.calculate_superlatives()

        film_buff = [s for s in superlatives if s["id"] == "film_buff"]
        assert len(film_buff) == 0

    def test_film_buff_not_awarded_when_movie_quiz_disabled(self, mock_ws):
        """Film Buff is not awarded when movie_quiz_enabled is False."""
        state = GameState()
        state.create_game(
            playlists=["test.json"],
            songs=[{"year": 2000, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://localhost:8123",
            movie_quiz_enabled=False,
        )
        state.add_player("Alice", mock_ws)
        state.players["Alice"].movie_bonus_total = 10

        superlatives = state.calculate_superlatives()

        film_buff = [s for s in superlatives if s["id"] == "film_buff"]
        assert len(film_buff) == 0


# =============================================================================
# get_state Movie Challenge Visibility Tests
# =============================================================================


class TestMovieChallengeInGetState:
    """Tests for movie_challenge visibility in get_state() (Issue #28)."""

    @pytest.fixture
    def state_with_movie_challenge(self, mock_ws):
        """Create a game state with movie challenge for state broadcast tests."""
        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["test.json"],
            songs=[{"year": 2000, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://localhost:8123",
            movie_quiz_enabled=True,
        )
        state.add_player("Alice", mock_ws)
        state.round = 1
        state.total_rounds = 5
        state.current_song = {
            "year": 2000,
            "artist": "Test Artist",
            "title": "Test Song",
            "album_art": "/test.jpg",
        }
        state.movie_challenge = MovieChallenge(
            correct_movie="The Bodyguard",
            options=["The Bodyguard", "Titanic", "Dirty Dancing"],
            correct_guesses=[{"name": "Alice", "time": 2.5}],
        )
        return state

    def test_playing_hides_movie_answer(self, state_with_movie_challenge):
        """get_state() in PLAYING hides correct_movie."""
        state_with_movie_challenge.phase = GamePhase.PLAYING
        state_with_movie_challenge.deadline = 1030000

        result = state_with_movie_challenge.get_state()

        assert "movie_challenge" in result
        assert "correct_movie" not in result["movie_challenge"]
        assert "results" not in result["movie_challenge"]
        assert result["movie_challenge"]["options"] == [
            "The Bodyguard",
            "Titanic",
            "Dirty Dancing",
        ]

    def test_reveal_shows_movie_answer(self, state_with_movie_challenge):
        """get_state() in REVEAL shows correct_movie and results."""
        state_with_movie_challenge.phase = GamePhase.REVEAL

        result = state_with_movie_challenge.get_state()

        assert "movie_challenge" in result
        assert result["movie_challenge"]["correct_movie"] == "The Bodyguard"
        assert "results" in result["movie_challenge"]

    def test_no_challenge_excluded_from_state(self, mock_ws):
        """get_state() excludes movie_challenge when None."""
        state = GameState(time_fn=lambda: 1000.0)
        state.create_game(
            playlists=["test.json"],
            songs=[{"year": 2000, "uri": "spotify:track:test"}],
            media_player="media_player.test",
            base_url="http://localhost:8123",
            movie_quiz_enabled=True,
        )
        state.add_player("Alice", mock_ws)
        state.round = 1
        state.total_rounds = 5
        state.deadline = 1030000
        state.current_song = {
            "year": 2000,
            "artist": "Test",
            "title": "Song",
            "album_art": "/test.jpg",
        }
        state.phase = GamePhase.PLAYING
        state.movie_challenge = None

        result = state.get_state()

        assert "movie_challenge" not in result
