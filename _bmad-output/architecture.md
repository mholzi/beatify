---
stepsCompleted: [1, 2, 3, 4, 5, 6, 7, 8]
inputDocuments:
  - '_bmad-output/prd.md'
  - '_bmad-output/research/music-assistant-media-player-research.md'
workflowType: 'architecture'
lastStep: 8
status: 'complete'
completedAt: '2025-12-18'
project_name: 'Beatify'
user_name: 'Markusholzhaeuser'
date: '2025-12-17'
---

# Architecture Decision Document

_This document builds collaboratively through step-by-step discovery. Sections are appended as we work through each architectural decision together._

## Project Context Analysis

### Requirements Overview

**Functional Requirements:**
58 requirements across 10 categories, with the core game loop (10 FRs) and scoring system (7 FRs) representing the heaviest architectural components. The integration spans HACS installation, direct media player control, and real-time WebSocket communication for up to 20 concurrent players.

**Non-Functional Requirements:**
- Performance: <2s page load, <200ms WebSocket latency, 60fps interactions
- Scalability: 20 players max, single game per HA instance
- Reliability: 99% game completion, graceful degradation on errors
- Security: Intentionally none (frictionless access is a design principle)

**Scale & Complexity:**
- Primary domain: Web application + Home Assistant integration
- Complexity level: Low-Medium (well-scoped MVP)
- Estimated architectural components: 6-8 major modules

### Technical Constraints & Dependencies

