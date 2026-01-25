"""
Unit Tests: MediaPlayerService

Tests media player integration for Epic 4 gameplay:
- Song playback via HA services (platform-based routing)
- Metadata retrieval from entity attributes
- Stop and volume control
- Error handling for unavailable player
- Platform capability detection

Story 4.1 - AC: #2, #6, #7
Platform routing - AC: #1, #2, #3 (Multi-platform support: MA, Sonos, Alexa)
"""

from __future__ import annotations

import sys
from unittest.mock import AsyncMock, MagicMock

import pytest

# Mock homeassistant before importing beatify modules
sys.modules["homeassistant"] = MagicMock()
sys.modules["homeassistant.core"] = MagicMock()
sys.modules["homeassistant.config_entries"] = MagicMock()
sys.modules["homeassistant.helpers"] = MagicMock()
sys.modules["homeassistant.helpers.config_validation"] = MagicMock()
sys.modules["homeassistant.components"] = MagicMock()
sys.modules["homeassistant.components.http"] = MagicMock()
sys.modules["homeassistant.components.frontend"] = MagicMock()
sys.modules["voluptuous"] = MagicMock()

from custom_components.beatify.services.media_player import (
    MediaPlayerService,
    get_platform_capabilities,
)


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.states = MagicMock()
    return hass


@pytest.mark.unit
class TestMediaPlayerServicePlayback:
    """Tests for song playback with platform-based routing."""

    @pytest.mark.asyncio
    async def test_play_song_via_music_assistant(self, mock_hass):
        """Music Assistant players use music_assistant.play_media service."""
        service = MediaPlayerService(
            mock_hass, "media_player.living_room", platform="music_assistant"
        )
        song = {"_resolved_uri": "spotify:track:abc123", "artist": "Test", "title": "Song"}

        result = await service.play_song(song)

        assert result is True
        mock_hass.services.async_call.assert_called_once_with(
            "music_assistant",
            "play_media",
            {"media_id": "spotify:track:abc123", "media_type": "track"},
            target={"entity_id": "media_player.living_room"},
            blocking=True,
        )

    @pytest.mark.asyncio
    async def test_play_song_via_sonos(self, mock_hass):
        """Sonos players use media_player.play_media with URI."""
        service = MediaPlayerService(
            mock_hass, "media_player.sonos_speaker", platform="sonos"
        )
        song = {"_resolved_uri": "spotify:track:abc123", "artist": "Test", "title": "Song"}

        result = await service.play_song(song)

        assert result is True
        mock_hass.services.async_call.assert_called_once_with(
            "media_player",
            "play_media",
            {
                "entity_id": "media_player.sonos_speaker",
                "media_content_id": "spotify:track:abc123",
                "media_content_type": "music",
            },
            blocking=True,
        )

    @pytest.mark.asyncio
    async def test_play_song_via_alexa_spotify(self, mock_hass):
        """Alexa players use text search with SPOTIFY content type."""
        service = MediaPlayerService(
            mock_hass, "media_player.echo", platform="alexa_media", provider="spotify"
        )
        song = {"_resolved_uri": "spotify:track:abc", "artist": "Test Artist", "title": "Test Song"}

        result = await service.play_song(song)

        assert result is True
        mock_hass.services.async_call.assert_called_once_with(
            "media_player",
            "play_media",
            {
                "entity_id": "media_player.echo",
                "media_content_id": "Test Song by Test Artist",
                "media_content_type": "SPOTIFY",
            },
            blocking=True,
        )

    @pytest.mark.asyncio
    async def test_play_song_via_alexa_apple_music(self, mock_hass):
        """Alexa players use text search with APPLE_MUSIC content type."""
        service = MediaPlayerService(
            mock_hass, "media_player.echo", platform="alexa_media", provider="apple_music"
        )
        song = {"_resolved_uri": "applemusic://track/123", "artist": "Test Artist", "title": "Test Song"}

        result = await service.play_song(song)

        assert result is True
        call_args = mock_hass.services.async_call.call_args
        assert call_args[0][2]["media_content_type"] == "APPLE_MUSIC"
        assert call_args[0][2]["media_content_id"] == "Test Song by Test Artist"

    @pytest.mark.asyncio
    async def test_play_song_returns_false_on_error(self, mock_hass):
        """play_song returns False when service call fails."""
        mock_hass.services.async_call = AsyncMock(side_effect=Exception("Service error"))
        service = MediaPlayerService(mock_hass, "media_player.living_room", platform="sonos")
        song = {"_resolved_uri": "spotify:track:abc123", "artist": "Test", "title": "Song"}

        result = await service.play_song(song)

        assert result is False

    @pytest.mark.asyncio
    async def test_play_song_unsupported_platform_returns_false(self, mock_hass):
        """play_song returns False for unsupported platforms."""
        service = MediaPlayerService(
            mock_hass, "media_player.unknown", platform="unknown_platform"
        )
        song = {"_resolved_uri": "spotify:track:abc123", "artist": "Test", "title": "Song"}

        result = await service.play_song(song)

        assert result is False
        mock_hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_calls_ha_service(self, mock_hass):
        """Stop calls the correct HA service."""
        service = MediaPlayerService(mock_hass, "media_player.living_room")

        result = await service.stop()

        assert result is True
        mock_hass.services.async_call.assert_called_once_with(
            "media_player",
            "media_stop",
            {"entity_id": "media_player.living_room"},
        )

    @pytest.mark.asyncio
    async def test_stop_returns_false_on_error(self, mock_hass):
        """Stop returns False when service call fails."""
        mock_hass.services.async_call = AsyncMock(side_effect=Exception("Service error"))
        service = MediaPlayerService(mock_hass, "media_player.living_room")

        result = await service.stop()

        assert result is False


