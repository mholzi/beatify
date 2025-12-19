# Story 4.4: Submission Tracking Display

Status: ready-for-dev

## Story

As a **player**,
I want **to see who else has submitted their guess**,
so that **I feel the social pressure and excitement of the game**.

## Acceptance Criteria

1. **AC1:** Given round is in progress, When any player submits their guess, Then all players see an updated "submitted" indicator (FR28) And update appears within 500ms

2. **AC2:** Given submissions are being tracked, When player view displays, Then a scrolling row or list shows which players have submitted And submitted players are visually distinct (e.g., checkmark, grayed out)

3. **AC3:** Given all players have submitted, When the last submission is received, Then round can optionally auto-advance to reveal (admin preference) Or timer continues until expiry

4. **AC4:** Given player views submission row, When many players are in game (>10), Then row scrolls horizontally or shows count ("15/18 submitted")

## Tasks / Subtasks

**DEPENDENCY:** Requires Story 4.3 (Year Submission) for submission events.

- [ ] **Task 1: Add submission tracker UI to game view** (AC: #1, #2)
  - [ ] 1.1 Add `#submission-tracker` container to game-view in player.html
  - [ ] 1.2 Position below year selector or at top of game view
  - [ ] 1.3 Add submission counter element `#submission-count`
  - [ ] 1.4 Add player avatars/indicators row `#submitted-players`

- [ ] **Task 2: Style submission tracker** (AC: #2, #4)
  - [ ] 2.1 Create `.submission-tracker` container styles
  - [ ] 2.2 Create `.player-indicator` styles for avatars
  - [ ] 2.3 Add `.is-submitted` state styles (checkmark, green border)
  - [ ] 2.4 Add horizontal scroll for overflow
  - [ ] 2.5 Style submission counter

- [ ] **Task 3: Update state broadcast with submission info** (AC: #1)
  - [ ] 3.1 In `get_state()`, include `players[].submitted` field
  - [ ] 3.2 Include `submitted_count` in PLAYING state
  - [ ] 3.3 Broadcast state after each submission

- [ ] **Task 4: Render submission tracker on state update** (AC: #1, #2)
  - [ ] 4.1 In `updateGameView()`, call `renderSubmissionTracker(data.players)`
  - [ ] 4.2 Create `renderSubmissionTracker()` function
  - [ ] 4.3 Update player indicators based on `submitted` field
  - [ ] 4.4 Update counter text

- [ ] **Task 5: Handle large player counts** (AC: #4)
  - [ ] 5.1 If >10 players, show abbreviated view
  - [ ] 5.2 Show count: "X/Y submitted"
  - [ ] 5.3 Optionally show scrollable full list
  - [ ] 5.4 Highlight current player in list

- [ ] **Task 6: Handle all-submitted detection** (AC: #3)
  - [ ] 6.1 In GameState, add `all_submitted() -> bool` method
  - [ ] 6.2 After each submission, check if all submitted
  - [ ] 6.3 If all submitted AND auto_advance enabled, trigger reveal
  - [ ] 6.4 Add `auto_advance_on_all_submitted: bool` config option

- [ ] **Task 7: Visual feedback on new submission** (AC: #1)
  - [ ] 7.1 Add animation when player indicator changes to submitted
  - [ ] 7.2 Use subtle pulse or glow effect
  - [ ] 7.3 Animation completes within 500ms

- [ ] **Task 8: Current player highlight** (AC: #2)
  - [ ] 8.1 Identify current player in list (by name match)
  - [ ] 8.2 Add `.is-current-player` class
  - [ ] 8.3 Style to distinguish from others

- [ ] **Task 9: Unit tests for all_submitted** (AC: #3)
  - [ ] 9.1 Test: returns False when some not submitted
  - [ ] 9.2 Test: returns True when all submitted
  - [ ] 9.3 Test: handles empty player list

- [ ] **Task 10: E2E tests for submission tracker** (AC: #1, #2)
  - [ ] 10.1 Test: tracker displays in game view
  - [ ] 10.2 Test: tracker updates on submission
  - [ ] 10.3 Test: count shows correct values

- [ ] **Task 11: Verify no regressions**
  - [ ] 11.1 Run `pytest tests/` - all pass
  - [ ] 11.2 Run `ruff check` - no new issues
  - [ ] 11.3 Test year selector still works

## Dev Notes

### Files to Modify

| File | Action |
|------|--------|
| `www/player.html` | Add submission tracker UI |
| `www/js/player.js` | Add tracker rendering logic |
| `www/css/styles.css` | Add tracker styles |
| `game/state.py` | Add all_submitted(), update get_state() |

### HTML Submission Tracker

```html
<!-- Add to game-view in player.html, before year-selector-container -->
<div id="submission-tracker" class="submission-tracker">
    <div class="submission-header">
        <span id="submission-count" class="submission-count">0/0 submitted</span>
    </div>
    <div id="submitted-players" class="submitted-players">
        <!-- Player indicators populated dynamically -->
    </div>
</div>
```

### CSS Styles

```css
/* Submission Tracker */
.submission-tracker {
    width: 100%;
    margin-bottom: 16px;
    padding: 12px;
    background: #f9fafb;
    border-radius: 12px;
}

.submission-header {
    text-align: center;
    margin-bottom: 8px;
}

.submission-count {
    font-size: 14px;
    font-weight: 500;
    color: #6b7280;
}

/* Player Indicators Row */
.submitted-players {
    display: flex;
    gap: 8px;
    overflow-x: auto;
    padding: 4px 0;
    -webkit-overflow-scrolling: touch;
    scrollbar-width: none; /* Firefox */
}

.submitted-players::-webkit-scrollbar {
    display: none; /* Chrome, Safari */
}

/* Player Indicator */
.player-indicator {
    display: flex;
    flex-direction: column;
    align-items: center;
    min-width: 48px;
    flex-shrink: 0;
}

.player-avatar {
    width: 36px;
    height: 36px;
    border-radius: 50%;
    background: #e5e7eb;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 14px;
    font-weight: 600;
    color: #6b7280;
    border: 2px solid transparent;
    transition: all 0.3s ease;
}

.player-indicator.is-submitted .player-avatar {
    background: #10b981;
    color: white;
    border-color: #059669;
    animation: submitted-pulse 0.5s ease-out;
}

.player-indicator.is-submitted .player-avatar::after {
    content: '✓';
    font-size: 16px;
}

.player-indicator.is-submitted .player-initials {
    display: none;
}

@keyframes submitted-pulse {
    0% { transform: scale(1); }
    50% { transform: scale(1.2); }
    100% { transform: scale(1); }
}

.player-name {
    font-size: 10px;
    color: #6b7280;
    max-width: 48px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    text-align: center;
    margin-top: 4px;
}

/* Current Player Highlight */
.player-indicator.is-current-player .player-avatar {
    border-color: #6366f1;
}

.player-indicator.is-current-player .player-name {
    font-weight: 600;
    color: #6366f1;
}

/* Compact Mode for Many Players */
.submission-tracker.is-compact .submitted-players {
    justify-content: center;
}

.submission-tracker.is-compact .player-indicator {
    display: none;
}

.submission-tracker.is-compact .submission-count {
    font-size: 16px;
    font-weight: 600;
}

/* All Submitted State */
.submission-tracker.all-submitted {
    background: #d1fae5;
}

.submission-tracker.all-submitted .submission-count {
    color: #059669;
    font-weight: 600;
}
```

### JavaScript Implementation

```javascript
// player.js - Add to IIFE

function renderSubmissionTracker(players) {
    const tracker = document.getElementById('submission-tracker');
    const container = document.getElementById('submitted-players');
    const countEl = document.getElementById('submission-count');

    if (!tracker || !container || !countEl) return;

    const playerList = players || [];
    const submittedCount = playerList.filter(p => p.submitted).length;
    const totalCount = playerList.length;

    // Update count
    countEl.textContent = `${submittedCount}/${totalCount} submitted`;

    // Check if all submitted
    const allSubmitted = submittedCount === totalCount && totalCount > 0;
    tracker.classList.toggle('all-submitted', allSubmitted);

    // Compact mode for many players
    const isCompact = playerList.length > 10;
    tracker.classList.toggle('is-compact', isCompact);

    if (isCompact) {
        container.innerHTML = '';
        return;
    }

    // Render player indicators
    container.innerHTML = playerList.map(player => {
        const initials = getInitials(player.name);
        const isCurrentPlayer = player.name === playerName;
        const classes = [
            'player-indicator',
            player.submitted ? 'is-submitted' : '',
            isCurrentPlayer ? 'is-current-player' : ''
        ].filter(Boolean).join(' ');

        return `
            <div class="${classes}">
                <div class="player-avatar">
                    <span class="player-initials">${initials}</span>
                </div>
                <span class="player-name">${escapeHtml(player.name)}</span>
            </div>
        `;
    }).join('');
}

function getInitials(name) {
    if (!name) return '?';
    const parts = name.trim().split(/\s+/);
    if (parts.length >= 2) {
        return (parts[0][0] + parts[1][0]).toUpperCase();
    }
    return name.slice(0, 2).toUpperCase();
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// Update updateGameView to include tracker
function updateGameView(data) {
    // ... existing code for round indicator, album cover ...

    // Render submission tracker
    renderSubmissionTracker(data.players);
}
```

### Backend - State Update with Submitted Field

```python
# game/state.py - Update get_players_state()

def get_players_state(self) -> list[dict[str, Any]]:
    """Get player state for broadcast."""
    players = []
    for player in self.players.values():
        player_data = {
            "name": player.name,
            "score": player.score,
            "streak": player.streak,
            "connected": player.connected,
            "is_admin": player.is_admin,
        }

        # Include submission status during PLAYING phase
        if self.phase == GamePhase.PLAYING:
            player_data["submitted"] = player.submitted

        players.append(player_data)

    return players

def all_submitted(self) -> bool:
    """Check if all connected players have submitted."""
    connected_players = [p for p in self.players.values() if p.connected]
    if not connected_players:
        return False
    return all(p.submitted for p in connected_players)

# Update get_state() for PLAYING phase
def get_state(self) -> dict[str, Any] | None:
    # ... existing code ...

    if self.phase == GamePhase.PLAYING:
        state["round"] = self.round
        state["total_rounds"] = self.total_rounds
        state["deadline"] = self.deadline
        state["last_round"] = self.last_round
        state["songs_remaining"] = (
            self._playlist_manager.get_remaining_count()
            if self._playlist_manager else 0
        )
        state["submitted_count"] = sum(
            1 for p in self.players.values() if p.submitted
        )
        state["all_submitted"] = self.all_submitted()
        # ... song info ...
```

### Auto-Advance on All Submitted (Optional)

```python
# server/websocket.py - After recording submission

async def _handle_submit(
    self, ws: web.WebSocketResponse, data: dict
) -> None:
    """Handle guess submission."""
    # ... existing validation and recording ...

    # Send acknowledgment
    await ws.send_json({
        "type": "submit_ack",
        "year": year
    })

    # Broadcast updated state
    await self._broadcast_state()

    # Check for auto-advance (optional feature)
    if game.all_submitted():
        _LOGGER.info("All players submitted, checking auto-advance")
        # Could trigger early reveal here if configured
        # For now, let timer continue
```

### Architecture Compliance

- **Real-time Updates:** Broadcast state after each submission
- **Latency:** Updates within 500ms per NFR4
- **State Format:** Players list includes `submitted` field per architecture
- **Mobile-first:** Horizontal scroll, touch-friendly

### Anti-Patterns to Avoid

- Do NOT poll for submission status - use WebSocket push
- Do NOT include submitted status in REVEAL/END phases
- Do NOT block UI while updating tracker
- Do NOT show submission counts before game starts

### Previous Story Learnings

- State broadcast pattern works well
- Player list rendering established in lobby
- Animation helps draw attention to changes
- Compact mode improves UX for large groups

### Dependencies on Other Stories

- **Story 4.3:** Provides submission events and `submitted` field
- **Story 4.5:** May trigger reveal when all submitted
- **Story 4.6:** Uses submission data for scoring

### References

- [Source: epics.md#Story-4.4] - FR28
- [Source: architecture.md#WebSocket-Architecture] - State broadcast
- [Source: project-context.md#WebSocket] - Players state format
- [Source: project-context.md#Frontend-Rules] - CSS patterns

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

### File List
