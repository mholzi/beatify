"""
Player Factory - Generate test player data.

Follows the factory pattern with overrides for parallel-safe,
schema-adaptive test data generation.

Usage:
    from tests.support.factories.player_factory import create_player

    # Default player
    player = create_player()

    # With overrides (shows test intent)
    admin = create_player(name="Admin", is_admin=True)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Player:
    """Player data model for testing."""

    session_id: str
    name: str
    score: int = 0
    submitted: bool = False
    guess: int | None = None
    bet: bool = False
    streak: int = 0
    connected: bool = True
    is_admin: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize for WebSocket messages."""
        return {
            "session_id": self.session_id,
            "name": self.name,
            "score": self.score,
            "submitted": self.submitted,
            "guess": self.guess,
            "bet": self.bet,
            "streak": self.streak,
            "connected": self.connected,
        }


def create_player(**overrides: Any) -> Player:
    """Create a test player with sensible defaults.

    All values are unique per call (UUID-based session_id)
    to ensure parallel test safety.

    Args:
        **overrides: Any Player field to override

    Returns:
        Player instance with merged defaults and overrides

    Examples:
        # Default player
        player = create_player()

        # Named player
        alice = create_player(name="Alice")

        # Admin player
        admin = create_player(name="GameMaster", is_admin=True)

        # Player with score
        winner = create_player(name="Winner", score=150, streak=5)
    """
    defaults = {
        "session_id": f"session-{uuid.uuid4().hex[:8]}",
        "name": f"Player-{uuid.uuid4().hex[:4]}",
        "score": 0,
        "submitted": False,
        "guess": None,
        "bet": False,
        "streak": 0,
        "connected": True,
        "is_admin": False,
    }
    defaults.update(overrides)
    return Player(**defaults)


def create_admin(**overrides: Any) -> Player:
    """Create an admin player (convenience factory)."""
    return create_player(is_admin=True, name="Admin", **overrides)


def create_player_with_guess(year: int, bet: bool = False, **overrides: Any) -> Player:
    """Create a player who has already submitted a guess."""
    return create_player(
        guess=year,
        bet=bet,
        submitted=True,
        **overrides,
    )
