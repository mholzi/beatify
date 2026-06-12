"""Tests for Beatify game state (custom_components/beatify/game/state.py)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

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


def _make_ws_for_state() -> AsyncMock:
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    ws.closed = False
    return ws


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


class TestCreateGameNoPlayableSongsAtomicity:
    """#1378: the #709 no-playable-songs check must run BEFORE any mutation.

    make_songs() yields Spotify-only URIs, so requesting provider
    "apple_music" leaves zero playable songs and create_game must raise
    ValueError without leaving GameState half-built (game_id minted, phase
    flipped to LOBBY, players wiped) — otherwise the host is dead-ended by
    the create-handler's existing-game guard (#935) on every retry.
    """

    def test_raises_for_no_playable_songs(self):
        state = make_game_state()
        with pytest.raises(ValueError, match="No playable songs"):
            _create_fresh_game(state, provider="apple_music")

    def test_game_id_not_minted_on_validation_failure(self):
        state = make_game_state()
        assert state.game_id is None
        with pytest.raises(ValueError, match="No playable songs"):
            _create_fresh_game(state, provider="apple_music")
        assert state.game_id is None

    def test_set_phase_not_invoked_on_validation_failure(self):
        # A fresh GameState already defaults to LOBBY, so asserting on the
        # final phase value can't distinguish "never touched" from "flipped".
        # Assert the _set_phase chokepoint is never called instead.
        state = make_game_state()
        with patch.object(state, "_set_phase", wraps=state._set_phase) as set_phase:
            with pytest.raises(ValueError, match="No playable songs"):
                _create_fresh_game(state, provider="apple_music")
        set_phase.assert_not_called()

    def test_players_not_wiped_on_validation_failure(self):
        state = make_game_state()
        # Seed a real lobby with a player (the "existing game" scenario).
        _create_fresh_game(state)
        state.add_player("Alice", MagicMock())
        good_game_id = state.game_id
        assert len(state.players) == 1

        # A failed create attempt (bad provider) must NOT wipe the existing
        # game's players, game_id, or phase.
        with pytest.raises(ValueError, match="No playable songs"):
            _create_fresh_game(state, provider="apple_music")
        assert len(state.players) == 1
        assert state.game_id == good_game_id
        assert state.phase == GamePhase.LOBBY

    def test_retry_with_valid_provider_succeeds_after_failure(self):
        state = make_game_state()
        with pytest.raises(ValueError, match="No playable songs"):
            _create_fresh_game(state, provider="apple_music")
        # Pre-mutation validation means retrying with a working provider just
        # works — no zombie lobby blocking it.
        result = _create_fresh_game(state, provider="spotify")
        assert result["game_id"] is not None
        assert state.phase == GamePhase.LOBBY


# ---------------------------------------------------------------------------
# REVEAL auto-advance (#1012)
# ---------------------------------------------------------------------------


class TestRevealAutoAdvance:
    def test_defaults_to_off(self):
        state = make_game_state()
        _create_fresh_game(state)
        assert state.reveal_auto_advance == 0

    def test_stores_configured_value(self):
        state = make_game_state()
        _create_fresh_game(state, reveal_auto_advance=60)
        assert state.reveal_auto_advance == 60

    def test_cancel_with_no_task_is_safe(self):
        state = make_game_state()
        _create_fresh_game(state)
        state._cancel_auto_advance()  # must not raise

    def test_song_finished_true_when_player_idle(self):
        state = make_game_state()
        _create_fresh_game(state)
        state._media_player_service = MagicMock()
        state._media_player_service.get_playback_state.return_value = "idle"
        assert state._song_finished() is True

    def test_song_finished_false_while_playing(self):
        state = make_game_state()
        _create_fresh_game(state)
        state._media_player_service = MagicMock()
        state._media_player_service.get_playback_state.return_value = "playing"
        assert state._song_finished() is False

    def test_song_finished_false_without_media_service(self):
        state = make_game_state()
        _create_fresh_game(state)
        state._media_player_service = None
        assert state._song_finished() is False

    def test_song_finished_false_when_transiently_unavailable(self):
        # #1374: a transient "unavailable" blip (Sonos/Cast handoff, MA
        # reload during the REVEAL dwell) must NOT be read as song-end.
        state = make_game_state()
        _create_fresh_game(state)
        state._media_player_service = MagicMock()
        state._media_player_service.get_playback_state.return_value = "unavailable"
        assert state._song_finished() is False

    def test_song_finished_false_when_state_none(self):
        # #1374: get_playback_state() returns None when the entity is
        # unavailable — same conservative handling as "unavailable".
        state = make_game_state()
        _create_fresh_game(state)
        state._media_player_service = MagicMock()
        state._media_player_service.get_playback_state.return_value = None
        assert state._song_finished() is False

    def test_song_finished_true_after_unavailable_recovers_to_idle(self):
        # #1374: a transient blip followed by a genuine song-end (player
        # back to "idle") still advances — the fix only suppresses the
        # blip itself, not a real track end.
        state = make_game_state()
        _create_fresh_game(state)
        state._media_player_service = MagicMock()
        state._media_player_service.get_playback_state.return_value = "unavailable"
        assert state._song_finished() is False
        state._media_player_service.get_playback_state.return_value = "idle"
        assert state._song_finished() is True

    async def test_advances_on_song_end(self):
        state = make_game_state()
        _create_fresh_game(state)
        state.phase = GamePhase.REVEAL
        state.start_round = AsyncMock()
        state._song_finished = MagicMock(return_value=True)
        with patch("asyncio.sleep", new=AsyncMock()):
            await state._reveal_auto_advance(0)
        state.start_round.assert_awaited_once()

    async def test_does_not_advance_when_phase_left_reveal(self):
        state = make_game_state()
        _create_fresh_game(state)
        state.phase = GamePhase.PLAYING
        state.start_round = AsyncMock()
        state._song_finished = MagicMock(return_value=True)
        with patch("asyncio.sleep", new=AsyncMock()):
            await state._reveal_auto_advance(0)
        state.start_round.assert_not_awaited()

    async def test_unattended_final_round_runs_end_ceremony_and_broadcasts(self):
        """#1360 regression: when the auto-advance carries the FINAL round and
        start_round() exhausts the playlist, it flips phase to END and returns
        False (a bare _set_phase(END), bypassing advance_to_end). Previously the
        broadcast only fired `if success`, so the game ended with no winner
        ceremony AND no broadcast — every client frozen on REVEAL.

        The unattended end must mirror the manual admin_next_round game-end: run
        advance_to_end() (party-light celebration + winner/podium TTS) AND fire
        the broadcast so the END state reaches clients.
        """
        state = make_game_state()
        _create_fresh_game(state)
        state.phase = GamePhase.REVEAL
        state._song_finished = MagicMock(return_value=True)

        # Simulate playlist exhaustion: start_round() flips to END + returns
        # False, exactly like the bare _set_phase(GamePhase.END) exhaustion
        # branch in RoundLifecycleMixin.start_round.
        async def exhausted_start_round(*_args, **_kwargs):
            state.phase = GamePhase.END
            return False

        state.start_round = AsyncMock(side_effect=exhausted_start_round)

        # Spy on the terminal ceremony + the broadcast callback.
        state.advance_to_end = AsyncMock()
        broadcast = AsyncMock()
        state.set_round_end_callback(broadcast)

        with patch("asyncio.sleep", new=AsyncMock()):
            await state._reveal_auto_advance(0)

        # Ceremony ran (winner/podium TTS + party lights) and END was broadcast.
        state.advance_to_end.assert_awaited_once()
        broadcast.assert_awaited_once()

    async def test_advance_broadcasts_after_normal_next_round(self):
        """Counterpart to #1360: a NON-final auto-advance (start_round succeeds)
        must still broadcast the new PLAYING state, and must NOT run the
        game-end ceremony.
        """
        state = make_game_state()
        _create_fresh_game(state)
        state.phase = GamePhase.REVEAL
        state._song_finished = MagicMock(return_value=True)
        state.start_round = AsyncMock(return_value=True)
        state.advance_to_end = AsyncMock()
        broadcast = AsyncMock()
        state.set_round_end_callback(broadcast)

        with patch("asyncio.sleep", new=AsyncMock()):
            await state._reveal_auto_advance(0)

        broadcast.assert_awaited_once()
        state.advance_to_end.assert_not_awaited()

    async def test_idle_halt_stops_playback_and_does_not_advance(self):
        """Zero-guess round: song-end stops the speaker, no new round."""
        state = make_game_state()
        _create_fresh_game(state)
        state.phase = GamePhase.REVEAL
        state.start_round = AsyncMock()
        state._song_finished = MagicMock(return_value=True)
        state._media_player_service = MagicMock()
        state._media_player_service.stop = AsyncMock()
        with patch("asyncio.sleep", new=AsyncMock()):
            await state._reveal_idle_halt()
        state._media_player_service.stop.assert_awaited_once()
        state.start_round.assert_not_awaited()

    async def test_idle_halt_no_stop_when_phase_left_reveal(self):
        """A manual next-round / pause before song-end makes the halt a no-op."""
        state = make_game_state()
        _create_fresh_game(state)
        state.phase = GamePhase.PLAYING
        state.start_round = AsyncMock()
        state._song_finished = MagicMock(return_value=True)
        state._media_player_service = MagicMock()
        state._media_player_service.stop = AsyncMock()
        with patch("asyncio.sleep", new=AsyncMock()):
            await state._reveal_idle_halt()
        state._media_player_service.stop.assert_not_awaited()
        state.start_round.assert_not_awaited()

    async def test_idle_halt_no_stop_when_phase_changes_as_song_finishes(self):
        """#1123 regression guard: admin clicked 'Next Round' exactly when the
        song finished.  The loop detects song-end and exits, but between the
        loop exit and the stop() call the admin's next_round command was
        processed and phase moved to PLAYING.  idle_halt must skip stop() so
        the newly-started song is not immediately silenced.

        Simulated by having _song_finished() flip the phase to PLAYING as a
        side-effect (represents the instant the song ends AND admin advances).
        """
        state = make_game_state()
        _create_fresh_game(state)
        state.phase = GamePhase.REVEAL
        state._media_player_service = MagicMock()
        state._media_player_service.stop = AsyncMock()

        def song_finished_and_phase_change():
            # Admin clicked Next Round at the exact moment the song ended:
            # start_round() already transitioned the phase to PLAYING.
            state.phase = GamePhase.PLAYING
            return True

        state._song_finished = MagicMock(side_effect=song_finished_and_phase_change)

        with patch("asyncio.sleep", new=AsyncMock()):
            await state._reveal_idle_halt()

        # Phase left REVEAL — stop() must NOT be called (would silence new song)
        state._media_player_service.stop.assert_not_awaited()

    async def test_end_game_cancels_auto_advance_task(self):
        """#1012 hardening: ending the game during REVEAL must cancel the
        auto-advance task synchronously, before end_game's awaits — otherwise a
        countdown expiring at that instant could fire start_round() (phase still
        REVEAL inside disable_party_lights/disable_tts) and play the next song
        after the game ended. Mirrors advance_to_end(); guards the HTTP/force-end
        path that calls end_game() directly.
        """
        state = make_game_state()
        _create_fresh_game(state, reveal_auto_advance=30)
        state.phase = GamePhase.REVEAL
        state.start_round = AsyncMock()

        # A real pending auto-advance task, parked on its first poll-sleep.
        task = asyncio.create_task(state._reveal_auto_advance(30))
        state._auto_advance_task = task
        await asyncio.sleep(0)  # let it reach `await asyncio.sleep(poll)`

        await state.end_game()

        # Handle cleared, task cancelled, no next round triggered.
        assert state._auto_advance_task is None
        with pytest.raises(asyncio.CancelledError):
            await task
        assert task.cancelled()
        state.start_round.assert_not_awaited()
        assert state.phase == GamePhase.LOBBY


# ---------------------------------------------------------------------------
# REVEAL countdown surface (#1048)
# ---------------------------------------------------------------------------


class TestRevealStartedAt:
    def test_starts_as_none(self):
        state = make_game_state()
        _create_fresh_game(state)
        assert state.reveal_started_at is None

    async def test_cleared_on_advance_to_end(self):
        state = make_game_state()
        _create_fresh_game(state)
        state.reveal_started_at = 123456789
        await state.advance_to_end()
        assert state.reveal_started_at is None

    def test_serializer_includes_advance_and_started_at_in_reveal(self):
        from custom_components.beatify.game.serializers import GameStateSerializer

        state = make_game_state()
        _create_fresh_game(state, reveal_auto_advance=30)
        state.phase = GamePhase.REVEAL
        state.reveal_started_at = 1_700_000_000_000
        # Mark at least one player as submitted so idle_halt isn't set.
        state.add_player("Alice", MagicMock())
        state.players["Alice"].submitted = True

        payload = GameStateSerializer.serialize(state)
        assert payload["reveal_auto_advance"] == 30
        assert payload["reveal_started_at"] == 1_700_000_000_000

    def test_serializer_omits_started_at_when_unset(self):
        from custom_components.beatify.game.serializers import GameStateSerializer

        state = make_game_state()
        _create_fresh_game(state, reveal_auto_advance=0)
        state.phase = GamePhase.REVEAL
        state.reveal_started_at = None
        state.add_player("Alice", MagicMock())
        state.players["Alice"].submitted = True

        payload = GameStateSerializer.serialize(state)
        assert payload["reveal_auto_advance"] == 0
        assert "reveal_started_at" not in payload


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
        # closed=False → the ws looks live, so is_active is True.
        self.state.add_player("Alice", MagicMock(closed=False))
        self.state.add_player("Bob", MagicMock(closed=False))

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

    def test_stale_connected_ghost_excluded(self):
        # #928: a player whose WebSocket is already closed but whose
        # `connected` flag has not been cleared must not block all-submitted.
        self.state.players["Bob"].ws.closed = True
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

    def test_paused_state_includes_reason_and_error_detail(self):
        """#805: PAUSED state must surface pause_reason AND last_error_detail
        so the admin's recovery banner can render the right message.
        """
        _create_fresh_game(self.state)
        self.state.phase = GamePhase.PAUSED
        self.state.pause_reason = "media_player_error"
        self.state.last_error_detail = "Speaker timed out after 15s"
        state = self.state.get_state()
        assert state is not None
        assert state["phase"] == "PAUSED"
        assert state["pause_reason"] == "media_player_error"
        assert state["last_error_detail"] == "Speaker timed out after 15s"

    def test_paused_state_empty_error_detail_when_unset(self):
        """admin_disconnected pauses leave last_error_detail empty —
        client uses this to skip the banner.
        """
        _create_fresh_game(self.state)
        self.state.phase = GamePhase.PAUSED
        self.state.pause_reason = "admin_disconnected"
        # last_error_detail defaults to "" on init, but be explicit:
        self.state.last_error_detail = ""
        state = self.state.get_state()
        assert state["last_error_detail"] == ""

    def test_paused_state_includes_provider(self):
        """#808 follow-up: PAUSED state must surface the user's selected
        provider so the recovery banner can name it explicitly
        ("Re-authenticate Apple Music in Music Assistant") instead of a
        generic "your music provider" hint.
        """
        _create_fresh_game(self.state)
        # Override provider after creation — bypasses the create_game URI
        # validation (test fixtures don't have apple_music URIs populated).
        self.state.provider = "apple_music"
        self.state.phase = GamePhase.PAUSED
        self.state.pause_reason = "media_player_error"
        state = self.state.get_state()
        assert state is not None
        assert state["provider"] == "apple_music"


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

    def test_rematch_total_rounds_uses_filtered_count(self):
        """#1377: total_rounds after rematch must come from the filtered/deduped
        PlaylistManager pool (like create_game), NOT len(raw songs).

        Two songs share a URI, so PlaylistManager dedupes one away: the raw
        list has 2 entries but the playable pool has 1. total_rounds must be 1.
        """
        songs = [
            {
                "year": 2000,
                "uri": "spotify:track:dup",
                "_resolved_uri": "spotify:track:dup",
                "title": "First",
                "artist": "A",
            },
            {
                "year": 2001,
                "uri": "spotify:track:dup",  # duplicate URI → deduped out
                "_resolved_uri": "spotify:track:dup",
                "title": "Second",
                "artist": "B",
            },
        ]
        _create_fresh_game(self.state, songs=songs)
        # create_game already derives the filtered count; sanity-check it.
        assert self.state.total_rounds == 1
        self.state.phase = GamePhase.END
        self.state.rematch_game()
        # rematch must match create_game, not len(preserved["songs"]) == 2.
        assert self.state.total_rounds == self.state._playlist_manager.get_total_count()
        assert self.state.total_rounds == 1


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

    @pytest.mark.asyncio
    async def test_pause_captures_admin_name_for_any_reason(self):
        """#790: pause_game must capture admin name regardless of reason.

        Without this, server-triggered pauses (media_player_error,
        no_songs_available) leave disconnected_admin_name empty and the admin
        can't reclaim via the existing reconnect path — creating an
        unrecoverable stuck state.
        """
        await self.state.pause_game("media_player_error")
        assert self.state.disconnected_admin_name == "Admin"

    @pytest.mark.asyncio
    async def test_pause_captures_admin_name_on_no_songs_available(self):
        await self.state.pause_game("no_songs_available")
        assert self.state.disconnected_admin_name == "Admin"


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
    async def test_resume_to_reveal_does_not_restamp_reveal_started_at(self):
        # #1273: resume routes through _set_phase(restore=True), which must NOT
        # re-stamp reveal_started_at. pause_game cleared it (left REVEAL), so it
        # stays None across the resume — the auto-advance countdown is not
        # restarted. Behaviour-preserving vs. the prior direct phase write.
        self.state.phase = GamePhase.REVEAL
        await self.state.pause_game("admin_disconnected")
        assert self.state.reveal_started_at is None
        result = await self.state.resume_game()
        assert result is True
        assert self.state.phase == GamePhase.REVEAL
        assert self.state.reveal_started_at is None

    @pytest.mark.asyncio
    async def test_resume_to_reveal_rearms_auto_advance(self):
        """#1371: a pause during REVEAL cancels the auto-advance task; resume
        must re-arm it, otherwise the game stalls on REVEAL forever (the very
        admin-disconnect pause unattended mode is meant to survive)."""
        self.state.phase = GamePhase.REVEAL
        # A round where someone submitted → auto-advance (not idle-halt).
        for p in self.state.players.values():
            p.submitted = True
        await self.state.pause_game("admin_disconnected")
        assert self.state._auto_advance_task is None  # pause cancelled it
        with patch.object(self.state, "_schedule_song_end_auto_advance") as rearm:
            result = await self.state.resume_game()
        assert result is True
        assert self.state.phase == GamePhase.REVEAL
        rearm.assert_called_once()

    @pytest.mark.asyncio
    async def test_resume_to_reveal_rearms_idle_halt_when_no_guesses(self):
        """#1371: zero-guess REVEAL must re-arm via the same scheduler helper
        (which picks idle-halt when nobody submitted)."""
        self.state.phase = GamePhase.REVEAL
        for p in self.state.players.values():
            p.submitted = False
        await self.state.pause_game("admin_disconnected")
        with patch.object(self.state, "_schedule_song_end_auto_advance") as rearm:
            await self.state.resume_game()
        rearm.assert_called_once()

    @pytest.mark.asyncio
    async def test_resume_to_playing_does_not_rearm_reveal(self):
        """#1371 guard: a resume-to-PLAYING must NOT touch the REVEAL re-arm."""
        with patch.object(self.state, "_schedule_song_end_auto_advance") as rearm:
            await self.state.pause_game("admin_disconnected")  # from PLAYING
            await self.state.resume_game()
        rearm.assert_not_called()

    @pytest.mark.asyncio
    async def test_resume_to_reveal_respawns_open_vote_window(self):
        """#1371: a vote window open at pause with time left is re-opened for
        the remaining seconds — voting_open True again with a fresh deadline."""
        self.state.phase = GamePhase.REVEAL
        self.state._title_artist_voting_open = True
        self.state._title_artist_vote_deadline = self.state._now() + 20
        await self.state.pause_game("admin_disconnected")
        # pause snapshotted the window even though cancel may reset live flags.
        assert self.state._paused_vote_open is True
        with patch.object(self.state, "_title_artist_vote_window", new=AsyncMock()):
            await self.state.resume_game()
        assert self.state._title_artist_voting_open is True
        assert self.state._title_artist_vote_deadline is not None
        # Snapshot consumed.
        assert self.state._paused_vote_open is False

    @pytest.mark.asyncio
    async def test_resume_to_reveal_finalizes_elapsed_vote_window(self):
        """#1371: a vote window whose deadline elapsed during the pause is
        finalized on resume (no zombie 0s-window) instead of respawned."""
        self.state.phase = GamePhase.REVEAL
        self.state._title_artist_voting_open = True
        self.state._title_artist_vote_deadline = self.state._now() - 5  # elapsed
        await self.state.pause_game("admin_disconnected")
        self.state._finalize_title_artist_window = AsyncMock()
        await self.state.resume_game()
        self.state._finalize_title_artist_window.assert_awaited_once()

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


