"""Tests for Beatify game state (custom_components/beatify/game/state.py)."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.beatify.const import (
    DOMAIN,
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
from custom_components.beatify.server.game_views import StartGameplayView
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


async def _drain_metadata_task(state: GameState) -> None:
    """Cancel and await the round manager's background metadata-fetch task.

    A real start_round happy-path spawns ``_fetch_metadata_async`` as a
    background task (RoundManager._metadata_task). In tests that drive a full
    start_round against an AsyncMock media player, that task awaits the mock's
    ``wait_for_metadata_update`` and is never otherwise joined — leaving the
    mock coroutine to be GC'd later as an "un-awaited coroutine", whose
    RuntimeWarning can leak into an unrelated test's ``recwarn`` (#1402 B2).
    Draining it here consumes the coroutine deterministically.
    """
    task = getattr(state._round_manager, "_metadata_task", None)
    if task is not None:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass


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

    @pytest.mark.asyncio
    async def test_end_game_restores_speaker_volume(self):
        """#1516: end_game hands the speaker back at its pre-game volume."""
        state = make_game_state()
        _create_fresh_game(state)
        media = MagicMock()
        media.set_volume = AsyncMock(return_value=True)
        media.restore_volume = AsyncMock(return_value=True)
        media.save_volume = MagicMock()
        state._media_player_service = media

        await state.end_game()

        media.restore_volume.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_set_volume_on_player_captures_pre_game_volume(self):
        """#1516: the first in-game volume change snapshots the original level."""
        state = make_game_state()
        media = MagicMock()
        media.set_volume = AsyncMock(return_value=True)
        media.save_volume = MagicMock()
        state._media_player_service = media

        await state.set_volume_on_player(0.8)

        media.save_volume.assert_called_once()
        media.set_volume.assert_awaited_once_with(0.8)


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
        state.get_player("Alice").submitted = True

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
        state.get_player("Alice").submitted = True

        payload = GameStateSerializer.serialize(state)
        assert payload["reveal_auto_advance"] == 0
        assert "reveal_started_at" not in payload

    def test_serializer_includes_relative_seconds_remaining_in_playing(self):
        """#1662: PLAYING payload carries the server-computed *relative*
        seconds_remaining (skew-immune) alongside the absolute deadline, so the
        client can anchor its countdown to its own clock."""
        from custom_components.beatify.game.serializers import GameStateSerializer

        now = 1_700_000_000.0
        state = make_game_state(time_fn=lambda: now)
        _create_fresh_game(state)
        state.phase = GamePhase.PLAYING
        state.deadline = int(now * 1000) + 30_000  # 30s out in server time
        state.add_player("Alice", MagicMock())

        payload = GameStateSerializer.serialize(state)
        assert payload["deadline"] == int(now * 1000) + 30_000
        assert payload["seconds_remaining"] == 30

    def test_serializer_seconds_remaining_floors_at_zero_when_expired(self):
        """#1662: an already-expired deadline serializes seconds_remaining == 0,
        never a negative value."""
        from custom_components.beatify.game.serializers import GameStateSerializer

        now = 1_700_000_000.0
        state = make_game_state(time_fn=lambda: now)
        _create_fresh_game(state)
        state.phase = GamePhase.PLAYING
        state.deadline = int(now * 1000) - 5_000  # 5s in the past
        state.add_player("Alice", MagicMock())

        payload = GameStateSerializer.serialize(state)
        assert payload["seconds_remaining"] == 0


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
        assert self.state.get_player("Alice") is not None

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
        self.state.get_player("Alice").connected = False
        # Reconnect with same name
        ok, err = self.state.add_player("Alice", ws2)
        assert ok is True
        assert err is None
        assert self.state.get_player("Alice").ws == ws2
        assert self.state.get_player("Alice").connected is True

    def test_player_name_trimmed(self):
        ok, err = self.state.add_player("  Bob  ", MagicMock())
        assert ok is True
        assert self.state.get_player("Bob") is not None


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
        self.state.get_player("Alice").submitted = True
        assert self.state.all_submitted() is False

    def test_all_submitted_returns_true(self):
        self.state.get_player("Alice").submitted = True
        self.state.get_player("Bob").submitted = True
        assert self.state.all_submitted() is True

    def test_disconnected_player_excluded(self):
        self.state.get_player("Bob").connected = False
        self.state.get_player("Alice").submitted = True
        assert self.state.all_submitted() is True

    def test_stale_connected_ghost_excluded(self):
        # #928: a player whose WebSocket is already closed but whose
        # `connected` flag has not been cleared must not block all-submitted.
        self.state.get_player("Bob").ws.closed = True
        self.state.get_player("Alice").submitted = True
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
        self.state.get_player("Alice").score = 50
        self.state.get_player("Bob").score = 80
        lb = self.state.get_leaderboard()
        assert lb[0]["name"] == "Bob"
        assert lb[1]["name"] == "Alice"

    def test_tied_scores_same_rank(self):
        self.state.add_player("Alice", MagicMock())
        self.state.add_player("Bob", MagicMock())
        self.state.get_player("Alice").score = 50
        self.state.get_player("Bob").score = 50
        lb = self.state.get_leaderboard()
        assert lb[0]["rank"] == 1
        assert lb[1]["rank"] == 1

    def test_rank_skips_after_tie(self):
        self.state.add_player("Alice", MagicMock())
        self.state.add_player("Bob", MagicMock())
        self.state.add_player("Carol", MagicMock())
        self.state.get_player("Alice").score = 100
        self.state.get_player("Bob").score = 50
        self.state.get_player("Carol").score = 50
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
        self.state.get_player("Alice").score = 40
        self.state.get_player("Alice").rounds_played = 1
        assert self.state.get_average_score() == 40

    def test_multiple_players(self):
        self.state.add_player("Alice", MagicMock())
        self.state.add_player("Bob", MagicMock())
        self.state.get_player("Alice").score = 40
        self.state.get_player("Alice").rounds_played = 1
        self.state.get_player("Bob").score = 60
        self.state.get_player("Bob").rounds_played = 1
        assert self.state.get_average_score() == 50

    def test_excludes_unscored_late_joiners(self):
        self.state.add_player("Alice", MagicMock())
        self.state.add_player("Bob", MagicMock())
        self.state.get_player("Alice").score = 40
        self.state.get_player("Alice").rounds_played = 1
        # Bob is a late joiner with no rounds played
        self.state.get_player("Bob").score = 40
        self.state.get_player("Bob").rounds_played = 0
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
        self.state.get_player("Alice").steal_available = True
        result = self.state.use_steal("Alice", "Bob")
        assert result["success"] is False
        assert result["error"] == ERR_TARGET_NOT_SUBMITTED

    def test_cannot_steal_self(self):
        self.state.get_player("Alice").steal_available = True
        result = self.state.use_steal("Alice", "Alice")
        assert result["success"] is False
        assert result["error"] == ERR_CANNOT_STEAL_SELF

    def test_successful_steal(self):
        self.state.get_player("Alice").steal_available = True
        self.state.get_player("Bob").submitted = True
        self.state.get_player("Bob").current_guess = 1990
        result = self.state.use_steal("Alice", "Bob")
        assert result["success"] is True
        assert result["year"] == 1990
        assert self.state.get_player("Alice").current_guess == 1990
        assert self.state.get_player("Alice").submitted is True
        assert self.state.get_player("Alice").steal_available is False
        assert self.state.get_player("Alice").steal_used is True

    def test_steal_wrong_phase(self):
        self.state.phase = GamePhase.REVEAL
        self.state.get_player("Alice").steal_available = True
        self.state.get_player("Bob").submitted = True
        self.state.get_player("Bob").current_guess = 1990
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

    def test_dedups_alt_equal_to_correct_artist(self):
        # #1402 B3: an alt_artist matching the correct artist (any case) must
        # never produce a duplicated correct answer in the options.
        song = {
            "artist": "Queen",
            "alt_artists": ["queen", "QUEEN", "David Bowie"],
        }
        options = build_artist_options(song)
        assert options is not None
        assert options.count("Queen") == 1
        assert "David Bowie" in options
        assert len(options) == 2

    def test_dedups_duplicate_alts_case_insensitively(self):
        # #1402 B3: repeated decoys collapse to a single option.
        song = {
            "artist": "Madonna",
            "alt_artists": ["Cher", "cher", "CHER"],
        }
        options = build_artist_options(song)
        assert options is not None
        assert options.count("Cher") == 1
        assert len(options) == 2

    def test_returns_none_when_only_decoy_is_the_correct_artist(self):
        # #1402 B3: if every alt collapses to the correct artist, no distinct
        # decoy remains -> the challenge would be trivial, so return None.
        song = {
            "artist": "U2",
            "alt_artists": ["u2", "U2"],
        }
        assert build_artist_options(song) is None


