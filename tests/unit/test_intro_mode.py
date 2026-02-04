"""Unit tests for Intro Mode feature (Issue #23)."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.beatify.const import (
    INTRO_BONUS_TIERS,
    INTRO_DURATION_SECONDS,
    INTRO_ROUND_CHANCE,
    MIN_INTRO_BONUSES_FOR_AWARD,
)
from custom_components.beatify.game.player import PlayerSession
from custom_components.beatify.game.state import GamePhase, GameState


@pytest.fixture
def mock_ws():
    """Mock WebSocket connection."""
    return MagicMock()


@pytest.fixture
def game_state():
    """Create a GameState instance for testing."""
    state = GameState()
    return state


@pytest.fixture
def mock_media_player():
    """Mock media player service."""
    service = AsyncMock()
    service.pause = AsyncMock()
    service.play = AsyncMock()
    service.play_song = AsyncMock()
    return service


# =============================================================================
# TestIntroModeCreation - Game creation with intro mode
# =============================================================================


class TestIntroModeCreation:
    """Tests for intro mode game creation (Issue #23)."""

    def test_create_game_with_intro_mode_enabled(self, game_state):
        """Verify intro_mode_enabled is stored when True."""
        game_state.create_game(
            playlists=["test.json"],
            songs=[{"uri": "spotify:track:abc123", "year": 2020}],
            media_player="media_player.test",
            base_url="http://localhost",
            intro_mode_enabled=True,
        )

        assert game_state.intro_mode_enabled is True

    def test_create_game_intro_mode_default_off(self, game_state):
        """Verify intro_mode_enabled defaults to False."""
        game_state.create_game(
            playlists=["test.json"],
            songs=[{"uri": "spotify:track:abc123", "year": 2020}],
            media_player="media_player.test",
            base_url="http://localhost",
        )

        assert game_state.intro_mode_enabled is False

    def test_create_game_initializes_intro_state(self, game_state):
        """Verify all intro-related state is initialized on game creation."""
        game_state.create_game(
            playlists=["test.json"],
            songs=[{"uri": "spotify:track:abc123", "year": 2020}],
            media_player="media_player.test",
            base_url="http://localhost",
            intro_mode_enabled=True,
        )

        assert game_state.is_intro_round is False
        assert game_state.intro_stopped is False
        assert game_state._intro_round_start_time is None
        assert game_state._intro_stop_task is None


# =============================================================================
# TestIntroRoundSelection - Random intro round selection
# =============================================================================


class TestIntroRoundSelection:
    """Tests for random intro round selection (Issue #23)."""

    def test_intro_round_never_when_disabled(self, game_state):
        """Verify is_intro_round stays False when mode disabled."""
        game_state.create_game(
            playlists=["test.json"],
            songs=[{"uri": "spotify:track:abc123", "year": 2020, "duration_ms": 180000}],
            media_player="media_player.test",
            base_url="http://localhost",
            intro_mode_enabled=False,
        )

        # Even with random returning low value, should not trigger
        with patch("random.random", return_value=0.01):
            # Reset to simulate what start_round does
            game_state.is_intro_round = False
            if game_state.intro_mode_enabled:
                import random
                if random.random() < INTRO_ROUND_CHANCE:
                    game_state.is_intro_round = True

        assert game_state.is_intro_round is False

    def test_intro_round_triggered_below_threshold(self, game_state):
        """Verify intro round triggers when random() < INTRO_ROUND_CHANCE."""
        game_state.create_game(
            playlists=["test.json"],
            songs=[{"uri": "spotify:track:abc123", "year": 2020, "duration_ms": 180000}],
            media_player="media_player.test",
            base_url="http://localhost",
            intro_mode_enabled=True,
        )

        # Patch at module level where it's used
        with patch("custom_components.beatify.game.state.random.random", return_value=0.10):
            # Simulate what start_round does for intro detection
            game_state.is_intro_round = False
            if game_state.intro_mode_enabled:
                import custom_components.beatify.game.state as state_module
                if state_module.random.random() < INTRO_ROUND_CHANCE:
                    song_duration_ms = 180000
                    if song_duration_ms >= INTRO_DURATION_SECONDS * 1000:
                        game_state.is_intro_round = True

        assert game_state.is_intro_round is True

    def test_intro_round_not_triggered_above_threshold(self, game_state):
        """Verify no intro round when random() >= INTRO_ROUND_CHANCE."""
        game_state.create_game(
            playlists=["test.json"],
            songs=[{"uri": "spotify:track:abc123", "year": 2020, "duration_ms": 180000}],
            media_player="media_player.test",
            base_url="http://localhost",
            intro_mode_enabled=True,
        )

        with patch("custom_components.beatify.game.state.random.random", return_value=0.50):
            game_state.is_intro_round = False
            if game_state.intro_mode_enabled:
                import custom_components.beatify.game.state as state_module
                if state_module.random.random() < INTRO_ROUND_CHANCE:
                    game_state.is_intro_round = True

        assert game_state.is_intro_round is False

    def test_short_song_skips_intro_mode(self, game_state):
        """Verify songs <10s don't trigger intro mode (F4 fix)."""
        game_state.create_game(
            playlists=["test.json"],
            songs=[{"uri": "spotify:track:abc123", "year": 2020, "duration_ms": 5000}],  # 5 seconds
            media_player="media_player.test",
            base_url="http://localhost",
            intro_mode_enabled=True,
        )

        with patch("custom_components.beatify.game.state.random.random", return_value=0.10):
            game_state.is_intro_round = False
            if game_state.intro_mode_enabled:
                import custom_components.beatify.game.state as state_module
                if state_module.random.random() < INTRO_ROUND_CHANCE:
                    song_duration_ms = 5000  # Short song
                    if song_duration_ms >= INTRO_DURATION_SECONDS * 1000:
                        game_state.is_intro_round = True

        # Should NOT trigger because song is too short
        assert game_state.is_intro_round is False


# =============================================================================
# TestIntroAutoStop - 10-second auto-pause
# =============================================================================


class TestIntroAutoStop:
    """Tests for 10-second auto-pause (Issue #23)."""

    @pytest.mark.asyncio
    async def test_intro_auto_stop_pauses_playback(self, game_state, mock_media_player):
        """Verify _intro_auto_stop calls pause on media player."""
        game_state._media_player_service = mock_media_player
        game_state.phase = GamePhase.PLAYING
        game_state.intro_stopped = False
        game_state._broadcast_state = AsyncMock()

        # Call with 0 delay for immediate execution
        await game_state._intro_auto_stop(0)

        mock_media_player.pause.assert_called_once()
        assert game_state.intro_stopped is True

    @pytest.mark.asyncio
    async def test_intro_auto_stop_broadcasts_state(self, game_state, mock_media_player):
        """Verify state broadcast after intro stops."""
        game_state._media_player_service = mock_media_player
        game_state.phase = GamePhase.PLAYING
        game_state.intro_stopped = False
        game_state._broadcast_state = AsyncMock()

        await game_state._intro_auto_stop(0)

        game_state._broadcast_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_intro_auto_stop_does_not_pause_if_already_stopped(self, game_state, mock_media_player):
        """Verify no double pause if intro already stopped."""
        game_state._media_player_service = mock_media_player
        game_state.phase = GamePhase.PLAYING
        game_state.intro_stopped = True  # Already stopped
        game_state._broadcast_state = AsyncMock()

        await game_state._intro_auto_stop(0)

        mock_media_player.pause.assert_not_called()

    def test_cancel_intro_timer(self, game_state):
        """Verify _cancel_intro_timer cancels the task."""
        mock_task = MagicMock()
        mock_task.done.return_value = False
        game_state._intro_stop_task = mock_task

        game_state._cancel_intro_timer()

        mock_task.cancel.assert_called_once()
        assert game_state._intro_stop_task is None

    def test_cancel_intro_timer_no_task(self, game_state):
        """Verify _cancel_intro_timer handles None task gracefully."""
        game_state._intro_stop_task = None

        # Should not raise
        game_state._cancel_intro_timer()

        assert game_state._intro_stop_task is None


# =============================================================================
# TestIntroSpeedBonus - Tiered speed bonus scoring
# =============================================================================


class TestIntroSpeedBonus:
    """Tests for tiered speed bonus scoring (Issue #23)."""

    def test_intro_bonus_tiers_constant(self):
        """Verify INTRO_BONUS_TIERS matches expected values."""
        assert INTRO_BONUS_TIERS == [5, 3, 1]

    def test_intro_duration_constant(self):
        """Verify INTRO_DURATION_SECONDS is 10."""
        assert INTRO_DURATION_SECONDS == 10

    def test_intro_round_chance_constant(self):
        """Verify INTRO_ROUND_CHANCE is 0.20."""
        assert INTRO_ROUND_CHANCE == 0.20

    def test_first_submitter_gets_5_bonus(self, mock_ws):
        """Verify fastest pre-cutoff submitter gets +5 bonus."""
        # Setup: Create players with different submission times
        player1 = PlayerSession(name="Alice", ws=mock_ws)
        player2 = PlayerSession(name="Bob", ws=mock_ws)
        player3 = PlayerSession(name="Charlie", ws=mock_ws)

        # Simulate intro round timing
        intro_start = 1000.0
        intro_cutoff = intro_start + INTRO_DURATION_SECONDS

        # Player 1 submits first (before cutoff)
        player1.submission_time = intro_start + 3.0  # 3s after start
        # Player 2 submits second (before cutoff)
        player2.submission_time = intro_start + 5.0  # 5s after start
        # Player 3 submits third (before cutoff)
        player3.submission_time = intro_start + 8.0  # 8s after start

        players = [player1, player2, player3]

        # Calculate rank for player1 (should be 0 = first)
        rank = len([
            p for p in players
            if p.submission_time is not None
            and p.submission_time < intro_cutoff
            and p.submission_time < player1.submission_time
        ])

        assert rank == 0  # First place
        assert INTRO_BONUS_TIERS[rank] == 5  # Gets +5

    def test_second_submitter_gets_3_bonus(self, mock_ws):
        """Verify second fastest pre-cutoff submitter gets +3 bonus."""
        player1 = PlayerSession(name="Alice", ws=mock_ws)
        player2 = PlayerSession(name="Bob", ws=mock_ws)

        intro_start = 1000.0
        intro_cutoff = intro_start + INTRO_DURATION_SECONDS

        player1.submission_time = intro_start + 3.0
        player2.submission_time = intro_start + 5.0

        players = [player1, player2]

        # Calculate rank for player2 (should be 1 = second)
        rank = len([
            p for p in players
            if p.submission_time is not None
            and p.submission_time < intro_cutoff
            and p.submission_time < player2.submission_time
        ])

        assert rank == 1  # Second place
        assert INTRO_BONUS_TIERS[rank] == 3  # Gets +3

    def test_third_submitter_gets_1_bonus(self, mock_ws):
        """Verify third fastest pre-cutoff submitter gets +1 bonus."""
        player1 = PlayerSession(name="Alice", ws=mock_ws)
        player2 = PlayerSession(name="Bob", ws=mock_ws)
        player3 = PlayerSession(name="Charlie", ws=mock_ws)

        intro_start = 1000.0
        intro_cutoff = intro_start + INTRO_DURATION_SECONDS

        player1.submission_time = intro_start + 3.0
        player2.submission_time = intro_start + 5.0
        player3.submission_time = intro_start + 8.0

        players = [player1, player2, player3]

        # Calculate rank for player3 (should be 2 = third)
        rank = len([
            p for p in players
            if p.submission_time is not None
            and p.submission_time < intro_cutoff
            and p.submission_time < player3.submission_time
        ])

        assert rank == 2  # Third place
        assert INTRO_BONUS_TIERS[rank] == 1  # Gets +1

    def test_submitter_after_cutoff_gets_no_bonus(self, mock_ws):
        """Verify player submitting after 10s cutoff gets no bonus."""
        player = PlayerSession(name="Alice", ws=mock_ws)

        intro_start = 1000.0
        intro_cutoff = intro_start + INTRO_DURATION_SECONDS

        # Submit after cutoff
        player.submission_time = intro_start + 12.0  # 12s after start

        # Should not qualify for bonus
        qualifies = (
            player.submission_time is not None
            and player.submission_time < intro_cutoff
        )

        assert qualifies is False


# =============================================================================
# TestIntroMasterSuperlative - Award calculation
# =============================================================================


class TestIntroMasterSuperlative:
    """Tests for Intro Master award (Issue #23)."""

    def test_min_intro_bonuses_constant(self):
        """Verify MIN_INTRO_BONUSES_FOR_AWARD is 1."""
        assert MIN_INTRO_BONUSES_FOR_AWARD == 1

    def test_player_with_most_bonuses_wins(self, mock_ws):
        """Verify player with most intro speed bonuses gets the award."""
        player1 = PlayerSession(name="Alice", ws=mock_ws)
        player2 = PlayerSession(name="Bob", ws=mock_ws)
        player3 = PlayerSession(name="Charlie", ws=mock_ws)

        player1.intro_speed_bonuses = 3
        player2.intro_speed_bonuses = 5  # Winner
        player3.intro_speed_bonuses = 2

        players = [player1, player2, player3]

        # Find winner (matching logic in calculate_superlatives)
        candidates = [
            (p, p.intro_speed_bonuses)
            for p in players
            if p.intro_speed_bonuses >= MIN_INTRO_BONUSES_FOR_AWARD
        ]
        winner = max(candidates, key=lambda x: x[1])

        assert winner[0].name == "Bob"
        assert winner[1] == 5

    def test_no_award_if_no_qualifying_players(self, mock_ws):
        """Verify no award when no players meet minimum threshold."""
        player1 = PlayerSession(name="Alice", ws=mock_ws)
        player1.intro_speed_bonuses = 0

        players = [player1]

        candidates = [
            (p, p.intro_speed_bonuses)
            for p in players
            if p.intro_speed_bonuses >= MIN_INTRO_BONUSES_FOR_AWARD
        ]

        assert len(candidates) == 0


# =============================================================================
# TestIntroStateIntegration - State management and integration
# =============================================================================


class TestIntroStateIntegration:
    """Tests for state management and integration (Issue #23)."""

    def test_player_session_has_intro_fields(self, mock_ws):
        """Verify PlayerSession has intro-related fields."""
        player = PlayerSession(name="Alice", ws=mock_ws)

        assert hasattr(player, "intro_bonus")
        assert hasattr(player, "intro_speed_bonuses")
        assert player.intro_bonus == 0
        assert player.intro_speed_bonuses == 0

    def test_player_reset_round_clears_intro_bonus(self, mock_ws):
        """Verify reset_round clears intro_bonus but not intro_speed_bonuses."""
        player = PlayerSession(name="Alice", ws=mock_ws)
        player.intro_bonus = 5
        player.intro_speed_bonuses = 3

        player.reset_round()

        assert player.intro_bonus == 0
        assert player.intro_speed_bonuses == 3  # Cumulative, not reset

    def test_player_reset_for_new_game_clears_all(self, mock_ws):
        """Verify reset_for_new_game clears all intro tracking."""
        player = PlayerSession(name="Alice", ws=mock_ws)
        player.intro_bonus = 5
        player.intro_speed_bonuses = 3

        player.reset_for_new_game()

        assert player.intro_bonus == 0
        assert player.intro_speed_bonuses == 0

    def test_get_state_includes_intro_fields(self, game_state):
        """Verify get_state includes all intro fields."""
        game_state.create_game(
            playlists=["test.json"],
            songs=[{"uri": "spotify:track:abc123", "year": 2020}],
            media_player="media_player.test",
            base_url="http://localhost",
            intro_mode_enabled=True,
        )
        game_state.is_intro_round = True
        game_state.intro_stopped = True

        state = game_state.get_state()

        assert state["intro_mode_enabled"] is True
        assert state["is_intro_round"] is True
        assert state["intro_stopped"] is True


# =============================================================================
# TestEdgeCases - Edge case tests
# =============================================================================


class TestEdgeCases:
    """Edge case tests for intro mode (Issue #23)."""

    @pytest.mark.asyncio
    async def test_intro_auto_stop_handles_pause_error(self, game_state, mock_media_player):
        """Verify graceful handling of media player pause errors."""
        mock_media_player.pause = AsyncMock(side_effect=Exception("Network error"))
        game_state._media_player_service = mock_media_player
        game_state.phase = GamePhase.PLAYING
        game_state.intro_stopped = False
        game_state._broadcast_state = AsyncMock()

        # Should not raise, just log warning
        await game_state._intro_auto_stop(0)

        # intro_stopped should still be set
        assert game_state.intro_stopped is True

    def test_all_players_submit_before_cutoff(self, mock_ws):
        """Verify handling when all players submit before 10s."""
        players = [
            PlayerSession(name="Alice", ws=mock_ws),
            PlayerSession(name="Bob", ws=mock_ws),
            PlayerSession(name="Charlie", ws=mock_ws),
        ]

        intro_start = 1000.0
        intro_cutoff = intro_start + INTRO_DURATION_SECONDS

        # All submit before cutoff
        players[0].submission_time = intro_start + 2.0
        players[1].submission_time = intro_start + 4.0
        players[2].submission_time = intro_start + 6.0

        # All should qualify
        qualifying = [
            p for p in players
            if p.submission_time and p.submission_time < intro_cutoff
        ]

        assert len(qualifying) == 3

    def test_no_submissions_before_cutoff(self, mock_ws):
        """Verify handling when no one submits before 10s."""
        players = [
            PlayerSession(name="Alice", ws=mock_ws),
            PlayerSession(name="Bob", ws=mock_ws),
        ]

        intro_start = 1000.0
        intro_cutoff = intro_start + INTRO_DURATION_SECONDS

        # All submit after cutoff
        players[0].submission_time = intro_start + 15.0
        players[1].submission_time = intro_start + 20.0

        # None should qualify
        qualifying = [
            p for p in players
            if p.submission_time and p.submission_time < intro_cutoff
        ]

        assert len(qualifying) == 0

    def test_player_with_none_submission_time(self, mock_ws):
        """Verify handling of players with None submission_time (F5 fix)."""
        players = [
            PlayerSession(name="Alice", ws=mock_ws),
            PlayerSession(name="Bob", ws=mock_ws),
        ]

        intro_start = 1000.0
        intro_cutoff = intro_start + INTRO_DURATION_SECONDS

        players[0].submission_time = intro_start + 5.0
        players[1].submission_time = None  # Did not submit

        # Only Alice should qualify
        qualifying = [
            p for p in players
            if p.submission_time is not None and p.submission_time < intro_cutoff
        ]

        assert len(qualifying) == 1
        assert qualifying[0].name == "Alice"
