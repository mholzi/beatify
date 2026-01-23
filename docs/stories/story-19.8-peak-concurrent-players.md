# Story 19.8: Peak Concurrent Players Metric

## Epic 19: Analytics Dashboard

## User Story

**As a** game administrator,
**I want to** see the peak number of concurrent players in a single game,
**So that I** can understand maximum capacity usage and plan for party-sized events.

---

## Overview

Add a "Peak Players" metric to the analytics dashboard stat cards section. This metric displays the highest `player_count` recorded from any single game in the selected time period, helping administrators understand their maximum capacity usage.

---

## Acceptance Criteria

### AC1: Peak Players Stat Card
- [ ] New stat card displayed in the stat cards section
- [ ] Card shows:
  - Icon: Group/crowd icon (e.g., "crowd" or similar)
  - Value: The maximum player_count from any single game
  - Label: "Peak Players"
- [ ] Card positioned after the existing stat cards (Total Games, Avg Players, Avg Score)

### AC2: Peak Players Calculation
- [ ] **Given** games have been played with varying player counts
- [ ] **When** the peak is calculated
- [ ] **Then** the value reflects the maximum player_count from a single game (e.g., "12")
- [ ] **And** no trend indicator is shown (peak is an absolute value, not trended)

### AC3: Empty State
- [ ] **Given** no games in the selected period
- [ ] **When** the dashboard loads
- [ ] **Then** peak players shows "--"

### AC4: Period Filtering
- [ ] Peak Players metric respects the selected time period (7d, 30d, 90d, all)
- [ ] Recalculates when period filter is changed

---

## Technical Implementation

### Files to Modify

#### 1. Backend: `custom_components/beatify/analytics.py`

**Location:** `compute_metrics()` method (line 525)

**Changes:**
Add `peak_players` calculation to the metrics computation:

```python
def compute_metrics(
    self, period: str = "30d"
) -> dict[str, Any]:
    """
    Compute dashboard metrics for a given period (Story 19.2).
    ...
    """
    now = int(time.time())

    # ... existing period boundary calculations ...

    current_games = self.get_games(start_date=current_start, end_date=now)

    # Existing metrics
    total_games = len(current_games)
    # ... other existing calculations ...

    # Story 19.8: Calculate peak concurrent players
    peak_players = max(
        (g["player_count"] for g in current_games),
        default=0
    )

    # Return dict - add peak_players field
    return {
        "period": period,
        "total_games": total_games,
        "avg_players_per_game": round(avg_players, 1),
        "avg_score": round(avg_score, 1),
        "error_rate": round(error_rate, 3),
        "peak_players": peak_players,  # NEW: Story 19.8
        "trends": {
            "games": round(calc_trend(total_games, prev_total_games), 2),
            "players": round(calc_trend(avg_players, prev_avg_players), 2),
            "score": round(calc_trend(avg_score, prev_avg_score), 2),
            "errors": round(calc_trend(error_rate, prev_error_rate), 2),
        },
        "playlists": playlists,
        "chart_data": chart_data,
        "error_stats": error_stats,
        "generated_at": now,
    }
```

#### 2. Frontend HTML: `custom_components/beatify/www/analytics.html`

**Location:** Inside the `<section class="stat-cards">` element (lines 44-65)

**Changes:**
Add a new stat card after the existing cards:

```html
<!-- Stat Cards Grid -->
<section class="stat-cards">
    <!-- Existing cards: stat-total-games, stat-avg-players, stat-avg-score -->
    <div class="stat-card" id="stat-total-games">
        <!-- ... existing ... -->
    </div>

    <div class="stat-card" id="stat-avg-players">
        <!-- ... existing ... -->
    </div>

    <div class="stat-card" id="stat-avg-score">
        <!-- ... existing ... -->
    </div>

    <!-- NEW: Story 19.8 - Peak Players -->
    <div class="stat-card" id="stat-peak-players">
        <div class="stat-icon" aria-hidden="true">🎉</div>
        <div class="stat-value">--</div>
        <div class="stat-label" data-i18n="analyticsDashboard.peakPlayers">Peak Players</div>
    </div>
</section>
```

**Note:** The Peak Players card intentionally omits the `stat-trend` div since peak is an absolute value without trend comparison.

#### 3. Frontend JavaScript: `custom_components/beatify/www/js/analytics.js`

**Location:** `renderStats()` function (lines 61-73)

**Changes:**
Add rendering logic for the peak players card:

