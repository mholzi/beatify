# Story 19.11: Streak Achievements Tracking

## Epic 19: Analytics Dashboard

## User Story

**As a** game administrator,
**I want to** see how often players achieve guess streaks,
**So that I** can understand engagement with the streak bonus mechanic.

---

## Overview

Add streak achievement tracking to the analytics system. When players achieve streaks of 3+, 5+, or 7+ consecutive correct guesses, record these milestones in analytics data. Display this information in a new "Streaks" section on the analytics dashboard, showing the distribution of streak achievements across all games.

---

## Acceptance Criteria

### AC1: Streak Achievement Recording
- [ ] **Given** a player guesses correctly multiple times in a row
- [ ] **When** the streak reaches 3, 5, or 7+
- [ ] **Then** the achievement is recorded in analytics data
- [ ] **And** each milestone is counted only once per streak (reaching 5 counts as 5+, not as 3+ AND 5+)

### AC2: Dashboard Streaks Section
- [ ] **Given** the analytics dashboard
- [ ] **When** viewing a new "Streaks" section or card
- [ ] **Then** streak distribution is displayed:
  - Count of 3+ streaks achieved
  - Count of 5+ streaks achieved
  - Count of 7+ streaks achieved (legendary)
- [ ] **And** section has appropriate icon (e.g., fire icon or streak indicator)

### AC3: Streak Persistence
- [ ] **Given** streak data is being collected
- [ ] **When** a game ends
- [ ] **Then** streak achievements from that game are persisted to analytics storage
- [ ] **And** data survives Home Assistant restarts

### AC4: Empty State
- [ ] **Given** no streak data exists (new feature)
- [ ] **When** dashboard loads
- [ ] **Then** shows "No streak data yet" or zeros for all streak counts

### AC5: Period Filtering
- [ ] Streak stats respect the selected time period (7d, 30d, 90d, all)
- [ ] Recalculate when period filter is changed

---

## Technical Implementation

### Files to Modify

#### 1. Backend: `custom_components/beatify/analytics.py`

**Add to `GameRecord` TypedDict (after line 40):**

```python
class GameRecord(TypedDict):
    """Game record schema (AC: #1)."""

    game_id: str
    started_at: int  # Unix timestamp
    ended_at: int  # Unix timestamp
    duration_seconds: int
    player_count: int
    playlist_names: list[str]
    rounds_played: int
    average_score: float
    difficulty: str
    error_count: int
    # Story 19.11: Streak achievements
    streak_3_count: int   # Number of 3+ streaks achieved
    streak_5_count: int   # Number of 5+ streaks achieved
    streak_7_count: int   # Number of 7+ streaks achieved
```

**Add new method to `AnalyticsStorage` class (after `compute_metrics` method which ends at line 622, before the error type constants):**

```python
def compute_streak_stats(
    self, period: str = "30d"
) -> dict[str, Any]:
    """
    Compute streak achievement statistics for a given period (Story 19.11).

    Args:
        period: Time period - "7d", "30d", "90d", or "all"

    Returns:
        Dict with streak counts and distribution
    """
    now = int(time.time())

    # Calculate period boundaries
    days_map = {"7d": 7, "30d": 30, "90d": 90, "all": 365 * 10}
    days = days_map.get(period, 30)
    start_ts = now - (days * 86400)

    # Get games for current period
    games = self.get_games(start_date=start_ts, end_date=now)

    # Sum streak achievements across all games
    streak_3_total = sum(g.get("streak_3_count", 0) for g in games)
    streak_5_total = sum(g.get("streak_5_count", 0) for g in games)
    streak_7_total = sum(g.get("streak_7_count", 0) for g in games)

    total_streaks = streak_3_total + streak_5_total + streak_7_total

    return {
        "streak_3_count": streak_3_total,
        "streak_5_count": streak_5_total,
        "streak_7_count": streak_7_total,
        "total_streaks": total_streaks,
        "has_data": total_streaks > 0,
    }
```

**Modify `compute_metrics` method return dict (lines 603-622) to include streak stats:**

