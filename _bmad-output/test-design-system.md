# System-Level Test Design - Beatify

**Date:** 2025-12-18
**Author:** Markusholzhaeuser (TEA: Murat)
**Status:** Draft
**Mode:** System-Level (Phase 3 - Pre-Implementation Testability Review)

---

## Executive Summary

This document provides the system-level testability review for Beatify, a Home Assistant party game integration. The architecture demonstrates **strong testability foundations** with time injection, explicit state machine, and mock-friendly design patterns.

**Overall Assessment: PASS** - Ready for implementation with test infrastructure.

---

## Testability Assessment

### Controllability: PASS

**Can we control system state for testing?**

| Capability | Status | Evidence |
|------------|--------|----------|
| Control game state | ✅ | WebSocket messages trigger state transitions; direct GameState instantiation |
| Time manipulation | ✅ | `GameState(time_fn=lambda: 1000.0)` documented in architecture |
| Data seeding | ✅ | In-memory state; create fresh GameState per test |
| External service mocking | ✅ | MA service: `AsyncMock()`, HA: `MagicMock()` patterns specified |
| Trigger error conditions | ✅ | Error codes (8 types) enable targeted error testing |

**Controllability Details:**

```python
# From architecture - time injection for testing
class GameState:
    def __init__(self, time_fn=time.time):
        self._now = time_fn

# Test usage
def test_round_expiry():
    state = GameState(time_fn=lambda: 1000.0)
    # Deterministic timer testing possible
```

### Observability: PASS

**Can we inspect system state?**

| Capability | Status | Evidence |
|------------|--------|----------|
| State inspection | ✅ | Full state broadcast via WebSocket after each event |
| Logging standards | ✅ | HA native: `_LOGGER = logging.getLogger(__name__)` |
| Clear success/failure | ✅ | State machine phases explicit; error codes distinct |
| Error messages | ✅ | 8 standardized error codes with human-readable messages |

**Observable State (WebSocket Broadcast):**

```json
{
    "type": "state",
    "phase": "LOBBY|PLAYING|REVEAL|END",
    "round": 1,
    "total_rounds": 10,
    "deadline": 1734537600000,
    "players": [{"name": "Tom", "score": 15, "submitted": true, "streak": 2, "connected": true}],
    "song": {"artist": "Wham!", "title": "Wake Me Up", "album_art": "..."}
}
```

### Reliability: PASS

**Are tests isolated and reproducible?**

| Capability | Status | Evidence |
|------------|--------|----------|
| Test isolation | ✅ | In-memory state; no persistence; fresh GameState per test |
| Parallel-safe | ✅ | No shared database; each test creates own game instance |
| Cleanup discipline | ✅ | Fixtures with teardown documented in architecture |
| Reproducible failures | ✅ | Deterministic state machine; time injection; explicit transitions |