# ---------------------------------------------------------------------------
# GameState.finalize_game
# ---------------------------------------------------------------------------


class TestFinalizeGame:
    def setup_method(self):
        self.state = make_game_state()
        _create_fresh_game(self.state, songs=make_songs(5))
        self.state.add_player("Alice", MagicMock())
        self.state.add_player("Bob", MagicMock())
        self.state.get_player("Alice").score = 120
        self.state.get_player("Bob").score = 80
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
        self.state.get_player("Alice").score = 100
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
        self.state.get_player("Alice").score = 200
        self.state.phase = GamePhase.END
        self.state.rematch_game()
        assert self.state.get_player("Alice") is not None
        assert self.state.get_player("Alice").score == 0  # reset for new game

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

    @pytest.mark.asyncio
    async def test_end_round_does_not_strand_when_broadcast_raises_arbitrary(self):
        """#1575: an unexpected exception type from the broadcast callback (one
        outside the historic ``(ConnectionError, OSError, TypeError)`` tuple)
        must not escape `_end_round_unlocked`. The round has already
        transitioned to REVEAL by the time the callback fires, so a raising
        broadcast must be swallowed + logged rather than stranding the round.
        """
        broadcast = AsyncMock(side_effect=RuntimeError("simulated broadcast bug"))
        self.state.set_round_end_callback(broadcast)

        # Must NOT raise — the arbitrary exception is caught defensively.
        await self.state.end_round()

        # Phase still transitioned and the callback was actually invoked.
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
        gs.get_player("Alice").submit_guess(1965, 1.0)
        gs.get_player("Bob").submit_guess(1965, 1.0)
        # Only Alice submitted her title/artist guess
        gs.get_player("Alice").has_title_artist_guess = True
        assert gs.check_all_guesses_complete() is False
        # Now Bob too
        gs.get_player("Bob").has_title_artist_guess = True
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

        # The happy path spawns a background _fetch_metadata_async task that
        # awaits the AsyncMock media player's wait_for_metadata_update. Drain
        # it before the test ends so its (mock) coroutine is consumed — an
        # un-drained task is GC'd later as an un-awaited coroutine, whose
        # RuntimeWarning can leak into an unrelated test's recwarn (#1402 B2).
        await _drain_metadata_task(state)

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


