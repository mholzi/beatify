# Story 19.10: Dynamic Song Difficulty Threshold

## Epic 19: Analytics Dashboard

## User Story

**As a** game administrator,
**I want** the hardest/easiest song cards to show data even with limited plays,
**So that** I always see useful song difficulty information regardless of game history.

---

## Overview

Currently, the hardest and easiest song statistics require a minimum of 3 plays per song before they appear in the analytics dashboard. This creates a poor user experience for new installations or infrequently used playlists where no songs meet this threshold.

This story introduces a **dynamic threshold** that adapts to the available data:
- If no song has been played 3+ times, the threshold automatically lowers
- The threshold equals `min(max_play_count_across_all_songs, 3)`
- This ensures users always see meaningful hardest/easiest data when any song data exists

---

## Acceptance Criteria

### AC1: Dynamic Threshold When Max Plays = 1
- [ ] **Given** all songs have been played only once (max_plays = 1)
- [ ] **When** computing hardest/easiest songs
- [ ] **Then** threshold is set to 1
- [ ] **And** all songs are eligible for hardest/easiest ranking

### AC2: Dynamic Threshold When Max Plays = 2
- [ ] **Given** at least one song has been played twice (max_plays = 2)
- [ ] **When** computing hardest/easiest songs
- [ ] **Then** threshold is set to 2
- [ ] **And** only songs with 2+ plays are eligible

### AC3: Standard Threshold When Max Plays >= 3
- [ ] **Given** at least one song has been played 3+ times (max_plays >= 3)
- [ ] **When** computing hardest/easiest songs
- [ ] **Then** threshold is capped at 3
- [ ] **And** only songs with 3+ plays are eligible (existing behavior)

### AC4: Threshold Formula
- [ ] **Given** the threshold formula
- [ ] **When** calculating eligible songs
- [ ] **Then** threshold = `min(max_play_count_across_all_songs, 3)`

### AC5: Edge Cases
- [ ] **Given** no songs have been played
- [ ] **When** computing hardest/easiest songs
- [ ] **Then** hardest and easiest return `None` (existing behavior)

- [ ] **Given** only one song has been played (once)
- [ ] **When** computing hardest/easiest songs
- [ ] **Then** that song appears as both hardest and easiest

### AC6: Backward Compatibility
- [ ] **Given** the existing `MIN_PLAYS_FOR_DIFFICULTY` constant
- [ ] **When** used in `get_song_difficulty()` method
- [ ] **Then** continues to use the static threshold of 3 (unchanged)
- [ ] **And** only `compute_song_stats()` uses the dynamic threshold

---

## Technical Implementation

### File to Modify

**`custom_components/beatify/services/stats.py`**

### Current Code (Lines 560-570)

```python
# Find most played (AC3)
most_played = max(song_list, key=lambda s: s["play_count"])

# Find hardest song - lowest accuracy with min 3 plays (AC3, AC7)
songs_with_enough_plays = [s for s in song_list if s["play_count"] >= 3]

hardest = None
easiest = None
if songs_with_enough_plays:
    hardest = min(songs_with_enough_plays, key=lambda s: s["accuracy"])
    easiest = max(songs_with_enough_plays, key=lambda s: s["accuracy"])
```

### Proposed Code Change

```python
# Find most played (AC3)
most_played = max(song_list, key=lambda s: s["play_count"])

# Story 19.10: Dynamic threshold for hardest/easiest songs
# Use min(max_play_count, 3) to always show data when possible
max_play_count = max(s["play_count"] for s in song_list)
min_plays_threshold = min(max_play_count, 3)

# Find hardest song - lowest accuracy with dynamic threshold
songs_with_enough_plays = [s for s in song_list if s["play_count"] >= min_plays_threshold]

hardest = None
easiest = None
if songs_with_enough_plays:
    hardest = min(songs_with_enough_plays, key=lambda s: s["accuracy"])
    easiest = max(songs_with_enough_plays, key=lambda s: s["accuracy"])
```

### Implementation Notes

1. **No constants change required**: The `MIN_PLAYS_FOR_DIFFICULTY` constant remains at 3 for use in `get_song_difficulty()` which displays star ratings during gameplay.

2. **Scope limited to analytics**: Only `compute_song_stats()` uses the dynamic threshold, affecting the hardest/easiest cards on the analytics dashboard.

3. **Safe fallback**: If `song_list` is empty, the code returns early (line 552-558), so `max()` on play counts will never fail on an empty list.

