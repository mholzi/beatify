# Story 4.1: Song Playback via Media Player

Status: ready-for-dev

## Story

As a **player**,
I want **to hear the song playing through the home speakers**,
so that **everyone in the room experiences the same audio together**.

## Acceptance Criteria

1. **AC1:** Given game transitions to PLAYING state for a new round, When round starts, Then the selected song plays through the configured HA media player (FR22) And playback begins within 1 second of round start

2. **AC2:** Given song is playing, When media player receives the play command, Then `media_player.play_media` service is called with entity_id, media_content_id (song URI), and media_content_type "music" And volume is set to the configured level

3. **AC3:** Given a song has been played in the current game session, When the system selects the next song, Then that song is marked as "played" and excluded from future selection And songs are selected randomly from the unplayed pool

4. **AC4:** Given all songs in selected playlists have been played, When the system tries to select the next song, Then admin is notified "All songs played - game will end after this reveal" And game transitions to END after final reveal

5. **AC5:** Given admin starts a new game (from setup screen), When new game session is created, Then all "played" markers are reset And full playlist is available again

6. **AC6:** Given song URI is invalid or unavailable, When playback is attempted, Then system marks song as played and skips to next song in playlist And logs warning for host review

7. **AC7:** Given media player becomes unavailable mid-game, When playback fails, Then game pauses with message "Media player unavailable" And game can resume when media player is restored

## Tasks / Subtasks

**CRITICAL:** This is the foundational story for Epic 4. It establishes the song playback engine that all other stories depend on.