# ---------------------------------------------------------------------------
# end_round resilience (#816)
# ---------------------------------------------------------------------------


class TestEndRoundResilience:
    """#816: a scoring exception on one player must NOT block the round-end
    transition. Without the defensive try/except in `_end_round_unlocked`,
    `ScoringService.score_player_round` raising propagated up before line
    1573 (where `phase = GamePhase.REVEAL` is set) — leaving the UI frozen
    on the PLAYING screen with the timer at 0 and no broadcast.

    The transition + broadcast must happen even if scoring partially fails.
    """

    def setup_method(self):
        self.state = make_game_state()
        _create_fresh_game(self.state)
        self.state.add_player("Alice", MagicMock())
        self.state.add_player("Bob", MagicMock())
        self.state.start_game()
        # Set up a current song so end_round has correct_year context.
        self.state.current_song = {
            "title": "Test Song",
            "artist": "Test Artist",
            "year": 1990,
        }
        self.state.round_start_time = self.state._now()

    @pytest.mark.asyncio
    async def test_end_round_completes_when_scoring_one_player_throws(self):
        """If ScoringService.score_player_round throws on one player,
        the round STILL transitions to REVEAL and the broadcast still fires.
        """
        broadcast = AsyncMock()
        self.state.set_round_end_callback(broadcast)

        with patch(
            "custom_components.beatify.game.scoring.ScoringService.score_player_round",
            side_effect=AttributeError("simulated state corruption"),
        ):
            await self.state.end_round()

        # Phase MUST have transitioned despite the scoring exception.
        assert self.state.phase == GamePhase.REVEAL
        # Broadcast MUST have been called so the UI updates.
        broadcast.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_end_round_completes_when_apply_closest_wins_throws(self):
        """Closest-wins exception path: same defensive guarantee."""
        self.state.closest_wins_mode = True
        broadcast = AsyncMock()
        self.state.set_round_end_callback(broadcast)

        with patch(
            "custom_components.beatify.game.scoring.ScoringService.apply_closest_wins",
            side_effect=ValueError("simulated bad state"),
        ):
            await self.state.end_round()

        assert self.state.phase == GamePhase.REVEAL
        broadcast.assert_awaited_once()


