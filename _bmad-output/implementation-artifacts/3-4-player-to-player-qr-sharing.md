# Story 3.4: Player-to-Player QR Sharing

Status: done

## Story

As a **player who has joined**,
I want **to show the QR code on my screen to invite friends**,
so that **joining can spread virally without needing the wall poster**.

## Acceptance Criteria

1. **AC1:** Given player is in the lobby, When lobby view displays, Then a QR code is visible on the player's screen (FR15) And QR code is labeled "Invite friends" or similar And QR code contains the same join URL

2. **AC2:** Given another guest scans the QR from a player's phone, When they open the link, Then they reach the same name entry screen And can join the same game

3. **AC3:** Given player is on a small phone screen (320px), When QR code displays, Then QR code is sized appropriately (not too small to scan, min 150px) And can be tapped to enlarge if needed

## Tasks / Subtasks

**CRITICAL:** Story 3.3 created the lobby structure with QR placeholder area. This story implements the QR code display.

- [x] **Task 1: Include join_url in state broadcast** (AC: #1, #2)
  - [x] 1.1 Verify `get_state()` in `game/state.py` includes `join_url` (should already exist from 2.3)
  - [x] 1.2 Ensure `join_url` is accessible in JavaScript state handling

- [x] **Task 2: Reference existing QR code library** (AC: #1)
  - [x] 2.1 Verify `www/js/qrcode.min.js` exists (created in Story 2.4 for admin page)
  - [x] 2.2 Add script tag to `player.html` (before `player.js`) referencing existing library

- [x] **Task 3: Implement QR code rendering** (AC: #1)
  - [x] 3.1 Add `#player-qr-code` container in QR share area of `player.html`
  - [x] 3.2 Add `renderQRCode(joinUrl)` function inside IIFE in `player.js`
  - [x] 3.3 Call `renderQRCode()` when lobby state is received

- [x] **Task 4: Add tap-to-enlarge modal** (AC: #3)
  - [x] 4.1 Add `#qr-modal` overlay structure to `player.html`
  - [x] 4.2 Add `openQRModal()` and `closeQRModal()` functions in `player.js`
  - [x] 4.3 Render larger QR code in modal (80vw max, min 250px)
  - [x] 4.4 Close on tap outside or close button

- [x] **Task 5: Style QR display for mobile** (AC: #1, #3)
  - [x] 5.1 Add `.qr-share-area` styles with centered QR
  - [x] 5.2 Set QR container min-width: 150px on small screens
  - [x] 5.3 Add "Invite friends" label with icon
  - [x] 5.4 Add tap-to-enlarge hint text

- [x] **Task 6: Style QR modal** (AC: #3)
  - [x] 6.1 Add `.qr-modal` overlay styles (dark backdrop)
  - [x] 6.2 Add `.qr-modal-content` centered container
  - [x] 6.3 Add close button styles (touch-friendly)
  - [x] 6.4 Add animation for open/close

- [x] **Task 7: E2E tests** (AC: #1, #3)
  - [x] 7.1 Add tests to `tests/e2e/test_qr_and_player_flow.py`
  - [x] 7.2 Test: QR code container visible in lobby
  - [x] 7.3 Test: QR code minimum size 150px
  - [x] 7.4 Test: Modal opens on QR tap
  - [x] 7.5 Test: Modal closes on backdrop tap

- [x] **Task 8: Verify no regressions**
  - [x] 8.1 Run `pytest tests/` - all pass
  - [x] 8.2 Run `ruff check` - pre-existing formatting issues only

## Dev Notes

### Existing Files to Modify

| File | Action |
|------|--------|
| `www/player.html` | Add QR container and modal |
| `www/js/player.js` | Add QR rendering and modal functions |
| `www/css/styles.css` | Add QR and modal styles |

### Existing QR Library (Reuse from Story 2.4)

**IMPORTANT:** The QR code library `www/js/qrcode.min.js` already exists from Story 2.4 (admin page QR display). Do NOT create a new file - reuse the existing one.

| File | Status |
|------|--------|
| `www/js/qrcode.min.js` | Already exists - reuse |

The library is `qrcode-generator` (https://github.com/kazuhikoarase/qrcode-generator) - MIT licensed, ~8KB. It's already bundled locally in `www/js/`.

### HTML: QR Share Area

```html
<!-- Inside #lobby-view, replace .qr-share-area content -->
<div id="qr-share-area" class="qr-share-area">
    <p class="qr-label">
        <span class="qr-icon">📲</span>
        Invite friends
    </p>
    <div id="player-qr-code" class="qr-container" role="button" tabindex="0"
         aria-label="Tap to enlarge QR code">
        <!-- QR code rendered here by JS -->
    </div>
    <p class="qr-hint">Tap to enlarge</p>
</div>

<!-- QR Modal (at end of body, before scripts) -->
<div id="qr-modal" class="qr-modal hidden" role="dialog" aria-modal="true"
     aria-labelledby="qr-modal-title">
    <div class="qr-modal-backdrop"></div>
    <div class="qr-modal-content">
        <h2 id="qr-modal-title" class="sr-only">Join Game QR Code</h2>
        <div id="qr-modal-code" class="qr-modal-code">
            <!-- Large QR code rendered here -->
        </div>
        <p class="qr-modal-label">Scan to join the game</p>
        <button id="qr-modal-close" class="btn btn-secondary qr-modal-close"
                aria-label="Close QR code">Close</button>
    </div>
</div>
```

### JavaScript: QR Code Functions

```javascript
// Inside IIFE in player.js

let currentJoinUrl = null;

function renderQRCode(joinUrl) {
    if (!joinUrl) return;
    currentJoinUrl = joinUrl;

    const container = document.getElementById('player-qr-code');
    if (!container) return;

    // Clear previous QR
    container.innerHTML = '';

    // Generate QR code using qrcode-generator
    const qr = qrcode(0, 'M');  // Type 0 = auto, Error correction M
    qr.addData(joinUrl);
    qr.make();

    // Create image (150px for inline display)
    container.innerHTML = qr.createImgTag(4, 0);  // Cell size 4, margin 0

    // Add click handler for modal
    container.onclick = openQRModal;
    container.onkeydown = (e) => {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            openQRModal();
        }
    };
}

function openQRModal() {
    if (!currentJoinUrl) return;

    const modal = document.getElementById('qr-modal');
    const modalCode = document.getElementById('qr-modal-code');
    if (!modal || !modalCode) return;

    // Clear and render larger QR
    modalCode.innerHTML = '';
    const qr = qrcode(0, 'M');
    qr.addData(currentJoinUrl);
    qr.make();
    modalCode.innerHTML = qr.createImgTag(8, 0);  // Larger cell size

    modal.classList.remove('hidden');
    document.body.style.overflow = 'hidden';

    // Focus close button for accessibility
    document.getElementById('qr-modal-close')?.focus();
}

function closeQRModal() {
    const modal = document.getElementById('qr-modal');
    if (modal) {
        modal.classList.add('hidden');
        document.body.style.overflow = '';
    }
}

function setupQRModal() {
    const modal = document.getElementById('qr-modal');
    const backdrop = modal?.querySelector('.qr-modal-backdrop');
    const closeBtn = document.getElementById('qr-modal-close');

    backdrop?.addEventListener('click', closeQRModal);
    closeBtn?.addEventListener('click', closeQRModal);

    // Close on Escape key
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape' && !modal?.classList.contains('hidden')) {
            closeQRModal();
        }
    });
}

// Initialize modal handlers
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', setupQRModal);
} else {
    setupQRModal();
}

// Update handleServerMessage to render QR
function handleServerMessage(data) {
    // ... existing code ...

    if (data.type === 'state') {
        if (data.phase === 'LOBBY') {
            showView('lobby-view');
            renderPlayerList(data.players || []);

            // Render QR code with join URL
            if (data.join_url) {
                renderQRCode(data.join_url);
            }
        }
    }
    // ... rest of existing code ...
}
```

### CSS: QR Styles

```css
/* QR Share Area */
.qr-share-area {
    text-align: center;
    padding: 24px 16px;
    background: #f9fafb;
    border-radius: 12px;
    margin-bottom: 16px;
}

.qr-label {
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 8px;
    font-size: 16px;
    font-weight: 500;
    color: #1f2937;
    margin-bottom: 16px;
}

.qr-icon {
    font-size: 20px;
}

.qr-container {
    display: inline-block;
    padding: 12px;
    background: white;
    border-radius: 8px;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
    cursor: pointer;
    min-width: 150px;
    min-height: 150px;
    transition: transform 0.2s ease;
}

.qr-container:hover,
.qr-container:focus {
    transform: scale(1.02);
    outline: 2px solid #3b82f6;
    outline-offset: 2px;
}

.qr-container img {
    display: block;
    width: 100%;
    height: auto;
}

.qr-hint {
    margin-top: 12px;
    font-size: 13px;
    color: #6b7280;
}

/* QR Modal */
.qr-modal {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 1000;
    display: flex;
    align-items: center;
    justify-content: center;
}

.qr-modal.hidden {
    display: none;
}

.qr-modal-backdrop {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    background: rgba(0, 0, 0, 0.75);
}

.qr-modal-content {
    position: relative;
    background: white;
    padding: 32px 24px;
    border-radius: 16px;
    text-align: center;
    max-width: 90vw;
    max-height: 90vh;
    animation: modalFadeIn 0.2s ease-out;
}

@keyframes modalFadeIn {
    from {
        opacity: 0;
        transform: scale(0.95);
    }
    to {
        opacity: 1;
        transform: scale(1);
    }
}

.qr-modal-code {
    display: inline-block;
    padding: 16px;
    background: white;
    border-radius: 8px;
    min-width: 250px;
}

.qr-modal-code img {
    display: block;
    width: 100%;
    max-width: 80vw;
    height: auto;
}

.qr-modal-label {
    margin: 16px 0;
    font-size: 18px;
    color: #1f2937;
}

.qr-modal-close {
    min-width: 120px;
    min-height: 48px;
}

/* Screen reader only */
.sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0, 0, 0, 0);
    border: 0;
}
```

### Architecture Compliance

- **Vanilla JS only** - No frameworks
- **Local files only** - QR library bundled, no CDN
- **Touch targets** - 150px minimum QR, 48px close button
- **Accessibility** - ARIA labels, keyboard navigation, focus management
- **Mobile-first** - 320px viewport tested

### Anti-Patterns to Avoid

- Do NOT load QR library from CDN - bundle locally
- Do NOT implement admin-only QR visibility - all players can share
- Do NOT block scrolling permanently - restore on modal close
- Do NOT forget to handle keyboard events (Enter/Space/Escape)

### Previous Story Learnings (3.3)

- `join_url` available in state broadcast
- Lobby view structure established with placeholder for QR
- CSS animations work well for subtle interactions
- Touch-friendly sizing critical for mobile

### References

- [Source: epics.md#Story-3.4] - FR15
- [Source: architecture.md#Frontend-Architecture] - Vanilla JS, static files
- [Source: project-context.md#Frontend-Rules] - Touch targets 44x44px
- [Source: 2-4-qr-code-generation-and-display.md] - QR library pattern (admin page)

## Dev Agent Record

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Completion Notes List

- Verified `join_url` already included in `get_state()` from Story 2.3
- Added QR code library script tag to player.html (reused existing qrcode.min.js)
- Added QR share area with `#player-qr-code` container
- Implemented `renderQRCode()` function using qrcode-generator library
- Added tap-to-enlarge modal with accessibility support (ARIA, keyboard navigation)
- Added `openQRModal()`, `closeQRModal()`, `setupQRModal()` functions
- Added comprehensive QR and modal CSS styles with animations
- QR minimum size 150px, modal uses 80vw max with min 250px
- Close on backdrop click, close button, or Escape key

### File List

- `custom_components/beatify/www/player.html` - Added QR share area, QR modal structure
- `custom_components/beatify/www/js/player.js` - Added `renderQRCode()`, modal functions, `setupQRModal()`
- `custom_components/beatify/www/css/styles.css` - Added QR share area and modal styles
- `tests/e2e/test_qr_and_player_flow.py` - Added QR visibility and modal tests