```python
return {
    "period": period,
    "total_games": total_games,
    "avg_players_per_game": round(avg_players, 1),
    "avg_score": round(avg_score, 1),
    "error_rate": round(error_rate, 3),
    "peak_players": peak_players,
    "avg_rounds": round(avg_rounds, 1),
    # Story 19.11: Include streak stats
    "streak_stats": self.compute_streak_stats(period),
    "trends": {
        # ... existing trends ...
    },
    # ... rest of return dict ...
}
```

#### 2. Game State: `custom_components/beatify/game/state.py`

**Add streak tracking fields to `GameState.__init__` (after line 190, before the closing of `__init__`):**

```python
# Story 19.11: Streak achievement tracking for analytics
self.streak_achievements: dict[str, int] = {
    "streak_3": 0,  # Count of 3+ streaks
    "streak_5": 0,  # Count of 5+ streaks
    "streak_7": 0,  # Count of 7+ streaks
}
```

**Modify `end_round` method (around line 1192, after the `player.streak += 1` line):**

The current code already tracks streaks on the player object (lines 1188-1202). Add achievement recording after the streak is incremented but before streak_bonus calculation:

```python
# Update streak - any points continues streak (Story 5.2)
# Note: streak based on speed_score, not bet-adjusted score
if speed_score > 0:
    player.previous_streak = 0  # Not relevant when scoring
    player.streak += 1

    # Story 19.11: Record streak achievements at milestones
    # Only count each milestone once (when first reached at exact value)
    if player.streak == 3:
        self.streak_achievements["streak_3"] += 1
    elif player.streak == 5:
        self.streak_achievements["streak_5"] += 1
    elif player.streak == 7:
        self.streak_achievements["streak_7"] += 1

    # Check for streak milestone bonus (awarded at exact milestones)
    player.streak_bonus = calculate_streak_bonus(player.streak)
    # ... existing steal unlock logic ...
```

**Modify `finalize_game` method (around line 391-439) to include streak data in return dict:**

```python
def finalize_game(self) -> dict[str, Any]:
    """
    Calculate final stats before ending the game (Story 14.4).
    ...
    """
    # ... existing calculations ...

    return {
        "playlist": playlist_name,
        "rounds": rounds_played,
        "player_count": player_count,
        "winner": winner_name,
        "winner_score": winner_score,
        "total_points": total_points,
        "avg_score_per_round": round(avg_score_per_round, 2),
        # Story 19.11: Include streak achievements
        "streak_3_count": self.streak_achievements.get("streak_3", 0),
        "streak_5_count": self.streak_achievements.get("streak_5", 0),
        "streak_7_count": self.streak_achievements.get("streak_7", 0),
    }
```

**Reset streak achievements in `end_game` method (around line 441-488, add after other resets):**

```python
def end_game(self) -> None:
    """End the current game and reset state."""
    # ... existing resets ...

    # Story 19.11: Reset streak tracking
    self.streak_achievements = {"streak_3": 0, "streak_5": 0, "streak_7": 0}
```

**Reset streak achievements in `create_game` method (around line 270, after round_duration assignment):**

```python
# Story 19.11: Reset streak tracking for new game
self.streak_achievements = {"streak_3": 0, "streak_5": 0, "streak_7": 0}
```

#### 3. Stats Service: `custom_components/beatify/services/stats.py`

**Modify `record_game` method (lines 158-169) to pass streak data to analytics:**

Add streak fields to the `analytics_record` dict after `error_count` (around line 168):

```python
analytics_record: GameRecord = {
    "game_id": game_id,
    "started_at": started_at,
    "ended_at": now,
    "duration_seconds": duration,
    "player_count": player_count,
    "playlist_names": playlist_names,
    "rounds_played": rounds,
    "average_score": round(avg_score_per_round, 2),
    "difficulty": difficulty,
    "error_count": self._analytics.session_error_count,
    # Story 19.11: Streak achievements
    "streak_3_count": game_summary.get("streak_3_count", 0),
    "streak_5_count": game_summary.get("streak_5_count", 0),
    "streak_7_count": game_summary.get("streak_7_count", 0),
}
await self._analytics.add_game(analytics_record)
```

