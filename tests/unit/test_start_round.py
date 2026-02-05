"""
Unit Tests: GameState start_round

Tests round initiation for Epic 4 gameplay:
- Phase transitions to PLAYING
- Round counter increments
- Deadline is set correctly
- Song selection and metadata
- Failed song handling

Story 4.1 - AC: #1, #3, #6
"""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mock homeassistant before importing beatify modules
sys.modules["homeassistant"] = MagicMock()
sys.modules["homeassistant.core"] = MagicMock()
sys.modules["homeassistant.components"] = MagicMock()
sys.modules["homeassistant.components.http"] = MagicMock()
sys.modules["homeassistant.components.frontend"] = MagicMock()
sys.modules["homeassistant.helpers"] = MagicMock()
sys.modules["homeassistant.helpers.aiohttp_client"] = MagicMock()

from custom_components.beatify.game.state import GamePhase, GameState
from custom_components.beatify.services.media_player import MediaPlayerService


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.states = MagicMock()
    return hass


@pytest.fixture(autouse=True)
def mock_media_player_service():
    """Mock MediaPlayerService methods so start_round succeeds without real HA."""
    with (
        patch.object(MediaPlayerService, "play_song", new_callable=AsyncMock, return_value=True),
        patch.object(
            MediaPlayerService,
            "verify_responsive",
            new_callable=AsyncMock,
            return_value=(True, None),
        ),
    ):
        yield


@pytest.fixture
def game_with_songs():
    """Create a game state with songs loaded."""
    state = GameState(time_fn=lambda: 1000.0)
    songs = [
        {
            "year": 1985,
            "uri": "spotify:track:1",
            "_resolved_uri": "spotify:track:1",
            "fun_fact": "Fact 1",
        },
        {
            "year": 1990,
            "uri": "spotify:track:2",
            "_resolved_uri": "spotify:track:2",
            "fun_fact": "Fact 2",
        },
        {
            "year": 1995,
            "uri": "spotify:track:3",
            "_resolved_uri": "spotify:track:3",
            "fun_fact": "Fact 3",
        },
    ]
    state.create_game(
        playlists=["playlist1.json"],
        songs=songs,
        media_player="media_player.test",
        base_url="http://test.local:8123",
    )
    return state


@pytest.mark.unit
class TestStartRoundPhaseTransition:
    """Tests for start_round phase transition."""

    @pytest.mark.asyncio
    async def test_start_round_transitions_to_playing(self, game_with_songs, mock_hass):
        """start_round transitions phase from LOBBY to PLAYING."""
        state = game_with_songs

        result = await state.start_round(mock_hass)

        assert result is True
        assert state.phase == GamePhase.PLAYING

    @pytest.mark.asyncio
    async def test_start_round_increments_round_counter(self, game_with_songs, mock_hass):
        """start_round increments the round counter."""
        state = game_with_songs
        assert state.round == 0

        await state.start_round(mock_hass)

        assert state.round == 1

    @pytest.mark.asyncio
    async def test_start_round_sets_total_rounds(self, game_with_songs, mock_hass):
        """start_round sets total_rounds from song count."""
        state = game_with_songs

        await state.start_round(mock_hass)

        assert state.total_rounds == 3


