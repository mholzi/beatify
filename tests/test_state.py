"""Tests for custom_components.beatify.game.state — Phase 2."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from custom_components.beatify.const import (
    DEFAULT_ROUND_DURATION,
    DIFFICULTY_EASY,
    DIFFICULTY_NORMAL,
    ERR_GAME_ENDED,
    ERR_GAME_FULL,
    ERR_NAME_INVALID,
    ERR_NAME_TAKEN,
    MAX_PLAYERS,
    ROUND_DURATION_MAX,
    ROUND_DURATION_MIN,
)
from custom_components.beatify.game.state import (
    ArtistChallenge,
    GamePhase,
    GameState,
    MovieChallenge,
    RoundAnalytics,
    build_artist_options,
    build_movie_options,
)
from tests.conftest import make_player


# =========================================================================
# GameState — create_game
# =========================================================================

class TestCreateGame:
    def test_basic_creation(self, game_state: GameState, sample_songs):
        result = game_state.create_game(
            playlists=["test.json"],
            songs=sample_songs,
            media_player="media_player.test",
            base_url="http://localhost:8123",
        )
        assert result["game_id"] is not None
        assert result["phase"] == "LOBBY"
        assert result["song_count"] == 3
        assert game_state.phase == GamePhase.LOBBY

    def test_custom_round_duration(self, game_state: GameState, sample_songs):
        game_state.create_game(
            playlists=["test.json"],
            songs=sample_songs,
            media_player="media_player.test",
            base_url="http://localhost:8123",
            round_duration=20,
        )
        assert game_state.round_duration == 20

    def test_invalid_round_duration_raises(self, game_state: GameState, sample_songs):
        with pytest.raises(ValueError):
            game_state.create_game(
                playlists=["test.json"],
                songs=sample_songs,
                media_player="media_player.test",
                base_url="http://localhost:8123",
                round_duration=5,  # below min
            )

    def test_difficulty_setting(self, game_state: GameState, sample_songs):
        game_state.create_game(
            playlists=["test.json"],
            songs=sample_songs,
            media_player="media_player.test",
            base_url="http://localhost:8123",
            difficulty=DIFFICULTY_EASY,
        )
        assert game_state.difficulty == DIFFICULTY_EASY

    def test_join_url_format(self, game_state: GameState, sample_songs):
        result = game_state.create_game(
            playlists=["test.json"],
            songs=sample_songs,
            media_player="media_player.test",
            base_url="http://localhost:8123",
        )
        assert game_state.join_url.startswith("http://localhost:8123/beatify/play?game=")

    def test_feature_flags(self, game_state: GameState, sample_songs):
        game_state.create_game(
            playlists=["test.json"],
            songs=sample_songs,
            media_player="media_player.test",
            base_url="http://localhost:8123",
            artist_challenge_enabled=False,
            movie_quiz_enabled=False,
            intro_mode_enabled=True,
        )
        assert game_state.artist_challenge_enabled is False
        assert game_state.movie_quiz_enabled is False
        assert game_state.intro_mode_enabled is True


# =========================================================================
# GameState — add_player / remove_player
# =========================================================================

class TestPlayerManagement:
    def _setup_game(self, gs: GameState, songs):
        gs.create_game(["t.json"], songs, "mp.test", "http://test")

    def test_add_player(self, game_state, sample_songs, mock_ws):
        self._setup_game(game_state, sample_songs)
        ok, err = game_state.add_player("Alice", mock_ws)
        assert ok is True
        assert err is None
        assert "Alice" in game_state.players

    def test_duplicate_name_rejected(self, game_state, sample_songs, mock_ws):
        self._setup_game(game_state, sample_songs)
        game_state.add_player("Alice", mock_ws)
        ok, err = game_state.add_player("Alice", MagicMock())
        assert ok is False
        assert err == ERR_NAME_TAKEN

    def test_empty_name_rejected(self, game_state, sample_songs, mock_ws):
        self._setup_game(game_state, sample_songs)
        ok, err = game_state.add_player("", mock_ws)
        assert ok is False
        assert err == ERR_NAME_INVALID

    def test_long_name_rejected(self, game_state, sample_songs, mock_ws):
        self._setup_game(game_state, sample_songs)
        ok, err = game_state.add_player("A" * 21, mock_ws)
        assert ok is False
        assert err == ERR_NAME_INVALID

    def test_add_during_end_rejected(self, game_state, sample_songs, mock_ws):
        self._setup_game(game_state, sample_songs)
        game_state.phase = GamePhase.END
        ok, err = game_state.add_player("Alice", mock_ws)
        assert ok is False
        assert err == ERR_GAME_ENDED

    def test_max_players(self, game_state, sample_songs):
        self._setup_game(game_state, sample_songs)
        for i in range(MAX_PLAYERS):
            game_state.add_player(f"P{i}", MagicMock())
        ok, err = game_state.add_player("Extra", MagicMock())
        assert ok is False
        assert err == ERR_GAME_FULL

    def test_reconnection(self, game_state, sample_songs, mock_ws):
        self._setup_game(game_state, sample_songs)
        game_state.add_player("Alice", mock_ws)
        game_state.players["Alice"].connected = False
        new_ws = MagicMock()
        ok, err = game_state.add_player("Alice", new_ws)
        assert ok is True
        assert game_state.players["Alice"].connected is True
        assert game_state.players["Alice"].ws == new_ws

    def test_remove_player(self, game_state, sample_songs, mock_ws):
        self._setup_game(game_state, sample_songs)
        game_state.add_player("Alice", mock_ws)
        game_state.remove_player("Alice")
        assert "Alice" not in game_state.players

    def test_late_joiner_gets_average_score(self, game_state, sample_songs):
        self._setup_game(game_state, sample_songs)
        game_state.add_player("Alice", MagicMock())
        game_state.players["Alice"].score = 100
        game_state.add_player("Bob", MagicMock())
        game_state.players["Bob"].score = 50
        # Switch to PLAYING to make next joiner "late"
        game_state.phase = GamePhase.PLAYING
        game_state.add_player("Charlie", MagicMock())
        assert game_state.players["Charlie"].score == 75  # avg of 100+50
        assert game_state.players["Charlie"].joined_late is True


# =========================================================================
# GameState — start_game
# =========================================================================

class TestStartGame:
    def test_start_from_lobby(self, game_state, sample_songs):
        game_state.create_game(["t.json"], sample_songs, "mp.test", "http://test")
        game_state.add_player("Alice", MagicMock())
        ok, err = game_state.start_game()
        assert ok is True
        assert game_state.phase == GamePhase.PLAYING

    def test_start_without_players(self, game_state, sample_songs):
        game_state.create_game(["t.json"], sample_songs, "mp.test", "http://test")
        ok, err = game_state.start_game()
        assert ok is False

    def test_start_already_started(self, game_state, sample_songs):
        game_state.create_game(["t.json"], sample_songs, "mp.test", "http://test")
        game_state.add_player("Alice", MagicMock())
        game_state.start_game()
        ok, err = game_state.start_game()
        assert ok is False
        assert err == "GAME_ALREADY_STARTED"


# =========================================================================
# GameState — get_state
# =========================================================================

class TestGetState:
    def test_no_game(self, game_state):
        assert game_state.get_state() is None

    def test_lobby_state(self, game_state, sample_songs):
        game_state.create_game(["t.json"], sample_songs, "mp.test", "http://test")
        state = game_state.get_state()
        assert state["phase"] == "LOBBY"
        assert "join_url" in state

    def test_end_state_has_winner(self, game_state, sample_songs):
        game_state.create_game(["t.json"], sample_songs, "mp.test", "http://test")
        game_state.add_player("Alice", MagicMock())
        game_state.players["Alice"].score = 50
        game_state.phase = GamePhase.END
        game_state.round = 3
        state = game_state.get_state()
        assert state["phase"] == "END"
        assert state["winner"]["name"] == "Alice"
        assert state["winner"]["score"] == 50


# =========================================================================
# GameState — end_game / rematch
# =========================================================================

class TestEndGameAndRematch:
    def test_end_game_resets(self, game_state, sample_songs):
        game_state.create_game(["t.json"], sample_songs, "mp.test", "http://test")
        game_state.add_player("Alice", MagicMock())
        game_state.end_game()
        assert game_state.game_id is None
        assert len(game_state.players) == 0
        assert game_state.phase == GamePhase.LOBBY

    def test_rematch_preserves_players(self, game_state, sample_songs):
        game_state.create_game(["t.json"], sample_songs, "mp.test", "http://test")
        game_state.add_player("Alice", MagicMock())
        game_state.players["Alice"].score = 100
        old_id = game_state.game_id
        game_state.rematch_game()
        assert game_state.game_id != old_id
        assert "Alice" in game_state.players
        assert game_state.players["Alice"].score == 0  # reset for new game
        assert game_state.phase == GamePhase.LOBBY


# =========================================================================
# GameState — finalize_game
# =========================================================================

class TestFinalizeGame:
    def test_finalize_returns_summary(self, game_state, sample_songs):
        game_state.create_game(["t.json"], sample_songs, "mp.test", "http://test")
        game_state.add_player("Alice", MagicMock())
        game_state.players["Alice"].score = 50
        game_state.round = 3
        summary = game_state.finalize_game()
        assert summary["winner"] == "Alice"
        assert summary["winner_score"] == 50
        assert summary["rounds"] == 3
        assert summary["player_count"] == 1


# =========================================================================
# GameState — set_admin
# =========================================================================

class TestSetAdmin:
    def test_set_admin(self, game_state, sample_songs):
        game_state.create_game(["t.json"], sample_songs, "mp.test", "http://test")
        game_state.add_player("Alice", MagicMock())
        assert game_state.set_admin("Alice") is True
        assert game_state.players["Alice"].is_admin is True

    def test_set_admin_nonexistent(self, game_state, sample_songs):
        game_state.create_game(["t.json"], sample_songs, "mp.test", "http://test")
        assert game_state.set_admin("Ghost") is False


# =========================================================================
# GameState — all_submitted
# =========================================================================

class TestAllSubmitted:
    def test_no_players(self, game_state, sample_songs):
        game_state.create_game(["t.json"], sample_songs, "mp.test", "http://test")
        assert game_state.all_submitted() is False

    def test_not_all_submitted(self, game_state, sample_songs):
        game_state.create_game(["t.json"], sample_songs, "mp.test", "http://test")
        game_state.add_player("Alice", MagicMock())
        game_state.add_player("Bob", MagicMock())
        game_state.players["Alice"].submitted = True
        assert game_state.all_submitted() is False

    def test_all_submitted(self, game_state, sample_songs):
        game_state.create_game(["t.json"], sample_songs, "mp.test", "http://test")
        game_state.add_player("Alice", MagicMock())
        game_state.add_player("Bob", MagicMock())
        game_state.players["Alice"].submitted = True
        game_state.players["Bob"].submitted = True
        assert game_state.all_submitted() is True

    def test_disconnected_ignored(self, game_state, sample_songs):
        game_state.create_game(["t.json"], sample_songs, "mp.test", "http://test")
        game_state.add_player("Alice", MagicMock())
        game_state.add_player("Bob", MagicMock())
        game_state.players["Alice"].submitted = True
        game_state.players["Bob"].connected = False
        assert game_state.all_submitted() is True


# =========================================================================
# GameState — leaderboard
# =========================================================================

class TestLeaderboard:
    def test_sorted_by_score(self, game_state, sample_songs):
        game_state.create_game(["t.json"], sample_songs, "mp.test", "http://test")
        game_state.add_player("Alice", MagicMock())
        game_state.add_player("Bob", MagicMock())
        game_state.players["Alice"].score = 50
        game_state.players["Bob"].score = 100
        lb = game_state.get_leaderboard()
        assert lb[0]["name"] == "Bob"
        assert lb[0]["rank"] == 1
        assert lb[1]["name"] == "Alice"
        assert lb[1]["rank"] == 2

    def test_tie_handling(self, game_state, sample_songs):
        game_state.create_game(["t.json"], sample_songs, "mp.test", "http://test")
        game_state.add_player("Alice", MagicMock())
        game_state.add_player("Bob", MagicMock())
        game_state.players["Alice"].score = 50
        game_state.players["Bob"].score = 50
        lb = game_state.get_leaderboard()
        assert lb[0]["rank"] == lb[1]["rank"] == 1


# =========================================================================
# GameState — steal mechanics
# =========================================================================

class TestStealMechanics:
    def _setup(self, gs, songs):
        gs.create_game(["t.json"], songs, "mp.test", "http://test")
        gs.add_player("Alice", MagicMock())
        gs.add_player("Bob", MagicMock())
        gs.phase = GamePhase.PLAYING

    def test_get_steal_targets(self, game_state, sample_songs):
        self._setup(game_state, sample_songs)
        game_state.players["Bob"].submitted = True
        targets = game_state.get_steal_targets("Alice")
        assert "Bob" in targets
        assert "Alice" not in targets

    def test_use_steal_success(self, game_state, sample_songs):
        self._setup(game_state, sample_songs)
        game_state.players["Alice"].steal_available = True
        game_state.players["Bob"].submitted = True
        game_state.players["Bob"].current_guess = 1985
        result = game_state.use_steal("Alice", "Bob")
        assert result["success"] is True
        assert game_state.players["Alice"].current_guess == 1985
        assert game_state.players["Alice"].steal_available is False

    def test_use_steal_no_steal_available(self, game_state, sample_songs):
        self._setup(game_state, sample_songs)
        result = game_state.use_steal("Alice", "Bob")
        assert result["success"] is False

    def test_use_steal_self(self, game_state, sample_songs):
        self._setup(game_state, sample_songs)
        game_state.players["Alice"].steal_available = True
        result = game_state.use_steal("Alice", "Alice")
        assert result["success"] is False


# =========================================================================
# GameState — volume
# =========================================================================

class TestVolume:
    def test_volume_up(self, game_state):
        game_state.volume_level = 0.5
        new = game_state.adjust_volume("up")
        assert new == pytest.approx(0.6)

    def test_volume_down(self, game_state):
        game_state.volume_level = 0.5
        new = game_state.adjust_volume("down")
        assert new == pytest.approx(0.4)

    def test_volume_clamped_high(self, game_state):
        game_state.volume_level = 1.0
        new = game_state.adjust_volume("up")
        assert new == 1.0

    def test_volume_clamped_low(self, game_state):
        game_state.volume_level = 0.0
        new = game_state.adjust_volume("down")
        assert new == 0.0


# =========================================================================
# GameState — reaction rate limiting
# =========================================================================

class TestReactionRateLimit:
    def test_first_reaction_allowed(self, game_state):
        assert game_state.record_reaction("Alice", "🎉") is True

    def test_second_reaction_blocked(self, game_state):
        game_state.record_reaction("Alice", "🎉")
        assert game_state.record_reaction("Alice", "❤️") is False

    def test_different_player_allowed(self, game_state):
        game_state.record_reaction("Alice", "🎉")
        assert game_state.record_reaction("Bob", "🎉") is True


# =========================================================================
# GameState — artist challenge
# =========================================================================

class TestArtistChallenge:
    def test_submit_correct_first(self, game_state, sample_songs):
        game_state.create_game(["t.json"], sample_songs, "mp.test", "http://test")
        game_state.artist_challenge = ArtistChallenge(
            correct_artist="Queen",
            options=["Queen", "Led Zeppelin", "The Beatles"],
        )
        result = game_state.submit_artist_guess("Alice", "Queen", 1000.0)
        assert result["correct"] is True
        assert result["first"] is True
        assert result["winner"] == "Alice"

    def test_submit_wrong(self, game_state, sample_songs):
        game_state.create_game(["t.json"], sample_songs, "mp.test", "http://test")
        game_state.artist_challenge = ArtistChallenge(
            correct_artist="Queen",
            options=["Queen", "Led Zeppelin", "The Beatles"],
        )
        result = game_state.submit_artist_guess("Alice", "Led Zeppelin", 1000.0)
        assert result["correct"] is False

    def test_second_correct_not_first(self, game_state, sample_songs):
        game_state.create_game(["t.json"], sample_songs, "mp.test", "http://test")
        game_state.artist_challenge = ArtistChallenge(
            correct_artist="Queen",
            options=["Queen", "Led Zeppelin"],
        )
        game_state.submit_artist_guess("Alice", "Queen", 1000.0)
        result = game_state.submit_artist_guess("Bob", "Queen", 1001.0)
        assert result["correct"] is True
        assert result["first"] is False
        assert result["winner"] == "Alice"  # Alice remains winner

    def test_no_challenge_raises(self, game_state):
        with pytest.raises(ValueError):
            game_state.submit_artist_guess("Alice", "Queen", 1000.0)


# =========================================================================
# GameState — movie challenge
# =========================================================================

class TestMovieChallenge:
    def test_submit_correct(self, game_state, sample_songs):
        game_state.create_game(["t.json"], sample_songs, "mp.test", "http://test")
        game_state.round_start_time = 1000.0
        game_state.movie_challenge = MovieChallenge(
            correct_movie="Wayne's World",
            options=["Wayne's World", "Pulp Fiction", "Grease"],
        )
        result = game_state.submit_movie_guess("Alice", "Wayne's World", 1002.0)
        assert result["correct"] is True
        assert result["rank"] == 1
        assert result["bonus"] == 5

    def test_submit_wrong(self, game_state, sample_songs):
        game_state.create_game(["t.json"], sample_songs, "mp.test", "http://test")
        game_state.round_start_time = 1000.0
        game_state.movie_challenge = MovieChallenge(
            correct_movie="Wayne's World",
            options=["Wayne's World", "Pulp Fiction", "Grease"],
        )
        result = game_state.submit_movie_guess("Alice", "Pulp Fiction", 1002.0)
        assert result["correct"] is False

    def test_already_guessed(self, game_state, sample_songs):
        game_state.create_game(["t.json"], sample_songs, "mp.test", "http://test")
        game_state.round_start_time = 1000.0
        game_state.movie_challenge = MovieChallenge(
            correct_movie="Wayne's World",
            options=["Wayne's World", "Pulp Fiction", "Grease"],
        )
        game_state.submit_movie_guess("Alice", "Wayne's World", 1002.0)
        result = game_state.submit_movie_guess("Alice", "Wayne's World", 1003.0)
        assert result["already_guessed"] is True

    def test_no_challenge_raises(self, game_state):
        with pytest.raises(ValueError):
            game_state.submit_movie_guess("Alice", "Test", 1000.0)


# =========================================================================
# RoundAnalytics dataclass
# =========================================================================

class TestRoundAnalytics:
    def test_to_dict(self):
        ra = RoundAnalytics(
            average_guess=1985.5,
            median_guess=1985,
            correct_decade="1980s",
        )
        d = ra.to_dict()
        assert d["average_guess"] == 1985.5
        assert d["correct_decade"] == "1980s"

    def test_to_dict_no_average(self):
        ra = RoundAnalytics()
        d = ra.to_dict()
        assert d["average_guess"] is None


# =========================================================================
# ArtistChallenge / MovieChallenge dataclasses
# =========================================================================

class TestArtistChallengeDataclass:
    def test_to_dict_hides_answer(self):
        ac = ArtistChallenge(correct_artist="Queen", options=["Queen", "Beatles"])
        d = ac.to_dict(include_answer=False)
        assert "correct_artist" not in d
        assert "options" in d

    def test_to_dict_shows_answer(self):
        ac = ArtistChallenge(correct_artist="Queen", options=["Queen", "Beatles"])
        d = ac.to_dict(include_answer=True)
        assert d["correct_artist"] == "Queen"


class TestMovieChallengeDataclass:
    def test_to_dict_hides_answer(self):
        mc = MovieChallenge(correct_movie="Grease", options=["Grease", "Jaws"])
        d = mc.to_dict(include_answer=False)
        assert "correct_movie" not in d

    def test_to_dict_shows_answer(self):
        mc = MovieChallenge(
            correct_movie="Grease",
            options=["Grease", "Jaws"],
            correct_guesses=[{"name": "Alice", "time": 2.5}],
        )
        d = mc.to_dict(include_answer=True)
        assert d["correct_movie"] == "Grease"
        assert "results" in d

    def test_get_player_bonus(self):
        mc = MovieChallenge(
            correct_movie="Grease",
            options=["Grease", "Jaws"],
            correct_guesses=[
                {"name": "Alice", "time": 1.0},
                {"name": "Bob", "time": 2.0},
                {"name": "Charlie", "time": 3.0},
            ],
        )
        assert mc.get_player_bonus("Alice") == 5
        assert mc.get_player_bonus("Bob") == 3
        assert mc.get_player_bonus("Charlie") == 1
        assert mc.get_player_bonus("Nobody") == 0


# =========================================================================
# build_artist_options / build_movie_options
# =========================================================================

class TestBuildOptions:
    def test_build_artist_options_valid(self):
        song = {"artist": "Queen", "alt_artists": ["Beatles", "Nirvana"]}
        opts = build_artist_options(song)
        assert opts is not None
        assert "Queen" in opts
        assert len(opts) == 3

    def test_build_artist_options_no_alts(self):
        assert build_artist_options({"artist": "Queen"}) is None

    def test_build_artist_options_no_artist(self):
        assert build_artist_options({"alt_artists": ["Beatles"]}) is None

    def test_build_movie_options_valid(self):
        song = {"movie": "Grease", "movie_choices": ["Grease", "Jaws", "Rocky"]}
        opts = build_movie_options(song)
        assert opts is not None
        assert "Grease" in opts

    def test_build_movie_options_no_movie(self):
        assert build_movie_options({"movie_choices": ["A", "B"]}) is None

    def test_build_movie_options_no_choices(self):
        assert build_movie_options({"movie": "Grease"}) is None

    def test_build_movie_options_insufficient(self):
        assert build_movie_options({"movie": "Grease", "movie_choices": ["Grease"]}) is None


# =========================================================================
# GameState — is_deadline_passed
# =========================================================================

class TestDeadline:
    def test_no_deadline(self, game_state):
        assert game_state.is_deadline_passed() is False

    def test_deadline_not_passed(self, game_state):
        game_state.deadline = 1001000  # 1001 seconds in ms
        assert game_state.is_deadline_passed() is False  # clock at 1000.0

    def test_deadline_passed(self, game_state):
        game_state.deadline = 999000  # 999 seconds in ms
        assert game_state.is_deadline_passed() is True
