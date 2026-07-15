"""Power-up system management for Beatify (Issue #351)."""

from __future__ import annotations

import logging
import random
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any

from custom_components.beatify.const import (
    ERR_ALREADY_SUBMITTED,
    ERR_CANNOT_SABOTAGE_SELF,
    ERR_CANNOT_STEAL_SELF,
    ERR_ELIMINATED,
    ERR_INVALID_ACTION,
    ERR_NO_SABOTAGE_AVAILABLE,
    ERR_NO_STEAL_AVAILABLE,
    ERR_NOT_IN_GAME,
    ERR_TARGET_ALREADY_SABOTAGED,
    ERR_TARGET_ALREADY_SUBMITTED,
    ERR_TARGET_NOT_SUBMITTED,
    SABOTAGE_EFFECTS,
    SABOTAGE_FORCED_BET,
    SABOTAGE_FREEZE,
    SABOTAGE_FREEZE_SECONDS,
    SABOTAGE_TIMER_CUT,
    SABOTAGE_TIMER_CUT_SECONDS,
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
        # #1664 PR-2: ``players`` is keyed by player_id now, so match on the
        # display name attribute rather than the dict key.
        # #1748: an eliminated player (Sudden Death) is out of the game — their
        # guess must not be a steal target.
        return [
            player.name
            for player in players.values()
            if player.name != stealer_name
            and player.submitted
            and not player.eliminated
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

        # #1664 PR-2: ``players`` is keyed by player_id now; steal targeting is
        # still name-based input (from get_steal_targets), so resolve by the
        # display name attribute. Name uniqueness is enforced at add_player, so
        # the first match is the intended player.
        def _by_name(wanted: str) -> PlayerSession | None:
            for candidate in players.values():
                if candidate.name == wanted:
                    return candidate
            return None

        stealer = _by_name(stealer_name)
        target = _by_name(target_name)

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
    # Sabotage (Issue #1665)
    # ------------------------------------------------------------------

    def get_sabotage_targets(
        self,
        saboteur_name: str,
        players: dict[str, PlayerSession],
    ) -> list[str]:
        """Get players who can still be sabotaged this round (#1665).

        The mirror image of ``get_steal_targets``: a steal copies an answer that
        already exists, so it needs a *submitted* target — sabotage handicaps the
        guess a player is still making, so it needs an *un-submitted* one. A
        player already hit this round is off the list (one hit per target per
        round), as is an eliminated player (#1748) and the saboteur themselves.

        Args:
            saboteur_name: Name of the player spending the token
            players: Current player dict

        Returns:
            List of player names that are valid sabotage targets

        """
        return [
            player.name
            for player in players.values()
            if player.name != saboteur_name
            and not player.submitted
            and not player.eliminated
            and player.sabotaged_by is None
        ]

    def use_sabotage(
        self,
        saboteur_name: str,
        target_name: str,
        players: dict[str, PlayerSession],
        phase: Any,
        now: float,
        effect_roll: Callable[[Sequence[str]], str] = random.choice,
    ) -> dict[str, Any]:
        """Execute sabotage: roll an effect and apply it to the target (#1665).

        The saboteur chooses only *whom* to hit — *how* they get hit is rolled
        here, server-side, so the client cannot pick (or predict) the effect.

        Args:
            saboteur_name: Name of the player spending the token
            target_name: Name of the player to hit
            players: Current player dict
            phase: Current game phase (compared against PLAYING)
            now: Current timestamp
            effect_roll: Chooser over SABOTAGE_EFFECTS — injectable for tests

        Returns:
            dict with success + rolled effect, or error code on failure

        """
        from .state import GamePhase  # noqa: PLC0415 — avoid circular import

        def _by_name(wanted: str) -> PlayerSession | None:
            for candidate in players.values():
                if candidate.name == wanted:
                    return candidate
            return None

        saboteur = _by_name(saboteur_name)
        target = _by_name(target_name)

        # Validations — mirror use_steal's order so the error codes stay
        # predictable for the client.
        if not saboteur:
            return {"success": False, "error": ERR_NOT_IN_GAME}

        if not saboteur.sabotage_available:
            return {"success": False, "error": ERR_NO_SABOTAGE_AVAILABLE}

        if phase != GamePhase.PLAYING:
            return {"success": False, "error": ERR_INVALID_ACTION}

        if saboteur_name == target_name:
            return {"success": False, "error": ERR_CANNOT_SABOTAGE_SELF}

        if not target:
            return {"success": False, "error": ERR_NOT_IN_GAME}

        # A locked-in answer can't be handicapped any more — all three effects
        # act on the *act of guessing*, so a submitted target is a no-op that
        # would silently eat the token.
        if target.submitted:
            return {"success": False, "error": ERR_TARGET_ALREADY_SUBMITTED}

        if target.eliminated:
            return {"success": False, "error": ERR_ELIMINATED}

        # One hit per target per round — two saboteurs stacking a timer-cut and
        # a freeze on the same victim would be un-survivable.
        if target.sabotaged_by is not None:
            return {"success": False, "error": ERR_TARGET_ALREADY_SABOTAGED}

        effect = effect_roll(SABOTAGE_EFFECTS)

        # Apply the rolled effect to the target. Each one is enforced server-side
        # on the target's submit path (see ws_handlers/guessing.py); the target
        # is told privately so their UI can reflect it.
        target.sabotaged_by = saboteur_name
        target.sabotage_effect = effect

        if effect == SABOTAGE_TIMER_CUT:
            target.sabotage_deadline_cut_ms = SABOTAGE_TIMER_CUT_SECONDS * 1000
        elif effect == SABOTAGE_FREEZE:
            target.sabotage_freeze_until = now + SABOTAGE_FREEZE_SECONDS
        elif effect == SABOTAGE_FORCED_BET:
            target.sabotage_forced_bet = True

        saboteur.consume_sabotage(target_name)

        _LOGGER.info(
            "Player %s sabotaged %s (effect: %s)",
            saboteur_name,
            target_name,
            effect,
        )

        return {
            "success": True,
            "target": target_name,
            "effect": effect,
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
