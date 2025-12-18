# Story 1.5: Admin Page Access

Status: ready-for-dev

## Story

As a **Home Assistant admin**,
I want **to access a standalone admin web page without authentication**,
So that **I can manage Beatify games from any device on my network**.

## Acceptance Criteria

1. **Given** Beatify integration is configured
   **When** admin navigates to `http://<ha-ip>:8123/beatify/admin`
   **Then** the admin page loads without requiring HA login (FR6)
   **And** the page is mobile-responsive

2. **Given** admin page loads
   **When** the page initializes
   **Then** it displays:
   - Detected media players from Story 1.4
   - Detected playlists from Story 1.4
   - Music Assistant status (connected/not found)
   **And** if MA is not configured, shows error with setup guide link (FR54)

3. **Given** admin accesses the page from a mobile device
   **When** the page renders
   **Then** all elements are touch-friendly (44x44px minimum targets)
   **And** layout adapts to mobile viewport

## Tasks / Subtasks

- [ ] Task 1: Create admin page HTTP endpoint (AC: #1)
  - [ ] 1.1: Create `server/views.py` module
  - [ ] 1.2: Create `AdminView` class extending `HomeAssistantView`
  - [ ] 1.3: Set `url = "/beatify/admin"`
  - [ ] 1.4: Set `name = "beatify:admin"`
  - [ ] 1.5: Set `requires_auth = False` for frictionless access
  - [ ] 1.6: Implement `get()` method to serve HTML page

- [ ] Task 2: Create admin HTML page (AC: #1, #2, #3)
  - [ ] 2.1: Create `www/admin.html` with basic structure
  - [ ] 2.2: Add viewport meta tag for mobile responsiveness
  - [ ] 2.3: Add CSS link to `www/css/styles.css`
  - [ ] 2.4: Add JS link to `www/js/admin.js`
  - [ ] 2.5: Create placeholder sections for media players, playlists, MA status

- [ ] Task 3: Create admin CSS styles (AC: #3)
  - [ ] 3.1: Create `www/css/styles.css`
  - [ ] 3.2: Set mobile-first base styles
  - [ ] 3.3: Set minimum touch target size: `min-width: 44px; min-height: 44px`
  - [ ] 3.4: Add responsive breakpoints using `min-width` media queries
  - [ ] 3.5: Style status indicators (connected/error states)

- [ ] Task 4: Create admin JavaScript (AC: #2)
  - [ ] 4.1: Create `www/js/admin.js`
  - [ ] 4.2: Implement `fetchStatus()` to get current state from API
  - [ ] 4.3: Implement `renderMediaPlayers(players)` to display list
  - [ ] 4.4: Implement `renderPlaylists(playlists)` to display list
  - [ ] 4.5: Implement `renderMAStatus(isConnected)` with error link if needed
  - [ ] 4.6: Call render functions on page load

- [ ] Task 5: Create status API endpoint (AC: #2)
  - [ ] 5.1: Create `StatusView` in `server/views.py`
  - [ ] 5.2: Set `url = "/beatify/api/status"`
  - [ ] 5.3: Set `requires_auth = False`
  - [ ] 5.4: Return JSON with media_players, playlists, ma_status
  - [ ] 5.5: Include error details if MA not configured

- [ ] Task 6: Register views in __init__.py (AC: #1)
  - [ ] 6.1: Import AdminView, StatusView from server.views
  - [ ] 6.2: Register views in `async_setup_entry` using `hass.http.register_view()`
  - [ ] 6.3: Serve static files from `www/` directory

- [ ] Task 7: Set up static file serving (AC: #1)
  - [ ] 7.1: Create `server/__init__.py` with static path registration
  - [ ] 7.2: Register static path for `/beatify/static` → `www/`
  - [ ] 7.3: Ensure CSS, JS files are accessible
  - [ ] 7.4: Create `www/img/no-artwork.svg` placeholder (referenced in architecture)

- [ ] Task 8: Write tests (AC: #1, #2)
  - [ ] 8.1: Test AdminView returns HTML without auth
  - [ ] 8.2: Test StatusView returns correct JSON structure
  - [ ] 8.3: Test static file serving works
  - [ ] 8.4: Test MA status reflects actual state

## Dependencies

- **Story 1.1** (done): Project scaffold with `__init__.py`
- **Story 1.2** (ready): HACS metadata configured
- **Story 1.3** (ready): MA detection in config flow
- **Story 1.4** (ready): Media player and playlist discovery (data stored in `hass.data[DOMAIN]`)

## Dev Notes

### HomeAssistantView Pattern

From [architecture.md - URL Structure]:
| Path | Purpose |
|------|---------|
| `/beatify/admin` | Admin page (setup, QR, controls) |
| `/beatify/static/*` | CSS, JS assets |

```python
# server/views.py
import logging
from pathlib import Path

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant

from ..const import DOMAIN

_LOGGER = logging.getLogger(__name__)

class AdminView(HomeAssistantView):
    """Serve the admin page."""

    url = "/beatify/admin"
    name = "beatify:admin"
    requires_auth = False  # Frictionless access per PRD

    def __init__(self, hass: HomeAssistant):
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:
        """Serve the admin HTML page."""
        html_path = Path(__file__).parent.parent / "www" / "admin.html"
        if not html_path.exists():
            _LOGGER.error("Admin page not found: %s", html_path)
            return web.Response(text="Admin page not found", status=500)
        html_content = html_path.read_text()
        return web.Response(text=html_content, content_type="text/html")


class StatusView(HomeAssistantView):
    """API endpoint for admin page status."""

    url = "/beatify/api/status"
    name = "beatify:api:status"
    requires_auth = False

    def __init__(self, hass: HomeAssistant):
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:
        """Return current status as JSON."""
        data = self.hass.data.get(DOMAIN, {})

        status = {
            "media_players": data.get("media_players", []),
            "playlists": data.get("playlists", []),
            "ma_configured": await self._check_ma_status(),
            "ma_setup_url": "https://music-assistant.io/getting-started/",
        }

        return web.json_response(status)

    async def _check_ma_status(self) -> bool:
        """Check if Music Assistant is configured."""
        from homeassistant.config_entries import ConfigEntryState
        entries = self.hass.config_entries.async_entries("music_assistant")
        return any(e.state == ConfigEntryState.LOADED for e in entries)
```

### Architecture Compliance

From [architecture.md - Core Architectural Decisions #10]:
- URL Structure: `/beatify/*` namespace
- Clean, memorable for QR codes

From [architecture.md - Frontend Architecture]:
```
www/
├── admin.html
├── css/
│   └── styles.css
└── js/
    └── admin.js
```

From [project-context.md - WebSocket (Custom, NOT HA's websocket_api)]:
- Endpoint: `/beatify/ws` via custom aiohttp handler
- NO authentication (frictionless player access)

### Admin HTML Structure

```html
<!-- www/admin.html -->
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Beatify Admin</title>
    <link rel="stylesheet" href="/beatify/static/css/styles.css">
</head>
<body>
    <header>
        <h1>Beatify</h1>
    </header>

    <main>
        <section id="ma-status" class="status-section">
            <h2>Music Assistant</h2>
            <div id="ma-status-content">Loading...</div>
        </section>

        <section id="media-players" class="card-section">
            <h2>Media Players</h2>
            <div id="media-players-list">Loading...</div>
        </section>

        <section id="playlists" class="card-section">
            <h2>Playlists</h2>
            <div id="playlists-list">Loading...</div>
        </section>

        <!-- Game controls added in Epic 2 -->
        <section id="game-controls" class="hidden">
            <button id="start-game" class="btn btn-primary" disabled>Start Game</button>
        </section>
    </main>

    <script src="/beatify/static/js/admin.js"></script>
</body>
</html>
```

### Admin CSS (Mobile-First)

From [project-context.md - Frontend Rules]:
- Mobile-first: use `min-width` breakpoints, not `max-width`
- Touch targets: minimum 44x44px

```css
/* www/css/styles.css */

/* Base mobile styles */
* {
    box-sizing: border-box;
}

body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    margin: 0;
    padding: 16px;
    background: #f5f5f5;
    color: #333;
}

header h1 {
    margin: 0 0 16px;
    font-size: 24px;
}

/* Touch targets - minimum 44x44px */
button, .btn {
    min-width: 44px;
    min-height: 44px;
    padding: 12px 24px;
    font-size: 16px;
    border: none;
    border-radius: 8px;
    cursor: pointer;
}

.btn-primary {
    background: #4CAF50;
    color: white;
}

.btn-primary:disabled {
    background: #ccc;
    cursor: not-allowed;
}

/* Status indicators */
.status-connected {
    color: #4CAF50;
}

.status-error {
    color: #f44336;
}

/* Cards */
.card-section {
    background: white;
    border-radius: 12px;
    padding: 16px;
    margin-bottom: 16px;
    box-shadow: 0 2px 4px rgba(0,0,0,0.1);
}

.card-section h2 {
    margin: 0 0 12px;
    font-size: 18px;
}

/* List items */
.list-item {
    padding: 12px;
    border-bottom: 1px solid #eee;
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.list-item:last-child {
    border-bottom: none;
}

/* Hidden utility */
.hidden {
    display: none;
}

/* Tablet+ breakpoint */
@media (min-width: 768px) {
    body {
        max-width: 800px;
        margin: 0 auto;
        padding: 24px;
    }

    header h1 {
        font-size: 32px;
    }
}
```

### Admin JavaScript

From [project-context.md - JavaScript]:
- Vanilla JS only (no jQuery, no frameworks)
- All WS field conversion: `snake_case` → `camelCase` on receive

```javascript
// www/js/admin.js

document.addEventListener('DOMContentLoaded', async () => {
    await loadStatus();
});

async function loadStatus() {
    try {
        const response = await fetch('/beatify/api/status');
        const status = await response.json();

        renderMAStatus(status.ma_configured, status.ma_setup_url);
        renderMediaPlayers(status.media_players);
        renderPlaylists(status.playlists);
    } catch (error) {
        console.error('Failed to load status:', error);
        document.getElementById('ma-status-content').textContent = 'Failed to load status';
    }
}

function renderMAStatus(isConfigured, setupUrl) {
    const container = document.getElementById('ma-status-content');

    if (isConfigured) {
        container.innerHTML = '<span class="status-connected">✓ Connected</span>';
    } else {
        container.innerHTML = `
            <span class="status-error">✗ Not configured</span>
            <p>Music Assistant is required for Beatify.</p>
            <a href="${setupUrl}" target="_blank" class="btn">Setup Guide</a>
        `;
    }
}

function renderMediaPlayers(players) {
    const container = document.getElementById('media-players-list');

    if (!players || players.length === 0) {
        container.innerHTML = '<p>No media players found</p>';
        return;
    }

    container.innerHTML = players.map(player => `
        <div class="list-item">
            <span>${player.friendly_name}</span>
            <span class="state">${player.state}</span>
        </div>
    `).join('');
}

function renderPlaylists(playlists) {
    const container = document.getElementById('playlists-list');

    if (!playlists || playlists.length === 0) {
        container.innerHTML = '<p>No playlists found. Add .json files to the beatify/playlists folder.</p>';
        return;
    }

    container.innerHTML = playlists.map(playlist => `
        <div class="list-item ${playlist.is_valid ? '' : 'status-error'}">
            <span>${playlist.name}</span>
            <span>${playlist.song_count} songs</span>
        </div>
    `).join('');
}
```

### Static File Registration

```python
# __init__.py additions

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Beatify from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    # Register HTTP views
    from .server.views import AdminView, StatusView
    hass.http.register_view(AdminView(hass))
    hass.http.register_view(StatusView(hass))

    # Register static files
    from .server import async_register_static_paths
    await async_register_static_paths(hass)

    # ... rest of setup

    return True
```

```python
# server/__init__.py
from pathlib import Path
from homeassistant.core import HomeAssistant
from homeassistant.components.http import StaticPathConfig

async def async_register_static_paths(hass: HomeAssistant) -> None:
    """Register static file paths."""
    www_path = Path(__file__).parent.parent / "www"

    await hass.http.async_register_static_paths([
        StaticPathConfig("/beatify/static", str(www_path), cache_headers=True)
    ])
```

### Project Structure Notes

Files created in this story:
```
custom_components/beatify/
├── __init__.py          # Modified: register views, static paths
├── server/
│   ├── __init__.py      # NEW: Static path registration
│   └── views.py         # NEW: AdminView, StatusView
└── www/
    ├── admin.html       # NEW: Admin page
    ├── css/
    │   └── styles.css   # NEW: Mobile-first styles
    └── js/
        └── admin.js     # NEW: Admin page logic

tests/
└── unit/
    └── test_views.py    # NEW: View tests
```

### Naming Conventions

From [project-context.md - Naming Conventions]:
| Context | Convention | Example |
|---------|------------|---------|
| JS files | kebab-case | `admin.js` (or `ws-client.js`) |
| JS variables | camelCase | `playerName` |
| CSS classes | kebab-case | `.player-card` |
| CSS states | is- prefix | `.is-active` |

### Testing This Story

**Unit Tests:**
```python
# tests/unit/test_views.py

async def test_admin_view_no_auth(hass, aiohttp_client):
    """Test admin page loads without authentication."""
    # Register view
    hass.http.register_view(AdminView(hass))
    client = await aiohttp_client(hass.http.app)

    response = await client.get("/beatify/admin")
    assert response.status == 200
    assert "text/html" in response.content_type

async def test_status_api_returns_json(hass, aiohttp_client):
    """Test status API returns expected structure."""
    hass.http.register_view(StatusView(hass))
    client = await aiohttp_client(hass.http.app)

    response = await client.get("/beatify/api/status")
    assert response.status == 200

    data = await response.json()
    assert "media_players" in data
    assert "playlists" in data
    assert "ma_configured" in data
```

**Manual Testing:**
1. Install Beatify integration
2. Navigate to `http://<ha-ip>:8123/beatify/admin`
3. Verify page loads without login prompt
4. Check media players are listed
5. Check playlists are listed
6. Check MA status shows correctly
7. Test on mobile device for responsiveness

### References

- [Source: _bmad-output/architecture.md#URL-Structure]
- [Source: _bmad-output/architecture.md#Frontend-Architecture]
- [Source: _bmad-output/architecture.md#API-Boundaries]
- [Source: _bmad-output/project-context.md#Frontend-Rules]
- [Source: _bmad-output/epics.md#Story-1.5]
- [Source: _bmad-output/epics.md#FR6] (admin page access)
- [Source: _bmad-output/epics.md#FR54] (MA not configured error)

---

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

### File List

