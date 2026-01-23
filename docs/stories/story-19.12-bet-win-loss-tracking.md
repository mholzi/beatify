# Story 19.12: Bet Win/Loss Tracking

## Epic 19: Analytics Dashboard

## User Story

**As a** game administrator,
**I want to** see betting success rates,
**So that I** can understand if the betting mechanic is balanced and engaging.

---

## Overview

Add bet outcome tracking to the analytics system. When players place bets during gameplay, record whether the bet was won or lost. Display this information in a new "Betting" section on the analytics dashboard, showing total bets placed and win rate percentage across all games.

Betting is a core game mechanic (Story 5.3) where players can double-or-nothing on their round score. This tracking helps administrators understand if players are engaging with the betting feature and whether the win/loss ratio suggests a balanced mechanic.

---

## Acceptance Criteria

### AC1: Bet Outcome Recording
- [ ] **Given** a player places a bet during gameplay
- [ ] **When** the round ends
- [ ] **Then** the bet outcome (won/lost) is recorded in the game's bet tracking
- [ ] **And** bet counts are accumulated per game (total_bets, bets_won)

### AC2: Dashboard Betting Section
- [ ] **Given** the analytics dashboard
- [ ] **When** viewing a new "Betting" section
- [ ] **Then** betting stats are displayed:
  - Total bets placed
  - Bets won
  - Win rate percentage
- [ ] **And** section has appropriate icon (dice/gambling icon)

### AC3: Bet Persistence
- [ ] **Given** bet data is being collected
- [ ] **When** a game ends
- [ ] **Then** bet outcomes from that game are persisted to analytics storage
- [ ] **And** data survives Home Assistant restarts

### AC4: Empty State
- [ ] **Given** no bet data exists (new feature)
- [ ] **When** dashboard loads
- [ ] **Then** shows "No betting data yet" or zeros for all bet counts

### AC5: Period Filtering
- [ ] Betting stats respect the selected time period (7d, 30d, 90d, all)
- [ ] Recalculate when period filter is changed

---

## Technical Implementation

### Files to Modify

#### 1. Backend: `custom_components/beatify/analytics.py`

**Add to `GameRecord` TypedDict (after streak fields, around line 45):**

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
    streak_3_count: int
    streak_5_count: int
    streak_7_count: int
    # Story 19.12: Bet tracking
    total_bets: int      # Total bets placed in game
    bets_won: int        # Bets that won (doubled points)
```

**Add new method to `AnalyticsStorage` class (after `compute_streak_stats` method, around line 666):**

```python
def compute_bet_stats(
    self, period: str = "30d"
) -> dict[str, Any]:
    """
    Compute betting statistics for a given period (Story 19.12).

    Args:
        period: Time period - "7d", "30d", "90d", or "all"

    Returns:
        Dict with bet counts and win rate
    """
    now = int(time.time())

    # Calculate period boundaries
    days_map = {"7d": 7, "30d": 30, "90d": 90, "all": 365 * 10}
    days = days_map.get(period, 30)
    start_ts = now - (days * 86400)

    # Get games for current period
    games = self.get_games(start_date=start_ts, end_date=now)

    # Sum bet outcomes across all games
    total_bets = sum(g.get("total_bets", 0) for g in games)
    bets_won = sum(g.get("bets_won", 0) for g in games)

    # Calculate win rate (avoid division by zero)
    win_rate = (bets_won / total_bets * 100) if total_bets > 0 else 0.0

    return {
        "total_bets": total_bets,
        "bets_won": bets_won,
        "win_rate": round(win_rate, 1),
        "has_data": total_bets > 0,
    }
```

**Modify `compute_metrics` method return dict (around line 607) to include bet stats:**

```python
return {
    "period": period,
    "total_games": total_games,
    "avg_players_per_game": round(avg_players, 1),
    "avg_score": round(avg_score, 1),
    "error_rate": round(error_rate, 3),
    "peak_players": peak_players,
    "avg_rounds": round(avg_rounds, 1),
    "streak_stats": self.compute_streak_stats(period),
    # Story 19.12: Include bet stats
    "bet_stats": self.compute_bet_stats(period),
    "trends": {
        # ... existing trends ...
    },
    # ... rest of return dict ...
}
```

#### 2. Game State: `custom_components/beatify/game/state.py`

**Add bet tracking fields to `GameState.__init__` (after streak_achievements, around line 197):**

```python
# Story 19.11: Streak achievement tracking for analytics
self.streak_achievements: dict[str, int] = {
    "streak_3": 0,
    "streak_5": 0,
    "streak_7": 0,
}

