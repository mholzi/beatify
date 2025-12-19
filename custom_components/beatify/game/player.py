"""Player session management for Beatify."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiohttp import web


@dataclass
class PlayerSession:
    """Represents a connected player."""

    name: str
    ws: web.WebSocketResponse
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
