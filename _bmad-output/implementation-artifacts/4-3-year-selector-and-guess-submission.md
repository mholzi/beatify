# Story 4.3: Year Selector & Guess Submission

Status: ready-for-dev

## Story

As a **player**,
I want **to select a year and submit my guess**,
so that **I can compete by guessing when the song was released**.

## Acceptance Criteria

1. **AC1:** Given player is viewing the round screen, When player interacts with year selector, Then a smooth, draggable slider or picker allows year selection (FR25) And year range spans reasonable bounds (e.g., 1950-2025) And selector responds at 60fps (NFR3)

2. **AC2:** Given player has selected a year, When player taps "Submit" button, Then guess is sent to server via WebSocket (FR26) And submission timestamp is recorded for speed bonus calculation

3. **AC3:** Given player submits their guess, When server acknowledges, Then player sees visual confirmation (checkmark, "Submitted!") (FR27) And submit button becomes disabled And player cannot change their guess

4. **AC4:** Given player has not submitted, When they try to submit after timer expires, Then submission is rejected by server And player sees "Time's up!" message

## Tasks / Subtasks

**DEPENDENCY:** Requires Story 4.2 (Round Display) for game-view UI integration.

- [ ] **Task 1: Create year selector UI** (AC: #1)
  - [ ] 1.1 Add year selector to `#year-selector-container` in player.html
  - [ ] 1.2 Use `<input type="range">` for slider implementation
  - [ ] 1.3 Set min="1950" max="2025" (configurable via JS)
  - [ ] 1.4 Add year display element showing current selection
  - [ ] 1.5 Add Submit button below slider

- [ ] **Task 2: Style year selector** (AC: #1)
  - [ ] 2.1 Create custom slider styles (webkit and moz)
  - [ ] 2.2 Make thumb large (44x44px minimum for touch)
  - [ ] 2.3 Add track styling with gradient or markers
  - [ ] 2.4 Style year display as large, prominent number
  - [ ] 2.5 Style Submit button - large, prominent, touch-friendly

- [ ] **Task 3: Implement year selector interaction** (AC: #1)
  - [ ] 3.1 Add `input` event listener to slider
  - [ ] 3.2 Update year display on slider change
  - [ ] 3.3 Use requestAnimationFrame for smooth updates
  - [ ] 3.4 Add haptic feedback on mobile if available

- [ ] **Task 4: Implement guess submission** (AC: #2)
  - [ ] 4.1 Add click handler to Submit button
  - [ ] 4.2 Get current year value from slider
  - [ ] 4.3 Send WebSocket message: `{"type": "submit", "year": number}`
  - [ ] 4.4 Disable button after click to prevent double submit
  - [ ] 4.5 Show loading state on button

- [ ] **Task 5: Handle server acknowledgment** (AC: #3)
  - [ ] 5.1 Listen for `submit_ack` message type in handleServerMessage
  - [ ] 5.2 Replace Submit button with "Submitted!" confirmation
  - [ ] 5.3 Add checkmark icon to confirmation
  - [ ] 5.4 Disable slider to prevent changes
  - [ ] 5.5 Add visual styling for submitted state

- [ ] **Task 6: Backend - handle submit message** (AC: #2, #4)
  - [ ] 6.1 In websocket.py, handle `type: "submit"` messages
  - [ ] 6.2 Validate player is in game
  - [ ] 6.3 Validate game phase is PLAYING
  - [ ] 6.4 Validate deadline not passed (reject if expired)
  - [ ] 6.5 Record submission: year, timestamp
  - [ ] 6.6 Send acknowledgment back to player

- [ ] **Task 7: Add submission tracking to PlayerSession** (AC: #2, #3)
  - [ ] 7.1 Add `submitted: bool = False` field
  - [ ] 7.2 Add `current_guess: int | None` field
  - [ ] 7.3 Add `submission_time: float | None` field
  - [ ] 7.4 Add method `submit_guess(year: int, time: float)`

- [ ] **Task 8: Handle expired submissions** (AC: #4)
  - [ ] 8.1 Check `deadline` before accepting submission
  - [ ] 8.2 If expired, send error: `ERR_ROUND_EXPIRED`
  - [ ] 8.3 Client shows "Time's up!" message on error
  - [ ] 8.4 Do NOT modify player state if rejected

- [ ] **Task 9: Handle already submitted** (AC: #3)
  - [ ] 9.1 Check `submitted` flag before accepting
  - [ ] 9.2 If already submitted, send error: `ERR_ALREADY_SUBMITTED`
  - [ ] 9.3 Client ignores (UI already in submitted state)

- [ ] **Task 10: Reset submission state for new round** (AC: #2, #3)
  - [ ] 10.1 In `start_round()`, reset all player submission states
  - [ ] 10.2 Clear `submitted`, `current_guess`, `submission_time`
  - [ ] 10.3 Client resets UI when receiving new PLAYING state

- [ ] **Task 11: Update state broadcast with submission status** (AC: #3)
  - [ ] 11.1 Include player's `submitted` status in personal state
  - [ ] 11.2 Broadcast to all when a player submits (for 4.4)

- [ ] **Task 12: Unit tests for submission handling** (AC: #2, #4)
  - [ ] 12.1 Test: valid submission is recorded
  - [ ] 12.2 Test: expired submission is rejected
  - [ ] 12.3 Test: duplicate submission is rejected
  - [ ] 12.4 Test: submission_time is recorded

- [ ] **Task 13: WebSocket integration tests** (AC: #2, #3, #4)
  - [ ] 13.1 Test: submit message returns ack
  - [ ] 13.2 Test: expired submit returns error
  - [ ] 13.3 Test: submit updates player state

- [ ] **Task 14: E2E tests for year selector** (AC: #1, #3)
  - [ ] 14.1 Test: slider is visible in game view
  - [ ] 14.2 Test: submit button click sends message
  - [ ] 14.3 Test: submitted state shows confirmation

- [ ] **Task 15: Verify no regressions**
  - [ ] 15.1 Run `pytest tests/` - all pass
  - [ ] 15.2 Run `ruff check` - no new issues
  - [ ] 15.3 Test countdown still works with selector

## Dev Notes

### Files to Modify

| File | Action |
|------|--------|
| `www/player.html` | Add year selector UI |
| `www/js/player.js` | Add slider interaction, submission logic |
| `www/css/styles.css` | Add slider and submission styles |
| `server/websocket.py` | Handle submit message |
| `game/player.py` | Add submission fields |
| `game/state.py` | Add submit_guess method |
| `const.py` | Add ERR_ROUND_EXPIRED, ERR_ALREADY_SUBMITTED |

### HTML Year Selector

```html
<!-- Add inside #year-selector-container in player.html -->
<div id="year-selector" class="year-selector">
    <div class="year-display">
        <span id="selected-year">1990</span>
    </div>

    <div class="slider-container">
        <span class="slider-label slider-label--min">1950</span>
        <input type="range"
               id="year-slider"
               min="1950"
               max="2025"
               value="1990"
               class="year-slider">
        <span class="slider-label slider-label--max">2025</span>
    </div>

    <button id="submit-btn" class="submit-btn">
        Submit Guess
    </button>

    <div id="submitted-confirmation" class="submitted-confirmation hidden">
        <span class="checkmark">✓</span>
        <span>Submitted!</span>
    </div>
</div>
```

### CSS Styles

```css
/* Year Selector */
.year-selector {
    width: 100%;
    padding: 16px 0;
}

.year-display {
    text-align: center;
    margin-bottom: 16px;
}

#selected-year {
    font-size: 56px;
    font-weight: 700;
    color: #1f2937;
    font-variant-numeric: tabular-nums;
}

/* Slider Container */
.slider-container {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 24px;
}

.slider-label {
    font-size: 12px;
    color: #6b7280;
    min-width: 40px;
}

.slider-label--min {
    text-align: right;
}

.slider-label--max {
    text-align: left;
}

/* Custom Range Slider */
.year-slider {
    -webkit-appearance: none;
    appearance: none;
    flex: 1;
    height: 8px;
    background: #e5e7eb;
    border-radius: 4px;
    outline: none;
}

.year-slider::-webkit-slider-thumb {
    -webkit-appearance: none;
    appearance: none;
    width: 44px;
    height: 44px;
    background: #6366f1;
    border-radius: 50%;
    cursor: pointer;
    border: 4px solid white;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
    transition: transform 0.1s ease;
}

.year-slider::-webkit-slider-thumb:active {
    transform: scale(1.1);
}

.year-slider::-moz-range-thumb {
    width: 44px;
    height: 44px;
    background: #6366f1;
    border-radius: 50%;
    cursor: pointer;
    border: 4px solid white;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
}

/* Submit Button */
.submit-btn {
    width: 100%;
    padding: 16px 24px;
    font-size: 18px;
    font-weight: 600;
    color: white;
    background: #6366f1;
    border: none;
    border-radius: 12px;
    cursor: pointer;
    transition: all 0.2s ease;
    min-height: 56px;
}

.submit-btn:hover {
    background: #4f46e5;
}

.submit-btn:active {
    transform: scale(0.98);
}

.submit-btn:disabled {
    background: #9ca3af;
    cursor: not-allowed;
    transform: none;
}

.submit-btn.is-loading {
    color: transparent;
    position: relative;
}

.submit-btn.is-loading::after {
    content: '';
    position: absolute;
    width: 24px;
    height: 24px;
    border: 3px solid white;
    border-top-color: transparent;
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    left: 50%;
    top: 50%;
    margin-left: -12px;
    margin-top: -12px;
}

/* Submitted Confirmation */
.submitted-confirmation {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 16px;
    background: #10b981;
    color: white;
    border-radius: 12px;
    font-size: 18px;
    font-weight: 600;
}

.submitted-confirmation .checkmark {
    font-size: 24px;
}

/* Submitted state for slider */
.year-selector.is-submitted .year-slider {
    pointer-events: none;
    opacity: 0.5;
}

.year-selector.is-submitted #selected-year {
    color: #6b7280;
}
```

### JavaScript Implementation

```javascript
// player.js - Add to IIFE

let hasSubmitted = false;

function initYearSelector() {
    const slider = document.getElementById('year-slider');
    const yearDisplay = document.getElementById('selected-year');

    if (!slider || !yearDisplay) return;

    // Update display on slider change
    slider.addEventListener('input', function() {
        yearDisplay.textContent = this.value;
    });

    // Submit button handler
    const submitBtn = document.getElementById('submit-btn');
    if (submitBtn) {
        submitBtn.addEventListener('click', handleSubmitGuess);
    }
}

function handleSubmitGuess() {
    if (hasSubmitted) return;

    const slider = document.getElementById('year-slider');
    const submitBtn = document.getElementById('submit-btn');

    if (!slider || !submitBtn) return;

    const year = parseInt(slider.value, 10);

    // Disable and show loading
    submitBtn.disabled = true;
    submitBtn.classList.add('is-loading');

    // Send submission via WebSocket
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
            type: 'submit',
            year: year
        }));
    } else {
        // WebSocket not connected
        showSubmitError('Connection lost. Please refresh.');
        submitBtn.disabled = false;
        submitBtn.classList.remove('is-loading');
    }
}

function handleSubmitAck(data) {
    hasSubmitted = true;

    const yearSelector = document.getElementById('year-selector');
    const submitBtn = document.getElementById('submit-btn');
    const confirmation = document.getElementById('submitted-confirmation');

    if (yearSelector) {
        yearSelector.classList.add('is-submitted');
    }

    if (submitBtn) {
        submitBtn.classList.add('hidden');
    }

    if (confirmation) {
        confirmation.classList.remove('hidden');
    }
}

function handleSubmitError(data) {
    const submitBtn = document.getElementById('submit-btn');

    if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.classList.remove('is-loading');
    }

    if (data.code === 'ROUND_EXPIRED') {
        showSubmitError("Time's up!");
        // Disable further attempts
        hasSubmitted = true;
        if (submitBtn) submitBtn.disabled = true;
    } else if (data.code === 'ALREADY_SUBMITTED') {
        // Already submitted, update UI
        handleSubmitAck(data);
    } else {
        showSubmitError(data.message || 'Submission failed');
    }
}

function showSubmitError(message) {
    const submitBtn = document.getElementById('submit-btn');
    if (submitBtn) {
        submitBtn.textContent = message;
        submitBtn.classList.add('is-error');
        setTimeout(() => {
            submitBtn.textContent = 'Submit Guess';
            submitBtn.classList.remove('is-error');
        }, 2000);
    }
}

function resetSubmissionState() {
    hasSubmitted = false;

    const yearSelector = document.getElementById('year-selector');
    const submitBtn = document.getElementById('submit-btn');
    const confirmation = document.getElementById('submitted-confirmation');
    const slider = document.getElementById('year-slider');

    if (yearSelector) {
        yearSelector.classList.remove('is-submitted');
    }

    if (submitBtn) {
        submitBtn.disabled = false;
        submitBtn.classList.remove('hidden', 'is-loading', 'is-error');
        submitBtn.textContent = 'Submit Guess';
    }

    if (confirmation) {
        confirmation.classList.add('hidden');
    }

    // Reset slider to middle value
    if (slider) {
        slider.value = 1990;
        const yearDisplay = document.getElementById('selected-year');
        if (yearDisplay) yearDisplay.textContent = '1990';
    }
}

// Update handleServerMessage
function handleServerMessage(data) {
    if (data.type === 'state') {
        switch (data.phase) {
            case 'PLAYING':
                resetSubmissionState();  // Reset for new round
                showView('game-view');
                updateGameView(data);
                startCountdown(data.deadline);
                initYearSelector();
                break;
            // ... other cases
        }
    } else if (data.type === 'submit_ack') {
        handleSubmitAck(data);
    } else if (data.type === 'error') {
        if (['ROUND_EXPIRED', 'ALREADY_SUBMITTED'].includes(data.code)) {
            handleSubmitError(data);
        }
        // ... other error handling
    }
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    initYearSelector();
});
```

### Backend - WebSocket Submit Handler

```python
# server/websocket.py - Add submit handling

async def _handle_message(
    self, ws: web.WebSocketResponse, data: dict
) -> None:
    """Handle incoming WebSocket message."""
    msg_type = data.get("type")

    if msg_type == "submit":
        await self._handle_submit(ws, data)
    # ... other message types

async def _handle_submit(
    self, ws: web.WebSocketResponse, data: dict
) -> None:
    """Handle guess submission."""
    game = self._game_state

    # Get player by WebSocket
    player = game.get_player_by_ws(ws)
    if not player:
        await self._send_error(ws, ERR_NOT_IN_GAME, "Not in game")
        return

    # Check phase
    if game.phase != GamePhase.PLAYING:
        await self._send_error(ws, ERR_INVALID_ACTION, "Not in playing phase")
        return

    # Check if already submitted
    if player.submitted:
        await self._send_error(ws, ERR_ALREADY_SUBMITTED, "Already submitted")
        return

    # Check deadline
    now_ms = int(time.time() * 1000)
    if game.deadline and now_ms > game.deadline:
        await self._send_error(ws, ERR_ROUND_EXPIRED, "Time's up!")
        return

    # Validate year
    year = data.get("year")
    if not isinstance(year, int) or year < 1950 or year > 2025:
        await self._send_error(ws, ERR_INVALID_ACTION, "Invalid year")
        return

    # Record submission
    submission_time = time.time()
    player.submit_guess(year, submission_time)

    # Send acknowledgment
    await ws.send_json({
        "type": "submit_ack",
        "year": year
    })

    # Broadcast updated state (player.submitted now True)
    await self._broadcast_state()

    _LOGGER.info(
        "Player %s submitted guess: %d at %.2f",
        player.name, year, submission_time
    )
```

### PlayerSession Submission Fields

```python
# game/player.py - Update PlayerSession

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

    # Submission tracking
    submitted: bool = False
    current_guess: int | None = None
    submission_time: float | None = None

    def submit_guess(self, year: int, timestamp: float) -> None:
        """Record a guess submission."""
        self.submitted = True
        self.current_guess = year
        self.submission_time = timestamp

    def reset_submission(self) -> None:
        """Reset submission state for new round."""
        self.submitted = False
        self.current_guess = None
        self.submission_time = None
```

### const.py Additions

```python
# Add to const.py

ERR_ROUND_EXPIRED = "ROUND_EXPIRED"
ERR_ALREADY_SUBMITTED = "ALREADY_SUBMITTED"
ERR_NOT_IN_GAME = "NOT_IN_GAME"
```

### Architecture Compliance

- **WebSocket Messages:** snake_case fields per architecture.md
- **Year Range:** 1950-2025 covers most popular music
- **Touch Targets:** 44x44px minimum per NFR18
- **60fps:** Using requestAnimationFrame for slider updates per NFR3
- **Error Codes:** UPPER_SNAKE_CASE per architecture.md

### Anti-Patterns to Avoid

- Do NOT allow submission after deadline - strict server-side validation
- Do NOT allow resubmission - one guess per round
- Do NOT use snake_case in JavaScript - use camelCase
- Do NOT block UI during submission - show loading state
- Do NOT trust client timestamp - server records submission time

### Previous Story Learnings

- WebSocket message handling pattern established in player.js
- Error handling with user-friendly messages
- State reset pattern for new rounds
- Loading states improve UX

### Dependencies on Other Stories

- **Story 4.1:** Provides `deadline` for expiry check
- **Story 4.2:** Provides game-view structure with selector container
- **Story 4.4:** Will show who has submitted
- **Story 4.6:** Will calculate score from submission

### References

- [Source: epics.md#Story-4.3] - FR25, FR26, FR27
- [Source: architecture.md#WebSocket-Architecture] - Submit message schema
- [Source: project-context.md#WebSocket] - Message format
- [Source: project-context.md#Frontend-Rules] - Touch targets, 60fps

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

### File List
