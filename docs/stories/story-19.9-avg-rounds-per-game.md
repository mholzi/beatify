# Story 19.9: Average Rounds Per Game Metric

## Epic 19: Analytics Dashboard

## User Story

**As a** game administrator,
**I want to** see the average number of rounds played per game,
**So that I** can understand typical game length and engagement depth.

---

## Overview

Add an "Avg Rounds" metric to the analytics dashboard stat cards section. This displays the mean `rounds_played` across all games in the selected time period as the fifth stat card. A trend indicator shows comparison to the previous period, helping administrators understand engagement patterns.

---

## Acceptance Criteria

### AC1: Avg Rounds Stat Card
- [ ] New stat card added to the stat cards section
- [ ] Card shows:
  - Icon: Game/dice icon (e.g., "🎲")
  - Value: The average rounds_played from all games in the period
  - Label: "Avg Rounds"
  - Trend indicator showing comparison to previous period
- [ ] Card positioned as the fifth stat card (after Total Games, Avg Players, Avg Score, Peak Players)

### AC2: Average Calculation
- [ ] **Given** games with varying round counts (e.g., 5, 10, 15 rounds)
- [ ] **When** the average is calculated
- [ ] **Then** the value is displayed as a decimal with one decimal place (e.g., "8.3")
- [ ] **And** trend indicator shows percentage change compared to previous period

### AC3: Empty State
- [ ] **Given** no games in the selected period
- [ ] **When** the dashboard loads
- [ ] **Then** avg rounds shows "--"
- [ ] **And** trend indicator shows neutral state ("-- 0%")

### AC4: Period Filtering
- [ ] Avg Rounds metric respects the selected time period (7d, 30d, 90d, all)
- [ ] Recalculates when period filter is changed
- [ ] Trend compares to the equivalent previous period

### AC5: Trend Indicator
- [ ] Trend shows positive (up arrow, green) when average rounds increased
- [ ] Trend shows negative (down arrow, red) when average rounds decreased
- [ ] Trend shows neutral when no change or no previous data

---

## Technical Implementation

### Files to Modify

#### 1. Backend: `custom_components/beatify/analytics.py`

**Location:** `compute_metrics()` method (line 525-614)

**Changes:**
Add `avg_rounds` calculation and replace `error_rate` with rounds trend:

```python
def compute_metrics(
    self, period: str = "30d"
) -> dict[str, Any]:
    """
    Compute dashboard metrics for a given period (Story 19.2).
    ...
    """
    now = int(time.time())

    # ... existing period boundary calculations (lines 538-549) ...

    current_games = self.get_games(start_date=current_start, end_date=now)
    previous_games = self.get_games(start_date=previous_start, end_date=current_start - 1)

    # Existing metrics calculations (lines 555-564)
    total_games = len(current_games)
    total_players = sum(g["player_count"] for g in current_games)
    total_rounds = sum(g["rounds_played"] for g in current_games)
    total_score = sum(g["average_score"] * g["player_count"] for g in current_games)

    avg_players = total_players / total_games if total_games > 0 else 0
    avg_score = total_score / total_players if total_players > 0 else 0

    # Story 19.9: Calculate average rounds per game
    avg_rounds = total_rounds / total_games if total_games > 0 else 0

    # Previous period metrics (lines 567-576)
    prev_total_games = len(previous_games)
    prev_total_players = sum(g["player_count"] for g in previous_games)
    prev_total_rounds = sum(g["rounds_played"] for g in previous_games)
    prev_total_score = sum(g["average_score"] * g["player_count"] for g in previous_games)

    prev_avg_players = prev_total_players / prev_total_games if prev_total_games > 0 else 0
    prev_avg_score = prev_total_score / prev_total_players if prev_total_players > 0 else 0

    # Story 19.9: Calculate previous period average rounds
    prev_avg_rounds = prev_total_rounds / prev_total_games if prev_total_games > 0 else 0

    # ... existing calc_trend function (lines 579-582) ...

    # Return dict - add avg_rounds field, keep error_rate for backwards compatibility
    return {
        "period": period,
        "total_games": total_games,
        "avg_players_per_game": round(avg_players, 1),
        "avg_score": round(avg_score, 1),
        "error_rate": round(error_rate, 3),  # Keep for backwards compatibility
        "peak_players": peak_players,
        "avg_rounds": round(avg_rounds, 1),  # NEW: Story 19.9
        "trends": {
            "games": round(calc_trend(total_games, prev_total_games), 2),
            "players": round(calc_trend(avg_players, prev_avg_players), 2),
            "score": round(calc_trend(avg_score, prev_avg_score), 2),
            "errors": round(calc_trend(error_rate, prev_error_rate), 2),
            "rounds": round(calc_trend(avg_rounds, prev_avg_rounds), 2),  # NEW: Story 19.9
        },
        "playlists": playlists,
        "chart_data": chart_data,
        "error_stats": error_stats,
        "generated_at": now,
    }
```