# ---------------------------------------------------------------------------
# Timer-task self-cancellation (#1029)
# ---------------------------------------------------------------------------


class TestTimerExpiryNoSubmissions:
    """#1029: timer expiry with zero submitted guesses must transition to
    REVEAL and broadcast cleanly. The timer task is `_timer_task`, and
    end_round calls cancel_timer() — which cancels the running task itself.
    That self-cancel schedules CancelledError on the next real `await`,
    interrupting the broadcast at the end of end_round. The fix releases the
    timer-task handle before invoking end_round so cancel_timer() is a no-op.
    """

    def setup_method(self):
        self.state = make_game_state()
        _create_fresh_game(self.state)
        self.state.add_player("Alice", MagicMock())
        self.state.add_player("Bob", MagicMock())
        self.state.start_game()
        self.state.current_song = {
            "title": "Test Song",
            "artist": "Test Artist",
            "year": 1990,
        }
        self.state.round_start_time = self.state._now()
        # Players have NOT submitted — this is the #1029 scenario.

    @pytest.mark.asyncio
    async def test_timer_expiry_no_submissions_reaches_reveal_and_broadcasts(
        self,
    ):
        """Run _timer_countdown as a real asyncio task so cancel_timer()
        inside end_round targets the running task. Without the fix, the
        broadcast at the end of end_round is interrupted by CancelledError.
        """
        broadcast = AsyncMock()
        self.state.set_round_end_callback(broadcast)

        # Patch the inner sleep so the test finishes instantly.
        with patch.object(
            self.state._round_manager,
            "_timer_countdown",
            new=AsyncMock(return_value=None),
        ):
            timer_task = asyncio.create_task(self.state._timer_countdown(0.0))
            # Register as the round timer so cancel_timer() targets it
            # (this mirrors how RoundManager.initialize_round wires it up).
            self.state._round_manager._timer_task = timer_task
            await timer_task

        assert self.state.phase == GamePhase.REVEAL
        broadcast.assert_awaited_once()
        # Task must complete cleanly — no self-cancellation.
        assert not timer_task.cancelled()


