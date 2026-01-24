"""
Unit Tests: PlaylistManager

Tests song selection and tracking for Epic 4 gameplay:
- Random unplayed song selection
- Marking songs as played
- Exhaustion detection
- Reset for new games

Story 4.1 - AC: #3, #4, #5
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock

import pytest

# Mock homeassistant before importing beatify modules
sys.modules["homeassistant"] = MagicMock()
sys.modules["homeassistant.core"] = MagicMock()
sys.modules["homeassistant.components"] = MagicMock()
sys.modules["homeassistant.components.http"] = MagicMock()
sys.modules["homeassistant.components.frontend"] = MagicMock()
sys.modules["homeassistant.config_entries"] = MagicMock()
sys.modules["homeassistant.const"] = MagicMock()
sys.modules["homeassistant.helpers"] = MagicMock()
sys.modules["homeassistant.helpers.typing"] = MagicMock()

from custom_components.beatify.game.playlist import (
    PlaylistManager,
    get_localized_field,
    SUPPORTED_LANGUAGES,
)


@pytest.mark.unit
class TestPlaylistManagerSelection:
    """Tests for song selection logic."""

    def test_get_next_song_returns_song_from_pool(self):
        """get_next_song returns a song from the available pool."""
        songs = [
            {"year": 1985, "uri": "spotify:track:1", "fun_fact": "Fact 1"},
            {"year": 1990, "uri": "spotify:track:2", "fun_fact": "Fact 2"},
            {"year": 1995, "uri": "spotify:track:3", "fun_fact": "Fact 3"},
        ]
        manager = PlaylistManager(songs)

        song = manager.get_next_song()

        assert song is not None
        assert song["uri"] in ["spotify:track:1", "spotify:track:2", "spotify:track:3"]

    def test_get_next_song_excludes_played_songs(self):
        """get_next_song excludes songs that have been marked as played."""
        songs = [
            {"year": 1985, "uri": "spotify:track:1", "fun_fact": "Fact 1"},
            {"year": 1990, "uri": "spotify:track:2", "fun_fact": "Fact 2"},
        ]
        manager = PlaylistManager(songs)

        # Mark first song as played
        manager.mark_played("spotify:track:1")

        # Get next song - should only return the unplayed one
        song = manager.get_next_song()

        assert song is not None
        assert song["uri"] == "spotify:track:2"

    def test_get_next_song_returns_none_when_all_played(self):
        """get_next_song returns None when all songs have been played."""
        songs = [
            {"year": 1985, "uri": "spotify:track:1", "fun_fact": "Fact 1"},
            {"year": 1990, "uri": "spotify:track:2", "fun_fact": "Fact 2"},
        ]
        manager = PlaylistManager(songs)

        # Mark all songs as played
        manager.mark_played("spotify:track:1")
        manager.mark_played("spotify:track:2")

        song = manager.get_next_song()

        assert song is None


@pytest.mark.unit
class TestPlaylistManagerTracking:
    """Tests for played song tracking."""

    def test_mark_played_adds_to_played_set(self):
        """mark_played adds URI to the played set."""
        songs = [{"year": 1985, "uri": "spotify:track:1", "fun_fact": "Fact 1"}]
        manager = PlaylistManager(songs)

        manager.mark_played("spotify:track:1")

        assert "spotify:track:1" in manager._played_uris

    def test_is_exhausted_returns_false_initially(self):
        """is_exhausted returns False when songs remain."""
        songs = [
            {"year": 1985, "uri": "spotify:track:1", "fun_fact": "Fact 1"},
            {"year": 1990, "uri": "spotify:track:2", "fun_fact": "Fact 2"},
        ]
        manager = PlaylistManager(songs)

        assert manager.is_exhausted() is False

    def test_is_exhausted_returns_true_when_all_played(self):
        """is_exhausted returns True when all songs have been played."""
        songs = [
            {"year": 1985, "uri": "spotify:track:1", "fun_fact": "Fact 1"},
            {"year": 1990, "uri": "spotify:track:2", "fun_fact": "Fact 2"},
        ]
        manager = PlaylistManager(songs)

        manager.mark_played("spotify:track:1")
        manager.mark_played("spotify:track:2")

        assert manager.is_exhausted() is True


@pytest.mark.unit
class TestPlaylistManagerReset:
    """Tests for reset functionality."""

    def test_reset_clears_played_songs(self):
        """reset clears all played song tracking."""
        songs = [
            {"year": 1985, "uri": "spotify:track:1", "fun_fact": "Fact 1"},
            {"year": 1990, "uri": "spotify:track:2", "fun_fact": "Fact 2"},
        ]
        manager = PlaylistManager(songs)

        # Mark songs as played
        manager.mark_played("spotify:track:1")
        manager.mark_played("spotify:track:2")
        assert manager.is_exhausted() is True

        # Reset
        manager.reset()

        assert manager.is_exhausted() is False
        assert manager.get_remaining_count() == 2

    def test_get_remaining_count(self):
        """get_remaining_count returns correct count."""
        songs = [
            {"year": 1985, "uri": "spotify:track:1", "fun_fact": "Fact 1"},
            {"year": 1990, "uri": "spotify:track:2", "fun_fact": "Fact 2"},
            {"year": 1995, "uri": "spotify:track:3", "fun_fact": "Fact 3"},
        ]
        manager = PlaylistManager(songs)

        assert manager.get_remaining_count() == 3

        manager.mark_played("spotify:track:1")
        assert manager.get_remaining_count() == 2

        manager.mark_played("spotify:track:2")
        assert manager.get_remaining_count() == 1

    def test_get_total_count(self):
        """get_total_count returns total song count."""
        songs = [
            {"year": 1985, "uri": "spotify:track:1", "fun_fact": "Fact 1"},
            {"year": 1990, "uri": "spotify:track:2", "fun_fact": "Fact 2"},
        ]
        manager = PlaylistManager(songs)

        assert manager.get_total_count() == 2

        # Total count should not change when songs are played
        manager.mark_played("spotify:track:1")
        assert manager.get_total_count() == 2


@pytest.mark.unit
class TestPlaylistManagerImmutability:
    """Tests for ensuring original songs list is not mutated."""

    def test_songs_list_not_mutated(self):
        """Original songs list should not be mutated."""
        original_songs = [
            {"year": 1985, "uri": "spotify:track:1", "fun_fact": "Fact 1"},
        ]
        manager = PlaylistManager(original_songs)

        manager.mark_played("spotify:track:1")

        # Original list should be unchanged
        assert len(original_songs) == 1


@pytest.mark.unit
class TestLocalizedContent:
    """Tests for localized content retrieval (Story 16.1, 16.3)."""

    def test_supported_languages_includes_de_es(self):
        """SUPPORTED_LANGUAGES includes German and Spanish."""
        assert "en" in SUPPORTED_LANGUAGES
        assert "de" in SUPPORTED_LANGUAGES
        assert "es" in SUPPORTED_LANGUAGES

    def test_get_localized_field_english_returns_base_field(self):
        """get_localized_field returns base field for English."""
        song = {
            "fun_fact": "English fun fact",
            "fun_fact_de": "German fun fact",
            "fun_fact_es": "Spanish fun fact",
        }
        result = get_localized_field(song, "fun_fact", "en")
        assert result == "English fun fact"

    def test_get_localized_field_german_returns_german_field(self):
        """get_localized_field returns German field when available."""
        song = {
            "fun_fact": "English fun fact",
            "fun_fact_de": "German fun fact",
        }
        result = get_localized_field(song, "fun_fact", "de")
        assert result == "German fun fact"

    def test_get_localized_field_spanish_returns_spanish_field(self):
        """get_localized_field returns Spanish field when available."""
        song = {
            "fun_fact": "English fun fact",
            "fun_fact_es": "Spanish fun fact",
        }
        result = get_localized_field(song, "fun_fact", "es")
        assert result == "Spanish fun fact"

    def test_get_localized_field_falls_back_to_english(self):
        """get_localized_field falls back to English when localized not available."""
        song = {
            "fun_fact": "English fun fact",
        }
        # German not available, should fall back to English
        result = get_localized_field(song, "fun_fact", "de")
        assert result == "English fun fact"

        # Spanish not available, should fall back to English
        result = get_localized_field(song, "fun_fact", "es")
        assert result == "English fun fact"

    def test_get_localized_field_returns_none_when_missing(self):
        """get_localized_field returns None when field is missing entirely."""
        song = {"year": 1985, "uri": "spotify:track:1"}
        result = get_localized_field(song, "fun_fact", "en")
        assert result is None

    def test_get_localized_field_with_awards_array(self):
        """get_localized_field works with array fields like awards."""
        song = {
            "awards": ["Grammy Award", "MTV Award"],
            "awards_de": ["Grammy Auszeichnung", "MTV Preis"],
            "awards_es": ["Premio Grammy", "Premio MTV"],
        }
        # English
        result = get_localized_field(song, "awards", "en")
        assert result == ["Grammy Award", "MTV Award"]

        # German
        result = get_localized_field(song, "awards", "de")
        assert result == ["Grammy Auszeichnung", "MTV Preis"]

        # Spanish
        result = get_localized_field(song, "awards", "es")
        assert result == ["Premio Grammy", "Premio MTV"]

    def test_get_localized_field_empty_localized_falls_back(self):
        """get_localized_field falls back when localized field is empty."""
        song = {
            "fun_fact": "English fun fact",
            "fun_fact_de": "",  # Empty string should fall back
        }
        result = get_localized_field(song, "fun_fact", "de")
        assert result == "English fun fact"

    def test_get_localized_field_none_localized_falls_back(self):
        """get_localized_field falls back when localized field is None."""
        song = {
            "fun_fact": "English fun fact",
            "fun_fact_es": None,  # None should fall back
        }
        result = get_localized_field(song, "fun_fact", "es")
        assert result == "English fun fact"