# ---------------------------------------------------------------------------
# #1402 B2 — game-core / concurrency batch
# ---------------------------------------------------------------------------


class TestMetadataCoroNoLeak:
    """#1402 B2 finding 1: the album-art fetch coroutine must never be created
    and dropped un-awaited.

    Previously start_round eagerly created _fetch_metadata_async(uri) and
    handed the live coroutine to build_round_metadata, which dropped it
    (metadata_coro=None) on intro-splash-deferred rounds or when no media
    player is configured — leaking it (RuntimeWarning: coroutine never
    awaited). The fetch is now passed as a factory invoked only when needed.
    """

    def test_factory_not_invoked_when_deferred(self):
        state = make_game_state()
        called = {"n": 0}

        def factory():
            called["n"] += 1
            return AsyncMock()()  # a real coroutine, only if invoked

        # Defer for splash -> needs_fetch False -> factory must NOT run.
        meta = state._round_manager.build_round_metadata(
            {"title": "x"},
            "spotify:track:x",
            True,  # will_defer_for_splash
            MagicMock(),  # media player present
            factory,
        )
        assert called["n"] == 0
        assert meta["metadata_coro"] is None
        assert meta["metadata_pending"] is False

    def test_factory_not_invoked_without_media_player(self):
        state = make_game_state()
        called = {"n": 0}

        def factory():
            called["n"] += 1
            return AsyncMock()()

        meta = state._round_manager.build_round_metadata(
            {"title": "x"},
            "spotify:track:x",
            False,
            None,  # no media player
            factory,
        )
        assert called["n"] == 0
        assert meta["metadata_coro"] is None

    def test_factory_invoked_once_when_needed(self):
        state = make_game_state()
        sentinel = AsyncMock()
        coro = sentinel()
        called = {"n": 0}

        def factory():
            called["n"] += 1
            return coro

        meta = state._round_manager.build_round_metadata(
            {"title": "x"},
            "spotify:track:x",
            False,  # not deferred
            MagicMock(),  # media player present
            factory,
        )
        assert called["n"] == 1
        assert meta["metadata_coro"] is coro
        assert meta["metadata_pending"] is True
        # Close the coroutine we deliberately created so the test itself
        # doesn't trigger the very warning it guards against.
        coro.close()

    @pytest.mark.asyncio
    async def test_start_round_deferred_does_not_warn(self, recwarn):
        """End-to-end: a deferred (intro-splash) round leaves no un-awaited
        coroutine behind."""
        state = make_game_state()
        _create_fresh_game(state)
        state.add_player("Admin", MagicMock())
        state.set_admin("Admin")
        state.start_game()

        # Force the intro-splash deferral path and a present media player.
        state._media_player_service = AsyncMock()
        state._round_manager.prepare_intro_round = MagicMock(return_value=True)

        await state.start_round()

        leaked = [
            w
            for w in recwarn.list
            if issubclass(w.category, RuntimeWarning)
            and "never awaited" in str(w.message)
        ]
        assert not leaked, f"un-awaited coroutine leaked: {leaked}"


