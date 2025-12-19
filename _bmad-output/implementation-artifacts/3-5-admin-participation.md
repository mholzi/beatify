# Story 3.5: Admin Participation

Status: done

## Story

As a **host**,
I want **to join the game as a player while keeping admin controls**,
so that **I can play along with my guests**.

## Acceptance Criteria

1. **AC1:** Given host is on the admin page with active lobby, When host clicks "Participate", Then host is prompted to enter their display name (FR20) And host joins the lobby as a player And host's view transitions to player view with admin controls visible

2. **AC2:** Given host has joined as participant, When host views the lobby, Then host sees the same player list as other players And host's name shows admin badge (FR18) And host has a "Start Game" button that others don't see (FR21)

3. **AC3:** Given host is the only player in lobby, When host clicks "Start Game", Then game can still start (single-player testing mode)

4. **AC4:** Given multiple players are in lobby, When host clicks "Start Game", Then game transitions from LOBBY to PLAYING state And all connected players receive the state change via WebSocket

## Tasks / Subtasks

**CRITICAL:** Stories 3.2-3.4 established the player lobby experience. This story adds admin-specific functionality: joining as admin and starting the game.

- [x] **Task 1: Add "Participate" button to admin page** (AC: #1)
  - [x] 1.1 Add `#participate-btn` button in `admin.html` lobby section
  - [x] 1.2 Style button as primary action (visible, touch-friendly)
  - [x] 1.3 Show only when game is in LOBBY phase

- [x] **Task 2: Add admin name entry modal** (AC: #1)
  - [x] 2.1 Add `#admin-join-modal` with name input to `admin.html`
  - [x] 2.2 Add `openAdminJoinModal()` and `closeAdminJoinModal()` in `admin.js`
  - [x] 2.3 Validate name (same rules as player: 1-20 chars)

- [x] **Task 3: Implement admin WebSocket join** (AC: #1)
  - [x] 3.1 WebSocket join happens on player page after redirect (not admin page)
  - [x] 3.2 Player page sends join message: `{"type": "join", "name": "...", "is_admin": true}`
  - [x] 3.3 Update `_handle_message()` in `websocket.py` to handle `is_admin` flag
  - [x] 3.4 Call `game_state.set_admin(name)` for admin joins
  - [x] 3.5 Enforce single admin: if admin already exists, reject with `ERR_ADMIN_EXISTS`

- [x] **Task 4: Transition admin to player view** (AC: #1, #2)
  - [x] 4.1 Store admin name in `sessionStorage` before redirect
  - [x] 4.2 Redirect to `/beatify/play?game=<id>` (WebSocket join happens there)
  - [x] 4.3 Player page reads `sessionStorage`, auto-connects with `is_admin: true` flag

- [x] **Task 5: Show admin controls on player page** (AC: #2)
  - [x] 5.1 Add `#admin-controls` container to `player.html` (initially hidden)
  - [x] 5.2 Check `sessionStorage` or state `is_admin` flag on page load
  - [x] 5.3 Show controls only if current player is admin
  - [x] 5.4 Add "Start Game" button in admin controls

- [x] **Task 6: Implement "Start Game" button** (AC: #2, #3, #4)
  - [x] 6.1 Add click handler to send admin action: `{"type": "admin", "action": "start_game"}`
  - [x] 6.2 Update `_handle_message()` in `websocket.py` for `start_game` action
  - [x] 6.3 Validate sender is admin before processing
  - [x] 6.4 Call `game_state.start_game()` to transition LOBBY → PLAYING
  - [x] 6.5 Broadcast state change to all connected players

- [x] **Task 7: Implement start_game in GameState** (AC: #3, #4)
  - [x] 7.1 Add `start_game()` method to `game/state.py`
  - [x] 7.2 Validate phase is LOBBY before transition
  - [x] 7.3 Allow start with 1+ players (single-player mode for testing)
  - [x] 7.4 Transition phase to PLAYING
  - [x] 7.5 Return error code if invalid state (e.g., `ERR_GAME_ALREADY_STARTED`)

- [x] **Task 8: Style admin controls** (AC: #2)
  - [x] 8.1 Add `.admin-controls` CSS in `styles.css`
  - [x] 8.2 Position at bottom of lobby view
  - [x] 8.3 Make "Start Game" button prominent (large, colored)
  - [x] 8.4 Ensure controls don't obstruct player list

- [x] **Task 9: Unit tests for admin join** (AC: #1, #3)
  - [x] 9.1 Test: `set_admin()` correctly marks player as admin
  - [x] 9.2 Test: Only one admin allowed (reject second admin join)
  - [x] 9.3 Test: `start_game()` transitions LOBBY → PLAYING

- [x] **Task 10: WebSocket integration tests** (AC: #1, #4)
  - [x] 10.1 Test: Admin join with `is_admin: true` flag
  - [x] 10.2 Test: Start game action broadcasts PLAYING state
  - [x] 10.3 Test: Non-admin cannot send start_game action

- [x] **Task 11: E2E tests** (AC: #1, #2, #4)
  - [x] 11.1 Test: "Participate" button visible on admin page
  - [x] 11.2 Test: Admin join flow transitions to player view
  - [x] 11.3 Test: "Start Game" button visible only for admin
  - [x] 11.4 Test: Game starts when button clicked

- [x] **Task 12: Verify no regressions**
  - [x] 12.1 Run `pytest tests/` - all pass
  - [x] 12.2 Run `ruff check` - pre-existing formatting issues only

## Dev Notes

### Existing Files to Modify

| File | Action |
|------|--------|
| `www/admin.html` | Add "Participate" button and modal |
| `www/js/admin.js` | Add admin join and redirect logic |
| `www/player.html` | Add admin controls section |
| `www/js/player.js` | Add admin detection and Start Game handler |
| `www/css/styles.css` | Add admin controls CSS |
| `server/websocket.py` | Handle admin join and start_game action |
| `game/state.py` | Add `start_game()` method |
| `const.py` | Add `ERR_GAME_ALREADY_STARTED`, `ERR_NOT_ADMIN`, `ERR_ADMIN_EXISTS` |

### WebSocket Message Schema

**Client → Server (Admin Join):**
```json
{"type": "join", "name": "Sarah", "is_admin": true}
```

**Client → Server (Start Game):**
```json
{"type": "admin", "action": "start_game"}
```

**Server → Client (Game Started):**
```json
{
  "type": "state",
  "phase": "PLAYING",
  "round": 1,
  "total_rounds": 10,
  "players": [...],
  "song": {"artist": "...", "title": "...", "album_art": "..."}
}
```

### Admin Detection Strategy

Two options for detecting admin on player page:

**Option A: Query parameter (simpler)**
```javascript
// Admin page redirects to:
// /beatify/play?game=abc123&admin=true

const urlParams = new URLSearchParams(window.location.search);
const isAdmin = urlParams.get('admin') === 'true';
```

**Option B: State-based (more secure)**
```javascript
// Server includes is_admin in player's state
// Find current player and check flag
const currentPlayer = data.players.find(p => p.name === playerName);
const isAdmin = currentPlayer?.is_admin === true;
```

**Recommendation:** Use Option B (state-based) as it's verified by server and persists across reconnections.

### HTML: Admin Page Additions

```html
<!-- In admin.html, inside lobby section -->
<div class="admin-lobby-actions">
    <button id="participate-btn" class="btn btn-primary">
        <span class="btn-icon">🎮</span>
        Join as Player
    </button>
</div>

<!-- Admin join modal -->
<div id="admin-join-modal" class="modal hidden">
    <div class="modal-backdrop"></div>
    <div class="modal-content">
        <h2>Join the Game</h2>
        <p>Enter your display name to join as a player with admin controls.</p>
        <div class="form-group">
            <input type="text" id="admin-name-input" class="name-input"
                   placeholder="Your name" maxlength="20"
                   autocomplete="off" autocapitalize="words">
            <p id="admin-name-error" class="validation-msg hidden"></p>
        </div>
        <div class="modal-actions">
            <button id="admin-join-btn" class="btn btn-primary" disabled>Join</button>
            <button id="admin-cancel-btn" class="btn btn-secondary">Cancel</button>
        </div>
    </div>
</div>
```

### HTML: Player Page Admin Controls

```html
<!-- In player.html, inside #lobby-view -->
<div id="admin-controls" class="admin-controls hidden">
    <button id="start-game-btn" class="btn btn-primary btn-large">
        <span class="btn-icon">▶️</span>
        Start Game
    </button>
    <p class="admin-hint">Press when everyone is ready</p>
</div>
```

### JavaScript: Admin Join (admin.js)

```javascript
// In admin.js

function openAdminJoinModal() {
    const modal = document.getElementById('admin-join-modal');
    if (modal) {
        modal.classList.remove('hidden');
        document.getElementById('admin-name-input')?.focus();
    }
}

function closeAdminJoinModal() {
    const modal = document.getElementById('admin-join-modal');
    if (modal) {
        modal.classList.add('hidden');
    }
}

function setupAdminJoin() {
    const participateBtn = document.getElementById('participate-btn');
    const cancelBtn = document.getElementById('admin-cancel-btn');
    const joinBtn = document.getElementById('admin-join-btn');
    const nameInput = document.getElementById('admin-name-input');

    participateBtn?.addEventListener('click', openAdminJoinModal);
    cancelBtn?.addEventListener('click', closeAdminJoinModal);

    nameInput?.addEventListener('input', function() {
        const name = this.value.trim();
        joinBtn.disabled = !name || name.length > 20;
    });

    joinBtn?.addEventListener('click', async function() {
        const name = nameInput?.value.trim();
        if (!name) return;

        joinBtn.disabled = true;
        joinBtn.textContent = 'Joining...';

        try {
            // Store admin name for player page
            sessionStorage.setItem('beatify_admin_name', name);
            sessionStorage.setItem('beatify_is_admin', 'true');

            // Redirect to player page with game ID
            const gameId = currentGameId;  // From admin page state
            window.location.href = `/beatify/play?game=${gameId}`;
        } catch (err) {
            console.error('Admin join failed:', err);
            joinBtn.disabled = false;
            joinBtn.textContent = 'Join';
        }
    });
}

// Call on page load
setupAdminJoin();
```

### JavaScript: Admin Controls on Player Page (player.js)

```javascript
// Inside IIFE in player.js

let isAdmin = false;

function checkAdminStatus() {
    // Check sessionStorage first (redirect from admin page)
    const storedAdmin = sessionStorage.getItem('beatify_is_admin');
    const storedName = sessionStorage.getItem('beatify_admin_name');

    if (storedAdmin === 'true' && storedName) {
        isAdmin = true;
        playerName = storedName;
        // Clear storage after reading
        sessionStorage.removeItem('beatify_is_admin');
        // Keep name for reconnection
    }
    return isAdmin;
}

function updateAdminControls(players) {
    const adminControls = document.getElementById('admin-controls');
    if (!adminControls) return;

    // Find if current player is admin from state
    const currentPlayer = players.find(p => p.name === playerName);
    isAdmin = currentPlayer?.is_admin === true;

    if (isAdmin) {
        adminControls.classList.remove('hidden');
    } else {
        adminControls.classList.add('hidden');
    }
}

function setupAdminControls() {
    const startBtn = document.getElementById('start-game-btn');

    startBtn?.addEventListener('click', function() {
        if (!ws || ws.readyState !== WebSocket.OPEN) return;

        startBtn.disabled = true;
        startBtn.textContent = 'Starting...';

        ws.send(JSON.stringify({
            type: 'admin',
            action: 'start_game'
        }));
    });
}

// Update handleServerMessage to update admin controls
function handleServerMessage(data) {
    if (data.type === 'state') {
        if (data.phase === 'LOBBY') {
            showView('lobby-view');
            renderPlayerList(data.players || []);
            renderQRCode(data.join_url);
            updateAdminControls(data.players || []);
        } else if (data.phase === 'PLAYING') {
            // Transition to game view (implemented in Epic 4)
            showView('game-view');
        }
    }
    // ... rest of existing code ...
}

// Check admin status on page load
checkAdminStatus();
if (isAdmin) {
    // Auto-connect with stored name
    connectWebSocket(playerName);
}

// Initialize on DOM ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', setupAdminControls);
} else {
    setupAdminControls();
}
```

### Python: Start Game Implementation

```python
# game/state.py additions

def start_game(self) -> tuple[bool, str | None]:
    """Start the game, transitioning from LOBBY to PLAYING.

    Returns:
        (success, error_code) - error_code is None on success
    """
    if self.phase != GamePhase.LOBBY:
        return False, ERR_GAME_ALREADY_STARTED

    if len(self.players) == 0:
        return False, ERR_GAME_NOT_STARTED  # No players to play with

    self.phase = GamePhase.PLAYING
    self.round = 1
    # Song selection will be implemented in Epic 4
    _LOGGER.info("Game started: %d players", len(self.players))
    return True, None
```

```python
# server/websocket.py - handle admin actions

async def _handle_message(self, ws: web.WebSocketResponse, data: dict) -> None:
    msg_type = data.get("type")
    game_state = self.hass.data.get(DOMAIN, {}).get("game")

    # ... existing join handling ...

    if msg_type == "join":
        name = data.get("name", "").strip()
        is_admin = data.get("is_admin", False)

        success, error_code = game_state.add_player(name, ws)

        if success:
            if is_admin:
                # Enforce single admin
                existing_admin = any(p.is_admin for p in game_state.players.values())
                if existing_admin:
                    # Remove the just-added player and return error
                    game_state.remove_player(name)
                    await ws.send_json({
                        "type": "error",
                        "code": ERR_ADMIN_EXISTS,
                        "message": "Game already has an admin"
                    })
                    return
                game_state.set_admin(name)
            # ... existing broadcast logic ...

    elif msg_type == "admin":
        action = data.get("action")

        # Find sender's player session
        sender = None
        for player in game_state.players.values():
            if player.ws == ws:
                sender = player
                break

        if not sender or not sender.is_admin:
            await ws.send_json({
                "type": "error",
                "code": ERR_NOT_ADMIN,
                "message": "Only admin can perform this action"
            })
            return

        if action == "start_game":
            success, error_code = game_state.start_game()
            if success:
                await broadcast_state(game_state)
            else:
                await ws.send_json({
                    "type": "error",
                    "code": error_code,
                    "message": "Failed to start game"
                })
```

### CSS: Admin Controls

```css
/* Admin Controls */
.admin-controls {
    padding: 24px 16px;
    text-align: center;
    background: linear-gradient(to top, #f9fafb, transparent);
    position: sticky;
    bottom: 0;
}

.admin-controls.hidden {
    display: none;
}

.btn-large {
    min-height: 56px;
    font-size: 20px;
    padding: 16px 32px;
}

.btn-icon {
    margin-right: 8px;
}

.admin-hint {
    margin-top: 8px;
    font-size: 14px;
    color: #6b7280;
}

/* Admin page modal */
.admin-lobby-actions {
    text-align: center;
    margin-top: 24px;
}
```

### Architecture Compliance

- **Admin via WebSocket** - Uses same WS connection as players
- **State-based admin detection** - Server authoritative on `is_admin`
- **Single admin per game** - Enforced in `add_player()` logic
- **LOBBY → PLAYING transition** - Explicit state machine
- **Touch targets** - 56px for Start Game button

### Anti-Patterns to Avoid

- Do NOT implement full game view - that's Epic 4
- Do NOT implement media playback - that's Epic 4 Story 4.1
- Do NOT allow multiple admins - reject with error
- Do NOT trust client-side admin flag alone - verify via state

### Error Codes & Constants

Add these to `const.py`:

```python
ERR_NOT_ADMIN = "NOT_ADMIN"
ERR_ADMIN_EXISTS = "ADMIN_EXISTS"
ERR_GAME_ALREADY_STARTED = "GAME_ALREADY_STARTED"
```

| Code | Message | Scenario |
|------|---------|----------|
| `NOT_ADMIN` | "Only admin can perform this action" | Non-admin sends admin action |
| `ADMIN_EXISTS` | "Game already has an admin" | Second player tries to join as admin |
| `GAME_ALREADY_STARTED` | "Game has already started" | Start when not in LOBBY |

### Previous Story Learnings (3.3, 3.4)

- Player list rendering: `renderPlayerList()` handles updates
- Modal pattern: Backdrop click to close, keyboard support
- State updates: `handleServerMessage()` is central handler
- Admin badge: Crown emoji "👑" established

### References

- [Source: epics.md#Story-3.5] - FR20, FR21
- [Source: architecture.md#WebSocket-Architecture] - Admin actions
- [Source: architecture.md#Game-State-Machine] - LOBBY → PLAYING
- [Source: project-context.md#State-Machine] - Valid transitions

## Dev Agent Record

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Completion Notes List

- Added "Join as Player" button to admin.html lobby section
- Added admin join modal with name input and validation
- Implemented `openAdminJoinModal()`, `closeAdminJoinModal()`, `setupAdminJoin()`, `handleAdminJoin()` in admin.js
- Uses sessionStorage for admin redirect flow (beatify_admin_name, beatify_is_admin)
- Added `ERR_ADMIN_EXISTS` and `ERR_NOT_ADMIN` constants
- Updated websocket.py to handle `is_admin` flag on join and enforce single admin
- Added admin action handling for `start_game` in websocket.py
- Added `start_game()` method to GameState with LOBBY → PLAYING transition
- Added admin controls section to player.html with "Start Game" button
- Added `checkAdminStatus()`, `updateAdminControls()`, `setupAdminControls()` in player.js
- State-based admin verification (server authoritative on is_admin)

### File List

- `custom_components/beatify/const.py` - Added `ERR_ADMIN_EXISTS`, `ERR_NOT_ADMIN`
- `custom_components/beatify/game/state.py` - Added `start_game()` method
- `custom_components/beatify/server/websocket.py` - Added admin join handling, start_game action
- `custom_components/beatify/www/admin.html` - Added "Join as Player" button and admin join modal
- `custom_components/beatify/www/js/admin.js` - Added admin join modal functions
- `custom_components/beatify/www/player.html` - Added admin controls section
- `custom_components/beatify/www/js/player.js` - Added admin detection and Start Game handler
- `custom_components/beatify/www/css/styles.css` - Added admin controls and modal styles
- `tests/integration/test_websocket.py` - Added admin join and start_game tests