**Isolation Pattern (from architecture):**

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
```

---

## Architecturally Significant Requirements (ASRs)

### ASR Risk Matrix

| ASR ID | Requirement | Category | Probability | Impact | Score | Testing Approach |
|--------|-------------|----------|-------------|--------|-------|------------------|
| ASR-001 | WebSocket latency <200ms | PERF | 2 | 3 | 6 | Integration tests with timing assertions |
| ASR-002 | 20 concurrent players | PERF | 2 | 2 | 4 | Load test with multiple WS connections |
| ASR-003 | 99% game completion rate | BUS | 2 | 3 | 6 | E2E full game flow tests; error recovery |
| ASR-004 | 95% reconnection success | BUS | 2 | 2 | 4 | Integration tests for session recovery |
| ASR-005 | Page load <2 seconds | PERF | 2 | 2 | 4 | Lighthouse CI; static file size checks |
| ASR-006 | 60fps year selector | PERF | 1 | 1 | 1 | Manual testing; simple slider implementation |
| ASR-007 | Graceful degradation on MA failure | BUS | 2 | 3 | 6 | Integration tests with MA mock failures |
| ASR-008 | Admin disconnect → pause | BUS | 2 | 2 | 4 | E2E test for PAUSED state handling |

### High-Priority ASRs (Score ≥6)

1. **ASR-001 (WebSocket latency)**: Critical for real-time game feel
   - **Test Strategy**: Measure round-trip time for state broadcasts
   - **Tool**: Playwright with performance timings

2. **ASR-003 (Game completion)**: Core business value
   - **Test Strategy**: Full game flow E2E tests (LOBBY → END)
   - **Tool**: Playwright E2E

3. **ASR-007 (MA failure handling)**: Resilience requirement
   - **Test Strategy**: Mock MA unavailable mid-game
   - **Tool**: pytest with AsyncMock

---

## Test Levels Strategy

### Recommended Split

| Level | Percentage | Target Areas | Rationale |
|-------|------------|--------------|-----------|
| **Unit** | 35% | Scoring, state machine, playlist validation | Complex business logic; pure functions |
| **Integration** | 35% | WebSocket handlers, MA service calls, session management | Critical component boundaries |
| **E2E** | 30% | User journeys (join, play, reveal, admin controls) | Real user experience validation |

### Test Level Mapping

#### Unit Tests (35%)

| Component | Test Focus | Count Est. |
|-----------|-----------|------------|
| `game/scoring.py` | Accuracy, speed bonus, streak, bet calculations | 15-20 |
| `game/state.py` | State transitions, validation, timer logic | 10-15 |
| `game/playlist.py` | JSON loading, validation, song selection | 8-10 |
| `game/player.py` | Session creation, reconnection logic | 5-8 |
| `server/messages.py` | Message serialization, schema validation | 5-8 |

**Unit Test Characteristics:**
- Pure function testing (no external deps)
- Time injection for timer tests
- Edge cases: exact boundaries (±3 years, ±5 years)
- Fast execution (<5ms per test)

#### Integration Tests (35%)

| Component | Test Focus | Count Est. |
|-----------|-----------|------------|
| `server/websocket.py` | Join, submit, admin message handling | 12-15 |
| `services/music_assistant.py` | MA service calls, error handling | 8-10 |
| `services/media_player.py` | Volume control, playback commands | 5-8 |
| `config_flow.py` | MA detection, media player discovery | 5-8 |

**Integration Test Pattern:**

```python
@pytest.fixture
async def ws_client(aiohttp_client):
    """Test client for WebSocket handlers."""
    from custom_components.beatify.server.websocket import create_app
    app = create_app(mock_game_state)
    client = await aiohttp_client(app)
    async with client.ws_connect('/beatify/ws') as ws:
        yield ws

async def test_player_join(ws_client):
    await ws_client.send_json({"type": "join", "name": "Tom"})
    msg = await ws_client.receive_json()
    assert msg["type"] == "state"
    assert any(p["name"] == "Tom" for p in msg["players"])
```

#### E2E Tests (30%)

| Journey | Priority | Test Focus |
|---------|----------|-----------|
| Player join flow | P0 | QR scan → name entry → lobby |
| Full game round | P0 | Song plays → guess → reveal → score |
| Admin controls | P0 | Start, stop song, volume, end game |
| Late join | P1 | Mid-game entry, state sync |
| Reconnection | P1 | Disconnect → reconnect → state recovery |
| Error scenarios | P1 | MA unavailable, network errors |

**E2E Test Pattern:**

```typescript
// tests/e2e/player-join.spec.ts
import { test, expect } from '@playwright/test';

test('player can join game via QR code', async ({ page }) => {
  // Navigate to player page (simulating QR scan)
  await page.goto('/beatify/play?game=test-game-id');

  // Enter name
  await page.fill('[data-testid="player-name"]', 'Tom');
  await page.click('[data-testid="join-button"]');

  // Verify in lobby
  await expect(page.getByText('Tom')).toBeVisible();
  await expect(page.getByText('Waiting for game to start')).toBeVisible();
});
```

---

## NFR Testing Approach

### Security: INTENTIONALLY MINIMAL

**Design Principle:** Frictionless access (no auth by design)

| Test | Purpose | Tool |
|------|---------|------|
| No auth required for /beatify/play | Verify frictionless access | Playwright |
| No auth required for /beatify/ws | Verify WebSocket open access | pytest-aiohttp |
| No sensitive data in responses | Verify no player data leakage | Integration tests |

**Security Testing Note:** Beatify intentionally has NO security features. Tests verify the absence of barriers, not their presence.

### Performance: Playwright + Custom Metrics

| Metric | Target | Test Approach |
|--------|--------|---------------|
| Page load | <2s | Lighthouse CI in GitHub Actions |
| WebSocket latency | <200ms | Integration test timing assertions |
| Lobby update | <500ms | E2E test with performance.now() |
| Year selector | 60fps | Manual validation (simple range input) |

**Performance Test Pattern:**

```python
async def test_websocket_latency(ws_client):
    start = time.time()
    await ws_client.send_json({"type": "join", "name": "LatencyTest"})
    msg = await ws_client.receive_json()
    latency = (time.time() - start) * 1000

    assert msg["type"] == "state"
    assert latency < 200, f"WebSocket latency {latency}ms exceeds 200ms target"