class TestEndGameSerializesWithRoundEnd:
    """#1402 B2 finding 2: end_game must serialize with an in-flight
    _end_round_unlocked so a torn-down game can't be flipped into REVEAL with
    stray tasks."""

    @pytest.mark.asyncio
    async def test_end_game_waits_for_in_flight_round_end(self):
        state = make_game_state()
        _create_fresh_game(state)
        state.add_player("Admin", MagicMock())
        state.set_admin("Admin")
        state.start_game()
        state.phase = GamePhase.PLAYING

        order = []

        # Hold _score_lock as if a round-end were mid-flight.
        async def fake_round_end():
            async with state._score_lock:
                order.append("round_end_start")
                await asyncio.sleep(0.05)
                order.append("round_end_finish")

        task = asyncio.create_task(fake_round_end())
        await asyncio.sleep(0)  # let it acquire the lock

        await state.end_game()
        order.append("end_game_done")
        await task

        # end_game's teardown (LOBBY) must land AFTER the round-end released
        # the lock — never interleaved.
        assert order == ["round_end_start", "round_end_finish", "end_game_done"]
        assert state.phase == GamePhase.LOBBY

    @pytest.mark.asyncio
    async def test_end_game_still_reaches_lobby(self):
        """Sanity: with no contention, end_game still tears down to LOBBY."""
        state = make_game_state()
        _create_fresh_game(state)
        state.add_player("Admin", MagicMock())
        state.set_admin("Admin")
        await state.end_game()
        assert state.phase == GamePhase.LOBBY
        assert state.game_id is None


class TestComputeWinners:
    """#1402 B2 finding 3: single winner/tie helper consumed by finalize_game
    and the END-state serializer."""

    def test_single_winner(self):
        state = make_game_state()
        state.add_player("Alice", MagicMock())
        state.add_player("Bob", MagicMock())
        state.get_player("Alice").score = 120
        state.get_player("Bob").score = 80
        winners, top = state.compute_winners()
        assert [w.name for w in winners] == ["Alice"]
        assert top == 120

    def test_tie(self):
        state = make_game_state()
        state.add_player("Alice", MagicMock())
        state.add_player("Bob", MagicMock())
        state.get_player("Alice").score = 100
        state.get_player("Bob").score = 100
        winners, top = state.compute_winners()
        assert {w.name for w in winners} == {"Alice", "Bob"}
        assert top == 100

    def test_no_players(self):
        state = make_game_state()
        assert state.compute_winners() == ([], 0)

    def test_finalize_and_serializer_agree(self):
        """The two consumers must report the same winner set (no drift)."""
        from custom_components.beatify.game.serializers import GameStateSerializer

        state = make_game_state()
        state.add_player("Alice", MagicMock())
        state.add_player("Bob", MagicMock())
        state.get_player("Alice").score = 100
        state.get_player("Bob").score = 100
        state.round = 3

        summary = state.finalize_game()
        end_state: dict = {}
        GameStateSerializer._add_end_state(state, end_state)

        assert summary["winner"] == "Alice, Bob"
        assert end_state["winner"]["name"] == "Alice, Bob"
        assert end_state["winner"]["is_tie"] is True
        assert summary["winner_score"] == end_state["winner"]["score"] == 100


class TestPauseSnapshotRace:
    """#1402 B2 finding 4: pause_game must flip to PAUSED before the media
    stop() await so an early-reveal interleaving during stop() cannot corrupt
    the pause snapshot."""

    @pytest.mark.asyncio
    async def test_phase_paused_before_media_stop(self):
        state = make_game_state()
        _setup_playing_game(state)

        observed = {}

        class Media:
            def __init__(self):
                self.stops = 0

            async def stop(self):
                # By the time we await stop(), the phase must already be PAUSED
                # so a concurrent early-reveal's `phase != PLAYING` guard bails.
                self.stops += 1
                observed["phase_during_stop"] = state.phase
                return True

        media = Media()
        state._media_player_service = media

        result = await state.pause_game("admin_disconnected")
        assert result is True
        assert observed["phase_during_stop"] == GamePhase.PAUSED
        # Snapshot still records PLAYING as the resume target.
        assert state._previous_phase == GamePhase.PLAYING
        assert state.phase == GamePhase.PAUSED
        assert media.stops == 1

    @pytest.mark.asyncio
    async def test_early_reveal_during_stop_is_noop(self):
        """An early-reveal racing the pause's stop() await sees PAUSED and bails,
        so the pause snapshot (_previous_phase=PLAYING) stays intact."""
        state = make_game_state()
        _setup_playing_game(state)

        class Media:
            async def stop(self):
                # Simulate an early-reveal attempt landing mid-stop.
                await state._end_round_unlocked()
                return True

        state._media_player_service = Media()

        await state.pause_game("admin_disconnected")

        # _end_round_unlocked must have no-op'd (guard: phase != PLAYING),
        # leaving the game cleanly PAUSED with a PLAYING resume target.
        assert state.phase == GamePhase.PAUSED
        assert state._previous_phase == GamePhase.PLAYING


