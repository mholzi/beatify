# Beatify Test Suite

Test framework for the Beatify Home Assistant party game integration.

## Quick Start

```bash
# Install dependencies
pip install pytest pytest-asyncio pytest-aiohttp pytest-cov ruff

# Run all tests
pytest

# Run with coverage
pytest --cov=custom_components/beatify --cov-report=html

# Run specific test types
pytest -m unit          # Fast unit tests only
pytest -m integration   # WebSocket/service tests
pytest -m e2e          # Browser tests (requires Playwright)
```

## Directory Structure

```
tests/
├── conftest.py              # Shared fixtures (game_state, mocks, etc.)
├── unit/                    # Unit tests (fast, no external deps)
│   ├── test_scoring.py      # Scoring logic tests
│   └── test_game_state.py   # State machine tests
├── integration/             # Integration tests (WebSocket, MA service)
│   └── test_websocket.py    # WebSocket handler tests
├── e2e/                     # End-to-end browser tests
│   └── (Playwright tests)
└── support/                 # Test infrastructure
    ├── fixtures/            # Custom pytest fixtures
    ├── factories/           # Data factories
    │   ├── __init__.py
    │   ├── player_factory.py
    │   └── song_factory.py
    └── helpers/             # Utility functions
```

## Test Types

### Unit Tests (`pytest -m unit`)

Fast, isolated tests for pure business logic:
- Scoring calculations
- State machine transitions
- Data validation

**Characteristics:**
- No external dependencies
- Run in <1ms each
- Use time injection for determinism

### Integration Tests (`pytest -m integration`)

Tests for component boundaries:
- WebSocket message handling
- Music Assistant service calls
- Home Assistant entity interactions

**Characteristics:**
- Use mocked external services
- Test async behavior with `pytest-asyncio`
- Verify error handling and edge cases

### E2E Tests (`pytest -m e2e`)

Browser tests for user journeys:
- Player join flow
- Full game round
- Admin controls

**Characteristics:**
- Require Playwright
- Test real browser behavior
- Validate mobile responsiveness

## Fixtures

### Core Fixtures (conftest.py)

| Fixture | Description |
|---------|-------------|
| `game_state` | Fresh GameState with frozen time |
| `frozen_time` | Fixed timestamp (1000.0) |
| `time_fn` | Time function for injection |
| `mock_hass` | Mocked Home Assistant instance |
| `mock_ma_service` | Mocked Music Assistant API |
| `mock_media_player` | Mocked HA media player entity |

### Usage Example

```python
import pytest
from tests.support.factories import create_player, create_song

@pytest.mark.unit
def test_exact_match_scoring(game_state):
    """Test scoring for exact year match."""
    # Arrange
    player = create_player(name="Alice")
    song = create_song(year=1984)

    # Act
    game_state.add_player(player.name, player.session_id)
    result = calculate_score(guess=1984, correct_year=song.year, ...)

    # Assert
    assert result["base"] == 20
    assert result["accuracy"] == "exact"
```

## Factories

### Player Factory

```python
from tests.support.factories import create_player, create_admin

# Default player (unique session_id, name)
player = create_player()

# With overrides
alice = create_player(name="Alice", score=50)

# Admin player
admin = create_admin()

# Player with submitted guess
guesser = create_player_with_guess(year=1985, bet=True)
```

### Song Factory

```python
from tests.support.factories import create_song, create_playlist

# Default song
song = create_song()

# Specific song
xmas = create_song(title="Last Christmas", artist="Wham!", year=1984)

# Playlist for testing
songs = create_playlist(count=10)
```

## Time Control

Beatify tests use time injection for deterministic timer tests:

```python
def test_timer_expiry(game_state, frozen_time):
    """Timer should use injected time function."""
    # Time is frozen at 1000.0
    assert game_state._now() == frozen_time

    # Time remains constant during test
    game_state.start_game()
    assert game_state._now() == 1000.0  # Still frozen
```

## WebSocket Testing

Integration tests use `pytest-aiohttp` for WebSocket testing:

```python
@pytest.mark.integration
async def test_player_join(ws_client):
    """Player can join via WebSocket."""
    async with ws_client.ws_connect('/beatify/ws') as ws:
        await ws.send_json({"type": "join", "name": "Alice"})
        msg = await ws.receive_json()

        assert msg["type"] == "state"
        assert any(p["name"] == "Alice" for p in msg["players"])
```

## Coverage

Target: **80% coverage** on `custom_components/beatify/`

```bash
# Generate HTML coverage report
pytest --cov=custom_components/beatify --cov-report=html

# View report
open htmlcov/index.html
```

### Coverage Exclusions (pyproject.toml)

- `# pragma: no cover` comments
- `__repr__` methods
- `NotImplementedError` raises
- `TYPE_CHECKING` blocks

## Markers

| Marker | Description |
|--------|-------------|
| `@pytest.mark.unit` | Fast unit tests |
| `@pytest.mark.integration` | Component integration tests |
| `@pytest.mark.e2e` | Browser end-to-end tests |
| `@pytest.mark.slow` | Tests taking >5 seconds |

## Best Practices

### Test Quality (from TEA Knowledge Base)

1. **Deterministic**: No `time.sleep()`, use `frozen_time` fixture
2. **Isolated**: Each test creates own data via factories
3. **Explicit**: Assertions visible in test body, not hidden in helpers
4. **Focused**: <300 lines per test file
5. **Fast**: <1.5 minutes per test

### Naming Convention

```
test_{component}_{scenario}_{expected_result}
```

Examples:
- `test_scoring_exact_match_awards_20_points`
- `test_game_state_start_without_players_raises_error`
- `test_websocket_join_creates_session`

### Test Structure (Given-When-Then)

```python
def test_exact_match_scoring():
    # Given (Arrange)
    player = create_player()
    song = create_song(year=1984)

    # When (Act)
    result = calculate_score(guess=1984, correct_year=1984, ...)

    # Then (Assert)
    assert result["base"] == 20
    assert result["accuracy"] == "exact"
```

## CI Integration

Tests run in GitHub Actions on every push:

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

      - name: Test
        run: pytest --cov=custom_components/beatify --cov-report=xml

      - name: Upload coverage
        uses: codecov/codecov-action@v4
```

## Troubleshooting

### Common Issues

**ImportError: No module named 'custom_components'**
```bash
# Add project root to PYTHONPATH
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
```

**Async test not running**
```bash
# Ensure pytest-asyncio is installed
pip install pytest-asyncio
```

**Coverage below threshold**
```bash
# Check which lines are uncovered
pytest --cov=custom_components/beatify --cov-report=term-missing
```

## Knowledge Base References

This test framework follows patterns from:
- `_bmad/bmm/testarch/knowledge/fixture-architecture.md`
- `_bmad/bmm/testarch/knowledge/data-factories.md`
- `_bmad/bmm/testarch/knowledge/test-quality.md`

---

**Framework:** pytest + pytest-asyncio + pytest-aiohttp
**Generated by:** BMad TEA Agent (Murat)
**Date:** 2025-12-18