# Story 19.12: Bet outcome tracking for analytics
self.bet_tracking: dict[str, int] = {
    "total_bets": 0,    # Total bets placed in game
    "bets_won": 0,      # Bets that won
}
```

**In `end_round` method (around line 1250-1252), add game-level tracking after existing bet tracking:**

The current code already tracks individual player bet outcomes and counts (lines 1238-1252):
```python
if player.bet_outcome == "won":
    player.bets_won += 1

# ... (superlative tracking)

# Track bets placed (AC3: Risk Taker)
if player.bet:
    player.bets_placed += 1
```

Add game-level bet tracking **inside** the existing `if player.bet:` block (after line 1252):

```python
# Track bets placed (AC3: Risk Taker)
if player.bet:
    player.bets_placed += 1
    # Story 19.12: Track game-level bet stats for analytics
    self.bet_tracking["total_bets"] += 1
    if player.bet_outcome == "won":
        self.bet_tracking["bets_won"] += 1
```

**NOTE**: This modifies the EXISTING `if player.bet:` block by adding 3 lines, not creating a new block.

**Modify `finalize_game` method (around line 441-453) to include bet data in return dict:**

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
        # Story 19.12: Include bet tracking
        "total_bets": self.bet_tracking.get("total_bets", 0),
        "bets_won": self.bet_tracking.get("bets_won", 0),
    }
```

**Reset bet tracking in `end_game` method (around line 503, after streak reset):**

```python
# Story 19.11: Reset streak tracking
self.streak_achievements = {"streak_3": 0, "streak_5": 0, "streak_7": 0}

# Story 19.12: Reset bet tracking
self.bet_tracking = {"total_bets": 0, "bets_won": 0}
```

**Reset bet tracking in `create_game` method (around line 283, after streak reset):**

```python
# Story 19.11: Reset streak tracking for new game
self.streak_achievements = {"streak_3": 0, "streak_5": 0, "streak_7": 0}

# Story 19.12: Reset bet tracking for new game
self.bet_tracking = {"total_bets": 0, "bets_won": 0}
```

#### 3. Stats Service: `custom_components/beatify/services/stats.py`

**Modify `record_game` method (around line 158-174) to pass bet data to analytics:**

Add bet fields to the `analytics_record` dict after streak fields:

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
    # Story 19.12: Bet tracking
    "total_bets": game_summary.get("total_bets", 0),
    "bets_won": game_summary.get("bets_won", 0),
}
await self._analytics.add_game(analytics_record)
```

#### 4. Frontend HTML: `custom_components/beatify/www/analytics.html`

**Add Betting Section after the Streak Achievements section (after line 124, before the loading state). Place it between the streak section and the loading/error state:**

```html
<!-- Story 19.12: Bet Win/Loss Tracking Section -->
<section class="betting-analytics" aria-labelledby="betting-stats-heading">
    <h2 class="section-header" id="betting-stats-heading">
        <span class="section-icon" aria-hidden="true">🎲</span>
        <span data-i18n="analyticsDashboard.bettingStats">Betting Statistics</span>
    </h2>

    <div class="betting-cards" id="betting-cards">
        <div class="betting-card" id="betting-total-card">
            <div class="betting-icon" aria-hidden="true">🎯</div>
            <div class="betting-value" id="betting-total-value">--</div>
            <div class="betting-label">
                <span data-i18n="analyticsDashboard.totalBets">Total Bets</span>
            </div>
            <div class="betting-description" data-i18n="analyticsDashboard.totalBetsDesc">Bets placed</div>
        </div>

        <div class="betting-card" id="betting-won-card">
            <div class="betting-icon" aria-hidden="true">🏆</div>
            <div class="betting-value" id="betting-won-value">--</div>
            <div class="betting-label">
                <span data-i18n="analyticsDashboard.betsWon">Bets Won</span>
            </div>
            <div class="betting-description" data-i18n="analyticsDashboard.betsWonDesc">Double points!</div>
        </div>

        <div class="betting-card betting-card--highlight" id="betting-rate-card">
            <div class="betting-icon" aria-hidden="true">📊</div>
            <div class="betting-value" id="betting-rate-value">--</div>
            <div class="betting-label">
                <span data-i18n="analyticsDashboard.winRate">Win Rate</span>
            </div>
            <div class="betting-description" data-i18n="analyticsDashboard.winRateDesc">Success percentage</div>
        </div>
    </div>

    <!-- Empty State (AC4) -->
    <div class="empty-state hidden" id="betting-empty">
        <div class="empty-icon" aria-hidden="true">🎲</div>
        <p data-i18n="analyticsDashboard.noBettingData">No betting data yet</p>
        <p class="empty-hint" data-i18n="analyticsDashboard.bettingHint">Players can bet to double their points on confident guesses</p>
    </div>