@pytest.mark.unit
class TestStartRoundDeadline:
    """Tests for round deadline setting."""

    @pytest.mark.asyncio
    async def test_start_round_sets_deadline(self, mock_hass):
        """start_round sets deadline based on current time + duration."""
        state = GameState(time_fn=lambda: 1000.0)
        songs = [
            {
                "year": 1985,
                "uri": "spotify:track:1",
                "_resolved_uri": "spotify:track:1",
                "fun_fact": "Fact 1",
            }
        ]
        state.create_game(
            playlists=["playlist1.json"],
            songs=songs,
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        await state.start_round(mock_hass)

        # Deadline should be current time (1000.0) + DEFAULT_ROUND_DURATION (45) seconds
        # Converted to milliseconds = 1045000
        from custom_components.beatify.const import DEFAULT_ROUND_DURATION

        expected_deadline = int((1000.0 + DEFAULT_ROUND_DURATION) * 1000)
        assert state.deadline == expected_deadline


@pytest.mark.unit
class TestStartRoundSongSelection:
    """Tests for song selection during start_round."""

    @pytest.mark.asyncio
    async def test_start_round_sets_current_song(self, game_with_songs, mock_hass):
        """start_round sets current_song with metadata."""
        state = game_with_songs

        await state.start_round(mock_hass)

        assert state.current_song is not None
        assert "year" in state.current_song
        assert "uri" in state.current_song
        assert "artist" in state.current_song
        assert "title" in state.current_song
        assert "album_art" in state.current_song

    @pytest.mark.asyncio
    async def test_start_round_marks_song_as_played(self, game_with_songs, mock_hass):
        """start_round marks the selected song as played."""
        state = game_with_songs

        await state.start_round(mock_hass)

        # The played song should be marked
        assert state._playlist_manager.get_remaining_count() == 2

    @pytest.mark.asyncio
    async def test_start_round_resets_player_submissions(self, game_with_songs, mock_hass):
        """start_round resets player submitted flags."""
        state = game_with_songs

        # Add a player with submitted=True
        mock_ws = MagicMock()
        state.add_player("TestPlayer", mock_ws)
        state.players["TestPlayer"].submitted = True

        await state.start_round(mock_hass)

        assert state.players["TestPlayer"].submitted is False


@pytest.mark.unit
class TestStartRoundLastRound:
    """Tests for last round detection."""

    @pytest.mark.asyncio
    async def test_start_round_sets_last_round_when_one_remaining(self, mock_hass):
        """start_round sets last_round=True when only 1 song remains."""
        state = GameState(time_fn=lambda: 1000.0)
        songs = [
            {
                "year": 1985,
                "uri": "spotify:track:1",
                "_resolved_uri": "spotify:track:1",
                "fun_fact": "Fact 1",
            }
        ]
        state.create_game(
            playlists=["playlist1.json"],
            songs=songs,
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        await state.start_round(mock_hass)

        assert state.last_round is True

    @pytest.mark.asyncio
    async def test_start_round_returns_false_when_exhausted(self, mock_hass):
        """start_round returns False when all songs are exhausted."""
        state = GameState(time_fn=lambda: 1000.0)
        songs = [
            {
                "year": 1985,
                "uri": "spotify:track:1",
                "_resolved_uri": "spotify:track:1",
                "fun_fact": "Fact 1",
            }
        ]
        state.create_game(
            playlists=["playlist1.json"],
            songs=songs,
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        # Play the only song
        await state.start_round(mock_hass)

        # Try to start another round - should fail
        result = await state.start_round(mock_hass)

        assert result is False
        assert state.phase == GamePhase.END


@pytest.mark.unit
class TestStartRoundMediaPlayer:
    """Tests for media player integration during start_round."""

    @pytest.mark.asyncio
    async def test_start_round_creates_media_player_service(self, game_with_songs, mock_hass):
        """start_round creates MediaPlayerService with correct entity."""
        state = game_with_songs

        await state.start_round(mock_hass)

        # Verify media player service was created
        assert state._media_player_service is not None
        assert state.media_player == "media_player.test"


@pytest.mark.unit
class TestGetStatePlayingPhase:
    """Tests for get_state during PLAYING phase."""

    @pytest.mark.asyncio
    async def test_get_state_includes_round_info(self, game_with_songs, mock_hass):
        """get_state includes round, total_rounds, deadline during PLAYING."""
        state = game_with_songs

        await state.start_round(mock_hass)

        result = state.get_state()

        assert result["round"] == 1
        assert result["total_rounds"] == 3
        assert "deadline" in result
        assert result["phase"] == "PLAYING"

    @pytest.mark.asyncio
    async def test_get_state_excludes_year_during_playing(self, game_with_songs, mock_hass):
        """get_state excludes year from song during PLAYING phase."""
        state = game_with_songs

        await state.start_round(mock_hass)

        result = state.get_state()

        assert "song" in result
        assert "year" not in result["song"]
        assert "artist" in result["song"]
        assert "title" in result["song"]
        assert "album_art" in result["song"]

    @pytest.mark.asyncio
    async def test_get_state_includes_last_round_flag(self, mock_hass):
        """get_state includes last_round flag during PLAYING."""
        state = GameState(time_fn=lambda: 1000.0)
        songs = [
            {
                "year": 1985,
                "uri": "spotify:track:1",
                "_resolved_uri": "spotify:track:1",
                "fun_fact": "Fact 1",
            }
        ]
        state.create_game(
            playlists=["playlist1.json"],
            songs=songs,
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        await state.start_round(mock_hass)

        result = state.get_state()

        assert result["last_round"] is True


@pytest.mark.unit
class TestStartRoundRichSongInfo:
    """Tests for rich song info fields during start_round (Story 14.3)."""

    @pytest.mark.asyncio
    async def test_start_round_preserves_chart_info(self, mock_hass):
        """start_round preserves chart_info from enriched playlist songs."""
        state = GameState(time_fn=lambda: 1000.0)
        songs = [
            {
                "year": 1982,
                "uri": "spotify:track:1",
                "_resolved_uri": "spotify:track:1",
                "fun_fact": "Fact 1",
                "chart_info": {"billboard_peak": 1, "weeks_on_chart": 22},
            }
        ]
        state.create_game(
            playlists=["playlist1.json"],
            songs=songs,
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        await state.start_round(mock_hass)

        assert state.current_song["chart_info"] == {"billboard_peak": 1, "weeks_on_chart": 22}

    @pytest.mark.asyncio
    async def test_start_round_preserves_certifications(self, mock_hass):
        """start_round preserves certifications from enriched playlist songs."""
        state = GameState(time_fn=lambda: 1000.0)
        songs = [
            {
                "year": 1982,
                "uri": "spotify:track:1",
                "_resolved_uri": "spotify:track:1",
                "fun_fact": "Fact 1",
                "certifications": ["4x Platinum (US)", "2x Platinum (UK)"],
            }
        ]
        state.create_game(
            playlists=["playlist1.json"],
            songs=songs,
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        await state.start_round(mock_hass)

        assert state.current_song["certifications"] == ["4x Platinum (US)", "2x Platinum (UK)"]

    @pytest.mark.asyncio
    async def test_start_round_preserves_awards(self, mock_hass):
        """start_round preserves awards from enriched playlist songs."""
        state = GameState(time_fn=lambda: 1000.0)
        songs = [
            {
                "year": 1982,
                "uri": "spotify:track:1",
                "_resolved_uri": "spotify:track:1",
                "fun_fact": "Fact 1",
                "awards": ["Grammy Hall of Fame (2004)"],
            }
        ]
        state.create_game(
            playlists=["playlist1.json"],
            songs=songs,
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        await state.start_round(mock_hass)

        assert state.current_song["awards"] == ["Grammy Hall of Fame (2004)"]

    @pytest.mark.asyncio
    async def test_start_round_defaults_missing_rich_info(self, mock_hass):
        """start_round provides defaults for missing rich info fields."""
        state = GameState(time_fn=lambda: 1000.0)
        # Song without any rich info fields (backward compatibility)
        songs = [
            {
                "year": 1985,
                "uri": "spotify:track:1",
                "_resolved_uri": "spotify:track:1",
                "fun_fact": "Fact 1",
            }
        ]
        state.create_game(
            playlists=["playlist1.json"],
            songs=songs,
            media_player="media_player.test",
            base_url="http://test.local:8123",
        )

        await state.start_round(mock_hass)

        # Should have empty defaults
        assert state.current_song["chart_info"] == {}
        assert state.current_song["certifications"] == []
        assert state.current_song["awards"] == []
