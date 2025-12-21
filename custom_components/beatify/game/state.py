"""Game state management for Beatify."""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
from enum import Enum
from typing import TYPE_CHECKING, Any

from custom_components.beatify.const import (
    DEFAULT_ROUND_DURATION,
    ERR_GAME_ALREADY_STARTED,
    ERR_GAME_ENDED,
    ERR_GAME_FULL,
    ERR_GAME_NOT_STARTED,
    ERR_NAME_INVALID,
    ERR_NAME_TAKEN,
    MAX_NAME_LENGTH,
    MAX_PLAYERS,
    MIN_NAME_LENGTH,
)

from .player import PlayerSession
from .playlist import PlaylistManager
from .scoring import apply_bet_multiplier, calculate_round_score, calculate_streak_bonus

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from aiohttp import web
    from homeassistant.core import HomeAssistant

    from custom_components.beatify.services.media_player import MediaPlayerService

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
        self.phase: GamePhase = GamePhase.LOBBY
        self.playlists: list[str] = []
        self.songs: list[dict[str, Any]] = []
        self.media_player: str | None = None
        self.join_url: str | None = None
        self.players: dict[str, PlayerSession] = {}

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

    def create_game(
        self,
        playlists: list[str],
        songs: list[dict[str, Any]],
        media_player: str,
        base_url: str,
    ) -> dict[str, Any]:
        """
        Create a new game session.

        Args:
            playlists: List of playlist file paths
            songs: List of song dicts loaded from playlists
            media_player: Entity ID of media player
            base_url: HA base URL for join URL construction

        Returns:
            dict with game_id, join_url, song_count, phase

        """
        self.game_id = secrets.token_urlsafe(8)
        self.phase = GamePhase.LOBBY
        self.playlists = playlists
        self.songs = songs
        self.media_player = media_player
        self.join_url = f"{base_url}/beatify/play?game={self.game_id}"
        self.players = {}

        # Initialize PlaylistManager for song selection (Epic 4)
        self._playlist_manager = PlaylistManager(songs)

        # Reset round tracking for new game
        self.round = 0
        self.total_rounds = len(songs)
        self.deadline = None
        self.current_song = None
        self.last_round = False
        self.pause_reason = None
        self._previous_phase = None

        # Reset timing for speed bonus (Story 5.1)
        self.round_start_time = None
        self.round_duration = DEFAULT_ROUND_DURATION

        # Reset song stopped flag (Story 6.2)
        self.song_stopped = False

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

        return state

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

        # Reset admin disconnect tracking (Epic 7)
        self.disconnected_admin_name = None

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

        # Add new player
        self.players[name] = PlayerSession(
            name=name, ws=ws, score=0, streak=0, joined_late=joined_late
        )
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

    def remove_player(self, name: str) -> None:
        """
        Remove player from game.

        Args:
            name: Player name to remove

        """
        if name in self.players:
            del self.players[name]
            _LOGGER.info("Player removed: %s", name)

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

    async def start_round(self, hass: HomeAssistant) -> bool:
        """
        Start a new round with song playback.

        Args:
            hass: Home Assistant instance for media player control

        Returns:
            True if round started successfully, False otherwise

        """
        # Import here to avoid circular imports
        from custom_components.beatify.services.media_player import (  # noqa: PLC0415
            MediaPlayerService,
        )

        if not self._playlist_manager:
            _LOGGER.error("No playlist manager configured")
            return False

        # Get next song
        song = self._playlist_manager.get_next_song()
        if not song:
            _LOGGER.info("All songs exhausted, ending game")
            self.phase = GamePhase.END
            return False

        # Check if this is the last round (1 song remaining after this one)
        self.last_round = self._playlist_manager.get_remaining_count() <= 1

        # Create media player service if needed
        if self.media_player and not self._media_player_service:
            self._media_player_service = MediaPlayerService(hass, self.media_player)

        # Play song via media player
        if self._media_player_service:
            success = await self._media_player_service.play_song(song["uri"])
            if not success:
                _LOGGER.warning("Failed to play song: %s", song["uri"])
                self._playlist_manager.mark_played(song["uri"])
                # Try next song recursively
                return await self.start_round(hass)

            # Wait for playback to start
            await asyncio.sleep(0.5)

            # Get metadata from media player
            metadata = await self._media_player_service.get_metadata()
        else:
            # No media player (testing mode)
            metadata = {
                "artist": "Test Artist",
                "title": "Test Song",
                "album_art": "/beatify/static/img/no-artwork.svg",
            }

        # Mark song as played
        self._playlist_manager.mark_played(song["uri"])

        # Set current song (year and fun_fact from playlist, rest from metadata)
        self.current_song = {
            "year": song["year"],
            "fun_fact": song.get("fun_fact", ""),
            "uri": song["uri"],
            **metadata,
        }

        # Update round tracking
        self.round += 1
        self.total_rounds = self._playlist_manager.get_total_count()

        # Record round start time for speed bonus calculation (Story 5.1)
        self.round_start_time = self._now()
        self.round_duration = DEFAULT_ROUND_DURATION
        self.deadline = int((self.round_start_time + self.round_duration) * 1000)

        # Reset player submissions for new round
        for player in self.players.values():
            player.reset_round()

        # Reset song stopped flag for new round (Story 6.2)
        self.song_stopped = False

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

        # Transition to REVEAL
        self.phase = GamePhase.REVEAL
        _LOGGER.info("Round %d ended, phase: REVEAL", self.round)

        # Invoke callback to broadcast state
        if self._on_round_end:
            await self._on_round_end()

    def cancel_timer(self) -> None:
        """Cancel the round timer (synchronous, for cleanup)."""
        if self._timer_task and not self._timer_task.done():
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

        if direction == "up":
            self.volume_level = min(1.0, self.volume_level + VOLUME_STEP)
        elif direction == "down":
            self.volume_level = max(0.0, self.volume_level - VOLUME_STEP)

        return self.volume_level
