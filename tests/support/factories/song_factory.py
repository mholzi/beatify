"""
Song Factory - Generate test song/track data.

Mirrors the Music Assistant track format used by Beatify.

Usage:
    from tests.support.factories.song_factory import create_song

    # Default song
    song = create_song()

    # Specific song
    song = create_song(title="Last Christmas", artist="Wham!", year=1984)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any


@dataclass
class Song:
    """Song/track data model for testing."""

    id: str
    title: str
    artist: str
    album: str
    year: int
    album_art_url: str | None = None
    duration_ms: int = 180000  # 3 minutes default

    def to_dict(self) -> dict[str, Any]:
        """Serialize for WebSocket messages."""
        return {
            "id": self.id,
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "year": self.year,
            "album_art": self.album_art_url,
            "duration_ms": self.duration_ms,
        }


# Sample songs from different decades for testing
SAMPLE_SONGS = [
    {"title": "Bohemian Rhapsody", "artist": "Queen", "album": "A Night at the Opera", "year": 1975},
    {"title": "Billie Jean", "artist": "Michael Jackson", "album": "Thriller", "year": 1982},
    {"title": "Last Christmas", "artist": "Wham!", "album": "Music from the Edge", "year": 1984},
    {"title": "Smells Like Teen Spirit", "artist": "Nirvana", "album": "Nevermind", "year": 1991},
    {"title": "Wonderwall", "artist": "Oasis", "album": "(What's the Story)", "year": 1995},
    {"title": "Crazy in Love", "artist": "Beyonce", "album": "Dangerously in Love", "year": 2003},
    {"title": "Rolling in the Deep", "artist": "Adele", "album": "21", "year": 2011},
    {"title": "Blinding Lights", "artist": "The Weeknd", "album": "After Hours", "year": 2020},
]


def create_song(**overrides: Any) -> Song:
    """Create a test song with sensible defaults.

    Args:
        **overrides: Any Song field to override

    Returns:
        Song instance with merged defaults and overrides

    Examples:
        # Default song
        song = create_song()

        # Specific song
        xmas = create_song(title="Last Christmas", artist="Wham!", year=1984)

        # Song from specific year (for testing year guessing)
        old_song = create_song(year=1975)
    """
    defaults = {
        "id": f"track-{uuid.uuid4().hex[:8]}",
        "title": f"Test Song {uuid.uuid4().hex[:4]}",
        "artist": "Test Artist",
        "album": "Test Album",
        "year": 1990,
        "album_art_url": "https://example.com/default-art.jpg",
        "duration_ms": 180000,
    }
    defaults.update(overrides)
    return Song(**defaults)


def create_song_from_sample(index: int = 0, **overrides: Any) -> Song:
    """Create a song from the sample library.

    Args:
        index: Index into SAMPLE_SONGS (0-7)
        **overrides: Additional overrides

    Returns:
        Song with realistic data
    """
    sample = SAMPLE_SONGS[index % len(SAMPLE_SONGS)]
    return create_song(**sample, **overrides)


def create_playlist(count: int = 10) -> list[Song]:
    """Create a playlist of test songs.

    Cycles through SAMPLE_SONGS to create variety.
    """
    return [create_song_from_sample(i) for i in range(count)]