```javascript
/**
 * Render stat cards with data
 * @param {Object} data - Analytics data from API
 */
function renderStats(data) {
    updateStatCard('stat-total-games', data.total_games, data.trends.games);
    updateStatCard('stat-avg-players', data.avg_players_per_game.toFixed(1), data.trends.players);
    updateStatCard('stat-avg-score', data.avg_score.toFixed(1), data.trends.score);

    // Story 19.8: Peak Players (no trend)
    updatePeakPlayersCard('stat-peak-players', data.peak_players);

    // Render additional sections (Stories 19.4, 19.5)
    if (data.playlists) {
        renderPlaylists(data.playlists);
    }
    if (data.chart_data) {
        renderChart(data.chart_data);
    }
}

/**
 * Update the Peak Players card (Story 19.8)
 * Peak is an absolute value, no trend indicator
 * @param {string} id - Card element ID
 * @param {number} value - Peak player count
 */
function updatePeakPlayersCard(id, value) {
    var card = document.getElementById(id);
    if (!card) return;

    card.classList.remove('loading');

    var valueEl = card.querySelector('.stat-value');
    if (valueEl) {
        // Show "--" if no games (value is 0 or undefined)
        valueEl.textContent = value > 0 ? value : '--';
    }
}
```

#### 4. Translation Files (Optional but Recommended)

**Files:**
- `custom_components/beatify/www/i18n/en.json`
- `custom_components/beatify/www/i18n/de.json`
- `custom_components/beatify/www/i18n/es.json`

**Add to `analyticsDashboard` section:**

English (`en.json`):
```json
"peakPlayers": "Peak Players"
```

German (`de.json`):
```json
"peakPlayers": "Max. Spieler"
```

Spanish (`es.json`):
```json
"peakPlayers": "Jugadores Pico"
```

---

## API Response Schema

The analytics API endpoint `/beatify/api/analytics?period={period}` will include:

```json
{
  "period": "30d",
  "total_games": 45,
  "avg_players_per_game": 4.2,
  "avg_score": 67.5,
  "peak_players": 12,
  "trends": {
    "games": 0.15,
    "players": 0.08,
    "score": -0.02,
    "errors": 0.0
  },
  "playlists": [...],
  "chart_data": {...},
  "error_stats": {...},
  "generated_at": 1737654321
}
```

---

## UI Mockup

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Period: [7 Days] [30 Days] [90 Days] [All Time]                            │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────┐ ┌─────────────────┐ ┌─────────────────┐ ┌────────────┐│
│  │      Total      │ │   Avg Players   │ │    Avg Score    │ │   Peak     ││
│  │      Games      │ │                 │ │                 │ │  Players   ││
│  │                 │ │                 │ │                 │ │            ││
│  │       45        │ │      4.2        │ │      67.5       │ │     12     ││
│  │    ↑ 15%        │ │    ↑ 8%         │ │    ↓ 2%         │ │    (no     ││
│  │                 │ │                 │ │                 │ │    trend)  ││
│  └─────────────────┘ └─────────────────┘ └─────────────────┘ └────────────┘│
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Edge Cases

1. **No games in period**: Display "--" for peak players value
2. **All games have 1 player**: Display "1"
3. **Single game in period**: Display that game's player count
4. **Period change**: Recalculate peak for new period
5. **Zero player games**: Should be filtered out (games with 0 players are not recorded per AC8 in stats.py)

---

## Definition of Done

- [ ] Backend `compute_metrics()` returns `peak_players` field
- [ ] API response includes `peak_players` in JSON
- [ ] HTML stat card added to analytics.html
- [ ] JavaScript updates Peak Players card on data load
- [ ] No trend indicator shown (peak is absolute)
- [ ] Empty state ("--") displays when no games
- [ ] Period filtering works correctly
- [ ] Unit tests added for peak_players calculation
- [ ] Manual testing completed for all time periods
- [ ] Translations added for English, German, and Spanish

---

## Testing Checklist

### Unit Tests
- [ ] `compute_metrics()` returns correct peak_players with multiple games
- [ ] `compute_metrics()` returns 0 when no games in period
- [ ] Peak correctly identifies maximum from varying player counts

### Manual Testing
- [ ] Load dashboard with games data - Peak Players shows correct value
- [ ] Load dashboard with no games - Peak Players shows "--"
- [ ] Switch time periods - Peak Players updates correctly
- [ ] Responsive layout - Card displays correctly on mobile

---

## Story Points: 2

## Priority: Low

## Dependencies
- Story 19.2 (Analytics Dashboard) - Must be completed
- Analytics API infrastructure must exist

---

## Effort Estimate: ~2 hours

---

## Related Stories
- Story 19.9: Avg Rounds Per Game Metric (similar pattern)
- Story 19.13: Analytics UI Polish (may consolidate UI changes)