class TestTitleArtistMode:
    """Title & Artist guessing mode wiring on GameState (Phase 3)."""

    def _make_game(self, *, title_artist_mode: bool):
        gs = make_game_state()
        gs.create_game(
            playlists=["test.json"],
            songs=make_songs(3),
            media_player="media_player.test",
            base_url="http://localhost:8123",
            title_artist_mode=title_artist_mode,
        )
        return gs

    def test_create_game_sets_title_artist_mode_flag(self):
        gs = self._make_game(title_artist_mode=True)
        assert gs.title_artist_mode is True

    def test_create_game_defaults_title_artist_mode_off(self):
        gs = make_game_state()
        gs.create_game(
            playlists=["test.json"],
            songs=make_songs(3),
            media_player="media_player.test",
            base_url="http://localhost:8123",
        )
        assert gs.title_artist_mode is False

    def test_init_round_creates_challenge_when_mode_on(self):
        gs = self._make_game(title_artist_mode=True)
        gs._challenge_manager.init_round(
            {"title": "Bohemian Rhapsody", "artist": "Queen"}
        )
        ch = gs.title_artist_challenge
        assert ch is not None
        assert ch.correct_title == "Bohemian Rhapsody"
        assert ch.correct_artist == "Queen"

    def test_submit_and_challenge_dict_hidden_in_playing(self):
        gs = self._make_game(title_artist_mode=True)
        gs._challenge_manager.init_round({"title": "Imagine", "artist": "John Lennon"})
        result = gs.submit_title_artist_guess("Alice", "Imagine", "John Lennon", 1.0)
        assert result["title_status"] == "exact"
        assert result["artist_status"] == "exact"
        # PLAYING: no truth leaked
        playing = gs.get_title_artist_challenge_dict(include_answer=False)
        assert playing == {"active": True}
        assert "correct_title" not in playing

    def test_challenge_dict_revealed_in_reveal(self):
        gs = self._make_game(title_artist_mode=True)
        gs._challenge_manager.init_round({"title": "Imagine", "artist": "John Lennon"})
        gs.submit_title_artist_guess("Alice", "Imagine", "Lennon", 1.0)
        reveal = gs.get_title_artist_challenge_dict(include_answer=True)
        assert reveal["correct_title"] == "Imagine"
        assert reveal["correct_artist"] == "John Lennon"
        assert reveal["voting_open"] is False
        # #1180 Phase 4: "Lennon" vs "John Lennon" is a genuine near-miss, now
        # surfaced via get_near_misses() instead of the Phase 2 placeholder [].
        assert reveal["near_misses"] == [
            {
                "id": "Alice:artist",
                "player": "Alice",
                "field": "artist",
                "guess": "Lennon",
                "votes_yes": 0,
                "votes_no": 0,
            }
        ]
        names = {r["player"] for r in reveal["results"]}
        assert "Alice" in names

    def test_challenge_dict_none_when_mode_off(self):
        gs = self._make_game(title_artist_mode=False)
        assert gs.get_title_artist_challenge_dict(include_answer=False) is None
        assert gs.get_title_artist_challenge_dict(include_answer=True) is None

    def test_early_reveal_waits_for_title_artist_guesses(self):
        gs = self._make_game(title_artist_mode=True)
        gs.phase = GamePhase.PLAYING
        gs._challenge_manager.init_round(
            {"title": "Yesterday", "artist": "The Beatles"}
        )
        gs.add_player("Alice", _make_ws_for_state())
        gs.add_player("Bob", _make_ws_for_state())
        # Year guesses in for both (the existing all_submitted gate)
        gs.players["Alice"].submit_guess(1965, 1.0)
        gs.players["Bob"].submit_guess(1965, 1.0)
        # Only Alice submitted her title/artist guess
        gs.players["Alice"].has_title_artist_guess = True
        assert gs.check_all_guesses_complete() is False
        # Now Bob too
        gs.players["Bob"].has_title_artist_guess = True
        assert gs.check_all_guesses_complete() is True


