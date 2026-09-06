"""Game state configuration for Beatify (Issue #464, #2635).

``GameStateConfig`` is a dataclass whose fields define every resettable
attribute on ``GameState`` that is **not** delegated to a subsystem manager
(RoundManager, PlayerRegistry, ChallengeManager, PowerUpManager).

``GameState.__init__`` and ``_reset_game_internals`` call
``_apply_config(self._default_config)`` to (re-)set these attributes
to their default values.

``GameOptions`` (#2635) answers the other half of the question: what the admin
*configured* this game with.  It is the single list that ``create_game``,
``rematch_game`` and the HTTP create-game view all read, so a new game option
is one field here instead of four parallel edits.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Any

from custom_components.beatify.const import (
    DEFAULT_ROUND_DURATION,
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


#: Session attributes a rematch carries over that are **not** game options
#: (#2635): the session's content, the derived join URL, and the language,
#: which the HTTP layer sets *after* ``create_game`` returns.  They are all
#: ``GameStateConfig`` fields, so ``_reset_game_internals`` clears them and the
#: rematch has to put them back.  Unlike the options below, this tuple does not
#: grow when a new game option is added.
REMATCH_CARRYOVER_ATTRS: tuple[str, ...] = (
    "playlists",
    "songs",
    "media_player",
    "join_url",
    "language",
)


@dataclass
class GameOptions:
    """The admin-configured options of one game session (Issue #2635).

    **One list.**  Before this dataclass the same option was written out four
    times — as a parameter of ``create_game``, as a field of
    ``GameStateConfig``, as an entry in the hand-written ``preserved`` dict of
    ``rematch_game`` and as a key of ``create_kwargs`` in ``game_views``.
    Forgetting one of them broke the rematch *silently*: the option fell back
    to its default with no error anywhere.

    Now ``create_game`` takes this object, ``rematch_game`` captures and
    re-applies it, and the HTTP layer builds it from the request body.  Adding
    a game option means adding a field here.

    Every field name is also an attribute (or a manager-delegating property) of
    ``GameState``, which is what makes :meth:`capture` and :meth:`apply_to`
    work by name.

    Note the overlap with :class:`GameStateConfig`, which is a *different*
    question: ``GameStateConfig`` says what ``_reset_game_internals`` resets,
    this says what a game is configured with.  The state-owned flags appear in
    both; ``tests/unit/test_game_options_2635.py`` asserts their defaults stay
    in step.
    """

    # --- Playback / scoring basics -------------------------------------
    round_duration: int = DEFAULT_ROUND_DURATION
    difficulty: str = DIFFICULTY_DEFAULT
    provider: str = PROVIDER_DEFAULT
    #: Platform identifier for playback routing (music_assistant, sonos, ...).
    platform: str = "unknown"
    #: #1475: 0 = play every playable song (the historic behaviour).
    max_rounds: int = 0
    #: #1012: seconds to dwell in REVEAL before advancing (0 = manual only).
    reveal_auto_advance: int = 0

    # --- Challenges (owned by ChallengeManager) ------------------------
    artist_challenge_enabled: bool = True
    movie_quiz_enabled: bool = True
    #: Issue #1180: Title & Artist guessing replaces the year guess.
    title_artist_mode: bool = False

    # --- Round flow (owned by RoundManager) ----------------------------
    #: Issue #23: intro mode (~20% random rounds).
    intro_mode_enabled: bool = False

    # --- Mode flags (owned by GameState) -------------------------------
    #: Issue #442: only the closest guess(es) earn points.
    closest_wins_mode: bool = False
    #: Issue #1726: songs arranged into a difficulty arc instead of random.
    rampup_order_enabled: bool = False
    #: Issue #827: last-place player eliminated each round.
    sudden_death_mode: bool = False
    #: Issue #1725: the last round's score is doubled.
    finale_double_enabled: bool = False
    #: Issue #1725: a tie for first with songs left triggers a playoff.
    finale_tiebreaker_enabled: bool = False
    #: Issue #1724: bottom-third players get a one-time catch-up steal.
    comeback_token_enabled: bool = False
    #: Issue #1727: the won-bet payout scales with difficulty (2x/3x/5x).
    difficulty_bet_scaling_enabled: bool = False
    #: Issue #1665: one sabotage token per player per game.
    sabotage_enabled: bool = False

    @classmethod
    def field_names(cls) -> list[str]:
        """Return the option names, in declaration order."""
        return [f.name for f in fields(cls)]

    @classmethod
    def capture(cls, state: Any) -> GameOptions:
        """Read the current options off a ``GameState``.

        Used by ``rematch_game`` in place of the hand-written ``preserved``
        dict: whatever the admin configured is read back by field name, so a
        newly added field is carried over without touching the rematch.
        """
        return cls(**{name: getattr(state, name) for name in cls.field_names()})

    def apply_to(self, state: Any) -> None:
        """Write every option onto a ``GameState``.

        Plain ``setattr`` throughout — the manager-owned names (challenges,
        round flow) go through ``GameState``'s delegation properties, exactly
        as the old ``preserved``-restore loop did.
        """
        for name in self.field_names():
            setattr(state, name, getattr(self, name))