@pytest.mark.unit
class TestMediaPlayerServiceMetadata:
    """Tests for metadata retrieval."""

    @pytest.mark.asyncio
    async def test_get_metadata_returns_entity_attributes(self, mock_hass):
        """get_metadata returns artist, title, album_art from entity."""
        mock_state = MagicMock()
        mock_state.attributes = {
            "media_artist": "Test Artist",
            "media_title": "Test Song",
            "entity_picture": "/local/image.jpg",
        }
        mock_hass.states.get.return_value = mock_state
        service = MediaPlayerService(mock_hass, "media_player.living_room")

        result = await service.get_metadata()

        assert result["artist"] == "Test Artist"
        assert result["title"] == "Test Song"
        assert result["album_art"] == "/local/image.jpg"

    @pytest.mark.asyncio
    async def test_get_metadata_returns_defaults_when_no_state(self, mock_hass):
        """get_metadata returns defaults when entity has no state."""
        mock_hass.states.get.return_value = None
        service = MediaPlayerService(mock_hass, "media_player.living_room")

        result = await service.get_metadata()

        assert result["artist"] == "Unknown Artist"
        assert result["title"] == "Unknown Title"
        assert result["album_art"] == "/beatify/static/img/no-artwork.svg"

    @pytest.mark.asyncio
    async def test_get_metadata_returns_defaults_for_missing_attributes(self, mock_hass):
        """get_metadata uses defaults for missing attributes."""
        mock_state = MagicMock()
        mock_state.attributes = {}  # Empty attributes
        mock_hass.states.get.return_value = mock_state
        service = MediaPlayerService(mock_hass, "media_player.living_room")

        result = await service.get_metadata()

        assert result["artist"] == "Unknown Artist"
        assert result["title"] == "Unknown Title"
        assert result["album_art"] == "/beatify/static/img/no-artwork.svg"


