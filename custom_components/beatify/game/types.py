"""Shared types for the game package — breaks cyclic imports (#192).

RoundAnalytics and _get_decade_label were previously split across
state.py and scoring.py, causing a circular dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def get_decade_label(year: int) -> str:
    """Get decade label for a year (e.g., 1985 -> '1980s')."""
    decade = (year // 10) * 10
    return f"{decade}s"


# Keep the underscore-prefixed alias for backward compatibility
_get_decade_label = get_decade_label


@dataclass
class RoundAnalytics:
    """Analytics calculated at end of each round for reveal display (Story 13.3)."""

    # Guesses data (AC1)
    all_guesses: list[dict[str, Any]] = field(default_factory=list)
    average_guess: float | None = None
    median_guess: int | None = None

    # Performance metrics (AC2, AC3)
    closest_players: list[str] = field(default_factory=list)
    furthest_players: list[str] = field(default_factory=list)
    exact_match_players: list[str] = field(default_factory=list)
    exact_match_count: int = 0
    scored_count: int = 0
    total_submitted: int = 0
    accuracy_percentage: int = 0

    # Speed champion (AC3)
    speed_champion: dict[str, Any] | None = None

    # Histogram data (AC5, AC6)
    decade_distribution: dict[str, int] = field(default_factory=dict)
    correct_decade: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        avg = round(self.average_guess, 1) if self.average_guess else None
        return {
            "all_guesses": self.all_guesses,
            "average_guess": avg,
            "median_guess": self.median_guess,
            "closest_players": self.closest_players,
            "furthest_players": self.furthest_players,
            "exact_match_players": self.exact_match_players,
            "exact_match_count": self.exact_match_count,
            "scored_count": self.scored_count,
            "total_submitted": self.total_submitted,
            "accuracy_percentage": self.accuracy_percentage,
            "speed_champion": self.speed_champion,
            "decade_distribution": self.decade_distribution,
            "correct_decade": self.correct_decade,
        }
