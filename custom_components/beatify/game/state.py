"""Game state management for Beatify."""

from __future__ import annotations

import logging
import secrets
import time
from enum import Enum
from typing import TYPE_CHECKING, Any

from custom_components.beatify.const import (
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

if TYPE_CHECKING:
    from collections.abc import Callable

    from aiohttp import web

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
        """Initialize game state.

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

    def create_game(
        self,
        playlists: list[str],
        songs: list[dict[str, Any]],
        media_player: str,
        base_url: str,
    ) -> dict[str, Any]:
        """Create a new game session.

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

        _LOGGER.info("Game created: %s with %d songs", self.game_id, len(songs))

        return {
            "game_id": self.game_id,
            "join_url": self.join_url,
            "phase": self.phase.value,
            "song_count": len(songs),
        }

    def get_state(self) -> dict[str, Any] | None:
        """Get current game state for broadcast.

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
            # Round info - defaults for Epic 4
            state["round"] = getattr(self, "round", 1)
            state["total_rounds"] = getattr(self, "total_rounds", 10)
            state["deadline"] = getattr(self, "deadline", None)
            # Song info - Epic 4
            current_song = getattr(self, "current_song", None)
            if current_song:
                state["song"] = {
                    "artist": current_song.get("artist", "Unknown"),
                    "title": current_song.get("title", "Unknown"),
                    "album_art": current_song.get(
                        "album_art", "/beatify/static/img/no-artwork.svg"
                    ),
                }

        elif self.phase == GamePhase.REVEAL:
            state["join_url"] = self.join_url
            state["round"] = getattr(self, "round", 1)
            state["total_rounds"] = getattr(self, "total_rounds", 10)
            # Full song info including year
            current_song = getattr(self, "current_song", None)
            if current_song:
                state["song"] = current_song

        elif self.phase == GamePhase.END:
            # Include winner info
            if self.players:
                winner = max(self.players.values(), key=lambda p: p.score)
                state["winner"] = {"name": winner.name, "score": winner.score}

        return state

    def end_game(self) -> None:
        """End the current game and reset state."""
        _LOGGER.info("Game ended: %s", self.game_id)
        self.game_id = None
        self.phase = GamePhase.LOBBY
        self.playlists = []
        self.songs = []
        self.media_player = None
        self.join_url = None
        self.players = {}

    def add_player(self, name: str, ws: web.WebSocketResponse) -> tuple[bool, str | None]:
        """Add a player to the game.

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

        # Check phase - reject END state
        if self.phase == GamePhase.END:
            return False, ERR_GAME_ENDED

        # Check player limit
        if len(self.players) >= MAX_PLAYERS:
            return False, ERR_GAME_FULL

        # Check uniqueness (case-insensitive)
        if name.lower() in [p.lower() for p in self.players]:
            return False, ERR_NAME_TAKEN

        # Determine if late joiner
        joined_late = self.phase != GamePhase.LOBBY

        # Add player
        self.players[name] = PlayerSession(
            name=name, ws=ws, score=0, streak=0, joined_late=joined_late
        )
        _LOGGER.info(
            "Player joined: %s (total: %d, late: %s)",
            name, len(self.players), joined_late
        )
        return True, None

    def get_player(self, name: str) -> PlayerSession | None:
        """Get player by name.

        Args:
            name: Player name

        Returns:
            PlayerSession or None if not found
        """
        return self.players.get(name)

    def remove_player(self, name: str) -> None:
        """Remove player from game.

        Args:
            name: Player name to remove
        """
        if name in self.players:
            del self.players[name]
            _LOGGER.info("Player removed: %s", name)

    def get_players_state(self) -> list[dict[str, Any]]:
        """Get player list for state broadcast.

        Returns:
            List of player dicts with name, score, connected, streak, is_admin
        """
        return [
            {
                "name": p.name,
                "score": p.score,
                "connected": p.connected,
                "streak": p.streak,
                "is_admin": p.is_admin,
            }
            for p in self.players.values()
        ]

    def set_admin(self, name: str) -> bool:
        """Mark a player as the admin.

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
        """Start the game, transitioning from LOBBY to PLAYING.

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
