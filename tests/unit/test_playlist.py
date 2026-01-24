"""Tests for playlist validation and multi-provider URI handling (Story 17.1)."""

from __future__ import annotations

from custom_components.beatify.const import (
    PROVIDER_APPLE_MUSIC,
    PROVIDER_PLEX,
    PROVIDER_SPOTIFY,
    PROVIDER_YOUTUBE_MUSIC,
)
from custom_components.beatify.game.playlist import (
    PlaylistManager,
    filter_songs_for_provider,
    get_song_uri,
    validate_playlist,
)

# =============================================================================
# VALIDATION TESTS
# =============================================================================


class TestValidatePlaylist:
    """Tests for validate_playlist() function."""

    def test_legacy_uri_only_loads_successfully(self):
        """AC1: Existing playlists with only 'uri' field load without modification."""
        data = {
            "name": "80s Hits",
            "songs": [
                {"year": 1984, "uri": "spotify:track:2WfaOiMkCvy7F5fcp2zZ8L"},
                {"year": 1985, "uri": "spotify:track:4uLU6hMCjMI75M1A2tKUQC"},
            ],
        }
        is_valid, errors = validate_playlist(data)
        assert is_valid is True
        assert errors == []

    def test_uri_spotify_and_uri_apple_music_validates(self):
        """AC2: Playlists with uri_spotify and/or uri_apple_music fields validate correctly."""
        data = {
            "name": "Multi-Provider Playlist",
            "songs": [
                {
                    "year": 1985,
                    "uri_spotify": "spotify:track:2WfaOiMkCvy7F5fcp2zZ8L",
                    "uri_apple_music": "applemusic://track/1035048414",
                },
            ],
        }
        is_valid, errors = validate_playlist(data)
        assert is_valid is True
        assert errors == []

    def test_mixed_uri_fields_validates(self):
        """Playlist with mix of legacy uri and new fields validates."""
        data = {
            "name": "Mixed Playlist",
            "songs": [
                # Legacy format
                {"year": 1984, "uri": "spotify:track:2WfaOiMkCvy7F5fcp2zZ8L"},
                # New format - Spotify only
                {"year": 1985, "uri_spotify": "spotify:track:4uLU6hMCjMI75M1A2tKUQC"},
                # New format - Apple Music only
                {"year": 1986, "uri_apple_music": "applemusic://track/1035048414"},
                # New format - both providers
                {
                    "year": 1987,
                    "uri_spotify": "spotify:track:5ChkMS8OtdzJeqyybCc9R5",
                    "uri_apple_music": "applemusic://track/1234567890",
                },
            ],
        }
        is_valid, errors = validate_playlist(data)
        assert is_valid is True
        assert errors == []

    def test_invalid_apple_music_pattern_rejected(self):
        """AC3: Apple Music URIs must match pattern applemusic://track/{numeric-id}."""
        data = {
            "name": "Invalid Apple Music",
            "songs": [
                {
                    "year": 1985,
                    "uri_apple_music": "applemusic://album/1035048414",  # Invalid: album not track
                },
            ],
        }
        is_valid, errors = validate_playlist(data)
        assert is_valid is False
        assert len(errors) == 2  # Invalid pattern + no valid URI
        assert "uri_apple_music" in errors[0]
        assert "applemusic://track/id" in errors[0]

    def test_invalid_spotify_pattern_rejected(self):
        """Spotify URIs must match pattern spotify:track:{22-char-id}."""
        data = {
            "name": "Invalid Spotify",
            "songs": [
                {
                    "year": 1985,
                    "uri": "spotify:album:2WfaOiMkCvy7F5fcp2zZ8L",  # Invalid: album not track
                },
            ],
        }
        is_valid, errors = validate_playlist(data)
        assert is_valid is False
        assert len(errors) == 2  # Invalid pattern + no valid URI
        assert "'uri' invalid" in errors[0]

    def test_no_valid_uri_reports_error(self):
        """AC4: Songs without any valid URI are logged but don't fail entirely."""
        data = {
            "name": "No URI Playlist",
            "songs": [
                {"year": 1985},  # Missing all URI fields
            ],
        }
        is_valid, errors = validate_playlist(data)
        assert is_valid is False
        assert "Song 1: no valid URI" in errors

    def test_empty_uri_string_reports_no_valid_uri(self):
        """Empty string URIs are treated as missing."""
        data = {
            "name": "Empty URI",
            "songs": [
                {"year": 1985, "uri": ""},
            ],
        }
        is_valid, errors = validate_playlist(data)
        assert is_valid is False
        assert "Song 1: no valid URI" in errors

    def test_youtube_music_uri_validates(self):
        """YouTube Music URIs validate correctly."""
        data = {
            "name": "YouTube Music Playlist",
            "songs": [
                {
                    "year": 1985,
                    "uri_youtube_music": "ytmusic://track/dQw4w9WgXcQ",
                },
            ],
        }
        is_valid, errors = validate_playlist(data)
        assert is_valid is True
        assert errors == []

    def test_plex_uri_validates(self):
        """Plex URIs validate correctly."""
        data = {
            "name": "Plex Playlist",
            "songs": [
                {
                    "year": 1985,
                    "uri_plex": "plex://track/12345",
                },
            ],
        }
        is_valid, errors = validate_playlist(data)
        assert is_valid is True
        assert errors == []

    def test_all_providers_uri_validates(self):
        """Playlists with all provider URIs validate correctly."""
        data = {
            "name": "All Providers Playlist",
            "songs": [
                {
                    "year": 1985,
                    "uri_spotify": "spotify:track:2WfaOiMkCvy7F5fcp2zZ8L",
                    "uri_apple_music": "applemusic://track/1035048414",
                    "uri_youtube_music": "ytmusic://track/dQw4w9WgXcQ",
                    "uri_plex": "plex://track/12345",
                },
            ],
        }
        is_valid, errors = validate_playlist(data)
        assert is_valid is True
        assert errors == []

    def test_invalid_youtube_music_pattern_rejected(self):
        """YouTube Music URIs must match pattern ytmusic://track/{id}."""
        data = {
            "name": "Invalid YouTube Music",
            "songs": [
                {
                    "year": 1985,
                    "uri_youtube_music": "ytmusic://album/abc123",  # Invalid: album not track
                },
            ],
        }
        is_valid, errors = validate_playlist(data)
        assert is_valid is False
        assert len(errors) == 2  # Invalid pattern + no valid URI
        assert "uri_youtube_music" in errors[0]
        assert "ytmusic://track/id" in errors[0]

    def test_invalid_plex_pattern_rejected(self):
        """Plex URIs must match pattern plex://track/{id}."""
        data = {
            "name": "Invalid Plex",
            "songs": [
                {
                    "year": 1985,
                    "uri_plex": "plex://album/abc123",  # Invalid: album not track
                },
            ],
        }
        is_valid, errors = validate_playlist(data)
        assert is_valid is False
        assert len(errors) == 2  # Invalid pattern + no valid URI
        assert "uri_plex" in errors[0]
        assert "plex://track/id" in errors[0]


