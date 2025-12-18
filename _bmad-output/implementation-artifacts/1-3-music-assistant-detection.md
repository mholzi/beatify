# Story 1.3: Music Assistant Detection

Status: ready-for-dev

## Story

As a **Home Assistant admin**,
I want **Beatify to detect if Music Assistant is installed and configured**,
So that **I know immediately if a required dependency is missing**.

## Acceptance Criteria

1. **Given** Music Assistant integration is installed and configured in HA
   **When** Beatify config flow runs
   **Then** Music Assistant is detected as available
   **And** setup proceeds to the next step

2. **Given** Music Assistant integration is NOT installed
   **When** Beatify config flow runs
   **Then** an error message displays: "Music Assistant not found. Beatify requires Music Assistant to play songs."
   **And** a link to the Music Assistant setup guide is provided
   **And** setup is blocked until MA is configured (FR54)

3. **Given** Music Assistant is installed but not properly configured
   **When** Beatify attempts to detect MA
   **Then** appropriate error message displays with troubleshooting guidance

## Tasks / Subtasks

- [ ] Task 1: Implement MA detection logic (AC: #1, #2)
  - [ ] 1.1: Create helper function `async_is_music_assistant_configured(hass)` in config_flow.py
  - [ ] 1.2: Check if `music_assistant` domain exists in `hass.data`
  - [ ] 1.3: Alternatively check `hass.config_entries.async_entries("music_assistant")`
  - [ ] 1.4: Return True only if MA is fully configured and loaded

- [ ] Task 2: Update config flow to check MA (AC: #1, #2, #3)
  - [ ] 2.1: Call MA detection in `async_step_user`
  - [ ] 2.2: If MA detected, proceed to create entry
  - [ ] 2.3: If MA NOT detected, return error form with `errors={"base": "ma_not_found"}`
  - [ ] 2.4: Add retry mechanism - user can check MA status and retry

- [ ] Task 3: Add error messages to translations (AC: #2, #3)
  - [ ] 3.1: Add `"ma_not_found"` error string to `translations/en.json`
  - [ ] 3.2: Include helpful message: "Music Assistant not found. Please install and configure Music Assistant first."
  - [ ] 3.3: Add `"ma_not_configured"` for partial setup scenarios
  - [ ] 3.4: Include link text for MA setup guide

- [ ] Task 4: Add MA setup guide link (AC: #2)
  - [ ] 4.1: Add `MA_SETUP_URL` constant to const.py
  - [ ] 4.2: Include URL in error message or as separate description
  - [ ] 4.3: URL should point to Music Assistant documentation

- [ ] Task 5: Handle edge cases (AC: #3)
  - [ ] 5.1: Handle MA installed but integration loading
  - [ ] 5.2: Handle MA installed but in error state
  - [ ] 5.3: Log detection results for debugging: `_LOGGER.debug("MA detection: %s", result)`

- [ ] Task 6: Write unit tests for MA detection (AC: #1, #2, #3)
  - [ ] 6.1: Test MA detected successfully (mock hass.config_entries)
  - [ ] 6.2: Test MA not installed (empty entries)
  - [ ] 6.3: Test MA installed but not loaded
  - [ ] 6.4: Test config flow shows error when MA missing
  - [ ] 6.5: Test config flow proceeds when MA present

## Dependencies

- **Story 1.1** (done): Project scaffold with `config_flow.py` skeleton
- **Story 1.2** (ready): HACS metadata and config flow registration

## Dev Notes

### Important: ConfigEntryState Import

**HA 2023.8+ required import:**
```python
from homeassistant.config_entries import ConfigEntryState
```

Do NOT use the deprecated `from homeassistant.config_entries import ENTRY_STATE_LOADED`.

### Music Assistant Detection Strategy

From [architecture.md - Music Assistant Integration]:
- MA is a **required** dependency
- Config flow must validate MA presence at setup
- Beatify won't function without MA for playback

**Detection Methods (in order of reliability):**

```python
# Method 1: Check config entries (most reliable)
async def async_is_music_assistant_configured(hass: HomeAssistant) -> bool:
    """Check if Music Assistant is installed and configured."""
    entries = hass.config_entries.async_entries("music_assistant")
    return any(entry.state == ConfigEntryState.LOADED for entry in entries)
```

```python
# Method 2: Check hass.data (quick but less reliable)
def is_ma_available(hass: HomeAssistant) -> bool:
    return "music_assistant" in hass.data
```

**Recommended: Use Method 1** - checks both installation and loaded state.

### Architecture Compliance

From [architecture.md - Core Architectural Decisions #3]:
- MA Integration: Required at setup, graceful runtime
- Config flow validates MA presence
- Runtime: If MA unavailable, pause game (handled in later stories)

From [project-context.md - Critical Implementation Rules]:
```python
# MA service calls pattern
await hass.services.async_call(
    "music_assistant",
    "play_media",
    {"entity_id": media_player_entity, "media_id": song_uri, ...}
)
```

### Config Flow Pattern

```python
# config_flow.py
from homeassistant.config_entries import ConfigEntry, ConfigEntryState, ConfigFlow
from .const import DOMAIN, MA_SETUP_URL

class BeatifyConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle initial step."""
        errors = {}

        # Check Music Assistant
        if not await self._async_is_ma_configured():
            errors["base"] = "ma_not_found"
            return self.async_show_form(
                step_id="user",
                errors=errors,
                description_placeholders={"ma_url": MA_SETUP_URL}
            )

        if user_input is not None:
            return self.async_create_entry(title="Beatify", data={})

        return self.async_show_form(step_id="user")

    async def _async_is_ma_configured(self) -> bool:
        """Check if Music Assistant is configured and loaded."""
        entries = self.hass.config_entries.async_entries("music_assistant")
        return any(
            entry.state == ConfigEntryState.LOADED
            for entry in entries
        )
```

### Translation Strings

```json
{
  "config": {
    "step": {
      "user": {
        "title": "Set up Beatify",
        "description": "Beatify is a party game that plays songs through Music Assistant.",
        "data": {}
      }
    },
    "error": {
      "ma_not_found": "Music Assistant not found. Please install and configure Music Assistant first. [Setup Guide]({ma_url})",
      "ma_not_configured": "Music Assistant is installed but not fully configured. Please complete Music Assistant setup first."
    },
    "abort": {
      "already_configured": "Beatify is already configured"
    }
  }
}
```

### Constants to Add

```python
# const.py additions
MA_SETUP_URL = "https://music-assistant.io/getting-started/"
```

### Import Order (Python - PEP 8)

```python
# config_flow.py
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigEntryState, ConfigFlow
from homeassistant.core import HomeAssistant

from .const import DOMAIN, MA_SETUP_URL

_LOGGER = logging.getLogger(__name__)
```

### Project Structure Notes

Files modified in this story:
```
custom_components/beatify/
├── const.py             # Add MA_SETUP_URL
├── config_flow.py       # Add MA detection logic
└── translations/
    └── en.json          # Add error messages

tests/
└── unit/
    └── test_config_flow.py  # Add MA detection tests
```

### Error Handling Strategy

From [architecture.md - Error Codes]:
- `ERR_MA_UNAVAILABLE = "MA_UNAVAILABLE"` - for runtime errors
- Config flow uses translation strings for user-facing errors

**Error scenarios:**
1. MA not installed → Show "ma_not_found" error with setup link
2. MA installed but loading → Wait or show "loading" message
3. MA in error state → Show "ma_not_configured" error
4. MA loaded → Proceed with setup

### Testing This Story

**Unit Tests:**
```python
# tests/unit/test_config_flow.py

async def test_ma_detected_successfully(hass, mock_ma_entry):
    """Test config flow when MA is configured."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] == "form"  # Shows form, no errors
    assert result.get("errors") is None

async def test_ma_not_found(hass):
    """Test config flow when MA is not installed."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["type"] == "form"
    assert result["errors"]["base"] == "ma_not_found"

async def test_ma_not_loaded(hass, mock_ma_entry_not_loaded):
    """Test config flow when MA is installed but not loaded."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}
    )
    assert result["errors"]["base"] == "ma_not_found"
```

**Manual Testing:**
1. Remove MA integration from HA
2. Try to add Beatify integration
3. Verify error message appears with link
4. Add MA integration back
5. Try to add Beatify again
6. Verify setup proceeds

### References

- [Source: _bmad-output/architecture.md#Music-Assistant-Integration]
- [Source: _bmad-output/architecture.md#Core-Architectural-Decisions]
- [Source: _bmad-output/project-context.md#Music-Assistant-Service-Calls]
- [Source: _bmad-output/epics.md#Story-1.3]
- [Source: _bmad-output/epics.md#FR54] (MA not configured error handling)

---

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

### File List

