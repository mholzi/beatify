"""Tests for Beatify game state (custom_components/beatify/game/state.py)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.beatify.const import (
    ERR_CANNOT_STEAL_SELF,
    ERR_GAME_ALREADY_STARTED,
    ERR_GAME_ENDED,
    ERR_GAME_FULL,
    ERR_GAME_NOT_STARTED,
    ERR_INVALID_ACTION,
    ERR_NAME_INVALID,
    ERR_NAME_TAKEN,
    ERR_NO_STEAL_AVAILABLE,
    ERR_NOT_IN_GAME,
    ERR_TARGET_NOT_SUBMITTED,
    MAX_PLAYERS,
)
from custom_components.beatify.game.state import (
    GamePhase,
    GameState,
    build_artist_options,
    build_movie_options,
)
from tests.conftest import make_game_state, make_songs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_fresh_game(state: GameState, songs=None, **kwargs) -> dict:
    """Helper: create a game with default or custom songs."""
    songs = songs or make_songs(5)
    return state.create_game(
        playlists=["test.json"],
        songs=songs,
        media_player="media_player.test",
        base_url="http://localhost:8123",
        **kwargs,
    )


# ---------------------------------------------------------------------------
# GameState.create_game
# ---------------------------------------------------------------------------


class TestCreateGame:
    def test_returns_expected_keys(self):
        state = make_game_state()
        result = _create_fresh_game(state)
        assert "game_id" in result
        assert "join_url" in result
        assert "phase" in result
        assert result["song_count"] == 5

    def test_phase_is_lobby(self):
        state = make_game_state()
        _create_fresh_game(state)
        assert state.phase == GamePhase.LOBBY

    def test_join_url_contains_game_id(self):
        state = make_game_state()
        result = _create_fresh_game(state)
        assert result["game_id"] in result["join_url"]

    def test_invalid_round_duration_too_short(self):
        state = make_game_state()
        with pytest.raises(ValueError):
            _create_fresh_game(state, round_duration=5)

    def test_invalid_round_duration_too_long(self):
        state = make_game_state()
        with pytest.raises(ValueError):
            _create_fresh_game(state, round_duration=120)

    def test_valid_round_duration_boundary(self):
        state = make_game_state()
        result = _create_fresh_game(state, round_duration=15)
        assert result["game_id"] is not None

    def test_clears_previous_game(self):
        state = make_game_state()
        _create_fresh_game(state)
        # Add a player
        state.add_player("Alice", MagicMock())
        # Create new game - should clear players
        _create_fresh_game(state)
        assert len(state.players) == 0

    def test_difficulty_stored(self):
        state = make_game_state()
        _create_fresh_game(state, difficulty="hard")
        assert state.difficulty == "hard"

    def test_total_rounds_equals_song_count(self):
        state = make_game_state()
        _create_fresh_game(state, songs=make_songs(10))
        assert state.total_rounds == 10


# ---------------------------------------------------------------------------
# GameState.add_player
# ---------------------------------------------------------------------------


class TestAddPlayer:
    def setup_method(self):
        self.state = make_game_state()
        _create_fresh_game(self.state)

    def test_add_player_success(self):
        ok, err = self.state.add_player("Alice", MagicMock())
        assert ok is True
        assert err is None
        assert "Alice" in self.state.players

    def test_add_duplicate_name_rejected(self):
        self.state.add_player("Alice", MagicMock())
        ok, err = self.state.add_player("Alice", MagicMock())
        assert ok is False
        assert err == ERR_NAME_TAKEN

    def test_duplicate_name_case_insensitive(self):
        self.state.add_player("Alice", MagicMock())
        ok, err = self.state.add_player("alice", MagicMock())
        assert ok is False
        assert err == ERR_NAME_TAKEN

    def test_empty_name_rejected(self):
        ok, err = self.state.add_player("", MagicMock())
        assert ok is False
        assert err == ERR_NAME_INVALID

    def test_whitespace_only_name_rejected(self):
        ok, err = self.state.add_player("   ", MagicMock())
        assert ok is False
        assert err == ERR_NAME_INVALID

    def test_name_too_long_rejected(self):
        ok, err = self.state.add_player("A" * 21, MagicMock())
        assert ok is False
        assert err == ERR_NAME_INVALID

    def test_name_at_max_length_accepted(self):
        ok, err = self.state.add_player("A" * 20, MagicMock())
        assert ok is True
        assert err is None

    def test_game_full_rejected(self):
        for i in range(MAX_PLAYERS):
            self.state.add_player(f"Player{i}", MagicMock())
        ok, err = self.state.add_player("OneMore", MagicMock())
        assert ok is False
        assert err == ERR_GAME_FULL

    def test_adding_in_end_phase_rejected(self):
        self.state.phase = GamePhase.END
        ok, err = self.state.add_player("Alice", MagicMock())
        assert ok is False
        assert err == ERR_GAME_ENDED

    def test_reconnection_allowed(self):
        ws1 = MagicMock()
        ws2 = MagicMock()
        self.state.add_player("Alice", ws1)
        # Simulate disconnect
        self.state.players["Alice"].connected = False
        # Reconnect with same name
        ok, err = self.state.add_player("Alice", ws2)
        assert ok is True
        assert err is None
        assert self.state.players["Alice"].ws == ws2
        assert self.state.players["Alice"].connected is True

    def test_player_name_trimmed(self):
        ok, err = self.state.add_player("  Bob  ", MagicMock())
        assert ok is True
        assert "Bob" in self.state.players


# ---------------------------------------------------------------------------
# GameState.start_game
# ---------------------------------------------------------------------------


class TestStartGame:
    def setup_method(self):
        self.state = make_game_state()
        _create_fresh_game(self.state)

    def test_start_with_players(self):
        self.state.add_player("Alice", MagicMock())
        ok, err = self.state.start_game()
        assert ok is True
        assert err is None
        assert self.state.phase == GamePhase.PLAYING

    def test_start_with_no_players(self):
        ok, err = self.state.start_game()
        assert ok is False
        assert err == ERR_GAME_NOT_STARTED

    def test_double_start_rejected(self):
        self.state.add_player("Alice", MagicMock())
        self.state.start_game()
        ok, err = self.state.start_game()
        assert ok is False
        assert err == ERR_GAME_ALREADY_STARTED


# ---------------------------------------------------------------------------
# GameState.all_submitted
# ---------------------------------------------------------------------------


class TestAllSubmitted:
    def setup_method(self):
        self.state = make_game_state()
        _create_fresh_game(self.state)
        self.state.add_player("Alice", MagicMock())
        self.state.add_player("Bob", MagicMock())

    def test_no_submissions_returns_false(self):
        assert self.state.all_submitted() is False

    def test_partial_submissions_returns_false(self):
        self.state.players["Alice"].submitted = True
        assert self.state.all_submitted() is False

    def test_all_submitted_returns_true(self):
        self.state.players["Alice"].submitted = True
        self.state.players["Bob"].submitted = True
        assert self.state.all_submitted() is True

    def test_disconnected_player_excluded(self):
        self.state.players["Bob"].connected = False
        self.state.players["Alice"].submitted = True
        assert self.state.all_submitted() is True

    def test_no_players_returns_false(self):
        self.state.players.clear()
        assert self.state.all_submitted() is False


# ---------------------------------------------------------------------------
# GameState.get_leaderboard
# ---------------------------------------------------------------------------


class TestLeaderboard:
    def setup_method(self):
        self.state = make_game_state()
        _create_fresh_game(self.state)

    def test_sorted_by_score_descending(self):
        self.state.add_player("Alice", MagicMock())
        self.state.add_player("Bob", MagicMock())
        self.state.players["Alice"].score = 50
        self.state.players["Bob"].score = 80
        lb = self.state.get_leaderboard()
        assert lb[0]["name"] == "Bob"
        assert lb[1]["name"] == "Alice"

    def test_tied_scores_same_rank(self):
        self.state.add_player("Alice", MagicMock())
        self.state.add_player("Bob", MagicMock())
        self.state.players["Alice"].score = 50
        self.state.players["Bob"].score = 50
        lb = self.state.get_leaderboard()
        assert lb[0]["rank"] == 1
        assert lb[1]["rank"] == 1

    def test_rank_skips_after_tie(self):
        self.state.add_player("Alice", MagicMock())
        self.state.add_player("Bob", MagicMock())
        self.state.add_player("Carol", MagicMock())
        self.state.players["Alice"].score = 100
        self.state.players["Bob"].score = 50
        self.state.players["Carol"].score = 50
        lb = self.state.get_leaderboard()
        ranks = {e["name"]: e["rank"] for e in lb}
        assert ranks["Alice"] == 1
        assert ranks["Bob"] == 2
        assert ranks["Carol"] == 2

    def test_empty_returns_empty_list(self):
        assert self.state.get_leaderboard() == []


# ---------------------------------------------------------------------------
# GameState.get_average_score
# ---------------------------------------------------------------------------


class TestGetAverageScore:
    def setup_method(self):
        self.state = make_game_state()
        _create_fresh_game(self.state)

    def test_no_players(self):
        assert self.state.get_average_score() == 0

    def test_single_player(self):
        self.state.add_player("Alice", MagicMock())
        self.state.players["Alice"].score = 40
        assert self.state.get_average_score() == 40

    def test_multiple_players(self):
        self.state.add_player("Alice", MagicMock())
        self.state.add_player("Bob", MagicMock())
        self.state.players["Alice"].score = 40
        self.state.players["Bob"].score = 60
        assert self.state.get_average_score() == 50


# ---------------------------------------------------------------------------
# GameState.use_steal
# ---------------------------------------------------------------------------


class TestUseSteal:
    def setup_method(self):
        self.state = make_game_state()
        _create_fresh_game(self.state)
        self.state.add_player("Alice", MagicMock())
        self.state.add_player("Bob", MagicMock())
        self.state.phase = GamePhase.PLAYING

    def test_no_steal_available(self):
        result = self.state.use_steal("Alice", "Bob")
        assert result["success"] is False
        assert result["error"] == ERR_NO_STEAL_AVAILABLE

    def test_target_not_submitted(self):
        self.state.players["Alice"].steal_available = True
        result = self.state.use_steal("Alice", "Bob")
        assert result["success"] is False
        assert result["error"] == ERR_TARGET_NOT_SUBMITTED

    def test_cannot_steal_self(self):
        self.state.players["Alice"].steal_available = True
        result = self.state.use_steal("Alice", "Alice")
        assert result["success"] is False
        assert result["error"] == ERR_CANNOT_STEAL_SELF

    def test_successful_steal(self):
        self.state.players["Alice"].steal_available = True
        self.state.players["Bob"].submitted = True
        self.state.players["Bob"].current_guess = 1990
        result = self.state.use_steal("Alice", "Bob")
        assert result["success"] is True
        assert result["year"] == 1990
        assert self.state.players["Alice"].current_guess == 1990
        assert self.state.players["Alice"].submitted is True
        assert self.state.players["Alice"].steal_available is False
        assert self.state.players["Alice"].steal_used is True

    def test_steal_wrong_phase(self):
        self.state.phase = GamePhase.REVEAL
        self.state.players["Alice"].steal_available = True
        self.state.players["Bob"].submitted = True
        self.state.players["Bob"].current_guess = 1990
        result = self.state.use_steal("Alice", "Bob")
        assert result["success"] is False
        assert result["error"] == ERR_INVALID_ACTION

    def test_unknown_stealer(self):
        result = self.state.use_steal("Ghost", "Bob")
        assert result["success"] is False
        assert result["error"] == ERR_NOT_IN_GAME


# ---------------------------------------------------------------------------
# GameState.record_reaction
# ---------------------------------------------------------------------------


class TestRecordReaction:
    def setup_method(self):
        self.state = make_game_state()
        _create_fresh_game(self.state)
        self.state.add_player("Alice", MagicMock())

    def test_first_reaction_accepted(self):
        assert self.state.record_reaction("Alice", "🎉") is True

    def test_second_reaction_from_same_player_rejected(self):
        self.state.record_reaction("Alice", "🎉")
        assert self.state.record_reaction("Alice", "😄") is False

    def test_different_players_each_get_one(self):
        self.state.add_player("Bob", MagicMock())
        assert self.state.record_reaction("Alice", "🎉") is True
        assert self.state.record_reaction("Bob", "🎉") is True

    def test_reset_between_phases(self):
        self.state.record_reaction("Alice", "🎉")
        # Simulate phase reset (happens in end_round)
        self.state._reactions_this_phase = set()
        assert self.state.record_reaction("Alice", "🎉") is True


# ---------------------------------------------------------------------------
# build_movie_options
# ---------------------------------------------------------------------------


class TestBuildMovieOptions:
    def test_valid_song(self):
        song = {
            "movie": "Grease",
            "movie_choices": ["Grease", "Saturday Night Fever", "Footloose"],
        }
        options = build_movie_options(song)
        assert options is not None
        assert len(options) == 3
        assert "Grease" in options

    def test_missing_movie_returns_none(self):
        song = {"movie_choices": ["A", "B", "C"]}
        assert build_movie_options(song) is None

    def test_empty_movie_returns_none(self):
        song = {"movie": "", "movie_choices": ["A", "B"]}
        assert build_movie_options(song) is None

    def test_insufficient_choices_returns_none(self):
        song = {"movie": "Grease", "movie_choices": ["Grease"]}
        assert build_movie_options(song) is None

    def test_options_are_shuffled(self):
        """Options should include the correct movie."""
        song = {
            "movie": "Grease",
            "movie_choices": ["Grease", "Footloose", "Dirty Dancing"],
        }
        options = build_movie_options(song)
        assert "Grease" in options

    def test_correct_movie_added_if_missing_from_choices(self):
        """If correct movie not in choices, it's inserted."""
        song = {
            "movie": "Grease",
            "movie_choices": ["Footloose", "Dirty Dancing"],
        }
        options = build_movie_options(song)
        assert options is not None
        assert "Grease" in options