- [ ] **Task 1: Add round tracking to GameState** (AC: #3, #4, #5)
  - [ ] 1.1 Add `round: int = 0` field to GameState
  - [ ] 1.2 Add `total_rounds: int` field (derived from playlist song count)
  - [ ] 1.3 Add `played_songs: set[str]` to track played song URIs
  - [ ] 1.4 Add `current_song: dict | None` field for current song data
  - [ ] 1.5 Add `deadline: int | None` field for round end timestamp (ms)

- [ ] **Task 2: Create MediaPlayerService** (AC: #1, #2, #6, #7)
  - [ ] 2.1 Create `services/media_player.py` with MediaPlayerService class
  - [ ] 2.2 Implement `async play_song(uri: str) -> bool` method
  - [ ] 2.3 Use `hass.services.async_call("media_player", "play_media", {...})`
  - [ ] 2.4 Implement `async get_metadata() -> dict` to fetch artist/title/album_art
  - [ ] 2.5 Implement `async stop() -> bool` method
  - [ ] 2.6 Implement `async set_volume(level: float) -> bool` method
  - [ ] 2.7 Add error handling for unavailable media player (return False, log error)

- [ ] **Task 3: Create PlaylistManager for song selection** (AC: #3, #4, #5, #6)
  - [ ] 3.1 Update `game/playlist.py` with PlaylistManager class
  - [ ] 3.2 Implement `get_next_song() -> dict | None` that selects random unplayed song
  - [ ] 3.3 Implement `mark_played(uri: str)` to add to played_songs set
  - [ ] 3.4 Implement `reset()` to clear played_songs for new game
  - [ ] 3.5 Implement `is_exhausted() -> bool` to check if all songs played
  - [ ] 3.6 Implement `get_remaining_count() -> int` for admin feedback

- [ ] **Task 4: Implement start_round() in GameState** (AC: #1, #2, #3, #6)
  - [ ] 4.1 Add `async start_round(hass: HomeAssistant)` method
  - [ ] 4.2 Select next song from PlaylistManager
  - [ ] 4.3 If no songs remain, set `last_round = True` flag
  - [ ] 4.4 Call MediaPlayerService.play_song(uri)
  - [ ] 4.5 Wait briefly (500ms) for playback to start
  - [ ] 4.6 Fetch metadata from media player entity attributes
  - [ ] 4.7 Set `current_song` dict with artist, title, album_art, year, fun_fact
  - [ ] 4.8 Set `deadline` to current time + DEFAULT_ROUND_DURATION (30s) in ms
  - [ ] 4.9 Increment `round` counter
  - [ ] 4.10 Transition phase to PLAYING

- [ ] **Task 5: Handle invalid/failed songs** (AC: #6)
  - [ ] 5.1 If play_song returns False, mark song as played
  - [ ] 5.2 Log warning with song URI
  - [ ] 5.3 Recursively call start_round to try next song
  - [ ] 5.4 If all songs fail, transition to END with error message

- [ ] **Task 6: Handle media player unavailability** (AC: #7)
  - [ ] 6.1 Add PAUSED phase handling with `pause_reason: str | None`
  - [ ] 6.2 If media player unavailable, transition to PAUSED
  - [ ] 6.3 Set `pause_reason = "MEDIA_PLAYER_UNAVAILABLE"`
  - [ ] 6.4 Broadcast state with pause reason to all players
  - [ ] 6.5 Add `resume_game()` method to retry playback

- [ ] **Task 7: Update admin start game flow** (AC: #1, #5)
  - [ ] 7.1 In WebSocket admin handler for "start_game" action
  - [ ] 7.2 Call `game_state.start_round(hass)`
  - [ ] 7.3 Broadcast new state to all connected players
  - [ ] 7.4 Reset played_songs when creating new game session

- [ ] **Task 8: Update get_state() for PLAYING phase** (AC: #1, #2)
  - [ ] 8.1 Include `round`, `total_rounds`, `deadline` in state
  - [ ] 8.2 Include `song` with artist, title, album_art (NOT year during PLAYING)
  - [ ] 8.3 Include `songs_remaining` count for admin info

- [ ] **Task 9: Add all songs exhausted notification** (AC: #4)
  - [ ] 9.1 When `is_exhausted()` returns True after song selection
  - [ ] 9.2 Add `last_round: bool` to state broadcast
  - [ ] 9.3 Admin UI shows "Final round!" indicator

- [ ] **Task 10: Unit tests for MediaPlayerService** (AC: #2, #6, #7)
  - [ ] 10.1 Test: play_song calls correct HA service
  - [ ] 10.2 Test: get_metadata returns entity attributes
  - [ ] 10.3 Test: play_song returns False on service error
  - [ ] 10.4 Test: set_volume calls volume_set service

- [ ] **Task 11: Unit tests for PlaylistManager** (AC: #3, #4, #5)
  - [ ] 11.1 Test: get_next_song returns random unplayed song
  - [ ] 11.2 Test: mark_played excludes song from future selection
  - [ ] 11.3 Test: is_exhausted returns True when all played
  - [ ] 11.4 Test: reset clears played songs

- [ ] **Task 12: Unit tests for start_round** (AC: #1, #3, #6)
  - [ ] 12.1 Test: start_round transitions to PLAYING
  - [ ] 12.2 Test: round counter increments
  - [ ] 12.3 Test: deadline is set correctly
  - [ ] 12.4 Test: current_song contains metadata
  - [ ] 12.5 Test: failed song is skipped

- [ ] **Task 13: Integration tests** (AC: #1, #7)
  - [ ] 13.1 Test: start_game admin action triggers playback
  - [ ] 13.2 Test: state broadcast includes round info
  - [ ] 13.3 Test: media player failure triggers PAUSED state

- [ ] **Task 14: Verify no regressions**
  - [ ] 14.1 Run `pytest tests/` - all pass
  - [ ] 14.2 Run `ruff check` - no new issues
  - [ ] 14.3 Test late join still works with new round state

## Dev Notes

### New Files to Create

| File | Purpose |
|------|---------|
| `services/media_player.py` | Media player service wrapper |

### Existing Files to Modify

| File | Action |
|------|--------|
| `game/state.py` | Add round tracking, start_round(), PAUSED handling |
| `game/playlist.py` | Add PlaylistManager class |
| `server/websocket.py` | Handle start_game action, call start_round |
| `const.py` | Add DEFAULT_ROUND_DURATION, ERR_NO_SONGS_REMAINING |

### MediaPlayerService Implementation

```python
# services/media_player.py

import logging
from typing import Any

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class MediaPlayerService:
    """Service for controlling HA media player."""

    def __init__(self, hass: HomeAssistant, entity_id: str):
        """Initialize with HomeAssistant and entity_id."""
        self._hass = hass
        self._entity_id = entity_id

    async def play_song(self, uri: str) -> bool:
        """Play a song by URI.

        Args:
            uri: Media content URI (e.g., spotify:track:xxx)

        Returns:
            True if playback started successfully, False otherwise
        """
        try:
            await self._hass.services.async_call(
                "media_player",
                "play_media",
                {
                    "entity_id": self._entity_id,
                    "media_content_id": uri,
                    "media_content_type": "music",
                },
            )
            return True
        except Exception as err:
            _LOGGER.error("Failed to play song %s: %s", uri, err)
            return False

    async def get_metadata(self) -> dict[str, Any]:
        """Get current track metadata from media player entity.

        Returns:
            Dict with artist, title, album_art keys
        """
        state = self._hass.states.get(self._entity_id)
        if not state:
            return {
                "artist": "Unknown Artist",
                "title": "Unknown Title",
                "album_art": "/beatify/static/img/no-artwork.svg",
            }

        return {
            "artist": state.attributes.get("media_artist", "Unknown Artist"),
            "title": state.attributes.get("media_title", "Unknown Title"),
            "album_art": state.attributes.get(
                "entity_picture", "/beatify/static/img/no-artwork.svg"
            ),
        }

    async def stop(self) -> bool:
        """Stop playback."""
        try:
            await self._hass.services.async_call(
                "media_player",
                "media_stop",
                {"entity_id": self._entity_id},
            )
            return True
        except Exception as err:
            _LOGGER.error("Failed to stop playback: %s", err)
            return False

    async def set_volume(self, level: float) -> bool:
        """Set volume level.

        Args:
            level: Volume level 0.0 to 1.0

        Returns:
            True if successful
        """
        try:
            await self._hass.services.async_call(
                "media_player",
                "volume_set",
                {
                    "entity_id": self._entity_id,
                    "volume_level": max(0.0, min(1.0, level)),
                },
            )
            return True
        except Exception as err:
            _LOGGER.error("Failed to set volume: %s", err)
            return False

    def is_available(self) -> bool:
        """Check if media player is available."""
        state = self._hass.states.get(self._entity_id)
        return state is not None and state.state != "unavailable"
```

### PlaylistManager Implementation

```python
# game/playlist.py - Add to existing file

import random
from typing import Any


class PlaylistManager:
    """Manages song selection and played tracking."""

    def __init__(self, songs: list[dict[str, Any]]):
        """Initialize with list of songs from loaded playlists.

        Each song dict must have: year, uri, fun_fact
        """
        self._songs = songs.copy()
        self._played_uris: set[str] = set()

    def get_next_song(self) -> dict[str, Any] | None:
        """Get random unplayed song.

        Returns:
            Song dict or None if all songs played
        """
        available = [s for s in self._songs if s["uri"] not in self._played_uris]
        if not available:
            return None
        return random.choice(available)

    def mark_played(self, uri: str) -> None:
        """Mark a song as played."""
        self._played_uris.add(uri)

    def reset(self) -> None:
        """Reset played tracking for new game."""
        self._played_uris.clear()

    def is_exhausted(self) -> bool:
        """Check if all songs have been played."""
        return len(self._played_uris) >= len(self._songs)

    def get_remaining_count(self) -> int:
        """Get count of unplayed songs."""
        return len(self._songs) - len(self._played_uris)

    def get_total_count(self) -> int:
        """Get total song count."""
        return len(self._songs)
```

### GameState Round Fields

```python
# game/state.py - Add to GameState class

from dataclasses import field
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

from ..const import DEFAULT_ROUND_DURATION
from ..services.media_player import MediaPlayerService
from .playlist import PlaylistManager

@dataclass
class GameState:
    # ... existing fields ...

    # Round tracking
    round: int = 0
    total_rounds: int = 0
    deadline: int | None = None
    current_song: dict[str, Any] | None = None
    last_round: bool = False

    # Pause tracking
    pause_reason: str | None = None
    _previous_phase: GamePhase | None = None

    # Services (injected)
    _media_player: MediaPlayerService | None = None
    _playlist_manager: PlaylistManager | None = None

    async def start_round(self, hass: HomeAssistant) -> bool:
        """Start a new round with song playback.

        Returns:
            True if round started successfully
        """
        if not self._playlist_manager:
            _LOGGER.error("No playlist manager configured")
            return False

        # Get next song
        song = self._playlist_manager.get_next_song()
        if not song:
            _LOGGER.info("All songs exhausted, ending game")
            self.transition_to(GamePhase.END)
            return False

        # Check if this is the last round
        self.last_round = self._playlist_manager.get_remaining_count() <= 1

        # Play song
        if self._media_player:
            success = await self._media_player.play_song(song["uri"])
            if not success:
                _LOGGER.warning("Failed to play song: %s", song["uri"])
                self._playlist_manager.mark_played(song["uri"])
                # Try next song
                return await self.start_round(hass)

            # Wait for playback to start
            await asyncio.sleep(0.5)

            # Get metadata from media player
            metadata = await self._media_player.get_metadata()
        else:
            # No media player (testing mode)
            metadata = {
                "artist": "Test Artist",
                "title": "Test Song",
                "album_art": "/beatify/static/img/no-artwork.svg",
            }

        # Mark song as played
        self._playlist_manager.mark_played(song["uri"])

        # Set current song (year and fun_fact from playlist, rest from metadata)
        self.current_song = {
            "year": song["year"],
            "fun_fact": song.get("fun_fact", ""),
            "uri": song["uri"],
            **metadata,
        }

        # Update round tracking
        self.round += 1
        self.total_rounds = self._playlist_manager.get_total_count()
        self.deadline = int((self._now() + DEFAULT_ROUND_DURATION) * 1000)

        # Reset player submissions for new round
        for player in self.players.values():
            player.submitted = False
            player.current_guess = None

        # Transition to PLAYING
        self.transition_to(GamePhase.PLAYING)
        return True
```

### WebSocket start_game Handler

```python
# server/websocket.py - Add to admin action handler

async def _handle_admin_action(
    self, ws: web.WebSocketResponse, action: str, data: dict
) -> None:
    """Handle admin control actions."""
    game = self._game_state

    if action == "start_game":
        if game.phase != GamePhase.LOBBY:
            await self._send_error(ws, ERR_INVALID_ACTION, "Game already started")
            return

        if len(game.players) < MIN_PLAYERS:
            await self._send_error(
                ws, ERR_INVALID_ACTION, f"Need at least {MIN_PLAYERS} players"
            )
            return

        # Start first round
        success = await game.start_round(self._hass)
        if success:
            await self._broadcast_state()
        else:
            await self._send_error(ws, ERR_NO_SONGS_REMAINING, "No songs available")
```

### State Broadcast for PLAYING

```python
# Update get_state() in game/state.py

def get_state(self) -> dict[str, Any] | None:
    """Get current game state for broadcast."""
    if not self.game_id:
        return None

    state = {
        "game_id": self.game_id,
        "phase": self.phase.value,
        "player_count": len(self.players),
        "players": self.get_players_state(),
    }

    if self.phase == GamePhase.LOBBY:
        state["join_url"] = self.join_url

    elif self.phase == GamePhase.PLAYING:
        state["round"] = self.round
        state["total_rounds"] = self.total_rounds
        state["deadline"] = self.deadline
        state["last_round"] = self.last_round
        state["songs_remaining"] = (
            self._playlist_manager.get_remaining_count()
            if self._playlist_manager else 0
        )
        # Song info WITHOUT year during PLAYING (hidden)
        if self.current_song:
            state["song"] = {
                "artist": self.current_song.get("artist", "Unknown"),
                "title": self.current_song.get("title", "Unknown"),
                "album_art": self.current_song.get(
                    "album_art", "/beatify/static/img/no-artwork.svg"
                ),
            }

    elif self.phase == GamePhase.REVEAL:
        state["round"] = self.round
        state["total_rounds"] = self.total_rounds
        state["last_round"] = self.last_round
        # Full song info INCLUDING year and fun_fact
        if self.current_song:
            state["song"] = self.current_song

    elif self.phase == GamePhase.PAUSED:
        state["pause_reason"] = self.pause_reason

    elif self.phase == GamePhase.END:
        if self.players:
            winner = max(self.players.values(), key=lambda p: p.score)
            state["winner"] = {"name": winner.name, "score": winner.score}

    return state
```

### const.py Additions

```python
# Add to const.py

DEFAULT_ROUND_DURATION = 30  # seconds
ERR_NO_SONGS_REMAINING = "NO_SONGS_REMAINING"
```

### Architecture Compliance

- **Media Player Integration:** Direct HA service calls per architecture.md
- **Playlist Format:** JSON with year, uri, fun_fact per architecture.md
- **State Machine:** LOBBY -> PLAYING transition via admin start
- **Song Metadata:** Artist/title/album_art from media_player entity attributes
- **Year Hidden:** Year NOT included in state during PLAYING phase
- **Error Recovery:** PAUSED state for media player failures

### Anti-Patterns to Avoid

- Do NOT include `year` or `fun_fact` in state during PLAYING phase
- Do NOT block event loop - all operations must be async
- Do NOT hardcode media player entity - use configured entity_id
- Do NOT skip song tracking - always mark songs as played
- Do NOT ignore playback failures - skip and try next song

### Previous Story Learnings (Epic 3)

- Phase handling in get_state() works well - extend it
- State broadcast pattern is established
- Late join handling already expects round/song fields
- PAUSED state needs to be added to GamePhase enum

### Epic 4 Dependencies

This story establishes foundation for:
- 4.2: Album cover display (uses current_song.album_art)
- 4.3: Year submission (uses deadline)
- 4.5: Timer expiry (uses deadline)
- 4.6: Reveal (uses current_song.year, fun_fact)

### References

- [Source: epics.md#Story-4.1] - FR22
- [Source: architecture.md#Media-Player-Integration] - Service calls
- [Source: architecture.md#Playlist-Data-Format] - JSON structure
- [Source: project-context.md#Media-Player-Service-Calls] - Exact API
- [Source: project-context.md#State-Machine] - Phase transitions

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

### File List
