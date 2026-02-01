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

    # Artist challenge bonus tracking (Story 20.4)
    artist_bonus: int = 0

    # Artist guess tracking (Story 20.9)
    has_artist_guess: bool = False

    # Movie quiz bonus tracking (Issue #28)
    movie_bonus: int = 0
    has_movie_guess: bool = False
    movie_bonus_total: int = 0  # Cumulative across rounds for superlative

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

    # Superlative tracking (Story 15.2) - CUMULATIVE, NOT reset in reset_round()
    submission_times: list[float] = field(
        default_factory=list
    )  # Time-to-submit per round (seconds)
    bets_placed: int = 0  # Total bets placed (distinct from bets_won)
    close_calls: int = 0  # Number of +/-1 year guesses (not exact)
    round_scores: list[int] = field(default_factory=list)  # All round scores for final 3 calc

    # Steal power-up tracking (Story 15.3)
    steal_available: bool = False  # True if steal unlocked and not yet used
    steal_used: bool = False  # True if steal was used this game (max 1 per game)
    stole_from: str | None = None  # Per-round: who was stolen from
    was_stolen_by: list[str] = field(
        default_factory=list
    )  # Per-round: who stole this player's answer

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
        # Reset artist bonus (Story 20.4)
        self.artist_bonus = 0
        # Reset artist guess tracking (Story 20.9)
        self.has_artist_guess = False
        # Reset movie quiz fields (Issue #28)
        self.movie_bonus = 0
        self.has_movie_guess = False
        # Reset bet fields (Story 5.3)
        self.bet = False
        self.bet_outcome = None
        # Reset previous streak (Story 5.4)
        self.previous_streak = 0
        # Reset per-round steal fields (Story 15.3)
        self.stole_from = None
        self.was_stolen_by = []

    def unlock_steal(self) -> bool:
        """Unlock steal power-up if not already used. Returns True if newly unlocked."""
        if self.steal_used or self.steal_available:
            return False
        self.steal_available = True
        return True

    def consume_steal(self, target_name: str) -> None:
        """Use the steal power-up to copy target's answer."""
        self.steal_available = False
        self.steal_used = True
        self.stole_from = target_name

    def reset_for_new_game(self) -> None:
        """Reset all game-level stats for a new game (Story 15.2)."""
        # Reset score and streaks
        self.score = 0
        self.streak = 0
        self.best_streak = 0
        self.rounds_played = 0
        self.bets_won = 0

        # Reset superlative tracking
        self.submission_times = []
        self.bets_placed = 0
        self.close_calls = 0
        self.round_scores = []

        # Reset steal tracking
        self.steal_available = False
        self.steal_used = False

        # Also reset round-level state
        self.reset_round()

    @property
    def avg_submission_time(self) -> float | None:
        """Average submission time in seconds (Story 15.2)."""
        if len(self.submission_times) < 3:
            return None
        return sum(self.submission_times) / len(self.submission_times)

    @property
    def final_three_score(self) -> int:
        """Sum of last 3 round scores (Story 15.2)."""
        return sum(self.round_scores[-3:]) if len(self.round_scores) >= 3 else 0