# ---------------------------------------------------------------------------
# build_artist_options
# ---------------------------------------------------------------------------


class TestBuildArtistOptions:
    def test_valid_song(self):
        song = {
            "artist": "The Beatles",
            "alt_artists": ["The Rolling Stones", "Led Zeppelin"],
        }
        options = build_artist_options(song)
        assert options is not None
        assert "The Beatles" in options
        assert len(options) == 3

    def test_missing_artist_returns_none(self):
        song = {"alt_artists": ["X", "Y"]}
        assert build_artist_options(song) is None

    def test_empty_artist_returns_none(self):
        song = {"artist": "", "alt_artists": ["X", "Y"]}
        assert build_artist_options(song) is None

    def test_no_alt_artists_returns_none(self):
        song = {"artist": "The Beatles", "alt_artists": []}
        assert build_artist_options(song) is None

    def test_options_include_correct_artist(self):
        song = {
            "artist": "ABBA",
            "alt_artists": ["Bee Gees", "Donna Summer"],
        }
        options = build_artist_options(song)
        assert "ABBA" in options


# ---------------------------------------------------------------------------
# GameState.finalize_game
# ---------------------------------------------------------------------------


class TestFinalizeGame:
    def setup_method(self):
        self.state = make_game_state()
        _create_fresh_game(self.state, songs=make_songs(5))
        self.state.add_player("Alice", MagicMock())
        self.state.add_player("Bob", MagicMock())
        self.state.players["Alice"].score = 120
        self.state.players["Bob"].score = 80
        self.state.round = 5

    def test_winner_is_highest_scorer(self):
        summary = self.state.finalize_game()
        assert summary["winner"] == "Alice"
        assert summary["winner_score"] == 120

    def test_total_points(self):
        summary = self.state.finalize_game()
        assert summary["total_points"] == 200

    def test_rounds_tracked(self):
        summary = self.state.finalize_game()
        assert summary["rounds"] == 5

    def test_player_count(self):
        summary = self.state.finalize_game()
        assert summary["player_count"] == 2

    def test_avg_score_per_round(self):
        summary = self.state.finalize_game()
        # 200 total / (5 rounds * 2 players) = 20.0
        assert summary["avg_score_per_round"] == pytest.approx(20.0)

    def test_no_players_returns_unknown_winner(self):
        self.state.players.clear()
        summary = self.state.finalize_game()
        assert summary["winner"] == "Unknown"
        assert summary["winner_score"] == 0