#### 4. Frontend HTML: `custom_components/beatify/www/analytics.html`

**Add Streak Section after the stat cards section (after line 80, before the loading state on line 82). The streak section should appear between the stat cards and the loading/error state sections:**

```html
<!-- Story 19.11: Streak Achievements Section -->
<section class="streak-analytics" aria-labelledby="streak-stats-heading">
    <h2 class="section-header" id="streak-stats-heading">
        <span class="section-icon" aria-hidden="true">🔥</span>
        <span data-i18n="analyticsDashboard.streakAchievements">Streak Achievements</span>
    </h2>

    <div class="streak-cards" id="streak-cards">
        <div class="streak-card" id="streak-3-card">
            <div class="streak-icon" aria-hidden="true">🔥</div>
            <div class="streak-value" id="streak-3-value">--</div>
            <div class="streak-label">
                <span data-i18n="analyticsDashboard.streak3Plus">3+ Streaks</span>
            </div>
            <div class="streak-description" data-i18n="analyticsDashboard.streak3Desc">Hot start!</div>
        </div>

        <div class="streak-card" id="streak-5-card">
            <div class="streak-icon" aria-hidden="true">🔥🔥</div>
            <div class="streak-value" id="streak-5-value">--</div>
            <div class="streak-label">
                <span data-i18n="analyticsDashboard.streak5Plus">5+ Streaks</span>
            </div>
            <div class="streak-description" data-i18n="analyticsDashboard.streak5Desc">On fire!</div>
        </div>

        <div class="streak-card streak-card--legendary" id="streak-7-card">
            <div class="streak-icon" aria-hidden="true">🔥🔥🔥</div>
            <div class="streak-value" id="streak-7-value">--</div>
            <div class="streak-label">
                <span data-i18n="analyticsDashboard.streak7Plus">7+ Streaks</span>
            </div>
            <div class="streak-description" data-i18n="analyticsDashboard.streak7Desc">Legendary!</div>
        </div>
    </div>

    <!-- Empty State (AC4) -->
    <div class="empty-state hidden" id="streak-empty">
        <div class="empty-icon" aria-hidden="true">🔥</div>
        <p data-i18n="analyticsDashboard.noStreakData">No streak data yet</p>
        <p class="empty-hint" data-i18n="analyticsDashboard.streakHint">Players earn streaks by guessing correctly multiple times in a row</p>
    </div>
</section>
```

#### 5. Frontend CSS: `custom_components/beatify/www/css/analytics.css`

**Add streak section styles:**

```css
/* Story 19.11: Streak Achievements Section */
.streak-analytics {
    margin-top: var(--space-lg);
}

.streak-cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: var(--space-md);
    margin-top: var(--space-md);
}

.streak-card {
    background: var(--bg-card);
    border-radius: var(--radius-lg);
    padding: var(--space-lg);
    text-align: center;
    border: 1px solid var(--border-color);
    transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.streak-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
}

.streak-card--legendary {
    background: linear-gradient(135deg, var(--bg-card) 0%, rgba(255, 107, 0, 0.1) 100%);
    border-color: var(--color-orange);
}

.streak-icon {
    font-size: 2rem;
    margin-bottom: var(--space-sm);
}

.streak-value {
    font-size: 2.5rem;
    font-weight: 700;
    color: var(--color-primary);
}

.streak-card--legendary .streak-value {
    color: var(--color-orange);
}

.streak-label {
    font-size: var(--text-sm);
    color: var(--text-secondary);
    margin-top: var(--space-xs);
}

.streak-description {
    font-size: var(--text-xs);
    color: var(--text-muted);
    margin-top: var(--space-xs);
}
```

#### 6. Frontend JavaScript: `custom_components/beatify/www/js/analytics.js`

**Add streak rendering function (after `renderStats` function which ends at line 82, before `updatePeakPlayersCard`):**

