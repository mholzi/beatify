"""Playlist discovery and validation for Beatify."""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from custom_components.beatify.const import (
    PLAYLIST_DIR,
    PROVIDER_APPLE_MUSIC,
    PROVIDER_DEFAULT,
    PROVIDER_SPOTIFY,
    PROVIDER_YOUTUBE_MUSIC,
    URI_PATTERN_APPLE_MUSIC,
    URI_PATTERN_SPOTIFY,
    URI_PATTERN_YOUTUBE_MUSIC,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class PlaylistManager:
    """Manages song selection and played tracking."""

    def __init__(self, songs: list[dict[str, Any]], provider: str = PROVIDER_DEFAULT) -> None:
        """
        Initialize with list of songs from loaded playlists.

        Each song dict must have: year, and at least one valid URI field
        Optional fields: fun_fact, fun_fact_de, fun_fact_es, awards, awards_de, awards_es

        Args:
            songs: List of song dictionaries
            provider: Music provider to use (PROVIDER_SPOTIFY or PROVIDER_APPLE_MUSIC)

        """
        self._provider = provider
        total_count = len(songs)
        filtered_songs, _ = filter_songs_for_provider(songs, provider)
        self._songs = filtered_songs
        self._played_uris: set[str] = set()
        _LOGGER.info(
            "PlaylistManager: %d/%d songs available for %s",
            len(self._songs),
            total_count,
            provider,
        )

    def get_next_song(self) -> dict[str, Any] | None:
        """
        Get random unplayed song.

        Returns:
            Song dict with _resolved_uri added, or None if all songs played

        """
        available = [
            s for s in self._songs if get_song_uri(s, self._provider) not in self._played_uris
        ]
        if not available:
            return None
        song = random.choice(available)  # noqa: S311
        # Add resolved URI to returned song dict
        song_copy = song.copy()
        song_copy["_resolved_uri"] = get_song_uri(song, self._provider)
        return song_copy

    def mark_played(self, uri: str) -> None:
        """
        Mark a song as played.

        Args:
            uri: Song URI to mark as played

        """
        self._played_uris.add(uri)

    def reset(self) -> None:
        """Reset played tracking for new game."""
        self._played_uris.clear()

    def is_exhausted(self) -> bool:
        """
        Check if all songs have been played.

        Returns:
            True if all songs have been played

        """
        return len(self._played_uris) >= len(self._songs)

    def get_remaining_count(self) -> int:
        """
        Get count of unplayed songs.

        Returns:
            Number of songs not yet played

        """
        return len(self._songs) - len(self._played_uris)

    def get_total_count(self) -> int:
        """
        Get total song count.

        Returns:
            Total number of songs in playlist

        """
        return len(self._songs)


# Validation constants
MIN_YEAR = 1900
MAX_YEAR = 2030

# Supported languages for localized content
SUPPORTED_LANGUAGES = ("en", "de", "es")


def get_localized_field(song: dict[str, Any], field: str, language: str) -> str | list[str] | None:
    """
    Get localized field value with English fallback.

    Args:
        song: Song dictionary
        field: Base field name (e.g., 'fun_fact', 'awards')
        language: Language code ('en', 'de', 'es')

    Returns:
        Localized value or English fallback, or None if neither exists

    """
    # Try localized field first (for non-English)
    if language != "en":
        localized_key = f"{field}_{language}"
        if song.get(localized_key):
            return song[localized_key]

    # Fallback to base field (English)
    return song.get(field)


def get_playlist_directory(hass: HomeAssistant) -> Path:
    """Get the playlist directory path."""
    return Path(hass.config.path(PLAYLIST_DIR))


async def async_ensure_playlist_directory(hass: HomeAssistant) -> Path:
    """Ensure playlist directory exists, create if missing."""
    playlist_dir = get_playlist_directory(hass)

    if not playlist_dir.exists():
        playlist_dir.mkdir(parents=True, exist_ok=True)
        _LOGGER.info("Created playlist directory: %s", playlist_dir)

    # Copy bundled playlists if they don't exist in destination
    await _copy_bundled_playlists(playlist_dir)

    return playlist_dir


def _get_playlist_version(path: Path) -> str:
    """Get version from playlist file. Returns '0.0' if no version field."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("version", "0.0")
    except Exception:  # noqa: BLE001
        return "0.0"


def _compare_versions(v1: str, v2: str) -> int:
    """Compare version strings. Returns: -1 if v1<v2, 0 if equal, 1 if v1>v2."""

    def parse(v: str) -> tuple[int, ...]:
        return tuple(int(x) for x in v.split("."))

    try:
        p1, p2 = parse(v1), parse(v2)
        if p1 < p2:
            return -1
        if p1 > p2:
            return 1
        return 0
    except ValueError:
        return 0


async def _copy_bundled_playlists(dest_dir: Path) -> None:
    """Copy bundled playlists to destination, updating if bundled version is newer."""
    # Bundled playlists are in custom_components/beatify/playlists/
    bundled_dir = Path(__file__).parent.parent / "playlists"

    if not bundled_dir.exists():
        return

    def _copy_file(src: Path, dst: Path) -> None:
        """Copy file contents (runs in executor)."""
        content = src.read_text(encoding="utf-8")
        dst.write_text(content, encoding="utf-8")

    def _get_versions(src: Path, dst: Path) -> tuple[str, str]:
        """Get versions from both files (runs in executor)."""
        bundled_ver = _get_playlist_version(src)
        existing_ver = _get_playlist_version(dst) if dst.exists() else "0.0"
        return bundled_ver, existing_ver

    loop = asyncio.get_event_loop()

    for playlist_file in bundled_dir.glob("*.json"):
        dest_file = dest_dir / playlist_file.name
        try:
            # Get versions
            bundled_ver, existing_ver = await loop.run_in_executor(
                None, _get_versions, playlist_file, dest_file
            )

            if not dest_file.exists():
                # New playlist - copy it
                await loop.run_in_executor(None, _copy_file, playlist_file, dest_file)
                _LOGGER.info("Copied bundled playlist %s (v%s)", playlist_file.name, bundled_ver)
            elif _compare_versions(bundled_ver, existing_ver) > 0:
                # Bundled version is newer - update
                await loop.run_in_executor(None, _copy_file, playlist_file, dest_file)
                _LOGGER.info(
                    "Updated playlist %s: v%s -> v%s",
                    playlist_file.name,
                    existing_ver,
                    bundled_ver,
                )
            else:
                _LOGGER.debug("Playlist %s is up to date (v%s)", playlist_file.name, existing_ver)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Failed to process playlist %s: %s", playlist_file.name, err)


def validate_playlist(data: dict[str, Any]) -> tuple[bool, list[str]]:
    """Validate playlist structure. Returns (is_valid, list_of_errors)."""
    errors: list[str] = []

    # Check required top-level fields
    if not isinstance(data.get("name"), str) or not data["name"].strip():
        errors.append("Missing or empty 'name' field")

    songs = data.get("songs")
    if not isinstance(songs, list):
        errors.append("Missing or invalid 'songs' array")
        return (False, errors)

    if len(songs) == 0:
        errors.append("Playlist has no songs")

    # Validate each song
    for i, song in enumerate(songs):
        if not isinstance(song, dict):
            errors.append(f"Song {i + 1}: not a valid object")
            continue

        # Check year
        year = song.get("year")
        if not isinstance(year, int):
            errors.append(f"Song {i + 1}: missing or invalid 'year' (must be integer)")
        elif not (MIN_YEAR <= year <= MAX_YEAR):
            errors.append(f"Song {i + 1}: year {year} out of range")

        # Check URIs - validate patterns and ensure at least one valid URI exists
        has_valid_uri = False

        # Check legacy 'uri' field (Spotify pattern)
        uri = song.get("uri")
        if isinstance(uri, str) and uri.strip():
            if re.match(URI_PATTERN_SPOTIFY, uri):
                has_valid_uri = True
            else:
                errors.append(
                    f"Song {i + 1}: 'uri' invalid (expected spotify:track:{{22-char-id}})"
                )

        # Check 'uri_spotify' field
        uri_spotify = song.get("uri_spotify")
        if isinstance(uri_spotify, str) and uri_spotify.strip():
            if re.match(URI_PATTERN_SPOTIFY, uri_spotify):
                has_valid_uri = True
            else:
                errors.append(
                    f"Song {i + 1}: 'uri_spotify' invalid (expected spotify:track:{{22-char-id}})"
                )

        # Check 'uri_apple_music' field
        uri_apple_music = song.get("uri_apple_music")
        if isinstance(uri_apple_music, str) and uri_apple_music.strip():
            if re.match(URI_PATTERN_APPLE_MUSIC, uri_apple_music):
                has_valid_uri = True
            else:
                errors.append(
                    f"Song {i + 1}: 'uri_apple_music' invalid (expected applemusic://track/id)"
                )

        # Check 'uri_youtube_music' field
        uri_youtube_music = song.get("uri_youtube_music")
        if isinstance(uri_youtube_music, str) and uri_youtube_music.strip():
            if re.match(URI_PATTERN_YOUTUBE_MUSIC, uri_youtube_music):
                has_valid_uri = True
            else:
                errors.append(
                    f"Song {i + 1}: 'uri_youtube_music' invalid (expected https://music.youtube.com/watch?v=...)"
                )

        # Error if no valid URI found
        if not has_valid_uri:
            errors.append(f"Song {i + 1}: no valid URI")

        # Story 20.2: Validate alt_artists if present (optional field)
        alt_artists = song.get("alt_artists")
        if alt_artists is not None:
            if not isinstance(alt_artists, list):
                errors.append(f"Song {i + 1}: 'alt_artists' must be an array")
            else:
                for j, alt in enumerate(alt_artists):
                    if not isinstance(alt, str) or not alt.strip():
                        errors.append(f"Song {i + 1}: 'alt_artists[{j}]' must be non-empty string")
                # Log warning if fewer than 2 alternatives (weak challenge)
                valid_alts = [a for a in alt_artists if isinstance(a, str) and a.strip()]
                if len(valid_alts) < 2:
                    _LOGGER.debug(
                        "Song %d has only %d alt_artists (2 recommended)",
                        i + 1,
                        len(valid_alts),
                    )

    return (len(errors) == 0, errors)


def get_song_uri(song: dict[str, Any], provider: str) -> str | None:
    """
    Get the URI for a song based on the provider.

    Args:
        song: Song dictionary with uri fields
        provider: Provider identifier (PROVIDER_SPOTIFY, PROVIDER_APPLE_MUSIC, or PROVIDER_YOUTUBE_MUSIC)

    Returns:
        URI string for the provider, or None if not available

    """
    if provider == PROVIDER_SPOTIFY:
        # For Spotify, prefer uri_spotify, fall back to legacy uri field
        return song.get("uri_spotify") or song.get("uri") or None
    if provider == PROVIDER_APPLE_MUSIC:
        # For Apple Music, only use uri_apple_music
        return song.get("uri_apple_music") or None
    if provider == PROVIDER_YOUTUBE_MUSIC:
        # For YouTube Music, only use uri_youtube_music
        return song.get("uri_youtube_music") or None
    return None


def filter_songs_for_provider(
    songs: list[dict[str, Any]], provider: str
) -> tuple[list[dict[str, Any]], int]:
    """
    Filter songs to only those available for the specified provider.

    Args:
        songs: List of song dictionaries
        provider: Provider identifier (PROVIDER_SPOTIFY or PROVIDER_APPLE_MUSIC)

    Returns:
        Tuple of (filtered_songs, skipped_count)

    """
    filtered: list[dict[str, Any]] = []
    skipped = 0

    for song in songs:
        uri = get_song_uri(song, provider)
        if uri:
            filtered.append(song)
        else:
            year = song.get("year", "unknown")
            _LOGGER.warning("Skipping song (year %s) - no URI for provider '%s'", year, provider)
            skipped += 1

    return (filtered, skipped)


async def async_discover_playlists(hass: HomeAssistant) -> list[dict]:
    """Discover all playlist files in the playlist directory."""
    playlist_dir = get_playlist_directory(hass)
    playlists: list[dict] = []

    if not playlist_dir.exists():
        _LOGGER.debug("Playlist directory does not exist: %s", playlist_dir)
        return playlists

    def _read_file(path: Path) -> str:
        """Read file contents (runs in executor)."""
        return path.read_text(encoding="utf-8")

    loop = asyncio.get_event_loop()

    for json_file in playlist_dir.glob("*.json"):
        try:
            content = await loop.run_in_executor(None, _read_file, json_file)
            data = json.loads(content)
            is_valid, errors = validate_playlist(data)

            # Count songs per provider (Story 17.1)
            songs = data.get("songs", [])
            spotify_count = sum(1 for s in songs if s.get("uri") or s.get("uri_spotify"))
            apple_music_count = sum(1 for s in songs if s.get("uri_apple_music"))
            youtube_music_count = sum(1 for s in songs if s.get("uri_youtube_music"))

            playlists.append(
                {
                    "path": str(json_file),
                    "filename": json_file.name,
                    "name": data.get("name", json_file.stem),
                    "tags": data.get("tags", []),  # Issue #70: Tag-based filtering
                    "song_count": len(songs),
                    "spotify_count": spotify_count,
                    "apple_music_count": apple_music_count,
                    "youtube_music_count": youtube_music_count,
                    "is_valid": is_valid,
                    "errors": errors,
                }
            )
        except json.JSONDecodeError as e:
            playlists.append(
                {
                    "path": str(json_file),
                    "filename": json_file.name,
                    "name": json_file.stem,
                    "tags": [],  # Issue #70
                    "song_count": 0,
                    "spotify_count": 0,
                    "apple_music_count": 0,
                    "youtube_music_count": 0,
                    "is_valid": False,
                    "errors": [f"Invalid JSON: {e}"],
                }
            )

    _LOGGER.debug("Found %d playlists", len(playlists))
    return playlists


async def async_load_and_validate_playlist(
    path: str | Path,
) -> tuple[dict | None, list[str]]:
    """Load and validate a playlist file."""
    path = Path(path)

    if not path.exists():
        return (None, [f"File not found: {path}"])

    def _read_file(p: Path) -> str:
        """Read file contents (runs in executor)."""
        return p.read_text(encoding="utf-8")

    try:
        content = await asyncio.get_event_loop().run_in_executor(None, _read_file, path)
        data = json.loads(content)
    except json.JSONDecodeError as e:
        return (None, [f"Invalid JSON: {e}"])

    is_valid, errors = validate_playlist(data)

    if is_valid:
        return (data, [])
    return (None, errors)
