# ATDD Checklist - Epic 1: Project Foundation & HA Integration

**Epic ID:** Epic 1
**Date:** 2025-12-18
**Author:** Markusholzhaeuser (TEA: Murat)
**Status:** RED PHASE - Tests Written, Awaiting Implementation

---

## Executive Summary

This document provides the Acceptance Test-Driven Development (ATDD) checklist for Epic 1. All tests have been written and are in the **RED phase** (failing). Implementation should follow the red-green-refactor cycle.

**Test Statistics:**
- Unit Tests: 10 tests in `test_manifest.py`
- Integration Tests: 15 tests in `test_config_flow.py`
- E2E Tests: 7 tests in `test_admin_page.py`
- **Total: 32 failing tests**

---

## Story Summary

| Story | Title | Test File | Test Count |
|-------|-------|-----------|------------|
| 1.1 | Initialize Project from Starter Template | `test_manifest.py` | 10 |
| 1.2 | HACS Installation & Integration Setup | `test_config_flow.py` | 3 |
| 1.3 | Music Assistant Detection | `test_config_flow.py` | 3 |
| 1.4 | Media Player & Playlist Discovery | `test_config_flow.py` | 9 |
| 1.5 | Admin Page Access | `test_admin_page.py` | 7 |

---

## Red-Green-Refactor Workflow

### RED Phase (Complete)

- [x] All acceptance criteria analyzed
- [x] Tests written in Given-When-Then format
- [x] Tests organized by story
- [x] Tests fail due to missing implementation
- [x] Required `data-testid` attributes documented

### GREEN Phase (DEV Team)

1. Pick one failing test
2. Implement minimal code to make it pass
3. Run test to verify green
4. Move to next test
5. Repeat until all tests pass

### REFACTOR Phase (DEV Team)

1. All tests passing (green)
2. Improve code quality
3. Extract duplications
4. Optimize performance
5. Ensure tests still pass

---

## Implementation Checklist

### Story 1.1: Initialize Project from Starter Template

**Tests:** `tests/unit/test_manifest.py`

#### Task 1.1.1: Clone integration_blueprint
- [ ] Clone `ludeeus/integration_blueprint` repository
- [ ] Rename to `beatify`
- [ ] Update all references from blueprint to beatify
- [ ] Run test: `pytest tests/unit/test_manifest.py::TestProjectStructure -v`
- [ ] All structure tests pass

#### Task 1.1.2: Configure manifest.json
- [ ] Set `domain` to "beatify"
- [ ] Set `version` to "0.0.1"
- [ ] Set `config_flow` to `true`
- [ ] Add `codeowners`
- [ ] Run test: `pytest tests/unit/test_manifest.py::TestManifestContent -v`
- [ ] All manifest tests pass

#### Task 1.1.3: Configure const.py
- [ ] Set `DOMAIN = "beatify"`
- [ ] Run test: `pytest tests/unit/test_manifest.py::TestConstContent -v`
- [ ] Test passes

#### Task 1.1.4: Code Quality
- [ ] Install ruff: `pip install ruff`
- [ ] Run: `ruff check custom_components/beatify/`
- [ ] Fix any linting errors
- [ ] Run test: `pytest tests/unit/test_manifest.py::TestCodeQuality -v`
- [ ] Test passes

---

### Story 1.2: HACS Installation & Integration Setup

**Tests:** `tests/integration/test_config_flow.py::TestHACSMetadata`, `TestConfigFlowSetup`

#### Task 1.2.1: Create hacs.json
- [ ] Create `hacs.json` in project root
- [ ] Set `name` to "Beatify"
- [ ] Add `documentation` URL
- [ ] Run test: `pytest tests/integration/test_config_flow.py::TestHACSMetadata -v`
- [ ] All HACS tests pass

#### Task 1.2.2: Implement Config Flow Skeleton
- [ ] Create `BeatifyConfigFlow` class in `config_flow.py`
- [ ] Implement `async_step_user` method
- [ ] Register config flow in manifest.json
- [ ] Remove `@pytest.mark.skip` from config flow tests
- [ ] Run test: `pytest tests/integration/test_config_flow.py::TestConfigFlowSetup -v`
- [ ] Config flow tests pass

---

### Story 1.3: Music Assistant Detection

**Tests:** `tests/integration/test_config_flow.py::TestMusicAssistantDetection`

#### Task 1.3.1: Implement MA Detection Function
- [ ] Create `detect_music_assistant(hass)` function
- [ ] Check `hass.data` for "music_assistant" key
- [ ] Return `True` if MA is configured, `False` otherwise
- [ ] Remove `@pytest.mark.skip` from MA detection tests
- [ ] Run test: `pytest tests/integration/test_config_flow.py::TestMusicAssistantDetection -v`
- [ ] Detection tests pass

#### Task 1.3.2: Implement MA Error Message
- [ ] Create `get_ma_error_message()` function
- [ ] Include "Music Assistant not found" text
- [ ] Include link to MA setup guide
- [ ] Error message test passes

---

### Story 1.4: Media Player & Playlist Discovery

**Tests:** `tests/integration/test_config_flow.py::TestMediaPlayerDiscovery`, `TestPlaylistDiscovery`

#### Task 1.4.1: Implement Media Player Discovery
- [ ] Create `discover_media_players(hass)` function
- [ ] Query `hass.states.async_all()` for `media_player.*` entities
- [ ] Return list with `entity_id`, `friendly_name`, `state`
- [ ] Remove `@pytest.mark.skip` from media player tests
- [ ] Run test: `pytest tests/integration/test_config_flow.py::TestMediaPlayerDiscovery -v`
- [ ] Media player tests pass