---

## UI Mockups

### Before (No Data Shown)
```
+------------------+  +------------------+  +------------------+
| HARDEST SONG     |  | EASIEST SONG     |  | MOST PLAYED      |
|                  |  |                  |  |                  |
| Not enough data  |  | Not enough data  |  | "Bohemian..."    |
| (need 3+ plays)  |  | (need 3+ plays)  |  | Queen - 2 plays  |
+------------------+  +------------------+  +------------------+
```

### After (Data Always Shown When Available)
```
+------------------+  +------------------+  +------------------+
| HARDEST SONG     |  | EASIEST SONG     |  | MOST PLAYED      |
|                  |  |                  |  |                  |
| "Radio Ga Ga"    |  | "Bohemian..."    |  | "Bohemian..."    |
| Queen - 23%      |  | Queen - 78%      |  | Queen - 2 plays  |
+------------------+  +------------------+  +------------------+
```

---

## Test Scenarios

### Unit Tests

```python
# tests/test_stats_service.py

def test_dynamic_threshold_max_plays_1():
    """When max plays is 1, threshold should be 1."""
    stats_service = StatsService(hass)
    # Setup: Add 3 songs, each played once
    await stats_service.record_song_result("song_a", [...], metadata_a)
    await stats_service.record_song_result("song_b", [...], metadata_b)
    await stats_service.record_song_result("song_c", [...], metadata_c)

    result = stats_service.compute_song_stats()

    # All songs should be eligible (threshold = 1)
    assert result["hardest"] is not None
    assert result["easiest"] is not None

def test_dynamic_threshold_max_plays_2():
    """When max plays is 2, threshold should be 2."""
    stats_service = StatsService(hass)
    # Setup: song_a played twice, song_b played once
    await stats_service.record_song_result("song_a", [...], metadata_a)
    await stats_service.record_song_result("song_a", [...], metadata_a)
    await stats_service.record_song_result("song_b", [...], metadata_b)

    result = stats_service.compute_song_stats()

    # Only song_a should be eligible (2+ plays)
    assert result["hardest"]["title"] == metadata_a["title"]
    assert result["easiest"]["title"] == metadata_a["title"]

def test_dynamic_threshold_max_plays_3_or_more():
    """When max plays is 3+, threshold should cap at 3."""
    stats_service = StatsService(hass)
    # Setup: song_a played 5 times, song_b played 2 times
    for _ in range(5):
        await stats_service.record_song_result("song_a", [...], metadata_a)
    for _ in range(2):
        await stats_service.record_song_result("song_b", [...], metadata_b)

    result = stats_service.compute_song_stats()

    # Only song_a should be eligible (3+ plays, song_b has only 2)
    assert result["hardest"]["title"] == metadata_a["title"]
    assert result["easiest"]["title"] == metadata_a["title"]

def test_dynamic_threshold_no_songs():
    """When no songs exist, return None for hardest/easiest."""
    stats_service = StatsService(hass)

    result = stats_service.compute_song_stats()

    assert result["hardest"] is None
    assert result["easiest"] is None
```

---

## Definition of Done

- [ ] Dynamic threshold implemented in `compute_song_stats()`
- [ ] Threshold formula: `min(max_play_count, 3)`
- [ ] Hardest/easiest cards show data with 1+ plays when that's the max
- [ ] Hardest/easiest cards show data with 2+ plays when that's the max
- [ ] Hardest/easiest cards show data with 3+ plays when any song has 3+
- [ ] `get_song_difficulty()` unchanged (still uses static threshold of 3)
- [ ] Unit tests added for all threshold scenarios
- [ ] No breaking changes to existing API responses
- [ ] Code reviewed and merged

---

## Story Points: 1

## Priority: High (Quick Fix)

## Effort Estimate: ~1 hour

## Dependencies
- Story 19.7 (Song Statistics) - Must be completed (provides `compute_song_stats()`)

---

## Related Stories
- **Story 19.7**: Song-Level Statistics Dashboard (introduced `compute_song_stats()`)
- **Story 15.1**: Song Difficulty Rating (introduced `get_song_difficulty()`)

---

## Notes

This is a quick fix that significantly improves user experience for new installations. The change is minimal (4 lines of code) but has high impact on the analytics dashboard usability.

The static `MIN_PLAYS_FOR_DIFFICULTY = 3` constant remains unchanged and is still used for displaying difficulty stars during gameplay, where statistical significance matters more.
