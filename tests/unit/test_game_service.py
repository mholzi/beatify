"""Tests for GameService facade (Issues #603, #609)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.beatify.const import DOMAIN
from custom_components.beatify.game.service import GameService


@pytest.fixture
def hass():
    """Minimal hass mock."""
    h = MagicMock()
    h.data = {DOMAIN: {}}
    return h


@pytest.fixture
def game_state():
    """Minimal GameState mock."""
    gs = MagicMock()
    gs.difficulty = "normal"
    gs.last_round = False
    gs.round = 3
    gs.song_stopped = False
    gs.current_time.return_value = 1000.0
    gs.finalize_game.return_value = {"winner": "Alice", "rounds": 3}
    gs.start_round = AsyncMock(return_value=True)
    gs.end_round = AsyncMock()
    gs.advance_to_end = AsyncMock()
    gs.end_game = AsyncMock()
    gs.stop_media = AsyncMock()
    gs.trigger_early_reveal_if_complete = AsyncMock()
    gs.create_game.return_value = {"game_id": "abc", "phase": "LOBBY"}
    gs.submit_artist_guess.return_value = {"correct": True, "first": True}
    gs.submit_movie_guess.return_value = {"correct": False, "already_guessed": False}
    gs.get_player.return_value = MagicMock()
    gs.rematch_game.return_value = None
    return gs


@pytest.fixture
def service(hass, game_state):
    return GameService(hass, game_state)


class TestGameServiceProperties:
    def test_state_returns_game_state(self, service, game_state):
        assert service.state is game_state

    def test_stats_service_returns_from_hass_data(self, service, hass):
        mock_stats = MagicMock()
        hass.data[DOMAIN]["stats"] = mock_stats
        assert service.stats_service is mock_stats

    def test_stats_service_returns_none_when_missing(self, service):
        assert service.stats_service is None


class TestGameLifecycle:
    @pytest.mark.asyncio
    async def test_create_game(self, service, game_state):
        result = await service.create_game(
            playlists=["p.json"], songs=[], media_player="mp", base_url="http://x"
        )
        game_state.create_game.assert_called_once()
        assert result["game_id"] == "abc"

    @pytest.mark.asyncio
    async def test_start_round(self, service, game_state):
        result = await service.start_round()
        game_state.start_round.assert_awaited_once()
        assert result is True

    @pytest.mark.asyncio
    async def test_end_round(self, service, game_state):
        await service.end_round()
        game_state.end_round.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_end_game(self, service, game_state):
        await service.end_game()
        game_state.end_game.assert_awaited_once()

    def test_rematch_game(self, service, game_state):
        service.rematch_game()
        game_state.rematch_game.assert_called_once()

    @pytest.mark.asyncio
    async def test_advance_to_end(self, service, game_state):
        await service.advance_to_end()
        game_state.advance_to_end.assert_awaited_once()


class TestFinalizeAndRecordStats:
    @pytest.mark.asyncio
    async def test_records_stats_when_service_available(
        self, service, hass, game_state
    ):
        mock_stats = MagicMock()
        mock_stats.record_game = AsyncMock()
        hass.data[DOMAIN]["stats"] = mock_stats

        await service.finalize_and_record_stats()

        game_state.finalize_game.assert_called_once()
        mock_stats.record_game.assert_awaited_once_with(
            {"winner": "Alice", "rounds": 3}, difficulty="normal"
        )

    @pytest.mark.asyncio
    async def test_skips_when_no_stats_service(self, service, game_state):
        await service.finalize_and_record_stats()
        game_state.finalize_game.assert_not_called()


class TestNextRound:
    @pytest.mark.asyncio
    async def test_starts_next_round(self, service, game_state):
        result = await service.next_round()
        assert result is True
        game_state.start_round.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ends_game_on_last_round(self, service, game_state, hass):
        game_state.last_round = True
        mock_stats = MagicMock()
        mock_stats.record_game = AsyncMock()
        hass.data[DOMAIN]["stats"] = mock_stats

        result = await service.next_round()
        assert result is False
        game_state.advance_to_end.assert_awaited_once()
        mock_stats.record_game.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_ends_game_when_no_songs(self, service, game_state):
        game_state.start_round = AsyncMock(return_value=False)
        result = await service.next_round()
        assert result is False
        game_state.advance_to_end.assert_awaited_once()


class TestStopSong:
    @pytest.mark.asyncio
    async def test_stop_song(self, service, game_state):
        await service.stop_song()
        game_state.stop_media.assert_awaited_once()
        assert game_state.song_stopped is True


class TestPlayerOperations:
    def test_submit_guess(self, service, game_state):
        player = MagicMock()
        game_state.get_player.return_value = player

        service.submit_guess("Alice", 1985, bet=True)

        game_state.get_player.assert_called_with("Alice")
        assert player.bet is True
        player.submit_guess.assert_called_once_with(1985, 1000.0)

    def test_submit_artist_guess(self, service, game_state):
        result = service.submit_artist_guess("Alice", "Beatles")
        game_state.submit_artist_guess.assert_called_once_with(
            "Alice", "Beatles", 1000.0
        )
        assert result["correct"] is True

    def test_submit_movie_guess(self, service, game_state):
        result = service.submit_movie_guess("Alice", "Titanic")
        game_state.submit_movie_guess.assert_called_once_with(
            "Alice", "Titanic", 1000.0
        )
        assert result["correct"] is False

    @pytest.mark.asyncio
    async def test_trigger_early_reveal(self, service, game_state):
        await service.trigger_early_reveal_if_complete()
        game_state.trigger_early_reveal_if_complete.assert_awaited_once()