```javascript
/**
 * Render streak achievements section (Story 19.11)
 * @param {Object} streakStats - Streak statistics from API
 */
function renderStreakStats(streakStats) {
    var cardsEl = document.getElementById('streak-cards');
    var emptyEl = document.getElementById('streak-empty');

    // Check for data
    if (!streakStats || !streakStats.has_data) {
        if (cardsEl) cardsEl.classList.add('hidden');
        if (emptyEl) emptyEl.classList.remove('hidden');
        return;
    }

    if (cardsEl) cardsEl.classList.remove('hidden');
    if (emptyEl) emptyEl.classList.add('hidden');

    // Update streak values
    updateStreakCard('streak-3-value', streakStats.streak_3_count);
    updateStreakCard('streak-5-value', streakStats.streak_5_count);
    updateStreakCard('streak-7-value', streakStats.streak_7_count);
}

/**
 * Update a streak card value
 * @param {string} id - Element ID
 * @param {number} value - Streak count
 */
function updateStreakCard(id, value) {
    var el = document.getElementById(id);
    if (el) {
        el.textContent = value > 0 ? value : '--';
    }
}
```

**Modify `renderStats` function (lines 61-82) to include streak rendering - add after line 73 (after avg_rounds):**

```javascript
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

    // Story 19.11: Streak Achievements
    if (data.streak_stats) {
        renderStreakStats(data.streak_stats);
    }

    // Render additional sections (Stories 19.4, 19.5)
    if (data.playlists) {
        renderPlaylists(data.playlists);
    }
    if (data.chart_data) {
        renderChart(data.chart_data);
    }
}
```

#### 7. Translation Files

**Add to `custom_components/beatify/www/i18n/en.json` under `analyticsDashboard`:**

```json
"streakAchievements": "Streak Achievements",
"streak3Plus": "3+ Streaks",
"streak5Plus": "5+ Streaks",
"streak7Plus": "7+ Streaks",
"streak3Desc": "Hot start!",
"streak5Desc": "On fire!",
"streak7Desc": "Legendary!",
"noStreakData": "No streak data yet",
"streakHint": "Players earn streaks by guessing correctly multiple times in a row"
```

**Add to `custom_components/beatify/www/i18n/de.json` under `analyticsDashboard`:**

```json
"streakAchievements": "Serien-Erfolge",
"streak3Plus": "3+ Serien",
"streak5Plus": "5+ Serien",
"streak7Plus": "7+ Serien",
"streak3Desc": "Guter Start!",
"streak5Desc": "Am Brennen!",
"streak7Desc": "Legendar!",
"noStreakData": "Noch keine Seriendaten",
"streakHint": "Spieler erhalten Serien durch mehrfaches korrektes Raten hintereinander"
```

**Add to `custom_components/beatify/www/i18n/es.json` under `analyticsDashboard`:**

```json
"streakAchievements": "Logros de Racha",
"streak3Plus": "Rachas de 3+",
"streak5Plus": "Rachas de 5+",
"streak7Plus": "Rachas de 7+",
"streak3Desc": "Buen comienzo!",
"streak5Desc": "En llamas!",
"streak7Desc": "Legendario!",
"noStreakData": "Sin datos de rachas todavia",
"streakHint": "Los jugadores ganan rachas al adivinar correctamente varias veces seguidas"
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
  "streak_stats": {
    "streak_3_count": 127,
    "streak_5_count": 43,
    "streak_7_count": 12,
    "total_streaks": 182,
    "has_data": true
  },
  "trends": {...},
  "playlists": [...],
  "chart_data": {...},
  "generated_at": 1737654321
}
```

---

## UI Mockup

