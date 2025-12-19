# Sprint Change Proposal

**Project:** Beatify
**Date:** 2025-12-19
**Author:** Bob (Scrum Master)
**Status:** Pending Approval

---

## 1. Issue Summary

### Problem Statement

Beatify was designed with Music Assistant as a required dependency for:
1. Playing music tracks (via `music_assistant.play_media` service)
2. Fetching track metadata (artist, title, album art) at runtime

However, Music Assistant is **not available** on the target Home Assistant instance, and analysis shows it's **unnecessary**—direct `media_player` entity control can accomplish the same goals more simply.

### Discovery Context

- **When discovered:** During implementation phase, after Epic 2 completion, before Epic 4
- **Trigger:** User realization that MA is unavailable and not needed
- **Category:** Strategic pivot / simplification

### Evidence

- Music Assistant integration not installed on target HA instance
- Direct `media_player` entities can play URIs via `media_player.play_media` service
- Media player entities expose `media_artist`, `media_title`, `entity_picture` attributes

---

## 2. Impact Analysis

### Epic Impact

| Epic | Status | Impact Level | Details |
|------|--------|--------------|---------|
| Epic 1 | DONE | Medium | Story 1.3 implementation needs modification (MA detection → media_player validation) |
| Epic 2 | DONE | Low | Playlist validation may need minor updates |
| Epic 3 | IN PROGRESS | None | No MA dependencies, continue as planned |
| Epic 4 | BACKLOG | High | Story 4.1 and 4.2 need rewriting before implementation |
| Epic 5 | BACKLOG | None | Scoring system unaffected |
| Epic 6 | BACKLOG | None | Admin controls unaffected |
| Epic 7 | BACKLOG | None | Resilience/recovery unaffected |

### Story Impact

| Story | Current State | Required Change |
|-------|---------------|-----------------|
| 1.3 Music Assistant Detection | DONE | Modify code: Remove MA detection, add media_player entity validation |
| 4.1 Song Playback via Music Assistant | BACKLOG | Rewrite: Change to "Song Playback via Media Player" |
| 4.2 Round Display (Album Cover & Timer) | BACKLOG | Update: Source metadata from media_player attributes |

### Artifact Conflicts

**PRD Updates Required:**
- FR3: Remove "detect Music Assistant installation status"
- FR22: Change "via Music Assistant" to "via media_player service"
- FR54: Remove MA error handling requirement
- NFR13: Remove "Music Assistant required"
- Journey 6 (Marcus): Update error scenarios
- Integration section: Remove Music Assistant dependency table

**Architecture Updates Required:**
- Technology Stack: Remove "Music Assistant 2.4+"
- Technical Constraints: Remove MA dependency
- Core Decision #3: Replace MA integration with media_player validation
- Playlist Data Format: "Metadata fetched from media_player attributes"
- Project Structure: Remove `services/music_assistant.py`, expand `media_player.py`
- Component Diagram: Remove MA as external dependency
- Data Flow: Route through `media_player.py` only

**Code Updates Required:**
- `const.py`: Remove `ERR_MA_UNAVAILABLE` error code
- `manifest.json`: Remove `after_dependencies: ["music_assistant"]`
- `config_flow.py`: Remove MA detection step
- `project-context.md`: Update all MA references

---

## 3. Recommended Approach

### Selected Path: Direct Adjustment

Modify existing stories and artifacts without rollback or MVP scope reduction.

### Rationale

1. **Low effort** - Most affected stories (4.1, 4.2) are still in backlog
2. **Low risk** - Simplifying architecture, not adding complexity
3. **Positive MVP impact** - Removes a dependency, easier installation for users
4. **No timeline impact** - Epic 3 continues unaffected
5. **Clean design** - Hybrid metadata strategy works well

### Metadata Strategy: Hybrid

| Source | Data |
|--------|------|
| **Playlist JSON** | `year` (required for scoring), `uri`, `fun_fact` (curated content) |
| **Media Player** | `media_artist`, `media_title`, `entity_picture` (runtime display) |

This approach:
- Keeps game-critical data (year) in curated playlists
- Reduces playlist maintenance burden
- Works with any media player that exposes standard attributes
- Falls back to `no-artwork.svg` when artwork unavailable

### Alternatives Considered

| Option | Verdict | Reason |
|--------|---------|--------|
| Rollback Story 1.3 | Rejected | Modification is simpler than rollback + reimplementation |
| Reduce MVP scope | Not needed | This change simplifies MVP, doesn't threaten it |
| Keep MA optional | Rejected | Adds complexity for no benefit |

---

## 4. Detailed Change Proposals

### Change 1: Story 1.3 Implementation Update

