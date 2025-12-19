# Story 2.4: QR Code Generation & Display

Status: done

## Story

As a **host**,
I want **to display and print a QR code that guests can scan to join**,
so that **joining the game is frictionless for my guests**.

## Acceptance Criteria

1. **AC1:** Given game lobby is created, When lobby view displays, Then a QR code is generated containing the player join URL (FR11) And the QR code is large enough to scan from across a room (minimum 256px, scales up on larger screens)

2. **AC2:** Given QR code is displayed, When host clicks "Print QR Code", Then a print-friendly view renders with: Large QR code centered, Join URL displayed as text below, "Scan to Play Beatify!" instruction, Minimal styling for clean printing (FR10)

3. **AC3:** Given host views QR code on mobile device, When page renders, Then QR code scales appropriately for the viewport And remains scannable (minimum 200px on mobile)

4. **AC4:** Given game session ends or doesn't exist, When QR code is scanned (player visits join URL), Then player sees message "This game has ended" or "Game not found" rather than error And player sees option to refresh or scan a new QR code

## Tasks / Subtasks

- [x] **Task 1: Enhance QR code generation with size options** (AC: #1, #3)
  - [x] 1.1 Verify qrcode.js library is loaded in admin.html from `www/js/vendor/qrcode.min.js` (Story 2.3 dependency)
  - [x] 1.2 Update QR code generation in `admin.js` `showLobbyView()` to use configurable size
  - [x] 1.3 Set default QR size to 300px for desktop, detect viewport and adjust
  - [x] 1.4 Add error correction level "M" for better scannability
  - [x] 1.5 Ensure QR code has white background padding for scanning margin
  - [x] 1.6 Add `aria-label` for accessibility: "QR code to join Beatify game"
  - [x] 1.7 Add QR code caching to avoid regeneration when returning to lobby view

- [x] **Task 2: Implement print QR functionality (Option A - same page)** (AC: #2)
  - [x] 2.1 Wire "Print QR Code" button (`#print-qr`) click handler in `admin.js`
  - [x] 2.2 Add `printQRCode()` function that triggers `window.print()`
  - [x] 2.3 Add print-specific CSS with `@media print` rules in `styles.css`
  - [x] 2.4 Hide navigation, buttons, and non-essential elements in print view using `.no-print` class
  - [x] 2.5 Wrap QR container and instruction in `.qr-print-area` for print visibility
  - [x] 2.6 Ensure print preview shows clean, centered QR code (400px) with URL below

- [x] **Task 3: Add responsive QR code sizing** (AC: #1, #3)
  - [x] 3.1 Add CSS media queries for QR container sizing
  - [x] 3.2 Desktop (>768px): 350px QR code
  - [x] 3.3 Tablet (481-768px): 280px QR code
  - [x] 3.4 Mobile (<480px): 250px QR code, full width container
  - [x] 3.5 Ensure QR code container has `max-width: 100%` for overflow prevention

- [x] **Task 4: Create player.html page** (AC: #4)
  - [x] 4.1 Create `player.html` in `www/` directory
  - [x] 4.2 Add basic structure: header, main content area with views
  - [x] 4.3 Add loading state view (`#loading-view`) with spinner
  - [x] 4.4 Add error view (`#not-found-view`) for game not found
  - [x] 4.5 Add error view (`#ended-view`) for game ended
  - [x] 4.6 Add join view (`#join-view`) placeholder for Epic 3
  - [x] 4.7 Meta viewport tag already included in template (verify present)

- [x] **Task 5: Create player.js with game validation** (AC: #4)
  - [x] 5.1 Create `player.js` in `www/js/` directory
  - [x] 5.2 On page load, extract `game` param from URL using `URLSearchParams`
  - [x] 5.3 Validate game ID format (alphanumeric, dashes, underscores, 8-16 chars) before API call
  - [x] 5.4 Call `GET /beatify/api/game-status?game=<id>` to validate game
  - [x] 5.5 Handle response: `exists: false` → show "Game not found"
  - [x] 5.6 Handle response: `phase: "END"` → show "Game has ended"
  - [x] 5.7 Handle response: `can_join: true` → show join view (placeholder for Epic 3)
  - [x] 5.8 Handle response: `can_join: false` (REVEAL/PAUSED) → show "Game in progress, try again"
  - [x] 5.9 Add "Refresh" button handler to re-check game status

- [x] **Task 6: Create game-status API endpoint** (AC: #4)
  - [x] 6.1 Add `GET /beatify/api/game-status` endpoint to `views.py`
  - [x] 6.2 Accept query param `game` (game ID)
  - [x] 6.3 Return 200 with JSON response (never 404 for invalid game)
  - [x] 6.4 Response format: `{ "exists": bool, "phase": str|null, "can_join": bool }`
  - [x] 6.5 `can_join` logic: true if `phase in ("LOBBY", "PLAYING")`, false otherwise
  - [x] 6.6 Handle null game_state safely (check before accessing properties)

- [x] **Task 7: Register player page view** (AC: #4)
  - [x] 7.1 Add `BeatifyPlayerView` class to `views.py`
  - [x] 7.2 Serve `player.html` at `/beatify/play`
  - [x] 7.3 No authentication required (`requires_auth = False`)
  - [x] 7.4 Register view in `__init__.py` during `async_setup_entry`

- [x] **Task 8: Add CSS for player page** (AC: #4)
  - [x] 8.1 Add `.player-container` styles (centered, max-width)
  - [x] 8.2 Add `.view` and `.view.hidden` for view switching
  - [x] 8.3 Add `.error-icon` large emoji styling
  - [x] 8.4 Add `.hint` subtle text styling
  - [x] 8.5 Add `.spinner` loading animation
  - [x] 8.6 Add error state styling (`.error-view h1`, `.error-view p`)

- [x] **Task 9: E2E tests for QR code and print** (AC: #1, #2, #3)
  - [x] 9.1 Create `tests/e2e/test_qr_and_player_flow.py` (combined test file)
  - [x] 9.2 Test QR code is displayed in lobby view
  - [x] 9.3 Test QR code contains correct join URL
  - [x] 9.4 Test print button exists and is clickable
  - [x] 9.5 Test QR code is visible at different viewport sizes
  - [x] 9.6 Test player page with invalid game ID shows "Game not found"
  - [x] 9.7 Test player page with ended game shows "Game has ended"
  - [x] 9.8 Test player page with valid game shows join view
  - [x] 9.9 Test refresh button re-validates game status

- [x] **Task 10: Verify all existing tests pass**
  - [x] 10.1 Run `pytest tests/` and verify no regressions
  - [x] 10.2 Run `ruff check` and fix any linting issues

## Dev Notes

### Story Dependencies

**CRITICAL: Story 2.3 must be completed first.** This story depends on:
- Lobby view existing in admin.html (`#lobby-section`)
- QR code container (`#qr-code`) existing
- Join URL display (`#join-url`) existing
- qrcode.js library downloaded to `www/js/vendor/qrcode.min.js`
- `showLobbyView(gameData)` function in admin.js
- GameState class with `get_state()` method

If any are missing, add them as part of Task 1.

### Architecture Compliance

- **URLs:** Player page at `/beatify/play` per architecture.md URL structure
- **No Auth:** Player page requires no authentication (frictionless access)
- **Static Files:** All HTML/CSS/JS served from `www/` directory
- **QR Library:** Local file at `www/js/vendor/qrcode.min.js` (no CDN)

### QR Code Best Practices

```javascript
// QR code configuration for optimal scanning
new QRCode(container, {
  text: joinUrl,
  width: 300,       // Desktop default
  height: 300,
  colorDark: "#000000",
  colorLight: "#ffffff",
  correctLevel: QRCode.CorrectLevel.M  // Medium error correction
});
```

**Size Guidelines:**
- Minimum 200px for close-range scanning (mobile)
- 300-400px for across-room scanning (TV/poster)
- Always maintain 1:1 aspect ratio
- Include white "quiet zone" padding (built into library)

### Do NOT (Anti-Patterns)

- ❌ Use SVG QR codes for print (PNG/canvas renders more reliably)
- ❌ Compress or resize QR after generation (loses quality)
- ❌ Add decorations/logos inside QR code (reduces scannability)
- ❌ Use colored QR codes (black on white is most scannable)
- ❌ Return 404 for invalid game ID (use 200 with `exists: false`)
- ❌ Create separate `print-qr.html` page (use same-page print with CSS)
- ❌ Access `game_state.game_id` without null-checking `game_state` first

### Existing Code to Extend

**From Story 2.3 (`admin.js`):**

| Element | Purpose |
|---------|---------|
| `showLobbyView(gameData)` | Extend with enhanced QR display |
| `#qr-code` container | Already exists, enhance styling |
| `#print-qr` button | Already stubbed, implement handler |

**From Story 2.3 (`admin.html`):**

| Section | Purpose |
|---------|---------|
| `#lobby-section` | Contains QR display |
| `.qr-container` | Enhance with responsive sizing |

**From Story 2.3 (`views.py`):**

| View | Purpose |
|------|---------|
| `BeatifyStartGameView` | Reference for view pattern |
| `BeatifyStatusView` | Already includes `active_game` (verify) |

### Implementation Reference

**BeatifyPlayerView class:**

```python
# views.py - add to existing file
from pathlib import Path

class BeatifyPlayerView(HomeAssistantView):
    """Serve the player page."""

    url = "/beatify/play"
    name = "beatify:play"
    requires_auth = False  # Frictionless access per PRD

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the player view."""
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:
        """Serve the player HTML page."""
        html_path = Path(__file__).parent.parent / "www" / "player.html"

        if not html_path.exists():
            _LOGGER.error("Player page not found: %s", html_path)
            return web.Response(text="Player page not found", status=500)

        html_content = html_path.read_text(encoding="utf-8")
        return web.Response(text=html_content, content_type="text/html")
```

**BeatifyGameStatusView class (with proper null handling):**

```python
# views.py - add to existing file

class BeatifyGameStatusView(HomeAssistantView):
    """Check game status for player page."""

    url = "/beatify/api/game-status"
    name = "beatify:api:game-status"
    requires_auth = False

    def __init__(self, hass: HomeAssistant):
        """Initialize view."""
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:
        """Get game status."""
        game_id = request.query.get("game")

        # No game ID provided
        if not game_id:
            return web.json_response({
                "exists": False,
                "phase": None,
                "can_join": False
            })

        # Get game state with safe access
        game_state = self.hass.data.get(DOMAIN, {}).get("game")

        # No game state or different game ID
        if not game_state:
            return web.json_response({
                "exists": False,
                "phase": None,
                "can_join": False
            })

        if game_state.game_id != game_id:
            return web.json_response({
                "exists": False,
                "phase": None,
                "can_join": False
            })

        # Game exists - return status
        phase = game_state.phase.value
        can_join = phase in ("LOBBY", "PLAYING")  # Late join supported

        return web.json_response({
            "exists": True,
            "phase": phase,
            "can_join": can_join
        })
```

**Print QR implementation:**

```javascript
// admin.js - add to existing file

// QR code caching
let cachedQRUrl = null;

function printQRCode() {
  window.print();
}

// Enhanced showLobbyView with caching
function showLobbyView(gameData) {
  currentGame = gameData;
  showView('lobby');

  const qrContainer = document.getElementById('qr-code');
  if (qrContainer) {
    // Only regenerate if URL changed
    if (cachedQRUrl !== gameData.join_url) {
      qrContainer.innerHTML = '';
      qrContainer.setAttribute('aria-label', 'QR code to join Beatify game');

      new QRCode(qrContainer, {
        text: gameData.join_url,
        width: 300,
        height: 300,
        colorDark: "#000000",
        colorLight: "#ffffff",
        correctLevel: QRCode.CorrectLevel.M
      });

      cachedQRUrl = gameData.join_url;
    }
  }

  const urlEl = document.getElementById('join-url');
  if (urlEl) {
    urlEl.textContent = gameData.join_url;
  }
}

// Wire print button
document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('print-qr')?.addEventListener('click', printQRCode);
});
```

**player.js with game ID validation:**

```javascript
// player.js
(function() {
  'use strict';

  // Get game ID from URL
  const urlParams = new URLSearchParams(window.location.search);
  const gameId = urlParams.get('game');

  // View elements
  const loadingView = document.getElementById('loading-view');
  const notFoundView = document.getElementById('not-found-view');
  const endedView = document.getElementById('ended-view');
  const joinView = document.getElementById('join-view');

  function showView(viewId) {
    [loadingView, notFoundView, endedView, joinView].forEach(v => {
      v?.classList.add('hidden');
    });
    document.getElementById(viewId)?.classList.remove('hidden');
  }

  async function checkGameStatus() {
    // Validate game ID exists
    if (!gameId) {
      showView('not-found-view');
      return;
    }

    // Validate game ID format (alphanumeric, dashes, underscores, 8-16 chars)
    if (!/^[a-zA-Z0-9_-]{8,16}$/.test(gameId)) {
      showView('not-found-view');
      return;
    }

    try {
      const response = await fetch(`/beatify/api/game-status?game=${encodeURIComponent(gameId)}`);
      const data = await response.json();

      if (!data.exists) {
        showView('not-found-view');
        return;
      }

      if (data.phase === 'END') {
        showView('ended-view');
        return;
      }

      if (data.can_join) {
        showView('join-view');
        // Full WebSocket connection in Epic 3
      } else {
        // REVEAL or PAUSED - can't join right now
        showView('not-found-view');
      }

    } catch (err) {
      console.error('Failed to check game status:', err);
      showView('not-found-view');
    }
  }

  // Initialize
  checkGameStatus();

  // Refresh button
  document.getElementById('refresh-btn')?.addEventListener('click', () => {
    showView('loading-view');
    checkGameStatus();
  });

})();
```

**player.html structure:**

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Beatify - Join Game</title>
    <link rel="stylesheet" href="/beatify/static/css/styles.css">
</head>
<body>
    <main class="player-container">
        <!-- Loading state -->
        <div id="loading-view" class="view">
            <div class="spinner"></div>
            <p>Connecting to game...</p>
        </div>

        <!-- Error: Game not found -->
        <div id="not-found-view" class="view hidden">
            <div class="error-icon">🎵</div>
            <h1>Game Not Found</h1>
            <p>This game doesn't exist or the link is incorrect.</p>
            <p class="hint">Scan a new QR code from the host's screen.</p>
            <button id="refresh-btn" class="btn btn-primary">Try Again</button>
        </div>

        <!-- Error: Game ended -->
        <div id="ended-view" class="view hidden">
            <div class="error-icon">🎉</div>
            <h1>Game Has Ended</h1>
            <p>Thanks for playing Beatify!</p>
            <p class="hint">Ask the host to start a new game.</p>
        </div>

        <!-- Join form (stub for Epic 3) -->
        <div id="join-view" class="view hidden">
            <h1>Join Beatify</h1>
            <p>Enter your name to join the game</p>
            <!-- Full implementation in Story 3.2 -->
            <p class="coming-soon">Name entry coming in next update...</p>
        </div>
    </main>

    <script src="/beatify/static/js/player.js"></script>
</body>
</html>
```

### CSS Additions

**Print styles (add to styles.css):**

```css
/* Print styles for QR code */
@media print {
  body * {
    visibility: hidden;
  }

  .qr-print-area,
  .qr-print-area * {
    visibility: visible;
  }

  .qr-print-area {
    position: absolute;
    left: 50%;
    top: 50%;
    transform: translate(-50%, -50%);
    text-align: center;
  }

  #qr-code {
    width: 400px !important;
    height: 400px !important;
  }

  .qr-instruction {
    font-size: 24px;
    font-weight: bold;
    margin-top: 20px;
  }

  .join-url {
    font-size: 14px;
    font-family: monospace;
    margin-top: 10px;
  }

  .no-print {
    display: none !important;
  }
}
```

**Responsive QR sizing:**

```css
/* QR code responsive sizing */
#qr-code {
  padding: 16px;
  background: white;
  border-radius: 8px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

@media (min-width: 769px) {
  #qr-code { width: 350px; height: 350px; }
}

@media (min-width: 481px) and (max-width: 768px) {
  #qr-code { width: 280px; height: 280px; }
}

@media (max-width: 480px) {
  .qr-container { padding: 16px; }
  #qr-code { width: 250px; height: 250px; }
}
```

**Player page styles:**

```css
/* Player page styles */
.player-container {
  max-width: 500px;
  margin: 0 auto;
  padding: 24px;
  text-align: center;
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.view {
  display: block;
}

.view.hidden {
  display: none;
}

.error-icon {
  font-size: 64px;
  margin-bottom: 16px;
}

.player-container h1 {
  margin-bottom: 12px;
  color: #1f2937;
}

.player-container p {
  color: #6b7280;
  margin-bottom: 8px;
}

.hint {
  font-size: 14px;
  color: #9ca3af;
}

.coming-soon {
  font-style: italic;
  color: #6b7280;
}

.spinner {
  width: 40px;
  height: 40px;
  margin: 0 auto 16px;
  border: 4px solid #f3f4f6;
  border-top: 4px solid #3b82f6;
  border-radius: 50%;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}
```

### Error Messages

| Context | Message |
|---------|---------|
| No game ID in URL | "Game Not Found" + "This game doesn't exist or the link is incorrect." |
| Invalid game ID format | "Game Not Found" + "This game doesn't exist or the link is incorrect." |
| Game ID not found | "Game Not Found" + "Scan a new QR code from the host's screen." |
| Game ended | "Game Has Ended" + "Thanks for playing Beatify!" |
| Game in REVEAL/PAUSED | "Game Not Found" (can't join mid-reveal) |

### Game Status Response Reference

| Scenario | Response |
|----------|----------|
| No game ID | `{ exists: false, phase: null, can_join: false }` |
| Invalid game ID | `{ exists: false, phase: null, can_join: false }` |
| Game in LOBBY | `{ exists: true, phase: "LOBBY", can_join: true }` |
| Game in PLAYING | `{ exists: true, phase: "PLAYING", can_join: true }` (late join) |
| Game in REVEAL | `{ exists: true, phase: "REVEAL", can_join: false }` |
| Game in PAUSED | `{ exists: true, phase: "PAUSED", can_join: false }` |
| Game in END | `{ exists: true, phase: "END", can_join: false }` |

### Testing Approach

- **E2E tests** (`tests/e2e/test_qr_and_player_flow.py`): Combined tests for QR display, print, and player page
- **Manual testing**: Print preview verification, QR scanning from different distances (3+ meters)

### Previous Story Learnings (2.3)

From Story 2.3:
- QR code container exists in lobby section
- Print button stubbed (`#print-qr`)
- Join URL displayed in `#join-url`
- qrcode.js library in `www/js/vendor/qrcode.min.js`
- Use `addEventListener` for button handlers (CSP compatibility)
- Add null checks for DOM elements

### References

- [Source: epics.md#Story-2.4] - Original acceptance criteria (FR10, FR11)
- [Source: architecture.md#URL-Structure] - `/beatify/play` for player page
- [Source: architecture.md#Frontend-Architecture] - Static files in `www/`
- [Source: project-context.md#Frontend-Rules] - Mobile-first, touch targets
- [Source: 2-3-start-game-and-create-lobby.md] - QR code foundation, view patterns

## Dev Agent Record

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Debug Log References

- Linting passes: All Python files pass ruff check
- QR code functionality extends Story 2.3 implementation

### Completion Notes List

- Created player.html with loading, not-found, ended, in-progress, and join views
- Created player.js with game ID validation and game-status API integration
- Added GameStatusView API endpoint returning exists/phase/can_join
- Added PlayerView to serve player.html at /beatify/play
- Registered new views in __init__.py
- Added responsive QR sizing CSS with media queries
- Added player page CSS styles (spinner, error icons, view switching)
- Created comprehensive E2E tests for QR and player flow
- All tasks from Story 2.3 foundation extended and completed

### File List

- `custom_components/beatify/__init__.py` - Modified (registered PlayerView, GameStatusView)
- `custom_components/beatify/www/player.html` - Created (player page with multiple views)
- `custom_components/beatify/www/js/player.js` - Created (game validation and view switching)
- `custom_components/beatify/www/css/styles.css` - Modified (player page styles, responsive QR, spinner animation)
- `custom_components/beatify/server/views.py` - Modified (added PlayerView, GameStatusView classes)
- `tests/e2e/test_qr_and_player_flow.py` - Created (QR display, print, player page tests)
