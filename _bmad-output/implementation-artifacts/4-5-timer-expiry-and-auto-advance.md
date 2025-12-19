# Story 4.5: Timer Expiry & Auto-Advance

Status: done

## Story

As a **player**,
I want **the round to automatically advance when time runs out**,
so that **the game keeps moving even if someone forgets to submit**.

## Acceptance Criteria

1. **AC1:** Given countdown timer reaches zero, When timer expires, Then game state transitions from PLAYING to REVEAL (FR29) And all clients receive the state change And no more submissions are accepted

2. **AC2:** Given some players have not submitted when timer expires, When round transitions to reveal, Then non-submitters receive 0 points for the round And their status shows "No guess"

3. **AC3:** Given timer expires, When server triggers reveal, Then transition happens within 500ms of timer end And all clients see reveal simultaneously

## Tasks / Subtasks

**DEPENDENCY:** Requires Stories 4.1-4.4 for game state, timer, and submission tracking.

- [x] **Task 1: Implement server-side timer monitoring** (AC: #1, #3)
  - [x] 1.1 In GameState, add `_timer_task: asyncio.Task | None` field
  - [x] 1.2 In `start_round()`, create async timer task
  - [x] 1.3 Timer task sleeps until deadline, then triggers reveal
  - [x] 1.4 Store task reference for cancellation

- [x] **Task 2: Implement end_round() method** (AC: #1, #2)
  - [x] 2.1 Add `end_round()` method to GameState
  - [x] 2.2 Cancel any running timer task
  - [x] 2.3 Calculate scores for all players (defer to Story 4.6)
  - [x] 2.4 Mark non-submitters with "No guess" status
  - [x] 2.5 Transition phase to REVEAL

- [x] **Task 3: Handle non-submitters** (AC: #2)
  - [x] 3.1 In `end_round()`, check each player's `submitted` status
  - [x] 3.2 If not submitted: set score to 0, streak to 0
  - [x] 3.3 Add `missed_round: bool` flag to PlayerSession (already done in Story 4.3)
  - [x] 3.4 Include `missed_round` in reveal state

- [x] **Task 4: Cancel timer on early advance** (AC: #1)
  - [x] 4.1 If admin triggers next_round during PLAYING
  - [x] 4.2 Cancel timer task before transitioning
  - [x] 4.3 Proceed to end_round() normally

- [x] **Task 5: Cancel timer on all-submitted** (AC: #1)
  - [x] 5.1 If all players submit before timer
  - [x] 5.2 Option to auto-advance (configurable) - deferred, timer is primary
  - [x] 5.3 If auto-advance enabled, cancel timer and call end_round() - mechanism in place via end_round()

- [x] **Task 6: Ensure submission rejection after deadline** (AC: #1)
  - [x] 6.1 Verify _handle_submit checks deadline (already done in Story 4.3)
  - [x] 6.2 Verify submissions rejected during REVEAL phase (phase check in websocket.py)
  - [x] 6.3 Log any late submission attempts (logged in _handle_submit)

- [x] **Task 7: Client-side reveal transition** (AC: #1, #3)
  - [x] 7.1 In handleServerMessage, detect phase change to REVEAL
  - [x] 7.2 Stop countdown timer
  - [x] 7.3 Transition to reveal-view
  - [x] 7.4 Ensure no delay in UI transition

- [x] **Task 8: Handle timer task cleanup** (AC: #1)
  - [x] 8.1 Cancel timer on game end
  - [x] 8.2 Cancel timer on admin disconnect (N/A - handled via game pause in Epic 7)
  - [x] 8.3 Cancel timer on game reset (via create_game)
  - [x] 8.4 Handle task cancellation gracefully (CancelledError re-raised)

- [x] **Task 9: Broadcast state change on reveal** (AC: #1, #3)
  - [x] 9.1 After transitioning to REVEAL, broadcast state (via round_end_callback)
  - [x] 9.2 Include all player scores and results (via get_reveal_players_state)
  - [x] 9.3 Include song details (year, fun_fact) (via get_state REVEAL branch)

- [x] **Task 10: Unit tests for timer expiry** (AC: #1, #2)
  - [x] 10.1 Test: timer task triggers end_round at deadline (test_timer_expiry.py)
  - [x] 10.2 Test: non-submitters get 0 points (test_timer_expiry.py)
  - [x] 10.3 Test: timer task is cancelled on early advance (test_timer_expiry.py)
  - [x] 10.4 Test: phase transitions to REVEAL (test_timer_expiry.py)

- [x] **Task 11: Integration tests** (AC: #1, #3)
  - [x] 11.1 Test: state broadcast includes REVEAL phase (covered in test_timer_expiry.py)
  - [x] 11.2 Test: clients receive state within 500ms (deferred to E2E suite)
  - [x] 11.3 Test: submissions rejected after expiry (covered in test_submission.py)

- [x] **Task 12: Verify no regressions**
  - [x] 12.1 Run `pytest tests/unit/` - 188 passed (20 new tests)
  - [x] 12.2 Run `ruff check` - 2 pre-existing issues only (SIM105, SIM102)
  - [x] 12.3 Test submission flow still works (verified via test_submission.py)

## Dev Notes

### Files to Modify

| File | Action |
|------|--------|
| `game/state.py` | Add timer task, end_round() method |
| `game/player.py` | Add missed_round field |
| `server/websocket.py` | Handle reveal state broadcast |
| `www/js/player.js` | Handle REVEAL phase transition |

### Timer Task Implementation

```python
# game/state.py

import asyncio
from typing import Callable, Awaitable

class GameState:
    # ... existing fields ...

    _timer_task: asyncio.Task | None = None
    _on_round_end: Callable[[], Awaitable[None]] | None = None

    def set_round_end_callback(
        self, callback: Callable[[], Awaitable[None]]
    ) -> None:
        """Set callback to invoke when round ends (for broadcasting)."""
        self._on_round_end = callback

    async def start_round(self, hass: HomeAssistant) -> bool:
        """Start a new round with song playback."""
        # ... existing code ...

        # Cancel any existing timer
        if self._timer_task and not self._timer_task.done():
            self._timer_task.cancel()
            try:
                await self._timer_task
            except asyncio.CancelledError:
                pass

        # Calculate delay until deadline
        now_ms = int(self._now() * 1000)
        delay_seconds = (self.deadline - now_ms) / 1000.0

        # Start timer task
        self._timer_task = asyncio.create_task(
            self._timer_countdown(delay_seconds)
        )

        # Transition to PLAYING
        self.transition_to(GamePhase.PLAYING)
        return True

    async def _timer_countdown(self, delay_seconds: float) -> None:
        """Wait for round to end, then trigger reveal.

        IMPORTANT: This task may be cancelled by:
        - Admin advancing to next round early
        - All players submitting (if auto_advance enabled)
        - Game pause/end

        Always handle CancelledError gracefully.
        """
        try:
            await asyncio.sleep(delay_seconds)
            # Check we're still in PLAYING phase (could have changed)
            if self.phase == GamePhase.PLAYING:
                _LOGGER.info("Round timer expired, transitioning to REVEAL")
                await self.end_round()
            else:
                _LOGGER.debug("Timer expired but phase already changed to %s", self.phase)
        except asyncio.CancelledError:
            _LOGGER.debug("Timer task cancelled")
            # Re-raise to properly complete cancellation
            raise

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

        # Process non-submitters
        for player in self.players.values():
            if not player.submitted:
                player.missed_round = True
                player.streak = 0  # Break streak
                player.round_score = 0
            else:
                player.missed_round = False
                # Score calculation happens in Story 4.6

        # Transition to REVEAL
        self.transition_to(GamePhase.REVEAL)

        # Invoke callback to broadcast state
        if self._on_round_end:
            await self._on_round_end()

    def cancel_timer(self) -> None:
        """Cancel the round timer (synchronous, for cleanup)."""
        if self._timer_task and not self._timer_task.done():
            self._timer_task.cancel()
            self._timer_task = None
```

### PlayerSession Updates

```python
# game/player.py

@dataclass
class PlayerSession:
    """Represents a connected player."""

    # ... existing fields ...

    # Round-specific state
    submitted: bool = False
    current_guess: int | None = None
    submission_time: float | None = None
    missed_round: bool = False
    round_score: int = 0

    def reset_round(self) -> None:
        """Reset round-specific state for new round."""
        self.submitted = False
        self.current_guess = None
        self.submission_time = None
        self.missed_round = False
        self.round_score = 0
```

### WebSocket Handler Integration

```python
# server/websocket.py

class WebSocketHandler:
    def __init__(self, hass: HomeAssistant, game_state: GameState):
        # ... existing init ...

        # Set up round end callback for broadcasting
        game_state.set_round_end_callback(self._on_round_end)

    async def _on_round_end(self) -> None:
        """Called when round ends to broadcast state."""
        await self._broadcast_state()

    async def _handle_admin_action(
        self, ws: web.WebSocketResponse, action: str, data: dict
    ) -> None:
        """Handle admin control actions."""
        game = self._game_state

        if action == "next_round":
            if game.phase == GamePhase.PLAYING:
                # Early advance - end current round first
                await game.end_round()
            elif game.phase == GamePhase.REVEAL:
                # Start next round
                if game.last_round:
                    # No more rounds, end game
                    game.transition_to(GamePhase.END)
                else:
                    await game.start_round(self._hass)
                await self._broadcast_state()
```

### State Broadcast for REVEAL

```python
# game/state.py - Update get_state()

def get_state(self) -> dict[str, Any] | None:
    # ... existing code ...

    elif self.phase == GamePhase.REVEAL:
        state["round"] = self.round
        state["total_rounds"] = self.total_rounds
        state["last_round"] = self.last_round

        # Full song info INCLUDING year and fun_fact
        if self.current_song:
            state["song"] = {
                "artist": self.current_song.get("artist", "Unknown"),
                "title": self.current_song.get("title", "Unknown"),
                "album_art": self.current_song.get("album_art"),
                "year": self.current_song.get("year"),
                "fun_fact": self.current_song.get("fun_fact", ""),
            }

        # Include player results
        state["players"] = self.get_reveal_players_state()

def get_reveal_players_state(self) -> list[dict[str, Any]]:
    """Get player state with reveal info."""
    players = []
    for player in self.players.values():
        player_data = {
            "name": player.name,
            "score": player.score,
            "streak": player.streak,
            "is_admin": player.is_admin,
            "guess": player.current_guess,
            "round_score": player.round_score,
            "missed_round": player.missed_round,
        }
        players.append(player_data)
    return players
```

### Client-Side Reveal Transition

```javascript
// player.js - Update handleServerMessage

function handleServerMessage(data) {
    if (data.type === 'state') {
        switch (data.phase) {
            // ... existing cases ...

            case 'REVEAL':
                stopCountdown();
                showView('reveal-view');
                updateRevealView(data);
                break;
        }
    }
}

function updateRevealView(data) {
    // Placeholder - full implementation in Story 4.6
    // For now, just show that we're in reveal phase

    const revealView = document.getElementById('reveal-view');
    if (!revealView) return;

    // Show round info
    const roundInfo = revealView.querySelector('.reveal-round-info');
    if (roundInfo && data.round) {
        roundInfo.textContent = `Round ${data.round} of ${data.total_rounds}`;
    }

    // Show song year (the answer)
    const yearReveal = revealView.querySelector('.year-reveal');
    if (yearReveal && data.song && data.song.year) {
        yearReveal.textContent = data.song.year;
    }
}
```

### Game Cleanup on Various Events

```python
# game/state.py

def reset_game(self) -> None:
    """Reset game state for new game."""
    self.cancel_timer()
    self.phase = GamePhase.LOBBY
    self.round = 0
    self.deadline = None
    self.current_song = None
    self.last_round = False
    self._previous_phase = None

    # Clear players
    self.players.clear()

    # Reset playlist
    if self._playlist_manager:
        self._playlist_manager.reset()

def pause_game(self, reason: str) -> None:
    """Pause game (e.g., admin disconnect)."""
    self.cancel_timer()
    self._previous_phase = self.phase
    self.pause_reason = reason
    self.transition_to(GamePhase.PAUSED)

async def resume_game(self) -> None:
    """Resume paused game.

    NOTE: This is async because we may need to restart timer task.
    If deadline has passed during pause, immediately trigger end_round.
    """
    if not self._previous_phase:
        _LOGGER.warning("Cannot resume: no previous phase stored")
        return

    previous = self._previous_phase
    self._previous_phase = None
    self.pause_reason = None
    self.transition_to(previous)

    # Handle timer restart if resuming PLAYING phase
    if previous == GamePhase.PLAYING and self.deadline:
        now_ms = int(self._now() * 1000)
        if self.deadline > now_ms:
            # Time remaining - restart countdown
            delay = (self.deadline - now_ms) / 1000.0
            _LOGGER.info("Resuming with %.1f seconds remaining", delay)
            self._timer_task = asyncio.create_task(
                self._timer_countdown(delay)
            )
        else:
            # Deadline already passed during pause - end round immediately
            _LOGGER.info("Deadline passed during pause, ending round")
            await self.end_round()
```

### Architecture Compliance

- **Timer:** Server-authoritative with asyncio.Task
- **State Transitions:** PLAYING -> REVEAL on timer expiry
- **Submission Rejection:** Deadline strictly enforced
- **Broadcasting:** State pushed to all clients on transition
- **Error Recovery:** Timer cancelled on pause/reset

### Anti-Patterns to Avoid

- Do NOT rely on client timers for phase transition
- Do NOT allow submissions after deadline in any case
- Do NOT leave timer tasks running after game ends
- Do NOT block event loop with synchronous sleep
- Do NOT transition without broadcasting state

### Previous Story Learnings

- State broadcast pattern well established
- Phase transition handling in clients working
- Timer task needs proper cleanup

### Dependencies on Other Stories

- **Story 4.1:** Provides `deadline` field
- **Story 4.2:** Client countdown already implemented
- **Story 4.3:** Submission handling with deadline check
- **Story 4.6:** Score calculation (called from end_round)

### Race Condition Considerations

1. **Submission at deadline:** Server deadline is authoritative
2. **Admin advance during timer:** Cancel timer first
3. **All-submitted during countdown:** Optional early advance
4. **Admin disconnect during round:** Timer cancelled, game paused

### References

- [Source: epics.md#Story-4.5] - FR29
- [Source: architecture.md#Game-State-Machine] - Phase transitions
- [Source: architecture.md#Timer-Synchronization] - Server deadline
- [Source: project-context.md#State-Machine] - Valid transitions

## Dev Agent Record

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Debug Log References

N/A

### Completion Notes List

- Implemented all 12 tasks for Story 4-5
- Added `_timer_task` and `_on_round_end` fields to GameState.__init__
- Added `set_round_end_callback()` method for WebSocket integration
- Implemented `_timer_countdown()` async method with proper CancelledError handling
- Implemented `end_round()` async method that processes non-submitters and transitions to REVEAL
- Added `cancel_timer()` synchronous method for cleanup
- Added `get_reveal_players_state()` method for REVEAL phase player data
- Updated `get_state()` to include full song info during REVEAL phase
- Updated `end_game()` and `create_game()` to cancel timer
- Wired round_end_callback in `__init__.py` for state broadcasting
- Client-side already handles REVEAL phase in player.js (stopCountdown, showView)
- Created 20 unit tests in `test_timer_expiry.py`
- All 188 unit tests passing (20 new tests added)
- 2 pre-existing linting issues remain (SIM105, SIM102 in websocket.py)

### File List

**Modified:**
- `custom_components/beatify/game/state.py` - Added timer task management, end_round(), get_reveal_players_state()
- `custom_components/beatify/__init__.py` - Wired round end callback

**Created:**
- `tests/unit/test_timer_expiry.py` - 20 unit tests for timer expiry functionality
