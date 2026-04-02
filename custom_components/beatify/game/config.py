"""Game state configuration for Beatify (Issue #464).

``GameStateConfig`` is a dataclass whose fields define every resettable
attribute on ``GameState`` that is **not** delegated to a subsystem manager
(RoundManager, PlayerRegistry, ChallengeManager, PowerUpManager).

``GameState.__init__`` and ``_reset_game_internals`` call
``_apply_config(self._default_config)`` to (re-)set these attributes
to their default values.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any

from custom_components.beatify.const import (
    DIFFICULTY_DEFAULT,
    PROVIDER_DEFAULT,
)


@dataclass
class GameStateConfig:
    """Default values for resettable GameState attributes.

    Every field here becomes an attribute on ``GameState`` via
    ``_apply_config``.  The ``field_names()`` classmethod returns
    the list of attribute names so ``_apply_config`` can iterate.
    """

    # Game data (reset to empty between games)
    playlists: list[str] = field(default_factory=list)
    songs: list[dict[str, Any]] = field(default_factory=list)
    media_player: str = ""
    join_url: str = ""

    # Settings with defaults
    provider: str = PROVIDER_DEFAULT
    difficulty: str = DIFFICULTY_DEFAULT
    language: str = "en"

    # Pause / resume state
    pause_reason: str | None = None
    _previous_phase: Any = None  # GamePhase | None — avoid circular import
    disconnected_admin_name: str | None = None

    # Error tracking
    last_error_detail: str = ""

    # Mode flags
    closest_wins_mode: bool = False

    @classmethod
    def field_names(cls) -> list[str]:
        """Return the names of all config-managed fields."""
        return [f.name for f in fields(cls)]
