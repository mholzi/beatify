"""
Unit Tests: Timer Expiry and Auto-Advance (Story 4.5)

Tests the round timer expiry mechanics:
- Timer task triggers end_round at deadline
- Non-submitters get 0 points and streak broken
- Timer task is cancelled on early advance
- Phase transitions to REVEAL on timer expiry
- Round end callback is invoked

Story 4.5 - AC: #1, #2, #3
"""

from __future__ import annotations

import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

# Mock homeassistant before importing beatify modules
sys.modules["homeassistant"] = MagicMock()
sys.modules["homeassistant.core"] = MagicMock()
sys.modules["homeassistant.components"] = MagicMock()
sys.modules["homeassistant.components.http"] = MagicMock()

from custom_components.beatify.game.state import GamePhase, GameState


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.states = MagicMock()
    return hass


@pytest.fixture
def game_with_songs():
    """Create a game state with songs loaded."""
    state = GameState(time_fn=lambda: 1000.0)
    songs = [
        {"year": 1985, "uri": "spotify:track:1", "fun_fact": "Fact 1"},
        {"year": 1990, "uri": "spotify:track:2", "fun_fact": "Fact 2"},
        {"year": 1995, "uri": "spotify:track:3", "fun_fact": "Fact 3"},
    ]
    state.create_game(
        playlists=["playlist1.json"],
        songs=songs,
        media_player="media_player.test",
        base_url="http://test.local:8123",
    )
    return state


@pytest.mark.unit
class TestTimerTaskCreation:
    """Tests for timer task creation during start_round."""

    @pytest.mark.asyncio
    async def test_start_round_creates_timer_task(self, game_with_songs, mock_hass):
        """start_round creates a timer task."""
        state = game_with_songs

        await state.start_round(mock_hass)

        assert state._timer_task is not None
        assert isinstance(state._timer_task, asyncio.Task)

        # Clean up the timer task
        state.cancel_timer()

    @pytest.mark.asyncio
    async def test_timer_task_is_running_after_start(self, game_with_songs, mock_hass):
        """Timer task should be running (not done) after start_round."""
        state = game_with_songs

        await state.start_round(mock_hass)

        assert state._timer_task is not None
        assert not state._timer_task.done()

        # Clean up
        state.cancel_timer()


@pytest.mark.unit
class TestEndRound:
    """Tests for end_round method."""

    @pytest.mark.asyncio
    async def test_end_round_transitions_to_reveal(self, game_with_songs, mock_hass):
        """end_round transitions phase from PLAYING to REVEAL."""
        state = game_with_songs

        await state.start_round(mock_hass)
        assert state.phase == GamePhase.PLAYING

        await state.end_round()

        assert state.phase == GamePhase.REVEAL

    @pytest.mark.asyncio
    async def test_end_round_cancels_timer(self, game_with_songs, mock_hass):
        """end_round cancels any running timer task."""
        state = game_with_songs

        await state.start_round(mock_hass)
        assert state._timer_task is not None

        await state.end_round()

        # Timer task should be None or cancelled
        assert state._timer_task is None or state._timer_task.cancelled()

    @pytest.mark.asyncio
    async def test_end_round_invokes_callback(self, game_with_songs, mock_hass):
        """end_round invokes the round end callback."""
        state = game_with_songs
        callback = AsyncMock()
        state.set_round_end_callback(callback)

        await state.start_round(mock_hass)
        await state.end_round()

        callback.assert_called_once()


@pytest.mark.unit
class TestNonSubmitters:
    """Tests for non-submitter handling when round ends."""

    @pytest.mark.asyncio
    async def test_non_submitters_get_zero_round_score(self, game_with_songs, mock_hass):
        """Players who didn't submit get round_score = 0."""
        state = game_with_songs

        # Add player who doesn't submit
        mock_ws = MagicMock()
        state.add_player("TestPlayer", mock_ws)

        await state.start_round(mock_hass)

        # Player hasn't submitted
        assert state.players["TestPlayer"].submitted is False

        await state.end_round()

        assert state.players["TestPlayer"].round_score == 0

    @pytest.mark.asyncio
    async def test_non_submitters_streak_broken(self, game_with_songs, mock_hass):
        """Players who didn't submit have their streak reset to 0."""
        state = game_with_songs

        # Add player with an existing streak
        mock_ws = MagicMock()
        state.add_player("TestPlayer", mock_ws)
        state.players["TestPlayer"].streak = 5

        await state.start_round(mock_hass)
        await state.end_round()

        assert state.players["TestPlayer"].streak == 0

    @pytest.mark.asyncio
    async def test_non_submitters_marked_as_missed(self, game_with_songs, mock_hass):
        """Players who didn't submit are marked with missed_round=True."""
        state = game_with_songs

        mock_ws = MagicMock()
        state.add_player("TestPlayer", mock_ws)

        await state.start_round(mock_hass)
        await state.end_round()

        assert state.players["TestPlayer"].missed_round is True

    @pytest.mark.asyncio
    async def test_submitters_not_marked_as_missed(self, game_with_songs, mock_hass):
        """Players who submitted are marked with missed_round=False."""
        state = game_with_songs

        mock_ws = MagicMock()
        state.add_player("TestPlayer", mock_ws)

        await state.start_round(mock_hass)

        # Simulate submission using proper method
        state.players["TestPlayer"].submit_guess(year=1985, timestamp=1000.0)

        await state.end_round()

        assert state.players["TestPlayer"].missed_round is False


