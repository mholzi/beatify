# Beatify Game Logic Flow Analysis

Full logical flow analysis from player and admin perspectives, covering winning conditions,
power-ups (steal, betting, challenges), and identified issues.

## 1. Game Lifecycle (Admin Perspective)

### Phase Transitions

```
LOBBY -> PLAYING -> REVEAL -> PLAYING -> ... -> REVEAL -> END -> LOBBY
                                                          |
                                                       REMATCH -> LOBBY
Any phase -> PAUSED -> (previous phase)
```

### Admin Flow

1. **Create Game** (HTTP POST `/beatify/api/start-game`)
   - Validates playlists, media player, provider, platform compatibility
   - Creates `GameState` with unique `game_id` and `admin_token` (`secrets.token_urlsafe`)
   - Phase set to `LOBBY`
   - Optional: configures Party Lights, TTS announcements

2. **Players Join** (WebSocket `join` message with `is_admin: true`)
   - First admin claim only allowed during LOBBY phase
   - Admin reconnection uses case-insensitive name matching
   - If game is PAUSED due to admin disconnect, reconnecting admin auto-resumes it

3. **Start Gameplay** (HTTP POST `/beatify/api/start-gameplay` or WebSocket `admin` -> `start_game`)
   - WebSocket path calls `start_round()` directly (skips `start_game()`)
   - HTTP path validates LOBBY phase, sets round_end callback, starts first round
   - Begins song playback, sets deadline timer

4. **Round Loop** (WebSocket `admin` -> `next_round`)
   - From PLAYING: force-ends current round -> REVEAL
   - From REVEAL + not last round: starts new round -> PLAYING
   - From REVEAL + last round: finalizes stats -> END
   - Admin can also skip songs, adjust volume, seek forward

5. **End Game Early** (WebSocket `admin` -> `end_game`)
   - Only allowed from PLAYING or REVEAL phase
   - Records stats, advances to END with all players preserved

6. **Dismiss Game** (WebSocket `admin` -> `dismiss_game`)
   - Only from END phase. Fully resets game state and clears all players

7. **Rematch** (WebSocket `admin` -> `rematch_game` or HTTP `/beatify/api/rematch-game`)
   - Only from END phase
   - Preserves connected players, resets all scores to 0
   - Generates new `game_id` and `admin_token`
   - Re-creates PlaylistManager with fresh song list

### Pause/Resume

- **Auto-pause**: Admin disconnect triggers 5-second grace period, then game pauses
- **Resume**: Admin reconnects (by name or session_id), game resumes
- Timer remaining is recalculated on resume; if expired during pause, round ends immediately

---

## 2. Player Flow

### Join & Reconnect

1. **Fresh Join** (`join` message)
   - Name validated: 1-20 chars, trimmed, case-insensitive duplicate check
   - Allowed during LOBBY, PLAYING, or REVEAL (rejected during END)
   - Late joiners (not LOBBY) receive average score of players with `rounds_played > 0`
   - Max 20 players enforced

2. **Session Reconnection** (`reconnect` with `session_id`)
   - Restores WebSocket connection; preserves all score/state
   - Handles dual-tab: old tab receives `SESSION_TAKEOVER` and is closed
   - Admin reconnection cancels pause timer and resumes game if paused

3. **Disconnect Handling**
   - Player marked `connected=false` but stays in game indefinitely
   - Admin disconnect: 5-second grace, then game auto-pauses
   - Disconnected players still count toward MAX_PLAYERS (20) limit

4. **Intentional Leave** (`leave` message)
   - Admin cannot leave (must end game instead)
   - Regular players are fully removed from the game

### Submission Flow

1. **Submit Year Guess** (`submit` message)
   - Validated: PLAYING phase, not already submitted, deadline not passed, year 1950-2026
   - Optional `bet` flag for double-or-nothing
   - After submission, checks if all connected players are done for early reveal

2. **Artist Challenge** (`artist_guess` message)
   - Only during PLAYING phase, only if artist challenge is active this round
   - Case-insensitive comparison against correct artist
   - First correct guess wins 5 bonus points; subsequent correct get acknowledgment only

