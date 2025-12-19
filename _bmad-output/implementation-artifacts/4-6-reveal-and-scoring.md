# Story 4.6: Reveal & Scoring

Status: ready-for-dev

## Story

As a **player**,
I want **to see the correct answer, song info, and my score**,
so that **I get the satisfying payoff of finding out how I did**.

## Acceptance Criteria

1. **AC1:** Given round transitions to REVEAL, When reveal displays, Then correct year is shown prominently (FR30) And song title and artist are displayed And fun_fact from playlist is shown (if available)

2. **AC2:** Given player submitted a guess, When reveal displays, Then player sees their personal result (FR31): their guessed year, the correct year, how many years off they were, and points earned this round

3. **AC3:** Given player's guess is evaluated, When score is calculated (FR32), Then accuracy scoring applies: exact match = 10 points, within ±3 years = 5 points, within ±5 years = 1 point, more than 5 years off = 0 points

4. **AC4:** Given player did not submit, When reveal displays, Then player sees "No guess - 0 points"

5. **AC5:** Given reveal phase completes, When admin triggers next round (or auto-advance), Then game returns to PLAYING state with next song

## Tasks / Subtasks

**DEPENDENCY:** Requires Stories 4.1-4.5 for complete round flow.

- [ ] **Task 1: Implement scoring module** (AC: #3)
  - [ ] 1.1 Create `game/scoring.py` with `calculate_accuracy_score()` function
  - [ ] 1.2 Implement exact match logic (0 diff = 10 points)
  - [ ] 1.3 Implement ±3 years logic (1-3 diff = 5 points)
  - [ ] 1.4 Implement ±5 years logic (4-5 diff = 1 point)
  - [ ] 1.5 Implement >5 years logic (>5 diff = 0 points)
  - [ ] 1.6 Return score as integer

- [ ] **Task 2: Integrate scoring in end_round()** (AC: #2, #3, #4)
  - [ ] 2.1 In `end_round()`, get correct year from current_song
  - [ ] 2.2 For each player who submitted, calculate accuracy score
  - [ ] 2.3 Store round_score on PlayerSession
  - [ ] 2.4 Add round_score to player's total score
  - [ ] 2.5 For non-submitters, set round_score = 0

- [ ] **Task 3: Update reveal-view HTML** (AC: #1, #2, #4)
  - [ ] 3.1 Replace placeholder content in #reveal-view
  - [ ] 3.2 Add correct year display (large, prominent)
  - [ ] 3.3 Add song info display (title, artist)
  - [ ] 3.4 Add fun_fact display (if available)
  - [ ] 3.5 Add personal result section

- [ ] **Task 4: Style reveal view** (AC: #1, #2)
  - [ ] 4.1 Create `.reveal-container` layout styles
  - [ ] 4.2 Create `.correct-year` styles (large, celebratory)
  - [ ] 4.3 Create `.song-info` styles
  - [ ] 4.4 Create `.fun-fact` styles (distinctive callout)
  - [ ] 4.5 Create `.personal-result` styles
  - [ ] 4.6 Add animations for score reveal

- [ ] **Task 5: Implement updateRevealView()** (AC: #1, #2, #4)
  - [ ] 5.1 Render correct year from data.song.year
  - [ ] 5.2 Render song title and artist
  - [ ] 5.3 Render fun_fact if available
  - [ ] 5.4 Calculate and display years off
  - [ ] 5.5 Display round score earned
  - [ ] 5.6 Handle missed round case

- [ ] **Task 6: Add personal result details** (AC: #2)
  - [ ] 6.1 Show player's guessed year
  - [ ] 6.2 Show correct year
  - [ ] 6.3 Show difference (e.g., "3 years off")
  - [ ] 6.4 Show points earned with explanation

- [ ] **Task 7: State broadcast with reveal data** (AC: #1, #2)
  - [ ] 7.1 Include song.year in REVEAL state
  - [ ] 7.2 Include song.fun_fact in REVEAL state
  - [ ] 7.3 Include each player's guess and round_score
  - [ ] 7.4 Include years_off for each player

- [ ] **Task 8: Handle next round transition** (AC: #5)
  - [ ] 8.1 Add "Next Round" button for admin in reveal view
  - [ ] 8.2 On click, send admin action next_round
  - [ ] 8.3 Server starts next round via start_round()
  - [ ] 8.4 Client transitions back to game-view

- [ ] **Task 9: Handle last round -> END** (AC: #5)
  - [ ] 9.1 If last_round is True, show "Final Results" instead
  - [ ] 9.2 Clicking "Final Results" transitions to END phase
  - [ ] 9.3 END phase shows final leaderboard (Story 5.6)

- [ ] **Task 10: Unit tests for scoring** (AC: #3)
  - [ ] 10.1 Test: exact match returns 10
  - [ ] 10.2 Test: 1 year off returns 5
  - [ ] 10.3 Test: 3 years off returns 5
  - [ ] 10.4 Test: 4 years off returns 1
  - [ ] 10.5 Test: 5 years off returns 1
  - [ ] 10.6 Test: 6 years off returns 0
  - [ ] 10.7 Test: 100 years off returns 0

- [ ] **Task 11: Integration tests** (AC: #2, #3)
  - [ ] 11.1 Test: reveal state includes song.year
  - [ ] 11.2 Test: player round_score calculated correctly
  - [ ] 11.3 Test: total score updated

- [ ] **Task 12: E2E tests** (AC: #1, #2)
  - [ ] 12.1 Test: reveal view shows correct year
  - [ ] 12.2 Test: reveal view shows player result
  - [ ] 12.3 Test: next round button advances game

- [ ] **Task 13: Verify no regressions**
  - [ ] 13.1 Run `pytest tests/` - all pass
  - [ ] 13.2 Run `ruff check` - no new issues
  - [ ] 13.3 Test full round flow end-to-end

## Dev Notes

### New Files to Create

| File | Purpose |
|------|---------|
| `game/scoring.py` | Score calculation logic |

### Files to Modify

| File | Action |
|------|--------|
| `www/player.html` | Replace reveal-view placeholder |
| `www/js/player.js` | Implement updateRevealView() |
| `www/css/styles.css` | Add reveal view styles |
| `game/state.py` | Integrate scoring in end_round() |

### Scoring Module

```python
# game/scoring.py

"""Scoring calculation for Beatify."""


def calculate_accuracy_score(guess: int, actual: int) -> int:
    """Calculate accuracy points based on guess vs actual year.

    Scoring rules (FR32):
    - Exact match: 10 points
    - Within ±3 years: 5 points
    - Within ±5 years: 1 point
    - More than 5 years off: 0 points

    Args:
        guess: Player's guessed year
        actual: Correct year from playlist

    Returns:
        Points earned (0, 1, 5, or 10)
    """
    diff = abs(guess - actual)

    if diff == 0:
        return 10
    elif diff <= 3:
        return 5
    elif diff <= 5:
        return 1
    else:
        return 0


def calculate_years_off_text(diff: int) -> str:
    """Get human-readable text for years difference.

    Args:
        diff: Absolute difference between guess and actual

    Returns:
        Text like "Exact!", "2 years off", etc.
    """
    if diff == 0:
        return "Exact!"
    elif diff == 1:
        return "1 year off"
    else:
        return f"{diff} years off"
```

### Integration in end_round()

```python
# game/state.py

from .scoring import calculate_accuracy_score

async def end_round(self) -> None:
    """End the current round and transition to REVEAL."""
    # Cancel timer if still running
    if self._timer_task and not self._timer_task.done():
        self._timer_task.cancel()
        try:
            await self._timer_task
        except asyncio.CancelledError:
            pass
        self._timer_task = None

    # Get correct year
    correct_year = self.current_song.get("year") if self.current_song else None

    # Calculate scores for all players
    for player in self.players.values():
        if player.submitted and correct_year is not None:
            # Calculate accuracy score
            player.round_score = calculate_accuracy_score(
                player.current_guess, correct_year
            )
            player.years_off = abs(player.current_guess - correct_year)
            player.missed_round = False

            # Update streak (scoring = continuing streak)
            if player.round_score > 0:
                player.streak += 1
            else:
                player.streak = 0

            # Add to total score
            player.score += player.round_score
        else:
            # Non-submitter
            player.round_score = 0
            player.years_off = None
            player.missed_round = True
            player.streak = 0  # Break streak

    # Transition to REVEAL
    self.transition_to(GamePhase.REVEAL)

    # Invoke callback to broadcast state
    if self._on_round_end:
        await self._on_round_end()
```

### PlayerSession Additions

```python
# game/player.py

@dataclass
class PlayerSession:
    # ... existing fields ...

    # Round results
    round_score: int = 0
    years_off: int | None = None
```

### State Broadcast for REVEAL

```python
# game/state.py - Update get_reveal_players_state()

def get_reveal_players_state(self) -> list[dict[str, Any]]:
    """Get player state with reveal info."""
    players = []
    for player in self.players.values():
        player_data = {
            "name": player.name,
            "score": player.score,
            "streak": player.streak,
            "is_admin": player.is_admin,
            "connected": player.connected,
            "guess": player.current_guess,
            "round_score": player.round_score,
            "years_off": player.years_off,
            "missed_round": player.missed_round,
        }
        players.append(player_data)

    # Sort by score descending for leaderboard preview
    players.sort(key=lambda p: p["score"], reverse=True)
    return players
```

### HTML Reveal View

```html
<!-- Replace #reveal-view content in player.html -->
<div id="reveal-view" class="view hidden">
    <div class="reveal-container">
        <!-- Round Info -->
        <div class="reveal-round-info">
            Round <span id="reveal-round">1</span> of <span id="reveal-total">10</span>
        </div>

        <!-- Album Cover (smaller) -->
        <div class="reveal-album">
            <img id="reveal-album-cover"
                 src="/beatify/static/img/no-artwork.svg"
                 alt="Album Cover"
                 class="reveal-album-cover">
        </div>

        <!-- Correct Year -->
        <div class="correct-year-container">
            <div class="correct-year-label">The year was</div>
            <div id="correct-year" class="correct-year">1984</div>
        </div>

        <!-- Song Info -->
        <div class="song-info">
            <div id="song-title" class="song-title">Wake Me Up Before You Go-Go</div>
            <div id="song-artist" class="song-artist">Wham!</div>
        </div>

        <!-- Fun Fact -->
        <div id="fun-fact-container" class="fun-fact-container hidden">
            <div class="fun-fact-icon">💡</div>
            <div id="fun-fact" class="fun-fact-text"></div>
        </div>

        <!-- Personal Result -->
        <div id="personal-result" class="personal-result">
            <div class="result-header">Your Result</div>
            <div id="result-content" class="result-content">
                <!-- Populated dynamically -->
            </div>
        </div>

        <!-- Admin Controls -->
        <div id="reveal-admin-controls" class="reveal-admin-controls hidden">
            <button id="next-round-btn" class="next-round-btn">
                Next Round
            </button>
        </div>
    </div>
</div>
```

### CSS Reveal Styles

```css
/* Reveal View */
.reveal-container {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 24px;
    max-width: 400px;
    margin: 0 auto;
    text-align: center;
}

.reveal-round-info {
    font-size: 14px;
    color: #6b7280;
    margin-bottom: 16px;
}

/* Album Cover (smaller for reveal) */
.reveal-album {
    margin-bottom: 24px;
}

.reveal-album-cover {
    width: 150px;
    height: 150px;
    object-fit: cover;
    border-radius: 12px;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.1);
}

/* Correct Year */
.correct-year-container {
    margin-bottom: 16px;
}

.correct-year-label {
    font-size: 16px;
    color: #6b7280;
    margin-bottom: 8px;
}

.correct-year {
    font-size: 72px;
    font-weight: 800;
    color: #10b981;
    font-variant-numeric: tabular-nums;
    animation: reveal-pop 0.5s ease-out;
}

@keyframes reveal-pop {
    0% {
        transform: scale(0.5);
        opacity: 0;
    }
    70% {
        transform: scale(1.1);
    }
    100% {
        transform: scale(1);
        opacity: 1;
    }
}

/* Song Info */
.song-info {
    margin-bottom: 16px;
}

.song-title {
    font-size: 20px;
    font-weight: 600;
    color: #1f2937;
    margin-bottom: 4px;
}

.song-artist {
    font-size: 16px;
    color: #6b7280;
}

/* Fun Fact */
.fun-fact-container {
    display: flex;
    align-items: flex-start;
    gap: 8px;
    background: #fef3c7;
    padding: 12px 16px;
    border-radius: 12px;
    margin-bottom: 24px;
    text-align: left;
    max-width: 100%;
}

.fun-fact-icon {
    font-size: 20px;
    flex-shrink: 0;
}

.fun-fact-text {
    font-size: 14px;
    color: #92400e;
    line-height: 1.4;
}

/* Personal Result */
.personal-result {
    width: 100%;
    background: #f3f4f6;
    padding: 16px;
    border-radius: 12px;
    margin-bottom: 24px;
}

.result-header {
    font-size: 14px;
    font-weight: 600;
    color: #6b7280;
    margin-bottom: 12px;
}

.result-content {
    display: flex;
    flex-direction: column;
    gap: 8px;
}

.result-row {
    display: flex;
    justify-content: space-between;
    align-items: center;
}

.result-label {
    font-size: 14px;
    color: #6b7280;
}

.result-value {
    font-size: 16px;
    font-weight: 600;
    color: #1f2937;
}

.result-value.is-exact {
    color: #10b981;
}

.result-value.is-close {
    color: #f59e0b;
}

.result-value.is-far {
    color: #ef4444;
}

.result-score {
    font-size: 32px;
    font-weight: 700;
    color: #6366f1;
    margin-top: 8px;
}

.result-missed {
    font-size: 16px;
    color: #ef4444;
    font-weight: 600;
}

/* Admin Controls */
.reveal-admin-controls {
    margin-top: 16px;
}

.next-round-btn {
    padding: 16px 32px;
    font-size: 18px;
    font-weight: 600;
    color: white;
    background: #6366f1;
    border: none;
    border-radius: 12px;
    cursor: pointer;
    transition: all 0.2s ease;
}

.next-round-btn:hover {
    background: #4f46e5;
}

.next-round-btn.is-final {
    background: #10b981;
}

.next-round-btn.is-final:hover {
    background: #059669;
}
```

### JavaScript Implementation

```javascript
// player.js - Update reveal handling

function updateRevealView(data) {
    const song = data.song || {};
    const players = data.players || [];

    // Update round info
    const roundEl = document.getElementById('reveal-round');
    const totalEl = document.getElementById('reveal-total');
    if (roundEl) roundEl.textContent = data.round || 1;
    if (totalEl) totalEl.textContent = data.total_rounds || 10;

    // Update album cover
    const albumCover = document.getElementById('reveal-album-cover');
    if (albumCover) {
        albumCover.src = song.album_art || '/beatify/static/img/no-artwork.svg';
    }

    // Update correct year
    const correctYear = document.getElementById('correct-year');
    if (correctYear) {
        correctYear.textContent = song.year || '????';
    }

    // Update song info
    const titleEl = document.getElementById('song-title');
    const artistEl = document.getElementById('song-artist');
    if (titleEl) titleEl.textContent = song.title || 'Unknown Song';
    if (artistEl) artistEl.textContent = song.artist || 'Unknown Artist';

    // Update fun fact
    const funFactContainer = document.getElementById('fun-fact-container');
    const funFactText = document.getElementById('fun-fact');
    if (funFactContainer && funFactText) {
        if (song.fun_fact) {
            funFactText.textContent = song.fun_fact;
            funFactContainer.classList.remove('hidden');
        } else {
            funFactContainer.classList.add('hidden');
        }
    }

    // Find current player's result
    const currentPlayer = players.find(p => p.name === playerName);
    renderPersonalResult(currentPlayer, song.year);

    // Show admin controls if admin
    const adminControls = document.getElementById('reveal-admin-controls');
    const nextRoundBtn = document.getElementById('next-round-btn');
    if (adminControls && currentPlayer && currentPlayer.is_admin) {
        adminControls.classList.remove('hidden');

        // Update button text for last round
        if (nextRoundBtn) {
            if (data.last_round) {
                nextRoundBtn.textContent = 'Final Results';
                nextRoundBtn.classList.add('is-final');
            } else {
                nextRoundBtn.textContent = 'Next Round';
                nextRoundBtn.classList.remove('is-final');
            }
        }
    } else if (adminControls) {
        adminControls.classList.add('hidden');
    }
}

function renderPersonalResult(player, correctYear) {
    const resultContent = document.getElementById('result-content');
    if (!resultContent) return;

    if (!player) {
        resultContent.innerHTML = '<div class="result-missed">Player not found</div>';
        return;
    }

    if (player.missed_round) {
        resultContent.innerHTML = `
            <div class="result-missed">No guess submitted</div>
            <div class="result-score">0 pts</div>
        `;
        return;
    }

    const yearsOff = player.years_off || 0;
    let yearsOffText = yearsOff === 0 ? 'Exact!' :
                       yearsOff === 1 ? '1 year off' :
                       `${yearsOff} years off`;

    let resultClass = yearsOff === 0 ? 'is-exact' :
                      yearsOff <= 3 ? 'is-close' : 'is-far';

    resultContent.innerHTML = `
        <div class="result-row">
            <span class="result-label">Your guess</span>
            <span class="result-value">${player.guess}</span>
        </div>
        <div class="result-row">
            <span class="result-label">Correct year</span>
            <span class="result-value">${correctYear}</span>
        </div>
        <div class="result-row">
            <span class="result-label">Accuracy</span>
            <span class="result-value ${resultClass}">${yearsOffText}</span>
        </div>
        <div class="result-score">+${player.round_score} pts</div>
    `;
}

// Add event listener for next round button
document.addEventListener('DOMContentLoaded', function() {
    const nextRoundBtn = document.getElementById('next-round-btn');
    if (nextRoundBtn) {
        nextRoundBtn.addEventListener('click', handleNextRound);
    }
});

function handleNextRound() {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({
            type: 'admin',
            action: 'next_round'
        }));
    }
}
```

### Architecture Compliance

- **Scoring Formula:** Exact implementation per project-context.md
- **State Transitions:** REVEAL -> PLAYING (next round) or END
- **Song Data:** Year and fun_fact revealed only in REVEAL phase
- **Mobile-first:** Responsive design, touch-friendly

### Anti-Patterns to Avoid

- Do NOT reveal year/fun_fact during PLAYING phase
- Do NOT modify scoring formula without updating project-context.md
- Do NOT skip streak reset for non-submitters
- Do NOT allow next round during PLAYING (only REVEAL)

### Previous Story Learnings

- View transitions well established
- Admin controls pattern from lobby works
- State broadcast includes all needed data
- Animations improve engagement

### Epic 5 Preparation

This story provides foundation for:
- **5.1:** Speed bonus calculation (extends calculate_accuracy_score)
- **5.2:** Streak tracking (player.streak already tracked)
- **5.3:** Betting mechanic (multiplier on round_score)
- **5.5/5.6:** Leaderboard (players sorted by score)

### References

- [Source: epics.md#Story-4.6] - FR30, FR31, FR32
- [Source: project-context.md#Scoring-Algorithm] - Exact scoring formula
- [Source: architecture.md#Playlist-Data-Format] - fun_fact field
- [Source: architecture.md#WebSocket-Architecture] - State schema

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

### File List
