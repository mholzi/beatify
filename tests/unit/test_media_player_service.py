"""
Unit Tests: MediaPlayerService

Tests media player integration for Epic 4 gameplay:
- Song playback via HA services
- Metadata retrieval from entity attributes
- Stop and volume control
- Error handling for unavailable player
- Provider-specific content type detection (Story 16.2)

Story 4.1 - AC: #2, #6, #7
Story 16.2 - AC: #1, #5 (Spotify playback fix for Alexa)
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
    get_media_content_type,
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
    """Tests for song playback."""

    @pytest.mark.asyncio
    async def test_play_song_calls_ha_service_with_spotify_content_type(self, mock_hass):
        """play_song calls HA service with 'spotify' content type for Spotify URIs (Story 16.2)."""
        service = MediaPlayerService(mock_hass, "media_player.living_room")

        result = await service.play_song("spotify:track:abc123")

        assert result is True
        mock_hass.services.async_call.assert_called_once_with(
            "media_player",
            "play_media",
            {
                "entity_id": "media_player.living_room",
                "media_content_id": "spotify:track:abc123",
                "media_content_type": "spotify",  # Story 16.2: Must be "spotify" for Alexa
            },
            blocking=True,
        )

    @pytest.mark.asyncio
    async def test_play_song_returns_false_on_error(self, mock_hass):
        """play_song returns False when service call fails."""
        mock_hass.services.async_call = AsyncMock(side_effect=Exception("Service error"))
        service = MediaPlayerService(mock_hass, "media_player.living_room")

        result = await service.play_song("spotify:track:abc123")

        assert result is False

    @pytest.mark.asyncio
    async def test_stop_calls_ha_service(self, mock_hass):
        """stop calls the correct HA service."""
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
        """stop returns False when service call fails."""
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
class TestMediaContentTypeDetection:
    """Tests for provider-specific content type detection (Story 16.2).

    AC #1: media_content_type shall be "spotify" for Spotify URIs
    AC #5: Content type shall be parameterizable per provider
    """

    def test_spotify_track_uri_returns_spotify_type(self):
        """Spotify track URI returns 'spotify' content type."""
        assert get_media_content_type("spotify:track:abc123") == "spotify"

    def test_spotify_album_uri_returns_spotify_type(self):
        """Spotify album URI returns 'spotify' content type."""
        assert get_media_content_type("spotify:album:xyz789") == "spotify"

    def test_spotify_playlist_uri_returns_spotify_type(self):
        """Spotify playlist URI returns 'spotify' content type."""
        assert get_media_content_type("spotify:playlist:def456") == "spotify"

    def test_apple_music_uri_returns_apple_music_type(self):
        """Apple Music URI returns 'apple_music' content type (legacy format)."""
        assert get_media_content_type("apple_music:track:abc123") == "apple_music"

    def test_applemusic_via_music_assistant_returns_music_type(self):
        """Apple Music via Music Assistant uses 'music' content type (Story 17.3)."""
        # Music Assistant uses applemusic:// scheme, not apple_music: prefix
        assert get_media_content_type("applemusic://track/1234567890") == "music"

    def test_tidal_uri_returns_tidal_type(self):
        """Tidal URI returns 'tidal' content type (future support)."""
        assert get_media_content_type("tidal:track:abc123") == "tidal"

    def test_http_url_returns_default_music_type(self):
        """HTTP URLs fall back to generic 'music' content type."""
        assert get_media_content_type("http://example.com/song.mp3") == "music"

    def test_https_url_returns_default_music_type(self):
        """HTTPS URLs fall back to generic 'music' content type."""
        assert get_media_content_type("https://example.com/song.mp3") == "music"

    def test_unknown_provider_returns_default_music_type(self):
        """Unknown provider prefix falls back to generic 'music' content type."""
        assert get_media_content_type("unknown:track:abc123") == "music"

    def test_uri_without_colon_returns_default_music_type(self):
        """URI without colon separator returns default 'music' type."""
        assert get_media_content_type("simplestring") == "music"

    def test_case_insensitive_provider_detection(self):
        """Provider detection is case-insensitive."""
        assert get_media_content_type("SPOTIFY:track:abc123") == "spotify"
        assert get_media_content_type("Spotify:track:abc123") == "spotify"


@pytest.mark.unit
class TestMediaPlayerServiceProviderPlayback:
    """Tests for playback with different providers (Story 16.2).

    AC #3: Sonos speaker playback works as before (no regression)
    AC #4: Chromecast device playback works as before (no regression)
    """

    @pytest.mark.asyncio
    async def test_play_song_with_http_url_uses_music_type(self, mock_hass):
        """play_song with HTTP URL uses 'music' content type (Sonos/Chromecast)."""
        service = MediaPlayerService(mock_hass, "media_player.sonos_speaker")

        result = await service.play_song("http://example.com/song.mp3")

        assert result is True
        mock_hass.services.async_call.assert_called_once_with(
            "media_player",
            "play_media",
            {
                "entity_id": "media_player.sonos_speaker",
                "media_content_id": "http://example.com/song.mp3",
                "media_content_type": "music",  # Generic type for HTTP URLs
            },
            blocking=True,
        )

    @pytest.mark.asyncio
    async def test_play_song_with_spotify_playlist_uri(self, mock_hass):
        """play_song with Spotify playlist URI uses 'spotify' content type."""
        service = MediaPlayerService(mock_hass, "media_player.alexa_echo")

        result = await service.play_song("spotify:playlist:37i9dQZF1DXcBWIGoYBM5M")

        assert result is True
        call_args = mock_hass.services.async_call.call_args
        assert call_args[0][2]["media_content_type"] == "spotify"