@pytest.mark.unit
class TestMediaPlayerServiceVolume:
    """Tests for volume control."""

    @pytest.mark.asyncio
    async def test_set_volume_calls_ha_service(self, mock_hass):
        """set_volume calls the correct HA service."""
        service = MediaPlayerService(mock_hass, "media_player.living_room")

        result = await service.set_volume(0.75)

        assert result is True
        mock_hass.services.async_call.assert_called_once_with(
            "media_player",
            "volume_set",
            {
                "entity_id": "media_player.living_room",
                "volume_level": 0.75,
            },
        )

    @pytest.mark.asyncio
    async def test_set_volume_clamps_to_valid_range(self, mock_hass):
        """set_volume clamps values to 0.0-1.0 range."""
        service = MediaPlayerService(mock_hass, "media_player.living_room")

        # Test clamping to max
        await service.set_volume(1.5)
        call_args = mock_hass.services.async_call.call_args
        assert call_args[0][2]["volume_level"] == 1.0

        mock_hass.services.async_call.reset_mock()

        # Test clamping to min
        await service.set_volume(-0.5)
        call_args = mock_hass.services.async_call.call_args
        assert call_args[0][2]["volume_level"] == 0.0

    @pytest.mark.asyncio
    async def test_set_volume_returns_false_on_error(self, mock_hass):
        """set_volume returns False when service call fails."""
        mock_hass.services.async_call = AsyncMock(side_effect=Exception("Service error"))
        service = MediaPlayerService(mock_hass, "media_player.living_room")

        result = await service.set_volume(0.5)

        assert result is False


@pytest.mark.unit
class TestMediaPlayerServiceAvailability:
    """Tests for availability checking."""

    def test_is_available_returns_true_when_state_exists(self, mock_hass):
        """is_available returns True when entity has valid state."""
        mock_state = MagicMock()
        mock_state.state = "idle"
        mock_hass.states.get.return_value = mock_state
        service = MediaPlayerService(mock_hass, "media_player.living_room")

        assert service.is_available() is True

    def test_is_available_returns_false_when_no_state(self, mock_hass):
        """is_available returns False when entity has no state."""
        mock_hass.states.get.return_value = None
        service = MediaPlayerService(mock_hass, "media_player.living_room")

        assert service.is_available() is False

    def test_is_available_returns_false_when_unavailable(self, mock_hass):
        """is_available returns False when entity state is 'unavailable'."""
        mock_state = MagicMock()
        mock_state.state = "unavailable"
        mock_hass.states.get.return_value = mock_state
        service = MediaPlayerService(mock_hass, "media_player.living_room")

        assert service.is_available() is False


@pytest.mark.unit
class TestPlatformCapabilities:
    """
    Tests for platform capability detection.

    Verifies each platform returns correct capability flags.
    """

    def test_music_assistant_capabilities(self):
        """Music Assistant supports Spotify and Apple Music via URI."""
        caps = get_platform_capabilities("music_assistant")
        assert caps["supported"] is True
        assert caps["spotify"] is True
        assert caps["apple_music"] is True
        assert caps["method"] == "uri"

    def test_sonos_capabilities(self):
        """Sonos supports Spotify only via URI."""
        caps = get_platform_capabilities("sonos")
        assert caps["supported"] is True
        assert caps["spotify"] is True
        assert caps["apple_music"] is False
        assert caps["method"] == "uri"

    def test_alexa_media_capabilities(self):
        """Alexa supports Spotify and Apple Music via text search."""
        caps = get_platform_capabilities("alexa_media")
        assert caps["supported"] is True
        assert caps["spotify"] is True
        assert caps["apple_music"] is True
        assert caps["method"] == "text_search"
        assert "caveat" in caps  # Alexa has search caveat

    def test_alexa_alias_maps_to_alexa_media(self):
        """'alexa' is an alias for 'alexa_media'."""
        caps = get_platform_capabilities("alexa")
        assert caps["supported"] is True
        assert caps["method"] == "text_search"

    def test_cast_not_supported(self):
        """Cast devices are not supported (require Music Assistant)."""
        caps = get_platform_capabilities("cast")
        assert caps["supported"] is False
        assert "reason" in caps

    def test_unknown_platform_not_supported(self):
        """Unknown platforms are not supported."""
        caps = get_platform_capabilities("unknown_platform")
        assert caps["supported"] is False
        assert "reason" in caps
