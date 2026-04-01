"""Game state management for Beatify."""

from __future__ import annotations

import asyncio
import logging
import random
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
    INTRO_ROUND_CHANCE,
    MIN_PLAYERS,
    PROVIDER_DEFAULT,
    ROUND_DURATION_MAX,
    ROUND_DURATION_MIN,
    VOLUME_STEP,
)

from .challenges import (
    ArtistChallenge,
    ChallengeManager,
    MovieChallenge,
    build_artist_options,  # noqa: F401 (re-exported for backward compatibility)
    build_movie_options,  # noqa: F401 (re-exported for backward compatibility)
)
from .highlights import HighlightsTracker
from .player import PlayerSession
from .playlist import PlaylistManager
from .player_registry import PlayerRegistry
from .powerups import PowerUpManager
from .scoring import (
    ScoringService,
)
from .protocols import MediaPlayerProtocol, PartyLightsProtocol
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
        self.game_id: str | None = None
        self.admin_token: str | None = None  # Issue #386: REST admin auth
        self.phase: GamePhase = GamePhase.LOBBY
        self.playlists: list[str] = []
        self.songs: list[dict[str, Any]] = []
        self.media_player: str | None = None
        self.join_url: str | None = None
        # Issue #331: Party Lights service
        self._party_lights: PartyLightsProtocol | None = None
        self._bg_tasks: set[asyncio.Task] = set()  # Issue #391: prevent GC of fire-and-forget tasks

        # Issue #347: Player management delegated to PlayerRegistry
        self._player_registry = PlayerRegistry()

        # Backward-compatible access — other code still uses self.players directly
        # This will be tightened in future refactors

        # Round tracking (Epic 4)
        self.round: int = 0
        self.total_rounds: int = 0
        self.deadline: int | None = None
        self.current_song: dict[str, Any] | None = None
        self.last_round: bool = False

        # Pause tracking (Epic 4)
        self.pause_reason: str | None = None
        self._previous_phase: GamePhase | None = None

        # Services (Epic 4)
        self._playlist_manager: PlaylistManager | None = None
        self._media_player_service: MediaPlayerProtocol | None = None

        # Timer task for round expiry (Story 4.5)
        self._timer_task: asyncio.Task | None = None
        self._on_round_end: Callable[[], Awaitable[None]] | None = None

        # Round timing for speed bonus (Story 5.1)
        self.round_start_time: float | None = None
        self.round_duration: float = DEFAULT_ROUND_DURATION

        # Song stopped flag (Story 6.2)
        self.song_stopped: bool = False

        # Volume control (Story 6.4)
        self.volume_level: float = 0.5  # Default 50%

        # Admin disconnect tracking (Epic 7)
        self.disconnected_admin_name: str | None = None

        # Language setting (Epic 12)
        self.language: str = "en"

        # Difficulty setting (Story 14.1)
        self.difficulty: str = DIFFICULTY_DEFAULT

        # Provider setting (Story 17.2)
        self.provider: str = PROVIDER_DEFAULT

        # Platform identifier for playback routing (replaces is_mass)
        self.platform: str = "unknown"

        # Last error detail for diagnostics
        self.last_error_detail: str = ""

        # Round analytics (Story 13.3)
        self.round_analytics: RoundAnalytics | None = None

        # Stats service reference (Story 14.4)
        self._stats_service: StatsService | None = None

        # Issue #351: Power-up system (steals, bets, streak tracking)
        self._powerup_manager = PowerUpManager()

        # Story 18.9: Reaction rate limiting per reveal phase
        self._reactions_this_phase: set[str] = set()

        # Story 20.1 / Issue #28: Challenge state (artist + movie quiz)
        self._challenge_manager = ChallengeManager()

        # Issue #23: Intro mode state
        self.intro_mode_enabled: bool = False
        self.is_intro_round: bool = False  # Set per-round randomly
        self.intro_stopped: bool = False  # Track if 10s cutoff hit
        self._intro_stop_task: asyncio.Task | None = None
        self._rounds_since_intro: int = (
            0  # Track rounds without intro for guaranteed minimum
        )
        self._intro_round_start_time: float | None = (
            None  # Track round start for bonus calc
        )

        # Issue #42: Async metadata for fast transitions
        self.metadata_pending: bool = False
        self._metadata_task: asyncio.Task | None = None
        self._on_metadata_update: Callable[[dict[str, Any]], Awaitable[None]] | None = (
            None
        )

        # Story 20.9: Early reveal flag
        self._early_reveal: bool = False

        # Issue AF2-013: Lock to prevent concurrent score updates
        # Guards end_round() and _trigger_early_reveal() against race conditions
        # when multiple players submit simultaneously during early reveal check
        self._score_lock: asyncio.Lock = asyncio.Lock()

        # Issue #75: Game highlights reel
        self.highlights_tracker = HighlightsTracker()

        # Issue #292: Intro splash state
        self._intro_splash_shown: bool = False
        self._intro_splash_pending: bool = False
        self._intro_splash_deferred_song: dict | None = None
        self._intro_splash_hass: HomeAssistant | None = None

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
        self.is_intro_round = False
        self.intro_stopped = False
        self._intro_round_start_time = None
        self._rounds_since_intro = 0
        self._cancel_intro_timer()

        # Reset timer task for new game
        self.cancel_timer()

        _LOGGER.info("Game created: %s with %d songs", self.game_id, len(songs))

        return {
            "game_id": self.game_id,
            "join_url": self.join_url,
            "phase": self.phase.value,
            "song_count": len(songs),
        }

    def get_state(self) -> dict[str, Any] | None:
        """
        Get current game state for broadcast.

        Returns phase-specific data for each game phase.

        Returns:
            Game state dict or None if no active game

        """
        if not self.game_id:
            return None

        state: dict[str, Any] = {
            "game_id": self.game_id,
            "phase": self.phase.value,
            "player_count": len(self.players),
            "players": self.get_players_state(),
            "language": self.language,
            "difficulty": self.difficulty,
            # Issue #23: Intro mode (available in all phases)
            "intro_mode_enabled": self.intro_mode_enabled,
            "is_intro_round": self.is_intro_round,
            "intro_stopped": self.intro_stopped,
            "intro_splash_pending": self._intro_splash_pending,
        }

        # Phase-specific data
        if self.phase == GamePhase.LOBBY:
            state["join_url"] = self.join_url

        elif self.phase == GamePhase.PLAYING:
            state["join_url"] = self.join_url
            state["round"] = self.round
            state["total_rounds"] = self.total_rounds
            state["deadline"] = self.deadline
            state["last_round"] = self.last_round
            state["songs_remaining"] = (
                self._playlist_manager.get_remaining_count()
                if self._playlist_manager
                else 0
            )
            # Submission tracking (Story 4.4)
            state["submitted_count"] = sum(
                1 for p in self.players.values() if p.submitted
            )
            state["all_submitted"] = self.all_submitted()
            # Song info WITHOUT year during PLAYING (hidden until reveal)
            if self.current_song:
                state["song"] = {
                    "artist": self.current_song.get("artist", "Unknown"),
                    "title": self.current_song.get("title", "Unknown"),
                    "album_art": self.current_song.get(
                        "album_art", "/beatify/static/img/no-artwork.svg"
                    ),
                }
            # Leaderboard (Story 5.5)
            state["leaderboard"] = self.get_leaderboard()
            # Story 20.1: Artist challenge (hide answer during PLAYING)
            ac = self._challenge_manager.get_artist_challenge_dict(include_answer=False)
            if ac is not None:
                state["artist_challenge"] = ac
            # Issue #28: Movie quiz challenge (hide answer during PLAYING)
            mc = self._challenge_manager.get_movie_challenge_dict(include_answer=False)
            if mc is not None:
                state["movie_challenge"] = mc

        elif self.phase == GamePhase.REVEAL:
            state["join_url"] = self.join_url
            state["round"] = self.round
            state["total_rounds"] = self.total_rounds
            state["last_round"] = self.last_round
            # Filtered song info during REVEAL — exclude URIs, alt_artists, internal fields
            if self.current_song:
                state["song"] = {
                    "artist": self.current_song.get("artist", "Unknown"),
                    "title": self.current_song.get("title", "Unknown"),
                    "year": self.current_song.get("year"),
                    "album_art": self.current_song.get(
                        "album_art", "/beatify/static/img/no-artwork.svg"
                    ),
                    "fun_fact": self.current_song.get("fun_fact", ""),
                    "fun_fact_de": self.current_song.get("fun_fact_de", ""),
                    "fun_fact_es": self.current_song.get("fun_fact_es", ""),
                    "fun_fact_fr": self.current_song.get("fun_fact_fr", ""),
                    "fun_fact_nl": self.current_song.get("fun_fact_nl", ""),
                }
            # Include reveal-specific player data (guesses, round_score, missed)
            state["players"] = self.get_reveal_players_state()
            # Leaderboard (Story 5.5)
            state["leaderboard"] = self.get_leaderboard()
            # Round analytics (Story 13.3 AC4)
            if self.round_analytics:
                state["round_analytics"] = self.round_analytics.to_dict()
            # Game performance comparison (Story 14.4 AC2, AC3, AC4, AC6)
            game_performance = self.get_game_performance()
            if game_performance:
                state["game_performance"] = game_performance
            # Song difficulty rating (Story 15.1 AC1, AC4)
            if self._stats_service and self.current_song:
                song_uri = self.current_song.get("uri")
                if song_uri:
                    difficulty = self._stats_service.get_song_difficulty(song_uri)
                    if difficulty:
                        state["song_difficulty"] = difficulty
            # Story 20.1: Artist challenge (reveal answer during REVEAL)
            ac = self._challenge_manager.get_artist_challenge_dict(include_answer=True)
            if ac is not None:
                state["artist_challenge"] = ac
            # Issue #28: Movie quiz challenge (reveal answer + results during REVEAL)
            mc = self._challenge_manager.get_movie_challenge_dict(include_answer=True)
            if mc is not None:
                state["movie_challenge"] = mc
            # Story 20.9: Early reveal flag for client-side toast
            if self._early_reveal:
                state["early_reveal"] = True

        elif self.phase == GamePhase.PAUSED:
            state["pause_reason"] = self.pause_reason

        elif self.phase == GamePhase.END:
            # Final leaderboard with all player stats (Story 5.6)
            state["leaderboard"] = self.get_final_leaderboard()
            state["game_stats"] = {
                "total_rounds": self.round,
                "total_players": len(self.players),
            }
            # Include winner info
            if self.players:
                winner = max(self.players.values(), key=lambda p: p.score)
                state["winner"] = {"name": winner.name, "score": winner.score}
            # Game performance comparison for end screen (Story 14.4 AC5, AC6)
            game_performance = self.get_game_performance()
            if game_performance:
                state["game_performance"] = game_performance
            # Superlatives - fun awards (Story 15.2)
            state["superlatives"] = self.calculate_superlatives()
            # Issue #75: Game highlights reel
            state["highlights"] = self.highlights_tracker.to_dict()
            # Issue #120: Shareable result cards
            state["share_data"] = build_share_data(self)

        return state

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
        """Reset internal game state (Issue #108).

        Shared by end_game() and rematch_game() to prevent field drift.
        Does NOT reset: players, sessions, phase, game_id, callbacks,
        service refs (_stats_service, _on_round_end, _on_metadata_update),
        or volume_level (caller's responsibility).
        """
        # Cancel async tasks before resetting references
        self._cancel_intro_timer()
        if self._metadata_task and not self._metadata_task.done():
            self._metadata_task.cancel()
        self._metadata_task = None

        # Reset playlists and media
        self.playlists = []
        self.songs = []
        self.media_player = None
        self.join_url = None

        # Reset round tracking (Epic 4)
        self.round = 0
        self.total_rounds = 0
        self.deadline = None
        self.current_song = None
        self.last_round = False
        self.pause_reason = None
        self._previous_phase = None
        self._playlist_manager = None
        self._media_player_service = None

        # Reset timing (Story 5.1)
        self.round_start_time = None
        self.round_duration = DEFAULT_ROUND_DURATION

        # Reset song stopped flag (Story 6.2)
        self.song_stopped = False

        # Reset early reveal flag (Story 20.9)
        self._early_reveal = False

        # Reset round analytics (Story 13.3)
        self.round_analytics = None

        # Reset admin disconnect tracking (Epic 7)
        self.disconnected_admin_name = None

        # Reset language (Epic 12)
        self.language = "en"

        # Reset difficulty (Story 14.1)
        self.difficulty = DIFFICULTY_DEFAULT

        # Reset provider (Story 17.2)
        self.provider = PROVIDER_DEFAULT

        # Issue #23: Reset intro mode per-round state
        self.is_intro_round = False
        self.intro_stopped = False
        self._intro_round_start_time = None

        # Reset metadata state
        self.metadata_pending = False

        # Reset reaction rate-limiting (Story 18.9)
        self._reactions_this_phase = set()

        # Reset error detail
        self.last_error_detail = ""

        # Issue #351: Reset power-up state
        self._powerup_manager.reset()

        # Story 20.1 / Issue #28: Reset challenges
        self._challenge_manager.reset()

        # Issue #75: Reset highlights tracker
        self.highlights_tracker.reset()

        # Issue #292: Reset intro splash state
        self._intro_splash_shown = False
        self._intro_splash_pending = False
        self._intro_splash_deferred_song = None
        self._intro_splash_hass = None

    async def end_game(self) -> None:
        """End the current game and reset state."""
        _LOGGER.info("Game ended: %s", self.game_id)
        self.cancel_timer()
        # Issue #331: Restore lights before resetting
        await self.disable_party_lights()
        self._reset_game_internals()
        self.game_id = None
        self.phase = GamePhase.LOBBY
        self.players = {}
        self.clear_all_sessions()

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

        # Re-create PlaylistManager with fresh song list
        self._playlist_manager = PlaylistManager(preserved_songs, preserved_provider)
        self.total_rounds = len(preserved_songs)

        self.phase = GamePhase.LOBBY
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
            self._cancel_intro_timer()
            # Stop media playback
            if self._media_player_service:
                await self._media_player_service.stop()

        # Transition to PAUSED
        self.phase = GamePhase.PAUSED
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
                self._timer_task = asyncio.create_task(
                    self._timer_countdown(remaining_seconds)
                )
                _LOGGER.info("Timer restarted with %.1fs remaining", remaining_seconds)

                # Issue #416: Restart intro stop timer if this was an intro round
                if (
                    self.is_intro_round
                    and not self.intro_stopped
                    and self._intro_round_start_time is not None
                ):
                    elapsed_intro = self._now() - self._intro_round_start_time
                    remaining_intro = INTRO_DURATION_SECONDS - elapsed_intro
                    if remaining_intro > 0:
                        self._intro_stop_task = asyncio.create_task(
                            self._intro_auto_stop(remaining_intro)
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
                self.pause_reason = None
                self.disconnected_admin_name = None
                self._previous_phase = None
                await self.end_round()
                return True

        # Restore previous phase
        self.phase = previous
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
        # Round and song selection will be implemented in Epic 4
        _LOGGER.info("Game started: %d players", len(self.players))
        return True, None

    async def start_round(self, hass: HomeAssistant, _retry_count: int = 0) -> bool:
        """Start a new round with song playback (#390).

        Args:
            hass: Home Assistant instance for media player control
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
            return False

        resolved_uri = song.get("_resolved_uri")
        if not resolved_uri:
            _LOGGER.warning("Skipping song (year %s) - no URI for provider", song.get("year", "?"))
            self._playlist_manager.mark_played(song.get("uri"))
            if _retry_count >= MAX_SONG_RETRIES:
                _LOGGER.error("No playable songs found after %d attempts, pausing game", MAX_SONG_RETRIES)
                await self.pause_game("no_songs_available")
                return False
            return await self.start_round(hass, _retry_count + 1)

        self.last_round = self._playlist_manager.get_remaining_count() <= 1
        self._ensure_media_player_service(hass)
        will_defer_for_splash = self._prepare_intro_round(song, hass)

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
                return await self.start_round(hass, _retry_count + 1)

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

    def _ensure_media_player_service(self, hass: HomeAssistant) -> None:
        """Create MediaPlayerService lazily on first round."""
        # Lazy import: only the concrete class for instantiation; type hints
        # use MediaPlayerProtocol (module-level) to keep the import graph acyclic.
        from custom_components.beatify.services.media_player import (  # noqa: PLC0415
            MediaPlayerService,
        )
        if self.media_player and not self._media_player_service:
            self._media_player_service = MediaPlayerService(
                hass, self.media_player, platform=self.platform, provider=self.provider
            )
            # Connect analytics for error recording (Story 19.1 AC: #2)
            if self._stats_service and hasattr(self._stats_service, "_analytics"):
                self._media_player_service.set_analytics(self._stats_service._analytics)

    def _prepare_intro_round(self, song: dict, hass: HomeAssistant) -> bool:
        """Determine if this is an intro round and set intro state flags.

        Returns True if playback should be deferred until admin confirms splash.
        """
        self.is_intro_round = False
        self.intro_stopped = False
        self._intro_round_start_time = None
        self._cancel_intro_timer()

        if not (self.intro_mode_enabled and self.round >= 3):
            return False

        force_intro = self._rounds_since_intro >= 3
        if not (force_intro or random.random() < INTRO_ROUND_CHANCE):
            self._rounds_since_intro += 1
            return False

        song_duration_ms = song.get("duration_ms", 999999)
        if song_duration_ms < INTRO_DURATION_SECONDS * 1000:
            self._rounds_since_intro += 1
            _LOGGER.info("Skipping intro mode for short song (%dms)", song_duration_ms)
            return False

        self.is_intro_round = True
        self._rounds_since_intro = 0
        self._intro_round_start_time = self._now()

        if not self._intro_splash_shown:
            # First intro round: defer playback until admin confirms splash
            self._intro_splash_pending = True
            self._intro_splash_deferred_song = song
            self._intro_splash_hass = hass
            _LOGGER.info(
                "Intro round activated for round %d%s (splash pending, playback deferred)",
                self.round + 1, " (forced)" if force_intro else "",
            )
            return True

        _LOGGER.info("Intro round activated for round %d%s", self.round + 1, " (forced)" if force_intro else "")
        return False

    def _build_round_metadata(self, song: dict, resolved_uri: str, will_defer_for_splash: bool) -> dict:
        """Build initial metadata dict and kick off background album art fetch."""
        if self._media_player_service or will_defer_for_splash:
            # Issue #42: Start round immediately, fetch album art in background
            self.metadata_pending = True
            self._metadata_task = asyncio.create_task(self._fetch_metadata_async(resolved_uri))
            return {
                "artist": song.get("artist", "Unknown"),
                "title": song.get("title", "Unknown"),
                "album_art": "/beatify/static/img/no-artwork.svg",
            }
        # No media player — testing mode
        self.metadata_pending = False
        return {
            "artist": song.get("artist", "Test Artist"),
            "title": song.get("title", "Test Song"),
            "album_art": "/beatify/static/img/no-artwork.svg",
        }

    def _initialize_round(
        self,
        song: dict,
        metadata: dict,
        resolved_uri: str,
        will_defer_for_splash: bool,
    ) -> None:
        """Commit all round state: current song, timers, player resets, phase transition."""
        self._playlist_manager.mark_played(song.get("_resolved_uri") or song.get("uri"))

        self.current_song = {
            "year": song["year"],
            "fun_fact": song.get("fun_fact", ""),
            "fun_fact_de": song.get("fun_fact_de", ""),
            "fun_fact_es": song.get("fun_fact_es", ""),
            "fun_fact_fr": song.get("fun_fact_fr", ""),
            "fun_fact_nl": song.get("fun_fact_nl", ""),
            "uri": resolved_uri,
            "chart_info": song.get("chart_info", {}),
            "certifications": song.get("certifications", []),
            "awards": song.get("awards", []),
            "awards_de": song.get("awards_de", []),
            "awards_es": song.get("awards_es", []),
            "awards_fr": song.get("awards_fr", []),
            "awards_nl": song.get("awards_nl", []),
            **metadata,
        }

        self._challenge_manager.init_round(song)

        # Issue #424: Cancel old timers before creating new ones
        self.cancel_timer()
        self._cancel_intro_timer()

        if self.is_intro_round and not will_defer_for_splash:
            self._intro_stop_task = asyncio.create_task(self._intro_auto_stop(INTRO_DURATION_SECONDS))

        self.round += 1
        self.total_rounds = self._playlist_manager.get_total_count()

        self.round_start_time = self._now()
        effective_duration = INTRO_DURATION_SECONDS if self.is_intro_round else self.round_duration
        self.deadline = int((self.round_start_time + effective_duration) * 1000)

        for player in self.players.values():
            player.reset_round()

        self.song_stopped = False
        self._early_reveal = False
        self.round_analytics = None

        delay_seconds = (self.deadline - int(self._now() * 1000)) / 1000.0
        self._timer_task = asyncio.create_task(self._timer_countdown(delay_seconds))
        self.phase = GamePhase.PLAYING

    async def _timer_countdown(self, delay_seconds: float) -> None:
        """
        Wait for round to end, then trigger reveal.

        This task may be cancelled by:
        - Admin advancing to next round early
        - All players submitting (if auto_advance enabled)
        - Game pause/end

        Always handle CancelledError gracefully.

        Args:
            delay_seconds: Seconds to wait before triggering reveal

        """
        try:
            if delay_seconds < 0:
                _LOGGER.warning(
                    "Round timer delay already negative (%.1fs), ending immediately",
                    delay_seconds,
                )
                delay_seconds = 0
            await asyncio.sleep(delay_seconds)
            # Check we're still in PLAYING phase (could have changed)
            if self.phase == GamePhase.PLAYING:
                _LOGGER.info("Round timer expired, transitioning to REVEAL")
                await self.end_round()
            else:
                _LOGGER.debug(
                    "Timer expired but phase already changed to %s", self.phase
                )
        except asyncio.CancelledError:
            _LOGGER.debug("Timer task cancelled")
            # Re-raise to properly complete cancellation
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
        self._cancel_intro_timer()

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

        # Issue #331: Update Party Lights for reveal phase + flash on exact matches
        await self._lights_set_phase(GamePhase.REVEAL)
        if correct_year is not None:
            for p in self.players.values():
                if p.submitted and p.years_off == 0:
                    await self._lights_flash("gold")
                    break  # One flash per round is enough

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

            # Streak milestones (3, 5, 7+)
            if player.streak in (3, 5, 7):
                self.highlights_tracker.record_streak(
                    player.name, player.streak, self.round
                )

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
        """Cancel the round timer (synchronous, for cleanup)."""
        if self._timer_task and not self._timer_task.done():
            # Don't cancel if we're being called from within the timer task itself
            # (happens when timer naturally expires and calls end_round)
            current_task = asyncio.current_task()
            if current_task != self._timer_task:
                self._timer_task.cancel()
        self._timer_task = None

    async def confirm_intro_splash(self) -> None:
        """Handle admin confirmation of intro splash (Issue #292, #403).

        Encapsulates all intro-splash state mutations so the websocket
        handler does not need to touch private attributes directly.
        """
        if not self._intro_splash_pending:
            return
        self._intro_splash_pending = False
        self._intro_splash_shown = True

        # Play the deferred song now that admin has confirmed
        deferred_song = self._intro_splash_deferred_song
        if deferred_song:
            success = await self.play_deferred_song(deferred_song)
            if not success:
                _LOGGER.warning(
                    "Failed to play deferred intro song: %s",
                    deferred_song.get("uri"),
                )
            self._intro_splash_deferred_song = None
            self._intro_splash_hass = None

        # Reset round timing to start from NOW (after admin confirmation)
        self.round_start_time = self._now()
        self._intro_round_start_time = self._now()

        effective_duration = INTRO_DURATION_SECONDS
        self.deadline = int(
            (self.round_start_time + effective_duration) * 1000
        )

        self._intro_stop_task = asyncio.create_task(
            self._intro_auto_stop(INTRO_DURATION_SECONDS)
        )

    def _cancel_intro_timer(self) -> None:
        """Cancel the intro auto-stop timer if running (Issue #23)."""
        if self._intro_stop_task and not self._intro_stop_task.done():
            self._intro_stop_task.cancel()
        self._intro_stop_task = None

    async def _intro_auto_stop(self, delay_seconds: float) -> None:
        """Signal end of intro challenge window after delay (Issue #23).

        Music intentionally continues playing — players hear the rest of the
        song after the intro window closes.  Only the UI state changes
        (intro_stopped = True) so clients show the "Intro complete!" badge.
        """
        try:
            await asyncio.sleep(delay_seconds)
            if self.phase == GamePhase.PLAYING and not self.intro_stopped:
                self.intro_stopped = True
                _LOGGER.info(
                    "Intro challenge window closed after %.1fs (music continues)",
                    delay_seconds,
                )
                # Broadcast updated state so clients update the intro badge
                if self._on_round_end:
                    await self._on_round_end()
        except asyncio.CancelledError:
            _LOGGER.debug("Intro stop task cancelled")
            raise

    def is_deadline_passed(self) -> bool:
        """
        Check if the round deadline has passed.

        Uses the injected time function for testability.

        Returns:
            True if deadline has passed, False otherwise.

        """
        if self.deadline is None:
            return False
        now_ms = int(self._now() * 1000)
        return now_ms > self.deadline

    def get_reveal_players_state(self) -> list[dict[str, Any]]:
        """
        Get player state with reveal info for REVEAL phase.

        Returns:
            List of player dicts including guess, round_score, years_off,
            speed bonus data (Story 5.1), streak bonus (Story 5.2),
            and artist bonus (Story 20.4), sorted by total score descending.

        """
        players = []
        for p in self.players.values():
            player_data = {
                "name": p.name,
                "score": p.score,
                "streak": p.streak,
                "is_admin": p.is_admin,
                "connected": p.connected,
                "guess": p.current_guess,
                "round_score": p.round_score,
                "years_off": p.years_off,
                "missed_round": p.missed_round,
                # Speed bonus data (Story 5.1)
                "base_score": p.base_score,
                "speed_multiplier": round(p.speed_multiplier, 2),
                # Streak bonus data (Story 5.2)
                "streak_bonus": p.streak_bonus,
                # Bet data (Story 5.3)
                "bet": p.bet,
                "bet_outcome": p.bet_outcome,
                # Missed round data (Story 5.4)
                "previous_streak": p.previous_streak,
                # Steal data (Story 15.3 AC4)
                "stole_from": p.stole_from,
                "was_stolen_by": p.was_stolen_by.copy() if p.was_stolen_by else [],
                "steal_available": p.steal_available,
            }
            # Story 20.4: Add artist bonus if challenge is enabled
            if self.artist_challenge_enabled:
                player_data["artist_bonus"] = p.artist_bonus
            # Issue #28: Add movie bonus if quiz is enabled
            if self.movie_quiz_enabled:
                player_data["movie_bonus"] = p.movie_bonus
            # Issue #23: Add intro bonus if mode is enabled
            if self.intro_mode_enabled:
                player_data["intro_bonus"] = p.intro_bonus
            players.append(player_data)
        # Sort by score descending for leaderboard preview
        players.sort(key=lambda p: p["score"], reverse=True)
        return players

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
        self._cancel_intro_timer()
        self.phase = GamePhase.END

        # Issue #331: Celebrate with Party Lights
        await self._lights_celebrate()

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
        self, hass: Any, entity_ids: list[str], intensity: str = "medium"
    ) -> None:
        """Configure and start Party Lights for the game."""
        # Lazy import: only the concrete class for instantiation; type hints
        # use PartyLightsProtocol (module-level) to keep the import graph acyclic.
        from custom_components.beatify.services.lights import PartyLightsService  # noqa: PLC0415

        self._party_lights = PartyLightsService(hass)
        await self._party_lights.start(entity_ids, intensity)

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

    async def _lights_celebrate(self) -> None:
        """Run Party Lights celebration (fire-and-forget)."""
        if self._party_lights:
            try:
                task = asyncio.create_task(self._party_lights.celebrate())
                self._bg_tasks.add(task)
                task.add_done_callback(self._bg_tasks.discard)
            except Exception:  # noqa: BLE001
                _LOGGER.warning("Party Lights celebration failed")

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
