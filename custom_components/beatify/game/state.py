"""Game state management for Beatify.

Subsystem ownership
-------------------
GameState is the central coordinator.  It **owns** (creates and holds
a reference to) the following subsystems:

* ``PlayerRegistry`` — player lifecycle, lookups, sessions, reactions
* ``PowerUpManager`` — steals, bet tracking, streak achievements
* ``ChallengeManager`` — artist challenge & movie quiz state and logic
* ``RoundManager`` — round number, timer/deadline, intro mode, metadata
* ``HighlightsTracker`` — game highlights reel (exact matches, streaks, …)

It **references** (does not own, receives via setter):

* ``StatsService`` — historical game statistics and song difficulty
* ``MediaPlayerService`` — lazy-created on first round via Home Assistant
* ``PartyLightsService`` — optional party-lights integration

Serialization is handled by ``GameStateSerializer`` (game/serializers.py)
which builds broadcast-ready dicts from GameState without GameState
needing to know its own wire format.

Reset logic uses ``GameStateConfig`` (game/config.py), a dataclass
whose fields define every resettable attribute and its default value.
"""

from __future__ import annotations

import asyncio
import logging
import time
from enum import Enum
from typing import TYPE_CHECKING, Any

from .challenges import (
    ArtistChallenge,  # noqa: F401 (re-exported for backward compatibility)
    ChallengeManager,
    MovieChallenge,  # noqa: F401 (re-exported for backward compatibility)
    build_artist_options,  # noqa: F401 (re-exported for backward compatibility)
    build_movie_options,  # noqa: F401 (re-exported for backward compatibility)
)
from .config import GameStateConfig
from .highlights import HighlightsTracker
from .player import PlayerSession
from .playlist import PlaylistManager
from .player_registry import PlayerRegistry
from .powerups import PowerUpManager
from .round_manager import RoundManager
from .scoring import (
    ScoringService,
)
from .protocols import MediaPlayerProtocol, PartyLightsProtocol
from .state_auto_advance import RevealAutoAdvanceMixin
from .state_challenge import ChallengeMixin
from .state_leaderboard import LeaderboardMixin
from .state_lifecycle import RoundLifecycleMixin
from .state_media import MediaControlMixin
from .state_pause import PauseResumeMixin
from .state_player import PlayerLifecycleMixin
from .state_setup import GameSetupMixin
from .state_scoring import RoundScoringMixin
from .state_serialization import StateSerializationMixin
from .state_tts import TtsAnnouncerMixin
from .state_vote_window import VoteWindowMixin

from .types import RoundAnalytics, _get_decade_label

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from aiohttp import web
    from homeassistant.core import HomeAssistant

    from custom_components.beatify.services.stats import StatsService

_LOGGER = logging.getLogger(__name__)


class GamePhase(Enum):
    """Game phase states."""

    LOBBY = "LOBBY"
    PLAYING = "PLAYING"
    REVEAL = "REVEAL"
    END = "END"
    PAUSED = "PAUSED"


# ---------------------------------------------------------------------------
# Phase-transition table (Issue #1273, AC#1 consolidation increment)
# ---------------------------------------------------------------------------
#
# The legal *forward* phase transitions, derived from every ``_set_phase`` call
# site in this module. This makes the transition graph an explicit, auditable
# data structure layered on the single ``_set_phase`` chokepoint — the exact
# follow-up the ``_set_phase`` docstring invited ("Follow-up increments can
# layer a transition table on top of this single chokepoint").
#
# IMPORTANT — observational, not enforcing: ``_set_phase`` only logs a WARNING
# when an *unexpected* edge is taken; it never raises and never blocks the
# write. This is deliberately behaviour-preserving: it surfaces drift (a new
# transition added without updating this table, or a genuinely illegal flip)
# without ever changing control flow. Exemptions: same-phase writes (e.g. the
# PLAYING→PLAYING next-round commit) and ``restore=True`` resumes are never
# checked — a resume legitimately restores PAUSED→PLAYING / PAUSED→REVEAL.
#
# Edges (source → allowed targets):
#   * LOBBY and END are valid targets from ANY phase — ``start_game`` /
#     rematch / reset re-initialise to LOBBY from anywhere, and
#     ``advance_to_end`` is a documented universal terminal.
#   * LOBBY   → PLAYING            (start_game)
#   * PLAYING → REVEAL, PAUSED     (reveal / pause)
#   * REVEAL  → PLAYING, PAUSED    (next-round commit / pause)
# Same-phase forward writes (LOBBY→LOBBY re-init, PLAYING→PLAYING next round)
# are covered by the same-phase exemption, not by this table.
_VALID_PHASE_TRANSITIONS: dict[GamePhase, frozenset[GamePhase]] = {
    GamePhase.LOBBY: frozenset({GamePhase.PLAYING}),
    GamePhase.PLAYING: frozenset({GamePhase.REVEAL, GamePhase.PAUSED}),
    GamePhase.REVEAL: frozenset({GamePhase.PLAYING, GamePhase.PAUSED}),
    GamePhase.PAUSED: frozenset(),
    GamePhase.END: frozenset(),
}

# Targets reachable from *any* source phase (re-init + universal terminal).
_UNIVERSAL_PHASE_TARGETS: frozenset[GamePhase] = frozenset(
    {GamePhase.LOBBY, GamePhase.END}
)


