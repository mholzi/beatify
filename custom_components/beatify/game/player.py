"""Player session management for Beatify."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiohttp import web


@dataclass
class PlayerSession:
    """Represents a connected player."""

    name: str
    ws: web.WebSocketResponse
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    score: int = 0
    streak: int = 0
    connected: bool = True
    is_admin: bool = False
    joined_late: bool = False
    joined_at: float = field(default_factory=time.time)
    submitted: bool = False
    current_guess: int | None = None
    submission_time: float | None = None
    # Round results (for Story 4.6)
    round_score: int = 0
    years_off: int | None = None
    missed_round: bool = False

    # Speed bonus tracking (Story 5.1)
    speed_multiplier: float = 1.0
    base_score: int = 0

    # Streak bonus tracking (Story 5.2)
    streak_bonus: int = 0

    # Betting tracking (Story 5.3)
    bet: bool = False
    bet_outcome: str | None = None  # "won", "lost", or None

    # No-submission tracking (Story 5.4)
    previous_streak: int = 0  # Streak before reset (for "lost X-streak" display)

    # Leaderboard tracking (Story 5.5)
    previous_rank: int | None = None  # Rank before last update

    # Final stats tracking (Story 5.6) - CUMULATIVE, NOT reset in reset_round()
    best_streak: int = 0  # Highest streak achieved during game
    rounds_played: int = 0  # Rounds where player submitted
    bets_won: int = 0  # Successful bets

    def submit_guess(self, year: int, timestamp: float) -> None:
        """Record a guess submission."""
        self.submitted = True
        self.current_guess = year
        self.submission_time = timestamp

    def reset_round(self) -> None:
        """Reset round-specific state for new round."""
        self.submitted = False
        self.current_guess = None
        self.submission_time = None
        self.round_score = 0
        self.years_off = None
        self.missed_round = False
        # Reset speed bonus fields (Story 5.1)
        self.speed_multiplier = 1.0
        self.base_score = 0
        # Reset streak bonus (Story 5.2)
        self.streak_bonus = 0
        # Reset bet fields (Story 5.3)
        self.bet = False
        self.bet_outcome = None
        # Reset previous streak (Story 5.4)
        self.previous_streak = 0
