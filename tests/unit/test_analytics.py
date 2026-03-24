"""Tests for Beatify analytics storage (custom_components/beatify/analytics.py)."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.beatify.analytics import (
    MAX_DETAILED_RECORDS,
    PRUNE_INTERVAL,
    RETENTION_DAYS,
    AnalyticsStorage,
    GameRecord,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_hass() -> MagicMock:
    """Create a mock hass instance suitable for AnalyticsStorage."""
    hass = MagicMock()
    hass.config.path.return_value = "/tmp/test_beatify/analytics.json"
    hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *args: fn(*args))
    return hass


def _make_game_record(
    *,
    game_id: str = "game-1",
    ended_at: int | None = None,
    player_count: int = 4,
    rounds_played: int = 5,
    average_score: float = 75.0,
    difficulty: str = "normal",
    error_count: int = 0,
    streak_3_count: int = 0,
    streak_5_count: int = 0,
    streak_10_count: int = 0,
    total_bets: int = 0,
    bets_won: int = 0,
    playlist_names: list[str] | None = None,
) -> GameRecord:
    """Build a GameRecord with sensible defaults."""
    now = ended_at or int(time.time())
    return {
        "game_id": game_id,
        "started_at": now - 600,
        "ended_at": now,
        "duration_seconds": 600,
        "player_count": player_count,
        "playlist_names": playlist_names or ["pop-hits"],
        "rounds_played": rounds_played,
        "average_score": average_score,
        "difficulty": difficulty,
        "error_count": error_count,
        "streak_3_count": streak_3_count,
        "streak_5_count": streak_5_count,
        "streak_10_count": streak_10_count,
        "total_bets": total_bets,
        "bets_won": bets_won,
    }


# ---------------------------------------------------------------------------
# TestEmptyData
# ---------------------------------------------------------------------------


class TestEmptyData:
    def setup_method(self):
        self.hass = _mock_hass()
        self.storage = AnalyticsStorage(self.hass)

    def test_returns_correct_structure(self):
        data = self.storage._empty_data()
        assert data["version"] == 1
        assert data["games"] == []
        assert data["errors"] == []
        assert data["monthly_summaries"] == []

    def test_returns_new_instance_each_call(self):
        a = self.storage._empty_data()
        b = self.storage._empty_data()
        assert a is not b
        assert a["games"] is not b["games"]


# ---------------------------------------------------------------------------
# TestAddGame
# ---------------------------------------------------------------------------


class TestAddGame:
    def setup_method(self):
        self.hass = _mock_hass()
        self.storage = AnalyticsStorage(self.hass)

    @pytest.mark.asyncio
    async def test_appends_game_record(self):
        record = _make_game_record()
        with patch.object(self.storage, "schedule_save"):
            await self.storage.add_game(record)
        assert len(self.storage._data["games"]) == 1
        assert self.storage._data["games"][0]["game_id"] == "game-1"

    @pytest.mark.asyncio
    async def test_multiple_games_appended(self):
        with patch.object(self.storage, "schedule_save"):
            for i in range(3):
                await self.storage.add_game(_make_game_record(game_id=f"game-{i}"))
        assert len(self.storage._data["games"]) == 3

    @pytest.mark.asyncio
    async def test_calls_schedule_save(self):
        with patch.object(self.storage, "schedule_save") as mock_save:
            await self.storage.add_game(_make_game_record())
        mock_save.assert_called_once()

    @pytest.mark.asyncio
    async def test_triggers_prune_at_interval(self):
        with (
            patch.object(self.storage, "schedule_save"),
            patch.object(
                self.storage, "_prune_old_records", new_callable=AsyncMock
            ) as mock_prune,
        ):
            for i in range(PRUNE_INTERVAL):
                await self.storage.add_game(_make_game_record(game_id=f"game-{i}"))
        mock_prune.assert_called_once()

    @pytest.mark.asyncio
    async def test_resets_prune_counter_after_prune(self):
        with (
            patch.object(self.storage, "schedule_save"),
            patch.object(self.storage, "_prune_old_records", new_callable=AsyncMock),
        ):
            for i in range(PRUNE_INTERVAL):
                await self.storage.add_game(_make_game_record(game_id=f"game-{i}"))
        assert self.storage._games_since_prune == 0

    @pytest.mark.asyncio
    async def test_no_prune_before_interval(self):
        with (
            patch.object(self.storage, "schedule_save"),
            patch.object(
                self.storage, "_prune_old_records", new_callable=AsyncMock
            ) as mock_prune,
        ):
            for i in range(PRUNE_INTERVAL - 1):
                await self.storage.add_game(_make_game_record(game_id=f"game-{i}"))
        mock_prune.assert_not_called()


# ---------------------------------------------------------------------------
# TestRecordError
# ---------------------------------------------------------------------------


class TestRecordError:
    def setup_method(self):
        self.hass = _mock_hass()
        self.storage = AnalyticsStorage(self.hass)

    def test_records_error_event(self):
        with patch.object(self.storage, "schedule_save"):
            self.storage.record_error("WEBSOCKET_DISCONNECT", "Connection lost")
        assert len(self.storage._data["errors"]) == 1
        err = self.storage._data["errors"][0]
        assert err["type"] == "WEBSOCKET_DISCONNECT"
        assert err["message"] == "Connection lost"
        assert "timestamp" in err

    def test_increments_session_error_count(self):
        with patch.object(self.storage, "schedule_save"):
            self.storage.record_error("ERR", "msg1")
            self.storage.record_error("ERR", "msg2")
        assert self.storage.session_error_count == 2

    def test_truncates_long_message(self):
        long_msg = "x" * 1000
        with patch.object(self.storage, "schedule_save"):
            self.storage.record_error("ERR", long_msg)
        assert len(self.storage._data["errors"][0]["message"]) == 500

    def test_calls_schedule_save(self):
        with patch.object(self.storage, "schedule_save") as mock_save:
            self.storage.record_error("ERR", "msg")
        mock_save.assert_called_once()


# ---------------------------------------------------------------------------
# TestSessionErrors
# ---------------------------------------------------------------------------


class TestSessionErrors:
    def setup_method(self):
        self.hass = _mock_hass()
        self.storage = AnalyticsStorage(self.hass)

    def test_initial_count_is_zero(self):
        assert self.storage.session_error_count == 0

    def test_reset_clears_count(self):
        with patch.object(self.storage, "schedule_save"):
            self.storage.record_error("ERR", "msg")
            self.storage.record_error("ERR", "msg")
        assert self.storage.session_error_count == 2
        self.storage.reset_session_errors()
        assert self.storage.session_error_count == 0


# ---------------------------------------------------------------------------
# TestGetGamesAndErrors (filtering)
# ---------------------------------------------------------------------------


class TestGetGamesAndErrors:
    def setup_method(self):
        self.hass = _mock_hass()
        self.storage = AnalyticsStorage(self.hass)
        now = int(time.time())
        # Add games at different timestamps
        self.storage._data["games"] = [
            _make_game_record(game_id="old", ended_at=now - 86400 * 60),
            _make_game_record(game_id="mid", ended_at=now - 86400 * 15),
            _make_game_record(game_id="new", ended_at=now - 3600),
        ]
        self.storage._data["errors"] = [
            {"timestamp": now - 86400 * 60, "type": "ERR", "message": "old"},
            {"timestamp": now - 3600, "type": "ERR", "message": "new"},
        ]
        self.now = now

    def test_get_games_no_filter(self):
        assert len(self.storage.get_games()) == 3

    def test_get_games_with_start_date(self):
        games = self.storage.get_games(start_date=self.now - 86400 * 20)
        ids = [g["game_id"] for g in games]
        assert "old" not in ids
        assert "mid" in ids
        assert "new" in ids

    def test_get_games_with_end_date(self):
        games = self.storage.get_games(end_date=self.now - 86400 * 10)
        ids = [g["game_id"] for g in games]
        assert "new" not in ids
        assert "old" in ids

    def test_get_errors_with_start_date(self):
        errors = self.storage.get_errors(start_date=self.now - 86400)
        assert len(errors) == 1
        assert errors[0]["message"] == "new"


# ---------------------------------------------------------------------------
# TestPruneOldData
# ---------------------------------------------------------------------------


class TestPruneOldData:
    def setup_method(self):
        self.hass = _mock_hass()
        self.storage = AnalyticsStorage(self.hass)

    @pytest.mark.asyncio
    async def test_no_prune_when_under_max_records(self):
        """Should not prune when total games <= MAX_DETAILED_RECORDS."""
        self.storage._data["games"] = [
            _make_game_record(game_id=f"g-{i}") for i in range(10)
        ]
        await self.storage._prune_old_records()
        assert len(self.storage._data["games"]) == 10

    @pytest.mark.asyncio
    async def test_prune_removes_old_games_over_limit(self):
        """Old games beyond retention should be pruned into summaries."""
        now = int(time.time())
        old_ts = now - (RETENTION_DAYS + 30) * 86400  # well beyond retention
        recent_ts = now - 3600

        games = []
        # Create enough games to exceed MAX_DETAILED_RECORDS
        for i in range(MAX_DETAILED_RECORDS + 50):
            ts = old_ts if i < 50 else recent_ts
            games.append(_make_game_record(game_id=f"g-{i}", ended_at=ts))
        self.storage._data["games"] = games

        await self.storage._prune_old_records()

        # Old games should be removed, recent ones kept
        assert len(self.storage._data["games"]) == MAX_DETAILED_RECORDS
        # Monthly summaries should be created for old games
        assert len(self.storage._data["monthly_summaries"]) > 0

    @pytest.mark.asyncio
    async def test_prune_creates_correct_monthly_summary(self):
        """Monthly summary should have correct aggregation."""
        now = int(time.time())
        old_ts = now - (RETENTION_DAYS + 10) * 86400

        # Need > MAX_DETAILED_RECORDS to trigger pruning
        games = []
        # 100 old games
        for i in range(100):
            games.append(
                _make_game_record(
                    game_id=f"old-{i}",
                    ended_at=old_ts + i,
                    player_count=3,
                    rounds_played=5,
                    error_count=1,
                )
            )
        # Fill up to exceed limit with recent games
        recent_ts = now - 3600
        for i in range(MAX_DETAILED_RECORDS + 1):
            games.append(
                _make_game_record(
                    game_id=f"recent-{i}",
                    ended_at=recent_ts,
                )
            )
        self.storage._data["games"] = games

        await self.storage._prune_old_records()

        summaries = self.storage._data["monthly_summaries"]
        assert len(summaries) >= 1
        summary = summaries[0]
        assert summary["games_count"] == 100
        assert summary["total_players"] == 300
        assert summary["avg_players_per_game"] == 3.0

    @pytest.mark.asyncio
    async def test_prune_removes_old_errors(self):
        """Errors beyond retention period should be pruned."""
        now = int(time.time())
        old_ts = now - (RETENTION_DAYS + 10) * 86400

        self.storage._data["errors"] = [
            {"timestamp": old_ts, "type": "ERR", "message": "old"},
            {"timestamp": now - 100, "type": "ERR", "message": "recent"},
        ]
        # Need games to exceed limit to trigger pruning logic
        games = []
        for i in range(MAX_DETAILED_RECORDS + 10):
            games.append(
                _make_game_record(
                    game_id=f"g-{i}",
                    ended_at=old_ts if i < 10 else now - 100,
                )
            )
        self.storage._data["games"] = games

        await self.storage._prune_old_records()

        errors = self.storage._data["errors"]
        assert len(errors) == 1
        assert errors[0]["message"] == "recent"


# ---------------------------------------------------------------------------
# TestComputeMetrics
# ---------------------------------------------------------------------------


class TestComputeMetrics:
    def setup_method(self):
        self.hass = _mock_hass()
        self.hass.config.path.side_effect = (
            lambda *parts: "/tmp/test_beatify/" + "/".join(parts)
        )
        self.storage = AnalyticsStorage(self.hass)
        self.now = int(time.time())

    def _add_recent_games(self, count: int = 5, days_ago: int = 3, **kwargs):
        ts = self.now - 86400 * days_ago
        for i in range(count):
            self.storage._data["games"].append(
                _make_game_record(game_id=f"g-{i}", ended_at=ts + i, **kwargs)
            )

    def test_empty_data_returns_zero_metrics(self):
        metrics = self.storage.compute_metrics("30d")
        assert metrics["total_games"] == 0
        assert metrics["avg_players_per_game"] == 0
        assert metrics["avg_score"] == 0
        assert metrics["error_rate"] == 0

    def test_correct_total_games(self):
        self._add_recent_games(count=5)
        metrics = self.storage.compute_metrics("30d")
        assert metrics["total_games"] == 5

    def test_correct_avg_players(self):
        self._add_recent_games(count=2, player_count=6)
        metrics = self.storage.compute_metrics("30d")
        assert metrics["avg_players_per_game"] == 6.0

    def test_correct_avg_score(self):
        self._add_recent_games(count=1, player_count=2, average_score=80.0)
        metrics = self.storage.compute_metrics("30d")
        # avg_score = sum(avg_score * player_count) / total_players
        # = (80 * 2) / 2 = 80
        assert metrics["avg_score"] == 80.0

    def test_period_7d_filters_correctly(self):
        self._add_recent_games(count=3, days_ago=2)  # within 7d
        self._add_recent_games(count=2, days_ago=10)  # outside 7d
        metrics = self.storage.compute_metrics("7d")
        assert metrics["total_games"] == 3

    def test_period_all_includes_everything(self):
        self._add_recent_games(count=3, days_ago=2)
        self._add_recent_games(count=2, days_ago=200)
        metrics = self.storage.compute_metrics("all")
        assert metrics["total_games"] == 5

    def test_peak_players(self):
        self.storage._data["games"].append(
            _make_game_record(game_id="g1", ended_at=self.now - 100, player_count=3)
        )
        self.storage._data["games"].append(
            _make_game_record(game_id="g2", ended_at=self.now - 50, player_count=8)
        )
        metrics = self.storage.compute_metrics("30d")
        assert metrics["peak_players"] == 8

    def test_avg_rounds(self):
        self._add_recent_games(count=2, rounds_played=10)
        metrics = self.storage.compute_metrics("30d")
        assert metrics["avg_rounds"] == 10.0

    def test_metrics_contain_expected_keys(self):
        self._add_recent_games(count=1)
        metrics = self.storage.compute_metrics("30d")
        expected_keys = {
            "period",
            "total_games",
            "avg_players_per_game",
            "avg_score",
            "error_rate",
            "peak_players",
            "avg_rounds",
            "streak_stats",
            "bet_stats",
            "trends",
            "playlists",
            "chart_data",
            "error_stats",
            "generated_at",
        }
        assert expected_keys.issubset(set(metrics.keys()))

    def test_trends_present(self):
        self._add_recent_games(count=2)
        metrics = self.storage.compute_metrics("30d")
        assert "games" in metrics["trends"]
        assert "players" in metrics["trends"]
        assert "score" in metrics["trends"]
        assert "errors" in metrics["trends"]
        assert "rounds" in metrics["trends"]


# ---------------------------------------------------------------------------
# TestComputeStreakStats
# ---------------------------------------------------------------------------


class TestComputeStreakStats:
    def setup_method(self):
        self.hass = _mock_hass()
        self.storage = AnalyticsStorage(self.hass)
        self.now = int(time.time())

    def test_no_games_returns_empty(self):
        stats = self.storage.compute_streak_stats("30d")
        assert stats["total_streaks"] == 0
        assert stats["has_data"] is False

    def test_aggregates_streak_counts(self):
        ts = self.now - 3600
        self.storage._data["games"] = [
            _make_game_record(
                ended_at=ts, streak_3_count=2, streak_5_count=1, streak_10_count=0
            ),
            _make_game_record(
                ended_at=ts + 1, streak_3_count=3, streak_5_count=0, streak_10_count=1
            ),
        ]
        stats = self.storage.compute_streak_stats("30d")
        assert stats["streak_3_count"] == 5
        assert stats["streak_5_count"] == 1
        assert stats["streak_10_count"] == 1
        assert stats["total_streaks"] == 7
        assert stats["has_data"] is True


# ---------------------------------------------------------------------------
# TestComputeBetStats
# ---------------------------------------------------------------------------


class TestComputeBetStats:
    def setup_method(self):
        self.hass = _mock_hass()
        self.storage = AnalyticsStorage(self.hass)
        self.now = int(time.time())

    def test_no_games_returns_empty(self):
        stats = self.storage.compute_bet_stats("30d")
        assert stats["total_bets"] == 0
        assert stats["has_data"] is False
        assert stats["win_rate"] == 0.0

    def test_aggregates_bet_counts(self):
        ts = self.now - 3600
        self.storage._data["games"] = [
            _make_game_record(ended_at=ts, total_bets=10, bets_won=6),
            _make_game_record(ended_at=ts + 1, total_bets=5, bets_won=2),
        ]
        stats = self.storage.compute_bet_stats("30d")
        assert stats["total_bets"] == 15
        assert stats["bets_won"] == 8
        assert stats["win_rate"] == pytest.approx(53.3, abs=0.1)
        assert stats["has_data"] is True


# ---------------------------------------------------------------------------
# TestTotalProperties
# ---------------------------------------------------------------------------


class TestTotalProperties:
    def setup_method(self):
        self.hass = _mock_hass()
        self.storage = AnalyticsStorage(self.hass)

    def test_total_games_includes_summaries(self):
        self.storage._data["games"] = [_make_game_record()]
        self.storage._data["monthly_summaries"] = [
            {
                "month": "2025-01",
                "games_count": 20,
                "total_players": 80,
                "avg_players_per_game": 4.0,
                "total_rounds": 100,
                "avg_rounds_per_game": 5.0,
                "error_rate": 0.1,
            }
        ]
        assert self.storage.total_games == 21


# ---------------------------------------------------------------------------
# TestPlaylistStats
# ---------------------------------------------------------------------------


class TestPlaylistStats:
    def setup_method(self):
        self.hass = _mock_hass()
        self.hass.config.path.side_effect = (
            lambda *parts: "/tmp/test_beatify/" + "/".join(parts)
        )
        self.storage = AnalyticsStorage(self.hass)

    def test_empty_games(self):
        result = self.storage.compute_playlist_stats([])
        assert result == []

    def test_aggregates_playlist_counts(self):
        games = [
            _make_game_record(playlist_names=["pop-hits", "rock-classics"]),
            _make_game_record(playlist_names=["pop-hits"]),
        ]
        result = self.storage.compute_playlist_stats(games)
        names = {r["name"] for r in result}
        assert "pop-hits" in names
        # pop-hits appears 2 times
        pop = next(r for r in result if r["name"] == "pop-hits")
        assert pop["play_count"] == 2

    def test_top_5_limit(self):
        games = [_make_game_record(playlist_names=[f"playlist-{i}"]) for i in range(10)]
        result = self.storage.compute_playlist_stats(games)
        assert len(result) <= 5
