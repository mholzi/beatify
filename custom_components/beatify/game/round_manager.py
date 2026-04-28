"""Round lifecycle manager for Beatify (Issue #464).

Owns all per-round state that was previously scattered across
``GameState``: round counter, timer/deadline, current song,
intro-mode logic, and metadata-pending flag.

``GameState`` delegates property access and method calls here so
the public interface stays identical.
"""

from __future__ import annotations

import asyncio
import logging
import random
from typing import TYPE_CHECKING, Any

from custom_components.beatify.const import (
    DEFAULT_ROUND_DURATION,
    INTRO_DURATION_SECONDS,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from homeassistant.core import HomeAssistant

    from .challenges import ChallengeManager
    from .player import PlayerSession
    from .playlist import PlaylistManager
    from .protocols import MediaPlayerProtocol
    from .types import RoundAnalytics

_LOGGER = logging.getLogger(__name__)


def _log_timer_task_failure(task: asyncio.Task) -> None:
    """Surface silent crashes in the round timer task (#816).

    Without this done-callback, an unhandled exception in the timer
    coroutine (or anything it awaits — including end_round and the
    full scoring path) leaves the task in `done with exception` state
    but nobody retrieves the result, so the round stays frozen on
    PLAYING with no diagnostic in the logs. Logging the exception here
    means the next time this happens we have a clear stack trace
    pointing at the actual cause.
    """
    if task.cancelled():
        return  # Cancellation is expected (admin pressed End/Pause/Skip).
    exc = task.exception()
    if exc is not None:
        _LOGGER.error(
            "Round timer task crashed silently — round will stay frozen "
            "on PLAYING. Error: %s",
            exc,
            exc_info=exc,
        )


# Intro mode constraints
_INTRO_MIN_ROUND = 3  # No intro before round 3
_INTRO_MIN_GAP = 2  # At least 2 normal rounds between intros
_INTRO_FORCE_GAP = 5  # Force intro after 5 non-intro rounds
_INTRO_PROBABILITY = 0.20  # ~20 % chance per eligible round
_INTRO_MIN_DURATION_MS = 30_000  # Song must be >= 30 s


class RoundManager:
    """Manages round lifecycle: number, timer, deadline, intro mode, metadata."""

    def __init__(self, time_fn: Callable[[], float]) -> None:
        self._now = time_fn

        # Round tracking
        self.round: int = 0
        self.total_rounds: int = 0
        self.deadline: int | None = None
        self.current_song: dict[str, Any] | None = None
        self.last_round: bool = False
        self.round_start_time: float | None = None
        self.round_duration: float = DEFAULT_ROUND_DURATION
        self.song_stopped: bool = False
        self.round_analytics: RoundAnalytics | None = None

        # Metadata
        self.metadata_pending: bool = False

        # Early reveal (all players submitted)
        self._early_reveal: bool = False

        # Timer tasks
        self._timer_task: asyncio.Task | None = None
        self._intro_stop_task: asyncio.Task | None = None
        self._metadata_task: asyncio.Task | None = None

        # Intro mode
        self.intro_mode_enabled: bool = False
        self.is_intro_round: bool = False
        self.intro_stopped: bool = False
        self._intro_round_start_time: float | None = None
        self._intro_splash_pending: bool = False
        self._intro_splash_shown: bool = False
        self._intro_splash_deferred_song: dict[str, Any] | None = None
        self._rounds_since_intro: int = 0

    # ------------------------------------------------------------------
    # Reset
    # ------------------------------------------------------------------

    def reset(self) -> None:
        """Reset all round state for a new game / end-game."""
        self.cancel_timer()
        self._cancel_intro_timer()
        self._cancel_metadata_task()

        self.round = 0
        self.total_rounds = 0
        self.deadline = None
        self.current_song = None
        self.last_round = False
        self.round_start_time = None
        self.round_duration = DEFAULT_ROUND_DURATION
        self.song_stopped = False
        self.round_analytics = None
        self.metadata_pending = False
        self._early_reveal = False

        self.is_intro_round = False
        self.intro_stopped = False
        self._intro_round_start_time = None
        self._intro_splash_pending = False
        self._intro_splash_shown = False
        self._intro_splash_deferred_song = None
        self._rounds_since_intro = 0

    # ------------------------------------------------------------------
    # Timer management
    # ------------------------------------------------------------------

    def cancel_timer(self) -> None:
        """Cancel the round timer task if running."""
        if self._timer_task is not None:
            self._timer_task.cancel()
            self._timer_task = None

    def _cancel_intro_timer(self) -> None:
        """Cancel the intro auto-stop task if running."""
        if self._intro_stop_task is not None:
            self._intro_stop_task.cancel()
            self._intro_stop_task = None

    def _cancel_metadata_task(self) -> None:
        """Cancel the background metadata task if running."""
        if self._metadata_task is not None:
            self._metadata_task.cancel()
            self._metadata_task = None

    @staticmethod
    def _on_metadata_task_done(task: asyncio.Task) -> None:
        """Log unhandled exceptions from background metadata fetch."""
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            _LOGGER.error("Background metadata fetch failed: %s", exc)

    def is_deadline_passed(self) -> bool:
        """Return True if the round deadline has passed."""
        if self.deadline is None:
            return False
        now_ms = int(self._now() * 1000)
        return now_ms >= self.deadline

    async def _timer_countdown(self, delay_seconds: float) -> None:
        """Sleep for the round timer duration.

        The caller (``GameState._timer_countdown``) wraps this with
        phase-aware ``end_round`` logic.
        """
        await asyncio.sleep(delay_seconds)

    async def _intro_auto_stop(
        self,
        remaining_seconds: float,
        on_round_end: Callable[[], Awaitable[None]] | None,
    ) -> None:
        """Auto-stop the intro after *remaining_seconds*.

        Sets ``intro_stopped = True`` so the frontend switches to the
        guessing UI.  Does **not** stop media playback — music continues
        through the reveal phase for intro rounds.
        """
        try:
            await asyncio.sleep(remaining_seconds)
            self.intro_stopped = True
            _LOGGER.info("Intro auto-stopped after %.1fs", remaining_seconds)
            if on_round_end:
                await on_round_end()
        except asyncio.CancelledError:
            _LOGGER.debug("Intro auto-stop cancelled")
            raise

    # ------------------------------------------------------------------
    # Intro round preparation
    # ------------------------------------------------------------------

    def prepare_intro_round(
        self, song: dict[str, Any], hass: HomeAssistant | None
    ) -> bool:
        """Decide whether this round should be an intro round.

        Returns ``True`` if the round will defer playback for an intro
        splash screen (``will_defer_for_splash``).
        """
        self.is_intro_round = False
        self._intro_splash_pending = False
        self._intro_splash_shown = False
        self._intro_splash_deferred_song = None
        self.intro_stopped = False
        self._intro_round_start_time = None

        if not self.intro_mode_enabled:
            return False

        # Too early in the game
        if self.round < _INTRO_MIN_ROUND:
            return False

        # Song must be long enough
        duration_ms = song.get("duration_ms", 0)
        if duration_ms and duration_ms < _INTRO_MIN_DURATION_MS:
            return False

        # Determine eligibility based on gap since last intro
        self._rounds_since_intro += 1

        if self._rounds_since_intro >= _INTRO_FORCE_GAP:
            selected = True
        elif self._rounds_since_intro >= _INTRO_MIN_GAP:
            selected = random.random() < _INTRO_PROBABILITY  # noqa: S311
        else:
            selected = False

        if not selected:
            return False

        # This round is an intro round
        self.is_intro_round = True
        self._intro_splash_pending = True
        self._intro_splash_deferred_song = dict(song)
        self._rounds_since_intro = 0

        _LOGGER.info("Round %d selected as intro round", self.round + 1)
        return True

    # ------------------------------------------------------------------
    # Round metadata & initialization
    # ------------------------------------------------------------------

    def build_round_metadata(
        self,
        song: dict[str, Any],
        resolved_uri: str,
        will_defer_for_splash: bool,
        media_player_service: MediaPlayerProtocol | None,
        metadata_coro: Any,
    ) -> dict[str, Any]:
        """Build the initial metadata dict used by ``initialize_round``.

        Args:
            song: Playlist song dict.
            resolved_uri: Provider-resolved URI for playback.
            will_defer_for_splash: True if playback is deferred for intro splash.
            media_player_service: Media player service (may be None).
            metadata_coro: Coroutine for async album-art fetch (may be None).

        Returns:
            Metadata dict consumed by ``initialize_round``.

        """
        album_art = song.get("album_art", "/beatify/static/img/no-artwork.svg")
        needs_fetch = media_player_service is not None and not will_defer_for_splash
        return {
            "album_art": album_art,
            "metadata_pending": needs_fetch,
            "metadata_coro": metadata_coro if needs_fetch else None,
            "resolved_uri": resolved_uri,
        }

    def initialize_round(
        self,
        song: dict[str, Any],
        metadata: dict[str, Any],
        resolved_uri: str,
        will_defer_for_splash: bool,
        playlist_manager: PlaylistManager | None,
        challenge_manager: ChallengeManager | None,
        players: dict[str, PlayerSession],
        timer_countdown: Callable[[float], Awaitable[None]],
        on_round_end: Callable[[], Awaitable[None]] | None,
    ) -> None:
        """Commit all round state for a new round.

        Increments round counter, sets current song, deadline, resets
        per-round player state, generates challenges, marks song as
        played, and starts timer/intro tasks.
        """
        self.round += 1
        self.current_song = dict(song)
        self.song_stopped = False
        self._early_reveal = False
        self.metadata_pending = metadata.get("metadata_pending", False)
        self.round_analytics = None

        now = self._now()
        self.round_start_time = now
        self.deadline = int(now * 1000) + int(self.round_duration * 1000)

        # Reset per-round player state
        for player in players.values():
            player.reset_round()

        # Mark song as played in playlist
        if playlist_manager:
            playlist_manager.mark_played(resolved_uri)

        # Generate challenges for this round
        if challenge_manager:
            challenge_manager.init_round(song)

        # Handle deferred intro splash vs normal timer start
        if will_defer_for_splash:
            # Playback deferred — timer starts on confirm_intro_splash
            _LOGGER.debug("Round %d deferred for intro splash", self.round)
        else:
            delay = (self.deadline - int(self._now() * 1000)) / 1000.0
            self._timer_task = asyncio.create_task(timer_countdown(delay))
            # #816: surface any silent task crash. Without this callback,
            # an unhandled exception inside `timer_countdown` (or anything
            # it awaits, e.g. end_round → scoring) leaves the task in
            # `done with exception` state but nobody calls `task.result()`,
            # so the round stays frozen on PLAYING with no log of what
            # went wrong. Now we always log the failure mode.
            self._timer_task.add_done_callback(_log_timer_task_failure)

            # Start intro auto-stop timer if this is an intro round
            if self.is_intro_round and on_round_end:
                self._intro_round_start_time = now
                self._intro_stop_task = asyncio.create_task(
                    self._intro_auto_stop(INTRO_DURATION_SECONDS, on_round_end)
                )

        # Start background metadata fetch
        self._cancel_metadata_task()
        metadata_coro = metadata.get("metadata_coro")
        if metadata_coro is not None:
            self._metadata_task = asyncio.create_task(metadata_coro)
            self._metadata_task.add_done_callback(self._on_metadata_task_done)

    # ------------------------------------------------------------------
    # Intro splash confirmation
    # ------------------------------------------------------------------

    async def confirm_intro_splash(
        self,
        play_deferred_song: Callable[[dict[str, Any]], Awaitable[bool]],
        on_round_end: Callable[[], Awaitable[None]] | None,
        timer_countdown: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        """Handle admin confirmation of intro splash (Issue #292, #403).

        Plays the deferred song, starts the round timer and the intro
        auto-stop timer.
        """
        if not self._intro_splash_pending:
            _LOGGER.warning("confirm_intro_splash called but no splash pending")
            return

        self._intro_splash_pending = False
        self._intro_splash_shown = True

        song = self._intro_splash_deferred_song
        if song:
            await play_deferred_song(song)

        # Cancel any existing timers to prevent leaks on double-tap (#493)
        self.cancel_timer()
        self._cancel_intro_timer()

        # Recalculate deadline from now
        now = self._now()
        self.round_start_time = now
        self.deadline = int(now * 1000) + int(self.round_duration * 1000)
        self._intro_round_start_time = now

        delay = (self.deadline - int(now * 1000)) / 1000.0
        countdown = timer_countdown or self._timer_countdown
        self._timer_task = asyncio.create_task(countdown(delay))
        self._timer_task.add_done_callback(_log_timer_task_failure)

        # Start intro auto-stop
        self._intro_stop_task = asyncio.create_task(
            self._intro_auto_stop(INTRO_DURATION_SECONDS, on_round_end)
        )

        _LOGGER.info("Intro splash confirmed, round timer started")
