"""High-level game operations facade (Issues #603, #609).

GameService provides a clean API for transport handlers (WebSocket, HTTP)
to interact with the game without reaching into GameState internals.

This is a **partial extraction** — only the most commonly used operations
have been moved here.  Existing code that accesses GameState directly
continues to work; callers can migrate incrementally.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from custom_components.beatify.const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from custom_components.beatify.game.state import GameState
    from custom_components.beatify.services.stats import StatsService

_LOGGER = logging.getLogger(__name__)


class GameService:
    """High-level game operations facade.

    Wraps the most common GameState operations that transport handlers
    (WebSocket, HTTP views) need, reducing their direct coupling to
    GameState internals.
    """

    def __init__(self, hass: HomeAssistant, game_state: GameState) -> None:
        self._hass = hass
        self._game_state = game_state

    # ------------------------------------------------------------------
    # Direct access to the underlying GameState (escape hatch for
    # operations not yet migrated to the service layer).
    # ------------------------------------------------------------------

    @property
    def state(self) -> GameState:
        """Return the underlying GameState for backward compatibility."""
        return self._game_state

    # ------------------------------------------------------------------
    # Stats helper (reduces repeated hass.data lookups in handlers)
    # ------------------------------------------------------------------

    @property
    def stats_service(self) -> StatsService | None:
        """Return the StatsService if available."""
        return self._hass.data.get(DOMAIN, {}).get("stats")

    # ------------------------------------------------------------------
    # Game lifecycle
    # ------------------------------------------------------------------

    async def create_game(self, **kwargs: Any) -> dict[str, Any]:
        """Create a new game session.

        Accepts the same keyword arguments as ``GameState.create_game``.
        Returns the result dict (game_id, join_url, phase, song_count).
        """
        return self._game_state.create_game(**kwargs)

    async def start_round(self) -> bool:
        """Start the next round (song playback + timer).

        Returns True if the round started successfully.
        """
        return await self._game_state.start_round()

    async def end_round(self) -> None:
        """End the current round and transition to REVEAL."""
        await self._game_state.end_round()

    async def advance_to_end(self) -> None:
        """Transition from REVEAL to END phase with cleanup."""
        await self._game_state.advance_to_end()

    async def end_game(self) -> None:
        """Fully end and reset the game (wipes all players)."""
        await self._game_state.end_game()

    def rematch_game(self) -> None:
        """Reset for rematch, preserving connected players."""
        self._game_state.rematch_game()

    async def finalize_and_record_stats(self) -> None:
        """Finalize game stats and record them via StatsService.

        This encapsulates the repeated pattern found in websocket.py
        where ``finalize_game()`` + ``stats_service.record_game()``
        are called together.
        """
        stats = self.stats_service
        if stats:
            game_summary = self._game_state.finalize_game()
            await stats.record_game(
                game_summary, difficulty=self._game_state.difficulty
            )
            _LOGGER.debug("Game stats recorded via GameService")

    # ------------------------------------------------------------------
    # Round-level operations
    # ------------------------------------------------------------------

    async def next_round(self) -> bool:
        """Advance to the next round, or end the game if no rounds remain.

        Handles the finalize-stats + advance-to-end logic that is
        duplicated across several admin handlers in websocket.py.

        Returns True if a new round was started successfully.
        """
        gs = self._game_state
        if gs.last_round:
            await self.finalize_and_record_stats()
            await gs.advance_to_end()
            return False

        success = await gs.start_round()
        if not success:
            await self.finalize_and_record_stats()
            await gs.advance_to_end()
            return False

        return True

    async def stop_song(self) -> None:
        """Stop the currently playing song and mark it stopped."""
        gs = self._game_state
        await gs.stop_media()
        gs.song_stopped = True
        _LOGGER.info("Song stopped in round %d", gs.round)

    # ------------------------------------------------------------------
    # Player operations
    # ------------------------------------------------------------------

    def submit_guess(self, player_name: str, year: int, bet: bool = False) -> None:
        """Record a year guess for the named player.

        The caller is responsible for validation (phase, deadline, year
        range) before calling this method.
        """
        player = self._game_state.get_player(player_name)
        if not player:
            return
        player.bet = bet
        submission_time = self._game_state.current_time()
        player.submit_guess(year, submission_time)

    def submit_artist_guess(self, player_name: str, artist: str) -> dict[str, Any]:
        """Submit an artist challenge guess.

        Returns the result dict from ChallengeManager.
        """
        guess_time = self._game_state.current_time()
        result = self._game_state.submit_artist_guess(player_name, artist, guess_time)
        player = self._game_state.get_player(player_name)
        if player:
            player.has_artist_guess = True
        return result

    def submit_movie_guess(self, player_name: str, movie: str) -> dict[str, Any]:
        """Submit a movie quiz guess.

        Returns the result dict from ChallengeManager.
        """
        guess_time = self._game_state.current_time()
        result = self._game_state.submit_movie_guess(player_name, movie, guess_time)
        player = self._game_state.get_player(player_name)
        if player:
            player.has_movie_guess = True
        return result

    async def trigger_early_reveal_if_complete(self) -> None:
        """Check and trigger early reveal when all guesses are in."""
        await self._game_state.trigger_early_reveal_if_complete()