class TestConfigurePartyLightsPreservesStates:
    """#1402 B2 finding 5: a reconfigure must carry the genuine pre-party light
    states forward, not lose them by replacing the service outright."""

    @pytest.mark.asyncio
    async def test_reconfigure_inherits_prior_saved_states(self):
        state = make_game_state()
        state._hass = MagicMock()

        snap_calls = {"n": 0}

        class PriorService:
            def snapshot_saved_states(self):
                snap_calls["n"] += 1
                return {"light.a": {"state": "on", "brightness": 42}}

        state._party_lights = PriorService()

        captured = {}

        class FakeService:
            def __init__(self, hass):
                self.hass = hass

            async def start(self, *args, **kwargs):
                captured["inherited"] = kwargs.get("inherited_states")

        with patch(
            "custom_components.beatify.services.lights.PartyLightsService",
            FakeService,
        ):
            await state.configure_party_lights(["light.a"], "medium")

        assert snap_calls["n"] == 1
        assert captured["inherited"] == {"light.a": {"state": "on", "brightness": 42}}

    @pytest.mark.asyncio
    async def test_first_configure_passes_no_inherited_states(self):
        state = make_game_state()
        state._hass = MagicMock()
        state._party_lights = None

        captured = {}

        class FakeService:
            def __init__(self, hass):
                pass

            async def start(self, *args, **kwargs):
                captured["inherited"] = kwargs.get("inherited_states")

        with patch(
            "custom_components.beatify.services.lights.PartyLightsService",
            FakeService,
        ):
            await state.configure_party_lights(["light.a"], "medium")

        assert captured["inherited"] is None


# ---------------------------------------------------------------------------
# Sudden Death mode (Issue #827)
# ---------------------------------------------------------------------------


def _add_live_player(state: GameState, name: str) -> None:
    """Add a player whose WebSocket reads as genuinely connected (is_active)."""
    ws = AsyncMock()
    ws.closed = False
    state.add_player(name, ws)
    state.get_player(name).connected = True


