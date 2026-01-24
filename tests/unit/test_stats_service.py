"""
Unit Tests: StatsService

Tests game statistics tracking for Story 14.4:
- Stats file load/save persistence
- Game recording with correct calculations
- Comparison methods for performance tracking
- Motivational message generation
- Edge cases (first game, corrupted file, 0 players)

Story 14.4 - AC: #1, #2, #3, #4, #6, #7, #8
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Mock homeassistant before importing beatify modules
sys.modules["homeassistant"] = MagicMock()
sys.modules["homeassistant.core"] = MagicMock()
sys.modules["homeassistant.components"] = MagicMock()
sys.modules["homeassistant.components.http"] = MagicMock()
sys.modules["homeassistant.components.frontend"] = MagicMock()
sys.modules["homeassistant.config_entries"] = MagicMock()

from custom_components.beatify.services.stats import StatsService


@pytest.fixture
def mock_hass(tmp_path):
    """Create a mock Home Assistant instance with temp config path."""
    hass = MagicMock()
    hass.config.path = lambda *parts: str(tmp_path / "/".join(parts))
    hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *args: fn(*args))
    return hass


@pytest.fixture
def stats_service(mock_hass):
    """Create a fresh StatsService instance."""
    return StatsService(mock_hass)


@pytest.fixture
def sample_game_summary():
    """Sample game summary data for recording."""
    return {
        "playlist": "80s-hits",
        "rounds": 10,
        "player_count": 4,
        "winner": "Alice",
        "winner_score": 850,
        "total_points": 2100,
    }


@pytest.mark.unit
class TestStatsServiceInit:
    """Tests for StatsService initialization."""

    def test_init_sets_empty_stats(self, stats_service):
        """StatsService initializes with empty stats structure."""
        assert stats_service._stats["version"] == 1
        assert stats_service._stats["games"] == []
        assert stats_service._stats["playlists"] == {}
        assert stats_service._stats["all_time"]["games_played"] == 0

    def test_init_sets_correct_file_path(self, mock_hass, tmp_path):
        """StatsService sets correct stats file path."""
        service = StatsService(mock_hass)
        expected_path = tmp_path / "beatify" / "stats.json"
        assert service._stats_file == Path(expected_path)


@pytest.mark.unit
class TestStatsServiceLoadSave:
    """Tests for stats file persistence (AC: #7)."""

    @pytest.mark.asyncio
    async def test_load_creates_empty_stats_when_no_file(self, stats_service):
        """load() creates empty stats when file doesn't exist."""
        await stats_service.load()

        assert stats_service._stats["version"] == 1
        assert stats_service._stats["games"] == []
        assert stats_service.games_played == 0

    @pytest.mark.asyncio
    async def test_load_reads_existing_stats_file(self, mock_hass, tmp_path):
        """load() reads and parses existing stats file."""
        # Create stats file
        stats_dir = tmp_path / "beatify"
        stats_dir.mkdir(parents=True)
        stats_file = stats_dir / "stats.json"
        stats_data = {
            "version": 1,
            "games": [{"id": "abc123", "avg_score_per_round": 5.5}],
            "playlists": {},
            "all_time": {"games_played": 1, "highest_avg_score": 5.5, "highest_avg_game_id": "abc123"},
        }
        stats_file.write_text(json.dumps(stats_data))

        service = StatsService(mock_hass)
        await service.load()

        assert service.games_played == 1
        assert len(service._stats["games"]) == 1

    @pytest.mark.asyncio
    async def test_load_recreates_on_corrupted_file(self, mock_hass, tmp_path):
        """load() recreates empty stats when file is corrupted."""
        # Create corrupted stats file
        stats_dir = tmp_path / "beatify"
        stats_dir.mkdir(parents=True)
        stats_file = stats_dir / "stats.json"
        stats_file.write_text("{ invalid json }")

        service = StatsService(mock_hass)
        await service.load()

        # Should have reset to empty stats
        assert service._stats["version"] == 1
        assert service._stats["games"] == []

    @pytest.mark.asyncio
    async def test_save_persists_stats_to_file(self, stats_service, tmp_path):
        """save() writes stats to JSON file."""
        stats_service._stats["all_time"]["games_played"] = 5

        await stats_service.save()

        stats_file = tmp_path / "beatify" / "stats.json"
        assert stats_file.exists()
        data = json.loads(stats_file.read_text())
        assert data["all_time"]["games_played"] == 5


@pytest.mark.unit
class TestStatsServiceRecordGame:
    """Tests for record_game() method (AC: #1, #8)."""

    @pytest.mark.asyncio
    async def test_record_game_creates_entry(self, stats_service, sample_game_summary):
        """record_game() creates correct game entry."""
        await stats_service.record_game(sample_game_summary)

        assert len(stats_service._stats["games"]) == 1
        game = stats_service._stats["games"][0]
        assert game["playlist"] == "80s-hits"
        assert game["rounds"] == 10
        assert game["player_count"] == 4
        assert game["winner"] == "Alice"
        assert game["winner_score"] == 850
        assert game["total_points"] == 2100

    @pytest.mark.asyncio
    async def test_record_game_calculates_avg_score(self, stats_service, sample_game_summary):
        """record_game() calculates avg_score_per_round correctly."""
        # total_points / (rounds * player_count) = 2100 / (10 * 4) = 52.5
        await stats_service.record_game(sample_game_summary)

        game = stats_service._stats["games"][0]
        assert game["avg_score_per_round"] == 52.5

    @pytest.mark.asyncio
    async def test_record_game_updates_all_time_stats(self, stats_service, sample_game_summary):
        """record_game() updates all_time statistics."""
        await stats_service.record_game(sample_game_summary)

        all_time = stats_service._stats["all_time"]
        assert all_time["games_played"] == 1
        assert all_time["highest_avg_score"] == 52.5

    @pytest.mark.asyncio
    async def test_record_game_updates_playlist_stats(self, stats_service, sample_game_summary):
        """record_game() updates playlist statistics."""
        await stats_service.record_game(sample_game_summary)

        playlist_stats = stats_service._stats["playlists"]["80s-hits"]
        assert playlist_stats["times_played"] == 1
        assert playlist_stats["total_rounds"] == 10

    @pytest.mark.asyncio
    async def test_record_game_skips_zero_players(self, stats_service):
        """record_game() does NOT record games with 0 players (AC: #8)."""
        game_summary = {
            "playlist": "test",
            "rounds": 10,
            "player_count": 0,
            "winner": "Nobody",
            "winner_score": 0,
            "total_points": 0,
        }

        await stats_service.record_game(game_summary)

        assert len(stats_service._stats["games"]) == 0
        assert stats_service.games_played == 0

    @pytest.mark.asyncio
    async def test_record_game_returns_comparison(self, stats_service, sample_game_summary):
        """record_game() returns comparison data for frontend."""
        result = await stats_service.record_game(sample_game_summary)

        assert "avg_score" in result
        assert "all_time_avg" in result
        assert "is_first_game" in result
        assert "is_new_record" in result


@pytest.mark.unit
class TestStatsServiceComparison:
    """Tests for get_game_comparison() method (AC: #2)."""

    def test_comparison_first_game(self, stats_service):
        """get_game_comparison() handles first game correctly (AC: #6)."""
        result = stats_service.get_game_comparison(5.0)

        assert result["is_first_game"] is True
        assert result["is_new_record"] is False
        assert result["difference"] == 0.0

    @pytest.mark.asyncio
    async def test_comparison_above_average(self, stats_service, sample_game_summary):
        """get_game_comparison() detects above average performance."""
        # Record first game
        await stats_service.record_game(sample_game_summary)

        # Compare new game with higher score
        result = stats_service.get_game_comparison(60.0)

        assert result["is_first_game"] is False
        assert result["is_above_average"] is True
        assert result["difference"] > 0

    @pytest.mark.asyncio
    async def test_comparison_new_record(self, stats_service, sample_game_summary):
        """get_game_comparison() detects new record."""
        # Record first game with 52.5 avg
        await stats_service.record_game(sample_game_summary)

        # Compare with even higher score
        result = stats_service.get_game_comparison(60.0)

        assert result["is_new_record"] is True


@pytest.mark.unit
class TestStatsServiceMotivationalMessage:
    """Tests for get_motivational_message() method (AC: #3, #4, #6)."""

    def test_message_first_game(self, stats_service):
        """get_motivational_message() returns first game message (AC: #6)."""
        comparison = stats_service.get_game_comparison(5.0)
        result = stats_service.get_motivational_message(comparison)

        assert result is not None
        assert result["type"] == "first"
        assert "First game" in result["message"]

    @pytest.mark.asyncio
    async def test_message_new_record(self, stats_service, sample_game_summary):
        """get_motivational_message() returns record message (AC: #4)."""
        await stats_service.record_game(sample_game_summary)
        comparison = stats_service.get_game_comparison(100.0)  # Much higher than 52.5
        result = stats_service.get_motivational_message(comparison)

        assert result is not None
        assert result["type"] == "record"
        assert "New Record" in result["message"]

    @pytest.mark.asyncio
    async def test_message_strong_game(self, stats_service):
        """get_motivational_message() returns strong game message (AC: #3)."""
        # Record high score game first (60 avg)
        await stats_service.record_game({
            "playlist": "test",
            "rounds": 10,
            "player_count": 4,
            "winner": "A",
            "winner_score": 100,
            "total_points": 2400,  # 60.0 avg
        })
        # Record lower game to bring down average
        await stats_service.record_game({
            "playlist": "test",
            "rounds": 10,
            "player_count": 4,
            "winner": "B",
            "winner_score": 100,
            "total_points": 1600,  # 40.0 avg
        })
        # All-time avg is now 50.0 (weighted), highest is 60.0
        # Test with 56.0 - above avg by 6, but below record (60)
        comparison = stats_service.get_game_comparison(56.0)
        result = stats_service.get_motivational_message(comparison)

        assert result is not None
        assert result["type"] == "strong"
        assert "Excellent" in result["message"]

    @pytest.mark.asyncio
    async def test_message_above_average(self, stats_service):
        """get_motivational_message() returns above average message."""
        # Record high score game first (60 avg)
        await stats_service.record_game({
            "playlist": "test",
            "rounds": 10,
            "player_count": 4,
            "winner": "A",
            "winner_score": 100,
            "total_points": 2400,  # 60.0 avg
        })
        # Record lower game to bring down average
        await stats_service.record_game({
            "playlist": "test",
            "rounds": 10,
            "player_count": 4,
            "winner": "B",
            "winner_score": 100,
            "total_points": 1600,  # 40.0 avg
        })
        # All-time avg is now 50.0 (weighted), highest is 60.0
        # Test with 52.0 - above avg by 2, but below record (60)
        comparison = stats_service.get_game_comparison(52.0)
        result = stats_service.get_motivational_message(comparison)

        assert result is not None
        assert result["type"] == "above"
        assert "Strong game" in result["message"]

    @pytest.mark.asyncio
    async def test_message_close_to_average(self, stats_service, sample_game_summary):
        """get_motivational_message() returns close message for slight below."""
        await stats_service.record_game(sample_game_summary)
        # Current avg is 52.5, so 50 is about 2.5 below
        comparison = stats_service.get_game_comparison(50.0)
        result = stats_service.get_motivational_message(comparison)

        assert result is not None
        assert result["type"] == "close"
        assert "Close to average" in result["message"]

    @pytest.mark.asyncio
    async def test_message_none_for_far_below(self, stats_service, sample_game_summary):
        """get_motivational_message() returns None for far below average."""
        await stats_service.record_game(sample_game_summary)
        # Current avg is 52.5, so 40 is about 12.5 below
        comparison = stats_service.get_game_comparison(40.0)
        result = stats_service.get_motivational_message(comparison)

        assert result is None


@pytest.mark.unit
class TestStatsServiceAllTimeAvg:
    """Tests for all_time_avg property."""

    def test_all_time_avg_zero_when_no_games(self, stats_service):
        """all_time_avg returns 0.0 when no games played."""
        assert stats_service.all_time_avg == 0.0

    @pytest.mark.asyncio
    async def test_all_time_avg_single_game(self, stats_service, sample_game_summary):
        """all_time_avg returns correct value for single game."""
        await stats_service.record_game(sample_game_summary)

        assert stats_service.all_time_avg == 52.5

    @pytest.mark.asyncio
    async def test_all_time_avg_weighted_multiple_games(self, stats_service):
        """all_time_avg is weighted by rounds * players."""
        # Game 1: 10 rounds, 4 players, 52.5 avg (weight: 40)
        await stats_service.record_game({
            "playlist": "test1",
            "rounds": 10,
            "player_count": 4,
            "winner": "A",
            "winner_score": 100,
            "total_points": 2100,  # 52.5 avg
        })

        # Game 2: 5 rounds, 2 players, 40.0 avg (weight: 10)
        await stats_service.record_game({
            "playlist": "test2",
            "rounds": 5,
            "player_count": 2,
            "winner": "B",
            "winner_score": 100,
            "total_points": 400,  # 40.0 avg
        })

        # Weighted avg: (52.5 * 40 + 40.0 * 10) / 50 = (2100 + 400) / 50 = 50.0
        assert stats_service.all_time_avg == 50.0


@pytest.mark.unit
class TestStatsServiceSummaryHistory:
    """Tests for get_summary() and get_history() methods."""

    @pytest.mark.asyncio
    async def test_get_summary(self, stats_service, sample_game_summary):
        """get_summary() returns correct summary data."""
        await stats_service.record_game(sample_game_summary)

        summary = await stats_service.get_summary()

        assert summary["games_played"] == 1
        assert summary["highest_avg_score"] == 52.5
        assert summary["all_time_avg"] == 52.5

    @pytest.mark.asyncio
    async def test_get_history_returns_recent_games(self, stats_service):
        """get_history() returns games in newest-first order."""
        for i in range(5):
            await stats_service.record_game({
                "playlist": f"playlist-{i}",
                "rounds": 10,
                "player_count": 4,
                "winner": "Test",
                "winner_score": 100,
                "total_points": 1000 + i * 100,
            })

        history = await stats_service.get_history(limit=3)

        assert len(history) == 3
        # Newest first - playlist-4 should be first
        assert history[0]["playlist"] == "playlist-4"
        assert history[2]["playlist"] == "playlist-2"

    @pytest.mark.asyncio
    async def test_get_history_respects_limit(self, stats_service, sample_game_summary):
        """get_history() respects limit parameter."""
        for _ in range(15):
            await stats_service.record_game(sample_game_summary)

        history = await stats_service.get_history(limit=10)

        assert len(history) == 10


# =============================================================================
# SONG DIFFICULTY TESTS (Story 15.1)
# =============================================================================


@pytest.mark.unit
class TestSongDifficultyRecording:
    """Tests for record_song_result method (Story 15.1 AC3)."""

    @pytest.mark.asyncio
    async def test_record_song_result_creates_entry(self, stats_service):
        """record_song_result() creates song entry with correct stats."""
        player_results = [
            {"submitted": True, "years_off": 0},
            {"submitted": True, "years_off": 2},
            {"submitted": False, "years_off": 0},
        ]

        await stats_service.record_song_result("spotify:track:abc123", player_results)

        songs = stats_service._stats["songs"]
        assert "spotify_track_abc123" in songs
        song = songs["spotify_track_abc123"]
        assert song["times_played"] == 1
        assert song["total_guesses"] == 2
        assert song["correct_guesses"] == 2  # Both within threshold (0 and 2)

    @pytest.mark.asyncio
    async def test_record_song_result_accumulates_stats(self, stats_service):
        """record_song_result() accumulates stats across multiple rounds."""
        # First round: 2 guesses, both correct (within 3 years)
        await stats_service.record_song_result("spotify:track:abc123", [
            {"submitted": True, "years_off": 1},
            {"submitted": True, "years_off": 2},
        ])

        # Second round: 2 guesses, 1 correct
        await stats_service.record_song_result("spotify:track:abc123", [
            {"submitted": True, "years_off": 0},
            {"submitted": True, "years_off": 10},
        ])

        song = stats_service._stats["songs"]["spotify_track_abc123"]
        assert song["times_played"] == 2
        assert song["total_guesses"] == 4
        assert song["correct_guesses"] == 3  # 3 within threshold

    @pytest.mark.asyncio
    async def test_record_song_result_correct_threshold(self, stats_service):
        """record_song_result() uses CORRECT_GUESS_THRESHOLD (3 years)."""
        player_results = [
            {"submitted": True, "years_off": 3},  # Exactly 3 = correct
            {"submitted": True, "years_off": 4},  # 4 = not correct
        ]

        await stats_service.record_song_result("spotify:track:test", player_results)

        song = stats_service._stats["songs"]["spotify_track_test"]
        assert song["correct_guesses"] == 1  # Only the 3-year-off guess

    @pytest.mark.asyncio
    async def test_record_song_result_tracks_total_years_off(self, stats_service):
        """record_song_result() tracks total years off for future analytics."""
        player_results = [
            {"submitted": True, "years_off": 5},
            {"submitted": True, "years_off": 10},
        ]

        await stats_service.record_song_result("spotify:track:test", player_results)

        song = stats_service._stats["songs"]["spotify_track_test"]
        assert song["total_years_off"] == 15


@pytest.mark.unit
class TestSongDifficultyCalculation:
    """Tests for get_song_difficulty method (Story 15.1 AC1, AC2, AC4)."""

    @pytest.mark.asyncio
    async def test_get_song_difficulty_returns_none_insufficient_plays(self, stats_service):
        """get_song_difficulty() returns None when times_played < 3 (AC4)."""
        # Only play once
        await stats_service.record_song_result("spotify:track:test", [
            {"submitted": True, "years_off": 0},
        ])

        result = stats_service.get_song_difficulty("spotify:track:test")

        assert result is None  # Need 3 plays minimum

    @pytest.mark.asyncio
    async def test_get_song_difficulty_returns_none_unknown_song(self, stats_service):
        """get_song_difficulty() returns None for unknown song URI."""
        result = stats_service.get_song_difficulty("spotify:track:unknown")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_song_difficulty_easy_high_accuracy(self, stats_service):
        """get_song_difficulty() returns 1 star (easy) for high accuracy (70%+)."""
        # Play song 3 times with high accuracy
        for _ in range(3):
            await stats_service.record_song_result("spotify:track:easy", [
                {"submitted": True, "years_off": 1},
                {"submitted": True, "years_off": 2},
                {"submitted": True, "years_off": 1},
            ])

        result = stats_service.get_song_difficulty("spotify:track:easy")

        assert result is not None
        assert result["stars"] == 1
        assert result["label"] == "easy"
        assert result["accuracy"] >= 70.0

    @pytest.mark.asyncio
    async def test_get_song_difficulty_medium_moderate_accuracy(self, stats_service):
        """get_song_difficulty() returns 2 stars (medium) for 40-69% accuracy."""
        # Play song 3 times with 50% accuracy
        for _ in range(3):
            await stats_service.record_song_result("spotify:track:medium", [
                {"submitted": True, "years_off": 1},   # correct
                {"submitted": True, "years_off": 10},  # wrong
            ])

        result = stats_service.get_song_difficulty("spotify:track:medium")

        assert result is not None
        assert result["stars"] == 2
        assert result["label"] == "medium"
        assert 40.0 <= result["accuracy"] < 70.0

    @pytest.mark.asyncio
    async def test_get_song_difficulty_hard_low_accuracy(self, stats_service):
        """get_song_difficulty() returns 3 stars (hard) for 20-39% accuracy."""
        # Play song 3 times with ~30% accuracy
        for _ in range(3):
            await stats_service.record_song_result("spotify:track:hard", [
                {"submitted": True, "years_off": 1},   # correct
                {"submitted": True, "years_off": 10},  # wrong
                {"submitted": True, "years_off": 15},  # wrong
            ])

        result = stats_service.get_song_difficulty("spotify:track:hard")

        assert result is not None
        assert result["stars"] == 3
        assert result["label"] == "hard"
        assert 20.0 <= result["accuracy"] < 40.0

    @pytest.mark.asyncio
    async def test_get_song_difficulty_extreme_very_low_accuracy(self, stats_service):
        """get_song_difficulty() returns 4 stars (extreme) for <20% accuracy."""
        # Play song 3 times with very low accuracy (less than 20%)
        for _ in range(3):
            await stats_service.record_song_result("spotify:track:extreme", [
                {"submitted": True, "years_off": 10},  # wrong
                {"submitted": True, "years_off": 15},  # wrong
                {"submitted": True, "years_off": 20},  # wrong
                {"submitted": True, "years_off": 25},  # wrong
                {"submitted": True, "years_off": 30},  # wrong
                {"submitted": True, "years_off": 2},   # correct - 1 of 6 = 16.7%
            ])

        result = stats_service.get_song_difficulty("spotify:track:extreme")

        assert result is not None
        assert result["stars"] == 4
        assert result["label"] == "extreme"
        assert result["accuracy"] < 20.0

    @pytest.mark.asyncio
    async def test_get_song_difficulty_threshold_boundary_70(self, stats_service):
        """get_song_difficulty() returns 1 star at exactly 70% accuracy."""
        # 7 correct out of 10 = 70% exactly
        for _ in range(3):
            await stats_service.record_song_result("spotify:track:boundary70", [
                {"submitted": True, "years_off": 1},
                {"submitted": True, "years_off": 1},
                {"submitted": True, "years_off": 1},
                {"submitted": True, "years_off": 1},
                {"submitted": True, "years_off": 1},
                {"submitted": True, "years_off": 1},
                {"submitted": True, "years_off": 1},
                {"submitted": True, "years_off": 10},
                {"submitted": True, "years_off": 10},
                {"submitted": True, "years_off": 10},
            ])

        result = stats_service.get_song_difficulty("spotify:track:boundary70")

        assert result is not None
        assert result["stars"] == 1

    @pytest.mark.asyncio
    async def test_get_song_difficulty_returns_times_played(self, stats_service):
        """get_song_difficulty() includes times_played in response."""
        for _ in range(5):
            await stats_service.record_song_result("spotify:track:test", [
                {"submitted": True, "years_off": 2},
            ])

        result = stats_service.get_song_difficulty("spotify:track:test")

        assert result is not None
        assert result["times_played"] == 5
