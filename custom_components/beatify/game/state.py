"""Game state management for Beatify."""

from __future__ import annotations

import asyncio
import logging
import random
import secrets
import time
from dataclasses import dataclass, field
from enum import Enum
from statistics import mean, median
from typing import TYPE_CHECKING, Any

from custom_components.beatify.const import (
    ARTIST_BONUS_POINTS,
    DEFAULT_ROUND_DURATION,
    DIFFICULTY_DEFAULT,
    ERR_CANNOT_STEAL_SELF,
    ERR_GAME_ALREADY_STARTED,
    ERR_GAME_ENDED,
    ERR_GAME_FULL,
    ERR_GAME_NOT_STARTED,
    ERR_INVALID_ACTION,
    ERR_NAME_INVALID,
    ERR_NAME_TAKEN,
    ERR_NO_STEAL_AVAILABLE,
    ERR_NOT_IN_GAME,
    ERR_TARGET_NOT_SUBMITTED,
    MAX_NAME_LENGTH,
    MAX_PLAYERS,
    MAX_SUPERLATIVES,
    MIN_BETS_FOR_AWARD,
    MIN_CLOSE_CALLS,
    MIN_MOVIE_WINS_FOR_AWARD,
    MIN_NAME_LENGTH,
    MIN_ROUNDS_FOR_CLUTCH,
    MIN_STREAK_FOR_AWARD,
    MOVIE_BONUS_TIERS,
    PROVIDER_DEFAULT,
    ROUND_DURATION_MAX,
    ROUND_DURATION_MIN,
    STEAL_UNLOCK_STREAK,
)