```
+-----------------------------------------------------------------------------------+
|  Streak Achievements                                                         |
+-----------------------------------------------------------------------------------+
|                                                                                   |
|  +------------------+  +------------------+  +----------------------+             |
|  |       🔥         |  |      🔥🔥        |  |       🔥🔥🔥          |             |
|  |                  |  |                  |  |                      |             |
|  |       127        |  |       43         |  |        12            |             |
|  |    3+ Streaks    |  |    5+ Streaks    |  |     7+ Streaks       |             |
|  |    Hot start!    |  |    On fire!      |  |     Legendary!       |             |
|  +------------------+  +------------------+  +----------------------+             |
|                                              (special golden border)              |
+-----------------------------------------------------------------------------------+
```

---

## Edge Cases

1. **No games played**: All streak counts show "--", empty state message displayed
2. **Games with no streaks**: All counts show 0 (not "--")
3. **Single player game**: Streaks still tracked normally
4. **Player disconnects during streak**: Streak is broken (standard behavior), no achievement recorded
5. **7+ continues past 7**: Only counts once when reaching 7 (not at 8, 9, etc.)
6. **Period filtering**: Only streaks from games within the period are counted
7. **Old games without streak data**: Show 0 for streak fields (backwards compatible)

---

## Definition of Done

- [ ] `GameRecord` TypedDict includes streak count fields
- [ ] `GameState` tracks streak achievements during gameplay
- [ ] `finalize_game()` returns streak counts
- [ ] `record_game()` passes streak data to analytics storage
- [ ] `compute_streak_stats()` method added to `AnalyticsStorage`
- [ ] `compute_metrics()` includes `streak_stats` in response
- [ ] HTML streak section added to analytics.html
- [ ] CSS styles for streak cards
- [ ] JavaScript renders streak data
- [ ] Empty state displays when no streak data
- [ ] Period filtering works for streak stats
- [ ] Data persists after HA restart
- [ ] Translations added for English, German, and Spanish
- [ ] Unit tests for streak tracking logic
- [ ] Manual testing completed for all scenarios

---

## Testing Checklist

### Unit Tests
- [ ] `GameState` increments streak_achievements at correct milestones
- [ ] Milestone only counted once per streak (3, 5, or 7 - not cumulative)
- [ ] `finalize_game()` returns correct streak counts
- [ ] `compute_streak_stats()` sums correctly across games
- [ ] `compute_streak_stats()` returns has_data=false when no streaks
- [ ] Period filtering excludes games outside range

### Integration Tests
- [ ] API returns streak_stats in response
- [ ] Streak data persists to analytics.json
- [ ] Data survives HA restart

### Manual Testing
- [ ] Play game with 3+ streak - verify count increments
- [ ] Play game with 5+ streak - verify count increments
- [ ] Play game with 7+ streak - verify count increments
- [ ] Load dashboard with no streak data - verify empty state
- [ ] Switch time periods - verify streak stats update
- [ ] Verify legendary card has special styling
- [ ] Test all three languages

---

## Story Points: 5

## Priority: Medium

## Dependencies
- Story 19.1 (Analytics Infrastructure) - Must be completed
- Story 19.2 (Analytics Dashboard) - Must be completed
- Story 5.2 (Streak Bonus) - Already implemented (streak tracking exists)

---

## Effort Estimate: ~4-6 hours

---

## Related Stories
- Story 5.2: Streak Bonus (existing streak mechanic)
- Story 15.2: Superlatives (Lucky Streak award)
- Story 19.12: Bet Tracking (similar analytics pattern)
- Story 19.13: Analytics UI Polish (may consolidate UI changes)

---

## Notes

- Streaks are already tracked on `PlayerSession.streak` and `PlayerSession.best_streak`
- The `STEAL_UNLOCK_STREAK` constant is 3, aligning with the 3+ milestone
- The `MIN_STREAK_FOR_AWARD` constant (used in superlatives) is 3
- **Important**: `STREAK_MILESTONES` in const.py uses keys {3, 5, 10} for bonus points calculation, but this story uses {3, 5, 7} for analytics tracking. These are intentionally different - the analytics milestones track engagement achievements, while STREAK_MILESTONES awards bonus points
- Reaching 5 counts ONLY as 5+, not also as 3+ (each milestone counted once per streak)
- The legendary 7+ streak is rare and should have special visual treatment (golden border)