#### Task 1.4.2: Implement Playlist Directory Setup
- [ ] Create `ensure_playlist_directory(config_path)` function
- [ ] Create `{config}/beatify/playlists/` if missing
- [ ] Remove `@pytest.mark.skip` from directory test
- [ ] Test passes

#### Task 1.4.3: Implement Playlist Discovery
- [ ] Create `discover_playlists(playlist_dir)` function
- [ ] Scan for `*.json` files
- [ ] Parse and extract `name`, `song_count`
- [ ] Return list of playlist metadata
- [ ] Remove `@pytest.mark.skip` from discovery tests
- [ ] Tests pass

#### Task 1.4.4: Implement Playlist Validation
- [ ] Create `validate_playlist(playlist_path)` function
- [ ] Check required fields: `name`, `songs`
- [ ] Check each song has: `year` (int), `uri` (string)
- [ ] Return validation result with errors
- [ ] Remove `@pytest.mark.skip` from validation tests
- [ ] Tests pass

---

### Story 1.5: Admin Page Access

**Tests:** `tests/e2e/test_admin_page.py`

#### Task 1.5.1: Create Admin Page HTML
- [ ] Create `/beatify/admin` route (no auth required)
- [ ] Create `www/admin.html` template
- [ ] Include basic structure
- [ ] Remove `@pytest.mark.skip` from access tests
- [ ] Run test: `pytest tests/e2e/test_admin_page.py::TestAdminPageAccess -v`
- [ ] Page loads without auth

#### Task 1.5.2: Add Required data-testid Attributes
- [ ] Add `data-testid="media-player-select"` to media player selector
- [ ] Add `data-testid="playlist-select"` to playlist area
- [ ] Add `data-testid="ma-status"` to MA status indicator
- [ ] Add `data-testid="ma-error"` to MA error message
- [ ] Remove `@pytest.mark.skip` from content tests
- [ ] Run test: `pytest tests/e2e/test_admin_page.py::TestAdminPageContent -v`
- [ ] Content tests pass

#### Task 1.5.3: Mobile Responsive Design
- [ ] Ensure no horizontal scroll on mobile viewports
- [ ] Ensure all buttons/inputs are minimum 44x44px
- [ ] Test on mobile viewport (390x844)
- [ ] Remove `@pytest.mark.skip` from mobile tests
- [ ] Run test: `pytest tests/e2e/test_admin_page.py::TestAdminPageMobileResponsive -v`
- [ ] Mobile tests pass

---

## Required data-testid Attributes

### Admin Page (/beatify/admin)

| Attribute | Element | Story |
|-----------|---------|-------|
| `media-player-select` | Media player dropdown/selector | 1.5 |
| `playlist-select` | Playlist checkbox area | 1.5 |
| `ma-status` | Music Assistant status indicator | 1.5 |
| `ma-error` | Music Assistant error message | 1.5 |
| `start-game-button` | Start game button | 2.3 (future) |

---

## Mock Requirements

### Music Assistant Mock

The integration tests use mocked Music Assistant:

```python
# Mock HA instance WITH Music Assistant
mock_hass.data = {
    "music_assistant": {
        "server": AsyncMock(),
    }
}

# Mock HA instance WITHOUT Music Assistant
mock_hass.data = {}
```

### Media Player Mock

```python
mock_hass.states.async_all.return_value = [
    MagicMock(
        entity_id="media_player.living_room",
        state="idle",
        attributes={"friendly_name": "Living Room Speaker"},
    ),
]
```

---

## Running Tests

```bash
# Run all Epic 1 tests (expect failures initially)
pytest tests/unit/test_manifest.py tests/integration/test_config_flow.py -v

# Run specific story tests
pytest tests/unit/test_manifest.py -v                    # Story 1.1
pytest tests/integration/test_config_flow.py -v          # Stories 1.2-1.4
pytest tests/e2e/test_admin_page.py -v                   # Story 1.5

# Run with markers
pytest -m unit -v       # Unit tests only
pytest -m integration   # Integration tests only
pytest -m e2e           # E2E tests only (requires Playwright)

# Debug specific test
pytest tests/unit/test_manifest.py::TestProjectStructure::test_custom_components_directory_exists -v
```

---

## Definition of Done

Epic 1 is complete when:

- [ ] All 32 tests pass (GREEN phase)
- [ ] Code coverage ≥80% for new files
- [ ] No ruff linting errors
- [ ] `custom_components/beatify/` loads in HA without errors
- [ ] Admin page accessible at `/beatify/admin`
- [ ] MA status correctly detected
- [ ] Media players and playlists listed on admin page

---

## Knowledge Base References

Patterns applied from TEA Knowledge Base:
- `fixture-architecture.md` - Mock fixtures for HA and MA
- `data-factories.md` - Test data generation (minimal for Epic 1)
- `test-quality.md` - Given-When-Then structure, one assertion per test
- `selector-resilience.md` - data-testid attributes for E2E tests

---

## Next Steps

After Epic 1 passes:
1. Run `*atdd` for Epic 2 (Game Session Creation)
2. Run `*ci` to set up GitHub Actions pipeline
3. Proceed to sprint planning

---

**Document Generated by:** BMad TEA Agent (Murat)
**Workflow:** `_bmad/bmm/workflows/testarch/atdd`
**Mode:** AI Generation (standard patterns)
