"""Power-up system management for Beatify (Issue #351)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from custom_components.beatify.const import (
    ERR_ALREADY_SUBMITTED,
    ERR_CANNOT_STEAL_SELF,
    ERR_INVALID_ACTION,
    ERR_NO_STEAL_AVAILABLE,
    ERR_NOT_IN_GAME,
    ERR_TARGET_NOT_SUBMITTED,
)

if TYPE_CHECKING:
    from .player import PlayerSession

_LOGGER = logging.getLogger(__name__)


class PowerUpManager:
    """Manages power-up system: steals, bet tracking, and streak achievements."""

    def __init__(self) -> None:
        self.streak_achievements: dict[str, int] = self._default_streak_achievements()
        self.bet_tracking: dict[str, int] = self._default_bet_tracking()

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Reset all power-up state for a new game."""
        self.streak_achievements = self._default_streak_achievements()
        self.bet_tracking = self._default_bet_tracking()

    # ------------------------------------------------------------------
    # Steal
    # ------------------------------------------------------------------

    def get_steal_targets(
        self,
        stealer_name: str,
        players: dict[str, PlayerSession],
    ) -> list[str]:
        """Get list of players who have submitted and can be stolen from (Story 15.3).

        Args:
            stealer_name: Name of the player attempting to steal
            players: Current player dict

        Returns:
            List of player names who have submitted this round, excluding self

        """
        return [
            name
            for name, player in players.items()
            if name != stealer_name and player.submitted
        ]

    def use_steal(
        self,
        stealer_name: str,
        target_name: str,
        players: dict[str, PlayerSession],
        phase: Any,
        now: float,
    ) -> dict[str, Any]:
        """Execute steal: copy target's guess to stealer (Story 15.3).

        Args:
            stealer_name: Name of the player using steal
            target_name: Name of the player to copy from
            players: Current player dict
            phase: Current game phase (compared against PLAYING)
            now: Current timestamp

        Returns:
            dict with success status, or error code on failure

        """
        from .state import GamePhase  # noqa: PLC0415 — avoid circular import

        stealer = players.get(stealer_name)
        target = players.get(target_name)

        # Validations
        if not stealer:
            return {"success": False, "error": ERR_NOT_IN_GAME}

        if stealer.submitted:
            return {"success": False, "error": ERR_ALREADY_SUBMITTED}

        if not stealer.steal_available:
            return {"success": False, "error": ERR_NO_STEAL_AVAILABLE}

        if phase != GamePhase.PLAYING:
            return {"success": False, "error": ERR_INVALID_ACTION}

        if stealer_name == target_name:
            return {"success": False, "error": ERR_CANNOT_STEAL_SELF}

        if not target:
            return {"success": False, "error": ERR_NOT_IN_GAME}

        if not target.submitted or target.current_guess is None:
            return {"success": False, "error": ERR_TARGET_NOT_SUBMITTED}

        # Execute steal
        stolen_year = target.current_guess

        # Copy guess to stealer (keeping stealer's bet status)
        stealer.current_guess = stolen_year
        stealer.submitted = True
        stealer.submission_time = now

        # Track steal relationship
        stealer.consume_steal(target_name)
        target.was_stolen_by.append(stealer_name)

        _LOGGER.info(
            "Player %s stole answer from %s (year: %d)",
            stealer_name,
            target_name,
            stolen_year,
        )

        return {
            "success": True,
            "target": target_name,
            "year": stolen_year,
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _default_streak_achievements() -> dict[str, int]:
        return {
            "streak_3": 0,
            "streak_5": 0,
            "streak_10": 0,
            "streak_15": 0,
            "streak_20": 0,
            "streak_25": 0,
        }

    @staticmethod
    def _default_bet_tracking() -> dict[str, int]:
        return {"total_bets": 0, "bets_won": 0}
