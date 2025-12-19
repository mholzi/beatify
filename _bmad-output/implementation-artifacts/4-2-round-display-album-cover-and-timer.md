# Story 4.2: Round Display (Album Cover & Timer)

Status: ready-for-dev

## Story

As a **player**,
I want **to see the album cover and a countdown timer**,
so that **I have visual context and know how much time I have to guess**.

## Acceptance Criteria

1. **AC1:** Given round starts, When player view updates, Then album cover image is displayed prominently (FR23) And image is fetched from media_player entity's `entity_picture` attribute And if no artwork available, placeholder image (`no-artwork.svg`) is shown

2. **AC2:** Given round starts, When player view updates, Then countdown timer displays starting from 30 seconds (FR24) And timer counts down in real-time And timer is large and clearly visible

3. **AC3:** Given timer is running, When time reaches 10 seconds, Then timer changes color (e.g., orange) to indicate urgency

4. **AC4:** Given timer is running, When time reaches 5 seconds, Then timer changes color again (e.g., red) for final warning

5. **AC5:** Given server sends `round_end_timestamp`, When client calculates remaining time, Then countdown is synchronized across all clients within 200ms (NFR2)

## Tasks / Subtasks

**DEPENDENCY:** Requires Story 4.1 (Song Playback) to be complete - provides current_song and deadline in state.

