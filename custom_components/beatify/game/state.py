"""Game state management for Beatify."""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from dataclasses import dataclass, field
from enum import Enum
from statistics import mean, median
from typing import TYPE_CHECKING, Any

from custom_components.beatify.const import (
    DEFAULT_ROUND_DURATION,
    DIFFICULTY_DEFAULT,
    ERR_APPLE_MUSIC_PLAYBACK,
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
    MIN_NAME_LENGTH,
    MIN_ROUNDS_FOR_CLUTCH,
    MIN_STREAK_FOR_AWARD,
    MIN_SUBMISSIONS_FOR_SPEED,
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

        # Round analytics (Story 13.3)
        self.round_analytics: RoundAnalytics | None = None

        # Stats service reference (Story 14.4)
        self._stats_service: StatsService | None = None

    def create_game(
        self,
        playlists: list[str],
        songs: list[dict[str, Any]],
        media_player: str,
        base_url: str,
        round_duration: int = DEFAULT_ROUND_DURATION,
        difficulty: str = DIFFICULTY_DEFAULT,
        provider: str = PROVIDER_DEFAULT,
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
                self._timer_task = asyncio.create_task(
                    self._timer_countdown(remaining_seconds)
                )
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

    def add_player(
        self, name: str, ws: web.WebSocketResponse
    ) -> tuple[bool, str | None]:
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
                else:
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
                name, initial_score, len(self.players) - 1
            )
        else:
            _LOGGER.info(
                "Player joined: %s (total: %d, late: %s)",
                name, len(self.players), joined_late
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

    def set_round_end_callback(
        self, callback: Callable[[], Awaitable[None]]
    ) -> None:
        """
        Set callback to invoke when round ends (for broadcasting).

        Args:
            callback: Async function to call when round ends

        """
        self._on_round_end = callback

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

    async def start_round(
        self, hass: HomeAssistant, _retry_count: int = 0
    ) -> bool:
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
            self._media_player_service = MediaPlayerService(hass, self.media_player)

        # Play song via media player
        if self._media_player_service:
            # Pre-flight check: verify speaker is responsive before playing
            # This wakes up sleeping speakers and detects unresponsive ones early
            if not await self._media_player_service.verify_responsive():
                _LOGGER.error("Media player not responsive, pausing game")
                await self.pause_game("media_player_error")
                return False

            # Use _resolved_uri if available (Story 17.3: multi-provider support)
            resolved_uri = song.get("_resolved_uri") or song.get("uri")
            success = await self._media_player_service.play_song(resolved_uri)
            if not success:
                _LOGGER.warning("Failed to play song: %s", song["uri"])  # Log original for debug
                self._playlist_manager.mark_played(resolved_uri)

                # Story 17.3: Apple Music specific error handling
                if resolved_uri and resolved_uri.startswith("applemusic://"):
                    _LOGGER.error(
                        "Apple Music playback failed. Check Music Assistant setup."
                    )
                    await self.pause_game(ERR_APPLE_MUSIC_PLAYBACK)
                    return False

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

            # Wait for metadata to update (polls until track ID matches or timeout)
            metadata = await self._media_player_service.wait_for_metadata_update(
                resolved_uri
            )
        else:
            # No media player (testing mode)
            metadata = {
                "artist": "Test Artist",
                "title": "Test Song",
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

        # Reset round analytics for new round (Story 13.3)
        self.round_analytics = None

        # Cancel any existing timer
        self.cancel_timer()

        # Calculate delay until deadline
        now_ms = int(self._now() * 1000)
        delay_seconds = (self.deadline - now_ms) / 1000.0

        # Start timer task for round expiry
        self._timer_task = asyncio.create_task(
            self._timer_countdown(delay_seconds)
        )

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
                _LOGGER.debug(
                    "Timer expired but phase already changed to %s", self.phase
                )
        except asyncio.CancelledError:
            _LOGGER.debug("Timer task cancelled")
            # Re-raise to properly complete cancellation
            raise

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
                if (
                    player.submission_time is not None
                    and self.round_start_time is not None
                ):
                    elapsed = player.submission_time - self.round_start_time
                else:
                    elapsed = self.round_duration  # No bonus if timing unavailable

                # Calculate score with speed bonus
                speed_score, player.base_score, player.speed_multiplier = (
                    calculate_round_score(
                        player.current_guess,
                        correct_year,
                        elapsed,
                        self.round_duration,
                        self.difficulty,
                    )
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
                    # Check for streak milestone bonus (awarded at exact milestones)
                    player.streak_bonus = calculate_streak_bonus(player.streak)
                    # Check for steal unlock at 3-streak milestone (Story 15.3)
                    if player.streak == STEAL_UNLOCK_STREAK:
                        if player.unlock_steal():
                            _LOGGER.info("Player %s unlocked steal at %d streak", player.name, player.streak)
                else:
                    player.previous_streak = player.streak  # Store for display (5.4)
                    player.streak = 0
                    player.streak_bonus = 0

                # Add to total score (round_score + streak_bonus are separate)
                # Streak bonus NOT doubled by bet
                player.score += player.round_score + player.streak_bonus

                # Track cumulative stats (Story 5.6) - AFTER all scoring
                player.rounds_played += 1
                player.best_streak = max(player.best_streak, player.streak)
                if player.bet_outcome == "won":
                    player.bets_won += 1

                # Track superlative data (Story 15.2)
                # Record submission time (elapsed from round start)
                if (
                    player.submission_time is not None
                    and self.round_start_time is not None
                ):
                    time_taken = player.submission_time - self.round_start_time
                    player.submission_times.append(time_taken)

                # Track bets placed (AC3: Risk Taker)
                if player.bet:
                    player.bets_placed += 1

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

        # Calculate round analytics after scoring (Story 13.3)
        self.round_analytics = self.calculate_round_analytics()

        # Record song results for difficulty tracking (Story 15.1 AC3)
        if self._stats_service and self.current_song:
            song_uri = self.current_song.get("uri")
            if song_uri:
                # Build player results list for song difficulty calculation
                player_results = [
                    {
                        "submitted": p.submitted,
                        "years_off": p.years_off if p.years_off is not None else 0,
                    }
                    for p in self.players.values()
                ]
                await self._stats_service.record_song_result(song_uri, player_results)

        # Transition to REVEAL
        self.phase = GamePhase.REVEAL
        _LOGGER.info("Round %d ended, phase: REVEAL", self.round)

        # Invoke callback to broadcast state
        if self._on_round_end:
            try:
                await self._on_round_end()
            except Exception as err:
                _LOGGER.error("Round_end callback failed: %s", err)

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
            speed bonus data (Story 5.1), and streak bonus (Story 5.2),
            sorted by total score descending.

        """
        players = [
            {
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
            for p in self.players.values()
        ]
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
            p for p in self.players.values()
            if p.submitted and p.current_guess is not None
        ]

        # Handle empty submissions (AC11)
        if not submitted_players:
            return RoundAnalytics(
                correct_decade=self._get_decade_label(correct_year)
            )

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
            p for p in submitted_players
            if p.submission_time is not None and self.round_start_time is not None
        ]
        if players_with_time:
            fastest_time = min(
                p.submission_time - self.round_start_time
                for p in players_with_time
            )
            speed_champs = [
                p.name for p in players_with_time
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
            (p, p.avg_submission_time)
            for p in players
            if p.avg_submission_time is not None
        ]
        if speed_candidates:
            fastest = min(speed_candidates, key=lambda x: x[1])
            awards.append({
                "id": "speed_demon",
                "emoji": "⚡",
                "title": "speed_demon",  # i18n key
                "player_name": fastest[0].name,
                "value": round(fastest[1], 1),
                "value_label": "avg_time",  # i18n key
            })

        # Lucky Streak - longest streak achieved (AC3)
        # Minimum streak of MIN_STREAK_FOR_AWARD
        streak_candidates = [
            (p, p.best_streak)
            for p in players
            if p.best_streak >= MIN_STREAK_FOR_AWARD
        ]
        if streak_candidates:
            best = max(streak_candidates, key=lambda x: x[1])
            awards.append({
                "id": "lucky_streak",
                "emoji": "🔥",
                "title": "lucky_streak",
                "player_name": best[0].name,
                "value": best[1],
                "value_label": "streak",
            })

        # Risk Taker - most bets placed (AC3)
        # Minimum MIN_BETS_FOR_AWARD bets
        bet_candidates = [
            (p, p.bets_placed)
            for p in players
            if p.bets_placed >= MIN_BETS_FOR_AWARD
        ]
        if bet_candidates:
            most_bets = max(bet_candidates, key=lambda x: x[1])
            awards.append({
                "id": "risk_taker",
                "emoji": "🎲",
                "title": "risk_taker",
                "player_name": most_bets[0].name,
                "value": most_bets[1],
                "value_label": "bets",
            })

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
                    awards.append({
                        "id": "clutch_player",
                        "emoji": "🌟",
                        "title": "clutch_player",
                        "player_name": clutch[0].name,
                        "value": clutch[1],
                        "value_label": "points",
                    })

        # Close Calls - most +/-1 year guesses (AC3)
        # Minimum MIN_CLOSE_CALLS close guesses
        close_candidates = [
            (p, p.close_calls)
            for p in players
            if p.close_calls >= MIN_CLOSE_CALLS
        ]
        if close_candidates:
            closest = max(close_candidates, key=lambda x: x[1])
            awards.append({
                "id": "close_calls",
                "emoji": "🎯",
                "title": "close_calls",
                "player_name": closest[0].name,
                "value": closest[1],
                "value_label": "close_guesses",
            })

        # Limit to MAX_SUPERLATIVES awards (AC1)
        return awards[:MAX_SUPERLATIVES]
