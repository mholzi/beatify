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
    # Issue #1726: Ramp-up ordering — songs arranged into a difficulty arc
    # (easy early, hardest known reserved for the finale) instead of uniform
    # random. Opt-in at game start (wizard). Default off = uniform random.
    rampup_order_enabled: bool = False
    # Issue #827: Sudden Death — last-place player eliminated each round.
    # Can be set at game start (wizard) or toggled live from the reveal screen.
    sudden_death_mode: bool = False
    # Issue #1725: Finale ×2 — on the last round, each player's round score is
    # doubled before it is committed, so a trailing player can still swing the
    # game. Opt-in at game start (wizard). Default off = normal scoring.
    finale_double_enabled: bool = False
    # Issue #1725: Finale sudden-death tiebreaker — if the game ends on a tie for
    # first while unplayed songs remain, a one-round playoff runs among ONLY the
    # tied players (reusing the #1472 elimination machinery) instead of declaring
    # a shared winner. Opt-in at game start (wizard). Default off.
    finale_tiebreaker_enabled: bool = False
    # Issue #1724: Comeback Token — after the halfway round completes, each
    # bottom-third player without a steal is handed one (reusing unlock_steal),
    # at most once per player per game. Rubber-banding so a trailing player gets
    # the catch-up power-up its effect is designed for. Opt-in at game start
    # (wizard). Default off = the streak-only steal unlock, unchanged.
    comeback_token_enabled: bool = False
    # Issue #1727: Difficulty-aware bet scaling — the won-bet payout scales with
    # difficulty (easy 2x / normal 3x / hard 5x) instead of a flat 3x, so betting
    # stays worthwhile on Hard where an exact guess is rare. Opt-in at game start
    # (wizard). Default off = flat 3x, byte-for-byte unchanged.
    difficulty_bet_scaling_enabled: bool = False
    # Issue #1665: Sabotage powerup — each player gets one token per game to hit
    # an opponent who is still guessing. The saboteur picks only the target; the
    # effect (timer-cut / forced bet / freeze) is rolled server-side on use.
    # Opt-in at game start (wizard). Default off = no tokens handed out at all.
    sabotage_enabled: bool = False
    # Issue #1180: Title & Artist guessing mode. Owned by ChallengeManager;
    # listed here for reset symmetry. GameState exposes a delegation property,
    # and _apply_config skips manager-delegated names (see field_names()).
    title_artist_mode: bool = False

    @classmethod
    def field_names(cls) -> list[str]:
        """Return the names of config-managed fields applied to GameState.

        Excludes flags that are owned by a subsystem manager and exposed on
        GameState only via a delegation property (Issue #1180:
        ``title_artist_mode`` is owned by ChallengeManager and reset by
        ChallengeManager.reset()).
        """
        delegated = {"title_artist_mode"}
        return [f.name for f in fields(cls) if f.name not in delegated]