class TestSuddenDeathElimination:
    """Core elimination logic for Sudden Death (#827)."""

    def setup_method(self):
        self.state = make_game_state()
        _create_fresh_game(self.state, sudden_death_mode=True)
        for n in ("Alice", "Bob", "Carol", "Dave"):
            _add_live_player(self.state, n)

    def _set_round_scores(self, scores: dict[str, int]) -> None:
        for name, sc in scores.items():
            self.state.get_player(name).round_score = sc

    def test_sudden_death_skips_round_1(self):
        """Round 1 never eliminates anyone."""
        self.state.round = 1
        self._set_round_scores({"Alice": 0, "Bob": 5, "Carol": 9, "Dave": 3})
        eliminated = self.state._apply_sudden_death_elimination()
        assert eliminated == []
        assert all(not p.eliminated for p in self.state.players.values())

    def test_sudden_death_eliminates_lowest_round_score(self):
        """From round 2 on, the lowest *round* score is eliminated."""
        self.state.round = 2
        self._set_round_scores({"Alice": 8, "Bob": 2, "Carol": 9, "Dave": 5})
        eliminated = self.state._apply_sudden_death_elimination()
        assert eliminated == ["Bob"]
        assert self.state.get_player("Bob").eliminated is True
        assert self.state.get_player("Bob").eliminated_round == 2
        # Everyone else survives.
        assert not self.state.get_player("Alice").eliminated
        assert not self.state.get_player("Carol").eliminated
        assert not self.state.get_player("Dave").eliminated

    def test_sudden_death_uses_round_delta_not_cumulative(self):
        """A high cumulative leader with the worst *round* is the one cut."""
        self.state.round = 3
        self.state.get_player("Alice").score = 100  # cumulative leader
        self.state.get_player("Bob").score = 5
        self._set_round_scores({"Alice": 0, "Bob": 7, "Carol": 4, "Dave": 6})
        eliminated = self.state._apply_sudden_death_elimination()
        assert eliminated == ["Alice"]

    def test_sudden_death_tie_break_uses_last_submission(self):
        """Tie for last → the slowest (latest) submitter is eliminated."""
        self.state.round = 2
        self._set_round_scores({"Alice": 1, "Bob": 1, "Carol": 9, "Dave": 9})
        self.state.get_player("Alice").submission_time = 10.0  # earlier = faster
        self.state.get_player("Bob").submission_time = 25.0  # later = slower → out
        eliminated = self.state._apply_sudden_death_elimination()
        assert eliminated == ["Bob"]
        assert self.state.get_player("Alice").eliminated is False

    def test_sudden_death_non_submitter_is_slowest(self):
        """A non-submitter (submission_time None) loses a last-place tie."""
        self.state.round = 2
        self._set_round_scores({"Alice": 0, "Bob": 0, "Carol": 5, "Dave": 5})
        self.state.get_player("Alice").submission_time = 12.0
        self.state.get_player("Bob").submission_time = None  # never submitted → out
        eliminated = self.state._apply_sudden_death_elimination()
        assert eliminated == ["Bob"]

    def test_sudden_death_no_elimination_with_one_survivor(self):
        """Never eliminate the last player standing."""
        self.state.round = 5
        for n in ("Bob", "Carol", "Dave"):
            self.state.get_player(n).eliminated = True
        self._set_round_scores({"Alice": 0})
        eliminated = self.state._apply_sudden_death_elimination()
        assert eliminated == []
        assert self.state.get_player("Alice").eliminated is False

    def test_sudden_death_disabled_no_elimination(self):
        """With the mode off, scoring never eliminates anyone."""
        self.state.sudden_death_mode = False
        self.state.round = 4
        self._set_round_scores({"Alice": 0, "Bob": 1, "Carol": 2, "Dave": 3})
        eliminated = self.state._apply_sudden_death_elimination()
        assert eliminated == []

    def test_already_eliminated_excluded_from_next_cut(self):
        """An eliminated player is not re-eliminated and not considered."""
        self.state.round = 3
        self.state.get_player("Bob").eliminated = True
        self.state.get_player("Bob").eliminated_round = 2
        self._set_round_scores({"Alice": 9, "Bob": -99, "Carol": 1, "Dave": 8})
        eliminated = self.state._apply_sudden_death_elimination()
        # Bob already out and ignored; Carol is the lowest live score.
        assert eliminated == ["Carol"]
        assert self.state.get_player("Bob").eliminated_round == 2

    def test_sudden_death_multi_tie_eliminates_exactly_one(self):
        """3+ players tied for last (all non-submitters) → exactly ONE is cut.

        Guards the ``max()`` single-winner behaviour: a mass tie must not wipe
        out the whole tied group in one round.
        """
        self.state.round = 4
        # Alice, Bob, Carol all tie at the minimum with no submission_time;
        # only Dave is clearly ahead.
        self._set_round_scores({"Alice": 0, "Bob": 0, "Carol": 0, "Dave": 7})
        for n in ("Alice", "Bob", "Carol"):
            self.state.get_player(n).submission_time = None
        eliminated = self.state._apply_sudden_death_elimination()
        assert len(eliminated) == 1
        assert sum(p.eliminated for p in self.state.players.values()) == 1
        assert not self.state.get_player("Dave").eliminated

    def test_sudden_death_multi_tie_is_deterministic(self):
        """The same tied board cuts the same player across independent games."""
        outcomes = set()
        for _ in range(2):
            state = make_game_state()
            _create_fresh_game(state, sudden_death_mode=True)
            for n in ("Alice", "Bob", "Carol", "Dave"):
                _add_live_player(state, n)
            state.round = 4
            for n in ("Alice", "Bob", "Carol"):
                state.get_player(n).round_score = 0
                state.get_player(n).submission_time = None
            state.get_player("Dave").round_score = 7
            outcomes.add(tuple(state._apply_sudden_death_elimination()))
        assert len(outcomes) == 1  # identical input → identical single cut


class TestSuddenDeathSubmissionTracker:
    """all_submitted ignores eliminated players (#827)."""

    def test_all_submitted_ignores_eliminated(self):
        state = make_game_state()
        _create_fresh_game(state, sudden_death_mode=True)
        for n in ("Alice", "Bob", "Carol"):
            _add_live_player(state, n)
        # Carol is out and will never submit again.
        state.get_player("Carol").eliminated = True
        state.get_player("Alice").submitted = True
        state.get_player("Bob").submitted = True
        state.get_player("Carol").submitted = False
        assert state.all_submitted() is True


class TestSuddenDeathAutoEnd:
    """start_round ends the game when one player remains (#827)."""

    @pytest.mark.asyncio
    async def test_sudden_death_auto_ends_at_one_remaining(self):
        state = make_game_state()
        _create_fresh_game(state, sudden_death_mode=True)
        for n in ("Alice", "Bob", "Carol"):
            _add_live_player(state, n)
        state.get_player("Bob").eliminated = True
        state.get_player("Carol").eliminated = True
        state.round = 4
        state.phase = GamePhase.PLAYING
        started = await state.start_round()
        assert started is False
        assert state.phase == GamePhase.END

    @pytest.mark.asyncio
    async def test_no_auto_end_when_two_remain(self):
        """Two survivors → start_round must NOT end the game on the guard."""
        state = make_game_state()
        _create_fresh_game(state, sudden_death_mode=True)
        for n in ("Alice", "Bob", "Carol"):
            _add_live_player(state, n)
        state.get_player("Carol").eliminated = True
        state.round = 3
        state.phase = GamePhase.PLAYING
        # Stub playback so start_round can proceed past the guard without media.
        with patch.object(state, "_ensure_media_player_service"):
            state._media_player_service = None
            await state.start_round()
        # The auto-end guard did not fire (phase is not END from the guard).
        assert state.phase != GamePhase.END