# =============================================================================
# GET_SONG_URI TESTS
# =============================================================================


class TestGetSongUri:
    """Tests for get_song_uri() function."""

    def test_spotify_provider_returns_uri_spotify(self):
        """For Spotify, prefer uri_spotify field."""
        song = {
            "year": 1985,
            "uri_spotify": "spotify:track:SPOTIFY123456789012",
            "uri_apple_music": "applemusic://track/1234567890",
        }
        result = get_song_uri(song, PROVIDER_SPOTIFY)
        assert result == "spotify:track:SPOTIFY123456789012"

    def test_spotify_provider_falls_back_to_legacy_uri(self):
        """AC1: For Spotify, fall back to legacy 'uri' field."""
        song = {
            "year": 1985,
            "uri": "spotify:track:LEGACY1234567890123",
        }
        result = get_song_uri(song, PROVIDER_SPOTIFY)
        assert result == "spotify:track:LEGACY1234567890123"

    def test_spotify_provider_prefers_uri_spotify_over_legacy(self):
        """uri_spotify takes precedence over legacy uri."""
        song = {
            "year": 1985,
            "uri": "spotify:track:LEGACY1234567890123",
            "uri_spotify": "spotify:track:PREFERRED678901234",
        }
        result = get_song_uri(song, PROVIDER_SPOTIFY)
        assert result == "spotify:track:PREFERRED678901234"

    def test_apple_music_provider_returns_uri_apple_music(self):
        """For Apple Music, return uri_apple_music field."""
        song = {
            "year": 1985,
            "uri": "spotify:track:SPOTIFY123456789012",
            "uri_apple_music": "applemusic://track/1234567890",
        }
        result = get_song_uri(song, PROVIDER_APPLE_MUSIC)
        assert result == "applemusic://track/1234567890"

    def test_apple_music_provider_returns_none_without_field(self):
        """For Apple Music, return None if uri_apple_music not present."""
        song = {
            "year": 1985,
            "uri": "spotify:track:SPOTIFY123456789012",
        }
        result = get_song_uri(song, PROVIDER_APPLE_MUSIC)
        assert result is None

    def test_unknown_provider_returns_none(self):
        """Unknown provider returns None."""
        song = {
            "year": 1985,
            "uri": "spotify:track:SPOTIFY123456789012",
            "uri_apple_music": "applemusic://track/1234567890",
        }
        result = get_song_uri(song, "unknown_provider")
        assert result is None

    def test_youtube_music_provider_returns_uri_youtube_music(self):
        """For YouTube Music, return uri_youtube_music field."""
        song = {
            "year": 1985,
            "uri": "spotify:track:SPOTIFY123456789012",
            "uri_youtube_music": "ytmusic://track/dQw4w9WgXcQ",
        }
        result = get_song_uri(song, PROVIDER_YOUTUBE_MUSIC)
        assert result == "ytmusic://track/dQw4w9WgXcQ"

    def test_youtube_music_provider_returns_none_without_field(self):
        """For YouTube Music, return None if uri_youtube_music not present."""
        song = {
            "year": 1985,
            "uri": "spotify:track:SPOTIFY123456789012",
        }
        result = get_song_uri(song, PROVIDER_YOUTUBE_MUSIC)
        assert result is None

    def test_plex_provider_returns_uri_plex(self):
        """For Plex, return uri_plex field."""
        song = {
            "year": 1985,
            "uri": "spotify:track:SPOTIFY123456789012",
            "uri_plex": "plex://track/12345",
        }
        result = get_song_uri(song, PROVIDER_PLEX)
        assert result == "plex://track/12345"

    def test_plex_provider_returns_none_without_field(self):
        """For Plex, return None if uri_plex not present."""
        song = {
            "year": 1985,
            "uri": "spotify:track:SPOTIFY123456789012",
        }
        result = get_song_uri(song, PROVIDER_PLEX)
        assert result is None