@pytest.mark.unit
class TestCancelTimer:
    """Tests for cancel_timer method."""

    @pytest.mark.asyncio
    async def test_cancel_timer_cancels_task(self, game_with_songs, mock_hass):
        """cancel_timer cancels the running timer task."""
        state = game_with_songs

        await state.start_round(mock_hass)
        timer_task = state._timer_task
        assert timer_task is not None
        assert not timer_task.done()

        state.cancel_timer()

        assert state._timer_task is None
        # Give event loop a chance to process cancellation
        await asyncio.sleep(0.01)
        assert timer_task.cancelled()

    def test_cancel_timer_noop_when_no_timer(self, game_with_songs):
        """cancel_timer does nothing when no timer is running."""
        state = game_with_songs
        assert state._timer_task is None

        # Should not raise
        state.cancel_timer()

        assert state._timer_task is None


@pytest.mark.unit
class TestGameEndCancelsTimer:
    """Tests that end_game cancels the timer."""

    @pytest.mark.asyncio
    async def test_end_game_cancels_timer(self, game_with_songs, mock_hass):
        """end_game cancels any running timer task."""
        state = game_with_songs

        await state.start_round(mock_hass)
        timer_task = state._timer_task
        assert timer_task is not None

        state.end_game()

        # Timer should be cancelled
        await asyncio.sleep(0.01)
        assert timer_task.cancelled() or timer_task.done()


@pytest.mark.unit
class TestCreateGameResetsTimer:
    """Tests that create_game resets timer state."""

    @pytest.mark.asyncio
    async def test_create_game_cancels_existing_timer(self, game_with_songs, mock_hass):
        """create_game cancels any existing timer from previous game."""
        state = game_with_songs

        await state.start_round(mock_hass)
        old_timer = state._timer_task
        assert old_timer is not None

        # Create a new game (simulating game reset)
        state.create_game(
            playlists=["new_playlist.json"],
            songs=[{"year": 2000, "uri": "spotify:track:new", "fun_fact": "New fact"}],
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        # Old timer should be cancelled
        await asyncio.sleep(0.01)
        assert old_timer.cancelled() or old_timer.done()


@pytest.mark.unit
class TestSetRoundEndCallback:
    """Tests for set_round_end_callback method."""

    def test_set_round_end_callback_stores_callback(self, game_with_songs):
        """set_round_end_callback stores the callback function."""
        state = game_with_songs
        callback = AsyncMock()

        state.set_round_end_callback(callback)

        assert state._on_round_end is callback


@pytest.mark.unit
class TestRevealPlayersState:
    """Tests for get_reveal_players_state method."""

    @pytest.mark.asyncio
    async def test_reveal_state_includes_guess(self, game_with_songs, mock_hass):
        """Reveal state includes player's guess."""
        state = game_with_songs

        mock_ws = MagicMock()
        state.add_player("TestPlayer", mock_ws)

        await state.start_round(mock_hass)

        # Simulate submission
        state.players["TestPlayer"].submit_guess(year=1988, timestamp=1000.0)

        await state.end_round()

        reveal_state = state.get_reveal_players_state()

        player_data = next(p for p in reveal_state if p["name"] == "TestPlayer")
        assert player_data["guess"] == 1988

    @pytest.mark.asyncio
    async def test_reveal_state_includes_round_score(self, game_with_songs, mock_hass):
        """Reveal state includes player's round_score."""
        state = game_with_songs

        mock_ws = MagicMock()
        state.add_player("TestPlayer", mock_ws)

        await state.start_round(mock_hass)
        await state.end_round()

        reveal_state = state.get_reveal_players_state()

        player_data = next(p for p in reveal_state if p["name"] == "TestPlayer")
        assert "round_score" in player_data

    @pytest.mark.asyncio
    async def test_reveal_state_includes_missed_round(self, game_with_songs, mock_hass):
        """Reveal state includes missed_round flag."""
        state = game_with_songs

        mock_ws = MagicMock()
        state.add_player("TestPlayer", mock_ws)

        await state.start_round(mock_hass)
        await state.end_round()

        reveal_state = state.get_reveal_players_state()

        player_data = next(p for p in reveal_state if p["name"] == "TestPlayer")
        assert player_data["missed_round"] is True


@pytest.mark.unit
class TestGetStateRevealPhase:
    """Tests for get_state during REVEAL phase."""

    @pytest.mark.asyncio
    async def test_get_state_reveal_includes_year(self, game_with_songs, mock_hass):
        """get_state includes song year during REVEAL phase."""
        state = game_with_songs

        await state.start_round(mock_hass)
        await state.end_round()

        assert state.phase == GamePhase.REVEAL

        result = state.get_state()

        assert "song" in result
        assert "year" in result["song"]

    @pytest.mark.asyncio
    async def test_get_state_reveal_includes_fun_fact(self, game_with_songs, mock_hass):
        """get_state includes fun_fact during REVEAL phase."""
        state = game_with_songs

        await state.start_round(mock_hass)
        await state.end_round()

        result = state.get_state()

        assert "song" in result
        assert "fun_fact" in result["song"]

    @pytest.mark.asyncio
    async def test_get_state_reveal_uses_reveal_players_state(
        self, game_with_songs, mock_hass
    ):
        """get_state uses get_reveal_players_state during REVEAL phase."""
        state = game_with_songs

        mock_ws = MagicMock()
        state.add_player("TestPlayer", mock_ws)

        await state.start_round(mock_hass)

        # Simulate submission
        state.players["TestPlayer"].submit_guess(year=1988, timestamp=1000.0)

        await state.end_round()

        result = state.get_state()

        # Players should include reveal-specific data
        player_data = next(p for p in result["players"] if p["name"] == "TestPlayer")
        assert "guess" in player_data
        assert "round_score" in player_data
        assert "missed_round" in player_data