class TestSuddenDeathPersistence:
    """eliminated state survives a round but resets for a new game (#827)."""

    def test_reset_round_preserves_eliminated(self):
        state = make_game_state()
        _create_fresh_game(state, sudden_death_mode=True)
        _add_live_player(state, "Alice")
        p = state.get_player("Alice")
        p.eliminated = True
        p.eliminated_round = 2
        p.reset_round()
        assert p.eliminated is True
        assert p.eliminated_round == 2

    def test_reset_for_new_game_clears_eliminated(self):
        state = make_game_state()
        _create_fresh_game(state, sudden_death_mode=True)
        _add_live_player(state, "Alice")
        p = state.get_player("Alice")
        p.eliminated = True
        p.eliminated_round = 2
        p.reset_for_new_game()
        assert p.eliminated is False
        assert p.eliminated_round is None

    @pytest.mark.asyncio
    async def test_pause_resume_preserves_eliminated(self):
        state = make_game_state()
        _create_fresh_game(state, sudden_death_mode=True)
        for n in ("Alice", "Bob", "Carol"):
            _add_live_player(state, n)
        state.phase = GamePhase.PLAYING
        state.get_player("Carol").eliminated = True
        state.get_player("Carol").eliminated_round = 2
        await state.pause_game("test_pause")
        await state.resume_game()
        assert state.get_player("Carol").eliminated is True
        assert state.get_player("Carol").eliminated_round == 2


class TestSuddenDeathLiveToggle:
    """The reveal-screen live toggle (#827)."""

    def test_set_sudden_death_toggles_flag(self):
        state = make_game_state()
        _create_fresh_game(state)  # default off
        assert state.sudden_death_mode is False
        assert state.set_sudden_death(True) is True
        assert state.sudden_death_mode is True
        assert state.set_sudden_death(False) is False
        assert state.sudden_death_mode is False

    def test_enable_mid_game_arms_eliminations(self):
        """Turning the mode ON mid-game arms cuts; while off, none happen.

        Models the documented semantics: with the mode off a finished round
        eliminates nobody (the result stands); once the host flips it on, the
        next scoring pass starts cutting.
        """
        state = make_game_state()
        _create_fresh_game(state)  # starts OFF
        for n in ("Alice", "Bob", "Carol"):
            _add_live_player(state, n)
        state.round = 3
        for name, sc in {"Alice": 2, "Bob": 9, "Carol": 7}.items():
            state.get_player(name).round_score = sc

        # Off: this round's results stand, nobody is cut.
        assert state._apply_sudden_death_elimination() == []
        assert all(not p.eliminated for p in state.players.values())

        # Host flips it on from the reveal screen → next pass arms the cut.
        state.set_sudden_death(True)
        assert state._apply_sudden_death_elimination() == ["Alice"]

    def test_disable_stops_further_cuts_but_keeps_eliminated(self):
        """Turning the mode OFF stops new cuts; already-out players stay out."""
        state = make_game_state()
        _create_fresh_game(state, sudden_death_mode=True)
        for n in ("Alice", "Bob", "Carol"):
            _add_live_player(state, n)
        state.round = 2
        for name, sc in {"Alice": 1, "Bob": 8, "Carol": 6}.items():
            state.get_player(name).round_score = sc
        assert state._apply_sudden_death_elimination() == ["Alice"]

        # Host turns it off — no further eliminations next round...
        state.set_sudden_death(False)
        state.round = 3
        for name, sc in {"Bob": 2, "Carol": 9}.items():
            state.get_player(name).round_score = sc
        assert state._apply_sudden_death_elimination() == []
        # ...but Alice, already eliminated, stays out.
        assert state.get_player("Alice").eliminated is True