# ---------------------------------------------------------------------------
# Phase transition SSOT (_set_phase) — Issue #1273
# ---------------------------------------------------------------------------


class TestSetPhaseSSOT:
    """The single phase write-point centralises phase + its invariants (#1273)."""

    def test_sets_phase(self):
        state = make_game_state()
        state._set_phase(GamePhase.PLAYING)
        assert state.phase == GamePhase.PLAYING

    def test_entering_reveal_stamps_reveal_started_at(self):
        # Deterministic clock so the stamp is predictable (#1048).
        state = make_game_state(time_fn=lambda: 1000.0)
        state._set_phase(GamePhase.REVEAL)
        assert state.phase == GamePhase.REVEAL
        assert state.reveal_started_at == 1_000_000  # int(now * 1000)

    @pytest.mark.parametrize(
        "phase",
        [GamePhase.LOBBY, GamePhase.PLAYING, GamePhase.PAUSED, GamePhase.END],
    )
    def test_leaving_reveal_clears_reveal_started_at(self, phase):
        state = make_game_state(time_fn=lambda: 1000.0)
        state._set_phase(GamePhase.REVEAL)
        assert state.reveal_started_at is not None
        # Any non-REVEAL transition clears the stamp — the SSOT invariant.
        state._set_phase(phase)
        assert state.reveal_started_at is None

    def test_invariant_reveal_started_at_iff_reveal(self):
        # reveal_started_at is non-None *iff* phase is REVEAL, for every phase.
        state = make_game_state(time_fn=lambda: 1000.0)
        for phase in GamePhase:
            state._set_phase(phase)
            if phase is GamePhase.REVEAL:
                assert state.reveal_started_at is not None
            else:
                assert state.reveal_started_at is None

    def test_notifies_state_callbacks_by_default(self):
        state = make_game_state()
        calls: list[int] = []
        state.register_state_callback(lambda: calls.append(1))
        state._set_phase(GamePhase.PLAYING)
        assert calls == [1]

    def test_notify_false_skips_callbacks(self):
        state = make_game_state()
        calls: list[int] = []
        state.register_state_callback(lambda: calls.append(1))
        state._set_phase(GamePhase.PLAYING, notify=False)
        assert calls == []
        assert state.phase == GamePhase.PLAYING

    def test_restore_to_reveal_does_not_stamp_reveal_started_at(self):
        # #1273: a resume *restores* a saved phase and must NOT re-stamp the
        # REVEAL timestamp (that would restart the auto-advance countdown).
        state = make_game_state(time_fn=lambda: 1000.0)
        assert state.reveal_started_at is None
        state._set_phase(GamePhase.REVEAL, restore=True)
        assert state.phase == GamePhase.REVEAL
        # restore=True leaves reveal_started_at exactly as it was (None here).
        assert state.reveal_started_at is None

    def test_restore_leaves_existing_reveal_started_at_untouched(self):
        # A pre-existing stamp survives a restore unchanged (neither cleared
        # nor re-stamped) — restore touches only the phase + notify.
        state = make_game_state(time_fn=lambda: 1000.0)
        state.reveal_started_at = 555
        state._set_phase(GamePhase.LOBBY, restore=True)
        assert state.phase == GamePhase.LOBBY
        assert state.reveal_started_at == 555

    def test_restore_still_notifies_by_default(self):
        state = make_game_state()
        calls: list[int] = []
        state.register_state_callback(lambda: calls.append(1))
        state._set_phase(GamePhase.PLAYING, restore=True)
        assert calls == [1]

    # -- Transition-validity table (#1273 AC#1 consolidation) ----------------

    @pytest.mark.parametrize(
        ("src", "dst"),
        [
            # Forward edges from the table.
            (GamePhase.LOBBY, GamePhase.PLAYING),
            (GamePhase.PLAYING, GamePhase.REVEAL),
            (GamePhase.PLAYING, GamePhase.PAUSED),
            (GamePhase.REVEAL, GamePhase.PLAYING),
            (GamePhase.REVEAL, GamePhase.PAUSED),
            # Universal targets reachable from any phase (re-init / terminal).
            (GamePhase.PLAYING, GamePhase.LOBBY),
            (GamePhase.REVEAL, GamePhase.LOBBY),
            (GamePhase.PAUSED, GamePhase.LOBBY),
            (GamePhase.END, GamePhase.LOBBY),
            (GamePhase.PLAYING, GamePhase.END),
            (GamePhase.REVEAL, GamePhase.END),
            (GamePhase.PAUSED, GamePhase.END),
        ],
    )
    def test_valid_transition_does_not_warn(self, src, dst, caplog):
        state = make_game_state()
        state.phase = src
        with caplog.at_level("WARNING"):
            state._set_phase(dst)
        assert state.phase == dst
        assert "Unexpected phase transition" not in caplog.text

    def test_same_phase_write_does_not_warn(self, caplog):
        # The PLAYING->PLAYING next-round commit must not be flagged.
        state = make_game_state()
        state.phase = GamePhase.PLAYING
        with caplog.at_level("WARNING"):
            state._set_phase(GamePhase.PLAYING)
        assert "Unexpected phase transition" not in caplog.text

    def test_restore_never_warns(self, caplog):
        # A resume restores PAUSED->PLAYING/REVEAL — exempt from the check.
        for dst in (GamePhase.PLAYING, GamePhase.REVEAL):
            state = make_game_state()
            state.phase = GamePhase.PAUSED
            with caplog.at_level("WARNING"):
                state._set_phase(dst, restore=True)
            assert "Unexpected phase transition" not in caplog.text

    def test_unexpected_transition_warns_but_proceeds(self, caplog):
        # LOBBY->REVEAL is not a legal forward edge: it must WARN yet still
        # perform the write (observational, never blocking).
        state = make_game_state()
        state.phase = GamePhase.LOBBY
        with caplog.at_level("WARNING"):
            state._set_phase(GamePhase.REVEAL)
        assert "Unexpected phase transition" in caplog.text
        assert "LOBBY -> REVEAL" in caplog.text
        assert state.phase == GamePhase.REVEAL  # write still happened

    def test_paused_to_playing_without_restore_warns(self, caplog):
        # Resuming PAUSED->PLAYING is legal ONLY via restore=True; a plain
        # forward write of that edge is unexpected and should be flagged.
        state = make_game_state()
        state.phase = GamePhase.PAUSED
        with caplog.at_level("WARNING"):
            state._set_phase(GamePhase.PLAYING)
        assert "Unexpected phase transition" in caplog.text
        assert state.phase == GamePhase.PLAYING


