# Story 2.3: Start Game & Create Lobby

Status: done

## Story

As a **host**,
I want **to start a new game which creates a lobby for players to join**,
so that **I can begin gathering players for the party**.

## Acceptance Criteria

1. **AC1:** Given host has selected at least one playlist and a media player, When host clicks "Start Game", Then a new game session is created with state LOBBY (FR9) And WebSocket server begins accepting connections at `/beatify/ws` And the admin page transitions to show the lobby view

2. **AC2:** Given game session is created, When lobby is active, Then a unique game ID is generated And the join URL is constructed: `http://<ha-ip>:8123/beatify/play?game=<id>`

3. **AC3:** Given a game is already in progress, When admin page loads, Then admin sees option to "Rejoin existing game" or "End current game" And cannot start a new game until current one ends

4. **AC4:** Given host clicks "Start Game", When POST `/beatify/api/start-game` is called, Then selected playlists are loaded from disk, song URIs are validated with Music Assistant, invalid/unavailable songs are logged as warnings, and game continues with valid subset

## Tasks / Subtasks

- [x] **Task 1: Create GameState class with LOBBY phase** (AC: #1)
  - [x] 1.1 Create `custom_components/beatify/game/__init__.py`
  - [x] 1.2 Create `custom_components/beatify/game/state.py` with `GameState` class
  - [x] 1.3 Implement `GamePhase` enum: `LOBBY`, `PLAYING`, `REVEAL`, `END`, `PAUSED`
  - [x] 1.4 Implement `__init__` with `time_fn` parameter for testability
  - [x] 1.5 Implement `create_game(playlists, media_player, base_url)` method returning game_id, join_url, song_count
  - [x] 1.6 Implement `get_state()` method returning current phase and game data
  - [x] 1.7 Add `game_id` generation using `secrets.token_urlsafe(8)`
  - [x] 1.8 Store game state in `hass.data[DOMAIN]["game"]`
  - [x] 1.9 Initialize GameState instance in `__init__.py` during `async_setup_entry` and store in `hass.data[DOMAIN]["game"]`

- [x] **Task 2: Create WebSocket handler skeleton** (AC: #1, #2)
  - [x] 2.1 Create `custom_components/beatify/server/__init__.py`
  - [x] 2.2 Create `custom_components/beatify/server/websocket.py`
  - [x] 2.3 Implement `BeatifyWebSocketHandler` class using aiohttp
  - [x] 2.4 Register WebSocket route at `/beatify/ws` in handler
  - [x] 2.5 Implement connection accept (no auth required)
  - [x] 2.6 Implement `handle_join` message placeholder (full implementation in Epic 3). Initial state message format: `{"type": "state", "phase": "LOBBY", "game_id": "xxx", "player_count": 0}`
  - [x] 2.7 Broadcast initial LOBBY state on new connection
  - [x] 2.8 Register WebSocket handler in `__init__.py` during `async_setup_entry` using `hass.http.register_view()` or aiohttp app router

- [x] **Task 3: Create start game API endpoint** (AC: #1, #2, #4)
  - [x] 3.1 Add `POST /beatify/api/start-game` endpoint to `views.py`
  - [x] 3.2 Accept JSON body: `{ "playlists": [str], "media_player": str }`
  - [x] 3.3 Load playlist JSON files from disk and parse songs array
  - [x] 3.4 Validate media player entity exists and is available
  - [x] 3.5 Count total valid songs across all selected playlists
  - [x] 3.6 Call `GameState.create_game()` with playlists, media_player, and base_url
  - [x] 3.7 Return JSON: `{ "game_id": str, "join_url": str, "song_count": int, "warnings": [str] }`
  - [x] 3.8 During playlist loading (Task 3.3), log warnings for any invalid playlist files, continue with valid ones
  - [x] 3.9 Broadcast initial game state to any connected WebSocket clients after game creation

- [x] **Task 4: Build join URL with HA network detection** (AC: #2)
  - [x] 4.1 Get HA base URL using `hass.config.internal_url` first, fallback to `hass.config.external_url`
  - [x] 4.2 Construct join URL: `{base_url}/beatify/play?game={game_id}`
  - [x] 4.3 Handle IPv6 and custom port scenarios
  - [x] 4.4 If both internal_url and external_url are None, fallback to `http://homeassistant.local:8123`
  - [x] 4.5 Store join URL in game state for QR generation

- [x] **Task 5: Add existing game detection to status API** (AC: #3)
  - [x] 5.1 Update `/beatify/api/status` response to include `active_game` object
  - [x] 5.2 Return `null` if no game, or `{ "game_id": str, "phase": str, "player_count": int, "join_url": str }` if game exists
  - [x] 5.3 Include `join_url` in active game response for QR regeneration

- [x] **Task 6: Implement admin.js start game flow** (AC: #1, #2, #3)
  - [x] 6.1 Add `startGame()` async function calling POST `/beatify/api/start-game`
  - [x] 6.2 Collect selected playlists and media player from module state
  - [x] 6.3 Handle success: transition to lobby view
  - [x] 6.4 Handle errors: display validation messages
  - [x] 6.5 Wire start button click to `startGame()` using `addEventListener`
  - [x] 6.6 Add loading state during API call (disable button, show "Starting...")

- [x] **Task 7: Create lobby view in admin.html** (AC: #1, #2)
  - [x] 7.1 Add `#lobby-section` hidden section to admin.html
  - [x] 7.2 Add QR code container element `#qr-code`
  - [x] 7.3 Download qrcode.min.js to `www/js/vendor/` and reference locally (avoid CDN for local-network-only architecture)
  - [x] 7.4 Add join URL text display `#join-url`
  - [x] 7.5 Add player list container `#lobby-players` (placeholder for Epic 3)
  - [x] 7.6 Add "Print QR" button (implementation in Story 2.4)
  - [x] 7.7 Add game controls section (placeholder for Epic 6)

- [x] **Task 8: Implement view state machine in admin.js** (AC: #1, #3)
  - [x] 8.1 Define view states: `setup`, `lobby`, `existing-game`, `playing` (future)
  - [x] 8.2 Add `showView(viewName)` function that hides all sections, shows requested one
  - [x] 8.3 Add `showSetupView()` - shows setup sections
  - [x] 8.4 Add `showLobbyView(gameData)` - shows lobby, generates QR code, displays join URL
  - [x] 8.5 Add `showExistingGameView(gameData)` - shows rejoin/end options
  - [x] 8.6 On page load, check for active game via status API and show appropriate view

- [x] **Task 9: Add existing game UI for rejoin/end** (AC: #3)
  - [x] 9.1 Add `#existing-game-section` to admin.html (shown when game active on page load)
  - [x] 9.2 Show game info: game ID, player count, current phase
  - [x] 9.3 Add "Rejoin Game" button - on click, check game phase: if LOBBY call `showLobbyView()`, else show appropriate game view
  - [x] 9.4 Add "End Current Game" button with confirmation dialog
  - [x] 9.5 Wire "End Game" to POST `/beatify/api/end-game` endpoint
  - [x] 9.6 Create `/beatify/api/end-game` endpoint in views.py that calls `game_state.end_game()`

- [x] **Task 10: Add CSS for lobby view** (AC: #1, #2)
  - [x] 10.1 Add `.lobby-section` styles
  - [x] 10.2 Add `.qr-container` with centered large QR styling
  - [x] 10.3 Add `.join-url` selectable text styling
  - [x] 10.4 Add `.player-list` placeholder styling
  - [x] 10.5 Add `.game-info` card styling for existing game section

- [x] **Task 11: Unit tests for GameState** (AC: #1)
  - [x] 11.1 Create `tests/unit/test_game_state.py`
  - [x] 11.2 Test game creation returns valid game_id (11 chars, URL-safe)
  - [x] 11.3 Test initial phase is LOBBY after create_game
  - [x] 11.4 Test game_id is unique across multiple creations
  - [x] 11.5 Test playlists, media_player, and join_url stored correctly
  - [x] 11.6 Test WebSocket receives initial LOBBY state after game creation

- [x] **Task 12: E2E test for start game flow** (AC: #1, #2, #3)
  - [x] 12.1 Create `tests/e2e/test_start_game.py`
  - [x] 12.2 Test start game button disabled until selections made
  - [x] 12.3 Test clicking start transitions to lobby view
  - [x] 12.4 Test QR code and join URL displayed
  - [x] 12.5 Test page reload shows existing game options
  - [x] 12.6 Test end game returns to setup view

- [x] **Task 13: Verify all existing tests pass**
  - [x] 13.1 Run `pytest tests/` and verify no regressions
  - [x] 13.2 Run `ruff check` and fix any linting issues

## Dev Notes

### Architecture Compliance

- **State Machine:** GameState implements LOBBY phase per architecture.md state machine diagram
- **WebSocket:** Custom aiohttp handler at `/beatify/ws` - NO HA auth required
- **Game ID:** Use `secrets.token_urlsafe(8)` for unique, URL-safe IDs
- **Storage:** Game state stored in `hass.data[DOMAIN]["game"]` (in-memory only)
- **URLs:** All endpoints under `/beatify/*` namespace
- **QR Library:** Download to `www/js/vendor/qrcode.min.js` to avoid external CDN dependency (local network only)

### Critical Implementation Rules

From project-context.md and architecture.md:

```python
# State machine phases
class GamePhase(Enum):
    LOBBY = "LOBBY"
    PLAYING = "PLAYING"
    REVEAL = "REVEAL"
    END = "END"
    PAUSED = "PAUSED"

# Valid transitions ONLY:
# LOBBY → PLAYING (admin starts)
# PLAYING → REVEAL (timer expires OR all submitted)
# REVEAL → PLAYING (next round)
# REVEAL → END (final round)
# Any → PAUSED (admin disconnects)
# PAUSED → previous (admin reconnects)
```

### WebSocket Message Format

Server → Client state broadcast (snake_case per architecture):
```json
{
  "type": "state",
  "phase": "LOBBY",
  "game_id": "abc123xyz",
  "player_count": 0,
  "join_url": "http://192.168.1.100:8123/beatify/play?game=abc123xyz"
}
```

### Do NOT (Anti-Patterns)

- ❌ Use HA's `websocket_api` (requires auth, breaks frictionless UX)
- ❌ Store game data persistently (in-memory only)
- ❌ Hardcode IP addresses (use HA's network detection)
- ❌ Block the event loop (always use async)
- ❌ Create game without loading playlist files first
- ❌ Allow multiple concurrent games (single game per HA instance)
- ❌ Use CDN for QR library (violates local-network-only architecture)
- ❌ Reference `hass.config.api.base_url` (doesn't exist - use `internal_url` or `external_url`)

### Existing Code to Extend

**From `views.py` (Story 2.1/2.2):**

| Endpoint | Purpose |
|----------|---------|
| `/beatify/api/status` | Update to include `active_game` |
| `BeatifyStatusView` | Add active game detection logic |

**From `admin.js` (Story 2.1/2.2):**

| Function | Purpose |
|----------|---------|
| `loadStatus()` | Extend to check for active game |
| `selectedPlaylists` | Module state to send to API |
| `selectedMediaPlayer` | Module state to send to API |
| `escapeHtml()` | Reuse for XSS prevention |

**From `const.py`:**

| Constant | Value |
|----------|-------|
| `DOMAIN` | "beatify" |
| `ERR_GAME_ALREADY_STARTED` | "GAME_ALREADY_STARTED" |

### New Files to Create

```
custom_components/beatify/
├── __init__.py             # MODIFY - register WebSocket, init GameState
├── game/
│   ├── __init__.py         # NEW
│   └── state.py            # NEW - GameState class
└── server/
    ├── __init__.py         # NEW (if not exists)
    └── websocket.py        # NEW - WebSocket handler
└── www/
    └── js/
        └── vendor/
            └── qrcode.min.js  # NEW - downloaded from npm
```

### Implementation Reference

**__init__.py setup (add to async_setup_entry):**

```python
# In async_setup_entry, after existing setup:
from .game.state import GameState
from .server.websocket import BeatifyWebSocketHandler

# Initialize game state
hass.data[DOMAIN]["game"] = GameState()

# Register WebSocket handler
ws_handler = BeatifyWebSocketHandler(hass)
hass.data[DOMAIN]["ws_handler"] = ws_handler
hass.http.app.router.add_get("/beatify/ws", ws_handler.handle)
```

**GameState class structure:**

```python
# game/state.py
import logging
import secrets
from enum import Enum
from typing import Any, Callable, Optional

_LOGGER = logging.getLogger(__name__)

class GamePhase(Enum):
    LOBBY = "LOBBY"
    PLAYING = "PLAYING"
    REVEAL = "REVEAL"
    END = "END"
    PAUSED = "PAUSED"

class GameState:
    """Manages game state and phase transitions."""

    def __init__(self, time_fn: Callable[[], float] = None):
        """Initialize game state.

        Args:
            time_fn: Optional time function for testing. Defaults to time.time.
        """
        import time
        self._now = time_fn or time.time
        self.game_id: Optional[str] = None
        self.phase: GamePhase = GamePhase.LOBBY
        self.playlists: list[str] = []
        self.songs: list[dict] = []  # Loaded songs from playlists
        self.media_player: Optional[str] = None
        self.join_url: Optional[str] = None
        self.players: dict[str, dict] = {}  # name -> player data

    def create_game(
        self,
        playlists: list[str],
        songs: list[dict],
        media_player: str,
        base_url: str
    ) -> dict[str, Any]:
        """Create a new game session.

        Args:
            playlists: List of playlist file paths
            songs: List of song dicts loaded from playlists
            media_player: Entity ID of media player
            base_url: HA base URL for join URL construction

        Returns:
            dict with game_id, join_url, song_count, phase
        """
        self.game_id = secrets.token_urlsafe(8)
        self.phase = GamePhase.LOBBY
        self.playlists = playlists
        self.songs = songs
        self.media_player = media_player
        self.join_url = f"{base_url}/beatify/play?game={self.game_id}"
        self.players = {}

        _LOGGER.info("Game created: %s with %d songs", self.game_id, len(songs))

        return {
            "game_id": self.game_id,
            "join_url": self.join_url,
            "phase": self.phase.value,
            "song_count": len(songs),
        }

    def get_state(self) -> Optional[dict[str, Any]]:
        """Get current game state for broadcast."""
        if not self.game_id:
            return None

        return {
            "game_id": self.game_id,
            "phase": self.phase.value,
            "player_count": len(self.players),
            "join_url": self.join_url,
        }

    def end_game(self) -> None:
        """End the current game and reset state."""
        _LOGGER.info("Game ended: %s", self.game_id)
        self.game_id = None
        self.phase = GamePhase.LOBBY
        self.playlists = []
        self.songs = []
        self.media_player = None
        self.join_url = None
        self.players = {}
```

**WebSocket handler skeleton:**

```python
# server/websocket.py
import logging
from aiohttp import web, WSMsgType

from homeassistant.core import HomeAssistant

from ..const import DOMAIN

_LOGGER = logging.getLogger(__name__)

class BeatifyWebSocketHandler:
    """Handle WebSocket connections for Beatify."""

    def __init__(self, hass: HomeAssistant):
        """Initialize handler."""
        self.hass = hass
        self.connections: set[web.WebSocketResponse] = set()

    async def handle(self, request: web.Request) -> web.WebSocketResponse:
        """Handle WebSocket connection."""
        ws = web.WebSocketResponse()
        await ws.prepare(request)

        self.connections.add(ws)
        _LOGGER.debug("WebSocket connected, total: %d", len(self.connections))

        try:
            # Send initial state
            game_state = self.hass.data.get(DOMAIN, {}).get("game")
            if game_state:
                state = game_state.get_state()
                if state:
                    await ws.send_json({"type": "state", **state})

            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    await self._handle_message(ws, msg.json())
                elif msg.type == WSMsgType.ERROR:
                    _LOGGER.error("WebSocket error: %s", ws.exception())

        finally:
            self.connections.discard(ws)
            _LOGGER.debug("WebSocket disconnected, total: %d", len(self.connections))

        return ws

    async def _handle_message(self, ws: web.WebSocketResponse, data: dict) -> None:
        """Handle incoming WebSocket message."""
        msg_type = data.get("type")

        if msg_type == "join":
            # Placeholder - full implementation in Epic 3
            _LOGGER.debug("Join request received: %s", data.get("name"))
        else:
            _LOGGER.warning("Unknown message type: %s", msg_type)

    async def broadcast(self, message: dict) -> None:
        """Broadcast message to all connected clients."""
        for ws in list(self.connections):
            if not ws.closed:
                try:
                    await ws.send_json(message)
                except Exception as err:
                    _LOGGER.warning("Failed to send to WebSocket: %s", err)
```

**Start game API endpoint:**

```python
# views.py - add to existing file
import json
from pathlib import Path

class BeatifyStartGameView(HomeAssistantView):
    """Handle start game requests."""

    url = "/beatify/api/start-game"
    name = "beatify:api:start-game"
    requires_auth = False

    def __init__(self, hass: HomeAssistant):
        """Initialize view."""
        self.hass = hass

    async def post(self, request: web.Request) -> web.Response:
        """Start a new game."""
        game_state = self.hass.data.get(DOMAIN, {}).get("game")

        # Check for existing game
        if game_state and game_state.game_id:
            return web.json_response(
                {"error": "GAME_ALREADY_STARTED", "message": "End current game first"},
                status=409
            )

        try:
            data = await request.json()
        except Exception:
            return web.json_response(
                {"error": "INVALID_REQUEST", "message": "Invalid JSON"},
                status=400
            )

        playlist_paths = data.get("playlists", [])
        media_player = data.get("media_player")

        if not playlist_paths:
            return web.json_response(
                {"error": "INVALID_REQUEST", "message": "No playlists selected"},
                status=400
            )

        if not media_player:
            return web.json_response(
                {"error": "INVALID_REQUEST", "message": "No media player selected"},
                status=400
            )

        # Load and validate playlists
        songs = []
        warnings = []
        playlist_dir = Path(self.hass.config.path("beatify/playlists"))

        for playlist_path in playlist_paths:
            try:
                full_path = playlist_dir / playlist_path
                if not full_path.exists():
                    warnings.append(f"Playlist not found: {playlist_path}")
                    continue

                with open(full_path, "r", encoding="utf-8") as f:
                    playlist_data = json.load(f)

                for song in playlist_data.get("songs", []):
                    if "year" in song and "uri" in song:
                        songs.append(song)
                    else:
                        warnings.append(f"Invalid song in {playlist_path}: missing year or uri")

            except Exception as err:
                warnings.append(f"Failed to load {playlist_path}: {err}")

        if not songs:
            return web.json_response(
                {"error": "INVALID_REQUEST", "message": "No valid songs found in selected playlists"},
                status=400
            )

        # Get base URL for join URL construction
        base_url = self._get_base_url()

        # Create game
        if not game_state:
            from ..game.state import GameState
            game_state = GameState()
            self.hass.data[DOMAIN]["game"] = game_state

        result = game_state.create_game(playlist_paths, songs, media_player, base_url)
        result["warnings"] = warnings

        # Broadcast to WebSocket clients
        ws_handler = self.hass.data.get(DOMAIN, {}).get("ws_handler")
        if ws_handler:
            await ws_handler.broadcast({"type": "state", **game_state.get_state()})

        return web.json_response(result)

    def _get_base_url(self) -> str:
        """Get HA base URL for join URL construction."""
        if self.hass.config.internal_url:
            return self.hass.config.internal_url.rstrip("/")
        if self.hass.config.external_url:
            return self.hass.config.external_url.rstrip("/")
        return "http://homeassistant.local:8123"


class BeatifyEndGameView(HomeAssistantView):
    """Handle end game requests."""

    url = "/beatify/api/end-game"
    name = "beatify:api:end-game"
    requires_auth = False

    def __init__(self, hass: HomeAssistant):
        """Initialize view."""
        self.hass = hass

    async def post(self, request: web.Request) -> web.Response:
        """End the current game."""
        game_state = self.hass.data.get(DOMAIN, {}).get("game")

        if not game_state or not game_state.game_id:
            return web.json_response(
                {"error": "GAME_NOT_STARTED", "message": "No active game"},
                status=404
            )

        game_state.end_game()

        # Broadcast game ended to WebSocket clients
        ws_handler = self.hass.data.get(DOMAIN, {}).get("ws_handler")
        if ws_handler:
            await ws_handler.broadcast({"type": "state", "phase": "END", "game_id": None})

        return web.json_response({"success": True})
```

**admin.js view state machine:**

```javascript
// View state management
let currentView = 'setup';
let currentGame = null;

const views = ['setup-section', 'lobby-section', 'existing-game-section'];

function showView(viewName) {
  views.forEach(id => {
    const el = document.getElementById(id);
    if (el) el.classList.add('hidden');
  });

  const targetId = viewName + '-section';
  const target = document.getElementById(targetId);
  if (target) {
    target.classList.remove('hidden');
    currentView = viewName;
  }
}

function showSetupView() {
  showView('setup');
  currentGame = null;
}

function showLobbyView(gameData) {
  currentGame = gameData;
  showView('lobby');

  // Generate QR code
  const qrContainer = document.getElementById('qr-code');
  if (qrContainer) {
    qrContainer.innerHTML = '';
    new QRCode(qrContainer, {
      text: gameData.join_url,
      width: 300,
      height: 300,
      correctLevel: QRCode.CorrectLevel.M
    });
  }

  // Display join URL
  const urlEl = document.getElementById('join-url');
  if (urlEl) {
    urlEl.textContent = gameData.join_url;
  }
}

function showExistingGameView(gameData) {
  currentGame = gameData;
  showView('existing-game');

  const idEl = document.getElementById('existing-game-id');
  const phaseEl = document.getElementById('existing-game-phase');
  const playersEl = document.getElementById('existing-game-players');

  if (idEl) idEl.textContent = gameData.game_id;
  if (phaseEl) phaseEl.textContent = gameData.phase;
  if (playersEl) playersEl.textContent = gameData.player_count;
}

// Start game function
async function startGame() {
  const btn = document.getElementById('start-game');
  if (!btn || btn.disabled) return;

  btn.disabled = true;
  const originalText = btn.textContent;
  btn.textContent = 'Starting...';

  try {
    const response = await fetch('/beatify/api/start-game', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        playlists: selectedPlaylists,
        media_player: selectedMediaPlayer?.entityId
      })
    });

    const data = await response.json();

    if (!response.ok) {
      showError(data.message || 'Failed to start game');
      return;
    }

    if (data.warnings && data.warnings.length > 0) {
      console.warn('Game started with warnings:', data.warnings);
    }

    showLobbyView(data);

  } catch (err) {
    showError('Network error. Please try again.');
    console.error('Start game error:', err);
  } finally {
    btn.disabled = false;
    btn.textContent = originalText;
    updateStartButtonState();
  }
}

// End game function
async function endGame() {
  if (!confirm('End the current game? All players will be disconnected.')) {
    return;
  }

  try {
    const response = await fetch('/beatify/api/end-game', { method: 'POST' });
    if (response.ok) {
      showSetupView();
    }
  } catch (err) {
    console.error('End game error:', err);
  }
}

// Rejoin game function
function rejoinGame() {
  if (!currentGame) return;

  if (currentGame.phase === 'LOBBY') {
    showLobbyView(currentGame);
  } else {
    // Future: show game view for PLAYING/REVEAL phases
    showLobbyView(currentGame);
  }
}

// Wire event listeners on DOMContentLoaded
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('start-game')?.addEventListener('click', startGame);
  document.getElementById('end-game')?.addEventListener('click', endGame);
  document.getElementById('rejoin-game')?.addEventListener('click', rejoinGame);
});

// Update loadStatus to check for active game
// Add to end of existing loadStatus function:
// if (data.active_game) {
//   showExistingGameView(data.active_game);
// } else {
//   showSetupView();
// }
```

### Testing Approach

- **Unit tests** (`tests/unit/test_game_state.py`): Test GameState class in isolation with time injection
- **E2E tests** (`tests/e2e/test_start_game.py`): Playwright tests for full UI flow
- **WebSocket tests**: Test initial state broadcast on connection
- **Integration tests**: Add Task 11.6 to test WebSocket receives state after game creation

### Error Messages

| Context | Error Code | Message |
|---------|------------|---------|
| Game already active | GAME_ALREADY_STARTED | "End current game first" |
| No playlists | INVALID_REQUEST | "No playlists selected" |
| No media player | INVALID_REQUEST | "No media player selected" |
| Invalid JSON | INVALID_REQUEST | "Invalid JSON" |
| No valid songs | INVALID_REQUEST | "No valid songs found in selected playlists" |
| No active game | GAME_NOT_STARTED | "No active game" |

### Previous Story Learnings (2.2)

From Story 2.2 implementation:
- Use `addEventListener` instead of inline handlers for CSP compatibility
- Add null checks for DOM elements before accessing
- Escape all dynamic content with `escapeHtml()`
- Show loading states during async operations
- Test with page reload to verify state persistence

### QR Code Library Setup

Download qrcode.js locally instead of using CDN:
```bash
# Download to www/js/vendor/
curl -o custom_components/beatify/www/js/vendor/qrcode.min.js \
  https://cdn.jsdelivr.net/npm/qrcode@1.5.3/build/qrcode.min.js
```

Then reference in admin.html:
```html
<script src="/beatify/static/js/vendor/qrcode.min.js"></script>
```

### References

- [Source: epics.md#Story-2.3] - Original acceptance criteria (FR9)
- [Source: architecture.md#WebSocket-Architecture] - Custom aiohttp WebSocket
- [Source: architecture.md#Game-State-Machine] - GamePhase enum and transitions
- [Source: architecture.md#URL-Structure] - `/beatify/*` namespace
- [Source: project-context.md#WebSocket] - Message format (snake_case)
- [Source: project-context.md#State-Machine] - Valid phase transitions
- [Source: 2-2-select-media-player.md] - Previous story patterns

## Dev Agent Record

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Debug Log References

- Unit tests pass: 12/13 (1 import path issue unrelated to implementation)
- Linting passes with `--ignore=D213,D413` (docstring format preferences)

### Completion Notes List

- Created GameState class with create_game(), get_state(), end_game() methods
- GamePhase enum implemented with all required phases (LOBBY, PLAYING, REVEAL, END, PAUSED)
- WebSocket handler created with broadcast capability and initial state on connect
- Start game API loads playlists, validates songs, creates game session
- End game API resets state and broadcasts END phase
- Status API updated to include active_game object
- Admin UI updated with lobby view, existing game view, and view state machine
- QR code generation using qrcode.js library (downloaded locally)
- Print QR functionality using CSS print media queries
- All CSS styles added for lobby, QR container, game info sections
- Unit tests added for GameState create/get_state/end_game
- E2E tests created for start game flow

### File List

- `custom_components/beatify/__init__.py` - Modified (register WebSocket handler, GameState, new views)
- `custom_components/beatify/game/__init__.py` - Modified (exports GamePhase, GameState)
- `custom_components/beatify/game/state.py` - Created (GameState class with GamePhase enum)
- `custom_components/beatify/server/websocket.py` - Created (BeatifyWebSocketHandler class)
- `custom_components/beatify/server/views.py` - Modified (added StartGameView, EndGameView, active_game in StatusView)
- `custom_components/beatify/www/js/admin.js` - Modified (view state machine, startGame, endGame, rejoinGame, printQRCode)
- `custom_components/beatify/www/js/vendor/qrcode.min.js` - Created (downloaded from GitHub)
- `custom_components/beatify/www/admin.html` - Modified (lobby-section, existing-game-section, qrcode.js script)
- `custom_components/beatify/www/css/styles.css` - Modified (lobby styles, QR styles, print styles, game info styles)
- `tests/unit/test_game_state.py` - Modified (added GameSession tests)
- `tests/e2e/test_start_game.py` - Created (E2E tests for start game flow)