**Specific Code Changes:**

**Add after line 564 (after `error_rate` calculation):**
```python
    # Story 19.9: Calculate average rounds per game
    avg_rounds = total_rounds / total_games if total_games > 0 else 0
```

**Add after line 576 (after `prev_error_rate` calculation):**
```python
    # Story 19.9: Calculate previous period average rounds
    prev_avg_rounds = prev_total_rounds / prev_total_games if prev_total_games > 0 else 0
```

**Modify the return dict (around line 597) to add:**
```python
        "avg_rounds": round(avg_rounds, 1),  # NEW: Story 19.9
```

**Modify the trends dict (around line 608) to add:**
```python
            "rounds": round(calc_trend(avg_rounds, prev_avg_rounds), 2),  # NEW: Story 19.9
```

#### 2. Frontend HTML: `custom_components/beatify/www/analytics.html`

**Location:** Inside the `<section class="stat-cards">` element (lines 44-72)

**Changes:**
Add Avg Rounds as the fifth stat card after Peak Players.

**Add new stat card after existing cards (after line 71, before `</section>`):**

```html
            <!-- Story 19.9: Avg Rounds Per Game -->
            <div class="stat-card" id="stat-avg-rounds">
                <div class="stat-icon" aria-hidden="true">🎲</div>
                <div class="stat-value">--</div>
                <div class="stat-label" data-i18n="analyticsDashboard.avgRounds">Avg Rounds</div>
                <div class="stat-trend"></div>
            </div>
```

**Note:** The Avg Rounds card includes the `stat-trend` div since this metric has trend comparison (unlike Peak Players).

#### 3. Frontend JavaScript: `custom_components/beatify/www/js/analytics.js`

**Location:** `renderStats()` function (lines 61-76)

**Changes:**
Add rendering logic for the average rounds card:

