"""Tests for Beatify stats service (custom_components/beatify/services/stats.py)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.beatify.services.stats import StatsService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_hass() -> MagicMock:
    """Create a mock HomeAssistant instance for StatsService."""
    mock_hass = MagicMock()
    mock_hass.config.path.return_value = "/tmp/test_beatify/stats.json"
    mock_hass.async_add_executor_job = AsyncMock(
        side_effect=lambda fn, *args: fn(*args)
    )
    return mock_hass


def _make_service() -> StatsService:
    """Create a StatsService with mocked hass."""
    return StatsService(_make_mock_hass())


def _make_game_summary(**overrides) -> dict:
    """Create a default game summary dict with optional overrides."""
    base = {
        "playlist": "80s Hits",
        "rounds": 5,
        "player_count": 2,
        "winner": "Alice",
        "winner_score": 100,
        "total_points": 200,
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# StatsService._empty_stats
# ---------------------------------------------------------------------------


class TestEmptyStats:
    def setup_method(self):
        self.service = _make_service()

    def test_returns_correct_structure(self):
        stats = self.service._empty_stats()
        assert stats["version"] == 1
        assert stats["games"] == []
        assert stats["playlists"] == {}
        assert stats["songs"] == {}

    def test_all_time_defaults(self):
        stats = self.service._empty_stats()
        all_time = stats["all_time"]
        assert all_time["games_played"] == 0
        assert all_time["highest_avg_score"] == 0.0
        assert all_time["highest_avg_game_id"] is None

    def test_returns_fresh_copy(self):
        """Each call should return a new dict, not the same reference."""
        stats1 = self.service._empty_stats()
        stats2 = self.service._empty_stats()
        assert stats1 is not stats2
        stats1["games"].append("test")
        assert len(stats2["games"]) == 0


# ---------------------------------------------------------------------------
# StatsService.record_game
# ---------------------------------------------------------------------------


class TestRecordGame:
    def setup_method(self):
        self.service = _make_service()

    @pytest.mark.asyncio
    async def test_records_game_entry(self):
        with patch.object(self.service, "save", new_callable=AsyncMock):
            await self.service.record_game(_make_game_summary())
        assert len(self.service._stats["games"]) == 1
        game = self.service._stats["games"][0]
        assert game["playlist"] == "80s Hits"
        assert game["rounds"] == 5
        assert game["player_count"] == 2
        assert game["winner"] == "Alice"

    @pytest.mark.asyncio
    async def test_updates_playlist_stats(self):
        with patch.object(self.service, "save", new_callable=AsyncMock):
            await self.service.record_game(_make_game_summary())
        playlist = self.service._stats["playlists"]["80s Hits"]
        assert playlist["times_played"] == 1
        assert playlist["total_rounds"] == 5

    @pytest.mark.asyncio
    async def test_updates_all_time_stats(self):
        with patch.object(self.service, "save", new_callable=AsyncMock):
            await self.service.record_game(_make_game_summary())
        all_time = self.service._stats["all_time"]
        assert all_time["games_played"] == 1

    @pytest.mark.asyncio
    async def test_calculates_avg_score_per_round(self):
        with patch.object(self.service, "save", new_callable=AsyncMock):
            await self.service.record_game(_make_game_summary())
        game = self.service._stats["games"][0]
        # 200 total / (5 rounds * 2 players) = 20.0
        assert game["avg_score_per_round"] == 20.0

    @pytest.mark.asyncio
    async def test_skips_recording_zero_players(self):
        summary = _make_game_summary(player_count=0)
        with patch.object(self.service, "save", new_callable=AsyncMock) as mock_save:
            result = await self.service.record_game(summary)
        assert len(self.service._stats["games"]) == 0
        mock_save.assert_not_awaited()
        assert result["is_first_game"] is True

    @pytest.mark.asyncio
    async def test_handles_division_by_zero_rounds(self):
        summary = _make_game_summary(rounds=0, player_count=2)
        with patch.object(self.service, "save", new_callable=AsyncMock):
            await self.service.record_game(summary)
        game = self.service._stats["games"][0]
        assert game["avg_score_per_round"] == 0.0

    @pytest.mark.asyncio
    async def test_returns_comparison_dict(self):
        with patch.object(self.service, "save", new_callable=AsyncMock):
            result = await self.service.record_game(_make_game_summary())
        assert "avg_score" in result
        assert "all_time_avg" in result
        assert "is_first_game" in result
        assert "is_new_record" in result

    @pytest.mark.asyncio
    async def test_new_high_score_flagged(self):
        """First game sets a record, second higher game should flag is_new_record."""
        with patch.object(self.service, "save", new_callable=AsyncMock):
            await self.service.record_game(_make_game_summary(total_points=100))
            result = await self.service.record_game(
                _make_game_summary(total_points=500)
            )
        assert result["is_new_record"] is True

    @pytest.mark.asyncio
    async def test_multiple_games_increment_count(self):
        with patch.object(self.service, "save", new_callable=AsyncMock):
            await self.service.record_game(_make_game_summary())
            await self.service.record_game(_make_game_summary())
        assert self.service._stats["all_time"]["games_played"] == 2
        assert len(self.service._stats["games"]) == 2


# ---------------------------------------------------------------------------
# StatsService.get_game_comparison
# ---------------------------------------------------------------------------


class TestGetGameComparison:
    def setup_method(self):
        self.service = _make_service()

    def test_first_game(self):
        comparison = self.service.get_game_comparison(20.0)
        assert comparison["is_first_game"] is True
        assert comparison["difference"] == 0.0
        assert comparison["is_above_average"] is False

    def test_above_average(self):
        # Simulate one prior game
        self.service._stats["games"].append(
            {"rounds": 5, "player_count": 2, "avg_score_per_round": 15.0}
        )
        self.service._stats["all_time"]["games_played"] = 1
        self.service._stats["all_time"]["highest_avg_score"] = 15.0
        comparison = self.service.get_game_comparison(20.0)
        assert comparison["is_first_game"] is False
        assert comparison["is_above_average"] is True
        assert comparison["difference"] == 5.0

    def test_below_average(self):
        self.service._stats["games"].append(
            {"rounds": 5, "player_count": 2, "avg_score_per_round": 25.0}
        )
        self.service._stats["all_time"]["games_played"] = 1
        self.service._stats["all_time"]["highest_avg_score"] = 25.0
        comparison = self.service.get_game_comparison(10.0)
        assert comparison["is_first_game"] is False
        assert comparison["is_above_average"] is False
        assert comparison["difference"] == -15.0

    def test_new_record(self):
        self.service._stats["games"].append(
            {"rounds": 5, "player_count": 2, "avg_score_per_round": 15.0}
        )
        self.service._stats["all_time"]["games_played"] = 1
        self.service._stats["all_time"]["highest_avg_score"] = 15.0
        comparison = self.service.get_game_comparison(30.0)
        assert comparison["is_new_record"] is True


# ---------------------------------------------------------------------------
# StatsService.get_motivational_message
# ---------------------------------------------------------------------------


class TestGetMotivationalMessage:
    def setup_method(self):
        self.service = _make_service()

    def test_first_game_message(self):
        comparison = {"is_first_game": True, "is_new_record": False, "difference": 0}
        msg = self.service.get_motivational_message(comparison)
        assert msg is not None
        assert msg["type"] == "first"

    def test_new_record_message(self):
        comparison = {"is_first_game": False, "is_new_record": True, "difference": 10}
        msg = self.service.get_motivational_message(comparison)
        assert msg is not None
        assert msg["type"] == "record"

    def test_strong_above_average(self):
        comparison = {"is_first_game": False, "is_new_record": False, "difference": 8.0}
        msg = self.service.get_motivational_message(comparison)
        assert msg is not None
        assert msg["type"] == "strong"
        assert "8.0" in msg["message"]

    def test_slight_above_average(self):
        comparison = {"is_first_game": False, "is_new_record": False, "difference": 3.0}
        msg = self.service.get_motivational_message(comparison)
        assert msg is not None
        assert msg["type"] == "above"

    def test_close_below_average(self):
        comparison = {
            "is_first_game": False,
            "is_new_record": False,
            "difference": -2.0,
        }
        msg = self.service.get_motivational_message(comparison)
        assert msg is not None
        assert msg["type"] == "close"

    def test_far_below_average_returns_none(self):
        comparison = {
            "is_first_game": False,
            "is_new_record": False,
            "difference": -10.0,
        }
        msg = self.service.get_motivational_message(comparison)
        assert msg is None


# ---------------------------------------------------------------------------
# StatsService.record_song_result
# ---------------------------------------------------------------------------


class TestRecordSongResult:
    def setup_method(self):
        self.service = _make_service()

    @pytest.mark.asyncio
    async def test_records_song_entry(self):
        player_results = [
            {"submitted": True, "years_off": 0},
            {"submitted": True, "years_off": 5},
        ]
        with patch.object(self.service, "save", new_callable=AsyncMock):
            await self.service.record_song_result(
                "spotify:track:abc123", player_results
            )
        song_key = "spotify_track_abc123"
        assert song_key in self.service._stats["songs"]
        song = self.service._stats["songs"][song_key]
        assert song["times_played"] == 1
        assert song["total_guesses"] == 2

    @pytest.mark.asyncio
    async def test_exact_match_tracked(self):
        player_results = [{"submitted": True, "years_off": 0}]
        with patch.object(self.service, "save", new_callable=AsyncMock):
            await self.service.record_song_result(
                "spotify:track:abc123", player_results
            )
        song = self.service._stats["songs"]["spotify_track_abc123"]
        assert song["exact_matches"] == 1
        assert song["correct_guesses"] == 1

    @pytest.mark.asyncio
    async def test_close_match_tracked(self):
        player_results = [{"submitted": True, "years_off": 2}]
        with patch.object(self.service, "save", new_callable=AsyncMock):
            await self.service.record_song_result(
                "spotify:track:abc123", player_results
            )
        song = self.service._stats["songs"]["spotify_track_abc123"]
        assert song["close_matches"] == 1
        assert song["correct_guesses"] == 1

    @pytest.mark.asyncio
    async def test_unsubmitted_player_ignored(self):
        player_results = [
            {"submitted": False, "years_off": 0},
            {"submitted": True, "years_off": 1},
        ]
        with patch.object(self.service, "save", new_callable=AsyncMock):
            await self.service.record_song_result(
                "spotify:track:abc123", player_results
            )
        song = self.service._stats["songs"]["spotify_track_abc123"]
        assert song["total_guesses"] == 1

    @pytest.mark.asyncio
    async def test_metadata_stored(self):
        player_results = [{"submitted": True, "years_off": 0}]
        metadata = {"title": "Bohemian Rhapsody", "artist": "Queen", "year": 1975}
        with patch.object(self.service, "save", new_callable=AsyncMock):
            await self.service.record_song_result(
                "spotify:track:abc123",
                player_results,
                song_metadata=metadata,
            )
        song = self.service._stats["songs"]["spotify_track_abc123"]
        assert song["title"] == "Bohemian Rhapsody"
        assert song["artist"] == "Queen"
        assert song["year"] == 1975

    @pytest.mark.asyncio
    async def test_playlist_tracking(self):
        player_results = [{"submitted": True, "years_off": 0}]
        with patch.object(self.service, "save", new_callable=AsyncMock):
            await self.service.record_song_result(
                "spotify:track:abc123",
                player_results,
                playlist_name="80s Hits",
            )
        song = self.service._stats["songs"]["spotify_track_abc123"]
        assert song["playlists"]["80s Hits"] == 1


# ---------------------------------------------------------------------------
# StatsService.get_song_difficulty
# ---------------------------------------------------------------------------


class TestGetSongDifficulty:
    def setup_method(self):
        self.service = _make_service()

    def test_insufficient_plays_returns_none(self):
        # Song played only once (MIN_PLAYS_FOR_DIFFICULTY = 3)
        self.service._stats["songs"]["spotify_track_abc"] = {
            "times_played": 1,
            "correct_guesses": 1,
            "total_guesses": 1,
        }
        result = self.service.get_song_difficulty("spotify:track:abc")
        assert result is None

    def test_no_data_returns_none(self):
        result = self.service.get_song_difficulty("spotify:track:unknown")
        assert result is None

    def test_zero_guesses_returns_none(self):
        self.service._stats["songs"]["spotify_track_abc"] = {
            "times_played": 5,
            "correct_guesses": 0,
            "total_guesses": 0,
        }
        result = self.service.get_song_difficulty("spotify:track:abc")
        assert result is None

    def test_easy_song_high_accuracy(self):
        """High accuracy (>=70%) should yield 1 star (easy)."""
        self.service._stats["songs"]["spotify_track_abc"] = {
            "times_played": 5,
            "correct_guesses": 9,
            "total_guesses": 10,
        }
        result = self.service.get_song_difficulty("spotify:track:abc")
        assert result is not None
        assert result["stars"] == 1
        assert result["label"] == "easy"
        assert result["accuracy"] == 90.0
        assert result["times_played"] == 5

    def test_hard_song_low_accuracy(self):
        """Low accuracy (20-40%) should yield 3 stars (hard)."""
        self.service._stats["songs"]["spotify_track_abc"] = {
            "times_played": 5,
            "correct_guesses": 3,
            "total_guesses": 10,
        }
        result = self.service.get_song_difficulty("spotify:track:abc")
        assert result is not None
        assert result["stars"] == 3
        assert result["label"] == "hard"


# ---------------------------------------------------------------------------
# StatsService.compute_song_stats
# ---------------------------------------------------------------------------


class TestComputeSongStats:
    def setup_method(self):
        self.service = _make_service()

    def _add_song(
        self,
        key,
        title,
        artist,
        year,
        times_played,
        exact,
        close,
        total_guesses,
        total_years_off=0,
        playlists=None,
    ):
        self.service._stats["songs"][key] = {
            "times_played": times_played,
            "correct_guesses": exact + close,
            "total_guesses": total_guesses,
            "total_years_off": total_years_off,
            "exact_matches": exact,
            "close_matches": close,
            "title": title,
            "artist": artist,
            "year": year,
            "playlists": playlists or {},
            "last_played": 1000,
        }

    def test_empty_songs_returns_nones(self):
        result = self.service.compute_song_stats()
        assert result["most_played"] is None
        assert result["hardest"] is None
        assert result["easiest"] is None
        assert result["by_playlist"] == []

    def test_most_played_identified(self):
        self._add_song(
            "s1", "Song A", "Artist A", 1980, 10, 5, 2, 10, playlists={"Rock": 10}
        )
        self._add_song(
            "s2", "Song B", "Artist B", 1990, 3, 2, 1, 5, playlists={"Rock": 3}
        )
        result = self.service.compute_song_stats()
        assert result["most_played"]["title"] == "Song A"

    def test_hardest_and_easiest(self):
        # Easy song: high accuracy
        self._add_song(
            "s1", "Easy Song", "Artist", 2000, 5, 8, 1, 10, playlists={"Pop": 5}
        )
        # Hard song: low accuracy
        self._add_song(
            "s2", "Hard Song", "Artist", 2010, 5, 0, 1, 10, playlists={"Pop": 5}
        )
        result = self.service.compute_song_stats()
        assert result["easiest"]["title"] == "Easy Song"
        assert result["hardest"]["title"] == "Hard Song"

    def test_songs_without_title_skipped(self):
        """Legacy entries without metadata should be excluded."""
        self.service._stats["songs"]["s1"] = {
            "times_played": 5,
            "correct_guesses": 3,
            "total_guesses": 5,
            "total_years_off": 10,
            "exact_matches": 1,
            "close_matches": 2,
            "title": "",
            "artist": "",
            "year": 0,
            "playlists": {},
            "last_played": 1000,
        }
        result = self.service.compute_song_stats()
        assert result["most_played"] is None

    def test_by_playlist_data(self):
        self._add_song(
            "s1",
            "Song A",
            "Artist A",
            1980,
            5,
            3,
            1,
            5,
            playlists={"Rock": 3, "Pop": 2},
        )
        result = self.service.compute_song_stats()
        names = [p["playlist_name"] for p in result["by_playlist"]]
        assert "Rock" in names
        assert "Pop" in names

    def test_playlist_filter(self):
        self._add_song(
            "s1",
            "Song A",
            "Artist A",
            1980,
            5,
            3,
            1,
            5,
            playlists={"Rock": 3, "Pop": 2},
        )
        result = self.service.compute_song_stats(playlist_filter="rock")
        assert len(result["by_playlist"]) == 1
        assert result["by_playlist"][0]["playlist_name"] == "Rock"


# ---------------------------------------------------------------------------
# StatsService.all_time_avg property
# ---------------------------------------------------------------------------


class TestAllTimeAvg:
    def setup_method(self):
        self.service = _make_service()

    def test_no_games_returns_zero(self):
        assert self.service.all_time_avg == 0.0

    def test_single_game(self):
        self.service._stats["games"].append(
            {"rounds": 5, "player_count": 2, "avg_score_per_round": 20.0}
        )
        assert self.service.all_time_avg == 20.0

    def test_weighted_average(self):
        """Average should be weighted by rounds * players."""
        # Game 1: 5 rounds, 2 players, avg 10 -> weight 10
        self.service._stats["games"].append(
            {"rounds": 5, "player_count": 2, "avg_score_per_round": 10.0}
        )
        # Game 2: 10 rounds, 1 player, avg 20 -> weight 10
        self.service._stats["games"].append(
            {"rounds": 10, "player_count": 1, "avg_score_per_round": 20.0}
        )
        # Weighted: (10*10 + 20*10) / (10+10) = 300/20 = 15.0
        assert self.service.all_time_avg == pytest.approx(15.0)

    def test_zero_weight_returns_zero(self):
        """Games with 0 rounds/players should not cause division by zero."""
        self.service._stats["games"].append(
            {"rounds": 0, "player_count": 0, "avg_score_per_round": 10.0}
        )
        assert self.service.all_time_avg == 0.0


# ---------------------------------------------------------------------------
# StatsService.games_played / get_summary / get_history
# ---------------------------------------------------------------------------


class TestMiscProperties:
    def setup_method(self):
        self.service = _make_service()

    def test_games_played_default(self):
        assert self.service.games_played == 0

    def test_games_played_after_recording(self):
        self.service._stats["all_time"]["games_played"] = 5
        assert self.service.games_played == 5

    @pytest.mark.asyncio
    async def test_get_summary(self):
        self.service._stats["all_time"]["games_played"] = 3
        self.service._stats["all_time"]["highest_avg_score"] = 25.5
        summary = await self.service.get_summary()
        assert summary["games_played"] == 3
        assert summary["highest_avg_score"] == 25.5

    @pytest.mark.asyncio
    async def test_get_history_returns_newest_first(self):
        self.service._stats["games"] = [
            {"id": "game1"},
            {"id": "game2"},
            {"id": "game3"},
        ]
        history = await self.service.get_history(limit=2)
        assert len(history) == 2
        assert history[0]["id"] == "game3"
        assert history[1]["id"] == "game2"

    @pytest.mark.asyncio
    async def test_get_history_default_limit(self):
        self.service._stats["games"] = [{"id": f"g{i}"} for i in range(15)]
        history = await self.service.get_history()
        assert len(history) == 10