3. **Movie Quiz** (`movie_guess` message)
   - Only during PLAYING phase, only if movie challenge is active this round
   - Speed-ranked bonus: 5/3/1 points for 1st/2nd/3rd correct guess
   - One guess per player (duplicate guesses return `already_guessed: true`)

### Early Reveal

All connected players must complete all required guesses:
- Year guess submitted
- If artist challenge active and at least one player guessed: all connected must guess
  - Unless challenge already has a winner (others are not blocked)
- If movie challenge active and at least one player guessed: all connected must guess
  - Unless challenge already has correct guesses

---

## 3. Power-Up System

### 3.1 Steal

**Unlock**: Achieve 3 consecutive correct answers (streak = `STEAL_UNLOCK_STREAK`)
- "Correct" = base accuracy score > 0 (at least within near range)

**Usage Flow**:
1. Player sends `get_steal_targets` -> receives list of submitted players
2. Player sends `steal` with target name
3. Target's `current_guess` is copied to stealer
4. Stealer is marked as submitted with current timestamp
5. One steal per game (flag `steal_used` prevents re-use)

**Scoring after steal**:
- Stealer gets scored on the stolen year with their own (later) submission time
- Speed multiplier is calculated from steal time, not original submission time
- Stealer's bet status carries over from before the steal

### 3.2 Betting (Double-or-Nothing)

- Player sets `bet: true` in their `submit` message
- If round_score > 0: score is doubled (`bet_outcome = "won"`)
- If round_score = 0: score stays 0 (`bet_outcome = "lost"`)
- Bets are tracked for superlatives (Risk Taker award)

### 3.3 Streaks

- Consecutive rounds with base accuracy score > 0
- Reset to 0 on any round with 0 base score, missed round, or non-closest in Closest Wins mode
- Milestone bonuses: 3->+20, 5->+50, 10->+100, 15->+150, 20->+250, 25->+400
- Streak = 3 unlocks Steal power-up (once per game)

---

## 4. Scoring System

### Per-Round Score Calculation

```
1. base_score = accuracy_score(guess, actual_year, difficulty)
   - Exact match: 10 points (all difficulties)
   - Easy:   within 7 years = 5pts, within 10 years = 1pt
   - Normal: within 3 years = 5pts, within 5 years = 1pt
   - Hard:   within 2 years = 3pts, else = 0

2. speed_multiplier = 2.0 - (elapsed_seconds / round_duration)
   - Range: [1.0, 2.0] (instant = 2x, at deadline = 1x)

3. speed_score = int(base_score * speed_multiplier)

4. round_score = speed_score * bet_multiplier
   - bet_won: 2x, no_bet: 1x, bet_lost: stays 0

5. streak_bonus = milestone_bonus(new_streak_count)

6. artist_bonus = 5 if first correct artist guess, else 0

7. movie_bonus = {5, 3, 1, 0} based on correct movie guess rank

8. intro_bonus = {5, 3, 1, 0} if submitted during intro window (first 15s)

9. player.score += round_score + streak_bonus + artist_bonus + movie_bonus + intro_bonus
```

### Closest Wins Mode

Applied after normal scoring. Only the closest guess(es) keep their `round_score`.
Non-closest submitted players:
- `round_score` zeroed and subtracted from total score
- `streak_bonus` zeroed and subtracted
- Streak reset to 0
- artist_bonus and movie_bonus are KEPT (skill-based)

### Winner Determination

- `max(players, key=lambda p: p.score)` -- highest total score wins
- Ties: first player found in dict iteration order (effectively join order)
- No tie-breaking mechanism

---

## 5. Issues Found

### ISSUE 1: Correct Answer Leaked to All Clients During PLAYING (High)

**Location**: `game/serializers.py:99-107`

The `admin_song` object broadcast during PLAYING phase includes `year` (the correct answer):
```python
state["admin_song"] = {"year": gs.current_song.get("year"), ...}
```
This is sent to ALL WebSocket clients via `broadcast_state()`. The comment says "players
ignore this" but any player can see it in browser DevTools. Significant cheating vector.

**Fix**: Send `admin_song` only to the admin WebSocket, or split broadcasts into
per-player/per-admin payloads.

### ISSUE 2: Steal Doesn't Check If Stealer Already Submitted (Medium)