from .player import PlayerSession
from .playlist import PlaylistManager
from .scoring import (
    apply_bet_multiplier,
    calculate_round_score,
    calculate_streak_bonus,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from aiohttp import web
    from homeassistant.core import HomeAssistant

    from custom_components.beatify.services.media_player import MediaPlayerService
    from custom_components.beatify.services.stats import StatsService

_LOGGER = logging.getLogger(__name__)


class GamePhase(Enum):
    """Game phase states."""

    LOBBY = "LOBBY"
    PLAYING = "PLAYING"
    REVEAL = "REVEAL"
    END = "END"
    PAUSED = "PAUSED"


@dataclass
class RoundAnalytics:
    """Analytics calculated at end of each round for reveal display (Story 13.3)."""

    # Guesses data (AC1)
    all_guesses: list[dict[str, Any]] = field(default_factory=list)
    average_guess: float | None = None
    median_guess: int | None = None

    # Performance metrics (AC2, AC3)
    closest_players: list[str] = field(default_factory=list)
    furthest_players: list[str] = field(default_factory=list)
    exact_match_players: list[str] = field(default_factory=list)
    exact_match_count: int = 0
    scored_count: int = 0
    total_submitted: int = 0
    accuracy_percentage: int = 0

    # Speed champion (AC3)
    speed_champion: dict[str, Any] | None = None

    # Histogram data (AC5, AC6)
    decade_distribution: dict[str, int] = field(default_factory=dict)
    correct_decade: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        avg = round(self.average_guess, 1) if self.average_guess else None
        return {
            "all_guesses": self.all_guesses,
            "average_guess": avg,
            "median_guess": self.median_guess,
            "closest_players": self.closest_players,
            "furthest_players": self.furthest_players,
            "exact_match_players": self.exact_match_players,
            "exact_match_count": self.exact_match_count,
            "scored_count": self.scored_count,
            "total_submitted": self.total_submitted,
            "accuracy_percentage": self.accuracy_percentage,
            "speed_champion": self.speed_champion,
            "decade_distribution": self.decade_distribution,
            "correct_decade": self.correct_decade,
        }


@dataclass
class ArtistChallenge:
    """Artist challenge state for bonus points feature (Epic 20)."""

    correct_artist: str
    options: list[str]  # Shuffled: correct + decoys
    winner: str | None = None
    winner_time: float | None = None

    def to_dict(self, include_answer: bool = False) -> dict[str, Any]:
        """
        Convert to JSON-serializable dictionary.

        Args:
            include_answer: If True, include correct_artist (for REVEAL phase).
                           If False, hide answer (for PLAYING phase).

        """
        result: dict[str, Any] = {
            "options": self.options,
            "winner": self.winner,
        }
        if self.winner_time is not None:
            result["winner_time"] = self.winner_time
        if include_answer:
            result["correct_artist"] = self.correct_artist
        return result


@dataclass
class MovieChallenge:
    """Movie quiz challenge state for bonus points feature (Issue #28)."""

    correct_movie: str
    options: list[str]  # Shuffled: 3 movie choices (correct + 2 decoys)
    correct_guesses: list[dict[str, Any]] = field(default_factory=list)  # [{name, time}]
    wrong_guesses: list[dict[str, Any]] = field(default_factory=list)  # [{name, guess}]

    def to_dict(self, include_answer: bool = False) -> dict[str, Any]:
        """
        Convert to JSON-serializable dictionary.

        Args:
            include_answer: If True, include correct_movie and results (for REVEAL).
                           If False, only show options (for PLAYING).

        """
        result: dict[str, Any] = {
            "options": self.options,
        }
        if include_answer:
            result["correct_movie"] = self.correct_movie
            result["results"] = self._build_results()
        return result

    def _build_results(self) -> dict[str, Any]:
        """Build movie quiz results for reveal display."""
        winners = []
        for i, guess in enumerate(self.correct_guesses):
            bonus = MOVIE_BONUS_TIERS[i] if i < len(MOVIE_BONUS_TIERS) else 0
            winners.append(
                {
                    "name": guess["name"],
                    "time": round(guess["time"], 2),
                    "bonus": bonus,
                }
            )
        return {
            "winners": winners,
            "wrong_guesses": [{"name": g["name"], "guess": g["guess"]} for g in self.wrong_guesses],
        }

    def get_player_bonus(self, player_name: str) -> int:
        """
        Get the bonus points for a specific player.

        Args:
            player_name: Name of the player

        Returns:
            Bonus points (5/3/1/0 based on speed rank)

        """
        for i, guess in enumerate(self.correct_guesses):
            if guess["name"] == player_name:
                return MOVIE_BONUS_TIERS[i] if i < len(MOVIE_BONUS_TIERS) else 0
        return 0


def build_movie_options(song: dict[str, Any]) -> list[str] | None:
    """
    Build shuffled movie options from song data (Issue #28).

    Args:
        song: Song dictionary with 'movie' and 'movie_choices'

    Returns:
        Shuffled list of movie options, or None if insufficient data

    """
    movie = song.get("movie", "")
    if isinstance(movie, str):
        movie = movie.strip()
    else:
        movie = ""

    movie_choices = song.get("movie_choices", [])

    # Validate required data
    if not movie:
        return None

    if not movie_choices or not isinstance(movie_choices, list):
        return None

    # Filter valid choices
    valid_choices = [c.strip() for c in movie_choices if isinstance(c, str) and c.strip()]

    if len(valid_choices) < 2:
        return None

    # Ensure correct movie is in the list
    if movie not in valid_choices:
        valid_choices = [movie] + valid_choices[:2]

    # Shuffle and return
    options = list(valid_choices)
    random.shuffle(options)

    return options


def build_artist_options(song: dict[str, Any]) -> list[str] | None:
    """
    Build shuffled artist options from song data (Story 20.2).

    Args:
        song: Song dictionary with 'artist' and optional 'alt_artists'

    Returns:
        Shuffled list of artist options, or None if insufficient data

    """
    artist = song.get("artist", "")
    if isinstance(artist, str):
        artist = artist.strip()
    else:
        artist = ""

    alt_artists = song.get("alt_artists", [])

    # Validate required data
    if not artist:
        return None

    if not alt_artists or not isinstance(alt_artists, list):
        return None

    # Filter valid alternatives
    valid_alts = [a.strip() for a in alt_artists if isinstance(a, str) and a.strip()]

    if not valid_alts:
        return None

    # Build and shuffle options
    options = [artist] + valid_alts
    random.shuffle(options)

    return options


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
        self.phase: GamePhase = GamePhase.LOBBY
        self.playlists: list[str] = []
        self.songs: list[dict[str, Any]] = []
        self.media_player: str | None = None
        self.join_url: str | None = None
        self.players: dict[str, PlayerSession] = {}
        self._sessions: dict[str, str] = {}  # session_id → player_name

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
        self._media_player_service: MediaPlayerService | None = None

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

        # Story 19.11: Streak achievement tracking for analytics
        self.streak_achievements: dict[str, int] = {
            "streak_3": 0,  # Count of 3+ streaks
            "streak_5": 0,  # Count of 5+ streaks
            "streak_7": 0,  # Count of 7+ streaks
        }

        # Story 19.12: Bet outcome tracking for analytics
        self.bet_tracking: dict[str, int] = {
            "total_bets": 0,  # Total bets placed in game
            "bets_won": 0,  # Bets that won
        }

        # Story 18.9: Reaction rate limiting per reveal phase
        self._reactions_this_phase: set[str] = set()

        # Story 20.1: Artist challenge state
        self.artist_challenge: ArtistChallenge | None = None
        self.artist_challenge_enabled: bool = False

        # Issue #28: Movie quiz challenge state
        self.movie_challenge: MovieChallenge | None = None
        self.movie_quiz_enabled: bool = False

        # Issue #42: Async metadata for fast transitions
        self.metadata_pending: bool = False
        self._metadata_task: asyncio.Task | None = None
        self._on_metadata_update: Callable[[dict[str, Any]], Awaitable[None]] | None = None

        # Story 20.9: Early reveal flag
        self._early_reveal: bool = False

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

        # Story 19.11: Reset streak tracking for new game
        self.streak_achievements = {"streak_3": 0, "streak_5": 0, "streak_7": 0}

        # Story 19.12: Reset bet tracking for new game
        self.bet_tracking = {"total_bets": 0, "bets_won": 0}

        # Story 20.1: Set artist challenge configuration
        self.artist_challenge_enabled = artist_challenge_enabled
        self.artist_challenge = None

        # Issue #28: Set movie quiz configuration
        self.movie_quiz_enabled = movie_quiz_enabled
        self.movie_challenge = None

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
                self._playlist_manager.get_remaining_count() if self._playlist_manager else 0
            )
            # Submission tracking (Story 4.4)
            state["submitted_count"] = sum(1 for p in self.players.values() if p.submitted)
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
            if self.artist_challenge_enabled and self.artist_challenge:
                state["artist_challenge"] = self.artist_challenge.to_dict(include_answer=False)
            # Issue #28: Movie quiz challenge (hide answer during PLAYING)
            if self.movie_quiz_enabled and self.movie_challenge:
                state["movie_challenge"] = self.movie_challenge.to_dict(include_answer=False)

        elif self.phase == GamePhase.REVEAL:
            state["join_url"] = self.join_url
            state["round"] = self.round
            state["total_rounds"] = self.total_rounds
            state["last_round"] = self.last_round
            # Full song info INCLUDING year and fun_fact during REVEAL
            if self.current_song:
                state["song"] = self.current_song
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
            if self.artist_challenge_enabled and self.artist_challenge:
                state["artist_challenge"] = self.artist_challenge.to_dict(include_answer=True)
            # Issue #28: Movie quiz challenge (reveal answer + results during REVEAL)
            if self.movie_quiz_enabled and self.movie_challenge:
                state["movie_challenge"] = self.movie_challenge.to_dict(include_answer=True)
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
            "streak_7_count": self.streak_achievements.get("streak_7", 0),
            # Story 19.12: Include bet tracking
            "total_bets": self.bet_tracking.get("total_bets", 0),
            "bets_won": self.bet_tracking.get("bets_won", 0),
        }

    def end_game(self) -> None:
        """End the current game and reset state."""
        _LOGGER.info("Game ended: %s", self.game_id)
        # Cancel any running timer
        self.cancel_timer()
        self.game_id = None
        self.phase = GamePhase.LOBBY
        self.playlists = []
        self.songs = []
        self.media_player = None
        self.join_url = None
        self.players = {}
        # Clear all session mappings (Story 11.6)
        self.clear_all_sessions()

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

        # Story 19.11: Reset streak tracking
        self.streak_achievements = {"streak_3": 0, "streak_5": 0, "streak_7": 0}

        # Story 19.12: Reset bet tracking
        self.bet_tracking = {"total_bets": 0, "bets_won": 0}

        # Story 20.1: Reset artist challenge
        self.artist_challenge = None
        self.artist_challenge_enabled = True  # Reset to default (Story 20.7)

        # Issue #28: Reset movie quiz challenge
        self.movie_challenge = None
        self.movie_quiz_enabled = True  # Reset to default

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
                self._timer_task = asyncio.create_task(self._timer_countdown(remaining_seconds))
                _LOGGER.info("Timer restarted with %.1fs remaining", remaining_seconds)

                # Resume media playback if it was stopped
                if self._media_player_service and self.current_song:
                    await self._media_player_service.play(self.current_song)
                    _LOGGER.info("Media playback resumed")
            else:
                # Timer would have expired during pause
                _LOGGER.info("Timer expired during pause, will advance to reveal")

        # Restore previous phase
        self.phase = previous
        self.pause_reason = None
        self.disconnected_admin_name = None
        self._previous_phase = None

        _LOGGER.info("Game resumed to phase: %s", previous.value)

        return True

    def get_average_score(self) -> int:
        """
        Calculate average score of all current players.

        Used for late joiners (Story 10.2) to start with a fair score.

        Returns:
            Average score rounded to nearest integer, or 0 if no players

        """
        if not self.players:
            return 0
        total = sum(p.score for p in self.players.values())
        return round(total / len(self.players))

    def add_player(self, name: str, ws: web.WebSocketResponse) -> tuple[bool, str | None]:
        """
        Add a player to the game.

        Allows joining during LOBBY, PLAYING, or REVEAL phases.
        Rejects during END phase.

        Args:
            name: Player display name (trimmed, max 20 chars)
            ws: WebSocket connection

        Returns:
            (success, error_code) - error_code is None on success

        """
        # Validate name
        name = name.strip()
        if not name or len(name) < MIN_NAME_LENGTH:
            return False, ERR_NAME_INVALID
        if len(name) > MAX_NAME_LENGTH:
            return False, ERR_NAME_INVALID

        # Check phase - reject END state (PAUSED is OK for reconnection)
        if self.phase == GamePhase.END:
            return False, ERR_GAME_ENDED

        # Check for reconnection (Story 7-2, 7-3) - case-insensitive match
        # Allowed during PAUSED phase for reconnection
        for existing_name, existing_player in self.players.items():
            if existing_name.lower() == name.lower():
                # Name exists - check if it's a reconnection (player disconnected)
                if not existing_player.connected:
                    # Reconnection: update WebSocket and mark connected
                    existing_player.ws = ws
                    existing_player.connected = True
                    _LOGGER.info("Player reconnected: %s", existing_name)
                    return True, None
                # Player still connected, reject duplicate
                return False, ERR_NAME_TAKEN

        # Check player limit
        if len(self.players) >= MAX_PLAYERS:
            return False, ERR_GAME_FULL

        # Determine if late joiner
        joined_late = self.phase != GamePhase.LOBBY

        # Calculate initial score (Story 10.2: late joiners get average)
        initial_score = self.get_average_score() if joined_late else 0

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
        """
        Get player by name.

        Args:
            name: Player name

        Returns:
            PlayerSession or None if not found

        """
        return self.players.get(name)

    def get_player_by_session_id(self, session_id: str) -> PlayerSession | None:
        """
        Get player by session ID (Story 11.1).

        Args:
            session_id: Session ID from cookie

        Returns:
            PlayerSession or None if not found

        """
        name = self._sessions.get(session_id)
        return self.players.get(name) if name else None

    def get_player_by_ws(self, ws: web.WebSocketResponse) -> PlayerSession | None:
        """
        Get player by WebSocket connection (Story 18.9).

        Args:
            ws: WebSocket connection

        Returns:
            PlayerSession or None if not found

        """
        for player in self.players.values():
            if player.ws == ws:
                return player
        return None

    def record_reaction(self, player_name: str, emoji: str) -> bool:
        """
        Record a player reaction (Story 18.9).

        Rate limited to 1 reaction per player per reveal phase.

        Args:
            player_name: Name of the player
            emoji: The emoji reaction

        Returns:
            True if reaction was recorded, False if rate limited

        """
        if player_name in self._reactions_this_phase:
            return False
        self._reactions_this_phase.add(player_name)
        return True

    def get_steal_targets(self, stealer_name: str) -> list[str]:
        """
        Get list of players who have submitted and can be stolen from (Story 15.3).

        Args:
            stealer_name: Name of the player attempting to steal

        Returns:
            List of player names who have submitted this round, excluding self

        """
        targets = []
        for name, player in self.players.items():
            if name != stealer_name and player.submitted:
                targets.append(name)
        return targets

    def use_steal(self, stealer_name: str, target_name: str) -> dict[str, Any]:
        """
        Execute steal: copy target's guess to stealer (Story 15.3).

        Args:
            stealer_name: Name of the player using steal
            target_name: Name of the player to copy from

        Returns:
            dict with success status, or error code on failure

        """
        stealer = self.players.get(stealer_name)
        target = self.players.get(target_name)

        # Validations
        if not stealer:
            return {"success": False, "error": ERR_NOT_IN_GAME}

        if not stealer.steal_available:
            return {"success": False, "error": ERR_NO_STEAL_AVAILABLE}

        if self.phase != GamePhase.PLAYING:
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
        stealer.submission_time = self._now()

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

    def remove_player(self, name: str) -> None:
        """
        Remove player from game.

        Args:
            name: Player name to remove

        """
        if name in self.players:
            player = self.players[name]
            # Clean up session mapping (Story 11.1)
            self._sessions.pop(player.session_id, None)
            del self.players[name]
            _LOGGER.info("Player removed: %s", name)

    def clear_all_sessions(self) -> None:
        """
        Clear all session mappings for game reset (Story 11.6).

        Called after broadcasting final state to ensure players receive
        END state before sessions are invalidated.

        """
        session_count = len(self._sessions)
        self._sessions.clear()
        _LOGGER.info("Cleared %d player sessions", session_count)

    def get_players_state(self) -> list[dict[str, Any]]:
        """
        Get player list for state broadcast.

        Returns:
            List of player dicts with name, score, connected, streak, is_admin,
            submitted

        """
        return [
            {
                "name": p.name,
                "score": p.score,
                "connected": p.connected,
                "streak": p.streak,
                "is_admin": p.is_admin,
                "submitted": p.submitted,
                # Steal availability (Story 15.3 AC1)
                "steal_available": p.steal_available,
                # Bet and steal status for submission tracker badges
                "bet": p.bet,
                "steal_used": p.steal_used,
            }
            for p in self.players.values()
        ]

    def all_submitted(self) -> bool:
        """
        Check if all connected players have submitted their guess.

        Returns:
            True if all connected players have submitted, False otherwise

        """
        connected_players = [p for p in self.players.values() if p.connected]
        if not connected_players:
            return False
        return all(p.submitted for p in connected_players)

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

        # If artist challenge enabled and active, also check artist guesses
        if self.artist_challenge_enabled and self.artist_challenge:
            for player in self.players.values():
                if player.connected and not player.has_artist_guess:
                    return False

        # Issue #28: If movie quiz enabled and active, also check movie guesses
        if self.movie_quiz_enabled and self.movie_challenge:
            for player in self.players.values():
                if player.connected and not player.has_movie_guess:
                    return False

        return True

    async def _trigger_early_reveal(self) -> None:
        """
        Trigger early transition to reveal when all guesses are in (Story 20.9).

        Cancels timer, sets early_reveal flag, and calls end_round.

        """
        _LOGGER.info(
            "All guesses complete - triggering early reveal (phase=%s, callback=%s)",
            self.phase.value,
            self._on_round_end is not None,
        )
        self.cancel_timer()
        self._early_reveal = True
        await self.end_round()
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
        """
        Mark a player as the admin.

        Args:
            name: Player name to mark as admin

        Returns:
            True if successful, False if player not found

        """
        if name not in self.players:
            return False
        self.players[name].is_admin = True
        _LOGGER.info("Player set as admin: %s", name)
        return True

    def start_game(self) -> tuple[bool, str | None]:
        """
        Start the game, transitioning from LOBBY to PLAYING.

        Returns:
            (success, error_code) - error_code is None on success

        """
        if self.phase != GamePhase.LOBBY:
            return False, ERR_GAME_ALREADY_STARTED

        if len(self.players) == 0:
            return False, ERR_GAME_NOT_STARTED  # No players to play with

        self.phase = GamePhase.PLAYING
        # Round and song selection will be implemented in Epic 4
        _LOGGER.info("Game started: %d players", len(self.players))
        return True, None

    async def start_round(self, hass: HomeAssistant, _retry_count: int = 0) -> bool:
        """
        Start a new round with song playback.

        Args:
            hass: Home Assistant instance for media player control
            _retry_count: Internal counter for failed song attempts (max 3)

        Returns:
            True if round started successfully, False otherwise

        """
        # Import here to avoid circular imports
        from custom_components.beatify.services.media_player import (  # noqa: PLC0415
            MediaPlayerService,
        )

        # Maximum retries to prevent runaway loop when media player is down
        MAX_SONG_RETRIES = 3

        if not self._playlist_manager:
            _LOGGER.error("No playlist manager configured")
            return False

        # Get next song
        song = self._playlist_manager.get_next_song()
        if not song:
            _LOGGER.info("All songs exhausted, ending game")
            self.phase = GamePhase.END
            return False

        # Story 17.3: Check for resolved URI, skip songs without URI for selected provider
        resolved_uri = song.get("_resolved_uri")
        if not resolved_uri:
            _LOGGER.warning(
                "Skipping song (year %s) - no URI for provider",
                song.get("year", "?"),
            )
            self._playlist_manager.mark_played(song.get("uri"))

            # Check retry limit to prevent infinite loop when no songs have URIs
            if _retry_count >= MAX_SONG_RETRIES:
                _LOGGER.error(
                    "No playable songs found after %d attempts, pausing game",
                    MAX_SONG_RETRIES,
                )
                await self.pause_game("no_songs_available")
                return False

            # Try next song with incremented retry count
            return await self.start_round(hass, _retry_count + 1)

        # Check if this is the last round (1 song remaining after this one)
        self.last_round = self._playlist_manager.get_remaining_count() <= 1

        # Create media player service if needed
        if self.media_player and not self._media_player_service:
            self._media_player_service = MediaPlayerService(
                hass,
                self.media_player,
                platform=self.platform,
                provider=self.provider,
            )
            # Connect analytics for error recording (Story 19.1 AC: #2)
            if self._stats_service and hasattr(self._stats_service, "_analytics"):
                self._media_player_service.set_analytics(self._stats_service._analytics)

        # Play song via media player
        if self._media_player_service:
            # Pre-flight check: verify speaker is responsive before playing
            # Skip for MA players since they use music_assistant.play_media service
            # which handles speaker state differently
            if self.platform != "music_assistant":
                (
                    responsive,
                    error_detail,
                ) = await self._media_player_service.verify_responsive()
                if not responsive:
                    self.last_error_detail = error_detail
                    _LOGGER.error(
                        "Media player not responsive: %s, pausing game",
                        error_detail,
                    )
                    await self.pause_game("media_player_error")
                    return False

            # Pass entire song dict for platform-specific playback routing
            success = await self._media_player_service.play_song(song)
            if not success:
                _LOGGER.warning(
                    "Failed to play song: %s", song.get("uri")
                )  # Log original for debug
                self._playlist_manager.mark_played(song.get("_resolved_uri") or song.get("uri"))

                # Check retry limit to prevent runaway loop
                if _retry_count >= MAX_SONG_RETRIES:
                    _LOGGER.error(
                        "Media player unreachable after %d attempts, pausing game",
                        MAX_SONG_RETRIES,
                    )
                    await self.pause_game("media_player_error")
                    return False

                # Brief delay before retry to allow media player recovery
                await asyncio.sleep(1.0)

                # Try next song with incremented retry count
                return await self.start_round(hass, _retry_count + 1)

            # Issue #42: Start round immediately, fetch album art in background
            # Fix #124: Use playlist artist/title as source of truth (never async)
            self.metadata_pending = True
            metadata = {
                "artist": song.get("artist", "Unknown"),  # From playlist (reliable)
                "title": song.get("title", "Unknown"),  # From playlist (reliable)
                "album_art": "/beatify/static/img/no-artwork.svg",  # Async fill
            }
            # Start background task to fetch album art only
            self._metadata_task = asyncio.create_task(self._fetch_metadata_async(resolved_uri))
        else:
            # No media player (testing mode)
            self.metadata_pending = False
            metadata = {
                "artist": song.get("artist", "Test Artist"),
                "title": song.get("title", "Test Song"),
                "album_art": "/beatify/static/img/no-artwork.svg",
            }

        # Mark song as played (Story 17.3: use resolved URI)
        self._playlist_manager.mark_played(song.get("_resolved_uri") or song.get("uri"))

        # Set current song (year and fun_fact from playlist, rest from metadata)
        # Story 14.3: Include rich song info fields from enriched playlists
        # Story 16.3: Include localized fun_fact and awards for i18n
        self.current_song = {
            "year": song["year"],
            "fun_fact": song.get("fun_fact", ""),
            "fun_fact_de": song.get("fun_fact_de", ""),
            "fun_fact_es": song.get("fun_fact_es", ""),
            "uri": song.get("_resolved_uri") or song.get("uri"),  # Story 17.3
            "chart_info": song.get("chart_info", {}),
            "certifications": song.get("certifications", []),
            "awards": song.get("awards", []),
            "awards_de": song.get("awards_de", []),
            "awards_es": song.get("awards_es", []),
            **metadata,
        }

        # Story 20.1: Initialize artist challenge for this round
        self.artist_challenge = self._init_artist_challenge(song)

        # Issue #28: Initialize movie quiz challenge for this round
        self.movie_challenge = self._init_movie_challenge(song)

        # Update round tracking
        self.round += 1
        self.total_rounds = self._playlist_manager.get_total_count()

        # Record round start time for speed bonus calculation (Story 5.1)
        # Note: self.round_duration is set in create_game() (Story 13.1)
        self.round_start_time = self._now()
        self.deadline = int((self.round_start_time + self.round_duration) * 1000)

        # Reset player submissions for new round
        for player in self.players.values():
            player.reset_round()

        # Reset song stopped flag for new round (Story 6.2)
        self.song_stopped = False

        # Reset early reveal flag for new round (Story 20.9)
        self._early_reveal = False

        # Reset round analytics for new round (Story 13.3)
        self.round_analytics = None

        # Cancel any existing timer
        self.cancel_timer()

        # Calculate delay until deadline
        now_ms = int(self._now() * 1000)
        delay_seconds = (self.deadline - now_ms) / 1000.0

        # Start timer task for round expiry
        self._timer_task = asyncio.create_task(self._timer_countdown(delay_seconds))

        # Transition to PLAYING
        self.phase = GamePhase.PLAYING
        _LOGGER.info(
            "Round %d started: %s - %s (%.1fs timer)",
            self.round,
            self.current_song.get("artist"),
            self.current_song.get("title"),
            delay_seconds,
        )
        return True

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
            await asyncio.sleep(delay_seconds)
            # Check we're still in PLAYING phase (could have changed)
            if self.phase == GamePhase.PLAYING:
                _LOGGER.info("Round timer expired, transitioning to REVEAL")
                await self.end_round()
            else:
                _LOGGER.debug("Timer expired but phase already changed to %s", self.phase)
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

        """
        # Cancel timer if still running
        self.cancel_timer()

        # Store current ranks before scoring for rank change detection (5.5)
        self._store_previous_ranks()

        # Get correct year from current song
        correct_year = self.current_song.get("year") if self.current_song else None

        # Calculate scores for all players
        for player in self.players.values():
            if player.submitted and correct_year is not None:
                # Calculate elapsed time for speed bonus (Story 5.1)
                if player.submission_time is not None and self.round_start_time is not None:
                    elapsed = player.submission_time - self.round_start_time
                else:
                    elapsed = self.round_duration  # No bonus if timing unavailable

                # Calculate score with speed bonus
                speed_score, player.base_score, player.speed_multiplier = calculate_round_score(
                    player.current_guess,
                    correct_year,
                    elapsed,
                    self.round_duration,
                    self.difficulty,
                )
                player.years_off = abs(player.current_guess - correct_year)
                player.missed_round = False

                # Apply bet multiplier (Story 5.3)
                player.round_score, player.bet_outcome = apply_bet_multiplier(
                    speed_score, player.bet
                )

                # Update streak - any points continues streak (Story 5.2)
                # Note: streak based on speed_score, not bet-adjusted score
                if speed_score > 0:
                    player.previous_streak = 0  # Not relevant when scoring
                    player.streak += 1

                    # Story 19.11: Record streak achievements at milestones
                    # Only count each milestone once (when first reached at exact value)
                    if player.streak == 3:
                        self.streak_achievements["streak_3"] += 1
                    elif player.streak == 5:
                        self.streak_achievements["streak_5"] += 1
                    elif player.streak == 7:
                        self.streak_achievements["streak_7"] += 1

                    # Check for streak milestone bonus (awarded at exact milestones)
                    player.streak_bonus = calculate_streak_bonus(player.streak)
                    # Check for steal unlock at 3-streak milestone (Story 15.3)
                    if player.streak == STEAL_UNLOCK_STREAK:
                        if player.unlock_steal():
                            _LOGGER.info(
                                "Player %s unlocked steal at %d streak",
                                player.name,
                                player.streak,
                            )
                else:
                    player.previous_streak = player.streak  # Store for display (5.4)
                    player.streak = 0
                    player.streak_bonus = 0

                # Story 20.4: Award artist bonus to challenge winner
                if self.artist_challenge and self.artist_challenge.winner == player.name:
                    player.artist_bonus = ARTIST_BONUS_POINTS
                else:
                    player.artist_bonus = 0

                # Issue #28: Award movie quiz bonus based on speed rank
                if self.movie_challenge:
                    player.movie_bonus = self.movie_challenge.get_player_bonus(player.name)
                    player.movie_bonus_total += player.movie_bonus
                else:
                    player.movie_bonus = 0

                # Add to total score (round_score + streak_bonus + artist_bonus + movie_bonus are separate)
                # Streak bonus, artist bonus, and movie bonus NOT doubled by bet
                player.score += (
                    player.round_score
                    + player.streak_bonus
                    + player.artist_bonus
                    + player.movie_bonus
                )

                # Track cumulative stats (Story 5.6) - AFTER all scoring
                player.rounds_played += 1
                player.best_streak = max(player.best_streak, player.streak)
                if player.bet_outcome == "won":
                    player.bets_won += 1

                # Track superlative data (Story 15.2)
                # Record submission time (elapsed from round start)
                if player.submission_time is not None and self.round_start_time is not None:
                    time_taken = player.submission_time - self.round_start_time
                    player.submission_times.append(time_taken)

                # Track bets placed (AC3: Risk Taker)
                if player.bet:
                    player.bets_placed += 1
                    # Story 19.12: Track game-level bet stats for analytics
                    self.bet_tracking["total_bets"] += 1
                    if player.bet_outcome == "won":
                        self.bet_tracking["bets_won"] += 1

                # Track close calls - +/-1 year but not exact (AC3: Close Calls)
                if player.years_off == 1:
                    player.close_calls += 1

                # Track round scores for Clutch Player calculation
                player.round_scores.append(player.round_score)
            else:
                # Non-submitter - store streak for "lost X-streak" display (5.4)
                player.previous_streak = player.streak
                player.round_score = 0
                player.base_score = 0
                player.speed_multiplier = 1.0
                player.years_off = None
                player.missed_round = True
                player.streak = 0  # Break streak
                player.streak_bonus = 0
                player.bet_outcome = None
                # Story 20.4: Non-submitters don't get artist bonus
                # (Note: They can still win if they guessed artist correctly during PLAYING)
                if self.artist_challenge and self.artist_challenge.winner == player.name:
                    player.artist_bonus = ARTIST_BONUS_POINTS
                    player.score += player.artist_bonus
                else:
                    player.artist_bonus = 0
                # Issue #28: Non-submitters can still earn movie bonus
                # (they may have guessed movie correctly during PLAYING)
                if self.movie_challenge:
                    player.movie_bonus = self.movie_challenge.get_player_bonus(player.name)
                    if player.movie_bonus > 0:
                        player.movie_bonus_total += player.movie_bonus
                        player.score += player.movie_bonus
                else:
                    player.movie_bonus = 0

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
                        playlist_name = playlist_path.replace(".json", "").replace("-", " ").title()
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
            _LOGGER.warning("No round_end callback set - REVEAL state will not be broadcast!")

    def cancel_timer(self) -> None:
        """Cancel the round timer (synchronous, for cleanup)."""
        if self._timer_task and not self._timer_task.done():
            # Don't cancel if we're being called from within the timer task itself
            # (happens when timer naturally expires and calls end_round)
            current_task = asyncio.current_task()
            if current_task != self._timer_task:
                self._timer_task.cancel()
        self._timer_task = None

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

    def adjust_volume(self, direction: str) -> float:
        """
        Adjust volume level by step (Story 6.4).

        Args:
            direction: "up" to increase, "down" to decrease

        Returns:
            New volume level (clamped 0.0 to 1.0)

        """
        from custom_components.beatify.const import VOLUME_STEP  # noqa: PLC0415

        # Sync with actual media player volume before adjusting
        if self._media_player_service:
            self.volume_level = self._media_player_service.get_volume()

        if direction == "up":
            self.volume_level = min(1.0, self.volume_level + VOLUME_STEP)
        elif direction == "down":
            self.volume_level = max(0.0, self.volume_level - VOLUME_STEP)

        return self.volume_level

    def calculate_round_analytics(self) -> RoundAnalytics:
        """
        Calculate analytics for current round reveal (Story 13.3).

        Returns:
            RoundAnalytics with all calculated fields.

        """
        correct_year = self.current_song.get("year") if self.current_song else None
        if correct_year is None:
            return RoundAnalytics()

        # Collect submitted player data
        submitted_players = [
            p for p in self.players.values() if p.submitted and p.current_guess is not None
        ]

        # Handle empty submissions (AC11)
        if not submitted_players:
            return RoundAnalytics(correct_decade=self._get_decade_label(correct_year))

        # Build all_guesses sorted by years_off (AC1)
        all_guesses = sorted(
            [
                {
                    "name": p.name,
                    "guess": p.current_guess,
                    "years_off": p.years_off or 0,
                }
                for p in submitted_players
            ],
            key=lambda x: x["years_off"],
        )

        guesses = [p.current_guess for p in submitted_players]

        # Calculate average and median values
        avg_guess = mean(guesses)
        med_guess = int(median(guesses))

        # Find closest players (min years_off) - handle ties (AC2, AC10)
        min_off = min(p.years_off or 0 for p in submitted_players)
        closest = [p.name for p in submitted_players if (p.years_off or 0) == min_off]

        # Find furthest players (max years_off) - handle ties (AC2, AC10)
        max_off = max(p.years_off or 0 for p in submitted_players)
        furthest = [p.name for p in submitted_players if (p.years_off or 0) == max_off]

        # Exact matches (AC2)
        exact = [p.name for p in submitted_players if p.years_off == 0]

        # Scored count and accuracy percentage (AC3, AC8)
        scored = sum(1 for p in submitted_players if p.round_score > 0)
        accuracy_pct = int((scored / len(submitted_players)) * 100)

        # Speed champion - fastest submission (AC3, AC10)
        speed_champion = None
        players_with_time = [
            p
            for p in submitted_players
            if p.submission_time is not None and self.round_start_time is not None
        ]
        if players_with_time:
            fastest_time = min(p.submission_time - self.round_start_time for p in players_with_time)
            speed_champs = [
                p.name
                for p in players_with_time
                if (p.submission_time - self.round_start_time) == fastest_time
            ]
            speed_champion = {
                "names": speed_champs,
                "time": round(fastest_time, 1),
            }

        # Decade distribution for histogram (AC5)
        decade_dist: dict[str, int] = {}
        for guess in guesses:
            decade = self._get_decade_label(guess)
            decade_dist[decade] = decade_dist.get(decade, 0) + 1

        return RoundAnalytics(
            all_guesses=all_guesses,
            average_guess=avg_guess,
            median_guess=med_guess,
            closest_players=closest,
            furthest_players=furthest,
            exact_match_players=exact,
            exact_match_count=len(exact),
            scored_count=scored,
            total_submitted=len(submitted_players),
            accuracy_percentage=accuracy_pct,
            speed_champion=speed_champion,
            decade_distribution=decade_dist,
            correct_decade=self._get_decade_label(correct_year),
        )

    def _get_decade_label(self, year: int) -> str:
        """
        Get decade label for a year (e.g., 1985 -> '1980s').

        Args:
            year: Year to get decade for

        Returns:
            Decade label string (e.g., "1980s")

        """
        decade = (year // 10) * 10
        return f"{decade}s"

    def calculate_superlatives(self) -> list[dict[str, Any]]:
        """
        Calculate fun awards based on game performance (Story 15.2).

        Returns list of awards (max 5) for display during END phase.
        Each award: {id, emoji, title, player_name, value, value_label}

        """
        awards: list[dict[str, Any]] = []
        players = list(self.players.values())

        if not players:
            return awards

        # Speed Demon - fastest average submission (AC3)
        # Requires at least MIN_SUBMISSIONS_FOR_SPEED submissions
        speed_candidates = [
            (p, p.avg_submission_time) for p in players if p.avg_submission_time is not None
        ]
        if speed_candidates:
            fastest = min(speed_candidates, key=lambda x: x[1])
            awards.append(
                {
                    "id": "speed_demon",
                    "emoji": "⚡",
                    "title": "speed_demon",  # i18n key
                    "player_name": fastest[0].name,
                    "value": round(fastest[1], 1),
                    "value_label": "avg_time",  # i18n key
                }
            )

        # Lucky Streak - longest streak achieved (AC3)
        # Minimum streak of MIN_STREAK_FOR_AWARD
        streak_candidates = [
            (p, p.best_streak) for p in players if p.best_streak >= MIN_STREAK_FOR_AWARD
        ]
        if streak_candidates:
            best = max(streak_candidates, key=lambda x: x[1])
            awards.append(
                {
                    "id": "lucky_streak",
                    "emoji": "🔥",
                    "title": "lucky_streak",
                    "player_name": best[0].name,
                    "value": best[1],
                    "value_label": "streak",
                }
            )

        # Risk Taker - most bets placed (AC3)
        # Minimum MIN_BETS_FOR_AWARD bets
        bet_candidates = [
            (p, p.bets_placed) for p in players if p.bets_placed >= MIN_BETS_FOR_AWARD
        ]
        if bet_candidates:
            most_bets = max(bet_candidates, key=lambda x: x[1])
            awards.append(
                {
                    "id": "risk_taker",
                    "emoji": "🎲",
                    "title": "risk_taker",
                    "player_name": most_bets[0].name,
                    "value": most_bets[1],
                    "value_label": "bets",
                }
            )

        # Clutch Player - best final 3 rounds (AC3)
        # Only if game has MIN_ROUNDS_FOR_CLUTCH+ rounds
        if self.round >= MIN_ROUNDS_FOR_CLUTCH:
            clutch_candidates = [
                (p, p.final_three_score)
                for p in players
                if len(p.round_scores) >= MIN_ROUNDS_FOR_CLUTCH
            ]
            if clutch_candidates:
                clutch = max(clutch_candidates, key=lambda x: x[1])
                # Only show if they scored something in final 3
                if clutch[1] > 0:
                    awards.append(
                        {
                            "id": "clutch_player",
                            "emoji": "🌟",
                            "title": "clutch_player",
                            "player_name": clutch[0].name,
                            "value": clutch[1],
                            "value_label": "points",
                        }
                    )

        # Close Calls - most +/-1 year guesses (AC3)
        # Minimum MIN_CLOSE_CALLS close guesses
        close_candidates = [(p, p.close_calls) for p in players if p.close_calls >= MIN_CLOSE_CALLS]
        if close_candidates:
            closest = max(close_candidates, key=lambda x: x[1])
            awards.append(
                {
                    "id": "close_calls",
                    "emoji": "🎯",
                    "title": "close_calls",
                    "player_name": closest[0].name,
                    "value": closest[1],
                    "value_label": "close_guesses",
                }
            )

        # Film Buff - most movie quiz bonus points (Issue #28)
        if self.movie_quiz_enabled:
            movie_candidates = [
                (p, p.movie_bonus_total)
                for p in players
                if p.movie_bonus_total >= MIN_MOVIE_WINS_FOR_AWARD
            ]
            if movie_candidates:
                film_buff = max(movie_candidates, key=lambda x: x[1])
                awards.append(
                    {
                        "id": "film_buff",
                        "emoji": "🎬",
                        "title": "film_buff",
                        "player_name": film_buff[0].name,
                        "value": film_buff[1],
                        "value_label": "movie_bonus",
                    }
                )

        # Limit to MAX_SUPERLATIVES awards (AC1)
        return awards[:MAX_SUPERLATIVES]

    def _init_artist_challenge(self, song: dict[str, Any]) -> ArtistChallenge | None:
        """
        Initialize artist challenge for a round (Story 20.2).

        Args:
            song: Song dict with artist info from playlist

        Returns:
            ArtistChallenge instance or None if artist challenge disabled
            or song lacks alt_artists data.

        """
        if not self.artist_challenge_enabled:
            return None

        options = build_artist_options(song)

        if not options or len(options) < 2:
            _LOGGER.debug("Skipping artist challenge: insufficient options")
            return None

        artist = song.get("artist", "")
        if isinstance(artist, str):
            artist = artist.strip()
        else:
            artist = ""

        return ArtistChallenge(
            correct_artist=artist,
            options=options,
            winner=None,
            winner_time=None,
        )

    def submit_artist_guess(
        self, player_name: str, artist: str, guess_time: float
    ) -> dict[str, Any]:
        """
        Submit artist guess for bonus points (Story 20.3).

        Args:
            player_name: Name of player guessing
            artist: Artist name guessed
            guess_time: Timestamp of guess

        Returns:
            Dict with keys: correct (bool), first (bool), winner (str|None)

        Raises:
            ValueError: If no artist challenge active

        """
        if not self.artist_challenge:
            raise ValueError("No artist challenge active")

        # Case-insensitive comparison
        correct = artist.strip().lower() == self.artist_challenge.correct_artist.lower()

        result: dict[str, Any] = {
            "correct": correct,
            "first": False,
            "winner": self.artist_challenge.winner,
        }

        if correct and not self.artist_challenge.winner:
            # First correct guess!
            self.artist_challenge.winner = player_name
            self.artist_challenge.winner_time = guess_time
            result["first"] = True
            result["winner"] = player_name
            _LOGGER.info("Artist challenge won by %s", player_name)

        return result

    def _init_movie_challenge(self, song: dict[str, Any]) -> MovieChallenge | None:
        """
        Initialize movie quiz challenge for a round (Issue #28).

        Args:
            song: Song dict with movie info from playlist

        Returns:
            MovieChallenge instance or None if movie quiz disabled
            or song lacks movie_choices data.

        """
        if not self.movie_quiz_enabled:
            return None

        options = build_movie_options(song)

        if not options or len(options) < 2:
            _LOGGER.debug("Skipping movie quiz: insufficient options")
            return None

        movie = song.get("movie", "")
        if isinstance(movie, str):
            movie = movie.strip()
        else:
            movie = ""

        if not movie:
            return None

        return MovieChallenge(
            correct_movie=movie,
            options=options,
            correct_guesses=[],
            wrong_guesses=[],
        )

    def submit_movie_guess(self, player_name: str, movie: str, guess_time: float) -> dict[str, Any]:
        """
        Submit movie guess for bonus points (Issue #28).

        Uses server-side timing. Correct guesses are ranked by speed
        for tiered bonus scoring (5/3/1 points).

        Args:
            player_name: Name of player guessing
            movie: Movie title guessed
            guess_time: Server timestamp of guess (time.time())

        Returns:
            Dict with keys: correct (bool), rank (int|None),
            bonus (int), already_guessed (bool)

        Raises:
            ValueError: If no movie challenge active

        """
        if not self.movie_challenge:
            raise ValueError("No movie challenge active")

        # Check if player already guessed
        for g in self.movie_challenge.correct_guesses:
            if g["name"] == player_name:
                return {"correct": True, "already_guessed": True, "rank": None, "bonus": 0}
        for g in self.movie_challenge.wrong_guesses:
            if g["name"] == player_name:
                return {"correct": False, "already_guessed": True, "rank": None, "bonus": 0}

        # Calculate elapsed time from round start (server-side timing)
        elapsed = 0.0
        if self.round_start_time is not None:
            elapsed = guess_time - self.round_start_time

        # Case-insensitive comparison
        correct = movie.strip().lower() == self.movie_challenge.correct_movie.lower()

        result: dict[str, Any] = {
            "correct": correct,
            "already_guessed": False,
            "rank": None,
            "bonus": 0,
        }

        if correct:
            self.movie_challenge.correct_guesses.append({"name": player_name, "time": elapsed})
            # Sort by time (fastest first) - ensures ranking is consistent
            self.movie_challenge.correct_guesses.sort(key=lambda g: g["time"])
            # Determine rank (0-indexed position)
            rank = next(
                i
                for i, g in enumerate(self.movie_challenge.correct_guesses)
                if g["name"] == player_name
            )
            bonus = MOVIE_BONUS_TIERS[rank] if rank < len(MOVIE_BONUS_TIERS) else 0
            result["rank"] = rank + 1  # 1-indexed for display
            result["bonus"] = bonus
            _LOGGER.info(
                "Movie quiz correct by %s (rank #%d, +%d bonus, %.2fs)",
                player_name,
                rank + 1,
                bonus,
                elapsed,
            )
        else:
            self.movie_challenge.wrong_guesses.append({"name": player_name, "guess": movie.strip()})
            _LOGGER.debug(
                "Movie quiz wrong by %s: '%s' (correct: '%s')",
                player_name,
                movie.strip(),
                self.movie_challenge.correct_movie,
            )

        return result