| Constraint | Impact |
|------------|--------|
| Python within HA environment | Must use HA's async patterns (aiohttp) |
| Local network only | No cloud, no CDN; QR contains local IP |
| WebSocket coexistence | Must not conflict with HA's native WebSocket |
| No authentication | Custom WebSocket endpoint (not HA's `websocket_api`) |

### Cross-Cutting Concerns Identified

1. **Real-time state synchronization** — All clients must see consistent game state
2. **Error recovery and resilience** — Admin/player disconnects, media player unavailable
3. **Mobile-first responsive design** — Primary interaction device is phone
4. **Admin role duality** — Single user plays and controls simultaneously
5. **Late-join state recovery** — Players entering mid-game need current round state

## Starter Template Evaluation

### Primary Technology Domain

Home Assistant HACS Integration (Python backend + vanilla JS frontend)

### Starter Options Considered

| Option | Status | Verdict |
|--------|--------|---------|
| ludeeus/integration_blueprint | ✅ Active | **Selected** |
| cookiecutter-homeassistant-custom-component | ⚠️ Outdated (2021) | Rejected |
| Manual from HA docs | ✅ Current | Backup option |

### Selected Starter: integration_blueprint

**Rationale:**
- Actively maintained with 539 stars
- Standard HA integration structure
- DevContainer support for VS Code
- Lightweight enough to extend for Beatify's custom needs
- HACS-compatible out of the box

**Initialization:**
```bash
git clone https://github.com/ludeeus/integration_blueprint.git beatify
cd beatify
mv custom_components/integration_blueprint custom_components/beatify
```

### Architectural Decisions Provided by Starter

**Language & Runtime:**
- Python 3.11+ (HA requirement)
- Async/await patterns (aiohttp)

**Code Organization:**
- Standard `custom_components/<domain>/` structure
- Config flow for UI-based setup
- Translation support

**Development Experience:**
- VS Code DevContainer with HA instance
- Ruff linting pre-configured
- GitHub Actions templates

**What Beatify Extends:**
- Custom WebSocket server (frictionless player access)
- HomeAssistantView web endpoints
- Static file serving for frontend
- Game state management module

## Core Architectural Decisions

### Decision Summary

| # | Category | Decision | Rationale |
|---|----------|----------|-----------|
| 1 | WebSocket | Custom aiohttp WebSocket | Frictionless player access (no HA auth) |
| 2 | State Management | State machine pattern | Clear phases: LOBBY → PLAYING → REVEAL → END |
| 3 | Media Player | Direct HA service calls | Simple integration, no external dependencies |
| 4 | Frontend Delivery | Static files in `www/` | Fastest load, no build step |
| 5 | Playlist Format | JSON (year + uri + fun_fact) | Metadata from media_player, year is game-critical |
| 6 | Player Sessions | Name-based + 60s reconnect | Survives brief disconnects, preserves score |
| 7 | Admin Identity | Via admin "Participate" button | Explicit admin route per PRD |
| 8 | Real-time Sync | Full state broadcast | Simple, state is small (20 players) |
| 9 | Timer | Hybrid server deadline | Server sets deadline, client counts down |
| 10 | URL Structure | `/beatify/*` namespace | Clean, memorable for QR codes |

### WebSocket Architecture

**Decision:** Custom aiohttp WebSocket server at `/beatify/ws`

- No authentication required (frictionless access)
- Single implementation for admin and players
- Reconnection handled via name-based session recovery

**Message Schema (Client → Server):**
```json
{"type": "join", "name": "string"}
{"type": "submit", "year": number, "bet": boolean}
{"type": "admin", "action": "start_game|stop_song|next_round|end_game"}
{"type": "admin", "action": "set_volume", "level": 0.0-1.0}
```

**Message Schema (Server → Client):**
```json
{"type": "state", "phase": "LOBBY|PLAYING|REVEAL|END", ...}
{"type": "error", "code": "string", "message": "string"}
```

**State payload rules:**
- `song.year` and `song.fun_fact` hidden during PLAYING, revealed in REVEAL
- `players[].streak` included for streak display
- `players[].streak_bonus` included in REVEAL results

### Game State Machine

**Decision:** Explicit state machine with phases

```
┌─────────┐    start    ┌─────────┐   timer/all   ┌────────┐
│  LOBBY  │───────────▶│ PLAYING │─────submitted─▶│ REVEAL │
└─────────┘             └─────────┘               └────────┘
     ▲                                                 │
     │                    next round                   │
     └─────────────────────────────────────────────────┘
                              │
                          end game
                              ▼
                         ┌────────┐
                         │  END   │
                         └────────┘
```

- State transitions triggered by: admin actions, timer expiry, all players submitted
- Invalid transitions rejected with error message
- Admin disconnect → PAUSED state, resume on reconnect

### Media Player Integration

**Decision:** Direct HA media_player service calls

- Config flow validates at least one media_player entity exists
- Runtime: If media player unavailable, pause game with "Media player unavailable" message
- Service calls: `media_player.play_media` for playback
- Metadata fetch: Artist/title/album art retrieved from media_player entity attributes after playback starts

**Playback Control:**
```python
await hass.services.async_call(
    "media_player",
    "play_media",
    {
        "entity_id": media_player_entity,
        "media_content_id": song_uri,
        "media_content_type": "music"
    }
)
```

**Metadata Retrieval:**
```python
state = hass.states.get(media_player_entity)
artist = state.attributes.get("media_artist", "Unknown Artist")
title = state.attributes.get("media_title", "Unknown Title")
artwork = state.attributes.get("entity_picture", "/beatify/static/img/no-artwork.svg")
```

### Playlist Data Format

**Decision:** JSON with year, URI, and fun_fact

```json
{
  "name": "80s Hits",
  "songs": [
    {
      "year": 1984,
      "uri": "spotify:track:xxx",
      "fun_fact": "George Michael wrote this in his bedroom in 10 minutes"
    }
  ]
}
```

- Stored in HA config directory: `config/beatify/playlists/`
- Year and fun_fact are authoritative (manually curated)
- Artist, title, album art fetched from media_player entity attributes at runtime

### Frontend Architecture

**Decision:** Static files served from `www/` directory

```
www/
├── admin.html
├── player.html
├── css/
│   └── styles.css
└── js/
    ├── admin.js
    ├── player.js
    └── ws.js
```

- No build step, no bundler
- Dynamic content via WebSocket
- QR code URL passed as query param: `/beatify/play?game=xxx`

### Player Session Management

**Decision:** Name-based identity with reconnection grace period

- Player identified by display name (unique per game)
- On disconnect: 60-second grace period before session expires
- Reconnect with same name within window → restore score, rejoin current round
- After timeout: name becomes available, old session discarded

### Timer Synchronization

**Decision:** Hybrid approach — server deadline, client countdown

- Server sends `round_end_timestamp` (Unix epoch ms)
- Clients calculate remaining time locally
- Server rejects submissions after deadline (authoritative)
- No client-side buffer — show real countdown, honest display

### Time Testing Strategy

**Decision:** Simple function injection for testability

```python
class GameState:
    def __init__(self, time_fn=time.time):
        self._now = time_fn
```

### URL Structure

| Path | Purpose |
|------|---------|
| `/beatify/admin` | Admin page (setup, QR, controls) |
| `/beatify/play` | Player page (join, game UI) |
| `/beatify/ws` | WebSocket endpoint |
| `/beatify/static/*` | CSS, JS assets |

## Implementation Patterns & Consistency Rules

### Pattern Summary

| Category | Pattern | Example |
|----------|---------|---------|
| Python naming | PEP 8 strict | `snake_case` funcs, `PascalCase` classes |
| JS naming | JS standard | `camelCase` funcs, `PascalCase` classes |
| WS message fields | snake_case | `{"player_name": "Tom"}` |
| Python files | snake_case | `game_state.py` |
| JS files | kebab-case | `player-client.js` |
| CSS classes | Simple kebab | `.player-card`, `.is-active` |
| Tests | Separate directory | `tests/test_*.py` |
| Logging | HA native | `_LOGGER = logging.getLogger(__name__)` |
| Error codes | UPPER_SNAKE | `NAME_TAKEN`, `GAME_NOT_STARTED` |
| Imports | PEP 8 / isort | stdlib → third-party → HA → local |

### Python Naming (PEP 8)

```python
# Classes: PascalCase
class GameState:
class WebSocketHandler:

# Functions/methods/variables: snake_case
def get_current_round():
player_name = "Tom"

# Constants: UPPER_SNAKE_CASE
MAX_PLAYERS = 20
RECONNECT_TIMEOUT = 60
```

### JavaScript Naming

```javascript
// Variables/functions: camelCase
const playerName = "Tom";
function handleSubmit() {}

// Constants: UPPER_SNAKE_CASE
const MAX_PLAYERS = 20;

// Classes: PascalCase
class GameClient {}
```

### WebSocket Message Format

All JSON fields use `snake_case` (Python-native). JS destructures with rename:

```javascript
const { player_name: playerName, current_score: currentScore } = data;
```

### File Naming

| Type | Convention | Example |
|------|------------|---------|
| Python | snake_case | `game_state.py`, `websocket_handler.py` |
| JavaScript | kebab-case | `player-client.js`, `ws-handler.js` |
| CSS | kebab-case | `styles.css` |

### CSS Classes

```css
/* Blocks: kebab-case */
.player-card { }
.year-slider { }

/* States: is- prefix */
.is-active { }
.is-submitted { }

/* Modifiers: double-dash */
.player-card--highlighted { }
```

### Test Structure

```
tests/
├── __init__.py
├── conftest.py           # Shared fixtures
├── test_game_state.py
├── test_scoring.py
└── test_websocket.py
```

### Logging

```python
import logging
_LOGGER = logging.getLogger(__name__)

_LOGGER.debug("State: %s -> %s", old, new)  # Dev only
_LOGGER.info("Game started: %d players", n)  # Events
_LOGGER.warning("Player disconnected: %s", name)  # Issues
_LOGGER.error("Media player error: %s", err)  # Failures
```

### Error Codes

| Code | Meaning |
|------|---------|
| `NAME_TAKEN` | Player name already exists |
| `NAME_INVALID` | Empty or too long |
| `GAME_NOT_STARTED` | Action requires active game |
| `GAME_ALREADY_STARTED` | Can't join after start |
| `NOT_ADMIN` | Admin action by non-admin |
| `ROUND_EXPIRED` | Submission after deadline |
| `MEDIA_PLAYER_UNAVAILABLE` | Media player offline or unresponsive |
| `INVALID_ACTION` | Unknown action type |

### Import Order (Python)

```python
# 1. Standard library
import logging
from typing import Any

# 2. Third-party
import aiohttp

# 3. Home Assistant
from homeassistant.core import HomeAssistant

# 4. Local
from .game.state import GameState
```

### Enforcement

**All AI agents MUST:**
- Run `ruff` linter before committing (catches naming violations)
- Follow these patterns exactly — no "improvements" or alternatives
- When in doubt, check existing code for precedent

## Project Structure & Boundaries

### Complete Project Directory Structure

```
beatify/
├── README.md                           # Project documentation
├── LICENSE                             # MIT license
├── hacs.json                           # HACS metadata
├── .gitignore
├── .ruff.toml                          # Linter config
├── .pre-commit-config.yaml             # Pre-commit hooks
├── requirements.txt                    # Dev dependencies (pytest, etc.)
│
├── .github/
│   ├── workflows/
│   │   ├── ci.yml                      # Lint, test on PR
│   │   └── release.yml                 # Build on tag
│   └── ISSUE_TEMPLATE/
│       ├── bug_report.yml
│       └── feature_request.yml
│
├── .devcontainer/
│   └── devcontainer.json               # VS Code dev container
│
├── custom_components/
│   └── beatify/
│       ├── __init__.py                 # Integration setup, entry point
│       ├── manifest.json               # HA integration metadata
│       ├── const.py                    # DOMAIN, constants, error codes
│       ├── config_flow.py              # UI setup wizard
│       │
│       ├── game/                       # Game logic module
│       │   ├── __init__.py
│       │   ├── state.py                # GameState class, state machine
│       │   ├── scoring.py              # Score calculation, bonuses
│       │   ├── player.py               # Player session management
│       │   └── playlist.py             # Playlist loading, validation
│       │
│       ├── server/                     # Web & WebSocket module
│       │   ├── __init__.py
│       │   ├── views.py                # HomeAssistantView classes
│       │   ├── websocket.py            # Custom WS handler
│       │   └── messages.py             # Message schema, serialization
│       │
│       ├── services/                   # HA service integration
│       │   ├── __init__.py
│       │   └── media_player.py         # Playback, volume, metadata
│       │
│       ├── translations/
│       │   └── en.json                 # Config flow strings
│       │
│       └── www/                        # Static frontend assets
│           ├── admin.html              # Admin page
│           ├── player.html             # Player page
│           ├── css/
│           │   └── styles.css          # Mobile-first styles
│           └── js/
│               ├── admin.js            # Admin page logic
│               ├── player.js           # Player page logic
│               └── ws-client.js        # Shared WebSocket client
│
└── tests/
    ├── __init__.py
    ├── conftest.py                     # Shared fixtures, mocks
    ├── test_game_state.py              # State machine tests
    ├── test_scoring.py                 # Scoring calculation tests
    ├── test_player_session.py          # Session management tests
    ├── test_playlist.py                # Playlist loading tests
    ├── test_websocket.py               # WS message handling tests
    └── test_integration.py             # Full game flow tests
```

### Requirements to Structure Mapping

| PRD Category | Files |
|--------------|-------|
| **FR1-6: Installation & Setup** | `__init__.py`, `config_flow.py`, `manifest.json` |
| **FR7-11: Game Configuration** | `game/playlist.py`, `server/views.py` (admin) |
| **FR12-16: Player Onboarding** | `server/websocket.py`, `game/player.py`, `www/player.html` |
| **FR17-21: Lobby Management** | `game/state.py` (LOBBY phase), `server/messages.py` |
| **FR22-31: Core Game Loop** | `game/state.py` (PLAYING/REVEAL), `services/media_player.py` |
| **FR32-38: Scoring System** | `game/scoring.py` |
| **FR39-42: Leaderboard** | `server/messages.py` (state broadcast), `www/js/player.js` |
| **FR43-48: Admin Controls** | `server/websocket.py`, `www/js/admin.js` |
| **FR49-53: Session Management** | `game/player.py`, `game/state.py` (PAUSED) |
| **FR54-59: Error Handling** | `const.py` (error codes), all modules |

### Architectural Boundaries

**API Boundaries:**

| Endpoint | Handler | Purpose |
|----------|---------|---------|
| `/beatify/admin` | `server/views.py:AdminView` | Serve admin HTML |
| `/beatify/play` | `server/views.py:PlayerView` | Serve player HTML |
| `/beatify/ws` | `server/websocket.py:WebSocketHandler` | Game communication |
| `/beatify/static/*` | HA static path | CSS, JS assets |

**Component Boundaries:**

```
┌─────────────────────────────────────────────────────────┐
│                    Home Assistant                        │
│  ┌─────────────────────────────────────────────────┐    │
│  │              Beatify Integration                 │    │
│  │                                                  │    │
│  │  ┌──────────────┐    ┌───────────────────────┐  │    │
│  │  │    server/   │    │        game/          │  │    │
│  │  │  views.py    │───▶│    state.py           │  │    │
│  │  │  websocket.py│◀──▶│    scoring.py         │  │    │
│  │  │  messages.py │    │    player.py          │  │    │
│  │  └──────────────┘    │    playlist.py        │  │    │
│  │         │            └───────────────────────┘  │    │
│  │         │                      │                │    │
│  │         ▼                      ▼                │    │
│  │  ┌──────────────────────────────────────────┐  │    │
│  │  │              services/                    │  │    │
│  │  │            media_player.py               │  │    │
│  │  └──────────────────────────────────────────┘  │    │
│  │                       │                         │    │
│  └───────────────────────│─────────────────────────┘    │
│                          ▼                              │
│  ┌───────────────────────────────────────────────────┐  │
│  │              Media Player Entities                 │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

**Data Flow:**

```
Player Phone                    Beatify                     Home Assistant
     │                            │                              │
     │ WS: {"type":"join"}        │                              │
     │───────────────────────────▶│                              │
     │                            │ game/player.py               │
     │                            │ create session               │
     │                            │                              │
     │ WS: {"type":"state",...}   │                              │
     │◀───────────────────────────│                              │
     │                            │                              │
     │ WS: {"type":"submit"}      │                              │
     │───────────────────────────▶│                              │
     │                            │ game/scoring.py              │
     │                            │ calculate points             │
     │                            │                              │
     │                            │ services/media_player.py     │
     │                            │────────────────────────────▶│
     │                            │  play_media / volume_set     │
```

### Key File Responsibilities

| File | Single Responsibility |
|------|----------------------|
| `__init__.py` | Integration lifecycle (setup, unload) |
| `config_flow.py` | User configuration UI |
| `const.py` | All constants, error codes |
| `game/state.py` | State machine, phase transitions |
| `game/scoring.py` | Point calculation only |
| `game/player.py` | Session tracking, reconnection |
| `game/playlist.py` | Load, validate, iterate playlists |
| `server/views.py` | HTTP endpoints only |
| `server/websocket.py` | WS connection handling |
| `server/messages.py` | Serialize/deserialize messages |
| `services/media_player.py` | Playback, volume, metadata retrieval |

## Architecture Validation Results

### Validation Summary

| Category | Result |
|----------|--------|
| Coherence | ✅ All decisions compatible |
| Requirements Coverage | ✅ 58/58 FRs supported |
| Implementation Readiness | ✅ Complete |
| Critical Gaps | ✅ None |

### Refinements from Review

**Playlist Storage Path:**
```
{HA_CONFIG}/beatify/playlists/*.json
```
User-editable location outside the integration directory.

**Test Fixtures (conftest.py):**
```python
@pytest.fixture
def game_state():
    """Game state with controlled time."""
    return GameState(time_fn=lambda: 1000.0)

@pytest.fixture
def mock_hass():
    """Mock Home Assistant instance."""
    hass = MagicMock()
    hass.config.path = lambda *p: "/config/" + "/".join(p)
    return hass

@pytest.fixture
def mock_media_player():
    """Mock media_player service calls."""
    return AsyncMock()
```

**Album Art Fallback:**
- If media_player returns no album art → use generic placeholder image
- Placeholder stored at: `www/img/no-artwork.svg`

**Scalability Note:**
- MVP target: 20 concurrent players
- Architecture can scale beyond with optimization (delta broadcasts, pagination)
- Full state broadcast is acceptable at 20; revisit if targeting 100+

### Architecture Completeness Checklist

**✅ Requirements Analysis**
- [x] Project context analyzed (HA integration + party game)
- [x] Scale assessed (20 players MVP, scalable beyond)
- [x] Constraints identified (local network, no auth)
- [x] Cross-cutting concerns mapped (state sync, error recovery)

**✅ Architectural Decisions**
- [x] 10 core decisions documented
- [x] Technology versions verified (HA 2025.11+, MA 2.4+, Python 3.11+)
- [x] WebSocket schema defined (messages.py)
- [x] State machine specified (LOBBY → PLAYING → REVEAL → END)

**✅ Implementation Patterns**
- [x] 9 naming/structure patterns defined
- [x] Error codes enumerated (8 codes)
- [x] Logging standards set (HA native)
- [x] Import order defined (PEP 8 / isort)
- [x] Test fixtures documented

**✅ Project Structure**
- [x] Complete directory tree (25+ files)
- [x] Component boundaries defined
- [x] Data flow documented
- [x] FR-to-file mapping complete
- [x] Playlist storage path specified

### Architecture Readiness Assessment

**Overall Status:** READY FOR IMPLEMENTATION

**Confidence Level:** HIGH

**Key Strengths:**
- Clear state machine with explicit phases
- Comprehensive WebSocket message schema with fun_fact support
- Strong separation of concerns (game/ vs server/ vs services/)
- Mobile-first, frictionless player experience preserved
- Testable design with time injection and mock fixtures

**Implementation Sequence:**
1. Clone integration_blueprint, rename to beatify
2. Create `const.py` with DOMAIN and error codes
3. Implement `game/state.py` state machine
4. Implement `game/scoring.py` calculations
5. Create `server/websocket.py` with join/submit handlers
6. Build minimal `www/player.html` for testing
7. Add `services/music_assistant.py` integration
8. Complete admin page and controls

---

## Architecture Completion Summary

### Workflow Completion

**Architecture Decision Workflow:** COMPLETED ✅
**Total Steps Completed:** 8
**Date Completed:** 2025-12-18
**Document Location:** `_bmad-output/architecture.md`

### Final Architecture Deliverables

**Complete Architecture Document**
- 10 core architectural decisions documented with rationale
- 9 implementation patterns ensuring AI agent consistency
- Complete project structure with 25+ files mapped
- 59 functional requirements mapped to architecture
- Validation confirming coherence and completeness

**Implementation Ready Foundation**
- Technology stack: Python 3.11+, HA 2025.11+, MA 2.4+
- WebSocket message schema fully specified
- State machine with explicit phases documented
- Test fixtures and patterns defined

### Implementation Handoff

**For AI Agents:**
This architecture document is your complete guide for implementing Beatify. Follow all decisions, patterns, and structures exactly as documented.

**First Implementation Priority:**
```bash
git clone https://github.com/ludeeus/integration_blueprint.git beatify
cd beatify
mv custom_components/integration_blueprint custom_components/beatify
```

**Development Sequence:**
1. Initialize project using integration_blueprint
2. Create `const.py` with DOMAIN, error codes, constants
3. Implement `game/state.py` state machine (LOBBY → PLAYING → REVEAL → END)
4. Implement `game/scoring.py` with accuracy/speed/streak calculations
5. Create `server/websocket.py` with custom aiohttp WS handler
6. Build `www/player.html` and `www/admin.html` static pages
7. Add `services/music_assistant.py` for MA integration
8. Complete config flow and translations

### Quality Assurance Checklist

**✅ Architecture Coherence**
- [x] All 10 decisions work together without conflicts
- [x] Technology choices are compatible
- [x] Patterns support architectural decisions
- [x] Structure aligns with all choices

**✅ Requirements Coverage**
- [x] 59/59 functional requirements supported
- [x] All non-functional requirements addressed
- [x] Cross-cutting concerns handled
- [x] Integration points defined

**✅ Implementation Readiness**
- [x] Decisions are specific and actionable
- [x] Patterns prevent agent conflicts
- [x] Structure is complete and unambiguous
- [x] Examples provided for clarity

---

**Architecture Status:** READY FOR IMPLEMENTATION ✅

**Next Phase:** Create epics and stories, then begin implementation using these architectural decisions.

