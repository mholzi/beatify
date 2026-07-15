"""Player-lifecycle delegation subsystem for :class:`GameState`.

Issue #1271 next-increment extraction (off ``origin/main``, following the
TTS / leaderboard / media-lights / challenge-delegation cuts): the
**player-lifecycle** cluster is pulled out of the ``game/state.py``
God-Object into this ``PlayerLifecycleMixin``.

The cluster is the thin pass-through layer between ``GameState`` and its two
player-owning subsystems:

* :class:`~custom_components.beatify.game.player_registry.PlayerRegistry`
  (``self._player_registry``) — player dict, lookups (by name / session-id /
  WebSocket), sessions, reactions, admin flag, submitted-state aggregates and
  the average-score helper, and
* :class:`~custom_components.beatify.game.powerups.PowerUpManager`
  (``self._powerup_manager``) — steal targeting / execution and the
  streak-achievement + bet-tracking counters.

The mixin is **behavior-preserving**: it carries the exact same methods and
properties that previously lived on ``GameState``, so its public API and every
caller / test are unchanged.

The mixin relies on attributes the host class owns and that live on ``self``
at runtime:

* ``self._player_registry`` — the actual player state + lookup logic this
  layer delegates to.
* ``self._powerup_manager`` — steal / streak / bet state this layer delegates
  to.
* ``self.phase`` — the current :class:`GamePhase`, passed through to
  ``add_player`` and ``use_steal`` (read-only here; the phase write-path stays
  on ``GameState``).
* ``self._now`` — the clock callable, passed through to ``use_steal``.

It carries no state of its own and imports nothing from ``state.py`` at
runtime (``PlayerSession`` is a typing-only import), so the extraction
introduces no cyclic imports.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aiohttp import web

    from .player import PlayerSession


class PlayerLifecycleMixin:
    """Player-lifecycle delegation behavior for :class:`GameState`.

    See module docstring for the host-class attributes this mixin reads.
    """

    # ------------------------------------------------------------------
    # Player registry delegation (keep public interface identical)
    # ------------------------------------------------------------------

    @property
    def players(self) -> dict[str, PlayerSession]:
        """Player dict keyed by player_id (== session_id) — delegated to PlayerRegistry.

        #1664 PR-2: the key is the stable ``player_id`` now, not the display
        name. Name-based access goes through ``get_player`` / ``remove_player``
        / ``set_admin`` (case-insensitive via the registry name index).
        """
        return self._player_registry.players

    @players.setter
    def players(self, value: dict[str, PlayerSession]) -> None:
        self._player_registry.players = value

    @property
    def leader(self) -> PlayerSession | None:
        """Get current leader player (cached per state change)."""
        if not self.players:
            return None
        return max(self.players.values(), key=lambda p: p.score)

    # ------------------------------------------------------------------
    # Power-up delegation properties (keep public interface identical)
    # ------------------------------------------------------------------

    @property
    def streak_achievements(self) -> dict[str, int]:
        """Streak achievement counters."""
        return self._powerup_manager.streak_achievements

    @streak_achievements.setter
    def streak_achievements(self, value: dict[str, int]) -> None:
        self._powerup_manager.streak_achievements = value

    @property
    def bet_tracking(self) -> dict[str, int]:
        """Bet outcome counters."""
        return self._powerup_manager.bet_tracking

    @bet_tracking.setter
    def bet_tracking(self, value: dict[str, int]) -> None:
        self._powerup_manager.bet_tracking = value

    # ------------------------------------------------------------------
    # Player lifecycle / lookup delegation (keep public interface identical)
    # ------------------------------------------------------------------

    def get_average_score(self) -> int:
        """Calculate average score of all current players. Delegates to PlayerRegistry."""
        return self._player_registry.get_average_score()

    def add_player(
        self, name: str, ws: web.WebSocketResponse
    ) -> tuple[bool, str | None]:
        """Add a player to the game. Delegates to PlayerRegistry."""
        return self._player_registry.add_player(
            name, ws, self.phase, self.get_average_score, self.round
        )

    def get_player(self, name: str) -> PlayerSession | None:
        """Get player by name. Delegates to PlayerRegistry."""
        return self._player_registry.get_player(name)

    def get_player_by_session_id(self, session_id: str) -> PlayerSession | None:
        """Get player by session ID. Delegates to PlayerRegistry."""
        return self._player_registry.get_player_by_session_id(session_id)

    def get_player_by_ws(self, ws: web.WebSocketResponse) -> PlayerSession | None:
        """Get player by WebSocket connection. Delegates to PlayerRegistry."""
        return self._player_registry.get_player_by_ws(ws)

    def record_reaction(self, player_name: str, emoji: str) -> bool:
        """Record a player reaction. Delegates to PlayerRegistry."""
        return self._player_registry.record_reaction(player_name, emoji)

    def get_steal_targets(self, stealer_name: str) -> list[str]:
        """Get list of players who can be stolen from (Story 15.3). Delegates to PowerUpManager."""
        return self._powerup_manager.get_steal_targets(stealer_name, self.players)

    def use_steal(self, stealer_name: str, target_name: str) -> dict[str, Any]:
        """Execute steal power-up (Story 15.3). Delegates to PowerUpManager."""
        return self._powerup_manager.use_steal(
            stealer_name, target_name, self.players, self.phase, self._now()
        )

    def get_sabotage_targets(self, saboteur_name: str) -> list[str]:
        """Get list of players who can be sabotaged (#1665). Delegates to PowerUpManager."""
        return self._powerup_manager.get_sabotage_targets(saboteur_name, self.players)

    def use_sabotage(self, saboteur_name: str, target_name: str) -> dict[str, Any]:
        """Execute sabotage power-up (#1665). Delegates to PowerUpManager."""
        return self._powerup_manager.use_sabotage(
            saboteur_name, target_name, self.players, self.phase, self._now()
        )

    def remove_player(self, name: str) -> None:
        """Remove player from game. Delegates to PlayerRegistry."""
        self._player_registry.remove_player(name)

    def clear_all_sessions(self) -> None:
        """Clear all session mappings for game reset. Delegates to PlayerRegistry."""
        self._player_registry.clear_all_sessions()

    def get_players_state(self) -> list[dict[str, Any]]:
        """Get player list for state broadcast. Delegates to PlayerRegistry."""
        return self._player_registry.get_players_state()

    def all_submitted(self) -> bool:
        """Check if all connected players have submitted. Delegates to PlayerRegistry."""
        return self._player_registry.all_submitted()

    def set_admin(self, name: str) -> bool:
        """Mark a player as admin. Delegates to PlayerRegistry."""
        return self._player_registry.set_admin(name)