class TestSuddenDeathStartFloor:
    """The >=3-connected-player floor enforced in StartGameplayView (#827)."""

    def _hass(self, state: GameState) -> MagicMock:
        hass = MagicMock()
        hass.data = {DOMAIN: {"game": state}}  # no ws_handler
        return hass

    @patch(
        "custom_components.beatify.server.game_views.is_authorized_http",
        return_value=True,
    )
    async def test_below_floor_auto_disables_sudden_death(self, _auth):
        """Starting gameplay with <3 connected players turns the mode off."""
        state = make_game_state()
        _create_fresh_game(state, sudden_death_mode=True)  # phase = LOBBY
        for n in ("Alice", "Bob"):  # only 2 connected
            _add_live_player(state, n)
        # Skip the real first-round machinery; we only assert the floor logic.
        state.start_round = AsyncMock(return_value=True)

        view = StartGameplayView(self._hass(state))
        resp = await view.post(MagicMock())
        body = json.loads(resp.body)

        assert resp.status == 200
        assert state.sudden_death_mode is False
        assert body.get("sudden_death_disabled") is True
        assert body.get("warnings")

    @patch(
        "custom_components.beatify.server.game_views.is_authorized_http",
        return_value=True,
    )
    async def test_at_floor_keeps_sudden_death(self, _auth):
        """With 3 connected players the mode survives the start, no warning."""
        state = make_game_state()
        _create_fresh_game(state, sudden_death_mode=True)
        for n in ("Alice", "Bob", "Carol"):  # exactly 3 connected
            _add_live_player(state, n)
        state.start_round = AsyncMock(return_value=True)

        view = StartGameplayView(self._hass(state))
        resp = await view.post(MagicMock())
        body = json.loads(resp.body)

        assert resp.status == 200
        assert state.sudden_death_mode is True
        assert "sudden_death_disabled" not in body
        assert "warnings" not in body


class TestSuddenDeathSuperlative:
    """Last One Standing superlative (#827)."""

    def test_last_one_standing_awarded_to_survivor(self):
        state = make_game_state()
        _create_fresh_game(state, sudden_death_mode=True)
        for n in ("Alice", "Bob", "Carol"):
            _add_live_player(state, n)
        state.get_player("Bob").eliminated = True
        state.get_player("Carol").eliminated = True
        state.round = 4
        awards = state.calculate_superlatives()
        last = [a for a in awards if a["id"] == "last_one_standing"]
        assert len(last) == 1
        assert last[0]["player_name"] == "Alice"
        assert last[0]["value"] == 2  # two eliminated

    def test_no_last_one_standing_when_mode_off(self):
        state = make_game_state()
        _create_fresh_game(state)  # sudden death off
        for n in ("Alice", "Bob"):
            _add_live_player(state, n)
        state.round = 4
        awards = state.calculate_superlatives()
        assert not any(a["id"] == "last_one_standing" for a in awards)


class TestSuddenDeathWinner:
    """Survivor is the winner + finish order reflects survival (#827 follow-ups)."""

    def _game(self):
        state = make_game_state()
        _create_fresh_game(state, sudden_death_mode=True)
        for n in ("Alice", "Bob", "Carol"):
            _add_live_player(state, n)
        return state

    def test_survivor_wins_despite_lower_score(self):
        """The last one standing wins even with a lower cumulative score."""
        state = self._game()
        state.get_player("Alice").score = 10  # survivor, fewer points
        state.get_player("Bob").score = 99
        state.get_player("Bob").eliminated = True
        state.get_player("Bob").eliminated_round = 3
        state.get_player("Carol").score = 50
        state.get_player("Carol").eliminated = True
        state.get_player("Carol").eliminated_round = 2
        winners, top = state.compute_winners()
        assert [w.name for w in winners] == ["Alice"]
        assert top == 10

    def test_winner_falls_back_to_score_without_elimination(self):
        """No eliminations yet → normal top-score winner."""
        state = self._game()
        state.get_player("Alice").score = 5
        state.get_player("Bob").score = 20
        state.get_player("Carol").score = 12
        winners, top = state.compute_winners()
        assert [w.name for w in winners] == ["Bob"]
        assert top == 20

    def test_final_leaderboard_orders_by_survival(self):
        """Survivor 1st, then reverse elimination order — not by score."""
        state = self._game()
        state.get_player("Alice").score = 10  # survivor
        state.get_player("Bob").score = 99
        state.get_player("Bob").eliminated = True
        state.get_player("Bob").eliminated_round = 2  # out earliest → last place
        state.get_player("Carol").score = 40
        state.get_player("Carol").eliminated = True
        state.get_player("Carol").eliminated_round = 3  # out latest → runner-up
        lb = state.get_final_leaderboard()
        assert [e["name"] for e in lb] == ["Alice", "Carol", "Bob"]
        assert [e["rank"] for e in lb] == [1, 2, 3]

    def test_final_leaderboard_score_order_when_mode_off(self):
        """Non-Sudden-Death game keeps the score-based final order."""
        state = make_game_state()
        _create_fresh_game(state)  # mode off
        for n in ("Alice", "Bob"):
            _add_live_player(state, n)
        state.get_player("Alice").score = 3
        state.get_player("Bob").score = 30
        lb = state.get_final_leaderboard()
        assert [e["name"] for e in lb] == ["Bob", "Alice"]
