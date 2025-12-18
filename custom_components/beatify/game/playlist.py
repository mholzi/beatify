"""Playlist discovery and validation for Beatify."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from custom_components.beatify.const import PLAYLIST_DIR

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Validation constants
MIN_YEAR = 1900
MAX_YEAR = 2030


def get_playlist_directory(hass: HomeAssistant) -> Path:
    """Get the playlist directory path."""
    return Path(hass.config.path(PLAYLIST_DIR))


async def async_ensure_playlist_directory(hass: HomeAssistant) -> Path:
    """Ensure playlist directory exists, create if missing."""
    playlist_dir = get_playlist_directory(hass)

    if not playlist_dir.exists():
        playlist_dir.mkdir(parents=True, exist_ok=True)
        _LOGGER.info("Created playlist directory: %s", playlist_dir)

    return playlist_dir


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
            errors.append(f"Song {i+1}: not a valid object")
            continue

        # Check year
        year = song.get("year")
        if not isinstance(year, int):
            errors.append(f"Song {i+1}: missing or invalid 'year' (must be integer)")
        elif not (MIN_YEAR <= year <= MAX_YEAR):
            errors.append(f"Song {i+1}: year {year} out of range")

        # Check URI
        uri = song.get("uri")
        if not isinstance(uri, str) or not uri.strip():
            errors.append(f"Song {i+1}: missing or invalid 'uri'")

    return (len(errors) == 0, errors)


async def async_discover_playlists(hass: HomeAssistant) -> list[dict]:
    """Discover all playlist files in the playlist directory."""
    playlist_dir = get_playlist_directory(hass)
    playlists: list[dict] = []

    if not playlist_dir.exists():
        _LOGGER.debug("Playlist directory does not exist: %s", playlist_dir)
        return playlists

    for json_file in playlist_dir.glob("*.json"):
        try:
            data = json.loads(json_file.read_text(encoding="utf-8"))
            is_valid, errors = validate_playlist(data)

            playlists.append({
                "path": str(json_file),
                "filename": json_file.name,
                "name": data.get("name", json_file.stem),
                "song_count": len(data.get("songs", [])),
                "is_valid": is_valid,
                "errors": errors,
            })
        except json.JSONDecodeError as e:
            playlists.append({
                "path": str(json_file),
                "filename": json_file.name,
                "name": json_file.stem,
                "song_count": 0,
                "is_valid": False,
                "errors": [f"Invalid JSON: {e}"],
            })

    _LOGGER.debug("Found %d playlists", len(playlists))
    return playlists


async def async_load_and_validate_playlist(
    path: str | Path,
) -> tuple[dict | None, list[str]]:
    """Load and validate a playlist file."""
    path = Path(path)

    if not path.exists():
        return (None, [f"File not found: {path}"])

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return (None, [f"Invalid JSON: {e}"])

    is_valid, errors = validate_playlist(data)

    if is_valid:
        return (data, [])
    return (None, errors)