# =============================================================================
# FILTER_SONGS_FOR_PROVIDER TESTS
# =============================================================================


class TestFilterSongsForProvider:
    """Tests for filter_songs_for_provider() function."""

    def test_filters_spotify_songs(self):
        """Filter returns songs with Spotify URIs."""
        songs = [
            {"year": 1984, "uri": "spotify:track:SONG1234567890123456"},
            {"year": 1985, "uri_apple_music": "applemusic://track/123"},
            {"year": 1986, "uri_spotify": "spotify:track:SONG2345678901234567"},
        ]
        filtered, skipped = filter_songs_for_provider(songs, PROVIDER_SPOTIFY)
        assert len(filtered) == 2
        assert skipped == 1
        assert filtered[0]["year"] == 1984
        assert filtered[1]["year"] == 1986

    def test_filters_apple_music_songs(self):
        """Filter returns songs with Apple Music URIs."""
        songs = [
            {"year": 1984, "uri": "spotify:track:SONG1234567890123456"},
            {"year": 1985, "uri_apple_music": "applemusic://track/123"},
            {"year": 1986, "uri_spotify": "spotify:track:SONG2345678901234567"},
        ]
        filtered, skipped = filter_songs_for_provider(songs, PROVIDER_APPLE_MUSIC)
        assert len(filtered) == 1
        assert skipped == 2
        assert filtered[0]["year"] == 1985

    def test_returns_correct_skipped_count(self):
        """AC4: Returns accurate skipped count."""
        songs = [
            {"year": 1984, "uri": "spotify:track:SONG1234567890123456"},
            {"year": 1985},  # No URI
            {"year": 1986},  # No URI
            {"year": 1987, "uri": "spotify:track:SONG2345678901234567"},
        ]
        filtered, skipped = filter_songs_for_provider(songs, PROVIDER_SPOTIFY)
        assert len(filtered) == 2
        assert skipped == 2

    def test_empty_list_returns_empty(self):
        """Empty song list returns empty result."""
        filtered, skipped = filter_songs_for_provider([], PROVIDER_SPOTIFY)
        assert filtered == []
        assert skipped == 0

    def test_filters_youtube_music_songs(self):
        """Filter returns songs with YouTube Music URIs."""
        songs = [
            {"year": 1984, "uri": "spotify:track:SONG1234567890123456"},
            {"year": 1985, "uri_youtube_music": "ytmusic://track/dQw4w9WgXcQ"},
            {"year": 1986, "uri_spotify": "spotify:track:SONG2345678901234567"},
        ]
        filtered, skipped = filter_songs_for_provider(songs, PROVIDER_YOUTUBE_MUSIC)
        assert len(filtered) == 1
        assert skipped == 2
        assert filtered[0]["year"] == 1985

    def test_filters_plex_songs(self):
        """Filter returns songs with Plex URIs."""
        songs = [
            {"year": 1984, "uri": "spotify:track:SONG1234567890123456"},
            {"year": 1985, "uri_plex": "plex://track/12345"},
            {"year": 1986, "uri_spotify": "spotify:track:SONG2345678901234567"},
        ]
        filtered, skipped = filter_songs_for_provider(songs, PROVIDER_PLEX)
        assert len(filtered) == 1
        assert skipped == 2
        assert filtered[0]["year"] == 1985