```

### Reliability: E2E + Integration

| Scenario | Test Type | Validation |
|----------|-----------|------------|
| API 500 error → graceful message | Integration | Mock MA failure, verify error state |
| Admin disconnect → PAUSED | E2E | Close admin WS, verify "Waiting for admin" |
| Player reconnect → state restore | Integration | Disconnect/reconnect within 60s |
| Timer expiry → auto-reveal | Integration | Time injection, verify REVEAL transition |

**Reliability Test Pattern:**

```python
async def test_admin_disconnect_pauses_game(ws_admin, ws_player, game_state):
    # Start game
    await ws_admin.send_json({"type": "admin", "action": "start_game"})

    # Close admin connection
    await ws_admin.close()

    # Verify player sees pause
    msg = await ws_player.receive_json()
    assert msg["phase"] == "PAUSED"
    assert "Waiting for admin" in msg.get("message", "")
```

### Maintainability: CI Tools

| Metric | Target | Tool |
|--------|--------|------|
| Test coverage | ≥80% | pytest-cov |
| Code quality | No ruff errors | ruff (pre-configured in blueprint) |
| Type hints | All public APIs | mypy (optional) |

---

## Test Environment Requirements

### Local Development

| Component | Setup |
|-----------|-------|
| Python | 3.11+ (pytest, pytest-aiohttp, pytest-cov) |
| Home Assistant | DevContainer with HA instance (from integration_blueprint) |
| Music Assistant | Mocked via AsyncMock |
| Browser | Playwright with Chromium |

### CI/CD (GitHub Actions)

```yaml
# .github/workflows/ci.yml
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: pip install -r requirements_test.txt

      - name: Lint
        run: ruff check .

      - name: Unit & Integration Tests
        run: pytest tests/ --cov=custom_components/beatify --cov-report=xml

      - name: E2E Tests (Playwright)
        run: |
          npx playwright install
          npx playwright test tests/e2e/
```

---

## Testability Concerns

### Identified Concerns

| ID | Concern | Category | Severity | Mitigation |
|----|---------|----------|----------|------------|
| TC-001 | WebSocket testing requires careful async handling | TECH | Medium | Use `pytest-aiohttp` with explicit async fixtures |
| TC-002 | Real-time timer tests prone to flakiness | TECH | Medium | Time injection via `time_fn` (already designed-in) |
| TC-003 | MA service availability in tests | TECH | Low | AsyncMock pattern documented; no real MA needed |
| TC-004 | Mobile browser testing coverage | TECH | Low | Playwright mobile viewports; keep UI simple |

### No Blocking Concerns

All identified concerns have mitigations documented in the architecture. The testability review does not identify any **blockers** for implementation.

---

## Recommendations for Sprint 0

### Test Infrastructure Setup

1. **Create `tests/conftest.py`** with documented fixtures:
   - `game_state` (with time injection)
   - `mock_hass` (MagicMock)
   - `mock_ma_service` (AsyncMock)
   - `ws_client` (aiohttp test client)

2. **Configure pytest** in `pyproject.toml`:
   ```toml
   [tool.pytest.ini_options]
   testpaths = ["tests"]
   asyncio_mode = "auto"
   ```

3. **Set up Playwright** for E2E:
   ```bash
   npm init playwright@latest
   ```

4. **Add coverage reporting**:
   ```bash
   pip install pytest-cov
   pytest --cov=custom_components/beatify --cov-report=html
   ```

### First Tests to Write (Epic 1)

| Test | File | Priority |
|------|------|----------|
| GameState initialization | `test_game_state.py` | P0 |
| State transitions (LOBBY→PLAYING) | `test_game_state.py` | P0 |
| Scoring calculations | `test_scoring.py` | P0 |
| WebSocket join handler | `test_websocket.py` | P0 |
| MA service mock | `test_music_assistant.py` | P1 |

---

## Quality Gate Criteria

### Pre-Implementation Gate (This Review)

- [x] Controllability: PASS
- [x] Observability: PASS
- [x] Reliability: PASS
- [x] No blocking testability concerns
- [x] Test infrastructure recommendations documented

### Implementation Gate (Per Epic)

- [ ] Unit test coverage ≥80% for new code
- [ ] All P0 tests pass (100%)
- [ ] No ruff linting errors
- [ ] E2E smoke test green

---

## Document Metadata

**Workflow**: `_bmad/bmm/workflows/testarch/test-design`
**Mode**: System-Level (Phase 3)
**Generated by**: BMad TEA Agent (Murat)
**Version**: 4.0 (BMad v6)

---

_This document was generated as part of the BMAD methodology solutioning phase. It should be reviewed before sprint planning and updated as architecture evolves._
