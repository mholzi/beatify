"""Analytics data collection and storage for Beatify (Story 19.1).

Provides persistent storage for game metrics and error events,
enabling historical analysis through the analytics dashboard.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Data retention constants (AC: #5)
MAX_DETAILED_RECORDS = 1000
RETENTION_DAYS = 90
PRUNE_INTERVAL = 10  # Prune every N game records


class GameRecord(TypedDict):
    """Game record schema (AC: #1)."""

    game_id: str
    started_at: int  # Unix timestamp
    ended_at: int  # Unix timestamp
    duration_seconds: int
    player_count: int
    playlist_names: list[str]
    rounds_played: int
    average_score: float
    difficulty: str
    error_count: int
    # Story 19.11: Streak achievements
    streak_3_count: int  # Number of 3+ streaks achieved
    streak_5_count: int  # Number of 5+ streaks achieved
    streak_7_count: int  # Number of 7+ streaks achieved
    # Story 19.12: Bet tracking
    total_bets: int  # Total bets placed in game
    bets_won: int  # Bets that won (doubled points)


class ErrorEvent(TypedDict):
    """Error event schema (AC: #2)."""

    timestamp: int  # Unix timestamp
    type: str  # Error type constant
    message: str


class MonthlySummary(TypedDict):
    """Monthly aggregate summary for old data."""

    month: str  # "YYYY-MM" format
    games_count: int
    total_players: int
    avg_players_per_game: float
    total_rounds: int
    avg_rounds_per_game: float
    error_rate: float


class AnalyticsData(TypedDict):
    """Complete analytics data schema."""

    version: int
    games: list[GameRecord]
    errors: list[ErrorEvent]
    monthly_summaries: list[MonthlySummary]


class AnalyticsStorage:
    """
    Analytics storage with async file I/O and atomic writes.

    Stores analytics data in {HA_CONFIG}/beatify/analytics.json with
    crash-safe atomic writes and non-blocking persistence (AC: #3, #4).
    """

    def __init__(self, hass: HomeAssistant) -> None:
        """
        Initialize analytics storage.

        Args:
            hass: Home Assistant instance

        """
        self._hass = hass
        self._path = Path(hass.config.path("beatify", "analytics.json"))
        self._data: AnalyticsData = self._empty_data()
        self._games_since_prune = 0
        self._session_error_count = 0
        self._save_lock = asyncio.Lock()
        self._playlist_display_names: dict[str, str] | None = None

    def _empty_data(self) -> AnalyticsData:
        """Return empty analytics data structure."""
        return {
            "version": 1,
            "games": [],
            "errors": [],
            "monthly_summaries": [],
        }

    async def load(self) -> None:
        """Load analytics data from file (AC: #3)."""
        try:
            if self._path.exists():
                content = await self._hass.async_add_executor_job(
                    self._path.read_text
                )
                self._data = json.loads(content)
                _LOGGER.debug(
                    "Loaded analytics: %d games, %d errors",
                    len(self._data.get("games", [])),
                    len(self._data.get("errors", [])),
                )
                # Prune old records on startup
                await self._prune_old_records()
            else:
                _LOGGER.debug("No analytics file found, starting fresh")
                self._data = self._empty_data()
        except (json.JSONDecodeError, KeyError, TypeError) as err:
            _LOGGER.warning("Analytics file corrupted, recreating: %s", err)
            self._data = self._empty_data()
            await self._save()

    async def _save(self) -> None:
        """
        Persist analytics data with atomic write (AC: #3).

        Uses temp file + rename for crash safety.
        """
        async with self._save_lock:
            try:
                # Ensure directory exists
                await self._hass.async_add_executor_job(
                    self._path.parent.mkdir, 0o755, True, True
                )

                # Write to temp file first (atomic write pattern)
                temp_path = self._path.with_suffix(".tmp")
                content = json.dumps(self._data, indent=2)

                def _write_atomic() -> None:
                    temp_path.write_text(content)
                    # Atomic rename (POSIX guarantees atomicity)
                    os.replace(temp_path, self._path)

                await self._hass.async_add_executor_job(_write_atomic)
                _LOGGER.debug("Analytics saved to %s", self._path)

            except OSError as err:
                _LOGGER.error("Failed to save analytics: %s", err)

    def schedule_save(self) -> None:
        """
        Schedule non-blocking save (AC: #4).

        Uses fire-and-forget pattern to avoid blocking game operations.
        """
        asyncio.create_task(self._save())

    async def add_game(self, record: GameRecord) -> None:
        """
        Add game record and schedule save (AC: #1).

        Args:
            record: Game record to store

        """
        self._data["games"].append(record)
        self._games_since_prune += 1

        # Prune periodically
        if self._games_since_prune >= PRUNE_INTERVAL:
            await self._prune_old_records()
            self._games_since_prune = 0

        self.schedule_save()

        _LOGGER.info(
            "Recorded analytics for game %s: %d players, %d rounds",
            record["game_id"],
            record["player_count"],
            record["rounds_played"],
        )

    def record_error(self, error_type: str, message: str) -> None:
        """
        Record error event (AC: #2).

        Args:
            error_type: Error type constant (e.g., WEBSOCKET_DISCONNECT)
            message: Human-readable error message

        """
        event: ErrorEvent = {
            "timestamp": int(time.time()),
            "type": error_type,
            "message": message[:500],  # Limit message length
        }
        self._data["errors"].append(event)
        self._session_error_count += 1
        self.schedule_save()

        _LOGGER.debug("Recorded error event: %s - %s", error_type, message)

    @property
    def session_error_count(self) -> int:
        """Get error count for current session."""
        return self._session_error_count

    def reset_session_errors(self) -> None:
        """Reset session error counter (called at game start)."""
        self._session_error_count = 0

    async def _prune_old_records(self) -> None:
        """
        Prune old records and create monthly summaries (AC: #5).

        Keeps last 90 days detailed, summarizes older records.
        """
        now = time.time()
        cutoff = now - (RETENTION_DAYS * 24 * 60 * 60)

        games = self._data["games"]
        if len(games) <= MAX_DETAILED_RECORDS:
            return

        # Separate old and recent games
        old_games: list[GameRecord] = []
        recent_games: list[GameRecord] = []

        for game in games:
            if game["ended_at"] < cutoff:
                old_games.append(game)
            else:
                recent_games.append(game)

        if not old_games:
            return

        # Group old games by month and create summaries
        monthly_groups: dict[str, list[GameRecord]] = {}
        for game in old_games:
            dt = datetime.fromtimestamp(game["ended_at"], tz=timezone.utc)
            month_key = dt.strftime("%Y-%m")
            if month_key not in monthly_groups:
                monthly_groups[month_key] = []
            monthly_groups[month_key].append(game)

        # Create monthly summaries
        for month, month_games in monthly_groups.items():
            # Check if summary already exists
            existing = next(
                (s for s in self._data["monthly_summaries"] if s["month"] == month),
                None,
            )
            if existing:
                # Update existing summary
                existing["games_count"] += len(month_games)
                existing["total_players"] += sum(g["player_count"] for g in month_games)
                existing["total_rounds"] += sum(g["rounds_played"] for g in month_games)
                # Recalculate averages
                if existing["games_count"] > 0:
                    existing["avg_players_per_game"] = round(
                        existing["total_players"] / existing["games_count"], 2
                    )
                    existing["avg_rounds_per_game"] = round(
                        existing["total_rounds"] / existing["games_count"], 2
                    )
            else:
                # Create new summary
                total_players = sum(g["player_count"] for g in month_games)
                total_rounds = sum(g["rounds_played"] for g in month_games)
                total_errors = sum(g["error_count"] for g in month_games)
                games_count = len(month_games)

                summary: MonthlySummary = {
                    "month": month,
                    "games_count": games_count,
                    "total_players": total_players,
                    "avg_players_per_game": round(total_players / games_count, 2),
                    "total_rounds": total_rounds,
                    "avg_rounds_per_game": round(total_rounds / games_count, 2),
                    "error_rate": round(total_errors / games_count, 2),
                }
                self._data["monthly_summaries"].append(summary)

        # Keep only recent games
        self._data["games"] = recent_games

        # Also prune old errors (keep last 90 days)
        self._data["errors"] = [
            e for e in self._data["errors"] if e["timestamp"] >= cutoff
        ]

        _LOGGER.info(
            "Pruned %d old games into %d monthly summaries",
            len(old_games),
            len(monthly_groups),
        )

    def get_games(
        self, start_date: int | None = None, end_date: int | None = None
    ) -> list[GameRecord]:
        """
        Get game records filtered by date range.

        Args:
            start_date: Unix timestamp for start (inclusive)
            end_date: Unix timestamp for end (inclusive)

        Returns:
            Filtered list of game records

        """
        games = self._data["games"]

        if start_date is not None:
            games = [g for g in games if g["ended_at"] >= start_date]
        if end_date is not None:
            games = [g for g in games if g["ended_at"] <= end_date]

        return games

    def get_errors(
        self, start_date: int | None = None, end_date: int | None = None
    ) -> list[ErrorEvent]:
        """
        Get error events filtered by date range.

        Args:
            start_date: Unix timestamp for start (inclusive)
            end_date: Unix timestamp for end (inclusive)

        Returns:
            Filtered list of error events

        """
        errors = self._data["errors"]

        if start_date is not None:
            errors = [e for e in errors if e["timestamp"] >= start_date]
        if end_date is not None:
            errors = [e for e in errors if e["timestamp"] <= end_date]

        return errors

    def get_monthly_summaries(self) -> list[MonthlySummary]:
        """Get all monthly summaries."""
        return self._data["monthly_summaries"]

    @property
    def total_games(self) -> int:
        """Get total games recorded (detailed + summarized)."""
        detailed = len(self._data["games"])
        summarized = sum(s["games_count"] for s in self._data["monthly_summaries"])
        return detailed + summarized

    @property
    def total_errors(self) -> int:
        """Get total errors recorded."""
        return len(self._data["errors"])

    def _get_playlist_display_names(self) -> dict[str, str]:
        """
        Load playlist display names from JSON files.

        Returns:
            Dict mapping slug (e.g., 'greatest-hits-of-all-time') to display name
            (e.g., 'Greatest Hits of All Time')
        """
        if self._playlist_display_names is not None:
            return self._playlist_display_names

        display_names: dict[str, str] = {}
        playlist_dir = Path(self._hass.config.path("custom_components/beatify/playlists"))

        if not playlist_dir.exists():
            _LOGGER.debug("Playlist directory not found: %s", playlist_dir)
            return display_names

        for json_file in playlist_dir.glob("*.json"):
            try:
                data = json.loads(json_file.read_text(encoding="utf-8"))
                slug = json_file.stem  # filename without .json
                if "name" in data:
                    display_names[slug] = data["name"]
                else:
                    display_names[slug] = slug  # fallback to slug
            except (json.JSONDecodeError, OSError) as err:
                _LOGGER.warning("Failed to read playlist %s: %s", json_file, err)

        self._playlist_display_names = display_names
        _LOGGER.debug("Loaded %d playlist display names", len(display_names))
        return display_names

    def compute_playlist_stats(
        self, games: list[GameRecord]
    ) -> list[dict[str, Any]]:
        """
        Aggregate playlist play counts from game records (Story 19.4).

        Args:
            games: List of game records to aggregate

        Returns:
            Top 5 playlists with name, play_count, percentage

        """
        playlist_counts: dict[str, int] = {}

        for game in games:
            for playlist_name in game.get("playlist_names", []):
                playlist_counts[playlist_name] = playlist_counts.get(playlist_name, 0) + 1

        # Sort by count descending
        sorted_playlists = sorted(
            playlist_counts.items(),
            key=lambda x: (-x[1], x[0]),  # Count desc, then name asc for ties
        )[:5]  # Top 5

        # Calculate percentage relative to total games with playlists
        total = sum(count for _, count in sorted_playlists)

        # Get display names mapping
        display_names = self._get_playlist_display_names()

        return [
            {
                "name": display_names.get(slug, slug),  # Use display name or fallback to slug
                "play_count": count,
                "percentage": round(count / total * 100, 1) if total > 0 else 0,
            }
            for slug, count in sorted_playlists
        ]

    def compute_games_over_time(
        self, games: list[GameRecord], period: str
    ) -> dict[str, Any]:
        """
        Aggregate game counts for chart visualization (Story 19.5).

        Args:
            games: List of game records
            period: Time period for granularity

        Returns:
            Chart data with labels, values, and granularity

        """
        from datetime import timedelta  # noqa: PLC0415

        now = datetime.now(timezone.utc)

        if period == "7d":
            # Daily aggregation
            days = 7
            granularity = "day"
            buckets = {(now - timedelta(days=i)).strftime("%Y-%m-%d"): 0 for i in range(days)}

            for game in games:
                dt = datetime.fromtimestamp(game["ended_at"], tz=timezone.utc)
                key = dt.strftime("%Y-%m-%d")
                if key in buckets:
                    buckets[key] += 1

            labels = [(now - timedelta(days=i)).strftime("%a") for i in range(days - 1, -1, -1)]
            values = [buckets[(now - timedelta(days=i)).strftime("%Y-%m-%d")] for i in range(days - 1, -1, -1)]

        elif period in ("30d", "90d"):
            # Weekly aggregation
            weeks = 4 if period == "30d" else 13
            granularity = "week"
            week_buckets: dict[str, int] = {}

            for i in range(weeks):
                week_start = now - timedelta(days=now.weekday() + 7 * i)
                week_buckets[week_start.strftime("%Y-%m-%d")] = 0

            for game in games:
                dt = datetime.fromtimestamp(game["ended_at"], tz=timezone.utc)
                week_start = dt - timedelta(days=dt.weekday())
                key = week_start.strftime("%Y-%m-%d")
                if key in week_buckets:
                    week_buckets[key] += 1

            sorted_keys = sorted(week_buckets.keys())
            labels = [f"W{i + 1}" for i in range(len(sorted_keys))]
            values = [week_buckets[k] for k in sorted_keys]

        else:  # "all"
            # Monthly aggregation
            granularity = "month"
            month_buckets: dict[str, int] = {}

            for game in games:
                dt = datetime.fromtimestamp(game["ended_at"], tz=timezone.utc)
                key = dt.strftime("%Y-%m")
                month_buckets[key] = month_buckets.get(key, 0) + 1

            sorted_keys = sorted(month_buckets.keys())[-12:]  # Last 12 months
            labels = [datetime.strptime(k, "%Y-%m").strftime("%b") for k in sorted_keys] if sorted_keys else []
            values = [month_buckets[k] for k in sorted_keys] if sorted_keys else []

        return {"labels": labels, "values": values, "granularity": granularity}

    def compute_error_stats(
        self, games: list[GameRecord], errors: list[ErrorEvent], period: str
    ) -> dict[str, Any]:
        """
        Compute error statistics for the given period (Story 19.6).

        Args:
            games: List of game records
            errors: List of error events
            period: Time period

        Returns:
            Error stats with rate, count, status, and recent errors

        """
        now = int(time.time())

        # Calculate period boundaries
        days_map = {"7d": 7, "30d": 30, "90d": 90, "all": 365 * 10}
        days = days_map.get(period, 30)
        start_ts = now - (days * 86400)

        # Filter errors by period
        period_errors = [e for e in errors if e["timestamp"] >= start_ts]

        # Calculate total events (games * avg rounds as rough estimate)
        total_events = sum(g.get("rounds_played", 10) for g in games)

        error_count = len(period_errors)
        error_rate = error_count / total_events if total_events > 0 else 0

        # Determine status
        if error_rate < 0.01:
            status = "healthy"
        elif error_rate < 0.05:
            status = "warning"
        else:
            status = "critical"

        # Recent errors (last 10)
        recent_errors = sorted(period_errors, key=lambda e: e["timestamp"], reverse=True)[:10]

        return {
            "error_rate": round(error_rate, 4),
            "error_count": error_count,
            "total_events": total_events,
            "status": status,
            "recent_errors": recent_errors,
        }

    def compute_metrics(
        self, period: str = "30d"
    ) -> dict[str, Any]:
        """
        Compute dashboard metrics for a given period (Story 19.2).

        Args:
            period: Time period - "7d", "30d", "90d", or "all"

        Returns:
            Dict with computed metrics and trend data

        """
        now = int(time.time())

        # Calculate period boundaries
        days_map = {"7d": 7, "30d": 30, "90d": 90, "all": 365 * 10}
        days = days_map.get(period, 30)

        current_start = now - (days * 86400)
        previous_start = current_start - (days * 86400)

        # Get games for current and previous periods
        current_games = self.get_games(start_date=current_start, end_date=now)
        previous_games = self.get_games(start_date=previous_start, end_date=current_start - 1)

        # Get errors for current period
        current_errors = self.get_errors(start_date=current_start, end_date=now)

        # Compute current period metrics
        total_games = len(current_games)
        total_players = sum(g["player_count"] for g in current_games)
        total_rounds = sum(g["rounds_played"] for g in current_games)
        total_score = sum(g["average_score"] * g["player_count"] for g in current_games)
        total_errors = len(current_errors)

        avg_players = total_players / total_games if total_games > 0 else 0
        avg_score = total_score / total_players if total_players > 0 else 0
        # Error rate = errors per round (should be a small decimal, e.g., 0.05 = 5%)
        error_rate = total_errors / total_rounds if total_rounds > 0 else 0

        # Story 19.9: Calculate average rounds per game
        avg_rounds = total_rounds / total_games if total_games > 0 else 0

        # Compute previous period metrics for trends
        prev_total_games = len(previous_games)
        prev_total_players = sum(g["player_count"] for g in previous_games)
        prev_total_rounds = sum(g["rounds_played"] for g in previous_games)
        prev_total_score = sum(g["average_score"] * g["player_count"] for g in previous_games)
        prev_errors = self.get_errors(start_date=previous_start, end_date=current_start - 1)
        prev_total_errors = len(prev_errors)

        prev_avg_players = prev_total_players / prev_total_games if prev_total_games > 0 else 0
        prev_avg_score = prev_total_score / prev_total_players if prev_total_players > 0 else 0
        prev_error_rate = prev_total_errors / prev_total_rounds if prev_total_rounds > 0 else 0

        # Story 19.9: Calculate previous period average rounds
        prev_avg_rounds = prev_total_rounds / prev_total_games if prev_total_games > 0 else 0

        # Calculate trends (percentage change)
        def calc_trend(current: float, previous: float) -> float:
            if previous == 0:
                return 1.0 if current > 0 else 0.0
            return (current - previous) / previous

        # Compute additional data for dashboard sections
        playlists = self.compute_playlist_stats(current_games)
        chart_data = self.compute_games_over_time(current_games, period)
        error_stats = self.compute_error_stats(
            current_games, self._data["errors"], period
        )

        # Story 19.8: Calculate peak concurrent players
        peak_players = max(
            (g["player_count"] for g in current_games),
            default=0
        )

        return {
            "period": period,
            "total_games": total_games,
            "avg_players_per_game": round(avg_players, 1),
            "avg_score": round(avg_score, 1),
            "error_rate": round(error_rate, 3),
            "peak_players": peak_players,
            "avg_rounds": round(avg_rounds, 1),  # Story 19.9
            # Story 19.11: Include streak stats
            "streak_stats": self.compute_streak_stats(period),
            # Story 19.12: Include bet stats
            "bet_stats": self.compute_bet_stats(period),
            "trends": {
                "games": round(calc_trend(total_games, prev_total_games), 2),
                "players": round(calc_trend(avg_players, prev_avg_players), 2),
                "score": round(calc_trend(avg_score, prev_avg_score), 2),
                "errors": round(calc_trend(error_rate, prev_error_rate), 2),
                "rounds": round(calc_trend(avg_rounds, prev_avg_rounds), 2),  # Story 19.9
            },
            "playlists": playlists,
            "chart_data": chart_data,
            "error_stats": error_stats,
            "generated_at": now,
        }

    def compute_streak_stats(
        self, period: str = "30d"
    ) -> dict[str, Any]:
        """
        Compute streak achievement statistics for a given period (Story 19.11).

        Args:
            period: Time period - "7d", "30d", "90d", or "all"

        Returns:
            Dict with streak counts and distribution
        """
        now = int(time.time())

        # Calculate period boundaries
        days_map = {"7d": 7, "30d": 30, "90d": 90, "all": 365 * 10}
        days = days_map.get(period, 30)
        start_ts = now - (days * 86400)

        # Get games for current period
        games = self.get_games(start_date=start_ts, end_date=now)

        # Sum streak achievements across all games
        streak_3_total = sum(g.get("streak_3_count", 0) for g in games)
        streak_5_total = sum(g.get("streak_5_count", 0) for g in games)
        streak_7_total = sum(g.get("streak_7_count", 0) for g in games)

        total_streaks = streak_3_total + streak_5_total + streak_7_total

        return {
            "streak_3_count": streak_3_total,
            "streak_5_count": streak_5_total,
            "streak_7_count": streak_7_total,
            "total_streaks": total_streaks,
            "has_data": total_streaks > 0,
        }

    def compute_bet_stats(
        self, period: str = "30d"
    ) -> dict[str, Any]:
        """
        Compute betting statistics for a given period (Story 19.12).

        Args:
            period: Time period - "7d", "30d", "90d", or "all"

        Returns:
            Dict with bet counts and win rate
        """
        now = int(time.time())

        # Calculate period boundaries
        days_map = {"7d": 7, "30d": 30, "90d": 90, "all": 365 * 10}
        days = days_map.get(period, 30)
        start_ts = now - (days * 86400)

        # Get games for current period
        games = self.get_games(start_date=start_ts, end_date=now)

        # Sum bet outcomes across all games
        total_bets = sum(g.get("total_bets", 0) for g in games)
        bets_won = sum(g.get("bets_won", 0) for g in games)

        # Calculate win rate (avoid division by zero)
        win_rate = (bets_won / total_bets * 100) if total_bets > 0 else 0.0

        return {
            "total_bets": total_bets,
            "bets_won": bets_won,
            "win_rate": round(win_rate, 1),
            "has_data": total_bets > 0,
        }


# Error type constants (AC: #2)
ERROR_WEBSOCKET_DISCONNECT = "WEBSOCKET_DISCONNECT"
ERROR_MEDIA_PLAYER_ERROR = "MEDIA_PLAYER_ERROR"
ERROR_PLAYBACK_FAILURE = "PLAYBACK_FAILURE"
ERROR_STATE_TRANSITION = "STATE_TRANSITION_ERROR"
