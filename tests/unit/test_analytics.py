"""
Unit Tests: Analytics Data Collection (Story 19.1)

Tests for analytics storage and data collection:
- Game record persistence (AC: #1, #3)
- Error event recording (AC: #2)
- Data retention and pruning (AC: #5)
- Non-blocking writes (AC: #4)

Story 19.1 - AC: #1, #2, #3, #4, #5
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

# Mock HA BEFORE importing beatify
sys.modules["homeassistant"] = MagicMock()
sys.modules["homeassistant.core"] = MagicMock()
sys.modules["homeassistant.config_entries"] = MagicMock()
sys.modules["homeassistant.components"] = MagicMock()
sys.modules["homeassistant.components.frontend"] = MagicMock()
sys.modules["homeassistant.components.http"] = MagicMock()

from custom_components.beatify.analytics import (
    AnalyticsStorage,
    ERROR_MEDIA_PLAYER_ERROR,
    ERROR_WEBSOCKET_DISCONNECT,
    GameRecord,
    MAX_DETAILED_RECORDS,
    RETENTION_DAYS,
)


@pytest.fixture
def mock_hass(tmp_path):
    """Create mock HomeAssistant with temp config path."""
    hass = MagicMock()
    hass.config.path = lambda *parts: str(tmp_path / "/".join(parts))

    def sync_executor(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    hass.async_add_executor_job = AsyncMock(side_effect=sync_executor)
    return hass


@pytest.fixture
def analytics_storage(mock_hass):
    """Create fresh AnalyticsStorage instance."""
    return AnalyticsStorage(mock_hass)


@pytest.fixture
def sample_game_record() -> GameRecord:
    """Sample game record for testing."""
    now = int(time.time())
    return {
        "game_id": "test-123",
        "started_at": now - 3600,
        "ended_at": now,
        "duration_seconds": 3600,
        "player_count": 4,
        "playlist_names": ["80s-hits"],
        "rounds_played": 10,
        "average_score": 42.5,
        "difficulty": "normal",
        "error_count": 0,
    }


@pytest.mark.unit
class TestAnalyticsStorageInit:
    """Tests for AnalyticsStorage initialization."""

    def test_creates_empty_data_structure(self, analytics_storage):
        """Empty analytics should have correct structure."""
        assert analytics_storage.total_games == 0
        assert analytics_storage.total_errors == 0

    @pytest.mark.asyncio
    async def test_load_creates_fresh_data_when_no_file(self, analytics_storage, tmp_path):
        """load() should create empty data when no file exists."""
        await analytics_storage.load()

        assert analytics_storage.total_games == 0
        assert analytics_storage.get_games() == []


@pytest.mark.unit
class TestAnalyticsGameRecording:
    """Tests for game record persistence (AC: #1, #3)."""

    @pytest.mark.asyncio
    async def test_add_game_stores_record(self, analytics_storage, sample_game_record):
        """add_game() stores game record correctly."""
        await analytics_storage.load()
        await analytics_storage.add_game(sample_game_record)

        games = analytics_storage.get_games()
        assert len(games) == 1
        assert games[0]["game_id"] == "test-123"
        assert games[0]["player_count"] == 4

    @pytest.mark.asyncio
    async def test_game_persists_to_file(
        self, analytics_storage, sample_game_record, tmp_path
    ):
        """Game records persist to analytics.json (AC: #3)."""
        await analytics_storage.load()
        await analytics_storage.add_game(sample_game_record)

        # Give async save time to complete
        await asyncio.sleep(0.1)

        analytics_path = tmp_path / "beatify" / "analytics.json"
        assert analytics_path.exists()

        content = json.loads(analytics_path.read_text())
        assert len(content["games"]) == 1
        assert content["games"][0]["game_id"] == "test-123"

    @pytest.mark.asyncio
    async def test_data_survives_restart(
        self, mock_hass, sample_game_record, tmp_path
    ):
        """Analytics data persists across restarts (AC: #3)."""
        # First session: record a game
        storage1 = AnalyticsStorage(mock_hass)
        await storage1.load()
        await storage1.add_game(sample_game_record)
        await asyncio.sleep(0.1)

        # Second session: verify data loaded
        storage2 = AnalyticsStorage(mock_hass)
        await storage2.load()

        games = storage2.get_games()
        assert len(games) == 1
        assert games[0]["game_id"] == "test-123"

    @pytest.mark.asyncio
    async def test_total_games_count(self, analytics_storage, sample_game_record):
        """total_games property counts all games."""
        await analytics_storage.load()

        assert analytics_storage.total_games == 0

        await analytics_storage.add_game(sample_game_record)
        assert analytics_storage.total_games == 1

        # Add another game
        record2 = sample_game_record.copy()
        record2["game_id"] = "test-456"
        await analytics_storage.add_game(record2)
        assert analytics_storage.total_games == 2


@pytest.mark.unit
class TestAnalyticsErrorRecording:
    """Tests for error event recording (AC: #2)."""

    @pytest.mark.asyncio
    async def test_record_error_stores_event(self, analytics_storage):
        """record_error() stores error event."""
        await analytics_storage.load()

        analytics_storage.record_error(
            ERROR_WEBSOCKET_DISCONNECT, "Connection lost unexpectedly"
        )

        errors = analytics_storage.get_errors()
        assert len(errors) == 1
        assert errors[0]["type"] == ERROR_WEBSOCKET_DISCONNECT
        assert "Connection lost" in errors[0]["message"]

    @pytest.mark.asyncio
    async def test_error_has_timestamp(self, analytics_storage):
        """Error events include timestamp."""
        await analytics_storage.load()
        now = int(time.time())

        analytics_storage.record_error(ERROR_MEDIA_PLAYER_ERROR, "Playback failed")

        errors = analytics_storage.get_errors()
        assert len(errors) == 1
        assert errors[0]["timestamp"] >= now
        assert errors[0]["timestamp"] <= now + 2

    @pytest.mark.asyncio
    async def test_session_error_count(self, analytics_storage):
        """session_error_count tracks errors in current session."""
        await analytics_storage.load()

        assert analytics_storage.session_error_count == 0

        analytics_storage.record_error(ERROR_WEBSOCKET_DISCONNECT, "Error 1")
        assert analytics_storage.session_error_count == 1

        analytics_storage.record_error(ERROR_MEDIA_PLAYER_ERROR, "Error 2")
        assert analytics_storage.session_error_count == 2

    @pytest.mark.asyncio
    async def test_reset_session_errors(self, analytics_storage):
        """reset_session_errors() clears the session counter."""
        await analytics_storage.load()

        analytics_storage.record_error(ERROR_WEBSOCKET_DISCONNECT, "Error")
        assert analytics_storage.session_error_count == 1

        analytics_storage.reset_session_errors()
        assert analytics_storage.session_error_count == 0

    @pytest.mark.asyncio
    async def test_error_message_truncated(self, analytics_storage):
        """Long error messages are truncated to 500 chars."""
        await analytics_storage.load()
        long_message = "x" * 1000

        analytics_storage.record_error(ERROR_MEDIA_PLAYER_ERROR, long_message)

        errors = analytics_storage.get_errors()
        assert len(errors[0]["message"]) == 500


@pytest.mark.unit
class TestAnalyticsDateFiltering:
    """Tests for date range filtering."""

    @pytest.mark.asyncio
    async def test_get_games_filters_by_start_date(self, analytics_storage):
        """get_games() filters by start_date."""
        await analytics_storage.load()
        now = int(time.time())

        # Add old game
        old_game: GameRecord = {
            "game_id": "old",
            "started_at": now - 86400 * 10,
            "ended_at": now - 86400 * 10 + 3600,
            "duration_seconds": 3600,
            "player_count": 2,
            "playlist_names": ["test"],
            "rounds_played": 5,
            "average_score": 30.0,
            "difficulty": "easy",
            "error_count": 0,
        }
        await analytics_storage.add_game(old_game)

        # Add recent game
        new_game: GameRecord = {
            "game_id": "new",
            "started_at": now - 3600,
            "ended_at": now,
            "duration_seconds": 3600,
            "player_count": 4,
            "playlist_names": ["test"],
            "rounds_played": 10,
            "average_score": 45.0,
            "difficulty": "normal",
            "error_count": 0,
        }
        await analytics_storage.add_game(new_game)

        # Filter to last 5 days
        cutoff = now - 86400 * 5
        games = analytics_storage.get_games(start_date=cutoff)

        assert len(games) == 1
        assert games[0]["game_id"] == "new"

    @pytest.mark.asyncio
    async def test_get_errors_filters_by_date_range(self, analytics_storage):
        """get_errors() filters by date range."""
        await analytics_storage.load()
        now = int(time.time())

        # Manually add errors with specific timestamps
        analytics_storage._data["errors"] = [
            {"timestamp": now - 86400 * 5, "type": "OLD", "message": "old"},
            {"timestamp": now - 86400, "type": "RECENT", "message": "recent"},
            {"timestamp": now, "type": "NEW", "message": "new"},
        ]

        # Filter last 3 days
        start = now - 86400 * 3
        end = now + 1
        errors = analytics_storage.get_errors(start_date=start, end_date=end)

        assert len(errors) == 2
        types = [e["type"] for e in errors]
        assert "RECENT" in types
        assert "NEW" in types
        assert "OLD" not in types


@pytest.mark.unit
class TestAnalyticsNonBlockingWrites:
    """Tests for non-blocking write pattern (AC: #4)."""

    @pytest.mark.asyncio
    async def test_schedule_save_returns_immediately(self, analytics_storage):
        """schedule_save() returns without blocking."""
        await analytics_storage.load()

        start = time.perf_counter()
        analytics_storage.schedule_save()
        elapsed = time.perf_counter() - start

        # Should return in under 5ms (AC: #4 - <5ms latency)
        assert elapsed < 0.005


@pytest.mark.unit
class TestAnalyticsAtomicWrites:
    """Tests for atomic write pattern (AC: #3)."""

    @pytest.mark.asyncio
    async def test_no_temp_file_remains(self, analytics_storage, sample_game_record, tmp_path):
        """Atomic write should not leave .tmp file."""
        await analytics_storage.load()
        await analytics_storage.add_game(sample_game_record)

        # Wait for save to complete
        await asyncio.sleep(0.2)

        # Check for temp file
        temp_path = tmp_path / "beatify" / "analytics.tmp"
        assert not temp_path.exists()

        # But main file should exist
        main_path = tmp_path / "beatify" / "analytics.json"
        assert main_path.exists()


@pytest.mark.unit
class TestAnalyticsMonthlySummaries:
    """Tests for monthly summary aggregation."""

    @pytest.mark.asyncio
    async def test_get_monthly_summaries(self, analytics_storage):
        """get_monthly_summaries() returns summary list."""
        await analytics_storage.load()

        # Manually add a summary
        analytics_storage._data["monthly_summaries"] = [
            {
                "month": "2025-01",
                "games_count": 10,
                "total_players": 50,
                "avg_players_per_game": 5.0,
                "total_rounds": 100,
                "avg_rounds_per_game": 10.0,
                "error_rate": 0.1,
            }
        ]

        summaries = analytics_storage.get_monthly_summaries()
        assert len(summaries) == 1
        assert summaries[0]["month"] == "2025-01"
        assert summaries[0]["games_count"] == 10


# Import asyncio for async tests
import asyncio


@pytest.mark.unit
class TestAnalyticsComputeMetrics:
    """Tests for compute_metrics() dashboard data (Story 19.2 AC: #2)."""

    @pytest.mark.asyncio
    async def test_compute_metrics_empty_data(self, analytics_storage):
        """compute_metrics() returns zeros for empty data."""
        await analytics_storage.load()

        result = analytics_storage.compute_metrics("30d")

        assert result["total_games"] == 0
        assert result["avg_players_per_game"] == 0
        assert result["avg_score"] == 0
        assert result["error_rate"] == 0
        assert "trends" in result
        assert "generated_at" in result

    @pytest.mark.asyncio
    async def test_compute_metrics_with_games(self, analytics_storage, sample_game_record):
        """compute_metrics() calculates correct averages."""
        await analytics_storage.load()
        await analytics_storage.add_game(sample_game_record)

        result = analytics_storage.compute_metrics("30d")

        assert result["total_games"] == 1
        assert result["avg_players_per_game"] == 4.0
        assert result["avg_score"] == 42.5
        assert result["period"] == "30d"

    @pytest.mark.asyncio
    async def test_compute_metrics_period_filtering(self, analytics_storage):
        """compute_metrics() filters by period."""
        await analytics_storage.load()
        now = int(time.time())

        # Add old game (60 days ago)
        old_game: GameRecord = {
            "game_id": "old",
            "started_at": now - 86400 * 60,
            "ended_at": now - 86400 * 60 + 3600,
            "duration_seconds": 3600,
            "player_count": 2,
            "playlist_names": ["test"],
            "rounds_played": 5,
            "average_score": 30.0,
            "difficulty": "easy",
            "error_count": 0,
        }
        await analytics_storage.add_game(old_game)

        # Add recent game (5 days ago)
        new_game: GameRecord = {
            "game_id": "new",
            "started_at": now - 86400 * 5,
            "ended_at": now - 86400 * 5 + 3600,
            "duration_seconds": 3600,
            "player_count": 4,
            "playlist_names": ["test"],
            "rounds_played": 10,
            "average_score": 45.0,
            "difficulty": "normal",
            "error_count": 0,
        }
        await analytics_storage.add_game(new_game)

        # 7 day period should only include recent game
        result_7d = analytics_storage.compute_metrics("7d")
        assert result_7d["total_games"] == 1

        # 90 day period should include both
        result_90d = analytics_storage.compute_metrics("90d")
        assert result_90d["total_games"] == 2

    @pytest.mark.asyncio
    async def test_compute_metrics_trends(self, analytics_storage):
        """compute_metrics() calculates trend percentages."""
        await analytics_storage.load()
        now = int(time.time())

        # Add game in current period
        current_game: GameRecord = {
            "game_id": "current",
            "started_at": now - 86400 * 5,
            "ended_at": now - 86400 * 5 + 3600,
            "duration_seconds": 3600,
            "player_count": 6,
            "playlist_names": ["test"],
            "rounds_played": 10,
            "average_score": 50.0,
            "difficulty": "normal",
            "error_count": 0,
        }
        await analytics_storage.add_game(current_game)

        # Add game in previous period
        prev_game: GameRecord = {
            "game_id": "prev",
            "started_at": now - 86400 * 40,  # 40 days ago (in previous 30d period)
            "ended_at": now - 86400 * 40 + 3600,
            "duration_seconds": 3600,
            "player_count": 4,
            "playlist_names": ["test"],
            "rounds_played": 8,
            "average_score": 40.0,
            "difficulty": "normal",
            "error_count": 0,
        }
        await analytics_storage.add_game(prev_game)

        result = analytics_storage.compute_metrics("30d")

        # Trends should show improvement
        assert result["trends"]["games"] == 0  # Same count (1 each period)
        assert result["trends"]["players"] > 0  # 6 vs 4 players
        assert result["trends"]["score"] > 0  # 50 vs 40 score


@pytest.mark.unit
class TestAnalyticsPlaylistStats:
    """Tests for compute_playlist_stats() (Story 19.4 AC: #1, #2)."""

    @pytest.mark.asyncio
    async def test_playlist_stats_empty_games(self, analytics_storage):
        """compute_playlist_stats() returns empty list for no games."""
        await analytics_storage.load()

        result = analytics_storage.compute_playlist_stats([])

        assert result == []

    @pytest.mark.asyncio
    async def test_playlist_stats_aggregates_counts(self, analytics_storage):
        """compute_playlist_stats() aggregates play counts correctly (AC: #1)."""
        await analytics_storage.load()
        now = int(time.time())

        games = [
            {
                "game_id": "g1", "started_at": now - 3600, "ended_at": now,
                "duration_seconds": 3600, "player_count": 4,
                "playlist_names": ["80s-hits", "rock-classics"],
                "rounds_played": 10, "average_score": 40.0,
                "difficulty": "normal", "error_count": 0,
            },
            {
                "game_id": "g2", "started_at": now - 7200, "ended_at": now - 3600,
                "duration_seconds": 3600, "player_count": 3,
                "playlist_names": ["80s-hits"],
                "rounds_played": 8, "average_score": 35.0,
                "difficulty": "normal", "error_count": 0,
            },
            {
                "game_id": "g3", "started_at": now - 10800, "ended_at": now - 7200,
                "duration_seconds": 3600, "player_count": 5,
                "playlist_names": ["pop-2000s", "80s-hits"],
                "rounds_played": 12, "average_score": 45.0,
                "difficulty": "normal", "error_count": 0,
            },
        ]

        result = analytics_storage.compute_playlist_stats(games)

        # 80s-hits should be top with 3 plays
        assert len(result) >= 2
        assert result[0]["name"] == "80s-hits"
        assert result[0]["play_count"] == 3

    @pytest.mark.asyncio
    async def test_playlist_stats_top5_limit(self, analytics_storage):
        """compute_playlist_stats() returns max 5 playlists (AC: #2)."""
        await analytics_storage.load()
        now = int(time.time())

        # Create games with 7 different playlists
        games = []
        for i in range(7):
            games.append({
                "game_id": f"g{i}", "started_at": now - 3600 * (i + 1), "ended_at": now - 3600 * i,
                "duration_seconds": 3600, "player_count": 4,
                "playlist_names": [f"playlist-{i}"],
                "rounds_played": 10, "average_score": 40.0,
                "difficulty": "normal", "error_count": 0,
            })

        result = analytics_storage.compute_playlist_stats(games)

        assert len(result) == 5  # Max 5

    @pytest.mark.asyncio
    async def test_playlist_stats_has_percentage(self, analytics_storage):
        """compute_playlist_stats() includes percentage (AC: #2)."""
        await analytics_storage.load()
        now = int(time.time())

        games = [
            {
                "game_id": "g1", "started_at": now - 3600, "ended_at": now,
                "duration_seconds": 3600, "player_count": 4,
                "playlist_names": ["playlist-a"],
                "rounds_played": 10, "average_score": 40.0,
                "difficulty": "normal", "error_count": 0,
            },
            {
                "game_id": "g2", "started_at": now - 7200, "ended_at": now - 3600,
                "duration_seconds": 3600, "player_count": 3,
                "playlist_names": ["playlist-a"],
                "rounds_played": 8, "average_score": 35.0,
                "difficulty": "normal", "error_count": 0,
            },
            {
                "game_id": "g3", "started_at": now - 10800, "ended_at": now - 7200,
                "duration_seconds": 3600, "player_count": 5,
                "playlist_names": ["playlist-b"],
                "rounds_played": 12, "average_score": 45.0,
                "difficulty": "normal", "error_count": 0,
            },
        ]

        result = analytics_storage.compute_playlist_stats(games)

        # playlist-a: 2/3 = 66.7%, playlist-b: 1/3 = 33.3%
        assert "percentage" in result[0]
        assert result[0]["percentage"] == 66.7
        assert result[1]["percentage"] == 33.3


@pytest.mark.unit
class TestAnalyticsGamesOverTime:
    """Tests for compute_games_over_time() (Story 19.5 AC: #1, #2, #3)."""

    @pytest.mark.asyncio
    async def test_games_over_time_7d_daily_granularity(self, analytics_storage):
        """compute_games_over_time() uses daily granularity for 7d (AC: #2)."""
        await analytics_storage.load()
        now = int(time.time())

        games = [
            {
                "game_id": "g1", "started_at": now - 3600, "ended_at": now,
                "duration_seconds": 3600, "player_count": 4,
                "playlist_names": ["test"],
                "rounds_played": 10, "average_score": 40.0,
                "difficulty": "normal", "error_count": 0,
            },
        ]

        result = analytics_storage.compute_games_over_time(games, "7d")

        assert result["granularity"] == "day"
        assert len(result["labels"]) == 7
        assert len(result["values"]) == 7

    @pytest.mark.asyncio
    async def test_games_over_time_30d_weekly_granularity(self, analytics_storage):
        """compute_games_over_time() uses weekly granularity for 30d (AC: #2)."""
        await analytics_storage.load()

        result = analytics_storage.compute_games_over_time([], "30d")

        assert result["granularity"] == "week"
        assert len(result["labels"]) == 4

    @pytest.mark.asyncio
    async def test_games_over_time_90d_weekly_granularity(self, analytics_storage):
        """compute_games_over_time() uses weekly granularity for 90d (AC: #2)."""
        await analytics_storage.load()

        result = analytics_storage.compute_games_over_time([], "90d")

        assert result["granularity"] == "week"
        assert len(result["labels"]) == 13

    @pytest.mark.asyncio
    async def test_games_over_time_all_monthly_granularity(self, analytics_storage):
        """compute_games_over_time() uses monthly granularity for all (AC: #2)."""
        await analytics_storage.load()

        result = analytics_storage.compute_games_over_time([], "all")

        assert result["granularity"] == "month"

    @pytest.mark.asyncio
    async def test_games_over_time_has_labels_and_values(self, analytics_storage):
        """compute_games_over_time() returns labels and values arrays (AC: #3)."""
        await analytics_storage.load()
        now = int(time.time())

        games = [
            {
                "game_id": "g1", "started_at": now - 86400, "ended_at": now,
                "duration_seconds": 3600, "player_count": 4,
                "playlist_names": ["test"],
                "rounds_played": 10, "average_score": 40.0,
                "difficulty": "normal", "error_count": 0,
            },
        ]

        result = analytics_storage.compute_games_over_time(games, "7d")

        assert "labels" in result
        assert "values" in result
        assert isinstance(result["labels"], list)
        assert isinstance(result["values"], list)
        assert len(result["labels"]) == len(result["values"])


@pytest.mark.unit
class TestAnalyticsErrorStats:
    """Tests for compute_error_stats() (Story 19.6 AC: #1, #2, #3)."""

    @pytest.mark.asyncio
    async def test_error_stats_healthy_status(self, analytics_storage):
        """compute_error_stats() returns 'healthy' for low error rate (AC: #3)."""
        await analytics_storage.load()
        now = int(time.time())

        # 10 games, 100 rounds, 0 errors = 0% error rate
        games = [
            {
                "game_id": f"g{i}", "started_at": now - 3600 * (i + 1), "ended_at": now - 3600 * i,
                "duration_seconds": 3600, "player_count": 4,
                "playlist_names": ["test"],
                "rounds_played": 10, "average_score": 40.0,
                "difficulty": "normal", "error_count": 0,
            }
            for i in range(10)
        ]
        errors = []

        result = analytics_storage.compute_error_stats(games, errors, "30d")

        assert result["status"] == "healthy"
        assert result["error_rate"] < 0.01

    @pytest.mark.asyncio
    async def test_error_stats_warning_status(self, analytics_storage):
        """compute_error_stats() returns 'warning' for moderate error rate (AC: #3)."""
        await analytics_storage.load()
        now = int(time.time())

        # 10 games, 100 rounds, 3 errors = 3% error rate
        games = [
            {
                "game_id": f"g{i}", "started_at": now - 3600 * (i + 1), "ended_at": now - 3600 * i,
                "duration_seconds": 3600, "player_count": 4,
                "playlist_names": ["test"],
                "rounds_played": 10, "average_score": 40.0,
                "difficulty": "normal", "error_count": 0,
            }
            for i in range(10)
        ]
        errors = [
            {"timestamp": now - 3600 * i, "type": "TEST_ERROR", "message": f"error {i}"}
            for i in range(3)
        ]

        result = analytics_storage.compute_error_stats(games, errors, "30d")

        assert result["status"] == "warning"
        assert 0.01 <= result["error_rate"] < 0.05

    @pytest.mark.asyncio
    async def test_error_stats_critical_status(self, analytics_storage):
        """compute_error_stats() returns 'critical' for high error rate (AC: #3)."""
        await analytics_storage.load()
        now = int(time.time())

        # 2 games, 20 rounds, 10 errors = 50% error rate
        games = [
            {
                "game_id": f"g{i}", "started_at": now - 3600 * (i + 1), "ended_at": now - 3600 * i,
                "duration_seconds": 3600, "player_count": 4,
                "playlist_names": ["test"],
                "rounds_played": 10, "average_score": 40.0,
                "difficulty": "normal", "error_count": 0,
            }
            for i in range(2)
        ]
        errors = [
            {"timestamp": now - 3600 * i, "type": "TEST_ERROR", "message": f"error {i}"}
            for i in range(10)
        ]

        result = analytics_storage.compute_error_stats(games, errors, "30d")

        assert result["status"] == "critical"
        assert result["error_rate"] >= 0.05

    @pytest.mark.asyncio
    async def test_error_stats_includes_recent_errors(self, analytics_storage):
        """compute_error_stats() includes up to 10 recent errors (AC: #2)."""
        await analytics_storage.load()
        now = int(time.time())

        games = []
        errors = [
            {"timestamp": now - 3600 * i, "type": "TEST_ERROR", "message": f"error {i}"}
            for i in range(15)
        ]

        result = analytics_storage.compute_error_stats(games, errors, "30d")

        assert "recent_errors" in result
        assert len(result["recent_errors"]) == 10  # Max 10

    @pytest.mark.asyncio
    async def test_error_stats_recent_errors_sorted(self, analytics_storage):
        """compute_error_stats() sorts recent errors by timestamp desc (AC: #2)."""
        await analytics_storage.load()
        now = int(time.time())

        games = []
        errors = [
            {"timestamp": now - 3600, "type": "OLD", "message": "old"},
            {"timestamp": now, "type": "NEW", "message": "new"},
            {"timestamp": now - 1800, "type": "MIDDLE", "message": "middle"},
        ]

        result = analytics_storage.compute_error_stats(games, errors, "30d")

        # Should be sorted newest first
        assert result["recent_errors"][0]["type"] == "NEW"
        assert result["recent_errors"][1]["type"] == "MIDDLE"
        assert result["recent_errors"][2]["type"] == "OLD"

    @pytest.mark.asyncio
    async def test_error_stats_has_counts(self, analytics_storage):
        """compute_error_stats() includes error_count and total_events (AC: #1)."""
        await analytics_storage.load()
        now = int(time.time())

        games = [
            {
                "game_id": "g1", "started_at": now - 3600, "ended_at": now,
                "duration_seconds": 3600, "player_count": 4,
                "playlist_names": ["test"],
                "rounds_played": 10, "average_score": 40.0,
                "difficulty": "normal", "error_count": 0,
            },
        ]
        errors = [
            {"timestamp": now - 1800, "type": "TEST", "message": "test error"},
        ]

        result = analytics_storage.compute_error_stats(games, errors, "30d")

        assert "error_count" in result
        assert result["error_count"] == 1
        assert "total_events" in result
        assert result["total_events"] == 10  # rounds_played
