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

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from aiohttp import web

    from .player import PlayerSession


_LOGGER = logging.getLogger(__name__)


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
        self,
        name: str,
        ws: web.WebSocketResponse,
        admin_claim_authenticated: bool = False,
    ) -> tuple[bool, str | None]:
        """Add a player to the game. Delegates to PlayerRegistry.

        ``admin_claim_authenticated`` (#2501) must be True to re-attach to a
        session that holds the host role; the default refuses it.
        """
        return self._player_registry.add_player(
            name,
            ws,
            self.phase,
            self.get_average_score,
            self.round,
            admin_claim_authenticated=admin_claim_authenticated,
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

    def reaction_retry_after(self, player_name: str) -> float:
        """Seconds until this player may react again (#2562). Delegates to PlayerRegistry."""
        return self._player_registry.reaction_retry_after(player_name)

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

    # ------------------------------------------------------------------
    # Taking a guest out mid-game, and letting them back (#2746)
    # ------------------------------------------------------------------

    def sit_out_player(self, name: str) -> bool:
        """Take a guest out of the running game without deleting them (#2746).

        Returns False when there is no such guest or they are the host.

        The design gate drew four options and the host picked **B**: every
        guest row is removable, connected or not, in the lobby or in a running
        game. Until now ``admin_kick_player`` refused both — outside LOBBY and
        for anyone still holding their phone — so the case that started the
        issue, a guest who has to leave mid-party, had no answer at all.

        **Taken out, not deleted.** ``remove_player`` drops the session
        outright: the score is gone, the row is gone, and the person who walks
        back in from the kitchen has no way back. This sets the third
        ``out_of_play`` sibling instead, next to ``eliminated`` (#827) and
        ``playoff_spectator`` (#2578). The round stops waiting on them —
        ``all_submitted()`` already skips ``out_of_play`` players — while the
        score and the rank stay where they were.

        That is also what makes trusting the host affordable. If the server
        refuses nothing, the guard has to be recoverability rather than a
        precondition: the worst outcome of a mis-tap in a dark room is a guest
        who taps back in with their points intact, not a guest whose game was
        destroyed.
        """
        target = self.get_player(name)
        if target is None or target.is_admin:
            return False
        target.sat_out_by_host = True
        target.rejoin_requested = False
        _LOGGER.info(
            "Host sat %s out (score %s kept, session kept) (#2746)",
            target.name,
            target.score,
        )
        return True

    def rejoin_allowed(self, player: PlayerSession) -> bool:
        """Whether this guest may tap their way back in (#2746).

        The host removes; the guest returns on their own. The host is not asked
        to re-admit anyone — that was the open question the gate left, and it
        was answered this way because the session survives the removal, so the
        phone already holds everything a return needs.

        The one refusal: once Sudden Death has actually started cutting, the
        survivor field is fixed. Someone re-entering it would change who is
        playing for the win. Measured on state rather than on intent — the mode
        being switched on is not enough, somebody has to have been eliminated —
        so a game configured for Sudden Death that never reached round 2 still
        lets a guest back.
        """
        if not player.sat_out_by_host:
            return False
        if self._finale_playoff_active:
            return False
        return not (
            self.sudden_death_mode and any(p.eliminated for p in self.players.values())
        )

    def request_rejoin(self, name: str) -> bool:
        """A guest asks to come back; it takes effect at the next round (#2746).

        Returns False when the guest may not return at all.

        **Never mid-round.** A guess that lands halfway through a round would
        be scored against a song the player did not hear from the start, and
        the leaderboard would move for a reason the room cannot see. In LOBBY
        and REVEAL there is no round in flight, so the return is immediate; in
        PLAYING it is parked and ``start_round`` picks it up. Either way the
        guest's phone says "back in for the next round" until it happens.
        """
        from .state import GamePhase

        target = self.get_player(name)
        if target is None or not self.rejoin_allowed(target):
            return False
        if self.phase is GamePhase.PLAYING:
            target.rejoin_requested = True
            _LOGGER.info("%s asked to rejoin, parked for the next round", target.name)
            return True
        target.sat_out_by_host = False
        target.rejoin_requested = False
        _LOGGER.info("%s rejoined (#2746)", target.name)
        return True

    def apply_pending_rejoins(self) -> list[str]:
        """Let parked returns in, at the round boundary. Returns their names."""
        returned: list[str] = []
        for player in self.players.values():
            if player.rejoin_requested and player.sat_out_by_host:
                player.sat_out_by_host = False
                player.rejoin_requested = False
                returned.append(player.name)
        if returned:
            _LOGGER.info("Rejoined at the round boundary: %s", ", ".join(returned))
        return returned

    def clear_all_sessions(self) -> None:
        """Clear all session mappings for game reset. Delegates to PlayerRegistry."""
        self._player_registry.clear_all_sessions()

    def get_players_state(self) -> list[dict[str, Any]]:
        """Get player list for state broadcast. Delegates to PlayerRegistry."""
        return self._player_registry.get_players_state()

    def sabotage_freeze_remaining(self, player: PlayerSession) -> int:
        """Whole seconds left on a player's sabotage freeze (#1665/#2700).

        Delegates to PlayerRegistry. The private "you were sabotaged" hit carries
        this alongside the broadcast so the victim's phone gets the authoritative
        duration in the same tick it gets the banner.
        """
        return self._player_registry.sabotage_freeze_remaining(player)

    def all_submitted(self) -> bool:
        """Check if all connected players have submitted. Delegates to PlayerRegistry."""
        return self._player_registry.all_submitted()

    def set_admin(self, name: str) -> bool:
        """Mark a player as admin. Delegates to PlayerRegistry."""
        return self._player_registry.set_admin(name)