- [ ] **Task 1: Replace game-view placeholder with full UI** (AC: #1, #2)
  - [ ] 1.1 Remove placeholder content from `#game-view` in `player.html`
  - [ ] 1.2 Add album cover image container with `#album-cover` img element
  - [ ] 1.3 Add timer display with `#timer` element
  - [ ] 1.4 Add round indicator `#round-indicator` (Round X of Y)
  - [ ] 1.5 Structure layout: album cover prominent center, timer below

- [ ] **Task 2: Style album cover display** (AC: #1)
  - [ ] 2.1 Add `.album-cover-container` styles - centered, max-width 300px
  - [ ] 2.2 Add `#album-cover` styles - rounded corners, shadow, responsive
  - [ ] 2.3 Add loading state while image loads
  - [ ] 2.4 Ensure no-artwork.svg fallback displays correctly

- [ ] **Task 3: Style timer display** (AC: #2, #3, #4)
  - [ ] 3.1 Add `#timer` base styles - large font (48px+), centered
  - [ ] 3.2 Add `.timer--warning` class (orange) for < 10 seconds
  - [ ] 3.3 Add `.timer--critical` class (red) for < 5 seconds
  - [ ] 3.4 Add pulse animation for critical state

- [ ] **Task 4: Implement client-side timer countdown** (AC: #2, #5)
  - [ ] 4.1 In `player.js`, add `startCountdown(deadline)` function
  - [ ] 4.2 Calculate remaining time from `deadline - Date.now()`
  - [ ] 4.3 Use `requestAnimationFrame` for smooth updates
  - [ ] 4.4 Update `#timer` element with seconds remaining
  - [ ] 4.5 Stop countdown when reaching 0

- [ ] **Task 5: Implement timer color transitions** (AC: #3, #4)
  - [ ] 5.1 In countdown loop, check remaining seconds
  - [ ] 5.2 Add `.timer--warning` class when < 10 seconds
  - [ ] 5.3 Add `.timer--critical` class when < 5 seconds
  - [ ] 5.4 Remove classes when new round starts

- [ ] **Task 6: Handle PLAYING phase in handleServerMessage** (AC: #1, #2)
  - [ ] 6.1 When `data.phase === 'PLAYING'`, update game view
  - [ ] 6.2 Set album cover src from `data.song.album_art`
  - [ ] 6.3 Set round indicator from `data.round` and `data.total_rounds`
  - [ ] 6.4 Start countdown from `data.deadline`
  - [ ] 6.5 Show game-view, hide other views

- [ ] **Task 7: Handle album cover image loading** (AC: #1)
  - [ ] 7.1 Add `onerror` handler to fall back to no-artwork.svg
  - [ ] 7.2 Add loading state while image loads
  - [ ] 7.3 Handle missing/null album_art gracefully

- [ ] **Task 8: Ensure timer synchronization** (AC: #5)
  - [ ] 8.1 Use server `deadline` timestamp, not client start time
  - [ ] 8.2 Handle clock skew by trusting server deadline
  - [ ] 8.3 Log any significant discrepancies for debugging

- [ ] **Task 9: Add round indicator styles** (AC: #1, #2)
  - [ ] 9.1 Add `#round-indicator` styles - smaller font, muted color
  - [ ] 9.2 Position above album cover
  - [ ] 9.3 Show "Final Round!" when `data.last_round` is true

- [ ] **Task 10: Mobile responsiveness** (AC: #1, #2)
  - [ ] 10.1 Ensure album cover scales on small screens
  - [ ] 10.2 Ensure timer is readable on all screen sizes
  - [ ] 10.3 Test touch interactions don't interfere with display

- [ ] **Task 11: Unit tests for countdown logic**
  - [ ] 11.1 Test: countdown calculates correct remaining time
  - [ ] 11.2 Test: warning class added at 10 seconds
  - [ ] 11.3 Test: critical class added at 5 seconds
  - [ ] 11.4 Test: countdown stops at 0

- [ ] **Task 12: E2E tests for game view**
  - [ ] 12.1 Test: album cover displays when phase is PLAYING
  - [ ] 12.2 Test: timer displays countdown
  - [ ] 12.3 Test: fallback image shown when no artwork

- [ ] **Task 13: Verify no regressions**
  - [ ] 13.1 Run `pytest tests/` - all pass
  - [ ] 13.2 Run `ruff check` - no new issues
  - [ ] 13.3 Test lobby still works correctly

## Dev Notes

### Files to Modify

| File | Action |
|------|--------|
| `www/player.html` | Replace game-view placeholder with full UI |
| `www/js/player.js` | Add countdown logic, handle PLAYING phase |
| `www/css/styles.css` | Add album cover, timer, round indicator styles |

### HTML Structure for Game View

```html
<!-- Replace #game-view content in player.html -->
<div id="game-view" class="view hidden">
    <div class="game-container">
        <!-- Round Indicator -->
        <div id="round-indicator" class="round-indicator">
            Round <span id="current-round">1</span> of <span id="total-rounds">10</span>
        </div>
        <div id="last-round-banner" class="last-round-banner hidden">
            Final Round!
        </div>

        <!-- Album Cover -->
        <div class="album-cover-container">
            <img id="album-cover"
                 src="/beatify/static/img/no-artwork.svg"
                 alt="Album Cover"
                 class="album-cover">
            <div id="album-loading" class="album-loading hidden">
                <div class="loading-spinner"></div>
            </div>
        </div>

        <!-- Timer -->
        <div class="timer-container">
            <div id="timer" class="timer">30</div>
        </div>

        <!-- Year Selector placeholder (Story 4.3) -->
        <div id="year-selector-container" class="year-selector-container">
            <!-- Implemented in Story 4.3 -->
        </div>
    </div>
</div>
```

### CSS Styles

```css
/* Game View Container */
.game-container {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 24px;
    max-width: 400px;
    margin: 0 auto;
}

/* Round Indicator */
.round-indicator {
    font-size: 14px;
    color: #6b7280;
    margin-bottom: 8px;
}

.last-round-banner {
    background: linear-gradient(135deg, #f59e0b, #d97706);
    color: white;
    padding: 8px 16px;
    border-radius: 20px;
    font-size: 14px;
    font-weight: 600;
    margin-bottom: 16px;
    animation: pulse 2s infinite;
}

/* Album Cover */
.album-cover-container {
    position: relative;
    width: 100%;
    max-width: 300px;
    margin-bottom: 24px;
}

.album-cover {
    width: 100%;
    aspect-ratio: 1;
    object-fit: cover;
    border-radius: 16px;
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.15);
}

.album-loading {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    background: #f3f4f6;
    border-radius: 16px;
}

.loading-spinner {
    width: 40px;
    height: 40px;
    border: 4px solid #e5e7eb;
    border-top-color: #6366f1;
    border-radius: 50%;
    animation: spin 1s linear infinite;
}

@keyframes spin {
    to { transform: rotate(360deg); }
}

/* Timer */
.timer-container {
    margin-bottom: 24px;
}

.timer {
    font-size: 64px;
    font-weight: 700;
    color: #1f2937;
    font-variant-numeric: tabular-nums;
    transition: color 0.3s ease;
}

.timer--warning {
    color: #f59e0b;
}

.timer--critical {
    color: #ef4444;
    animation: pulse 0.5s infinite;
}

@keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.7; }
}

/* Year Selector Container (placeholder for 4.3) */
.year-selector-container {
    width: 100%;
    margin-top: 16px;
}

/* Responsive adjustments */
@media (max-width: 360px) {
    .album-cover-container {
        max-width: 250px;
    }

    .timer {
        font-size: 48px;
    }
}

@media (min-width: 768px) {
    .album-cover-container {
        max-width: 350px;
    }

    .timer {
        font-size: 72px;
    }
}
```

### JavaScript Countdown Implementation

```javascript
// player.js - Add to IIFE

let countdownInterval = null;

function startCountdown(deadline) {
    // Clear any existing countdown
    if (countdownInterval) {
        cancelAnimationFrame(countdownInterval);
    }

    const timerElement = document.getElementById('timer');
    if (!timerElement) return;

    // Remove previous state classes
    timerElement.classList.remove('timer--warning', 'timer--critical');

    function updateCountdown() {
        const now = Date.now();
        const remaining = Math.max(0, Math.ceil((deadline - now) / 1000));

        timerElement.textContent = remaining;

        // Update timer color based on remaining time
        if (remaining <= 5) {
            timerElement.classList.remove('timer--warning');
            timerElement.classList.add('timer--critical');
        } else if (remaining <= 10) {
            timerElement.classList.remove('timer--critical');
            timerElement.classList.add('timer--warning');
        } else {
            timerElement.classList.remove('timer--warning', 'timer--critical');
        }

        // Continue countdown if time remains
        if (remaining > 0) {
            countdownInterval = requestAnimationFrame(updateCountdown);
        }
    }

    // Start the countdown
    countdownInterval = requestAnimationFrame(updateCountdown);
}

function stopCountdown() {
    if (countdownInterval) {
        cancelAnimationFrame(countdownInterval);
        countdownInterval = null;
    }
}

// Update handleServerMessage for PLAYING phase
function handleServerMessage(data) {
    // ... existing code ...

    if (data.type === 'state') {
        switch (data.phase) {
            case 'LOBBY':
                stopCountdown();
                showView('lobby-view');
                renderPlayerList(data.players || []);
                renderQRCode(data.join_url);
                updateAdminControls(data.players || []);
                break;

            case 'PLAYING':
                showView('game-view');
                updateGameView(data);
                startCountdown(data.deadline);
                break;

            case 'REVEAL':
                stopCountdown();
                showView('reveal-view');
                // Full reveal UI in Story 4.6
                break;

            case 'END':
                stopCountdown();
                showView('end-view');
                break;
        }
    }
    // ... rest of existing code ...
}

function updateGameView(data) {
    // Update round indicator
    const currentRound = document.getElementById('current-round');
    const totalRounds = document.getElementById('total-rounds');
    const lastRoundBanner = document.getElementById('last-round-banner');

    if (currentRound) currentRound.textContent = data.round || 1;
    if (totalRounds) totalRounds.textContent = data.total_rounds || 10;

    // Show/hide last round banner
    if (lastRoundBanner) {
        if (data.last_round) {
            lastRoundBanner.classList.remove('hidden');
        } else {
            lastRoundBanner.classList.add('hidden');
        }
    }

    // Update album cover
    const albumCover = document.getElementById('album-cover');
    const albumLoading = document.getElementById('album-loading');

    if (albumCover && data.song) {
        // Show loading state
        if (albumLoading) albumLoading.classList.remove('hidden');

        const newSrc = data.song.album_art || '/beatify/static/img/no-artwork.svg';

        // Handle image load
        albumCover.onload = function() {
            if (albumLoading) albumLoading.classList.add('hidden');
        };

        // Handle image error - fallback to placeholder
        albumCover.onerror = function() {
            albumCover.src = '/beatify/static/img/no-artwork.svg';
            if (albumLoading) albumLoading.classList.add('hidden');
        };

        albumCover.src = newSrc;
    }
}
```

### Architecture Compliance

- **Timer Synchronization:** Hybrid approach - server sends deadline, client counts down
- **Album Art:** Fetched from media_player entity's `entity_picture` attribute
- **Fallback:** `no-artwork.svg` placeholder per architecture.md
- **Mobile-first:** Min 44x44px touch targets, responsive scaling
- **Performance:** 60fps timer using requestAnimationFrame (NFR3)

### Anti-Patterns to Avoid

- Do NOT use setInterval for timer - use requestAnimationFrame
- Do NOT trust client clock for timer start - use server deadline
- Do NOT leave img src empty - always use placeholder
- Do NOT hardcode 30 seconds - use deadline from server
- Do NOT block main thread during countdown

### Previous Story Learnings

- `showView()` function handles view transitions - reuse it
- State broadcast includes `song` object with album_art
- Phase handling switch statement established in 3.6
- Loading states improve perceived performance

### Dependencies on Other Stories

- **Story 4.1:** Provides `deadline`, `round`, `total_rounds`, `song` in state
- **Story 4.3:** Year selector UI will be added inside `#year-selector-container`
- **Story 4.5:** Will handle timer expiry logic

### References

- [Source: epics.md#Story-4.2] - FR23, FR24
- [Source: architecture.md#Timer-Synchronization] - Hybrid approach
- [Source: architecture.md#Frontend-Architecture] - Static file structure
- [Source: project-context.md#Frontend-Rules] - CSS/JS conventions
- [Source: project-context.md#Anti-Patterns] - No empty img src

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

### File List