</section>
```

#### 5. Frontend CSS: `custom_components/beatify/www/css/analytics.css`

**Add betting section styles (after the streak styles, around line 428):**

```css
/* =====================================================
   Betting Statistics (Story 19.12)
   ===================================================== */

.betting-analytics {
    margin-top: var(--spacing-xl, 32px);
}

.betting-cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: var(--spacing-md, 16px);
    margin-top: var(--spacing-md, 16px);
}

.betting-card {
    background: var(--surface-color, #1a1a2e);
    border-radius: var(--border-radius, 12px);
    padding: var(--spacing-lg, 24px);
    text-align: center;
    border: 1px solid var(--surface-border, #333);
    transition: transform 0.2s ease, box-shadow 0.2s ease;
}

.betting-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
}

.betting-card--highlight {
    background: linear-gradient(135deg, var(--surface-color, #1a1a2e) 0%, rgba(0, 245, 255, 0.1) 100%);
    border-color: var(--neon-cyan, #00f5ff);
}

.betting-icon {
    font-size: 2rem;
    margin-bottom: var(--spacing-sm, 8px);
}

.betting-value {
    font-size: 2.5rem;
    font-weight: 700;
    color: var(--neon-cyan, #00f5ff);
    font-family: 'Outfit', sans-serif;
}

.betting-card--highlight .betting-value {
    color: var(--neon-purple, #9d4edd);
}

.betting-label {
    font-size: var(--font-size-sm, 0.875rem);
    color: var(--text-secondary, #a0a0a0);
    margin-top: var(--spacing-xs, 4px);
}

.betting-description {
    font-size: var(--font-size-xs, 0.75rem);
    color: var(--text-muted, #666);
    margin-top: var(--spacing-xs, 4px);
}

/* Win rate color indicators */
.betting-value.win-rate-high {
    color: var(--success-color, #00ff88) !important;
}

.betting-value.win-rate-mid {
    color: #ffc107 !important;
}

.betting-value.win-rate-low {
    color: var(--error-color, #ff4444) !important;
}
```

#### 6. Frontend JavaScript: `custom_components/beatify/www/js/analytics.js`

**Add betting rendering function (after `renderStreakStats` function, around line 124):**

```javascript
/**
 * Render betting statistics section (Story 19.12)
 * @param {Object} betStats - Betting statistics from API
 */
function renderBetStats(betStats) {
    var cardsEl = document.getElementById('betting-cards');
    var emptyEl = document.getElementById('betting-empty');

    // Check for data
    if (!betStats || !betStats.has_data) {
        if (cardsEl) cardsEl.classList.add('hidden');
        if (emptyEl) emptyEl.classList.remove('hidden');
        return;
    }

    if (cardsEl) cardsEl.classList.remove('hidden');
    if (emptyEl) emptyEl.classList.add('hidden');

    // Update betting values
    updateBettingCard('betting-total-value', betStats.total_bets);
    updateBettingCard('betting-won-value', betStats.bets_won);
    updateBettingCardWithRate('betting-rate-value', betStats.win_rate);
}

/**
 * Update a betting card value
 * @param {string} id - Element ID
 * @param {number} value - Bet count
 */
function updateBettingCard(id, value) {
    var el = document.getElementById(id);
    if (el) {
        el.textContent = value > 0 ? value : '--';
    }
}

/**
 * Update betting card with win rate and color coding
 * @param {string} id - Element ID
 * @param {number} rate - Win rate percentage
 */
function updateBettingCardWithRate(id, rate) {
    var el = document.getElementById(id);
    if (!el) return;

    // Remove existing color classes
    el.classList.remove('win-rate-high', 'win-rate-mid', 'win-rate-low');

    if (rate > 0) {
        el.textContent = rate.toFixed(1) + '%';
        // Color code based on win rate
        if (rate >= 60) {
            el.classList.add('win-rate-high');
        } else if (rate >= 40) {
            el.classList.add('win-rate-mid');
        } else {
            el.classList.add('win-rate-low');
        }
    } else {
        el.textContent = '--';
    }
}
```

**Modify `renderStats` function (around line 76-86) to include betting rendering:**

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

    // Story 19.12: Betting Statistics
    if (data.bet_stats) {
        renderBetStats(data.bet_stats);
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
"bettingStats": "Betting Statistics",
"totalBets": "Total Bets",
"totalBetsDesc": "Bets placed",
"betsWon": "Bets Won",
"betsWonDesc": "Double points!",
"winRate": "Win Rate",
"winRateDesc": "Success percentage",
"noBettingData": "No betting data yet",
"bettingHint": "Players can bet to double their points on confident guesses"
```

**Add to `custom_components/beatify/www/i18n/de.json` under `analyticsDashboard`:**

```json
"bettingStats": "Wett-Statistiken",
"totalBets": "Wetten Gesamt",
"totalBetsDesc": "Platzierte Wetten",
"betsWon": "Gewonnene Wetten",
"betsWonDesc": "Doppelte Punkte!",
"winRate": "Gewinnrate",
"winRateDesc": "Erfolgsprozentsatz",
"noBettingData": "Noch keine Wettdaten",
"bettingHint": "Spieler konnen wetten, um ihre Punkte bei sicheren Schatzungen zu verdoppeln"
```

**Add to `custom_components/beatify/www/i18n/es.json` under `analyticsDashboard`:**

```json
"bettingStats": "Estadisticas de Apuestas",
"totalBets": "Apuestas Totales",
"totalBetsDesc": "Apuestas realizadas",
"betsWon": "Apuestas Ganadas",
"betsWonDesc": "Puntos dobles!",
"winRate": "Tasa de Victoria",
"winRateDesc": "Porcentaje de exito",
"noBettingData": "Sin datos de apuestas todavia",
"bettingHint": "Los jugadores pueden apostar para duplicar sus puntos en adivinanzas seguras"
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
  "bet_stats": {
    "total_bets": 234,
    "bets_won": 112,
    "win_rate": 47.9,
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
|  Betting Statistics                                                               |
+-----------------------------------------------------------------------------------+
|                                                                                   |
|  +------------------+  +------------------+  +----------------------+             |
|  |       🎯         |  |       🏆         |  |       📊             |             |
|  |                  |  |                  |  |                      |             |
|  |       234        |  |       112        |  |       47.9%          |             |
|  |    Total Bets    |  |    Bets Won      |  |     Win Rate         |             |
|  |   Bets placed    |  |  Double points!  |  |  Success percentage  |             |
|  +------------------+  +------------------+  +----------------------+             |
|                                              (highlighted card)                   |
+-----------------------------------------------------------------------------------+
```

---

## Existing Code Reference

### How Betting Currently Works (Story 5.3)

**Player tracking in `game/player.py`:**
- `bet: bool = False` - Whether player placed a bet this round
- `bet_outcome: str | None = None` - "won", "lost", or None
- `bets_won: int = 0` - Cumulative successful bets (for final stats)
- `bets_placed: int = 0` - Total bets placed (for superlatives)

**Scoring in `game/scoring.py` (`apply_bet_multiplier`):**
- If bet and scored points (>0): double the score, outcome="won"
- If bet and 0 points: score stays 0, outcome="lost"
- If no bet: score unchanged, outcome=None

**Current tracking in `game/state.py` `end_round` method (lines 1235-1256):**
```python
# Track cumulative stats (Story 5.6) - AFTER all scoring
player.rounds_played += 1
player.best_streak = max(player.best_streak, player.streak)
if player.bet_outcome == "won":
    player.bets_won += 1

# Track superlative data (Story 15.2)
# ... (submission time tracking)

# Track bets placed (AC3: Risk Taker)
if player.bet:
    player.bets_placed += 1

# Track close calls - +/-1 year but not exact (AC3: Close Calls)
if player.years_off == 1:
    player.close_calls += 1
```

The Story 19.12 implementation adds game-level aggregation of this per-player tracking to persist in analytics.

---

## Edge Cases

1. **No games played**: All bet counts show "--", empty state message displayed
2. **Games with no bets**: All counts show 0 (not "--"), has_data is false
3. **100% or 0% win rate**: Display edge case rates normally (100.0% or 0.0%)
4. **Single bet in game**: Stats still recorded and calculated correctly
5. **Period filtering**: Only bets from games within the period are counted
6. **Old games without bet data**: Show 0 for bet fields (backwards compatible)
7. **Player bets but doesn't submit guess**: Bet not counted (bet is only valid with submission)
8. **Multiple players betting in same round**: Each bet tracked independently

---

## Definition of Done

- [ ] `GameRecord` TypedDict includes bet count fields (total_bets, bets_won)
- [ ] `GameState` tracks bet outcomes during gameplay via bet_tracking dict
- [ ] `finalize_game()` returns bet counts
- [ ] `record_game()` passes bet data to analytics storage
- [ ] `compute_bet_stats()` method added to `AnalyticsStorage`
- [ ] `compute_metrics()` includes `bet_stats` in response
- [ ] HTML betting section added to analytics.html
- [ ] CSS styles for betting cards
- [ ] JavaScript renders betting data
- [ ] Empty state displays when no betting data
- [ ] Period filtering works for betting stats
- [ ] Win rate color coding implemented (green >60%, yellow 40-60%, red <40%)
- [ ] Data persists after HA restart
- [ ] Translations added for English, German, and Spanish
- [ ] Unit tests for bet tracking logic
- [ ] Manual testing completed for all scenarios

---

## Testing Checklist

### Unit Tests
- [ ] `GameState.bet_tracking` increments correctly when player bets
- [ ] Bet only counted when player has submitted (not for non-submitters)
- [ ] Won bet increments both total_bets and bets_won
- [ ] Lost bet increments only total_bets
- [ ] `finalize_game()` returns correct bet counts
- [ ] `compute_bet_stats()` calculates win rate correctly
- [ ] `compute_bet_stats()` returns has_data=false when no bets
- [ ] Period filtering excludes games outside range
- [ ] Division by zero handled (0 total bets = 0% win rate)

### Integration Tests
- [ ] API returns bet_stats in response
- [ ] Bet data persists to analytics.json
- [ ] Data survives HA restart
- [ ] Old game records without bet fields don't break analytics

### Manual Testing
- [ ] Play game with bets placed - verify counts increment
- [ ] Play game with won bets - verify win count and rate
- [ ] Play game with lost bets - verify loss tracked correctly
- [ ] Play game with no bets - verify empty state shows
- [ ] Load dashboard with no bet data - verify empty state
- [ ] Switch time periods - verify bet stats update
- [ ] Verify win rate card has highlight styling
- [ ] Verify win rate color coding (high/mid/low)
- [ ] Test all three languages

---

## Story Points: 5

## Priority: Medium

## Dependencies
- Story 19.1 (Analytics Infrastructure) - Must be completed
- Story 19.2 (Analytics Dashboard) - Must be completed
- Story 5.3 (Betting Mechanic) - Already implemented (bet tracking exists on player)
- Story 19.11 (Streak Tracking) - Similar pattern, can reference implementation

---

## Effort Estimate: ~4-5 hours

---

## Related Stories
- Story 5.3: Betting Mechanic (existing bet logic)
- Story 15.2: Superlatives - Risk Taker award (bets_placed tracking)
- Story 19.11: Streak Tracking (similar analytics pattern)
- Story 19.13: Analytics UI Polish (may consolidate UI changes)

---

## Notes

- Betting is tracked per-player in `PlayerSession` with `bet`, `bet_outcome`, `bets_won`, `bets_placed`
- The `apply_bet_multiplier` function in `scoring.py` determines win/loss outcome
- Win rate around 50% suggests balanced mechanic (risk/reward is even)
- Significantly higher win rate may indicate players only bet when confident
- This story aggregates per-player bet data into game-level analytics, similar to how Story 19.11 handles streaks
- The betting section should appear AFTER the streak section and BEFORE the playlist section on the dashboard
