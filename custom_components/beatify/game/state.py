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
import secrets
import time
from enum import Enum
from typing import TYPE_CHECKING, Any

from custom_components.beatify.const import (
    DEFAULT_ROUND_DURATION,
    DIFFICULTY_DEFAULT,
    DIFFICULTY_SCORING,
    ERR_GAME_ALREADY_STARTED,
    ERR_GAME_NOT_STARTED,
    INTRO_DURATION_SECONDS,
    MIN_PLAYERS,
    PROVIDER_DEFAULT,
    ROUND_DURATION_MAX,
    ROUND_DURATION_MIN,
    STREAK_MILESTONES,
    VOLUME_STEP,
)

from .challenges import (
    ArtistChallenge,
    ChallengeManager,
    MovieChallenge,
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
from .serializers import GameStateSerializer
from .share import build_share_data
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


class GameState:
    """Manages game state and phase transitions."""

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
        # Issue #331: Party Lights service
        self._party_lights: PartyLightsProtocol | None = None
        # Issue #447: TTS announcement service
        self._tts_service: Any = None  # TTSService (lazy import)
        self._tts_announce_game_start: bool = True
        self._tts_announce_winner: bool = True
        self._bg_tasks: set[asyncio.Task] = set()  # Issue #391: prevent GC of fire-and-forget tasks

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

        # Timer task for round expiry (Story 4.5)
        self._timer_task: asyncio.Task | None = None

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

    def current_time(self) -> float:
        """Return the current timestamp from the injected clock."""
        return self._now()

    # ------------------------------------------------------------------
    # Player registry delegation (keep public interface identical)
    # ------------------------------------------------------------------

    @property
    def players(self) -> dict[str, PlayerSession]:
        """Player dict — delegated to PlayerRegistry."""
        return self._player_registry.players

    @players.setter
    def players(self, value: dict[str, PlayerSession]) -> None:
        self._player_registry.players = value

    @property
    def _sessions(self) -> dict[str, str]:
        """Session mapping — delegated to PlayerRegistry."""
        return self._player_registry._sessions

    @_sessions.setter
    def _sessions(self, value: dict[str, str]) -> None:
        self._player_registry._sessions = value

    @property
    def _reactions_this_phase(self) -> set[str]:
        """Reaction tracking — delegated to PlayerRegistry."""
        return self._player_registry._reactions_this_phase

    @_reactions_this_phase.setter
    def _reactions_this_phase(self, value: set[str]) -> None:
        self._player_registry._reactions_this_phase = value

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
    def _intro_round_start_time(self) -> float | None:
        """Intro round start time — delegated to RoundManager."""
        return self._round_manager._intro_round_start_time

    @_intro_round_start_time.setter
    def _intro_round_start_time(self, value: float | None) -> None:
        self._round_manager._intro_round_start_time = value

    @property
    def metadata_pending(self) -> bool:
        """Metadata pending flag — delegated to RoundManager."""
        return self._round_manager.metadata_pending

    @metadata_pending.setter
    def metadata_pending(self, value: bool) -> None:
        self._round_manager.metadata_pending = value

    @property
    def _early_reveal(self) -> bool:
        """Early reveal flag — delegated to RoundManager."""
        return self._round_manager._early_reveal

    @_early_reveal.setter
    def _early_reveal(self, value: bool) -> None:
        self._round_manager._early_reveal = value

    @property
    def _intro_splash_pending(self) -> bool:
        """Intro splash pending — delegated to RoundManager."""
        return self._round_manager._intro_splash_pending

    @_intro_splash_pending.setter
    def _intro_splash_pending(self, value: bool) -> None:
        self._round_manager._intro_splash_pending = value

    @property
    def _timer_task(self) -> asyncio.Task | None:
        """Timer task — delegated to RoundManager."""
        return self._round_manager._timer_task

    @_timer_task.setter
    def _timer_task(self, value: asyncio.Task | None) -> None:
        self._round_manager._timer_task = value

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
    # Challenge delegation properties (keep public interface identical)
    # ------------------------------------------------------------------

    @property
    def artist_challenge(self) -> ArtistChallenge | None:
        """Current artist challenge state."""
        return self._challenge_manager.artist_challenge

    @artist_challenge.setter
    def artist_challenge(self, value: ArtistChallenge | None) -> None:
        self._challenge_manager.artist_challenge = value

    @property
    def artist_challenge_enabled(self) -> bool:
        """Whether artist challenge is enabled."""
        return self._challenge_manager.artist_challenge_enabled

    @artist_challenge_enabled.setter
    def artist_challenge_enabled(self, value: bool) -> None:
        self._challenge_manager.artist_challenge_enabled = value

    @property
    def movie_challenge(self) -> MovieChallenge | None:
        """Current movie quiz challenge state."""
        return self._challenge_manager.movie_challenge

    @movie_challenge.setter
    def movie_challenge(self, value: MovieChallenge | None) -> None:
        self._challenge_manager.movie_challenge = value

    @property
    def movie_quiz_enabled(self) -> bool:
        """Whether movie quiz is enabled."""
        return self._challenge_manager.movie_quiz_enabled

    @movie_quiz_enabled.setter
    def movie_quiz_enabled(self, value: bool) -> None:
        self._challenge_manager.movie_quiz_enabled = value

    def create_game(
        self,
        playlists: list[str],
        songs: list[dict[str, Any]],
        media_player: str,
        base_url: str,
        round_duration: int = DEFAULT_ROUND_DURATION,
        difficulty: str = DIFFICULTY_DEFAULT,
        provider: str = PROVIDER_DEFAULT,
        platform: str = "unknown",
        artist_challenge_enabled: bool = True,
        movie_quiz_enabled: bool = True,
        intro_mode_enabled: bool = False,
        closest_wins_mode: bool = False,
    ) -> dict[str, Any]:
        """
        Create a new game session.

        Args:
            playlists: List of playlist file paths
            songs: List of song dicts loaded from playlists
            media_player: Entity ID of media player
            base_url: HA base URL for join URL construction
            round_duration: Round timer duration in seconds (10-60, default 30)
            difficulty: Difficulty level (easy/normal/hard, default normal)
            provider: Music provider (spotify/apple_music, default spotify)
            platform: Platform identifier for playback routing (music_assistant, sonos, alexa_media)
            artist_challenge_enabled: Whether to enable artist guessing (default True)
            movie_quiz_enabled: Whether to enable movie quiz bonus (default True)
            intro_mode_enabled: Whether to enable intro mode (~20% random rounds)
            closest_wins_mode: Whether only the closest guess(es) earn points

        Returns:
            dict with game_id, join_url, song_count, phase

        Raises:
            ValueError: If round_duration is outside valid range (10-60)

        """
        # Validate round duration (Story 13.1)
        if not (ROUND_DURATION_MIN <= round_duration <= ROUND_DURATION_MAX):
            raise ValueError(
                f"Round duration must be between {ROUND_DURATION_MIN} "
                f"and {ROUND_DURATION_MAX} seconds"
            )

        # Clear any leftover sessions from previous/crashed game (Story 11.6)
        self.clear_all_sessions()

        self.game_id = secrets.token_urlsafe(8)
        self.admin_token = secrets.token_urlsafe(16)  # Issue #386: REST admin auth
        self.phase = GamePhase.LOBBY
        self._notify_state_callbacks()
        self.playlists = playlists
        self.songs = songs
        self.media_player = media_player
        self.join_url = f"{base_url}/beatify/play?game={self.game_id}"
        self.players = {}

        # Store provider setting (Story 17.2)
        self.provider = provider

        # Store platform for playback routing
        self.platform = platform

        # Reset error detail
        self.last_error_detail = ""

        # Initialize PlaylistManager for song selection (Epic 4, Story 17.2: with provider)
        self._playlist_manager = PlaylistManager(songs, provider)

        # Reset round tracking for new game
        self.round = 0
        self.total_rounds = len(songs)
        self.deadline = None
        self.current_song = None
        self.last_round = False
        self.pause_reason = None
        self._previous_phase = None

        # Reset timing for speed bonus (Story 5.1) and configurable duration (Story 13.1)
        self.round_start_time = None
        self.round_duration = round_duration

        # Set difficulty (Story 14.1)
        self.difficulty = difficulty

        # Reset song stopped flag (Story 6.2)
        self.song_stopped = False

        # Reset round analytics (Story 13.3)
        self.round_analytics = None

        # Issue #351: Reset power-up state for new game
        self._powerup_manager.reset()

        # Story 20.1 / Issue #28: Set challenge configuration
        self._challenge_manager.configure(
            artist_challenge_enabled=artist_challenge_enabled,
            movie_quiz_enabled=movie_quiz_enabled,
        )

        # Issue #23: Set intro mode configuration
        self.intro_mode_enabled = intro_mode_enabled

        # Issue #442: Set closest wins mode
        self.closest_wins_mode = closest_wins_mode
        self.is_intro_round = False
        self.intro_stopped = False
        self._intro_round_start_time = None
        self._round_manager._rounds_since_intro = 0
        self._round_manager._cancel_intro_timer()

        # Reset timer task for new game
        self.cancel_timer()

        _LOGGER.info("Game created: %s with %d songs", self.game_id, len(songs))

        return {
            "game_id": self.game_id,
            "join_url": self.join_url,
            "phase": self.phase.value,
            "song_count": len(songs),
        }

    def _build_song_dict(self, include_reveal: bool = False) -> dict:
        """Build the song info dict from current_song.

        Args:
            include_reveal: If True, include year and fun_fact fields
                            shown only during REVEAL phase.
        """
        song = self.current_song
        result = {
            "artist": song.get("artist", "Unknown"),
            "title": song.get("title", "Unknown"),
            "album_art": song.get(
                "album_art", "/beatify/static/img/no-artwork.svg"
            ),
        }
        if include_reveal:
            result["year"] = song.get("year")
            result["fun_fact"] = song.get("fun_fact", "")
            result["fun_fact_de"] = song.get("fun_fact_de", "")
            result["fun_fact_es"] = song.get("fun_fact_es", "")
            result["fun_fact_fr"] = song.get("fun_fact_fr", "")
            result["fun_fact_nl"] = song.get("fun_fact_nl", "")
        return result

    def _state_playing(self) -> dict[str, Any]:
        """Return PLAYING phase-specific state fragment."""
        fragment: dict[str, Any] = {
            "join_url": self.join_url,
            "round": self.round,
            "total_rounds": self.total_rounds,
            "deadline": self.deadline,
            "last_round": self.last_round,
            "songs_remaining": (
                self._playlist_manager.get_remaining_count()
                if self._playlist_manager
                else 0
            ),
            # Submission tracking (Story 4.4)
            "submitted_count": sum(
                1 for p in self.players.values() if p.submitted
            ),
            "all_submitted": self.all_submitted(),
            # Leaderboard (Story 5.5)
            "leaderboard": self.get_leaderboard(),
        }
        # Song info WITHOUT year during PLAYING (hidden until reveal)
        if self.current_song:
            fragment["song"] = self._build_song_dict()
        # Story 20.1: Artist challenge (hide answer during PLAYING)
        ac = self._challenge_manager.get_artist_challenge_dict(include_answer=False)
        if ac is not None:
            fragment["artist_challenge"] = ac
        # Issue #28: Movie quiz challenge (hide answer during PLAYING)
        mc = self._challenge_manager.get_movie_challenge_dict(include_answer=False)
        if mc is not None:
            fragment["movie_challenge"] = mc
        return fragment

    def _state_reveal(self) -> dict[str, Any]:
        """Return REVEAL phase-specific state fragment."""
        fragment: dict[str, Any] = {
            "join_url": self.join_url,
            "round": self.round,
            "total_rounds": self.total_rounds,
            "last_round": self.last_round,
            # Include reveal-specific player data (guesses, round_score, missed)
            "players": self.get_reveal_players_state(),
            # Leaderboard (Story 5.5)
            "leaderboard": self.get_leaderboard(),
        }
        # Filtered song info during REVEAL — exclude URIs, alt_artists, internal fields
        if self.current_song:
            fragment["song"] = self._build_song_dict(include_reveal=True)
        # Round analytics (Story 13.3 AC4)
        if self.round_analytics:
            fragment["round_analytics"] = self.round_analytics.to_dict()
        # Game performance comparison (Story 14.4 AC2, AC3, AC4, AC6)
        game_performance = self.get_game_performance()
        if game_performance:
            fragment["game_performance"] = game_performance
        # Song difficulty rating (Story 15.1 AC1, AC4)
        if self._stats_service and self.current_song:
            song_uri = self.current_song.get("uri")
            if song_uri:
                difficulty = self._stats_service.get_song_difficulty(song_uri)
                if difficulty:
                    fragment["song_difficulty"] = difficulty
        # Story 20.1: Artist challenge (reveal answer during REVEAL)
        ac = self._challenge_manager.get_artist_challenge_dict(include_answer=True)
        if ac is not None:
            fragment["artist_challenge"] = ac
        # Issue #28: Movie quiz challenge (reveal answer + results during REVEAL)
        mc = self._challenge_manager.get_movie_challenge_dict(include_answer=True)
        if mc is not None:
            fragment["movie_challenge"] = mc
        # Story 20.9: Early reveal flag for client-side toast
        if self._early_reveal:
            fragment["early_reveal"] = True
        return fragment

    def _state_end(self) -> dict[str, Any]:
        """Return END phase-specific state fragment."""
        fragment: dict[str, Any] = {
            # Final leaderboard with all player stats (Story 5.6)
            "leaderboard": self.get_final_leaderboard(),
            "game_stats": {
                "total_rounds": self.round,
                "total_players": len(self.players),
            },
            # Superlatives - fun awards (Story 15.2)
            "superlatives": self.calculate_superlatives(),
            # Issue #75: Game highlights reel
            "highlights": self.highlights_tracker.to_dict(),
            # Issue #120: Shareable result cards
            "share_data": build_share_data(self),
        }
        # Include winner info
        if self.players:
            winner = max(self.players.values(), key=lambda p: p.score)
            fragment["winner"] = {"name": winner.name, "score": winner.score}
        # Game performance comparison for end screen (Story 14.4 AC5, AC6)
        game_performance = self.get_game_performance()
        if game_performance:
            fragment["game_performance"] = game_performance
        return fragment

    def get_state(self) -> dict[str, Any] | None:
        """Get current game state for broadcast.

        Delegates to GameStateSerializer (Issue #464).

        Returns:
            Game state dict or None if no active game

        """
        return GameStateSerializer.serialize(self)

    def get_reveal_players_state(self) -> list[dict[str, Any]]:
        """Get player state with reveal info for REVEAL phase.

        Delegates to GameStateSerializer (Issue #464).

        Returns:
            List of player dicts including guess, round_score, years_off,
            speed bonus data (Story 5.1), streak bonus (Story 5.2),
            and artist bonus (Story 20.4), sorted by total score descending.

        """
        return GameStateSerializer.get_reveal_players_state(self)

    def finalize_game(self) -> dict[str, Any]:
        """
        Calculate final stats before ending the game (Story 14.4).

        Must be called BEFORE end_game() to capture statistics.
        Returns summary dict for StatsService.record_game().

        Returns:
            Game summary dict with playlist, rounds, player_count,
            winner, winner_score, total_points, avg_score_per_round

        """
        # Calculate totals
        total_points = sum(p.score for p in self.players.values())
        player_count = len(self.players)
        rounds_played = self.round

        # Determine winner
        winner_name = "Unknown"
        winner_score = 0
        if self.players:
            winner = max(self.players.values(), key=lambda p: p.score)
            winner_name = winner.name
            winner_score = winner.score

        # Calculate average score per round
        avg_score_per_round = 0.0
        if rounds_played > 0 and player_count > 0:
            avg_score_per_round = total_points / (rounds_played * player_count)

        # Determine playlist name (use first playlist or "mixed")
        playlist_name = "unknown"
        if self.playlists:
            # Extract playlist name from path
            playlist_path = self.playlists[0]
            if "/" in playlist_path:
                playlist_name = playlist_path.split("/")[-1].replace(".json", "")
            else:
                playlist_name = playlist_path.replace(".json", "")

        return {
            "playlist": playlist_name,
            "rounds": rounds_played,
            "player_count": player_count,
            "winner": winner_name,
            "winner_score": winner_score,
            "total_points": total_points,
            "avg_score_per_round": round(avg_score_per_round, 2),
            # Story 19.11: Include streak achievements
            "streak_3_count": self.streak_achievements.get("streak_3", 0),
            "streak_5_count": self.streak_achievements.get("streak_5", 0),
            "streak_10_count": self.streak_achievements.get("streak_10", 0),
            # Story 19.12: Include bet tracking
            "total_bets": self.bet_tracking.get("total_bets", 0),
            "bets_won": self.bet_tracking.get("bets_won", 0),
        }

    def _reset_game_internals(self) -> None:
        """Reset internal game state (Issue #108, #464).

        Shared by end_game() and rematch_game() to prevent field drift.
        Uses GameStateConfig to rebuild config-managed fields from defaults,
        and delegates round state reset to RoundManager.reset().

        Does NOT reset: players, sessions, phase, game_id, callbacks,
        service refs (_stats_service, _on_round_end, _on_metadata_update),
        or volume_level (caller's responsibility).
        """
        # Issue #477: Clear admin spectator WS (connection stays open, just de-ref)
        self._admin_ws = None

        # Issue #464: Reset round lifecycle (timers, metadata, intro state)
        self._round_manager.reset()
        self.cancel_timer()

        # Issue #464: Rebuild config-managed fields from defaults
        self._apply_config(self._default_config)

        # Issue #351: Reset power-up state
        self._powerup_manager.reset()

        # Story 20.1 / Issue #28: Reset challenges
        self._challenge_manager.reset()

        # Issue #75: Reset highlights tracker
        self.highlights_tracker.reset()

    async def end_game(self) -> None:
        """End the current game and reset state."""
        _LOGGER.info("Game ended: %s", self.game_id)
        self.cancel_timer()
        # Issue #331: Restore lights before resetting
        await self.disable_party_lights()
        # Issue #447: Disable TTS
        await self.disable_tts()
        self._reset_game_internals()
        self.game_id = None
        self.phase = GamePhase.LOBBY
        self.players = {}
        self.clear_all_sessions()
        self._notify_state_callbacks()

    def rematch_game(self) -> None:
        """Reset game for rematch, preserving connected players (Issue #108)."""
        _LOGGER.info("Rematch initiated from game: %s", self.game_id)
        self.cancel_timer()

        # Preserve game settings that the admin configured
        preserved_playlists = self.playlists
        preserved_songs = list(self.songs)  # Copy so we get a fresh playlist
        preserved_media_player = self.media_player
        preserved_join_url = self.join_url
        preserved_provider = self.provider
        preserved_platform = self.platform
        preserved_difficulty = self.difficulty
        preserved_language = self.language
        preserved_round_duration = self.round_duration
        preserved_artist_challenge = self.artist_challenge_enabled
        preserved_movie_quiz = self.movie_quiz_enabled
        preserved_intro_mode = self.intro_mode_enabled
        preserved_closest_wins = self.closest_wins_mode

        self._reset_game_internals()

        # Restore preserved settings for seamless rematch
        self.playlists = preserved_playlists
        self.songs = preserved_songs
        self.media_player = preserved_media_player
        self.provider = preserved_provider
        self.platform = preserved_platform
        self.difficulty = preserved_difficulty
        self.language = preserved_language
        self.round_duration = preserved_round_duration
        self.artist_challenge_enabled = preserved_artist_challenge
        self.movie_quiz_enabled = preserved_movie_quiz
        self.intro_mode_enabled = preserved_intro_mode
        self.closest_wins_mode = preserved_closest_wins

        # Re-create PlaylistManager with fresh song list
        self._playlist_manager = PlaylistManager(preserved_songs, preserved_provider)
        self.total_rounds = len(preserved_songs)

        self.phase = GamePhase.LOBBY
        self._notify_state_callbacks()
        # Reset each player's game stats but keep them connected
        for player in self.players.values():
            player.reset_for_new_game()
        # Generate new game ID and admin token for the rematch
        self.game_id = secrets.token_urlsafe(8)
        self.admin_token = secrets.token_urlsafe(16)  # Issue #386

        # Regenerate join_url with new game_id
        if preserved_join_url:
            base_url = preserved_join_url.split("/beatify/play")[0]
            self.join_url = f"{base_url}/beatify/play?game={self.game_id}"

        _LOGGER.info(
            "Rematch ready with %d players, %d songs, new game_id: %s",
            len(self.players),
            self.total_rounds,
            self.game_id,
        )

    async def pause_game(self, reason: str) -> bool:
        """
        Pause the game (typically due to admin disconnect).

        Args:
            reason: Pause reason code (e.g., "admin_disconnected")

        Returns:
            True if successfully paused, False if already paused/ended

        """
        if self.phase == GamePhase.PAUSED:
            return False  # Already paused
        if self.phase == GamePhase.END:
            return False  # Can't pause ended game

        # Store current phase for resume
        self._previous_phase = self.phase
        self.pause_reason = reason

        # Store admin name for rejoin verification (Story 7-2)
        if reason == "admin_disconnected":
            for player in self.players.values():
                if player.is_admin:
                    self.disconnected_admin_name = player.name
                    break

        # Stop timer if in PLAYING
        if self.phase == GamePhase.PLAYING:
            self.cancel_timer()
            # Issue #23: Cancel intro timer if running
            self._round_manager._cancel_intro_timer()
            # Stop media playback
            if self._media_player_service:
                await self._media_player_service.stop()

        # Transition to PAUSED
        self.phase = GamePhase.PAUSED
        self._notify_state_callbacks()
        _LOGGER.info("Game paused: %s", reason)

        return True

    async def resume_game(self) -> bool:
        """
        Resume game from PAUSED state.

        Returns:
            True if successfully resumed, False if not paused

        """
        if self.phase != GamePhase.PAUSED:
            return False
        if self._previous_phase is None:
            _LOGGER.error("Cannot resume: no previous phase stored")
            return False

        previous = self._previous_phase

        # Restart timer if resuming to PLAYING and deadline still valid
        if previous == GamePhase.PLAYING and self.deadline:
            now_ms = int(self._now() * 1000)
            remaining_ms = self.deadline - now_ms

            if remaining_ms > 0:
                remaining_seconds = remaining_ms / 1000.0
                self._round_manager._timer_task = asyncio.create_task(
                    self._timer_countdown(remaining_seconds)
                )
                _LOGGER.info("Timer restarted with %.1fs remaining", remaining_seconds)

                # Issue #416: Restart intro stop timer if this was an intro round
                # Issue #496: Use actual playing time (excludes pause duration)
                if (
                    self.is_intro_round
                    and not self.intro_stopped
                    and self._intro_round_start_time is not None
                ):
                    elapsed_intro = self._round_manager.round_duration - remaining_seconds
                    remaining_intro = INTRO_DURATION_SECONDS - elapsed_intro
                    if remaining_intro > 0:
                        self._round_manager._intro_stop_task = asyncio.create_task(
                            self._round_manager._intro_auto_stop(remaining_intro, self._on_round_end)
                        )
                        _LOGGER.info(
                            "Intro stop timer restarted with %.1fs remaining",
                            remaining_intro,
                        )

                # Resume media playback if it was stopped
                if self._media_player_service and self.current_song:
                    await self._media_player_service.play()
                    _LOGGER.info("Media playback resumed")
            else:
                # Timer expired during pause — end the round immediately
                _LOGGER.info("Timer expired during pause, ending round")
                self.phase = previous
                self._notify_state_callbacks()
                self.pause_reason = None
                self.disconnected_admin_name = None
                self._previous_phase = None
                await self.end_round()
                return True

        # Restore previous phase
        self.phase = previous
        self._notify_state_callbacks()
        self.pause_reason = None
        self.disconnected_admin_name = None
        self._previous_phase = None

        _LOGGER.info("Game resumed to phase: %s", previous.value)

        return True

    def get_average_score(self) -> int:
        """Calculate average score of all current players. Delegates to PlayerRegistry."""
        return self._player_registry.get_average_score()

    def add_player(
        self, name: str, ws: web.WebSocketResponse
    ) -> tuple[bool, str | None]:
        """Add a player to the game. Delegates to PlayerRegistry."""
        return self._player_registry.add_player(
            name, ws, self.phase, self.get_average_score
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
                p.has_artist_guess for p in self.players.values() if p.connected
            )
            if not has_winner and anyone_guessed:
                for player in self.players.values():
                    if player.connected and not player.has_artist_guess:
                        return False

        # Issue #28: If movie quiz enabled and active, check movie guesses
        # Skip check if challenge already has correct guesses or no one interacted
        if self.movie_quiz_enabled and self.movie_challenge:
            has_correct = len(self.movie_challenge.correct_guesses) > 0
            anyone_guessed = any(
                p.has_movie_guess for p in self.players.values() if p.connected
            )
            if not has_correct and anyone_guessed:
                for player in self.players.values():
                    if player.connected and not player.has_movie_guess:
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
            self._early_reveal = True
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

    def set_stats_service(self, stats_service: StatsService) -> None:
        """
        Set stats service reference (Story 14.4).

        Args:
            stats_service: StatsService instance for game performance tracking

        """
        self._stats_service = stats_service
        _LOGGER.info("Stats service connected to GameState")

    def _calculate_current_avg(self) -> float:
        """
        Calculate current game's average score per round (Story 14.4).

        Used for in-game comparison to all-time average.

        Returns:
            Current game average score per round, or 0.0 if no data

        """
        if self.round == 0 or not self.players:
            return 0.0

        total_points = sum(p.score for p in self.players.values())
        player_count = len(self.players)

        return total_points / (self.round * player_count)

    def get_game_performance(self) -> dict[str, Any] | None:
        """
        Get game performance comparison data (Story 14.4).

        Used during REVEAL and END phases to show motivational feedback.

        Returns:
            Performance dict with comparison data, or None if no stats service

        """
        if not self._stats_service:
            _LOGGER.debug("get_game_performance: No stats service connected")
            return None

        current_avg = self._calculate_current_avg()
        comparison = self._stats_service.get_game_comparison(current_avg)
        message_data = self._stats_service.get_motivational_message(comparison)

        return {
            "current_avg": round(current_avg, 2),
            "all_time_avg": comparison["all_time_avg"],
            "difference": comparison["difference"],
            "is_above_average": comparison["is_above_average"],
            "is_new_record": comparison["is_new_record"],
            "is_first_game": comparison["is_first_game"],
            "message": message_data,
        }

    def set_admin(self, name: str) -> bool:
        """Mark a player as admin. Delegates to PlayerRegistry."""
        return self._player_registry.set_admin(name)

    def start_game(self) -> tuple[bool, str | None]:
        """
        Start the game, transitioning from LOBBY to PLAYING.

        Returns:
            (success, error_code) - error_code is None on success

        """
        if self.phase != GamePhase.LOBBY:
            return False, ERR_GAME_ALREADY_STARTED

        if len(self.players) < MIN_PLAYERS:
            return False, ERR_GAME_NOT_STARTED  # Need at least MIN_PLAYERS to play

        self.phase = GamePhase.PLAYING
        self._notify_state_callbacks()
        # Round and song selection will be implemented in Epic 4
        _LOGGER.info("Game started: %d players", len(self.players))
        return True, None

    async def start_round(self, _retry_count: int = 0) -> bool:
        """Start a new round with song playback (#390).

        Args:
            _retry_count: Internal counter for failed song attempts (max 3)

        Returns:
            True if round started successfully, False otherwise

        """
        MAX_SONG_RETRIES = 3

        if not self._playlist_manager:
            _LOGGER.error("No playlist manager configured")
            return False

        # Get next playable song (skip songs without URI for selected provider)
        song = self._playlist_manager.get_next_song()
        if not song:
            _LOGGER.info("All songs exhausted, ending game")
            self.phase = GamePhase.END
            self._notify_state_callbacks()
            return False

        resolved_uri = song.get("_resolved_uri")
        if not resolved_uri:
            _LOGGER.warning("Skipping song (year %s) - no URI for provider", song.get("year", "?"))
            self._playlist_manager.mark_played(song.get("uri"))
            if _retry_count >= MAX_SONG_RETRIES:
                _LOGGER.error("No playable songs found after %d attempts, pausing game", MAX_SONG_RETRIES)
                await self.pause_game("no_songs_available")
                return False
            return await self.start_round(_retry_count + 1)

        self.last_round = self._playlist_manager.get_remaining_count() <= 1
        self._ensure_media_player_service()
        will_defer_for_splash = self._prepare_intro_round(song)

        # Play song via media player (skip if deferred for intro splash)
        if self._media_player_service and not will_defer_for_splash:
            if not self._media_player_service.is_available():
                self.last_error_detail = f"Media player {self.media_player} is unavailable"
                _LOGGER.error("Media player %s is not available, pausing game", self.media_player)
                await self.pause_game("media_player_error")
                return False

            # Additional responsiveness check for non-MA players
            if self.platform != "music_assistant":
                responsive, error_detail = await self._media_player_service.verify_responsive()
                if not responsive:
                    self.last_error_detail = error_detail
                    _LOGGER.error("Media player not responsive: %s, pausing game", error_detail)
                    await self.pause_game("media_player_error")
                    return False

            success = await self._media_player_service.play_song(song)
            if not success:
                _LOGGER.warning("Failed to play song: %s", song.get("uri"))
                self._playlist_manager.mark_played(song.get("_resolved_uri") or song.get("uri"))
                if _retry_count >= MAX_SONG_RETRIES:
                    _LOGGER.error("Media player unreachable after %d attempts, pausing game", MAX_SONG_RETRIES)
                    await self.pause_game("media_player_error")
                    return False
                await asyncio.sleep(1.0)
                return await self.start_round(_retry_count + 1)

        metadata = self._build_round_metadata(song, resolved_uri, will_defer_for_splash)
        self._initialize_round(song, metadata, resolved_uri, will_defer_for_splash)

        delay_seconds = (self.deadline - int(self._now() * 1000)) / 1000.0
        await self._lights_set_phase(GamePhase.PLAYING)
        _LOGGER.info(
            "Round %d started: %s - %s (%.1fs timer)",
            self.round,
            self.current_song.get("artist"),
            self.current_song.get("title"),
            delay_seconds,
        )
        return True

    def _ensure_media_player_service(self) -> None:
        """Create MediaPlayerService lazily on first round."""
        # Lazy import: only the concrete class for instantiation; type hints
        # use MediaPlayerProtocol (module-level) to keep the import graph acyclic.
        from custom_components.beatify.services.media_player import (  # noqa: PLC0415
            MediaPlayerService,
        )
        if self.media_player and not self._media_player_service:
            self._media_player_service = MediaPlayerService(
                self._hass, self.media_player, platform=self.platform, provider=self.provider
            )
            # Connect analytics for error recording (Story 19.1 AC: #2)
            if self._stats_service and hasattr(self._stats_service, "_analytics"):
                self._media_player_service.set_analytics(self._stats_service._analytics)

    def _prepare_intro_round(self, song: dict) -> bool:
        """Determine if this is an intro round. Delegates to RoundManager."""
        return self._round_manager.prepare_intro_round(song, self._hass)

    def _build_round_metadata(self, song: dict, resolved_uri: str, will_defer_for_splash: bool) -> dict:
        """Build initial metadata dict. Delegates to RoundManager."""
        return self._round_manager.build_round_metadata(
            song, resolved_uri, will_defer_for_splash,
            self._media_player_service,
            self._fetch_metadata_async(resolved_uri),
        )

    def _initialize_round(
        self,
        song: dict,
        metadata: dict,
        resolved_uri: str,
        will_defer_for_splash: bool,
    ) -> None:
        """Commit all round state. Delegates to RoundManager."""
        self._round_manager.initialize_round(
            song, metadata, resolved_uri, will_defer_for_splash,
            self._playlist_manager,
            self._challenge_manager,
            self.players,
            self._timer_countdown,
            self._on_round_end,
        )
        self.round_analytics = None
        self.phase = GamePhase.PLAYING
        self._notify_state_callbacks()

    async def _timer_countdown(self, delay_seconds: float) -> None:
        """Wait for round to end, then trigger reveal.

        Wraps RoundManager._timer_countdown with phase-aware end_round call.
        """
        try:
            await self._round_manager._timer_countdown(delay_seconds)
            # Timer completed normally — check phase and end round
            if self.phase == GamePhase.PLAYING:
                await self.end_round()
            else:
                _LOGGER.debug(
                    "Timer expired but phase already changed to %s", self.phase
                )
        except asyncio.CancelledError:
            _LOGGER.debug("Timer task cancelled")
            raise

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
            if self.current_song and self.current_song.get("uri") == uri:
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

        except asyncio.CancelledError:
            _LOGGER.debug("Metadata fetch cancelled")
            raise
        except Exception as err:  # noqa: BLE001
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
        """Inner end_round logic. Caller MUST hold _score_lock."""
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

        # Calculate scores for all players — delegates to ScoringService (#139)
        all_players = list(self.players.values())
        for player in self.players.values():
            ScoringService.score_player_round(
                player,
                correct_year=correct_year,
                round_start_time=self.round_start_time,
                round_duration=self.round_duration,
                difficulty=self.difficulty,
                artist_challenge=self.artist_challenge,
                movie_challenge=self.movie_challenge,
                is_intro_round=self.is_intro_round,
                intro_round_start_time=self._intro_round_start_time,
                all_players=all_players,
                streak_achievements=self.streak_achievements,
                bet_tracking=self.bet_tracking,
            )

        # Issue #442: Closest Wins — zero out non-closest players' scores
        if self.closest_wins_mode and correct_year is not None:
            ScoringService.apply_closest_wins(all_players, correct_year)

        # Issue #120: Track round results for shareable result cards
        if correct_year is not None:
            scoring_cfg = DIFFICULTY_SCORING.get(
                self.difficulty, DIFFICULTY_SCORING[DIFFICULTY_DEFAULT]
            )
            close_range = scoring_cfg["close_range"]
            near_range = scoring_cfg["near_range"]
            for player in self.players.values():
                if player.submitted and player.years_off is not None:
                    if player.years_off == 0:
                        player.round_results.append("exact")
                    elif close_range > 0 and player.years_off <= close_range:
                        player.round_results.append("scored")
                    elif near_range > 0 and player.years_off <= near_range:
                        player.round_results.append("close")
                    else:
                        player.round_results.append("missed")
                else:
                    player.round_results.append("missed")

        # Issue #75: Record highlights after scoring
        try:
            self._record_round_highlights(correct_year)
        except Exception as err:
            _LOGGER.error("Failed to record round highlights: %s", err)

        # Issue #23: Music continues playing through reveal for intro rounds.
        # No resume needed — _intro_auto_stop no longer pauses playback.

        # Calculate round analytics after scoring (Story 13.3)
        try:
            self.round_analytics = self.calculate_round_analytics()
        except Exception as err:
            _LOGGER.error("Failed to calculate round analytics: %s", err)
            self.round_analytics = None

        # Record song results for difficulty tracking (Story 15.1 AC3)
        # Extended for song statistics (Story 19.7)
        # Wrapped in try/catch to ensure round transition completes even if stats fail
        if self._stats_service and self.current_song:
            song_uri = self.current_song.get("uri")
            if song_uri:
                try:
                    # Build player results list for song difficulty calculation
                    player_results = [
                        {
                            "submitted": p.submitted,
                            "years_off": p.years_off if p.years_off is not None else 0,
                        }
                        for p in self.players.values()
                    ]
                    # Story 19.7: Pass song metadata and playlist info
                    song_metadata = {
                        "title": self.current_song.get("title", "Unknown"),
                        "artist": self.current_song.get("artist", "Unknown"),
                        "year": self.current_song.get("year", 0),
                    }
                    # Extract playlist name from path (e.g., "greatest-hits.json" -> "Greatest Hits")
                    playlist_name = None
                    if self.playlists:
                        playlist_path = self.playlists[0]
                        playlist_name = (
                            playlist_path.replace(".json", "").replace("-", " ").title()
                        )
                    await self._stats_service.record_song_result(
                        song_uri,
                        player_results,
                        song_metadata=song_metadata,
                        playlist_name=playlist_name,
                        difficulty=self.difficulty,
                    )
                except Exception as err:
                    _LOGGER.error("Failed to record song results: %s", err)

        # Transition to REVEAL
        self._reactions_this_phase = set()  # Story 18.9: Clear for new reveal phase
        self.phase = GamePhase.REVEAL
        self._notify_state_callbacks()

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

        _LOGGER.info("Round %d ended, phase: REVEAL", self.round)

        # Invoke callback to broadcast state
        if self._on_round_end:
            _LOGGER.debug("Invoking round_end callback to broadcast REVEAL state")
            try:
                await self._on_round_end()
                _LOGGER.debug("Round_end callback completed successfully")
            except Exception as err:
                _LOGGER.error("Round_end callback failed: %s", err)
        else:
            _LOGGER.warning(
                "No round_end callback set - REVEAL state will not be broadcast!"
            )

    def _record_round_highlights(self, correct_year: int | None) -> None:
        """Detect and record highlights for the current round (Issue #75)."""
        if correct_year is None:
            return

        song_title = ""
        if self.current_song:
            song_title = self.current_song.get("title", "Unknown")

        submitted_players = [
            p
            for p in self.players.values()
            if p.submitted and p.current_guess is not None
        ]

        for player in submitted_players:
            # Exact match
            if player.years_off == 0:
                self.highlights_tracker.record_exact_match(
                    player.name, song_title, correct_year, self.round
                )

            # Heartbreaker (off by 1)
            if player.years_off == 1:
                self.highlights_tracker.record_heartbreaker(
                    player.name, song_title, 1, self.round
                )

            # Streak milestones
            if player.streak in STREAK_MILESTONES:
                self.highlights_tracker.record_streak(
                    player.name, player.streak, self.round
                )
                # Fire-and-forget flash (sync context — cannot await)
                task = asyncio.create_task(self._lights_flash("orange"))
                self._bg_tasks.add(task)
                task.add_done_callback(self._bg_tasks.discard)

            # Bet win
            if player.bet_outcome == "won" and player.round_score >= 10:
                self.highlights_tracker.record_bet_win(
                    player.name, player.round_score, self.round
                )

            # Comeback (gained 2+ positions)
            if player.previous_rank is not None:
                # Calculate current rank
                sorted_players = sorted(
                    self.players.values(), key=lambda p: (-p.score, p.name)
                )
                current_rank = next(
                    (
                        i + 1
                        for i, p in enumerate(sorted_players)
                        if p.name == player.name
                    ),
                    None,
                )
                if current_rank is not None:
                    positions_gained = player.previous_rank - current_rank
                    if positions_gained >= 2:
                        self.highlights_tracker.record_comeback(
                            player.name, positions_gained, self.round
                        )

        # Speed record (fastest submission this round)
        timed = [
            (p, p.submission_time - self.round_start_time)
            for p in submitted_players
            if p.submission_time is not None and self.round_start_time is not None
        ]
        if timed:
            fastest_player, fastest_time = min(timed, key=lambda x: x[1])
            if fastest_time < 5.0:  # Only highlight very fast answers
                self.highlights_tracker.record_speed_record(
                    fastest_player.name, fastest_time, self.round
                )

        # Photo finish (tied round scores among top players) — Issue #414
        scores = [p.round_score for p in self.players.values()]
        if len(scores) >= 2:
            from collections import Counter

            score_counts = Counter(scores)
            for score, count in score_counts.items():
                if count >= 2 and score > 0:
                    tied_names = [
                        p.name
                        for p in self.players.values()
                        if p.round_score == score
                    ]
                    # Only record if it's among the top scores
                    top_score = max(scores)
                    if score >= top_score * 0.8:
                        self.highlights_tracker.record_photo_finish(
                            tied_names, self.round
                        )
                        break  # Only one photo finish per round

    def cancel_timer(self) -> None:
        """Cancel the round timer. Delegates to RoundManager."""
        self._round_manager.cancel_timer()

    async def confirm_intro_splash(self) -> None:
        """Handle admin confirmation of intro splash (Issue #292, #403).

        Delegates to RoundManager.
        """
        await self._round_manager.confirm_intro_splash(
            self.play_deferred_song, self._on_round_end
        )

    def is_deadline_passed(self) -> bool:
        """Check if the round deadline has passed. Delegates to RoundManager."""
        return self._round_manager.is_deadline_passed()

    def get_leaderboard(self) -> list[dict[str, Any]]:
        """
        Get leaderboard sorted by score (Story 5.5).

        Returns:
            List of player data with rank and movement info.
            Note: is_current is set client-side based on playerName.

        """
        # Sort by score descending, then by name for tie-breaking display order
        sorted_players = sorted(
            self.players.values(),
            key=lambda p: (-p.score, p.name),
        )

        leaderboard = []
        current_rank = 0
        previous_score = None

        for i, player in enumerate(sorted_players):
            # Handle ties (same score = same rank)
            # Example: scores [100, 80, 80, 50] -> ranks [1, 2, 2, 4]
            if player.score != previous_score:
                current_rank = i + 1  # Rank jumps to position (skips tied ranks)
            previous_score = player.score

            # Calculate rank change (positive = moved up)
            rank_change = 0
            if player.previous_rank is not None:
                rank_change = player.previous_rank - current_rank

            entry = {
                "rank": current_rank,
                "name": player.name,
                "score": player.score,
                "streak": player.streak,
                "is_admin": player.is_admin,
                "rank_change": rank_change,
                "connected": player.connected,
            }
            leaderboard.append(entry)

        return leaderboard

    def _store_previous_ranks(self) -> None:
        """Store current ranks before scoring for rank change detection."""
        sorted_players = sorted(
            self.players.values(),
            key=lambda p: (-p.score, p.name),
        )

        current_rank = 0
        previous_score = None

        for i, player in enumerate(sorted_players):
            if player.score != previous_score:
                current_rank = i + 1
            previous_score = player.score
            player.previous_rank = current_rank

    def get_final_leaderboard(self) -> list[dict[str, Any]]:
        """
        Get final leaderboard with full player stats (Story 5.6).

        Returns:
            List of player data with rank and final stats.
            Note: is_current is set client-side based on playerName.

        """
        # Sort by score descending, then by name for tie-breaking display order
        sorted_players = sorted(
            self.players.values(),
            key=lambda p: (-p.score, p.name),
        )

        leaderboard = []
        current_rank = 0
        previous_score = None

        for i, player in enumerate(sorted_players):
            if player.score != previous_score:
                current_rank = i + 1
            previous_score = player.score

            entry = {
                "rank": current_rank,
                "name": player.name,
                "score": player.score,
                "is_admin": player.is_admin,
                "connected": player.connected,
                # Final stats (Story 5.6)
                "best_streak": player.best_streak,
                "rounds_played": player.rounds_played,
                "bets_won": player.bets_won,
            }
            leaderboard.append(entry)

        return leaderboard

    async def advance_to_end(self) -> None:
        """Transition to END phase with proper cleanup (#321).

        Use this instead of setting ``phase = GamePhase.END`` directly.
        Cancels timers so no stale callbacks fire after the game ends.
        Does NOT clear players (they stay for rematch/end screen).
        """
        self.cancel_timer()
        self._round_manager._cancel_intro_timer()
        self.phase = GamePhase.END
        self._notify_state_callbacks()

        # Issue #331: Celebrate with Party Lights
        await self._lights_celebrate()

        # Issue #447: Announce winner via TTS
        await self.announce_winner()

        _LOGGER.info("Game advanced to END phase")

    async def stop_media(self) -> None:
        """Stop media playback if a media player service is available (#321)."""
        if self._media_player_service:
            await self._media_player_service.stop()

    async def set_volume_on_player(self, level: float) -> bool:
        """Apply volume level to the media player (#321).

        Returns:
            True if successful, False if failed or no media player.
        """
        if self._media_player_service:
            return await self._media_player_service.set_volume(level)
        return False

    async def seek_forward(self, seconds: int) -> bool:
        """Seek media player forward by given seconds (#498)."""
        if self._media_player_service:
            return await self._media_player_service.seek_forward(seconds)
        return False

    async def play_deferred_song(self, song: dict) -> bool:
        """Play a song that was deferred for intro splash (#321).

        Returns:
            True if playback started, False otherwise.
        """
        if self._media_player_service:
            return await self._media_player_service.play_song(song)
        return False

    # ------------------------------------------------------------------
    # Party Lights (#331)
    # ------------------------------------------------------------------

    async def configure_party_lights(
        self,
        entity_ids: list[str],
        intensity: str = "medium",
        light_mode: str = "dynamic",
        wled_presets: dict[str, int] | None = None,
    ) -> None:
        """Configure and start Party Lights for the game."""
        # Lazy import: only the concrete class for instantiation; type hints
        # use PartyLightsProtocol (module-level) to keep the import graph acyclic.
        from custom_components.beatify.services.lights import PartyLightsService  # noqa: PLC0415

        self._party_lights = PartyLightsService(self._hass)
        await self._party_lights.start(entity_ids, intensity, light_mode, wled_presets)

    async def disable_party_lights(self) -> None:
        """Stop Party Lights and restore original light states."""
        if self._party_lights:
            await self._party_lights.stop()
            self._party_lights = None

    async def _lights_set_phase(self, phase: GamePhase) -> None:
        """Set Party Lights phase color (fire-and-forget)."""
        if self._party_lights:
            try:
                await self._party_lights.set_phase(phase)
            except Exception:  # noqa: BLE001
                _LOGGER.warning("Party Lights phase change failed")

    async def _lights_flash(self, color: str) -> None:
        """Flash Party Lights (fire-and-forget)."""
        if self._party_lights:
            try:
                task = asyncio.create_task(self._party_lights.flash(color))
                self._bg_tasks.add(task)
                task.add_done_callback(self._bg_tasks.discard)
            except Exception:  # noqa: BLE001
                _LOGGER.warning("Party Lights flash failed")

    async def _lights_strobe(self, count: int = 5) -> None:
        """Run Party Lights strobe effect (fire-and-forget)."""
        if self._party_lights:
            try:
                task = asyncio.create_task(self._party_lights.strobe(count))
                self._bg_tasks.add(task)
                task.add_done_callback(self._bg_tasks.discard)
            except Exception:  # noqa: BLE001
                _LOGGER.warning("Party Lights strobe failed")

    async def _lights_celebrate(self) -> None:
        """Run Party Lights celebration (fire-and-forget)."""
        if self._party_lights:
            try:
                task = asyncio.create_task(self._party_lights.celebrate())
                self._bg_tasks.add(task)
                task.add_done_callback(self._bg_tasks.discard)
            except Exception:  # noqa: BLE001
                _LOGGER.warning("Party Lights celebration failed")

    # ------------------------------------------------------------------
    # TTS Announcements (#447)
    # ------------------------------------------------------------------

    async def configure_tts(
        self,
        entity_id: str,
        *,
        announce_game_start: bool = True,
        announce_winner: bool = True,
    ) -> None:
        """Configure TTS announcement service for the game."""
        from custom_components.beatify.services.tts import TTSService  # noqa: PLC0415

        self._tts_service = TTSService(self._hass, entity_id)
        self._tts_announce_game_start = announce_game_start
        self._tts_announce_winner = announce_winner

    async def disable_tts(self) -> None:
        """Disable TTS announcements."""
        self._tts_service = None

    async def _tts_announce(self, message: str) -> None:
        """Speak a TTS announcement (fire-and-forget)."""
        if self._tts_service:
            try:
                task = asyncio.create_task(self._tts_service.speak(message))
                self._bg_tasks.add(task)
                task.add_done_callback(self._bg_tasks.discard)
            except Exception:  # noqa: BLE001
                _LOGGER.warning("TTS announcement failed")

    async def announce_game_start(self) -> None:
        """Announce game start (use case 16)."""
        if not self._tts_service or not self._tts_announce_game_start:
            return
        message = (
            f"Let's play Beatify! {self.total_rounds} rounds, "
            f"{self.difficulty} difficulty."
        )
        await self._tts_announce(message)

    async def announce_winner(self) -> None:
        """Announce the winner (use case 18)."""
        if not self._tts_service or not self._tts_announce_winner or not self.players:
            return
        winner = max(self.players.values(), key=lambda p: p.score)
        message = (
            f"And the winner is... {winner.name} with {winner.score} points!"
        )
        await self._tts_announce(message)

    def adjust_volume(self, direction: str) -> float:
        """
        Adjust volume level by step (Story 6.4).

        Args:
            direction: "up" to increase, "down" to decrease

        Returns:
            New volume level (clamped 0.0 to 1.0)

        """
        # Sync with actual media player volume before adjusting
        if self._media_player_service:
            self.volume_level = self._media_player_service.get_volume()

        if direction == "up":
            self.volume_level = min(1.0, self.volume_level + VOLUME_STEP)
        elif direction == "down":
            self.volume_level = max(0.0, self.volume_level - VOLUME_STEP)

        return self.volume_level

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
        )

    def submit_artist_guess(
        self, player_name: str, artist: str, guess_time: float
    ) -> dict[str, Any]:
        """Submit artist guess for bonus points (Story 20.3). Delegates to ChallengeManager."""
        return self._challenge_manager.submit_artist_guess(
            player_name, artist, guess_time
        )

    def submit_movie_guess(
        self, player_name: str, movie: str, guess_time: float
    ) -> dict[str, Any]:
        """Submit movie guess for bonus points (Issue #28). Delegates to ChallengeManager."""
        return self._challenge_manager.submit_movie_guess(
            player_name, movie, guess_time, self.round_start_time
        )