# =============================================================================
# PLAYLIST MANAGER TESTS
# =============================================================================


class TestPlaylistManager:
    """Tests for PlaylistManager class with multi-provider support."""

    def test_default_provider_is_spotify(self):
        """Default provider should be Spotify."""
        songs = [
            {"year": 1984, "uri": "spotify:track:SONG1234567890123456"},
        ]
        manager = PlaylistManager(songs)
        assert manager._provider == PROVIDER_SPOTIFY

    def test_filters_songs_for_provider_on_init(self):
        """PlaylistManager filters songs for the specified provider."""
        songs = [
            {"year": 1984, "uri": "spotify:track:SONG1234567890123456"},
            {"year": 1985, "uri_apple_music": "applemusic://track/123"},
            {"year": 1986, "uri_spotify": "spotify:track:SONG2345678901234567"},
        ]
        manager = PlaylistManager(songs, provider=PROVIDER_APPLE_MUSIC)
        assert manager.get_total_count() == 1

    def test_get_next_song_returns_resolved_uri(self):
        """get_next_song() includes _resolved_uri field."""
        songs = [
            {"year": 1984, "uri": "spotify:track:SONG1234567890123456"},
        ]
        manager = PlaylistManager(songs)
        song = manager.get_next_song()
        assert song is not None
        assert "_resolved_uri" in song
        assert song["_resolved_uri"] == "spotify:track:SONG1234567890123456"

    def test_get_next_song_uses_provider_specific_uri(self):
        """get_next_song() resolves URI based on provider."""
        songs = [
            {
                "year": 1984,
                "uri_spotify": "spotify:track:SPOTIFY_URI_12345678",
                "uri_apple_music": "applemusic://track/123456",
            },
        ]
        manager = PlaylistManager(songs, provider=PROVIDER_APPLE_MUSIC)
        song = manager.get_next_song()
        assert song is not None
        assert song["_resolved_uri"] == "applemusic://track/123456"

    def test_mark_played_tracks_resolved_uri(self):
        """mark_played() uses resolved URI for tracking."""
        songs = [
            {"year": 1984, "uri": "spotify:track:SONG1234567890123456"},
            {"year": 1985, "uri": "spotify:track:SONG2345678901234567"},
        ]
        manager = PlaylistManager(songs)
        song = manager.get_next_song()
        assert song is not None
        manager.mark_played(song["_resolved_uri"])
        assert manager.get_remaining_count() == 1

    def test_is_exhausted_with_filtered_songs(self):
        """is_exhausted() works correctly with filtered songs."""
        songs = [
            {"year": 1984, "uri": "spotify:track:SONG1234567890123456"},
        ]
        manager = PlaylistManager(songs, provider=PROVIDER_APPLE_MUSIC)
        # No Apple Music songs, so immediately exhausted
        assert manager.is_exhausted() is True

    def test_original_songs_not_modified(self):
        """PlaylistManager doesn't modify original song list."""
        songs = [
            {"year": 1984, "uri": "spotify:track:SONG1234567890123456"},
        ]
        original_count = len(songs)
        manager = PlaylistManager(songs)
        _ = manager.get_next_song()
        # Original list unchanged
        assert len(songs) == original_count
        # And original song dict doesn't have _resolved_uri
        assert "_resolved_uri" not in songs[0]

    def test_youtube_music_provider_filtering(self):
        """PlaylistManager correctly filters YouTube Music songs."""
        songs = [
            {"year": 1984, "uri": "spotify:track:SONG1234567890123456"},
            {"year": 1985, "uri_youtube_music": "ytmusic://track/dQw4w9WgXcQ"},
            {"year": 1986, "uri_spotify": "spotify:track:SONG2345678901234567"},
        ]
        manager = PlaylistManager(songs, provider=PROVIDER_YOUTUBE_MUSIC)
        assert manager.get_total_count() == 1

    def test_plex_provider_filtering(self):
        """PlaylistManager correctly filters Plex songs."""
        songs = [
            {"year": 1984, "uri": "spotify:track:SONG1234567890123456"},
            {"year": 1985, "uri_plex": "plex://track/12345"},
            {"year": 1986, "uri_spotify": "spotify:track:SONG2345678901234567"},
        ]
        manager = PlaylistManager(songs, provider=PROVIDER_PLEX)
        assert manager.get_total_count() == 1

    def test_youtube_music_resolved_uri(self):
        """get_next_song() resolves YouTube Music URI correctly."""
        songs = [
            {
                "year": 1984,
                "uri_spotify": "spotify:track:SPOTIFY_URI_12345678",
                "uri_youtube_music": "ytmusic://track/dQw4w9WgXcQ",
            },
        ]
        manager = PlaylistManager(songs, provider=PROVIDER_YOUTUBE_MUSIC)
        song = manager.get_next_song()
        assert song is not None
        assert song["_resolved_uri"] == "ytmusic://track/dQw4w9WgXcQ"

    def test_plex_resolved_uri(self):
        """get_next_song() resolves Plex URI correctly."""
        songs = [
            {
                "year": 1984,
                "uri_spotify": "spotify:track:SPOTIFY_URI_12345678",
                "uri_plex": "plex://track/12345",
            },
        ]
        manager = PlaylistManager(songs, provider=PROVIDER_PLEX)
        song = manager.get_next_song()
        assert song is not None
        assert song["_resolved_uri"] == "plex://track/12345"
