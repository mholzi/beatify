# Story 1.2: HACS Installation & Integration Setup

Status: ready-for-dev

## Story

As a **Home Assistant admin**,
I want **to install Beatify via HACS and add it through Settings → Integrations**,
So that **Beatify is properly registered in my Home Assistant instance**.

## Acceptance Criteria

1. **Given** Beatify is available in HACS
   **When** admin installs via HACS and restarts Home Assistant
   **Then** Beatify appears in the HACS integration list as installed
   **And** no errors appear in Home Assistant logs

2. **Given** Beatify is installed via HACS
   **When** admin navigates to Settings → Devices & Services → Add Integration → searches "Beatify"
   **Then** Beatify appears in the integration list
   **And** admin can initiate the setup flow

3. **Given** admin initiates Beatify setup
   **When** the config flow completes successfully
   **Then** Beatify integration appears in the integrations dashboard
   **And** `hacs.json` contains valid metadata (name, documentation URL, domains)

## Tasks / Subtasks

- [ ] Task 1: Create/verify hacs.json metadata (AC: #1, #3)
  - [ ] 1.1: Ensure `hacs.json` exists in project root with required fields
  - [ ] 1.2: Set `"name": "Beatify"`
  - [ ] 1.3: Set `"homeassistant": "2025.11.0"` (minimum HA version)
  - [ ] 1.4: Set `"render_readme": true` for HACS UI
  - [ ] 1.5: Add documentation URL pointing to repository
  - [ ] 1.6: Verify `"domains": ["beatify"]` is set

- [ ] Task 2: Verify manifest.json HACS compatibility (AC: #1, #2)
  - [ ] 2.1: Confirm `"domain": "beatify"` matches hacs.json
  - [ ] 2.2: Confirm `"version": "0.0.1"` is valid semver
  - [ ] 2.3: Verify `"config_flow": true` for UI setup
  - [ ] 2.4: Verify `"after_dependencies": ["music_assistant"]` is present
  - [ ] 2.5: Ensure `"iot_class": "local_push"` is set

- [ ] Task 3: Create HACS installation documentation (AC: #1)
  - [ ] 3.1: Update README.md with HACS installation instructions
  - [ ] 3.2: Add manual installation instructions as fallback
  - [ ] 3.3: Document post-installation restart requirement
  - [ ] 3.4: Add troubleshooting section for common HACS issues

- [ ] Task 4: Verify config flow registration (AC: #2)
  - [ ] 4.1: Ensure `config_flow.py` has correct `DOMAIN` import
  - [ ] 4.2: Verify `ConfigFlow` class has `domain = DOMAIN`
  - [ ] 4.3: Confirm `async_step_user` method exists and returns form/create entry
  - [ ] 4.4: Verify `strings.json` / `translations/en.json` has config flow strings
  - [ ] 4.5: Add `await self.async_set_unique_id(DOMAIN)` and `self._abort_if_unique_id_configured()` to prevent duplicate entries

- [ ] Task 5: Test HACS installation flow (AC: #1, #2, #3)
  - [ ] 5.1: Add repository to HACS as custom repository (for testing)
  - [ ] 5.2: Install via HACS and verify download completes
  - [ ] 5.3: Restart Home Assistant
  - [ ] 5.4: Verify Beatify appears in integration search
  - [ ] 5.5: Complete config flow and verify integration appears in dashboard
  - [ ] 5.6: Check HA logs for any errors or warnings

## Dependencies

- **Story 1.1** (done): Project initialized from integration_blueprint with `custom_components/beatify/` structure

## Dev Notes

### Previous Story Context (Story 1.1)

Key learnings from Story 1.1 implementation:
- Template files cleaned up (removed api.py, coordinator.py, data.py, entity.py, sensor.py, binary_sensor.py, switch.py)
- `const.py` created with DOMAIN, game constants, and error codes
- `config_flow.py` skeleton exists with basic `async_step_user`
- Logging standardized to `_LOGGER = logging.getLogger(__name__)`
- All 69 unit tests passing

### HACS Requirements

From HACS documentation, a valid integration requires:

**hacs.json (project root):**
```json
{
  "name": "Beatify",
  "homeassistant": "2025.11.0",
  "render_readme": true,
  "domains": ["beatify"]
}
```

**Required manifest.json fields:**
```json
{
  "domain": "beatify",
  "name": "Beatify",
  "version": "0.0.1",
  "config_flow": true,
  "documentation": "https://github.com/<owner>/beatify",
  "codeowners": ["@<owner>"],
  "iot_class": "local_push",
  "after_dependencies": ["music_assistant"]
}
```

### Architecture Compliance

From [architecture.md - Starter Template Evaluation]:
- HACS compatibility is provided by integration_blueprint starter
- `after_dependencies: ["music_assistant"]` ensures MA loads before Beatify

From [architecture.md - Core Architectural Decisions]:
- MA is a required dependency (validated at setup time)
- Config flow validates MA presence (Story 1.3)

### Project Structure Notes

Current structure from Story 1.1:
```
custom_components/beatify/
├── __init__.py          # async_setup_entry, async_unload_entry
├── manifest.json        # HA integration metadata
├── const.py             # DOMAIN, constants
├── config_flow.py       # UI setup wizard (skeleton)
└── translations/
    └── en.json          # Config flow strings
```

This story ensures HACS metadata is correct; no new files needed.

### Config Flow Requirements

The config flow must:
1. Inherit from `ConfigFlow` with `domain = DOMAIN`
2. Implement `async_step_user` for initial setup
3. Return `self.async_create_entry()` on success
4. Have matching translation strings

```python
# config_flow.py structure
from homeassistant.config_entries import ConfigFlow
from .const import DOMAIN

class BeatifyConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input=None):
        # MA detection will be added in Story 1.3
        if user_input is not None:
            return self.async_create_entry(title="Beatify", data={})
        return self.async_show_form(step_id="user")
```

### HACS Installation Process

1. User opens HACS in HA sidebar
2. Goes to Integrations tab
3. Clicks "Explore & Download Repositories" (or adds custom repo)
4. Searches for "Beatify"
5. Clicks Download
6. Restarts Home Assistant
7. Goes to Settings → Devices & Services → Add Integration
8. Searches "Beatify" and initiates setup

### Testing This Story

**Manual HACS Testing:**
1. Push code to GitHub repository
2. Add as custom repository in HACS: Settings → Custom repositories
3. Enter repository URL, select "Integration" category
4. Install and restart HA
5. Verify integration appears in Settings

**Validation checklist:**
- [ ] hacs.json passes HACS validation
- [ ] manifest.json valid according to HA specs
- [ ] Config flow appears in UI
- [ ] No errors in HA logs after install/restart
- [ ] Integration creates entry successfully

### References

- [Source: _bmad-output/architecture.md#Starter-Template-Evaluation]
- [Source: _bmad-output/architecture.md#Core-Architectural-Decisions]
- [Source: _bmad-output/epics.md#Story-1.2]
- [Source: _bmad-output/project-context.md#Home-Assistant-Integration]
- [HACS Developer Documentation](https://hacs.xyz/docs/developer/start)

---

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

### File List

