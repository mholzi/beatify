"""Game statistics tracking service for Beatify."""

from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from custom_components.beatify.analytics import AnalyticsStorage

_LOGGER = logging.getLogger(__name__)


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
            },
            "songs": {},  # Song difficulty tracking (Story 15.1)
        }

    async def load(self) -> None:
        """Load stats from file or create empty structure."""
        try:
            if self._stats_file.exists():
                content = await self._hass.async_add_executor_job(self._stats_file.read_text)
                self._stats = json.loads(content)
                _LOGGER.debug(
                    "Loaded stats: %d games played",
                    self._stats.get("all_time", {}).get("games_played", 0),
                )
            else:
                _LOGGER.debug("No stats file found, starting fresh")
                self._stats = self._empty_stats()
        except (json.JSONDecodeError, KeyError, TypeError) as err:
            _LOGGER.warning("Stats file corrupted, recreating: %s", err)
            self._stats = self._empty_stats()
            await self.save()

    async def save(self) -> None:
        """Persist stats to file."""
        try:
            # Ensure directory exists
            await self._hass.async_add_executor_job(
                self._stats_file.parent.mkdir, 0o755, True, True
            )
            # Write stats
            content = json.dumps(self._stats, indent=2)
            await self._hass.async_add_executor_job(self._stats_file.write_text, content)
            _LOGGER.debug("Stats saved to %s", self._stats_file)
        except OSError as err:
            _LOGGER.error("Failed to save stats: %s", err)

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
                "streak_7_count": game_summary.get("streak_7_count", 0),
                # Story 19.12: Bet tracking
                "total_bets": game_summary.get("total_bets", 0),
                "bets_won": game_summary.get("bets_won", 0),
            }
            await self._analytics.add_game(analytics_record)
            self._game_start_time = None  # Reset for next game

        # Store comparison before updating stats
        comparison = self.get_game_comparison(avg_score_per_round)

        # Add to games list
        self._stats["games"].append(game_entry)

        # Update playlist stats
        playlist_key = game_entry["playlist"]
        if playlist_key not in self._stats["playlists"]:
            self._stats["playlists"][playlist_key] = {
                "times_played": 0,
                "total_rounds": 0,
                "avg_score_per_round": 0.0,
            }

        playlist_stats = self._stats["playlists"][playlist_key]
        playlist_stats["times_played"] += 1
        playlist_stats["total_rounds"] += rounds

        # Update all-time stats
        all_time = self._stats["all_time"]
        all_time["games_played"] += 1

        # Check for new high score
        if avg_score_per_round > all_time["highest_avg_score"]:
            all_time["highest_avg_score"] = round(avg_score_per_round, 2)
            all_time["highest_avg_game_id"] = game_id
            comparison["is_new_record"] = True

        # Save to file
        await self.save()

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

        return total_weighted / total_weight

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

        # Save to file
        await self.save()

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
        if not song_stats or song_stats.get("times_played", 0) < MIN_PLAYS_FOR_DIFFICULTY:
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
        songs_with_enough_plays = [s for s in song_list if s["play_count"] >= min_plays_threshold]

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
                ps["avg_accuracy"] = round(ps["total_accuracy"] / ps["accuracy_count"], 2)
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
            by_playlist = [p for p in by_playlist if p["playlist_id"] == playlist_filter]

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
