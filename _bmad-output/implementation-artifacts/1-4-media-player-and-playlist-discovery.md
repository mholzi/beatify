# Story 1.4: Media Player & Playlist Discovery

Status: ready-for-dev

## Story

As a **Home Assistant admin**,
I want **to see available media players and playlists during setup**,
So that **I can verify my system is ready to run Beatify games**.

## Acceptance Criteria

1. **Given** Music Assistant is configured
   **When** Beatify scans for media players
   **Then** all HA `media_player` entities are listed with friendly names (FR4)
   **And** at least one media player must be available to proceed

2. **Given** Beatify scans for playlists
   **When** the playlist directory `{HA_CONFIG}/beatify/playlists/` exists
   **Then** all `.json` files in that directory are listed as available playlists (FR5)

3. **Given** the playlist directory does not exist
   **When** Beatify scans for playlists
   **Then** the directory is created automatically
   **And** a message indicates "No playlists found yet" (not an error at setup time)

4. **Given** playlist JSON files exist
   **When** Beatify validates them
   **Then** each file is checked for required fields: `name`, `songs[]` with `year`, `uri`
   **And** invalid playlists are flagged with specific error messages

## Tasks / Subtasks

- [ ] Task 1: Create media player discovery service (AC: #1)
  - [ ] 1.1: Create `services/media_player.py` module
  - [ ] 1.2: Implement `async_get_media_players(hass)` function
  - [ ] 1.3: Query all `media_player.*` entities from `hass.states`
  - [ ] 1.4: Return list of dicts with `entity_id`, `friendly_name`, `state`
  - [ ] 1.5: Filter out unavailable entities (optional, configurable)

- [ ] Task 2: Create playlist discovery service (AC: #2, #3, #4)
  - [ ] 2.1: Create `game/playlist.py` module
  - [ ] 2.2: Define playlist directory path: `{HA_CONFIG}/beatify/playlists/`
  - [ ] 2.3: Implement `async_get_playlist_directory(hass)` to return path
  - [ ] 2.4: Implement `async_ensure_playlist_directory(hass)` to create if missing
  - [ ] 2.5: Implement `async_discover_playlists(hass)` to list all `.json` files

- [ ] Task 3: Implement playlist validation (AC: #4)
  - [ ] 3.1: Implement `validate_playlist(data: dict) -> tuple[bool, list[str]]`
  - [ ] 3.2: Check required fields: `name` (string), `songs` (list)
  - [ ] 3.3: For each song, check: `year` (int), `uri` (string)
  - [ ] 3.4: Validate year is within reasonable bounds (1900-2030)
  - [ ] 3.5: Optional field: `fun_fact` (string)
  - [ ] 3.6: Return (is_valid, list_of_errors)
  - [ ] 3.7: Implement `async_load_and_validate_playlist(hass, path)` combining load + validate

- [ ] Task 4: Store discovery results in hass.data (AC: #1, #2)
  - [ ] 4.1: During setup, store discovered media players in `hass.data[DOMAIN]["media_players"]`
  - [ ] 4.2: Store discovered playlists in `hass.data[DOMAIN]["playlists"]`
  - [ ] 4.3: Store playlist directory path in `hass.data[DOMAIN]["playlist_dir"]`
  - [ ] 4.4: Add refresh functions for later use

- [ ] Task 5: Update __init__.py setup (AC: #1, #2, #3)
  - [ ] 5.1: Call `async_ensure_playlist_directory()` during setup
  - [ ] 5.2: Discover media players and playlists
  - [ ] 5.3: Log discovery results: `_LOGGER.info("Found %d media players, %d playlists", ...)`
  - [ ] 5.4: Store results in `hass.data[DOMAIN]`

- [ ] Task 6: Add constants for playlist format (AC: #4)
  - [ ] 6.1: Add `PLAYLIST_DIR = "beatify/playlists"` to const.py
  - [ ] 6.2: Add `PLAYLIST_REQUIRED_FIELDS = ["name", "songs"]`
  - [ ] 6.3: Add `SONG_REQUIRED_FIELDS = ["year", "uri"]`

- [ ] Task 7: Write unit tests (AC: #1, #2, #3, #4)
  - [ ] 7.1: Test media player discovery with mock entities
  - [ ] 7.2: Test playlist directory creation
  - [ ] 7.3: Test playlist discovery with mock files
  - [ ] 7.4: Test valid playlist validation
  - [ ] 7.5: Test invalid playlist detection (missing fields)
  - [ ] 7.6: Test empty playlist directory handling

## Dependencies

- **Story 1.1** (done): Project scaffold with `const.py` and `__init__.py`
- **Story 1.2** (ready): HACS metadata configured
- **Story 1.3** (ready): MA detection in config flow

## Dev Notes

### Media Player Discovery

From [architecture.md - Core Architectural Decisions]:
- All HA `media_player` entities should be available for selection
- Config flow validates at least one media player exists

```python
# services/media_player.py
import logging
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

async def async_get_media_players(hass: HomeAssistant) -> list[dict]:
    """Get all available media player entities."""
    media_players = []

    for state in hass.states.async_all("media_player"):
        media_players.append({
            "entity_id": state.entity_id,
            "friendly_name": state.attributes.get("friendly_name", state.entity_id),
            "state": state.state,
        })

    _LOGGER.debug("Found %d media players", len(media_players))
    return media_players
```

### Playlist Data Format

From [architecture.md - Playlist Data Format] and [project-context.md - Playlist Format]:

```json
{
  "name": "80s Hits",
  "songs": [
    {
      "year": 1984,
      "uri": "spotify:track:xxx",
      "fun_fact": "Written in 10 minutes"
    }
  ]
}
```

**Required fields:**
- `name` (string): Playlist display name
- `songs` (array): List of song objects
  - `year` (integer): Release year (authoritative, manually curated)
  - `uri` (string): Music service URI (e.g., `spotify:track:xxx`)

**Optional fields:**
- `songs[].fun_fact` (string): Fun fact shown during reveal

**Fetched from MA at runtime:**
- `artist`, `title`, `album_art` - NOT stored in playlist JSON

### Playlist Storage Path

From [architecture.md - Playlist Validation]:
```
{HA_CONFIG}/beatify/playlists/*.json
```

User-editable location outside the integration directory.

```python
# game/playlist.py
import json
import logging
from pathlib import Path
from homeassistant.core import HomeAssistant

from ..const import PLAYLIST_DIR

_LOGGER = logging.getLogger(__name__)

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

async def async_discover_playlists(hass: HomeAssistant) -> list[dict]:
    """Discover all playlist files."""
    playlist_dir = get_playlist_directory(hass)
    playlists = []

    if not playlist_dir.exists():
        return playlists

    for json_file in playlist_dir.glob("*.json"):
        try:
            data = json.loads(json_file.read_text())
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
```

### Playlist Validation

```python
# game/playlist.py (continued)

def validate_playlist(data: dict) -> tuple[bool, list[str]]:
    """Validate playlist structure. Returns (is_valid, errors)."""
    errors = []

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

        if not isinstance(song.get("year"), int):
            errors.append(f"Song {i+1}: missing or invalid 'year' (must be integer)")
        elif not (1900 <= song["year"] <= 2030):
            errors.append(f"Song {i+1}: year {song['year']} out of range (1900-2030)")

        if not isinstance(song.get("uri"), str) or not song["uri"].strip():
            errors.append(f"Song {i+1}: missing or invalid 'uri'")

    return (len(errors) == 0, errors)
```

### Architecture Compliance

From [architecture.md - Project Structure]:
```
custom_components/beatify/
├── game/
│   └── playlist.py      # Playlist loading, validation
├── services/
│   └── media_player.py  # Media player discovery
```

From [architecture.md - Requirements to Structure Mapping]:
- FR4 (media player display) → `services/media_player.py`
- FR5 (playlist detection) → `game/playlist.py`

### Project Structure Notes

Files created/modified in this story:
```
custom_components/beatify/
├── __init__.py          # Add discovery calls during setup
├── const.py             # Add PLAYLIST_DIR constant
├── game/
│   ├── __init__.py      # NEW: Package init
│   └── playlist.py      # NEW: Playlist discovery/validation
└── services/
    ├── __init__.py      # NEW: Package init
    └── media_player.py  # NEW: Media player discovery

tests/
└── unit/
    ├── test_playlist.py       # NEW: Playlist tests
    └── test_media_player.py   # NEW: Media player tests
```

### Import Order (Python - PEP 8)

```python
# game/playlist.py
import json
import logging
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant

from ..const import PLAYLIST_DIR

_LOGGER = logging.getLogger(__name__)
```

### Naming Conventions

From [project-context.md - Naming Conventions]:
- Python files: `snake_case` (playlist.py, media_player.py)
- Python functions: `snake_case` (async_get_media_players, validate_playlist)
- Python classes: `PascalCase` (if any)
- Constants: `UPPER_SNAKE` (PLAYLIST_DIR)

### Testing This Story

**Unit Tests:**
```python
# tests/unit/test_playlist.py

def test_validate_valid_playlist():
    """Test validation of a valid playlist."""
    data = {
        "name": "80s Hits",
        "songs": [
            {"year": 1984, "uri": "spotify:track:xxx"},
            {"year": 1985, "uri": "spotify:track:yyy", "fun_fact": "Cool fact"}
        ]
    }
    is_valid, errors = validate_playlist(data)
    assert is_valid is True
    assert errors == []

def test_validate_missing_name():
    """Test validation catches missing name."""
    data = {"songs": [{"year": 1984, "uri": "spotify:track:xxx"}]}
    is_valid, errors = validate_playlist(data)
    assert is_valid is False
    assert "Missing or empty 'name' field" in errors

def test_validate_invalid_year():
    """Test validation catches invalid year type."""
    data = {
        "name": "Test",
        "songs": [{"year": "1984", "uri": "spotify:track:xxx"}]
    }
    is_valid, errors = validate_playlist(data)
    assert is_valid is False
    assert any("year" in e for e in errors)
```

```python
# tests/unit/test_media_player.py

async def test_discover_media_players(hass, mock_media_player_states):
    """Test media player discovery."""
    players = await async_get_media_players(hass)
    assert len(players) == 2
    assert players[0]["entity_id"] == "media_player.living_room"
    assert players[0]["friendly_name"] == "Living Room Speaker"
```

**Manual Testing:**
1. Create `{HA_CONFIG}/beatify/playlists/` directory
2. Add valid and invalid playlist JSON files
3. Load Beatify and check logs for discovery results
4. Verify media players are detected from HA

### References

- [Source: _bmad-output/architecture.md#Playlist-Data-Format]
- [Source: _bmad-output/architecture.md#Project-Structure-Boundaries]
- [Source: _bmad-output/project-context.md#Playlist-Format]
- [Source: _bmad-output/epics.md#Story-1.4]
- [Source: _bmad-output/epics.md#FR4] (media player display)
- [Source: _bmad-output/epics.md#FR5] (playlist detection)

---

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

### File List