**File:** `custom_components/beatify/config_flow.py`

**OLD Behavior:**
- Detect Music Assistant integration
- Block setup if MA not found
- Show error with MA setup guide link

**NEW Behavior:**
- Validate at least one `media_player` entity exists
- Warn if no media players available
- No MA dependency check

---

### Change 2: Story 4.1 Rewrite

**OLD Title:** Song Playback via Music Assistant

**NEW Title:** Song Playback via Media Player

**NEW Acceptance Criteria:**

**Given** game transitions to PLAYING state for a new round
**When** round starts
**Then** the selected song plays through the configured HA media player via `media_player.play_media` service
**And** playback begins within 1 second of round start

**Given** song is playing
**When** media_player receives the play command
**Then** `media_player.play_media` service is called with:
- `entity_id`: selected media player
- `media_content_id`: song URI from playlist
- `media_content_type`: "music"

**Given** song URI is invalid or unavailable
**When** playback fails
**Then** system marks song as played and skips to next
**And** logs warning for host review

---

### Change 3: Story 4.2 Metadata Update

**OLD:** Album art fetched from Music Assistant metadata

**NEW:** Album art fetched from media_player entity attributes

**Implementation:**
```python
# After playback starts, read from media_player state
state = hass.states.get(media_player_entity)
artist = state.attributes.get("media_artist", "Unknown Artist")
title = state.attributes.get("media_title", "Unknown Title")
artwork = state.attributes.get("entity_picture", "/beatify/static/img/no-artwork.svg")
```

---

### Change 4: PRD Functional Requirements

**FR3 - REMOVE:**
```
OLD: System can detect Music Assistant installation status
NEW: (Remove this requirement entirely)
```

**FR22 - MODIFY:**
```
OLD: System can play song audio through selected HA media player via Music Assistant
NEW: System can play song audio through selected HA media player
```

**FR54 - REMOVE:**
```
OLD: System can display error when Music Assistant not configured
NEW: (Remove this requirement entirely)
```

---

### Change 5: Architecture Document

**Technology Stack - REMOVE:**
```
OLD: | Music Assistant | 2.4+ | Required dependency |
NEW: (Remove row entirely)
```

**Core Decision #3 - REPLACE:**
```
OLD: MA Integration - Required at setup, graceful runtime
NEW: Media Player Integration - Validate entities at setup, direct service calls
```

**Project Structure - UPDATE:**
```
OLD:
├── services/
│   ├── music_assistant.py      # MA service calls
│   └── media_player.py         # Volume, playback control

NEW:
├── services/
│   └── media_player.py         # Playback, volume, metadata
```

---

### Change 6: project-context.md Updates

**Music Assistant Service Calls - REPLACE:**
```python
# OLD
await hass.services.async_call(
    "music_assistant",
    "play_media",
    {"entity_id": media_player_entity, "media_id": song_uri, ...}
)

# NEW
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

**Error Codes - REMOVE:**
```
OLD: ERR_MA_UNAVAILABLE = "MA_UNAVAILABLE"
NEW: (Remove this constant)
```

---

## 5. Implementation Handoff

### Change Scope Classification: Minor-to-Moderate

Most changes are documentation/story updates. Only Story 1.3 requires code modification of already-implemented functionality.

### Handoff Recipients

| Role | Responsibilities |
|------|------------------|
| **Scrum Master** | Update epics.md story descriptions, coordinate artifact updates |
| **Architect** | Review and approve Architecture document changes |
| **Dev Agent** | Modify Story 1.3 code, implement Epic 4 with new approach |

### Implementation Sequence

1. **SM** updates PRD (remove MA references)
2. **SM** updates Architecture document
3. **SM** updates project-context.md
4. **SM** rewrites Story 4.1 and 4.2 in epics.md
5. **Dev** modifies Story 1.3 implementation (MA → media_player validation)
6. **Dev** continues Epic 3 (unchanged)
7. **Dev** implements Epic 4 with media_player approach

### Success Criteria

- [ ] PRD updated with MA references removed
- [ ] Architecture document updated
- [ ] project-context.md updated
- [ ] Story 1.3 code modified to validate media_players instead of MA
- [ ] Story 4.1 rewritten in epics.md
- [ ] Story 4.2 updated in epics.md
- [ ] Epic 4 implemented successfully with direct media_player control

---

## 6. Approval

**Proposed by:** Bob (Scrum Master)
**Date:** 2025-12-19

**Approval Status:** ✅ APPROVED

- [x] User approval obtained (2025-12-19)
- [x] Artifact updates completed (2025-12-19)
- [x] Implementation handoff confirmed (2025-12-19)

---

*Generated by Correct Course Workflow*
