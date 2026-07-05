"""Game statistics tracking service for Beatify."""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from custom_components.beatify.analytics import AnalyticsStorage

_LOGGER = logging.getLogger(__name__)

# Cap on detailed game entries kept in stats.json. Older games are folded into
# the all_time aggregates incrementally as they age out, so the per-save
# json.dumps cost (and file size) stays bounded instead of growing forever as
# more games are recorded (#1402). The all_time average is maintained from a
# running weighted sum, so dropping detailed entries does not skew it.
MAX_DETAILED_GAMES = 500

# Debounce window for per-round stat saves. record_song_result runs once per
# round (~30s) and each call would otherwise rewrite the entire growing
# stats.json via json.dumps (#1708). We coalesce rapid saves into a single
# write scheduled STATS_SAVE_DEBOUNCE_SECONDS in the future; any save requested
# before the timer fires resets it. Game end and unload flush explicitly so no
# data is lost. Mirrors AnalyticsStorage's error-save debounce (#1388).
STATS_SAVE_DEBOUNCE_SECONDS = 30.0


class StatsService:
    """Service for tracking game statistics."""

    def __init__(self, hass: HomeAssistant) -> None:
        """
        Initialize stats service.

        Args:
            hass: Home Assistant instance

        """
        self._hass = hass
        self._stats_file = Path(hass.config.path("beatify/stats.json"))
        self._stats: dict[str, Any] = self._empty_stats()
        self._analytics: AnalyticsStorage | None = None
        self._game_start_time: int | None = None
        self._all_time_avg_cache: float | None = None
        self._save_task: asyncio.Task | None = None
        self._save_lock = asyncio.Lock()
        # Dirty flag: set on every _schedule_save_now(); the save's
        # done-callback re-schedules if it was set again while a save was in
        # flight, so mutations made during a save are never silently dropped
        # (#1402).
        self._save_dirty = False
        # Pending debounce timer for schedule_save() (#1708). None when no save
        # is queued; a call_later handle otherwise.
        self._save_handle: asyncio.TimerHandle | None = None

    def set_analytics(self, analytics: AnalyticsStorage) -> None:
        """
        Set analytics storage for data collection (Story 19.1).

        Args:
            analytics: AnalyticsStorage instance

        """
        self._analytics = analytics

    def record_game_start(self) -> None:
        """Record game start time for duration calculation (Story 19.1)."""
        self._game_start_time = int(time.time())
        if self._analytics:
            self._analytics.reset_session_errors()

    def _empty_stats(self) -> dict[str, Any]:
        """Return empty stats structure."""
        return {
            "version": 1,
            "games": [],
            "playlists": {},
            "all_time": {
                "games_played": 0,
                "highest_avg_score": 0.0,
                "highest_avg_game_id": None,
                # Running weighted score sums so all_time_avg survives the
                # detailed-games cap: when a game ages out of the detailed list
                # its weighted contribution is folded in here (#1402).
                "total_weighted_score": 0.0,
                "total_weight": 0,
            },
            "songs": {},  # Song difficulty tracking (Story 15.1)
        }

    async def load(self) -> None:
        """Load stats from file or create empty structure."""
        try:
            if self._stats_file.exists():
                content = await self._hass.async_add_executor_job(
                    self._stats_file.read_text
                )
                self._stats = json.loads(content)
                self._all_time_avg_cache = None
                _LOGGER.debug(
                    "Loaded stats: %d games played",
                    self._stats.get("all_time", {}).get("games_played", 0),
                )
            else:
                _LOGGER.debug("No stats file found, starting fresh")
                self._stats = self._empty_stats()
        except OSError as err:
            # The file exists but cannot be read (permissions, transient I/O
            # error). Start fresh in memory so startup is not blocked, but do
            # NOT persist an empty file — that would destroy the unreadable
            # (possibly recoverable) history. A later successful save can still
            # overwrite it once whatever blocked the read clears (#1402).
            _LOGGER.error("Stats file unreadable, starting fresh in memory: %s", err)
            self._stats = self._empty_stats()
            self._all_time_avg_cache = None
        except (json.JSONDecodeError, KeyError, TypeError) as err:
            _LOGGER.warning("Stats file corrupted, recreating: %s", err)
            self._stats = self._empty_stats()
            self._all_time_avg_cache = None
            await self.save()

    async def save(self) -> None:
        """
        Persist stats to file with a crash-safe atomic write.

        Mirrors the temp-file + os.replace pattern used by
        ``AnalyticsStorage._save``: the JSON is written to ``stats.json.tmp``
        first and then atomically renamed over ``stats.json``. A crash or
        power loss mid-write leaves the previous (valid) stats.json intact
        instead of a truncated file that load() would discard, wiping all
        game history (#1386). The lock serializes concurrent saves (e.g. a
        directly-awaited save from load()'s corruption path interleaving with
        a scheduled save task).
        """
        async with self._save_lock:
            try:
                # Ensure directory exists
                await self._hass.async_add_executor_job(
                    self._stats_file.parent.mkdir, 0o755, True, True
                )

                # Take a REAL snapshot on the loop thread before dispatching to
                # the executor. json.dumps runs in the executor while the loop
                # keeps mutating self._stats (record_song_result mutates
                # _stats["songs"] in place, record_game appends/deletes games),
                # so handing over a live reference would let json.dumps iterate
                # a dict that changes size — raising RuntimeError mid-serialize
                # and leaving the batch unwritten (#1762, regression from
                # #1708's debounce which makes the collision more likely). A
                # deepcopy is bounded (MAX_DETAILED_GAMES games) and costs a few
                # ms on the loop thread, cheaply buying the executor a stable,
                # immutable view. The expensive json.dumps AND the file write
                # still run together in the executor so neither blocks the loop
                # (#1402).
                stats_path = self._stats_file
                temp_path = stats_path.with_suffix(".json.tmp")
                snapshot = copy.deepcopy(self._stats)

                def _serialize_and_write() -> None:
                    content = json.dumps(snapshot, indent=2)
                    temp_path.write_text(content)
                    # Atomic rename (POSIX guarantees atomicity)
                    os.replace(temp_path, stats_path)

                await self._hass.async_add_executor_job(_serialize_and_write)
                _LOGGER.debug("Stats saved to %s", self._stats_file)
            except OSError as err:
                _LOGGER.error("Failed to save stats: %s", err)
            except (RuntimeError, ValueError) as err:
                # Defense-in-depth: the deepcopy above should already prevent a
                # "dictionary changed size during iteration" RuntimeError (and
                # any serialization ValueError), but if one still slips through
                # the batch is not on disk. Flag dirty so the done-callback path
                # (_handle_save_done) retries rather than silently dropping it
                # (#1762).
                _LOGGER.error("Failed to serialize stats, will retry: %s", err)
                self._save_dirty = True

    def schedule_save(self) -> None:
        """
        Schedule a debounced non-blocking save (#1708).

        record_song_result runs once per round (~30s). Writing the whole
        (growing) stats.json on every round hammers the disk and runs
        json.dumps of the full store in the event loop. Instead we coalesce:
        the save is deferred STATS_SAVE_DEBOUNCE_SECONDS into the future and any
        call arriving before the timer fires resets it, so a burst of rounds
        results in a single write. Game end (record_game) and unload
        (async_shutdown) flush explicitly so nothing is lost.
        """
        if self._save_handle is not None:
            self._save_handle.cancel()

        def _fire() -> None:
            self._save_handle = None
            self._schedule_save_now()

        self._save_handle = self._hass.loop.call_later(
            STATS_SAVE_DEBOUNCE_SECONDS, _fire
        )

    def _schedule_save_now(self) -> None:
        """
        Kick off an immediate non-blocking save (fire-and-forget).

        Coalesces rapid calls: if a save is already in flight, the call sets a
        dirty flag and the in-flight save's done-callback re-schedules a fresh
        save. Without this, the save task snapshots ``self._stats`` at the
        moment it runs and any mutation made AFTER that snapshot but before the
        task finishes would be silently dropped until the next unrelated save
        (#1402).
        """
        if self._save_task is not None and not self._save_task.done():
            self._save_dirty = True
            return
        self._save_dirty = False
        self._save_task = asyncio.create_task(self.save())
        self._save_task.add_done_callback(self._handle_save_done)

    async def async_flush(self) -> None:
        """
        Cancel any pending debounced save and persist immediately (#1708).

        Used on game end and unload so the last coalesced batch of per-round
        updates is written even though its debounce timer hasn't fired yet.
        Idempotent: a no-op beyond a harmless extra write if nothing is dirty.
        """
        if self._save_handle is not None:
            self._save_handle.cancel()
            self._save_handle = None
        await self.save()

    async def async_shutdown(self) -> None:
        """Flush pending stats on unload so debounced rounds aren't lost."""
        await self.async_flush()

    def _handle_save_done(self, task: asyncio.Task) -> None:
        """Log save-task errors and re-schedule if mutated mid-save (#1402)."""
        if (exc := task.exception()) is not None:
            _LOGGER.error("Unhandled error in stats save task: %s", exc)
        # A _schedule_save_now() arrived while this save was in flight — its
        # mutations may not be on disk yet, so kick off another immediate save.
        # (Use the non-debounced path: the data is already committed to being
        # written; don't restart a fresh debounce window, #1708.)
        if self._save_dirty:
            self._schedule_save_now()

    async def record_game(self, game_summary: dict, difficulty: str = "normal") -> dict:
        """
        Record completed game and return comparison data.

        Args:
            game_summary: Dict with playlist, rounds, player_count, winner,
                         winner_score, total_points
            difficulty: Game difficulty setting (Story 19.1)

        Returns:
            Comparison data dict for frontend display

        """
        # AC8: Don't record games with 0 players
        if game_summary.get("player_count", 0) == 0:
            _LOGGER.debug("Skipping stats recording for game with 0 players")
            return self.get_game_comparison(0.0)

        # Calculate average score per round
        rounds = game_summary.get("rounds", 1)
        player_count = game_summary.get("player_count", 1)
        total_points = game_summary.get("total_points", 0)

        # Avoid division by zero
        if rounds * player_count == 0:
            avg_score_per_round = 0.0
        else:
            avg_score_per_round = total_points / (rounds * player_count)

        # Create game entry
        game_id = str(uuid.uuid4())[:8]
        now = int(time.time())
        game_entry = {
            "id": game_id,
            "date": datetime.now(timezone.utc).isoformat(),
            "playlist": game_summary.get("playlist", "unknown"),
            "rounds": rounds,
            "player_count": player_count,
            "winner": game_summary.get("winner", "Unknown"),
            "winner_score": game_summary.get("winner_score", 0),
            "avg_score_per_round": round(avg_score_per_round, 2),
            "total_points": total_points,
        }

        # Record to analytics storage (Story 19.1 AC: #1)
        if self._analytics:
            started_at = self._game_start_time or now
            duration = now - started_at
            playlist_names = [game_summary.get("playlist", "unknown")]

            from custom_components.beatify.analytics import GameRecord  # noqa: PLC0415

            analytics_record: GameRecord = {
                "game_id": game_id,
                "started_at": started_at,
                "ended_at": now,
                "duration_seconds": duration,
                "player_count": player_count,
                "playlist_names": playlist_names,
                "rounds_played": rounds,
                "average_score": round(avg_score_per_round, 2),
                "difficulty": difficulty,
                "error_count": self._analytics.session_error_count,
                # Story 19.11: Streak achievements
                "streak_3_count": game_summary.get("streak_3_count", 0),
                "streak_5_count": game_summary.get("streak_5_count", 0),
                "streak_10_count": game_summary.get("streak_10_count", 0),
                # Story 19.12: Bet tracking
                "total_bets": game_summary.get("total_bets", 0),
                "bets_won": game_summary.get("bets_won", 0),
            }
            await self._analytics.add_game(analytics_record)
            self._game_start_time = None  # Reset for next game

        # Store comparison before updating stats
        comparison = self.get_game_comparison(avg_score_per_round)

        # Invalidate cached all-time average
        self._all_time_avg_cache = None

        # Add to games list
        self._stats["games"].append(game_entry)

        # Update playlist stats
        playlist_key = game_entry["playlist"]
        if playlist_key not in self._stats["playlists"]:
            self._stats["playlists"][playlist_key] = {
                "times_played": 0,
                "total_rounds": 0,
                "avg_score_per_round": 0.0,
                # Weighted score accumulators so avg_score_per_round can be
                # maintained instead of staying a permanent 0.0 (#1402).
                "total_weighted_score": 0.0,
                "total_weight": 0,
            }

        playlist_stats = self._stats["playlists"][playlist_key]
        playlist_stats["times_played"] += 1
        playlist_stats["total_rounds"] += rounds
        # Maintain avg_score_per_round as a rounds*players-weighted mean,
        # matching the all_time weighting (#1402).
        weight = rounds * player_count
        playlist_stats["total_weighted_score"] = (
            playlist_stats.get("total_weighted_score", 0.0)
            + avg_score_per_round * weight
        )
        playlist_stats["total_weight"] = playlist_stats.get("total_weight", 0) + weight
        if playlist_stats["total_weight"] > 0:
            playlist_stats["avg_score_per_round"] = round(
                playlist_stats["total_weighted_score"] / playlist_stats["total_weight"],
                2,
            )

        # Update all-time stats
        all_time = self._stats["all_time"]
        all_time["games_played"] += 1
        # Maintain the running weighted score sum that backs all_time_avg, so
        # the average is correct even after old games are folded out of the
        # detailed list by the cap below (#1402).
        all_time["total_weighted_score"] = (
            all_time.get("total_weighted_score", 0.0) + avg_score_per_round * weight
        )
        all_time["total_weight"] = all_time.get("total_weight", 0) + weight

        # Check for new high score
        if avg_score_per_round > all_time["highest_avg_score"]:
            all_time["highest_avg_score"] = round(avg_score_per_round, 2)
            all_time["highest_avg_game_id"] = game_id
            comparison["is_new_record"] = True

        # Cap the detailed games list: the running aggregates above already
        # capture every game's contribution, so older entries can be dropped to
        # bound file size and per-save json.dumps cost (#1402).
        games_list = self._stats["games"]
        if len(games_list) > MAX_DETAILED_GAMES:
            del games_list[:-MAX_DETAILED_GAMES]

        # Game end is a natural flush point: persist immediately (cancelling any
        # pending per-round debounce) so a completed game is never lost to a
        # crash/unload before the debounce timer fires (#1708).
        await self.async_flush()

        _LOGGER.info(
            "Recorded game %s: %.2f avg pts/round, %d players, %d rounds",
            game_id,
            avg_score_per_round,
            player_count,
            rounds,
        )

        return comparison

    def get_game_comparison(self, avg_score: float) -> dict:
        """
        Compare current game avg to all-time avg.

        Args:
            avg_score: Current game's average score per round

        Returns:
            Comparison dict with all relevant data

        """
        all_time = self._stats["all_time"]
        games_played = all_time["games_played"]
        all_time_avg = self.all_time_avg
        highest_avg = all_time["highest_avg_score"]

        is_first_game = games_played == 0
        is_new_record = not is_first_game and avg_score > highest_avg
        difference = avg_score - all_time_avg if not is_first_game else 0.0

        return {
            "avg_score": round(avg_score, 2),
            "all_time_avg": round(all_time_avg, 2),
            "difference": round(difference, 2),
            "is_new_record": is_new_record,
            "is_first_game": is_first_game,
            "is_above_average": difference > 0 if not is_first_game else False,
        }

    def get_motivational_message(self, comparison: dict) -> dict | None:
        """
        Generate motivational message based on performance.

        Args:
            comparison: Comparison dict from get_game_comparison

        Returns:
            Dict with type and message, or None for below average

        """
        if comparison.get("is_first_game"):
            return {"type": "first", "message": "First game! Setting the benchmark"}

        if comparison.get("is_new_record"):
            return {
                "type": "record",
                "message": "New Record! Highest scoring game ever!",
            }

        diff = comparison.get("difference", 0)
        if diff > 5:
            return {
                "type": "strong",
                "message": f"Excellent! {diff:.1f} pts above average",
            }
        if diff > 0:
            return {
                "type": "above",
                "message": f"Strong game! {diff:.1f} pts above average",
            }
        if diff > -5:
            return {
                "type": "close",
                "message": f"Close to average! Just {abs(diff):.1f} pts below",
            }

        # No message for significantly below average
        return None

    @property
    def all_time_avg(self) -> float:
        """
        Get all-time weighted average score per round.

        Returns:
            Weighted average across all games, or 0.0 if no games

        """
        if self._all_time_avg_cache is not None:
            return self._all_time_avg_cache

        all_time = self._stats.get("all_time", {})
        # Prefer the maintained running aggregates: the detailed games list is
        # capped (#1402) so it no longer represents full history, but the
        # all_time weighted sums do. Fall back to recomputing from the games
        # list for legacy stats files written before these fields existed.
        stored_weight = all_time.get("total_weight", 0)
        if stored_weight:
            result = all_time.get("total_weighted_score", 0.0) / stored_weight
            self._all_time_avg_cache = result
            return result

        games = self._stats.get("games", [])
        if not games:
            return 0.0

        # Weighted average by rounds * players
        total_weighted = 0.0
        total_weight = 0

        for game in games:
            weight = game.get("rounds", 1) * game.get("player_count", 1)
            avg = game.get("avg_score_per_round", 0.0)
            total_weighted += avg * weight
            total_weight += weight

        if total_weight == 0:
            return 0.0

        result = total_weighted / total_weight
        self._all_time_avg_cache = result
        return result

    @property
    def games_played(self) -> int:
        """Get total games played."""
        return self._stats.get("all_time", {}).get("games_played", 0)

    async def get_summary(self) -> dict:
        """Get stats summary for admin UI."""
        all_time = self._stats.get("all_time", {})
        return {
            "games_played": all_time.get("games_played", 0),
            "highest_avg_score": all_time.get("highest_avg_score", 0.0),
            "all_time_avg": round(self.all_time_avg, 2),
        }

    async def get_history(self, limit: int = 10) -> list[dict]:
        """
        Get recent game history.

        Args:
            limit: Maximum number of games to return

        Returns:
            List of recent game entries, newest first

        """
        games = self._stats.get("games", [])
        # Return newest first
        return list(reversed(games[-limit:]))

    # Song difficulty tracking methods (Story 15.1)
    # Extended for song statistics (Story 19.7)

    def _uri_to_key(self, uri: str) -> str:
        """
        Convert song URI to safe dictionary key.

        Args:
            uri: Song URI (e.g., "spotify:track:4iV5W9uYEdYUVa79Axb7Rh")

        Returns:
            Safe key string (e.g., "spotify_track_4iV5W9uYEdYUVa79Axb7Rh")

        """
        return uri.replace(":", "_").replace("/", "_")

    async def record_song_result(
        self,
        song_uri: str,
        player_results: list[dict],
        song_metadata: dict | None = None,
        playlist_name: str | None = None,
        difficulty: str = "normal",
    ) -> None:
        """
        Record song results from a completed round (Story 15.1 AC3, Story 19.7).

        A guess is considered "correct" for difficulty purposes when years_off <= 3.
        Extended to track song metadata for analytics dashboard.

        Args:
            song_uri: URI of the song that was played
            player_results: List of player result dicts with 'submitted', 'years_off'
            song_metadata: Optional dict with title, artist, year (Story 19.7)
            playlist_name: Optional playlist name for per-playlist stats (Story 19.7)
            difficulty: Game difficulty setting for accuracy calculation (Story 19.7)

        """
        from custom_components.beatify.const import (  # noqa: PLC0415
            CORRECT_GUESS_THRESHOLD,
            DIFFICULTY_SCORING,
        )

        song_key = self._uri_to_key(song_uri)

        # Ensure songs dict exists (for legacy stats files)
        if "songs" not in self._stats:
            self._stats["songs"] = {}

        # Initialize song entry if not exists
        if song_key not in self._stats["songs"]:
            self._stats["songs"][song_key] = {
                "times_played": 0,
                "correct_guesses": 0,
                "total_guesses": 0,
                "total_years_off": 0,
                # Story 19.7: Extended tracking
                "exact_matches": 0,
                "close_matches": 0,
                "title": "",
                "artist": "",
                "year": 0,
                "playlists": {},  # playlist_name -> play_count
                "last_played": 0,
            }

        song = self._stats["songs"][song_key]
        song["times_played"] += 1
        song["last_played"] = int(time.time())

        # Update metadata if provided (Story 19.7)
        if song_metadata:
            song["title"] = song_metadata.get("title", song.get("title", ""))
            song["artist"] = song_metadata.get("artist", song.get("artist", ""))
            song["year"] = song_metadata.get("year", song.get("year", 0))

        # Track per-playlist plays (Story 19.7)
        if playlist_name:
            playlists = song.get("playlists", {})
            playlists[playlist_name] = playlists.get(playlist_name, 0) + 1
            song["playlists"] = playlists

        # Get difficulty tolerance for close matches (Story 19.7 AC5)
        scoring = DIFFICULTY_SCORING.get(difficulty, DIFFICULTY_SCORING["normal"])
        close_range = scoring.get("close_range", 3)

        # Process player results
        for result in player_results:
            if result.get("submitted"):
                song["total_guesses"] += 1
                years_off = result.get("years_off", 0)
                song["total_years_off"] += years_off

                # Exact match (Story 19.7 AC5)
                if years_off == 0:
                    song["exact_matches"] = song.get("exact_matches", 0) + 1
                    song["correct_guesses"] += 1
                # Close match - within difficulty tolerance (Story 19.7 AC5)
                elif years_off <= close_range:
                    song["close_matches"] = song.get("close_matches", 0) + 1
                    song["correct_guesses"] += 1
                elif years_off <= CORRECT_GUESS_THRESHOLD:
                    song["correct_guesses"] += 1

        # Schedule deferred save (non-blocking)
        self.schedule_save()

        _LOGGER.debug(
            "Recorded song result for %s: %d guesses, %d correct",
            song_key,
            song["total_guesses"],
            song["correct_guesses"],
        )

    def get_song_difficulty(self, song_uri: str) -> dict[str, Any] | None:
        """
        Calculate difficulty rating for a song (Story 15.1 AC1, AC2, AC4).

        Args:
            song_uri: URI of the song

        Returns:
            Dict with stars, label, accuracy, times_played, or None if insufficient data

        """
        from custom_components.beatify.const import (  # noqa: PLC0415
            DIFFICULTY_LABELS,
            DIFFICULTY_THRESHOLDS,
            MIN_PLAYS_FOR_DIFFICULTY,
        )

        song_key = self._uri_to_key(song_uri)
        songs = self._stats.get("songs", {})
        song_stats = songs.get(song_key)

        # Not enough data (AC4)
        if (
            not song_stats
            or song_stats.get("times_played", 0) < MIN_PLAYS_FOR_DIFFICULTY
        ):
            return None

        # Guard against division by zero
        if song_stats.get("total_guesses", 0) == 0:
            return None

        # Calculate accuracy percentage
        accuracy = (song_stats["correct_guesses"] / song_stats["total_guesses"]) * 100

        # Map accuracy to stars (AC2)
        # Higher accuracy = easier song = fewer stars
        stars = 4  # Default to extreme
        for star_level, threshold in sorted(DIFFICULTY_THRESHOLDS.items()):
            if accuracy >= threshold:
                stars = star_level
                break

        return {
            "stars": stars,
            "label": DIFFICULTY_LABELS[stars],
            "accuracy": round(accuracy, 1),
            "times_played": song_stats["times_played"],
        }

    def compute_song_stats(self, playlist_filter: str | None = None) -> dict[str, Any]:
        """
        Compute song statistics for analytics dashboard (Story 19.7 AC3).

        Args:
            playlist_filter: Optional playlist ID to filter by

        Returns:
            Dict with most_played, hardest, easiest, and by_playlist data

        """
        songs = self._stats.get("songs", {})

        if not songs:
            return {
                "most_played": None,
                "hardest": None,
                "easiest": None,
                "by_playlist": [],
            }

        # Build list of songs with computed stats
        song_list: list[dict[str, Any]] = []
        for uri_key, song_data in songs.items():
            # Skip songs with no plays
            if song_data.get("times_played", 0) == 0:
                continue

            # Skip songs without metadata (legacy entries)
            if not song_data.get("title"):
                continue

            total_guesses = song_data.get("total_guesses", 0)
            if total_guesses == 0:
                continue

            # Calculate accuracy (Story 19.7 AC5)
            exact = song_data.get("exact_matches", 0)
            close = song_data.get("close_matches", 0)
            # Accuracy = (exact * 1.0 + close * 0.5) / total_guesses
            accuracy = (exact * 1.0 + close * 0.5) / total_guesses

            # Calculate average year difference
            avg_year_diff = song_data.get("total_years_off", 0) / total_guesses

            song_list.append(
                {
                    "uri_key": uri_key,
                    "title": song_data.get("title", "Unknown"),
                    "artist": song_data.get("artist", "Unknown"),
                    "year": song_data.get("year", 0),
                    "play_count": song_data.get("times_played", 0),
                    "accuracy": round(accuracy, 2),
                    "avg_year_diff": round(avg_year_diff, 1),
                    "exact_matches": exact,
                    "total_guesses": total_guesses,
                    "last_played": song_data.get("last_played", 0),
                    "playlists": song_data.get("playlists", {}),
                }
            )

        if not song_list:
            return {
                "most_played": None,
                "hardest": None,
                "easiest": None,
                "by_playlist": [],
            }

        # Find most played (AC3)
        most_played = max(song_list, key=lambda s: s["play_count"])

        # Story 19.10: Dynamic threshold for hardest/easiest songs
        # Use min(max_play_count, 3) to always show data when possible
        max_play_count = max(s["play_count"] for s in song_list)
        min_plays_threshold = min(max_play_count, 3)

        # Find hardest song - lowest accuracy with dynamic threshold
        songs_with_enough_plays = [
            s for s in song_list if s["play_count"] >= min_plays_threshold
        ]

        hardest = None
        easiest = None
        if songs_with_enough_plays:
            hardest = min(songs_with_enough_plays, key=lambda s: s["accuracy"])
            easiest = max(songs_with_enough_plays, key=lambda s: s["accuracy"])

        # Build by_playlist data (AC3)
        playlist_stats: dict[str, dict[str, Any]] = {}

        for song in song_list:
            for playlist_name, play_count in song.get("playlists", {}).items():
                if playlist_name not in playlist_stats:
                    playlist_stats[playlist_name] = {
                        "playlist_id": playlist_name.lower().replace(" ", "-"),
                        "playlist_name": playlist_name,
                        "total_plays": 0,
                        "unique_songs_played": 0,
                        "total_accuracy": 0.0,
                        "accuracy_count": 0,
                        "songs": [],
                    }

                ps = playlist_stats[playlist_name]
                ps["total_plays"] += play_count
                ps["unique_songs_played"] += 1
                ps["total_accuracy"] += song["accuracy"] * play_count
                ps["accuracy_count"] += play_count

                ps["songs"].append(
                    {
                        "title": song["title"],
                        "artist": song["artist"],
                        "year": song["year"],
                        "play_count": play_count,
                        "accuracy": song["accuracy"],
                        "avg_year_diff": song["avg_year_diff"],
                        "exact_matches": song["exact_matches"],
                        "last_played": song["last_played"],
                    }
                )

        # Calculate average accuracy per playlist and sort songs
        by_playlist = []
        for ps in playlist_stats.values():
            if ps["accuracy_count"] > 0:
                ps["avg_accuracy"] = round(
                    ps["total_accuracy"] / ps["accuracy_count"], 2
                )
            else:
                ps["avg_accuracy"] = 0.0

            # Sort songs by play_count descending
            ps["songs"].sort(key=lambda s: s["play_count"], reverse=True)

            # Remove internal tracking fields
            del ps["total_accuracy"]
            del ps["accuracy_count"]

            by_playlist.append(ps)

        # Sort playlists by total_plays descending
        by_playlist.sort(key=lambda p: p["total_plays"], reverse=True)

        # Apply playlist filter if specified
        if playlist_filter:
            by_playlist = [
                p for p in by_playlist if p["playlist_id"] == playlist_filter
            ]

        def _format_song(s: dict) -> dict | None:
            """Format song for API response."""
            if not s:
                return None
            # Find primary playlist for this song
            playlists = s.get("playlists", {})
            primary_playlist = (
                max(playlists.keys(), key=lambda k: playlists[k]) if playlists else ""
            )
            return {
                "title": s["title"],
                "artist": s["artist"],
                "year": s["year"],
                "play_count": s["play_count"],
                "accuracy": s["accuracy"],
                "avg_year_diff": s["avg_year_diff"],
                "playlist": primary_playlist,
            }

        return {
            "most_played": _format_song(most_played),
            "hardest": _format_song(hardest),
            "easiest": _format_song(easiest),
            "by_playlist": by_playlist,
        }