class GameState(
    ChallengeMixin,
    GameSetupMixin,
    LeaderboardMixin,
    MediaControlMixin,
    PauseResumeMixin,
    PlayerLifecycleMixin,
    RevealAutoAdvanceMixin,
    RoundLifecycleMixin,
    RoundScoringMixin,
    StateSerializationMixin,
    TtsAnnouncerMixin,
    VoteWindowMixin,
):
    """Manages game state and phase transitions.

    The TTS / spoken-announcement subsystem (Issue #1271 first-increment
    extraction) lives in :class:`~custom_components.beatify.game.state_tts.TtsAnnouncerMixin`.

    The leaderboard / ranking subsystem (Issue #1271 next-increment
    extraction) lives in :class:`~custom_components.beatify.game.state_leaderboard.LeaderboardMixin`.

    The media-player & party-lights output subsystem (Issue #1271
    next-increment extraction) lives in
    :class:`~custom_components.beatify.game.state_media.MediaControlMixin`.

    The challenge-delegation subsystem (Issue #1271 next-increment
    extraction, stacked on the media extraction) lives in
    :class:`~custom_components.beatify.game.state_challenge.ChallengeMixin`.

    The player-lifecycle subsystem (Issue #1271 next-increment extraction:
    PlayerRegistry + PowerUpManager delegation — player lookups, sessions,
    reactions, admin, steal/streak/bet pass-throughs) lives in
    :class:`~custom_components.beatify.game.state_player.PlayerLifecycleMixin`.

    The Title & Artist REVEAL vote-window subsystem (Issue #1271
    next-increment extraction — the #1180 Phase 4 vote-window scheduling +
    finalization writers the challenge-delegation cut deliberately left
    behind, coupled to the score lock and the auto-advance task) lives in
    :class:`~custom_components.beatify.game.state_vote_window.VoteWindowMixin`.

    The round-scoring & round-stats subsystem (Issue #1271 next-increment
    extraction, stacked on the vote-window cut — the round-end scoring pass
    plus highlights / analytics / song-result recording, i.e. the
    ``_end_round_unlocked`` phase 2 & 3 helpers; the shared
    ``_score_all_players`` loop deliberately stays here so the round-end and
    vote-window deferred-rescore paths cannot drift) lives in
    :class:`~custom_components.beatify.game.state_scoring.RoundScoringMixin`.

    The state-serialization & game-summary subsystem (Issue #1271
    next-increment extraction, stacked on the round-scoring cut — the
    frontend/StatsService serialization entry points ``get_state`` /
    ``get_reveal_players_state`` plus the end-of-game summary
    (``finalize_game``), live performance comparison (``get_game_performance``
    / ``_calculate_current_avg``), the ``StatsService`` wiring
    (``set_stats_service``) and the difficulty lookup (``get_song_difficulty``))
    lives in
    :class:`~custom_components.beatify.game.state_serialization.StateSerializationMixin`.

    The round-lifecycle / round-start subsystem (Issue #1271 next-increment
    extraction, stacked on the state-serialization cut — the LOBBY→PLAYING
    start gate (``start_game``) plus the full ``start_round`` orchestration
    (song selection, playback dispatch, metadata build, round-state commit) and
    its setup helpers (``_ensure_media_player_service``, ``_prepare_intro_round``,
    ``_build_round_metadata``, ``_initialize_round``); the round-*end* /
    REVEAL-transition path deliberately stays here) lives in
    :class:`~custom_components.beatify.game.state_lifecycle.RoundLifecycleMixin`.

    The pause / resume subsystem (Issue #1271 next-increment extraction, stacked
    on the round-lifecycle cut — the PLAYING/REVEAL→PAUSED pause gate
    (``pause_game``: phase snapshot, timer + media-playback stop, REVEAL
    auto-advance supersession) and the PAUSED→(previous phase) resume restore
    (``resume_game``: remaining-deadline timer/intro-timer restart, media
    resume, or immediate round-end if the deadline elapsed during the pause —
    always writing the phase through ``_set_phase(restore=True)`` so a
    resume-to-REVEAL never re-stamps ``reveal_started_at``); the ``_set_phase``
    chokepoint and ``_timer_countdown`` / ``end_round`` stay on ``GameState``)
    lives in
    :class:`~custom_components.beatify.game.state_pause.PauseResumeMixin`.

    The REVEAL auto-advance subsystem (Issue #1271 next-increment extraction,
    off ``main`` after the pause/resume cut — the #1012 unattended REVEAL→next
    machinery: the song-end / dwell auto-advance task (``_reveal_auto_advance``),
    the zero-guesses idle-halt task (``_reveal_idle_halt``), their shared
    song-end poll (``_song_finished``) and the cancel hook
    (``_cancel_auto_advance``); the scheduler that *starts* these tasks
    (``_schedule_reveal_advance``) and the ``_set_phase`` chokepoint stay on
    ``GameState``) lives in
    :class:`~custom_components.beatify.game.state_auto_advance.RevealAutoAdvanceMixin`.

    The game-setup subsystem (Issue #1271 next-increment extraction, off
    ``main`` — the new-session builder (``create_game``: token generation,
    PlaylistManager construction, storefront detection, round-tracking + config
    reset, challenge / power-up / mode configuration), the teardown
    (``end_game``) and the player-preserving rebuild (``rematch_game``), their
    shared field-reset (``_reset_game_internals``) and the Apple-Music
    storefront detection (``_detect_storefront``); the ``_set_phase`` chokepoint
    and ``_apply_config`` / ``_default_config`` stay on ``GameState``) lives in
    :class:`~custom_components.beatify.game.state_setup.GameSetupMixin`.
    """

    def __init__(self, time_fn: Callable[[], float] | None = None) -> None:
        """
        Initialize game state.

        Args:
            time_fn: Optional time function for testing. Defaults to time.time.

        """
        self._now = time_fn or time.time
        self._hass: HomeAssistant | None = None
        self.game_id: str | None = None
        self.admin_token: str | None = None  # Issue #386: REST admin auth
        self.phase: GamePhase = GamePhase.LOBBY
        # #1012: REVEAL auto-advance (seconds; 0 = manual) + its task handle
        self.reveal_auto_advance: int = 0
        self._auto_advance_task: asyncio.Task | None = None
        # #1180 Phase 4: title/artist near-miss vote window is open in REVEAL.
        self._title_artist_voting_open: bool = False
        # #1180: server-owned wall-clock deadline (in self._now units) for the
        # open vote window, so the serializer publishes an authoritative
        # vote_seconds_remaining (no client clock-skew). None when not voting.
        self._title_artist_vote_deadline: float | None = None
        # #1048: ms timestamp REVEAL was entered — clients compute remaining
        # countdown vs Date.now(). None outside REVEAL.
        self.reveal_started_at: int | None = None
        # Issue #331: Party Lights service
        self._party_lights: PartyLightsProtocol | None = None
        # Issue #447 / #1271: TTS announcement subsystem state lives in
        # TtsAnnouncerMixin; initialize it here so the attributes exist before
        # any announcement fires.
        self._init_tts_state()
        self._bg_tasks: set[asyncio.Task] = (
            set()
        )  # Issue #391: prevent GC of fire-and-forget tasks

        # Issue #347: Player management delegated to PlayerRegistry
        self._player_registry = PlayerRegistry()

        # Issue #464: Round lifecycle delegated to RoundManager
        self._round_manager = RoundManager(self._now)

        # Issue #464: Default config for config-driven reset
        self._default_config = GameStateConfig()

        # Apply config defaults to self
        self._apply_config(self._default_config)

        # Services (Epic 4)
        self._playlist_manager: PlaylistManager | None = None
        self._media_player_service: MediaPlayerProtocol | None = None

        # Callback for round end (Story 4.5)
        self._on_round_end: Callable[[], Awaitable[None]] | None = None

        # Volume control (Story 6.4)
        self.volume_level: float = 0.5  # Default 50%

        # Platform identifier for playback routing (replaces is_mass)
        self.platform: str = "unknown"

        # Stats service reference (Story 14.4)
        self._stats_service: StatsService | None = None

        # Issue #351: Power-up system (steals, bets, streak tracking)
        self._powerup_manager = PowerUpManager()

        # Story 20.1 / Issue #28: Challenge state (artist + movie quiz)
        self._challenge_manager = ChallengeManager()

        # Issue #442: Closest Wins mode
        self.closest_wins_mode: bool = False

        # Issue #477: Admin spectator WebSocket (host without being a player)
        self._admin_ws: web.WebSocketResponse | None = None

        # Issue #42: Metadata update callback
        self._on_metadata_update: Callable[[dict[str, Any]], Awaitable[None]] | None = (
            None
        )

        # Issue AF2-013: Lock to prevent concurrent score updates
        self._score_lock: asyncio.Lock = asyncio.Lock()

        # Issue #75: Game highlights reel
        self.highlights_tracker = HighlightsTracker()

        # Issue #441: Observer callbacks for HA entity updates
        self._state_callbacks: list[Callable[[], None]] = []

    def _apply_config(self, config: GameStateConfig) -> None:
        """Apply a GameStateConfig to self, setting all config-managed fields."""
        for field_name in GameStateConfig.field_names():
            setattr(self, field_name, getattr(config, field_name))

    def set_hass(self, hass: HomeAssistant) -> None:
        """Store the Home Assistant instance for service creation."""
        self._hass = hass

    def register_state_callback(self, cb: Callable[[], None]) -> None:
        """Register a callback invoked on every state change (Issue #441)."""
        self._state_callbacks.append(cb)

    def unregister_state_callback(self, cb: Callable[[], None]) -> None:
        """Remove a previously registered state callback (Issue #441)."""
        try:
            self._state_callbacks.remove(cb)
        except ValueError:
            pass

    def _notify_state_callbacks(self) -> None:
        """Notify all registered state observers (Issue #441)."""
        for cb in self._state_callbacks:
            cb()

    # ------------------------------------------------------------------
    # Phase transitions — Single Source of Truth (Issue #1273)
    # ------------------------------------------------------------------
    #
    # ALL writes to ``self.phase`` now go through ``_set_phase`` — including the
    # two ``resume_game`` restores, which pass ``restore=True`` (#1273). There
    # are no remaining direct ``self.phase = …`` assignments anywhere in the
    # codebase. This makes the backend the one authoritative owner of the game
    # phase and gives every transition a single, auditable chokepoint. Two
    # invariants that were previously hand-maintained at each scattered
    # ``self.phase = …`` site are now enforced here so they can never drift:
    #
    #   * ``reveal_started_at`` (#1048) is owned by forward transitions: non-None
    #     *iff* phase is REVEAL — stamped on entry to REVEAL, cleared on every
    #     other forward transition. A ``restore=True`` resume deliberately leaves
    #     it untouched (resume must not restart the auto-advance countdown).
    #   * registered state observers (#441) are notified on every phase change.
    #
    # This centralises the *write* path. An explicit, auditable transition
    # table (``_VALID_PHASE_TRANSITIONS`` above) is now layered on top of this
    # chokepoint: ``_set_phase`` logs a WARNING on any forward edge missing from
    # the table. The check is observational only — it never raises or blocks, so
    # behaviour is unchanged; it exists to surface drift (an un-tabled new edge
    # or a genuinely illegal flip).

    def _set_phase(
        self, new_phase: GamePhase, *, notify: bool = True, restore: bool = False
    ) -> None:
        """Authoritatively transition the game to ``new_phase``.

        The single write-point for ``self.phase`` (Issue #1273). Maintains the
        ``reveal_started_at`` invariant (#1048) and notifies state observers
        (#441) so no transition site has to remember either bookkeeping step.

        Args:
            new_phase: The phase to transition into.
            notify: Whether to fire registered state callbacks. Defaults to
                True; pass False only when the caller batches its own notify
                immediately afterwards (kept for callers that interleave other
                bookkeeping between the phase write and the broadcast).
            restore: Pass True only from ``resume_game`` (#1273). A resume
                *restores* a previously-saved phase rather than making a forward
                transition, so it must NOT re-stamp ``reveal_started_at`` — a
                resume-to-REVEAL would otherwise restart the auto-advance
                countdown. With ``restore=True`` the ``reveal_started_at`` value
                is left exactly as-is (neither stamped nor cleared); only the
                phase write + notify happen. This lets the two resume writes
                join the SSOT chokepoint without changing behaviour. Defaults to
                False (forward transitions own the timestamp invariant).

        """
        # #1273 (AC#1 consolidation): observational transition-validity check.
        # Logs — never raises, never blocks — when a forward edge isn't in the
        # explicit transition table, so drift (an un-tabled new transition or a
        # genuinely illegal flip) is surfaced without altering control flow.
        # Same-phase writes and restores are exempt (see the table comment).
        if not restore and new_phase is not self.phase:
            allowed = _VALID_PHASE_TRANSITIONS.get(self.phase, frozenset())
            if new_phase not in _UNIVERSAL_PHASE_TARGETS and new_phase not in allowed:
                _LOGGER.warning(
                    "Unexpected phase transition %s -> %s (not in transition "
                    "table); proceeding. If this is a new legitimate edge, add "
                    "it to _VALID_PHASE_TRANSITIONS (#1273).",
                    self.phase.value,
                    new_phase.value,
                )
        self.phase = new_phase
        # #1048: the REVEAL-entry timestamp is owned entirely by forward phase
        # transitions. Entering REVEAL stamps it; any other phase clears it.
        # A restore (resume) deliberately leaves the timestamp untouched — see
        # the ``restore`` arg docstring.
        if not restore:
            if new_phase is GamePhase.REVEAL:
                self.reveal_started_at = int(self._now() * 1000)
            else:
                self.reveal_started_at = None
        if notify:
            self._notify_state_callbacks()

    def current_time(self) -> float:
        """Return the current timestamp from the injected clock."""
        return self._now()

    # ------------------------------------------------------------------
    # Player registry / power-up delegation lives in PlayerLifecycleMixin
    # (Issue #1271 extraction). See game/state_player.py.
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # RoundManager delegation (keep public interface identical)
    # ------------------------------------------------------------------

    @property
    def round(self) -> int:
        """Current round number — delegated to RoundManager."""
        return self._round_manager.round

    @round.setter
    def round(self, value: int) -> None:
        self._round_manager.round = value

    @property
    def total_rounds(self) -> int:
        """Total rounds — delegated to RoundManager."""
        return self._round_manager.total_rounds

    @total_rounds.setter
    def total_rounds(self, value: int) -> None:
        self._round_manager.total_rounds = value

    @property
    def deadline(self) -> int | None:
        """Round deadline (ms) — delegated to RoundManager."""
        return self._round_manager.deadline

    @deadline.setter
    def deadline(self, value: int | None) -> None:
        self._round_manager.deadline = value

    @property
    def current_song(self) -> dict[str, Any] | None:
        """Current song dict — delegated to RoundManager."""
        return self._round_manager.current_song

    @current_song.setter
    def current_song(self, value: dict[str, Any] | None) -> None:
        self._round_manager.current_song = value

    @property
    def last_round(self) -> bool:
        """Whether this is the last round — delegated to RoundManager."""
        return self._round_manager.last_round

    @last_round.setter
    def last_round(self, value: bool) -> None:
        self._round_manager.last_round = value

    @property
    def round_start_time(self) -> float | None:
        """Round start timestamp — delegated to RoundManager."""
        return self._round_manager.round_start_time

    @round_start_time.setter
    def round_start_time(self, value: float | None) -> None:
        self._round_manager.round_start_time = value

    @property
    def round_duration(self) -> float:
        """Round timer duration — delegated to RoundManager."""
        return self._round_manager.round_duration

    @round_duration.setter
    def round_duration(self, value: float) -> None:
        self._round_manager.round_duration = value

    @property
    def song_stopped(self) -> bool:
        """Song stopped flag — delegated to RoundManager."""
        return self._round_manager.song_stopped

    @song_stopped.setter
    def song_stopped(self, value: bool) -> None:
        self._round_manager.song_stopped = value

    @property
    def round_analytics(self) -> RoundAnalytics | None:
        """Round analytics — stored on RoundManager for lifecycle coherence."""
        return self._round_manager.round_analytics

    @round_analytics.setter
    def round_analytics(self, value: RoundAnalytics | None) -> None:
        self._round_manager.round_analytics = value

    @property
    def intro_mode_enabled(self) -> bool:
        """Intro mode enabled — delegated to RoundManager."""
        return self._round_manager.intro_mode_enabled

    @intro_mode_enabled.setter
    def intro_mode_enabled(self, value: bool) -> None:
        self._round_manager.intro_mode_enabled = value

    @property
    def is_intro_round(self) -> bool:
        """Whether current round is intro mode — delegated to RoundManager."""
        return self._round_manager.is_intro_round

    @is_intro_round.setter
    def is_intro_round(self, value: bool) -> None:
        self._round_manager.is_intro_round = value

    @property
    def intro_stopped(self) -> bool:
        """Intro stopped flag — delegated to RoundManager."""
        return self._round_manager.intro_stopped

    @intro_stopped.setter
    def intro_stopped(self, value: bool) -> None:
        self._round_manager.intro_stopped = value

    @property
    def intro_splash_pending(self) -> bool:
        """Intro splash pending flag — delegated to RoundManager."""
        return self._round_manager._intro_splash_pending

    @property
    def early_reveal(self) -> bool:
        """Early reveal flag — delegated to RoundManager."""
        return self._round_manager._early_reveal

    @property
    def songs_remaining(self) -> int:
        """Count of unplayed songs remaining in the playlist."""
        if self._playlist_manager:
            return self._playlist_manager.get_remaining_count()
        return 0

    @property
    def metadata_pending(self) -> bool:
        """Metadata pending flag — delegated to RoundManager."""
        return self._round_manager.metadata_pending

    @metadata_pending.setter
    def metadata_pending(self, value: bool) -> None:
        self._round_manager.metadata_pending = value

    # ------------------------------------------------------------------
    # Power-up delegation properties live in PlayerLifecycleMixin
    # (Issue #1271 extraction). See game/state_player.py.
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Game setup (create / reset / end / rematch) + Apple-Music storefront
    # detection live in GameSetupMixin (Issue #1271 extraction).
    # See game/state_setup.py.
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Pause / resume lives in PauseResumeMixin (Issue #1271 extraction).
    # See game/state_pause.py.
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Player lifecycle / lookup + power-up delegation lives in
    # PlayerLifecycleMixin (Issue #1271 extraction). See game/state_player.py.
    # ------------------------------------------------------------------

    def check_all_guesses_complete(self) -> bool:
        """
        Check if all connected players have submitted all required guesses (Story 20.9).

        For early reveal: checks year guesses, and if artist challenge is active,
        also checks artist guesses.

        Returns:
            True if all connected players have completed all required guesses

        """
        # First check year guesses using existing method
        # Note: all_submitted() already returns False for zero connected players
        if not self.all_submitted():
            return False

        # If artist challenge enabled and active, check artist guesses
        # Skip check if challenge already has a winner (buttons disabled for others)
        # or if no one has guessed yet (don't block early reveal for ignored challenges)
        if self.artist_challenge_enabled and self.artist_challenge:
            has_winner = getattr(self.artist_challenge, "winner", None) is not None
            anyone_guessed = any(
                p.has_artist_guess for p in self.players.values() if p.is_active
            )
            if not has_winner and anyone_guessed:
                for player in self.players.values():
                    if player.is_active and not player.has_artist_guess:
                        return False

        # Issue #28: If movie quiz enabled and active, check movie guesses
        # Skip check if challenge already has correct guesses or no one interacted
        if self.movie_quiz_enabled and self.movie_challenge:
            has_correct = len(self.movie_challenge.correct_guesses) > 0
            anyone_guessed = any(
                p.has_movie_guess for p in self.players.values() if p.is_active
            )
            if not has_correct and anyone_guessed:
                for player in self.players.values():
                    if player.is_active and not player.has_movie_guess:
                        return False

        # #1180: In Title & Artist mode, wait for every active player to submit
        # their title/artist guess before auto-advancing. This mode replaces the
        # year guess, so there is no "winner" short-circuit — each player guesses
        # independently and we hold PLAYING until all are in.
        if self.title_artist_mode and self.title_artist_challenge:
            for player in self.players.values():
                if player.is_active and not player.has_title_artist_guess:
                    return False

        return True

    async def _trigger_early_reveal(self) -> None:
        """
        Trigger early transition to reveal when all guesses are in (Story 20.9).

        Cancels timer, sets early_reveal flag, and calls end_round.
        Uses _score_lock to prevent concurrent invocations from racing
        when multiple players submit simultaneously (AF2-013).

        """
        async with self._score_lock:
            # Re-check phase under lock — another coroutine may have already
            # transitioned to REVEAL between our caller's check and acquiring
            # the lock.
            if self.phase != GamePhase.PLAYING:
                _LOGGER.debug(
                    "Early reveal skipped — phase already %s", self.phase.value
                )
                return

            _LOGGER.info(
                "All guesses complete - triggering early reveal (phase=%s, callback=%s)",
                self.phase.value,
                self._on_round_end is not None,
            )
            self.cancel_timer()
            self._round_manager._early_reveal = True
            await self._end_round_unlocked()
            _LOGGER.info("Early reveal complete - phase now %s", self.phase.value)

    async def trigger_early_reveal_if_complete(self) -> None:
        """Trigger early reveal if the round is playing and all guesses are in."""
        if self.phase == GamePhase.PLAYING and self.check_all_guesses_complete():
            await self._trigger_early_reveal()

    def set_round_end_callback(self, callback: Callable[[], Awaitable[None]]) -> None:
        """
        Set callback to invoke when round ends (for broadcasting).

        Args:
            callback: Async function to call when round ends

        """
        self._on_round_end = callback

    def set_metadata_update_callback(
        self, callback: Callable[[dict[str, Any]], Awaitable[None]]
    ) -> None:
        """
        Set callback to invoke when song metadata is ready (Issue #42).

        Args:
            callback: Async function to call with metadata dict when available

        """
        self._on_metadata_update = callback

    async def _timer_countdown(self, delay_seconds: float) -> None:
        """Wait for round to end, then trigger reveal.

        Wraps RoundManager._timer_countdown with phase-aware end_round call.
        """
        try:
            await self._round_manager._timer_countdown(delay_seconds)
            # #1029: release the timer-task handle BEFORE invoking end_round.
            # end_round → _end_round_unlocked calls self.cancel_timer(), which
            # would cancel `_timer_task` — and `_timer_task` IS the currently
            # running task. A self-cancel schedules CancelledError on the next
            # real yield, interrupting the REVEAL broadcast (and historically
            # the phase transition itself before fake-await chains masked it).
            # _log_timer_task_failure treats cancellations as silent, so the
            # round froze on PLAYING with no diagnostic. Clearing the handle
            # here makes the subsequent cancel_timer() a no-op for this task.
            self._round_manager._timer_task = None
            # Timer completed normally — check phase and end round
            if self.phase == GamePhase.PLAYING:
                # #471 Phase 1: announce time-up only when timer ran to zero
                # (not on early-reveal). Done before end_round so the audio
                # leads the REVEAL transition.
                await self.announce_time_up()
                await self.end_round()
            else:
                _LOGGER.debug(
                    "Timer expired but phase already changed to %s", self.phase
                )
        except asyncio.CancelledError:
            _LOGGER.debug("Timer task cancelled")
            raise

    def _score_all_players(
        self, correct_year: int | None, all_players: list[PlayerSession]
    ) -> None:
        """Score every player for the current round via ScoringService.

        Single source of truth for the per-player score loop so the round-end
        path (_end_round_unlocked) and the title/artist rescore path
        (_finalize_title_artist_window) cannot drift. In title/artist mode the
        manager is passed so scoring uses the title+artist points path (#1180).
        NOT idempotent — ScoringService.score_player_round accumulates score,
        rounds_played and round_scores — so each player must be scored exactly
        once per round. The caller is responsible for that (the title/artist
        near-miss path defers scoring to a single post-resolve invocation).

        #816: wrap per player so an unexpected state shape in ONE player doesn't
        abort the round-end transition; the rest still score and the round ends.
        """
        title_artist_manager = (
            self._challenge_manager if self.title_artist_mode else None
        )
        for player in self.players.values():
            try:
                ScoringService.score_player_round(
                    player,
                    correct_year=correct_year,
                    round_start_time=self.round_start_time,
                    round_duration=self.round_duration,
                    difficulty=self.difficulty,
                    artist_challenge=self.artist_challenge,
                    movie_challenge=self.movie_challenge,
                    is_intro_round=self.is_intro_round,
                    intro_round_start_time=self._round_manager._intro_round_start_time,
                    all_players=all_players,
                    streak_achievements=self.streak_achievements,
                    bet_tracking=self.bet_tracking,
                    title_artist_manager=title_artist_manager,
                )
            except (KeyError, AttributeError, TypeError, ValueError) as err:
                _LOGGER.error(
                    "Scoring failed for player %s in round %d: %s — "
                    "their score is unchanged this round, round still ends",
                    getattr(player, "name", "?"),
                    self.round,
                    err,
                )

    async def _fetch_metadata_async(self, uri: str) -> None:
        """
        Fetch album art in background and update current_song (Issue #42).

        Fix #124: Only updates album_art — artist/title come from playlist
        data (set in start_round) and are never overwritten by media player
        state, which can be stale or from a different track (especially on
        Sonos/Spotify where queue management introduces race conditions).

        Args:
            uri: The song URI to fetch metadata for

        """
        try:
            if not self._media_player_service:
                _LOGGER.warning("No media player service for metadata fetch")
                return

            # Wait for metadata (this is the slow part we moved to background)
            metadata = await self._media_player_service.wait_for_metadata_update(uri)

            # Fix #124: Only update album_art from media player.
            # Artist/title are authoritative from playlist data — media player
            # state can report stale/wrong track info (especially Sonos + Spotify).
            if self.current_song:
                current_uri = self.current_song.get(
                    "_resolved_uri"
                ) or self.current_song.get("uri")
                if current_uri == uri:
                    self.current_song["album_art"] = metadata.get(
                        "album_art", "/beatify/static/img/no-artwork.svg"
                    )
                    self.metadata_pending = False

                    _LOGGER.info(
                        "Album art updated for: %s - %s",
                        self.current_song.get("artist"),
                        self.current_song.get("title"),
                    )

                    # Invoke callback to broadcast update (album art only)
                    if self._on_metadata_update:
                        await self._on_metadata_update(
                            {
                                "artist": self.current_song["artist"],
                                "title": self.current_song["title"],
                                "album_art": self.current_song["album_art"],
                            }
                        )
                else:
                    _LOGGER.debug("Metadata arrived for different song, ignoring")
            else:
                _LOGGER.debug("Metadata arrived for different song, ignoring")

        except asyncio.CancelledError:
            _LOGGER.debug("Metadata fetch cancelled")
            raise
        except (KeyError, AttributeError, TypeError, OSError) as err:  # noqa: BLE001
            _LOGGER.warning("Failed to fetch metadata: %s", err)
            self.metadata_pending = False

    async def end_round(self) -> None:
        """
        End the current round and transition to REVEAL.

        Calculates scores for all players and invokes round end callback.
        Acquires _score_lock to prevent concurrent score mutations (AF2-013).

        """
        async with self._score_lock:
            await self._end_round_unlocked()

    async def _end_round_unlocked(self) -> None:
        """Inner end_round logic. Caller MUST hold _score_lock.

        Short orchestrator over the round-end phases (#1272). Each helper runs
        under the caller-held _score_lock — none acquires the lock itself, so
        the _unlocked contract is preserved:
          1. guard + setup (timer cancel, previous-rank snapshot, correct_year)
          2. _score_round            — scoring pass + closest-wins + round_results
          3. _record_round_stats     — highlights, analytics, song-result stats
          4. _transition_to_reveal   — REVEAL announcement + phase flip
          5. _schedule_reveal_advance — vote window / auto-advance / idle-halt
          6. _apply_reveal_lights    — party-light phase + event flashes
          7. round-end broadcast callback
        """
        # Guard: skip if already transitioned (e.g. timer + early reveal race)
        if self.phase != GamePhase.PLAYING:
            _LOGGER.debug("end_round skipped — phase already %s", self.phase.value)
            return

        # Cancel timer if still running
        self.cancel_timer()

        # Issue #23: Cancel intro timer if running
        self._round_manager._cancel_intro_timer()

        # Store current ranks before scoring for rank change detection (5.5)
        self._store_previous_ranks()

        # Get correct year from current song
        correct_year = self.current_song.get("year") if self.current_song else None

        # Issue #415: Warn if scoring without a correct year when players submitted
        if correct_year is None:
            submitted_count = sum(1 for p in self.players.values() if p.submitted)
            if submitted_count > 0:
                _LOGGER.warning(
                    "Scoring round %d with no correct_year — %d submitted player(s) "
                    "will receive 0 points (current_song=%s)",
                    self.round,
                    submitted_count,
                    "missing" if self.current_song is None else "no year field",
                )

        # Phase 2: scoring pass (year/title-artist), closest-wins, round_results
        self._score_round(correct_year)

        # Phase 3: highlights, round analytics, persisted song-result stats
        await self._record_round_stats(correct_year)

        # Phase 4: REVEAL announcement + transition to the REVEAL phase
        await self._transition_to_reveal(correct_year)

        # Phase 5: schedule the title/artist vote window or REVEAL auto-advance
        self._schedule_reveal_advance()

        # Phase 6: party-light phase update + exact/correct flashes
        await self._apply_reveal_lights(correct_year)

        _LOGGER.info("Round %d ended, phase: REVEAL", self.round)

        # Invoke callback to broadcast state
        if self._on_round_end:
            _LOGGER.debug("Invoking round_end callback to broadcast REVEAL state")
            try:
                await self._on_round_end()
                _LOGGER.debug("Round_end callback completed successfully")
            except (ConnectionError, OSError, TypeError) as err:
                _LOGGER.error("Round_end callback failed: %s", err)
        else:
            _LOGGER.warning(
                "No round_end callback set - REVEAL state will not be broadcast!"
            )

    async def _transition_to_reveal(self, correct_year: int | None) -> None:
        """Announce the reveal and flip the phase to REVEAL (#1272).

        Fires the combined REVEAL announcement (before the visible state
        change so audio leads), clears per-phase reactions, sets phase +
        reveal_started_at, and notifies state callbacks. Caller holds
        _score_lock.
        """
        # The per-round REVEAL announcements (correct answer, accuracy,
        # streaks, bets, steal unlocks, standings) collected into ONE
        # combined utterance — see _announce_reveal. Fired BEFORE the phase
        # transition so the audio leads the visible state change, and
        # wrapped so a TTS hiccup never blocks REVEAL below.
        try:
            await self._announce_reveal(correct_year)
        except (KeyError, AttributeError, TypeError, ValueError) as err:
            _LOGGER.error("REVEAL announcement failed: %s", err)

        # Transition to REVEAL
        self._player_registry._reactions_this_phase = (
            set()
        )  # Story 18.9: Clear for new reveal phase
        # #1273: _set_phase stamps reveal_started_at on REVEAL entry (#1048 —
        # so the admin client can render the auto-advance countdown on the
        # sticky Next button) and notifies observers (#441).
        self._set_phase(GamePhase.REVEAL)

    def _schedule_reveal_advance(self) -> None:
        """Schedule the REVEAL vote window or auto-advance task (#1272).

        Sync; caller holds _score_lock. Cancels any prior auto-advance, then
        either opens the title/artist vote window (which owns the dwell) or
        schedules the song-end auto-advance / idle-halt task.
        """
        # #1012: schedule the unattended REVEAL auto-advance — always on
        # (timer 0 = advance at song-end). start_round itself ends the
        # game when songs are exhausted, so this also carries the final
        # round's REVEAL through to END.
        #
        # Exception: a round where nobody submitted a guess means the party
        # is idle — let the song finish, stop playback, and hold on REVEAL
        # instead of burning through the playlist unattended. The host's
        # manual "Next round" still resumes the game.
        self._cancel_auto_advance()
        # #1180 Phase 4: in title/artist mode the conditional vote window owns
        # the REVEAL dwell. It opens the 30s window when there are near-misses
        # (the window task also scores + rebroadcasts on expiry), or resolves
        # immediately and falls through to the normal auto-advance when there
        # are none. When the window is open it already owns _auto_advance_task,
        # so skip the song-end auto-advance scheduling entirely.
        if self.title_artist_mode:
            self._schedule_title_artist_vote_window()
        if not self._title_artist_voting_open:
            if any(p.submitted for p in self.players.values()):
                self._auto_advance_task = asyncio.create_task(
                    self._reveal_auto_advance(self.reveal_auto_advance)
                )
            else:
                _LOGGER.info(
                    "Round %d ended with zero guesses — holding after song-end",
                    self.round,
                )
                self._auto_advance_task = asyncio.create_task(self._reveal_idle_halt())

    async def _apply_reveal_lights(self, correct_year: int | None) -> None:
        """Update party lights for REVEAL + flash on exact/correct (#1272).

        Caller holds _score_lock. Sets the REVEAL light phase, then flashes
        gold when any player was exact (years_off == 0) or green when any was
        within one year.
        """
        # Issue #331/#517: Update Party Lights for reveal phase + event flashes
        await self._lights_set_phase(GamePhase.REVEAL)
        if correct_year is not None:
            has_exact = False
            has_correct = False
            for p in self.players.values():
                if p.submitted and p.years_off is not None:
                    if p.years_off == 0:
                        has_exact = True
                    elif p.years_off <= 1:
                        has_correct = True
            if has_exact:
                await self._lights_flash("gold")
            elif has_correct:
                await self._lights_flash("green")

    def cancel_timer(self) -> None:
        """Cancel the round timer. Delegates to RoundManager."""
        self._round_manager.cancel_timer()

    async def confirm_intro_splash(self) -> None:
        """Handle admin confirmation of intro splash (Issue #292, #403).

        Delegates to RoundManager.
        """
        await self._round_manager.confirm_intro_splash(
            self.play_deferred_song, self._on_round_end, self._timer_countdown
        )

    def is_deadline_passed(self) -> bool:
        """Check if the round deadline has passed. Delegates to RoundManager."""
        return self._round_manager.is_deadline_passed()

    async def advance_to_end(self) -> None:
        """Transition to END phase with proper cleanup (#321).

        Use this instead of setting ``phase = GamePhase.END`` directly.
        Cancels timers so no stale callbacks fire after the game ends.
        Does NOT clear players (they stay for rematch/end screen).
        """
        self.cancel_timer()
        self._round_manager._cancel_intro_timer()
        self._cancel_auto_advance()  # #1012
        # #1273: transition clears reveal_started_at (#1048) + notifies (#441).
        self._set_phase(GamePhase.END)

        # Issue #331: Celebrate with Party Lights, then stop (#553)
        if self._party_lights:
            try:
                await self._party_lights.celebrate()
            except Exception:  # noqa: BLE001
                _LOGGER.warning("Party Lights celebration failed")
            await self.disable_party_lights()

        # Issue #447: Announce winner via TTS
        await self.announce_winner()
        # Issue #841 Phase 3: read out the podium (use case 19).
        await self.announce_podium()

        _LOGGER.info("Game advanced to END phase")

    def calculate_round_analytics(self) -> RoundAnalytics:
        """Calculate round analytics (Story 13.3). Delegates to ScoringService (#139)."""
        correct_year = self.current_song.get("year") if self.current_song else None
        return ScoringService.calculate_round_analytics(
            list(self.players.values()),
            correct_year,
            self.round_start_time,
        )

    @staticmethod
    def _get_decade_label(year: int) -> str:
        """Get decade label for a year (e.g., 1985 -> '1980s')."""
        return _get_decade_label(year)

    def calculate_superlatives(self) -> list[dict[str, Any]]:
        """Calculate fun awards (Story 15.2). Delegates to ScoringService (#139)."""
        return ScoringService.calculate_superlatives(
            list(self.players.values()),
            rounds_played=self.round,
            movie_quiz_enabled=self.movie_quiz_enabled,
            intro_mode_enabled=self.intro_mode_enabled,
            title_artist_mode_enabled=self.title_artist_mode,
        )
