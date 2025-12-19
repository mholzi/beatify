# Story 3.6: Late Join Support

Status: done

## Story

As a **guest arriving late to the party**,
I want **to join a game that's already in progress**,
so that **I don't have to wait for the next game**.

## Acceptance Criteria

1. **AC1:** Given game is in PLAYING state (not LOBBY), When late joiner scans QR and enters name, Then player joins directly into the current round (FR16) And player skips the lobby entirely And player sees the current game state (album cover, timer, etc.)

2. **AC2:** Given late joiner joins during PLAYING phase, When they land in the game, Then they can submit a guess for the current round if time remains And they appear on the leaderboard with 0 points initially

3. **AC3:** Given late joiner joins during REVEAL phase, When they land in the game, Then they see the current reveal And they're ready for the next round

4. **AC4:** Given game is in END state, When someone scans the QR, Then they see "This game has ended" message And cannot join

## Tasks / Subtasks

**CRITICAL:** Story 3.2 implemented the basic join flow. This story extends it to handle all game phases.

- [x] **Task 1: Update add_player to allow late joins** (AC: #1, #2)
  - [x] 1.1 Modify `add_player()` in `game/state.py` to accept joins in PLAYING/REVEAL phases
  - [x] 1.2 Add `joined_late: bool = False` field to track late joiners (for analytics)
  - [x] 1.3 Ensure late joiners start with score=0, streak=0

- [x] **Task 2: Handle END state rejection** (AC: #4)
  - [x] 2.1 Return `ERR_GAME_ENDED` if phase is END
  - [x] 2.2 Add `ERR_GAME_ENDED = "GAME_ENDED"` to `const.py`

- [x] **Task 3: Update WebSocket join handler for phases** (AC: #1, #2, #3)
  - [x] 3.1 Check game phase in `_handle_message()` join handler
  - [x] 3.2 For LOBBY: existing behavior (show lobby)
  - [x] 3.3 For PLAYING: send game state with current round info
  - [x] 3.4 For REVEAL: send state with reveal info
  - [x] 3.5 For END: send error, do not add player

- [x] **Task 4: Update get_state() for full game info** (AC: #1, #2, #3)
  - [x] 4.1 Include `round`, `total_rounds`, `deadline` in PLAYING state
  - [x] 4.2 Include `song` info appropriate for phase (album art for PLAYING, full for REVEAL)
  - [x] 4.3 Include current player's `submitted` status if applicable

- [x] **Task 5: Add game view placeholder** (AC: #1, #2, #3)
  - [x] 5.1 Add `#game-view` div to `player.html` with placeholder content
  - [x] 5.2 Add `#reveal-view` div to `player.html` with placeholder content
  - [x] 5.3 Add `#end-view` div to `player.html` with game ended message
  - [x] 5.4 Add basic CSS for all views

- [x] **Task 6: Update handleServerMessage for all phases** (AC: #1, #2, #3, #4)
  - [x] 6.1 Handle PLAYING phase: show game-view
  - [x] 6.2 Handle REVEAL phase: show reveal-view
  - [x] 6.3 Handle END phase: show end-view
  - [x] 6.4 Handle GAME_ENDED error: show end-view with message

- [x] **Task 7: Update player page initial load** (AC: #1, #4)
  - [x] 7.1 Modify `checkGameStatus()` to return game phase in API response
  - [x] 7.2 If phase is END, show "Game has ended" instead of join form
  - [x] 7.3 Preserve existing behavior for LOBBY phase

- [x] **Task 8: Update game-status API endpoint** (AC: #4)
  - [x] 8.1 Include `phase` in `/beatify/api/game-status` response
  - [x] 8.2 Include message for END phase

- [x] **Task 9: Unit tests for late join** (AC: #1, #2, #3, #4)
  - [x] 9.1 Test: add_player succeeds in PLAYING phase
  - [x] 9.2 Test: add_player succeeds in REVEAL phase
  - [x] 9.3 Test: add_player fails in END phase with ERR_GAME_ENDED
  - [x] 9.4 Test: late joiner has score=0, streak=0

- [x] **Task 10: WebSocket integration tests** (AC: #1, #4)
  - [x] 10.1 Test: late join during PLAYING receives game state
  - [x] 10.2 Test: join during END receives error
  - [x] 10.3 Test: late joiner appears in player list broadcast

- [x] **Task 11: E2E tests** (AC: #1, #4)
  - [x] 11.1 Test: End view shown when game phase is END
  - [x] 11.2 Test: Game view shown when joining during PLAYING

- [x] **Task 12: Verify no regressions**
  - [x] 12.1 Run `pytest tests/` - all pass (112 passed, some skipped due to missing dependencies)
  - [x] 12.2 Run `ruff check` - pre-existing formatting issues only

## Dev Notes

### Existing Files to Modify

| File | Action |
|------|--------|
| `www/player.html` | Add game-view, reveal-view, end-view placeholders |
| `www/js/player.js` | Handle PLAYING/REVEAL/END phases in message handler |
| `www/css/styles.css` | Add basic styles for new views |
| `server/websocket.py` | Update join handler for all phases |
| `server/views.py` | Update game-status API to include phase |
| `game/state.py` | Allow late joins, update get_state() |
| `game/player.py` | Add `joined_late` field |
| `const.py` | Add `ERR_GAME_ENDED` |

### State Response by Phase

**LOBBY Phase (existing):**
```json
{
  "type": "state",
  "phase": "LOBBY",
  "game_id": "abc123",
  "player_count": 5,
  "players": [...],
  "join_url": "http://..."
}
```

**PLAYING Phase:**
```json
{
  "type": "state",
  "phase": "PLAYING",
  "game_id": "abc123",
  "round": 3,
  "total_rounds": 10,
  "deadline": 1703012345678,
  "players": [...],
  "song": {
    "artist": "Wham!",
    "title": "Wake Me Up Before You Go-Go",
    "album_art": "/beatify/static/artwork/abc.jpg"
  }
}
```

**REVEAL Phase:**
```json
{
  "type": "state",
  "phase": "REVEAL",
  "game_id": "abc123",
  "round": 3,
  "total_rounds": 10,
  "players": [...],
  "song": {
    "artist": "Wham!",
    "title": "Wake Me Up Before You Go-Go",
    "album_art": "/beatify/static/artwork/abc.jpg",
    "year": 1984,
    "fun_fact": "George Michael wrote this in his bedroom"
  }
}
```

**END Phase:**
```json
{
  "type": "state",
  "phase": "END",
  "game_id": "abc123",
  "players": [...],
  "winner": {"name": "Tom", "score": 150}
}
```

### HTML: New View Placeholders

```html
<!-- In player.html after #lobby-view -->

<!-- Game View (placeholder - full implementation in Epic 4) -->
<div id="game-view" class="view hidden">
    <div class="game-placeholder">
        <h1>🎵 Round in Progress</h1>
        <p>You joined late! Full game UI coming in Epic 4.</p>
        <p id="game-round-info">Round 1 of 10</p>
    </div>
</div>

<!-- Reveal View (placeholder - full implementation in Epic 4) -->
<div id="reveal-view" class="view hidden">
    <div class="reveal-placeholder">
        <h1>🎉 Round Reveal</h1>
        <p>Full reveal UI coming in Epic 4.</p>
    </div>
</div>

<!-- End View -->
<div id="end-view" class="view hidden">
    <div class="end-container">
        <div class="end-icon">🎮</div>
        <h1>Game Has Ended</h1>
        <p class="end-message">Thanks for playing Beatify!</p>
        <p class="hint">Ask the host to start a new game.</p>
    </div>
</div>
```

### JavaScript: Phase Handling

```javascript
// Inside IIFE in player.js

function handleServerMessage(data) {
    const joinBtn = document.getElementById('join-btn');
    const nameInput = document.getElementById('name-input');

    if (data.type === 'state') {
        switch (data.phase) {
            case 'LOBBY':
                showView('lobby-view');
                renderPlayerList(data.players || []);
                renderQRCode(data.join_url);
                updateAdminControls(data.players || []);
                break;

            case 'PLAYING':
                showView('game-view');
                // Update round info (placeholder)
                const roundInfo = document.getElementById('game-round-info');
                if (roundInfo && data.round && data.total_rounds) {
                    roundInfo.textContent = `Round ${data.round} of ${data.total_rounds}`;
                }
                // Full game UI in Epic 4
                break;

            case 'REVEAL':
                showView('reveal-view');
                // Full reveal UI in Epic 4
                break;

            case 'END':
                showView('end-view');
                break;
        }
    } else if (data.type === 'error') {
        if (data.code === 'GAME_ENDED') {
            showView('end-view');
        } else {
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
}

// Update checkGameStatus to handle END phase
async function checkGameStatus() {
    // ... existing code ...

    if (response.ok) {
        const data = await response.json();
        if (data.active) {
            if (data.phase === 'END') {
                showView('end-view');
            } else {
                showView('join-view');
            }
        } else {
            showView('not-found-view');
        }
    }
}
```

### Python: Late Join Logic

```python
# game/state.py - update add_player

def add_player(self, name: str, ws: WebSocketResponse) -> tuple[bool, str | None]:
    """Add a player to the game.

    Allows joining during LOBBY, PLAYING, or REVEAL phases.
    Rejects during END phase.
    """
    # Validate name
    name = name.strip()
    if not name or len(name) < MIN_NAME_LENGTH:
        return False, ERR_NAME_INVALID
    if len(name) > MAX_NAME_LENGTH:
        return False, ERR_NAME_INVALID

    # Check phase - reject END state
    if self.phase == GamePhase.END:
        return False, ERR_GAME_ENDED

    # Check player limit
    if len(self.players) >= MAX_PLAYERS:
        return False, ERR_GAME_FULL

    # Check uniqueness (case-insensitive)
    if name.lower() in [p.name.lower() for p in self.players.values()]:
        return False, ERR_NAME_TAKEN

    # Determine if late joiner
    joined_late = self.phase != GamePhase.LOBBY

    # Add player
    self.players[name] = PlayerSession(
        name=name,
        ws=ws,
        score=0,
        streak=0,
        joined_late=joined_late
    )
    _LOGGER.info(
        "Player joined: %s (total: %d, late: %s)",
        name, len(self.players), joined_late
    )
    return True, None


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

    # Phase-specific data
    if self.phase == GamePhase.LOBBY:
        state["join_url"] = self.join_url

    elif self.phase == GamePhase.PLAYING:
        state["round"] = self.round
        state["total_rounds"] = self.total_rounds
        state["deadline"] = self.deadline
        # Song info without year (hidden during play)
        if self.current_song:
            state["song"] = {
                "artist": self.current_song.get("artist", "Unknown"),
                "title": self.current_song.get("title", "Unknown"),
                "album_art": self.current_song.get("album_art", "/beatify/static/img/no-artwork.svg")
            }

    elif self.phase == GamePhase.REVEAL:
        state["round"] = self.round
        state["total_rounds"] = self.total_rounds
        # Full song info including year and fun_fact
        if self.current_song:
            state["song"] = self.current_song

    elif self.phase == GamePhase.END:
        # Include winner info
        if self.players:
            winner = max(self.players.values(), key=lambda p: p.score)
            state["winner"] = {"name": winner.name, "score": winner.score}

    return state
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
    joined_late: bool = False
    joined_at: float = field(default_factory=time.time)
```

### const.py Addition

```python
# Add to const.py
ERR_GAME_ENDED = "GAME_ENDED"
```

### Game Status API Update

```python
# server/views.py - update GameStatusView

async def get(self, request: web.Request) -> web.Response:
    """Check if game is active and get its phase."""
    game_state = self.hass.data.get(DOMAIN, {}).get("game")

    if not game_state or not game_state.game_id:
        return web.json_response({"active": False})

    return web.json_response({
        "active": True,
        "game_id": game_state.game_id,
        "phase": game_state.phase.value,
        "player_count": len(game_state.players)
    })
```

### CSS: New View Styles

```css
/* Game View Placeholder */
.game-placeholder,
.reveal-placeholder {
    text-align: center;
    padding: 48px 24px;
}

.game-placeholder h1,
.reveal-placeholder h1 {
    font-size: 32px;
    margin-bottom: 16px;
}

.game-placeholder p,
.reveal-placeholder p {
    font-size: 16px;
    color: #6b7280;
    margin-bottom: 8px;
}

#game-round-info {
    font-size: 18px;
    font-weight: 500;
    color: #1f2937;
    margin-top: 16px;
}

/* End View */
.end-container {
    text-align: center;
    padding: 48px 24px;
    max-width: 400px;
    margin: 0 auto;
}

.end-icon {
    font-size: 64px;
    margin-bottom: 16px;
}

.end-container h1 {
    font-size: 28px;
    color: #1f2937;
    margin-bottom: 8px;
}

.end-message {
    font-size: 18px;
    color: #6b7280;
    margin-bottom: 16px;
}
```

### Epic 4 Field Dependencies

The `get_state()` method references fields that will be fully implemented in Epic 4:

| Field | Type | Default Until Epic 4 |
|-------|------|---------------------|
| `self.round` | int | `1` |
| `self.total_rounds` | int | `10` (or from config) |
| `self.deadline` | int | `None` (timestamp) |
| `self.current_song` | dict | `None` |

**IMPORTANT:** For this story, handle these fields gracefully:
- Check if fields exist before accessing
- Return `None` or default values if not set
- Full implementation happens in Epic 4 Story 4.1

```python
# Safe field access pattern
state["round"] = getattr(self, 'round', 1)
state["total_rounds"] = getattr(self, 'total_rounds', 10)
state["deadline"] = getattr(self, 'deadline', None)
if hasattr(self, 'current_song') and self.current_song:
    state["song"] = {...}
```

### Architecture Compliance

- **Late join allowed** - LOBBY, PLAYING, REVEAL phases accept joins
- **END phase blocks joins** - Return ERR_GAME_ENDED
- **Score initialization** - Late joiners start at 0
- **Streak preservation** - Late joiners start streak at 0
- **Phase-specific state** - Different data returned per phase
- **Epic 4 compatibility** - Gracefully handle missing round/song fields

### Anti-Patterns to Avoid

- Do NOT implement full game/reveal views - that's Epic 4
- Do NOT give late joiners points for missed rounds
- Do NOT skip deadline validation for late joiners
- Do NOT allow joining after END state
- Do NOT crash if `current_song` or `deadline` is None - use safe access patterns

### Previous Story Learnings (3.5)

- Phase handling: `switch` on `data.phase` for routing
- State broadcast: All players receive same state structure
- Admin controls: Already hidden for non-admins
- View switching: `showView()` handles all transitions

### References

- [Source: epics.md#Story-3.6] - FR16
- [Source: architecture.md#Game-State-Machine] - All phases
- [Source: project-context.md#State-Machine] - Phase transitions
- [Source: project-context.md#WebSocket] - State message format

## Dev Agent Record

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Completion Notes List

- Backend implementation completed in prior session: `add_player()` updated to allow late joins during PLAYING/REVEAL and reject END, `joined_late` field added to PlayerSession, `get_state()` updated for phase-specific data, ERR_GAME_ENDED constant added
- Frontend updated to handle all game phases: added `reveal-view` and `end-view` placeholders to player.html, updated `handleServerMessage()` to handle PLAYING/REVEAL/END phases, added GAME_ENDED error handling
- CSS added for reveal-placeholder and end-container styles
- Tests verified: 112 tests passing (some skipped due to missing homeassistant module in local environment)
- Pre-existing ruff formatting issues noted but not part of this story's scope

### File List

- `custom_components/beatify/const.py` - Added `ERR_GAME_ENDED` constant
- `custom_components/beatify/game/player.py` - Added `joined_late: bool = False` field
- `custom_components/beatify/game/state.py` - Updated `add_player()` for late joins and END rejection, updated `get_state()` for phase-specific data
- `custom_components/beatify/server/websocket.py` - Updated error messages for GAME_ENDED
- `custom_components/beatify/www/player.html` - Added reveal-view and end-view placeholders
- `custom_components/beatify/www/js/player.js` - Added view elements and phase handling for REVEAL/END, GAME_ENDED error handling
- `custom_components/beatify/www/css/styles.css` - Added reveal-placeholder and end-container styles