**Location**: `game/powerups.py:63-131`

`use_steal()` does not check `stealer.submitted`. A player who already submitted can use steal
to overwrite their guess with another player's answer. `handle_submit()` correctly blocks
duplicate submissions, but steal bypasses this.

**Consequence**: Player can see their guess is likely wrong (via metadata cues), then steal a
better answer late in the round.

**Fix**: Add `if stealer.submitted: return error` check in `use_steal()`.

### ISSUE 3: Bet Carries Over After Steal (Medium)

**Location**: `game/powerups.py:111`

Steal preserves the stealer's bet status. Combined with Issue 2:
1. Submit year 2000 with `bet=True`
2. Realize it's probably wrong
3. Steal year 1985 from another player
4. Bet now applies to the stolen (better) answer -> potential double points

**Fix**: Either clear bet on steal, or block steal if already submitted (Issue 2 fix).

### ISSUE 4: MIN_PLAYERS Check Never Enforced (Medium)

**Location**: `game/state.py:1077-1095`, `server/ws_handlers.py:307-354`

`start_game()` checks `MIN_PLAYERS = 2`, but it's never called. Both the WebSocket admin
handler and the HTTP endpoint call `start_round()` directly, bypassing the player count check.
A game can start with 0 or 1 players.

**Fix**: Add player count check to `start_round()` or call `start_game()` before first
`start_round()`.

### ISSUE 5: Closest Wins Doesn't Subtract intro_bonus (Medium)

**Location**: `game/scoring.py:430-467`

`apply_closest_wins()` subtracts `round_score` and `streak_bonus` for non-closest players,
but does not subtract `intro_bonus`. Since intro_bonus is speed-based (not skill-based like
artist/movie), it should arguably be zeroed too for consistency.

**Fix**: Add `p.score -= p.intro_bonus; p.intro_bonus = 0` in the closest-wins zeroing block.

### ISSUE 6: Steal Doesn't Trigger Early Reveal Check (Low)

**Location**: `server/ws_handlers.py:969-988`

After a successful steal, `handle_steal` broadcasts state but does not call
`trigger_early_reveal_if_complete()`. If a steal causes all players to be "submitted",
the early reveal won't fire until the timer expires.

**Fix**: Add `await game_state.trigger_early_reveal_if_complete()` after steal success.

### ISSUE 7: Rematch HTTP Endpoint Has No Auth (Low)

**Location**: `server/game_views.py:338-380`

`/beatify/api/rematch-game` has no admin token verification. Any client who can reach the
endpoint can trigger a rematch during END phase. While the game is local, this allows
non-players to disrupt by forcing rematches.

### ISSUE 8: Winner Tie Gives Arbitrary Result (Low)

**Location**: `game/state.py:614`, `game/serializers.py:183`

`max(players.values(), key=lambda p: p.score)` returns the first player found on tie. The
leaderboard correctly assigns equal ranks for ties, but the winner announcement names only
one player, determined by dict iteration order (effectively join order).

### ISSUE 9: Steal Speed Penalty Is Implicit (Design Note)

**Location**: `game/powerups.py:114`

Steal sets `submission_time = now` (steal time), giving a worse speed multiplier than the
original submitter. This is probably intentional as a trade-off, but is not documented or
communicated to the player.

---

## 6. Summary Table

| #  | Severity   | Issue |
|----|------------|-------|
| 1  | **HIGH**   | Correct answer (year) leaked to all clients via `admin_song` during PLAYING |
| 2  | **MEDIUM** | Steal doesn't check if stealer already submitted -- allows overwriting guess |
| 3  | **MEDIUM** | Bet carries over after steal -- exploit for double points on stolen answer |
| 4  | **MEDIUM** | `start_game()` MIN_PLAYERS check bypassed -- games can start with 0-1 players |
| 5  | **MEDIUM** | Closest Wins doesn't subtract `intro_bonus` for non-closest players |
| 6  | **LOW**    | Steal doesn't trigger early reveal check |
| 7  | **LOW**    | Rematch HTTP endpoint has no auth check |
| 8  | **LOW**    | Winner tie resolved arbitrarily (join order) |
| 9  | **LOW**    | Steal speed penalty is implicit/undocumented |
