"""Player registry for Beatify — manages player lifecycle and lookups."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from ..const import (
    ERR_GAME_ENDED,
    ERR_GAME_FULL,
    ERR_NAME_INVALID,
    ERR_NAME_TAKEN,
    MAX_NAME_LENGTH,
    MAX_PLAYERS,
    MIN_NAME_LENGTH,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from aiohttp import web

    from .state import GamePhase

from .player import PlayerSession

_LOGGER = logging.getLogger(__name__)


class PlayerRegistry:
    """Manages player add/remove, lookups, sessions, and reactions."""

    def __init__(self, time_fn: Callable[[], float] | None = None) -> None:
        """Initialize empty registry.

        Args:
            time_fn: Clock used for time-based player state (#1665 freeze
                countdown). Must be the SAME clock GameState hands to
                PowerUpManager, or the countdown is nonsense. Defaults to
                ``time.time`` to match ``GameState._now``.

        """
        self._now: Callable[[], float] = time_fn or time.time
        # #1664 PR-2: ``players`` is now keyed by ``player_id`` (== session_id),
        # the stable server-issued identifier — NOT the display name. The name
        # is a mutable display attribute tracked by ``_name_index`` purely as a
        # non-authoritative uniqueness / lookup hint.
        self._players: dict[str, PlayerSession] = {}  # player_id → PlayerSession
        # name.lower() → player_id (display / uniqueness hint, not authoritative)
        self._name_index: dict[str, str] = {}
        # session_id → player_id — reconnect gate (see clear_all_sessions):
        # clearing this map invalidates session-based reconnect while leaving
        # the players themselves intact (Story 11.6 leftover-session semantics).
        self._sessions: dict[str, str] = {}
        self._reactions_this_phase: set[str] = set()

    @property
    def players(self) -> dict[str, PlayerSession]:
        """Player dict keyed by ``player_id`` (== session_id)."""
        return self._players

    @players.setter
    def players(self, value: dict[str, PlayerSession]) -> None:
        """Replace the player dict and rebuild the derived indexes.

        Callers assign a fresh dict (typically ``{}`` on teardown). Keeping the
        ``_name_index`` / ``_sessions`` maps consistent here avoids stale
        lookups after a wholesale replacement.
        """
        self._players = value
        self._rebuild_indexes()

    def _rebuild_indexes(self) -> None:
        """Rebuild ``_name_index`` and ``_sessions`` from ``_players``."""
        self._name_index = {
            player.name.lower(): player_id
            for player_id, player in self._players.items()
        }
        self._sessions = {
            player.session_id: player_id for player_id, player in self._players.items()
        }

    def reset(self) -> None:
        """Clear all players, sessions, and reactions."""
        self._players.clear()
        self._name_index.clear()
        self._sessions.clear()
        self._reactions_this_phase.clear()

    def reset_reactions(self) -> None:
        """Clear reaction tracking for a new reveal phase."""
        self._reactions_this_phase.clear()

    def add_player(
        self,
        name: str,
        ws: web.WebSocketResponse,
        phase: GamePhase,
        average_score_fn: Callable[[], int],
        current_round: int = 0,
    ) -> tuple[bool, str | None]:
        """
        Add a player to the game.

        Allows joining during LOBBY, PLAYING, or REVEAL phases.
        Rejects during END phase.

        Args:
            name: Player display name (trimmed, max 20 chars)
            ws: WebSocket connection
            phase: Current game phase
            average_score_fn: Callable returning current average score for late joiners
            current_round: The round in progress (#1752). Recorded as
                ``joined_round`` for late joiners so Sudden Death can grant them
                one grace round (excluded from that round's elimination pool).

        Returns:
            (success, error_code) - error_code is None on success

        """
        from .state import GamePhase

        # Validate name
        name = name.strip()
        if not name or len(name) < MIN_NAME_LENGTH:
            return False, ERR_NAME_INVALID
        if len(name) > MAX_NAME_LENGTH:
            return False, ERR_NAME_INVALID

        # Check phase - reject END state (PAUSED is OK for reconnection)
        if phase == GamePhase.END:
            return False, ERR_GAME_ENDED

        # #1664 PR-2: name-based reconnect FALLBACK (deprecated).
        # The authoritative reconnect path is session_id-based
        # (``get_player_by_session_id`` → ``handle_reconnect``). This
        # case-insensitive name match is kept as an explicit backward-compat
        # fallback for clients that rejoin by name without a valid session_id
        # (old cookies, cleared storage). It will be removed in PR-5 once prod
        # logs confirm it is unused.
        existing_id = self._name_index.get(name.lower())
        existing_player = self.players.get(existing_id) if existing_id else None
        if existing_player is not None:
            if not existing_player.connected:
                existing_player.ws = ws
                existing_player.connected = True
                _LOGGER.info(
                    "name-based reconnect fallback (deprecated) for %s",
                    existing_player.name,
                )
                return True, None
            # #646: Check if the old WS is actually dead (race condition
            # where _handle_disconnect hasn't run yet after browser reload)
            if existing_player.ws is None or existing_player.ws.closed:
                _LOGGER.info(
                    "name-based reconnect fallback (deprecated) for %s: "
                    "stale connected flag, old WS closed — allowing rejoin",
                    existing_player.name,
                )
                existing_player.ws = ws
                existing_player.connected = True
                return True, None
            return False, ERR_NAME_TAKEN

        # Check player limit
        if len(self.players) >= MAX_PLAYERS:
            return False, ERR_GAME_FULL

        # Determine if late joiner
        joined_late = phase != GamePhase.LOBBY

        # Calculate initial score (late joiners get average)
        initial_score = average_score_fn() if joined_late else 0

        # Add new player. #1752: record the round a late joiner entered so
        # Sudden Death excludes them from that round's elimination pool (one
        # grace round); LOBBY joins leave joined_round None.
        player = PlayerSession(
            name=name,
            ws=ws,
            score=initial_score,
            streak=0,
            joined_late=joined_late,
            joined_round=current_round if joined_late else None,
        )
        # #1664 PR-2: key by player_id (== session_id), not the display name.
        self._players[player.player_id] = player
        self._name_index[name.lower()] = player.player_id
        self._sessions[player.session_id] = player.player_id

        # Log join with score info
        if joined_late and initial_score > 0:
            _LOGGER.info(
                "Late joiner %s inherits average score: %d (from %d players)",
                name,
                initial_score,
                len(self.players) - 1,
            )
        else:
            _LOGGER.info(
                "Player joined: %s (total: %d, late: %s)",
                name,
                len(self.players),
                joined_late,
            )
        return True, None

    def get_player(self, name: str) -> PlayerSession | None:
        """Get player by display name (case-insensitive via ``_name_index``).

        #1664 PR-2 / F6: name lookup is now uniformly case-insensitive across
        ``get_player`` / ``remove_player`` / ``set_admin`` — all resolve through
        the same ``_name_index`` (name.lower() → player_id).
        """
        player_id = self._name_index.get(name.lower())
        return self.players.get(player_id) if player_id else None

    def get_player_by_session_id(self, session_id: str) -> PlayerSession | None:
        """Get player by session ID (authoritative reconnect path)."""
        player_id = self._sessions.get(session_id)
        return self.players.get(player_id) if player_id else None

    def get_player_by_ws(self, ws: web.WebSocketResponse) -> PlayerSession | None:
        """Get player by WebSocket connection."""
        for player in self.players.values():
            if player.ws == ws:
                return player
        return None

    def record_reaction(self, player_name: str, emoji: str) -> bool:
        """
        Record a player reaction. Rate limited to 1 per player per reveal phase.

        Returns:
            True if reaction was recorded, False if rate limited

        """
        if player_name in self._reactions_this_phase:
            return False
        self._reactions_this_phase.add(player_name)
        return True

    def remove_player(self, name: str) -> None:
        """Remove player from game (by display name, case-insensitive — F6)."""
        player_id = self._name_index.get(name.lower())
        player = self.players.get(player_id) if player_id else None
        if player_id is None or player is None:
            return
        self._sessions.pop(player.session_id, None)
        self._name_index.pop(player.name.lower(), None)
        del self._players[player_id]
        _LOGGER.info("Player removed: %s", player.name)

    def clear_all_sessions(self) -> None:
        """Clear all session mappings for game reset."""
        session_count = len(self._sessions)
        self._sessions.clear()
        _LOGGER.info("Cleared %d player sessions", session_count)

    def _sabotage_freeze_remaining(self, player: PlayerSession) -> int:
        """Whole seconds left on this player's sabotage freeze (#1665).

        0 when no freeze is riding on them or it has already lapsed. Server-computed
        (mirrors ``seconds_remaining``) so the client counts down against its own
        clock rather than subtracting a server epoch from a skewed ``Date.now()``.
        """
        if player.sabotage_freeze_until is None:
            return 0
        return max(0, round(player.sabotage_freeze_until - self._now()))

    def get_players_state(self) -> list[dict[str, Any]]:
        """Get player list for state broadcast."""
        return [
            {
                "name": p.name,
                # #1664 PR-1: stable id alias (== session_id), additive enabler
                "player_id": p.player_id,
                "score": p.score,
                "connected": p.connected,
                "streak": p.streak,
                "is_admin": p.is_admin,
                "submitted": p.submitted,
                "steal_available": p.steal_available,
                "bet": p.bet,
                "steal_used": p.steal_used,
                # Issue #1665: Sabotage token + the effect currently riding on
                # this player. ``sabotage_freeze_remaining`` is server-computed
                # (like ``seconds_remaining``) so the client counts down against
                # its OWN clock instead of subtracting a server epoch.
                "sabotage_available": p.sabotage_available,
                "sabotage_used": p.sabotage_used,
                "sabotaged": p.sabotaged,
                "sabotaged_by": p.sabotaged_by,
                "sabotage_effect": p.sabotage_effect,
                "sabotage_forced_bet": p.sabotage_forced_bet,
                "sabotage_freeze_remaining": self._sabotage_freeze_remaining(p),
                "onboarded": p.onboarded,
                # Issue #827: Sudden Death — eliminated players render the
                # spectator view and a skull badge on leaderboards.
                "eliminated": p.eliminated,
                "eliminated_round": p.eliminated_round,
            }
            for p in self.players.values()
        ]

    def all_submitted(self) -> bool:
        """Check if all genuinely-connected players have submitted their guess.

        Uses ``is_active`` rather than the raw ``connected`` flag so a stale
        ghost (closed WebSocket not yet cleaned up) can't block early reveal
        for the whole room — #928. Eliminated players (#827) never submit, so
        they are excluded from the all-submitted (early reveal) check.
        """
        active_players = [
            p for p in self.players.values() if p.is_active and not p.eliminated
        ]
        if not active_players:
            return False
        return all(p.submitted for p in active_players)

    def get_average_score(self) -> int:
        """Calculate average score for late joiners.

        Uses only players who have completed at least one round to avoid
        inflating the average with other late joiners' initial scores (#494).
        """
        scored_players = [p for p in self.players.values() if p.rounds_played > 0]
        if not scored_players:
            return 0
        total = sum(p.score for p in scored_players)
        return round(total / len(scored_players))

    def set_admin(self, name: str) -> bool:
        """
        Set a player as admin (by display name, case-insensitive — F6).

        Returns:
            True if admin was set, False if player not found

        """
        player = self.get_player(name)
        if player:
            player.is_admin = True
            _LOGGER.info("Admin set: %s", player.name)
            return True
        return False