# ---------------------------------------------------------------------------
# #1358: start_round must re-validate game identity / phase after awaits
# ---------------------------------------------------------------------------


class TestStartRoundGhostRoundGuard:
    """#1358: start_round parks in long awaits (verify_responsive, play_song —
    play_song waits a full Music Assistant timeout). If the game is torn down or
    replaced while parked, start_round must NOT resume and stamp PLAYING onto a
    dead/replaced game. The fix snapshots a monotonic _game_epoch at entry and
    re-validates epoch + phase after the playback await, stopping the playback
    it just started and bailing instead of committing the round.
    """

    def _setup(self) -> GameState:
        state = make_game_state()
        _create_fresh_game(state)
        state.add_player("Admin", MagicMock())
        state.add_player("Bob", MagicMock())
        state.set_admin("Admin")
        state.start_game()  # LOBBY -> PLAYING (needs MIN_PLAYERS)
        state.phase = GamePhase.PLAYING
        # music_assistant platform skips the verify_responsive branch so the
        # only await before _initialize_round is play_song.
        state.platform = "music_assistant"
        media = AsyncMock()
        media.is_available = MagicMock(return_value=True)
        state._media_player_service = media
        state._ensure_media_player_service = MagicMock()  # keep our mock service
        return state

    @pytest.mark.asyncio
    async def test_end_game_during_play_song_aborts_round(self):
        """end_game() completing while start_round is parked in play_song must
        not produce a ghost PLAYING round on a torn-down game."""
        state = self._setup()
        media = state._media_player_service

        async def end_game_then_succeed(_song):
            # Simulate the admin ending the game while play_song is parked.
            await state.end_game()
            return True

        media.play_song.side_effect = end_game_then_succeed

        result = await state.start_round()

        assert result is False
        # Game was torn down: must NOT be flipped to PLAYING.
        assert state.phase != GamePhase.PLAYING
        assert state.game_id is None
        assert state.round == 0  # _initialize_round never ran
        # The playback we kicked off must be stopped on the dead game.
        media.stop.assert_awaited()

    @pytest.mark.asyncio
    async def test_concurrent_pause_during_play_song_not_overwritten(self):
        """A concurrent pause_game (-> PAUSED) while parked in play_song must not
        be silently overwritten back to PLAYING by _initialize_round."""
        state = self._setup()
        media = state._media_player_service

        async def pause_then_succeed(_song):
            await state.pause_game("admin_disconnected")
            return True

        media.play_song.side_effect = pause_then_succeed

        result = await state.start_round()

        assert result is False
        assert state.phase == GamePhase.PAUSED
        assert state.round == 0

    @pytest.mark.asyncio
    async def test_rematch_during_play_song_aborts_round(self):
        """A rematch replacing the game identity mid-await must abort the round
        even though the new game is also a valid (LOBBY) game."""
        state = self._setup()
        media = state._media_player_service

        async def rematch_then_succeed(_song):
            state.rematch_game()  # new epoch, new game_id, phase LOBBY
            return True

        media.play_song.side_effect = rematch_then_succeed

        result = await state.start_round()

        assert result is False
        assert state.phase != GamePhase.PLAYING
        assert state.round == 0
        media.stop.assert_awaited()

    @pytest.mark.asyncio
    async def test_normal_round_still_starts(self):
        """Guard must be inert on the happy path: no teardown during play_song,
        the round commits to PLAYING as before."""
        state = self._setup()
        media = state._media_player_service
        media.play_song.return_value = True

        result = await state.start_round()

        assert result is True
        assert state.phase == GamePhase.PLAYING
        assert state.round == 1

    @pytest.mark.asyncio
    async def test_epoch_bumped_by_lifecycle_boundaries(self):
        """create_game / end_game / rematch_game each advance the epoch."""
        state = make_game_state()
        e0 = state._game_epoch
        _create_fresh_game(state)
        e1 = state._game_epoch
        assert e1 > e0

        state.add_player("Admin", MagicMock())
        state.set_admin("Admin")
        await state.end_game()
        e2 = state._game_epoch
        assert e2 > e1

        _create_fresh_game(state)
        state.add_player("Admin", MagicMock())
        state.set_admin("Admin")
        state.rematch_game()
        assert state._game_epoch > e2
