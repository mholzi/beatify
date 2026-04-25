"""Tests for Beatify game state (custom_components/beatify/game/state.py)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

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
        # ws.closed must be explicitly False — bare MagicMock attributes are
        # MagicMocks (truthy), which PlayerRegistry interprets as a dead
        # connection and allows rejoin under "stale connected flag" handling
        # (#646). For this test we want the original ws to look healthy.
        first_ws = MagicMock()
        first_ws.closed = False
        self.state.add_player("Alice", first_ws)
        ok, err = self.state.add_player("Alice", MagicMock())
        assert ok is False
        assert err == ERR_NAME_TAKEN

    def test_duplicate_name_case_insensitive(self):
        first_ws = MagicMock()
        first_ws.closed = False
        self.state.add_player("Alice", first_ws)
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
        self.state.add_player("Bob", MagicMock())
        ok, err = self.state.start_game()
        assert ok is True
        assert err is None
        assert self.state.phase == GamePhase.PLAYING

    def test_start_with_one_player_rejected(self):
        self.state.add_player("Alice", MagicMock())
        ok, err = self.state.start_game()
        assert ok is False
        assert err == ERR_GAME_NOT_STARTED

    def test_start_with_no_players(self):
        ok, err = self.state.start_game()
        assert ok is False
        assert err == ERR_GAME_NOT_STARTED

    def test_double_start_rejected(self):
        self.state.add_player("Alice", MagicMock())
        self.state.add_player("Bob", MagicMock())
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
        self.state.players["Alice"].rounds_played = 1
        assert self.state.get_average_score() == 40

    def test_multiple_players(self):
        self.state.add_player("Alice", MagicMock())
        self.state.add_player("Bob", MagicMock())
        self.state.players["Alice"].score = 40
        self.state.players["Alice"].rounds_played = 1
        self.state.players["Bob"].score = 60
        self.state.players["Bob"].rounds_played = 1
        assert self.state.get_average_score() == 50

    def test_excludes_unscored_late_joiners(self):
        self.state.add_player("Alice", MagicMock())
        self.state.add_player("Bob", MagicMock())
        self.state.players["Alice"].score = 40
        self.state.players["Alice"].rounds_played = 1
        # Bob is a late joiner with no rounds played
        self.state.players["Bob"].score = 40
        self.state.players["Bob"].rounds_played = 0
        assert self.state.get_average_score() == 40


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
        self.state._player_registry._reactions_this_phase = set()
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


# ---------------------------------------------------------------------------
# Issue #228: rematch_game → LOBBY phase with join_url (Start Gameplay fix)
# ---------------------------------------------------------------------------


class TestRematchGame:
    """Ensure rematch_game() puts game in LOBBY with a valid join_url so
    the admin 'Spiel starten' button can transition LOBBY → PLAYING."""

    def setup_method(self):
        from tests.conftest import make_game_state

        self.state = make_game_state()

    def test_rematch_transitions_to_lobby(self):
        """After rematch, phase must be LOBBY (not END or any other phase)."""
        _create_fresh_game(self.state)
        self.state.phase = GamePhase.END
        self.state.rematch_game()
        assert self.state.phase == GamePhase.LOBBY

    def test_rematch_generates_new_game_id(self):
        """New game_id should differ from the old one."""
        result = _create_fresh_game(self.state)
        old_id = result["game_id"]
        self.state.phase = GamePhase.END
        self.state.rematch_game()
        assert self.state.game_id is not None
        assert self.state.game_id != old_id

    def test_rematch_lobby_state_has_join_url(self):
        """get_state() after rematch must include join_url (required for QR code
        and the new 'Spiel starten' button in the admin lobby view, Issue #228)."""
        _create_fresh_game(self.state)
        self.state.phase = GamePhase.END
        self.state.rematch_game()
        state = self.state.get_state()
        assert state is not None
        assert state["phase"] == "LOBBY"
        assert "join_url" in state
        assert self.state.game_id in state["join_url"]

    def test_rematch_preserves_players(self):
        """Players must be preserved across rematch (scores reset)."""
        _create_fresh_game(self.state)
        self.state.add_player("Alice", MagicMock())
        self.state.players["Alice"].score = 200
        self.state.phase = GamePhase.END
        self.state.rematch_game()
        assert "Alice" in self.state.players
        assert self.state.players["Alice"].score == 0  # reset for new game

    def test_rematch_preserves_songs(self):
        """Songs must be restored so gameplay can start immediately."""
        songs = [
            {"year": 2000, "uri": "spotify:track:abc", "title": "T", "artist": "A"}
        ]
        _create_fresh_game(self.state, songs=songs)
        self.state.phase = GamePhase.END
        self.state.rematch_game()
        assert len(self.state.songs) > 0
        assert self.state.total_rounds > 0


# ---------------------------------------------------------------------------
# GameState.pause_game / resume_game
# ---------------------------------------------------------------------------


def _setup_playing_game(state: GameState) -> None:
    """Helper: set up a game in PLAYING phase with an admin player."""
    _create_fresh_game(state)
    ws = MagicMock()
    state.add_player("Admin", ws)
    state.set_admin("Admin")
    state.start_game()
    state.phase = GamePhase.PLAYING
    state.deadline = int(state._now() * 1000) + 30_000  # 30s remaining


class TestPauseGame:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.state = make_game_state()
        _setup_playing_game(self.state)

    @pytest.mark.asyncio
    async def test_pause_playing_game(self):
        result = await self.state.pause_game("admin_disconnected")
        assert result is True
        assert self.state.phase == GamePhase.PAUSED
        assert self.state._previous_phase == GamePhase.PLAYING

    @pytest.mark.asyncio
    async def test_pause_reveal_game(self):
        self.state.phase = GamePhase.REVEAL
        result = await self.state.pause_game("admin_disconnected")
        assert result is True
        assert self.state.phase == GamePhase.PAUSED
        assert self.state._previous_phase == GamePhase.REVEAL

    @pytest.mark.asyncio
    async def test_pause_already_paused(self):
        self.state.phase = GamePhase.PAUSED
        result = await self.state.pause_game("admin_disconnected")
        assert result is False

    @pytest.mark.asyncio
    async def test_pause_ended_game(self):
        self.state.phase = GamePhase.END
        result = await self.state.pause_game("admin_disconnected")
        assert result is False

    @pytest.mark.asyncio
    async def test_pause_stores_admin_name(self):
        await self.state.pause_game("admin_disconnected")
        assert self.state.disconnected_admin_name == "Admin"

    @pytest.mark.asyncio
    async def test_pause_sets_reason(self):
        await self.state.pause_game("admin_disconnected")
        assert self.state.pause_reason == "admin_disconnected"

    @pytest.mark.asyncio
    async def test_pause_cancels_timer(self):
        self.state._round_manager._timer_task = asyncio.create_task(asyncio.sleep(100))
        await self.state.pause_game("admin_disconnected")
        assert (
            self.state._round_manager._timer_task is None
            or self.state._round_manager._timer_task.cancelled()
        )

    @pytest.mark.asyncio
    async def test_pause_stops_media(self):
        mock_media = AsyncMock()
        self.state._media_player_service = mock_media
        await self.state.pause_game("admin_disconnected")
        mock_media.stop.assert_awaited_once()


class TestResumeGame:
    @pytest.fixture(autouse=True)
    def setup(self):
        self.state = make_game_state()
        _setup_playing_game(self.state)

    @pytest.mark.asyncio
    async def test_resume_to_playing(self):
        await self.state.pause_game("admin_disconnected")
        result = await self.state.resume_game()
        assert result is True
        assert self.state.phase == GamePhase.PLAYING

    @pytest.mark.asyncio
    async def test_resume_to_reveal(self):
        self.state.phase = GamePhase.REVEAL
        await self.state.pause_game("admin_disconnected")
        result = await self.state.resume_game()
        assert result is True
        assert self.state.phase == GamePhase.REVEAL

    @pytest.mark.asyncio
    async def test_resume_not_paused(self):
        result = await self.state.resume_game()
        assert result is False

    @pytest.mark.asyncio
    async def test_resume_no_previous_phase(self):
        self.state.phase = GamePhase.PAUSED
        self.state._previous_phase = None
        result = await self.state.resume_game()
        assert result is False

    @pytest.mark.asyncio
    async def test_resume_clears_pause_state(self):
        await self.state.pause_game("admin_disconnected")
        await self.state.resume_game()
        assert self.state.pause_reason is None
        assert self.state.disconnected_admin_name is None
        assert self.state._previous_phase is None

    @pytest.mark.asyncio
    async def test_resume_calls_play_without_args(self):
        """Regression test for #313: play() must be called with no args."""
        mock_media = AsyncMock()
        self.state._media_player_service = mock_media
        self.state.current_song = {"title": "Test", "uri": "spotify:track:test"}
        await self.state.pause_game("admin_disconnected")
        await self.state.resume_game()
        mock_media.play.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_resume_expired_timer_ends_round(self):
        """When timer expired during pause, round should end immediately."""
        self.state.deadline = int(self.state._now() * 1000) - 1000  # expired
        await self.state.pause_game("admin_disconnected")
        self.state.end_round = AsyncMock()
        result = await self.state.resume_game()
        assert result is True
        self.state.end_round.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_pause_resume_roundtrip(self):
        original_phase = self.state.phase
        await self.state.pause_game("admin_disconnected")
        assert self.state.phase == GamePhase.PAUSED
        await self.state.resume_game()
        assert self.state.phase == original_phase