# ---------------------------------------------------------------------------
# GameState.is_deadline_passed
# ---------------------------------------------------------------------------


class TestDeadlinePassed:
    def test_no_deadline_returns_false(self):
        state = make_game_state()
        assert state.is_deadline_passed() is False

    def test_past_deadline_returns_true(self):
        now = 1_000_000.0
        state = make_game_state(time_fn=lambda: now)
        # Deadline 10 seconds in the past
        state.deadline = int((now - 10) * 1000)
        assert state.is_deadline_passed() is True

    def test_future_deadline_returns_false(self):
        now = 1_000_000.0
        state = make_game_state(time_fn=lambda: now)
        state.deadline = int((now + 30) * 1000)
        assert state.is_deadline_passed() is False


# ---------------------------------------------------------------------------
# GameState.get_state (smoke test for each phase)
# ---------------------------------------------------------------------------


class TestGetState:
    def setup_method(self):
        self.state = make_game_state()

    def test_no_game_returns_none(self):
        assert self.state.get_state() is None

    def test_lobby_state_has_join_url(self):
        _create_fresh_game(self.state)
        state = self.state.get_state()
        assert state is not None
        assert "join_url" in state
        assert state["phase"] == "LOBBY"

    def test_end_state_has_winner(self):
        _create_fresh_game(self.state)
        self.state.add_player("Alice", MagicMock())
        self.state.players["Alice"].score = 100
        self.state.phase = GamePhase.END
        state = self.state.get_state()
        assert "winner" in state
        assert state["winner"]["name"] == "Alice"
