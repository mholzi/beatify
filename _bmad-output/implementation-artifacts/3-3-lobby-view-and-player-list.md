# Story 3.3: Lobby View & Player List

Status: done

## Story

As a **player in the lobby**,
I want **to see all other players waiting and know who the admin is**,
so that **I know the game is filling up and who's in charge**.

## Acceptance Criteria

1. **AC1:** Given player has joined the lobby, When lobby view displays, Then a list of all players in the lobby is shown (FR17) And each player's name is displayed And the list updates in real-time as players join/leave (FR19)

2. **AC2:** Given admin has joined as a player, When lobby displays player list, Then admin's name shows a visible badge/indicator (e.g., "👑" or "(Host)") (FR18) And the badge is clearly distinguishable

3. **AC3:** Given new player joins the lobby, When their WebSocket connection is established, Then all existing players see the new name appear within 500ms (NFR4) And a subtle animation or highlight draws attention to the new joiner

4. **AC4:** Given player disconnects from lobby, When WebSocket connection closes, Then player is removed from the list after brief grace period (5 seconds) And other players see the list update

## Tasks / Subtasks

**CRITICAL:** Story 3.2 created the lobby view placeholder. This story implements the full player list with real-time updates.

- [x] **Task 1: Update player state to include admin flag** (AC: #2)
  - [x] 1.1 Add `is_admin: bool = False` field to `PlayerSession` dataclass in `game/player.py`
  - [x] 1.2 Update `get_players_state()` in `game/state.py` to include `is_admin` field
  - [x] 1.3 Add `set_admin(name)` method to `GameState` to mark a player as admin

- [x] **Task 2: Track player connection state** (AC: #4)
  - [x] 2.1 Add `LOBBY_DISCONNECT_GRACE_PERIOD = 5` constant to `const.py`
  - [x] 2.2 Update `handle_disconnect()` in `websocket.py` to mark player as `connected: False`
  - [x] 2.3 Create async task to remove player after 5-second grace period
  - [x] 2.4 Cancel removal task if player reconnects within grace period

- [x] **Task 3: Broadcast state on player changes** (AC: #1, #3, #4)
  - [x] 3.1 Create `broadcast_state()` helper in `websocket.py`
  - [x] 3.2 Call broadcast on player join (already done in 3.2, verify)
  - [x] 3.3 Call broadcast on player disconnect
  - [x] 3.4 Call broadcast on player reconnect

- [x] **Task 4: Implement lobby HTML structure** (AC: #1, #2)
  - [x] 4.1 Replace placeholder content in `#lobby-view` in `player.html`
  - [x] 4.2 Add: `#player-list` container, `#player-count` display
  - [x] 4.3 Add: QR code area (placeholder for Story 3.4)
  - [x] 4.4 Add: "Waiting for host to start..." message for non-admins

- [x] **Task 5: Implement player list rendering in JS** (AC: #1, #2, #3)
  - [x] 5.1 Add `renderPlayerList(players)` function inside IIFE in `player.js`
  - [x] 5.2 Create player card HTML with name display
  - [x] 5.3 Add admin badge (crown emoji "👑") for `is_admin: true` players
  - [x] 5.4 Add "You" indicator for current player
  - [x] 5.5 Add CSS class `.is-new` for animation on new players

- [x] **Task 6: Handle WebSocket state updates** (AC: #1, #3, #4)
  - [x] 6.1 Update `handleServerMessage()` to call `renderPlayerList()` on state updates
  - [x] 6.2 Detect new players by comparing previous/current player lists
  - [x] 6.3 Apply `.is-new` class to new player cards for 2 seconds

- [x] **Task 7: Add CSS for lobby and player list** (AC: #1, #2, #3)
  - [x] 7.1 Add `.lobby-container` layout (centered, max-width 500px)
  - [x] 7.2 Add `.player-list` grid/flex layout
  - [x] 7.3 Add `.player-card` styling (touch-friendly, 48px min-height)
  - [x] 7.4 Add `.admin-badge` styling (crown icon with color)
  - [x] 7.5 Add `.is-new` animation (subtle highlight/fade-in)
  - [x] 7.6 Add `.player-card--you` styling to highlight current player

- [x] **Task 8: Unit tests for admin flag** (AC: #2)
  - [x] 8.1 Test: `set_admin()` sets `is_admin: True` on player
  - [x] 8.2 Test: `get_players_state()` includes `is_admin` field

- [x] **Task 9: WebSocket integration tests** (AC: #1, #3, #4)
  - [x] 9.1 Test: state broadcast includes all players with names
  - [x] 9.2 Test: state broadcast includes `is_admin` flags
  - [x] 9.3 Test: disconnect removes player from broadcast after grace period

- [x] **Task 10: E2E tests** (AC: #1, #2, #3)
  - [x] 10.1 Add tests to `tests/e2e/test_qr_and_player_flow.py`
  - [x] 10.2 Test: Player list renders with correct player count
  - [x] 10.3 Test: Admin badge visible for admin player
  - [x] 10.4 Test: New player animation applied

- [x] **Task 11: Verify no regressions**
  - [x] 11.1 Run `pytest tests/` - all pass
  - [x] 11.2 Run `ruff check` - no errors

## Dev Notes

### Existing Files to Modify

| File | Action |
|------|--------|
| `www/player.html` | Replace lobby placeholder with full structure |
| `www/js/player.js` | Add player list rendering logic |
| `www/css/styles.css` | Add lobby and player list CSS |
| `server/websocket.py` | Add disconnect handling and broadcast helper |
| `game/state.py` | Add `set_admin()` method, update `get_players_state()` |
| `game/player.py` | Add `is_admin` field |
| `const.py` | Add `LOBBY_DISCONNECT_GRACE_PERIOD` |

### Player State Structure

```json
{
  "type": "state",
  "phase": "LOBBY",
  "game_id": "abc123",
  "player_count": 5,
  "players": [
    {"name": "Sarah", "score": 0, "connected": true, "streak": 0, "is_admin": true},
    {"name": "Tom", "score": 0, "connected": true, "streak": 0, "is_admin": false}
  ]
}
```

### HTML: Lobby View Structure

```html
<div id="lobby-view" class="view hidden">
    <div class="lobby-container">
        <header class="lobby-header">
            <h1>Game Lobby</h1>
            <p id="player-count" class="player-count">0 players</p>
        </header>

        <div id="player-list" class="player-list">
            <!-- Player cards rendered by JS -->
        </div>

        <div id="qr-share-area" class="qr-share-area">
            <!-- QR code for sharing - Story 3.4 -->
            <p class="hint">Invite friends with the QR code</p>
        </div>

        <div id="lobby-status" class="lobby-status">
            <p>Waiting for host to start the game...</p>
        </div>
    </div>
</div>
```

### JavaScript: Player List Rendering

**NOTE:** `handleServerMessage()` already exists from Story 3.2. The code below UPDATES the existing function - do not create a duplicate.

```javascript
// Inside IIFE in player.js

let previousPlayers = [];

function renderPlayerList(players) {
    const listEl = document.getElementById('player-list');
    const countEl = document.getElementById('player-count');
    if (!listEl) return;

    // Update player count
    if (countEl) {
        const count = players.length;
        countEl.textContent = `${count} player${count !== 1 ? 's' : ''}`;
    }

    // Find new players by comparing with previous list
    const previousNames = previousPlayers.map(p => p.name);
    const newNames = players
        .filter(p => !previousNames.includes(p.name))
        .map(p => p.name);

    // Render player cards
    listEl.innerHTML = players.map(player => {
        const isNew = newNames.includes(player.name);
        const isYou = player.name === playerName;
        const classes = [
            'player-card',
            isNew ? 'is-new' : '',
            isYou ? 'player-card--you' : '',
            !player.connected ? 'player-card--disconnected' : ''
        ].filter(Boolean).join(' ');

        return `
            <div class="${classes}" data-player="${player.name}">
                <span class="player-name">
                    ${player.is_admin ? '<span class="admin-badge">👑</span>' : ''}
                    ${escapeHtml(player.name)}
                    ${isYou ? '<span class="you-badge">(You)</span>' : ''}
                </span>
            </div>
        `;
    }).join('');

    // Remove .is-new class after animation
    setTimeout(() => {
        listEl.querySelectorAll('.is-new').forEach(el => {
            el.classList.remove('is-new');
        });
    }, 2000);

    previousPlayers = [...players];
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Update handleServerMessage to render player list
function handleServerMessage(data) {
    const joinBtn = document.getElementById('join-btn');
    const nameInput = document.getElementById('name-input');

    if (data.type === 'state') {
        if (data.phase === 'LOBBY') {
            showView('lobby-view');
            renderPlayerList(data.players || []);
        }
        // Other phases handled in later stories
    } else if (data.type === 'error') {
        showJoinError(data.message);
        if (joinBtn) {
            joinBtn.disabled = false;
            joinBtn.textContent = 'Join Game';
        }
        if (nameInput) {
            nameInput.focus();
        }
        playerName = null;
    }
}
```

### CSS: Lobby Styles

```css
/* Lobby Container */
.lobby-container {
    max-width: 500px;
    margin: 0 auto;
    padding: 24px 16px;
}

.lobby-header {
    text-align: center;
    margin-bottom: 24px;
}

.lobby-header h1 {
    font-size: 24px;
    margin-bottom: 8px;
    color: #1f2937;
}

.player-count {
    font-size: 16px;
    color: #6b7280;
}

/* Player List */
.player-list {
    display: flex;
    flex-direction: column;
    gap: 8px;
    margin-bottom: 24px;
}

.player-card {
    display: flex;
    align-items: center;
    padding: 12px 16px;
    min-height: 48px;
    background: #f9fafb;
    border-radius: 8px;
    border: 1px solid #e5e7eb;
    transition: all 0.3s ease;
}

.player-card--you {
    background: #eff6ff;
    border-color: #3b82f6;
}

.player-card--disconnected {
    opacity: 0.5;
}

.player-name {
    display: flex;
    align-items: center;
    gap: 8px;
    font-size: 16px;
    color: #1f2937;
}

.admin-badge {
    font-size: 18px;
}

.you-badge {
    font-size: 12px;
    color: #3b82f6;
    font-weight: 500;
}

/* New player animation */
.player-card.is-new {
    animation: playerJoin 0.5s ease-out;
    background: #ecfdf5;
    border-color: #10b981;
}

@keyframes playerJoin {
    from {
        opacity: 0;
        transform: translateY(-10px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}

/* QR Share Area */
.qr-share-area {
    text-align: center;
    padding: 16px;
    margin-bottom: 16px;
}

/* Lobby Status */
.lobby-status {
    text-align: center;
    padding: 16px;
    color: #6b7280;
}
```

### WebSocket Handler: Disconnect Handling

```python
# server/websocket.py additions

import asyncio
from custom_components.beatify.const import LOBBY_DISCONNECT_GRACE_PERIOD

# Track pending removal tasks
_pending_removals: dict[str, asyncio.Task] = {}

async def handle_disconnect(ws: web.WebSocketResponse) -> None:
    """Handle WebSocket disconnection."""
    game_state = self.hass.data.get(DOMAIN, {}).get("game")
    if not game_state:
        return

    # Find player by WebSocket
    player_name = None
    for name, player in game_state.players.items():
        if player.ws == ws:
            player_name = name
            player.connected = False
            break

    if not player_name:
        return

    _LOGGER.info("Player disconnected: %s", player_name)

    # Broadcast disconnect state
    await broadcast_state(game_state)

    # Schedule removal after grace period
    async def remove_after_timeout():
        await asyncio.sleep(LOBBY_DISCONNECT_GRACE_PERIOD)
        if player_name in game_state.players:
            if not game_state.players[player_name].connected:
                game_state.remove_player(player_name)
                await broadcast_state(game_state)
                _LOGGER.info("Player removed after timeout: %s", player_name)
        if player_name in _pending_removals:
            del _pending_removals[player_name]

    task = asyncio.create_task(remove_after_timeout())
    _pending_removals[player_name] = task


async def broadcast_state(game_state) -> None:
    """Broadcast current game state to all connected players."""
    state_msg = {"type": "state", **game_state.get_state()}
    for player in game_state.players.values():
        if player.connected and not player.ws.closed:
            try:
                await player.ws.send_json(state_msg)
            except Exception:  # noqa: BLE001
                pass
```

### PlayerSession Update

```python
# game/player.py
@dataclass
class PlayerSession:
    """Represents a connected player."""

    name: str
    ws: web.WebSocketResponse
    score: int = 0
    streak: int = 0
    connected: bool = True
    is_admin: bool = False
    joined_at: float = field(default_factory=time.time)
```

### GameState Method Additions

```python
# game/state.py additions

def set_admin(self, name: str) -> bool:
    """Mark a player as the admin.

    Returns:
        True if successful, False if player not found
    """
    if name not in self.players:
        return False
    self.players[name].is_admin = True
    return True


def get_players_state(self) -> list[dict]:
    """Get player list for state broadcast."""
    return [
        {
            "name": p.name,
            "score": p.score,
            "connected": p.connected,
            "streak": p.streak,
            "is_admin": p.is_admin,
        }
        for p in self.players.values()
    ]
```

### Architecture Compliance

- **Vanilla JS only** - No frameworks
- **IIFE pattern** - All code inside existing closure
- **Real-time updates** - Lobby update delay < 500ms (NFR4)
- **Touch targets** - 48px min-height on player cards
- **Admin badge** - Crown emoji "👑" for visual clarity
- **HTML escaping** - Prevent XSS via `escapeHtml()` function

### Anti-Patterns to Avoid

- Do NOT use innerHTML without escaping player names (XSS risk)
- Do NOT implement "Start Game" button - that's Story 3.5
- Do NOT implement QR code display - that's Story 3.4
- Do NOT implement late join - that's Story 3.6
- Do NOT remove players immediately on disconnect - use 5s grace period

### Previous Story Learnings (3.2)

- WebSocket: Connection handling via `ws.onmessage`, `ws.onclose`
- State updates: `handleServerMessage()` receives all state changes
- Player name: Stored in `playerName` variable and `localStorage`
- View switching: `showView()` handles transitions

### References

- [Source: epics.md#Story-3.3] - FR17, FR18, FR19, NFR4
- [Source: architecture.md#WebSocket-Architecture] - State broadcast pattern
- [Source: project-context.md#WebSocket] - State message format
- [Source: 3-2-name-entry-and-join.md] - WebSocket client patterns

## Dev Agent Record

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Completion Notes List

- Added `is_admin` field to PlayerSession dataclass
- Added `set_admin()` method to GameState
- Updated `get_players_state()` to include `is_admin` field
- Added `LOBBY_DISCONNECT_GRACE_PERIOD = 5` constant
- Implemented disconnect handling with 5-second grace period in websocket.py
- Added `broadcast_state()` helper method
- Updated player.html with full lobby structure (player list, QR area, status)
- Added `renderPlayerList()` function with admin badge and "You" indicator
- Added `.is-new` animation for new player cards
- Added comprehensive lobby CSS styles
- Added unit tests for admin flag in test_player_session.py

### File List

- `custom_components/beatify/game/player.py` - Added `is_admin: bool = False` field
- `custom_components/beatify/game/state.py` - Added `set_admin()` method, updated `get_players_state()`
- `custom_components/beatify/const.py` - Added `LOBBY_DISCONNECT_GRACE_PERIOD = 5`
- `custom_components/beatify/server/websocket.py` - Added disconnect handling, `broadcast_state()` helper
- `custom_components/beatify/www/player.html` - Updated lobby structure with player list container
- `custom_components/beatify/www/js/player.js` - Added `renderPlayerList()`, `escapeHtml()`
- `custom_components/beatify/www/css/styles.css` - Added lobby and player list CSS
- `tests/unit/test_player_session.py` - Added TestAdminFlag test class