**Modify `renderStats()` function to add (after line 67):**

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

    // Story 19.9: Avg Rounds Per Game (with trend)
    updateStatCard('stat-avg-rounds',
        data.avg_rounds > 0 ? data.avg_rounds.toFixed(1) : '--',
        data.trends.rounds || 0
    );

    // Render additional sections (Stories 19.4, 19.5)
    if (data.playlists) {
        renderPlaylists(data.playlists);
    }
    if (data.chart_data) {
        renderChart(data.chart_data);
    }
}
```

**Note:** The existing `updateStatCard()` function (lines 657-682) already handles trend rendering, so we can reuse it for Avg Rounds. The only special handling is to display "--" when there are no games (avg_rounds is 0).

#### 4. Translation Files

**Files:**
- `custom_components/beatify/www/i18n/en.json`
- `custom_components/beatify/www/i18n/de.json`
- `custom_components/beatify/www/i18n/es.json`

**Add to `analyticsDashboard` section:**

English (`en.json`):
```json
"avgRounds": "Avg Rounds"
```

German (`de.json`):
```json
"avgRounds": "Durchschn. Runden"
```

Spanish (`es.json`):
```json
"avgRounds": "Rondas Prom."
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
  "error_rate": 0.012,
  "peak_players": 12,
  "avg_rounds": 8.3,
  "trends": {
    "games": 0.15,
    "players": 0.08,
    "score": -0.02,
    "errors": 0.0,
    "rounds": 0.05
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
+-----------------------------------------------------------------------------------+
|  Period: [7 Days] [30 Days] [90 Days] [All Time]                                  |
+-----------------------------------------------------------------------------------+
|                                                                                   |
|  +--------------+ +--------------+ +--------------+ +--------------+ +-----------+
|  |    Total     | | Avg Players  | |  Avg Score   | |    Peak      | |   Avg     |
|  |    Games     | |              | |              | |  Players     | |  Rounds   |
|  |              | |              | |              | |              | |           |
|  |      45      | |     4.2      | |     67.5     | |      12      | |    8.3    |
|  |   up 15%     | |   up 8%      | |  down 2%     | |  (no trend)  | |  up 5%    |
|  +--------------+ +--------------+ +--------------+ +--------------+ +-----------+
|                                                                                   |
+-----------------------------------------------------------------------------------+
```

---

## Edge Cases

1. **No games in period**: Display "--" for avg rounds value, neutral trend ("-- 0%")
2. **Games with 0 rounds**: Include in calculation (results in lower average)
3. **All games have same round count**: Display that count, no trend change if same in previous period
4. **Single game in period**: Display that game's round count
5. **Period change**: Recalculate average and trend for new period
6. **No previous period data**: Trend shows +100% if current has games, 0% if no games

---

## Definition of Done

- [ ] Backend `compute_metrics()` returns `avg_rounds` field
- [ ] Backend `compute_metrics()` returns `trends.rounds` field
- [ ] API response includes `avg_rounds` in JSON
- [ ] API response includes `trends.rounds` in JSON
- [ ] HTML stat card added to analytics.html
- [ ] JavaScript updates Avg Rounds card on data load
- [ ] Trend indicator shows correctly (positive/negative/neutral)
- [ ] Empty state ("--") displays when no games
- [ ] Period filtering works correctly
- [ ] Unit tests added for avg_rounds calculation
- [ ] Manual testing completed for all time periods
- [ ] Translations added for English, German, and Spanish

---

## Testing Checklist

### Unit Tests
- [ ] `compute_metrics()` returns correct avg_rounds with multiple games
- [ ] `compute_metrics()` returns 0 when no games in period
- [ ] Average correctly calculated from varying round counts (5, 10, 15 = 10.0)
- [ ] Trend correctly calculated between periods
- [ ] Trend shows +1.0 (100%) when previous period has no games but current does

### Manual Testing
- [ ] Load dashboard with games data - Avg Rounds shows correct value
- [ ] Load dashboard with no games - Avg Rounds shows "--"
- [ ] Switch time periods - Avg Rounds updates correctly
- [ ] Trend indicator displays with correct color and direction
- [ ] Responsive layout - Card displays correctly on mobile
- [ ] Verify translations load correctly for en/de/es

### Integration Testing
- [ ] API returns correct JSON structure with new fields
- [ ] JavaScript correctly parses and displays API response
- [ ] Period filtering updates both value and trend

---

## Story Points: 2

## Priority: Low

## Dependencies
- Story 19.2 (Analytics Dashboard) - Must be completed
- Analytics API infrastructure must exist
- Story 19.8 (Peak Players) - Should be completed (establishes pattern)

---

## Effort Estimate: ~2 hours

---

## Related Stories
- Story 19.8: Peak Concurrent Players Metric (similar pattern, completed)
- Story 19.13: Analytics UI Polish (may consolidate UI changes)

---

## Notes

- This story follows the same implementation pattern as Story 19.8 (Peak Players)
- The `rounds_played` field is already tracked in the `GameRecord` TypedDict (line 38 in analytics.py)
- The `total_rounds` calculation already exists in `compute_metrics()` (line 557) for other calculations
- The `prev_total_rounds` calculation already exists in `compute_metrics()` (line 569)
