"""Player registry for Beatify — manages player lifecycle and lookups."""

from __future__ import annotations

import logging
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
    from aiohttp import web

    from .state import GamePhase

from .player import PlayerSession

_LOGGER = logging.getLogger(__name__)


class PlayerRegistry:
    """Manages player add/remove, lookups, sessions, and reactions."""

    def __init__(self) -> None:
        """Initialize empty registry."""
        self.players: dict[str, PlayerSession] = {}
        self._sessions: dict[str, str] = {}  # session_id → player_name
        self._reactions_this_phase: set[str] = set()

    def reset(self) -> None:
        """Clear all players, sessions, and reactions."""
        self.players.clear()
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
        average_score_fn: callable,
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

        # Check for reconnection - case-insensitive match
        for existing_name, existing_player in self.players.items():
            if existing_name.lower() == name.lower():
                if not existing_player.connected:
                    existing_player.ws = ws
                    existing_player.connected = True
                    _LOGGER.info("Player reconnected: %s", existing_name)
                    return True, None
                # #646: Check if the old WS is actually dead (race condition
                # where _handle_disconnect hasn't run yet after browser reload)
                if existing_player.ws is None or existing_player.ws.closed:
                    _LOGGER.info(
                        "Player %s: stale connected flag, old WS closed — allowing rejoin",
                        existing_name,
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

        # Add new player
        player = PlayerSession(
            name=name, ws=ws, score=initial_score, streak=0, joined_late=joined_late
        )
        self.players[name] = player
        self._sessions[player.session_id] = name

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
        """Get player by name (case-insensitive to match add_player reconnection)."""
        player = self.players.get(name)
        if player is not None:
            return player
        # Fallback: case-insensitive lookup (#413)
        name_lower = name.lower()
        for existing_name, existing_player in self.players.items():
            if existing_name.lower() == name_lower:
                return existing_player
        return None

    def get_player_by_session_id(self, session_id: str) -> PlayerSession | None:
        """Get player by session ID."""
        name = self._sessions.get(session_id)
        return self.players.get(name) if name else None

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
        """Remove player from game."""
        if name in self.players:
            player = self.players[name]
            self._sessions.pop(player.session_id, None)
            del self.players[name]
            _LOGGER.info("Player removed: %s", name)

    def clear_all_sessions(self) -> None:
        """Clear all session mappings for game reset."""
        session_count = len(self._sessions)
        self._sessions.clear()
        _LOGGER.info("Cleared %d player sessions", session_count)

    def get_players_state(self) -> list[dict[str, Any]]:
        """Get player list for state broadcast."""
        return [
            {
                "name": p.name,
                "score": p.score,
                "connected": p.connected,
                "streak": p.streak,
                "is_admin": p.is_admin,
                "submitted": p.submitted,
                "steal_available": p.steal_available,
                "bet": p.bet,
                "steal_used": p.steal_used,
            }
            for p in self.players.values()
        ]

    def all_submitted(self) -> bool:
        """Check if all connected players have submitted their guess."""
        connected_players = [p for p in self.players.values() if p.connected]
        if not connected_players:
            return False
        return all(p.submitted for p in connected_players)

    def get_average_score(self) -> int:
        """Calculate average score for late joiners.

        Uses only players who have completed at least one round to avoid
        inflating the average with other late joiners' initial scores (#494).
        """
        scored_players = [
            p for p in self.players.values() if p.rounds_played > 0
        ]
        if not scored_players:
            return 0
        total = sum(p.score for p in scored_players)
        return round(total / len(scored_players))

    def set_admin(self, name: str) -> bool:
        """
        Set a player as admin.

        Returns:
            True if admin was set, False if player not found

        """
        player = self.players.get(name)
        if player:
            player.is_admin = True
            _LOGGER.info("Admin set: %s", name)
            return True
        return False
