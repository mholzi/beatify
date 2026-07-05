"""Tests for Beatify stats service (custom_components/beatify/services/stats.py)."""

from __future__ import annotations

import asyncio
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


# ---------------------------------------------------------------------------
# StatsService.save — atomic write (#1386)
# ---------------------------------------------------------------------------


def _make_real_fs_service(stats_path) -> StatsService:
    """Create a StatsService that writes to a real on-disk stats.json path."""
    mock_hass = MagicMock()
    mock_hass.config.path.return_value = str(stats_path)
    # Run executor jobs inline on the calling thread.
    mock_hass.async_add_executor_job = AsyncMock(
        side_effect=lambda fn, *args: fn(*args)
    )
    return StatsService(mock_hass)


class TestAtomicSave:
    """save() must write stats.json atomically (temp file + os.replace)."""

    @pytest.mark.asyncio
    async def test_save_uses_temp_then_replace(self, tmp_path):
        import json as _json

        stats_path = tmp_path / "beatify" / "stats.json"
        service = _make_real_fs_service(stats_path)
        service._stats["all_time"]["games_played"] = 7

        await service.save()

        # Final file exists with the written content.
        assert stats_path.exists()
        data = _json.loads(stats_path.read_text())
        assert data["all_time"]["games_played"] == 7
        # No leftover temp file after a successful save.
        assert not (tmp_path / "beatify" / "stats.json.tmp").exists()

    @pytest.mark.asyncio
    async def test_crash_mid_write_leaves_old_file_intact(self, tmp_path):
        """A crash before os.replace must not corrupt the existing stats.json."""
        import json as _json

        stats_path = tmp_path / "beatify" / "stats.json"
        service = _make_real_fs_service(stats_path)

        # First, persist a valid file with real game history.
        service._stats["all_time"]["games_played"] = 42
        service._stats["games"] = [{"id": "keepme"}]
        await service.save()
        good_content = stats_path.read_text()
        assert _json.loads(good_content)["all_time"]["games_played"] == 42

        # Now simulate a crash mid-write: os.replace raises before the temp
        # file is promoted over the live stats.json.
        service._stats["all_time"]["games_played"] = 999

        def _boom(_src, _dst):
            raise OSError("simulated power loss mid-write")

        with patch("custom_components.beatify.services.stats.os.replace", _boom):
            # save() swallows OSError and logs it; it must not raise.
            await service.save()

        # The original file is untouched — history is NOT lost.
        assert stats_path.exists()
        assert stats_path.read_text() == good_content
        reloaded = _json.loads(stats_path.read_text())
        assert reloaded["all_time"]["games_played"] == 42
        assert reloaded["games"] == [{"id": "keepme"}]

    @pytest.mark.asyncio
    async def test_save_is_serialized_by_lock(self, tmp_path):
        """Concurrent save() calls must not interleave (lock held)."""
        stats_path = tmp_path / "beatify" / "stats.json"
        service = _make_real_fs_service(stats_path)

        in_flight = 0
        max_concurrent = 0

        async def _tracking_executor(fn, *args):
            nonlocal in_flight, max_concurrent
            in_flight += 1
            max_concurrent = max(max_concurrent, in_flight)
            # Yield control so a second save() could interleave if unlocked.
            await asyncio.sleep(0)
            try:
                return fn(*args)
            finally:
                in_flight -= 1

        service._hass.async_add_executor_job = AsyncMock(side_effect=_tracking_executor)

        await asyncio.gather(service.save(), service.save())

        # The lock guarantees the file-I/O sections never overlap.
        assert max_concurrent == 1


# ---------------------------------------------------------------------------
# TestScheduleSaveDirtyFlag — mutations during an in-flight save aren't dropped
# (#1402)
# ---------------------------------------------------------------------------


class TestScheduleSaveDirtyFlag:
    @pytest.mark.asyncio
    async def test_mutation_during_inflight_save_triggers_resave(self, tmp_path):
        """A schedule_save() during an in-flight save must cause a follow-up
        save so the later mutation reaches disk."""
        import json as _json

        stats_path = tmp_path / "beatify" / "stats.json"
        service = _make_real_fs_service(stats_path)

        # Block the first save inside the executor so we can mutate + re-schedule
        # while it is in flight.
        release = asyncio.Event()
        save_count = 0

        async def _gated_executor(fn, *args):
            nonlocal save_count
            # mkdir runs first; only gate the serialize-and-write call.
            if getattr(fn, "__name__", "") == "_serialize_and_write":
                save_count += 1
                if save_count == 1:
                    await release.wait()
            return fn(*args)

        service._hass.async_add_executor_job = AsyncMock(side_effect=_gated_executor)

        service._stats["all_time"]["games_played"] = 1
        # #1708: schedule_save() is now debounced; _schedule_save_now() owns the
        # immediate fire-and-forget + dirty-flag coalescing this test exercises.
        service._schedule_save_now()  # starts save #1 (gated)
        await asyncio.sleep(0)  # let the task reach the gate

        # Mutate AFTER save #1 snapshotted, and re-schedule.
        service._stats["all_time"]["games_played"] = 2
        service._schedule_save_now()  # in flight -> sets dirty flag
        assert service._save_dirty is True

        release.set()  # let save #1 finish -> done-callback re-schedules
        # Drain pending tasks.
        for _ in range(10):
            await asyncio.sleep(0)
            if service._save_task is not None:
                await service._save_task

        data = _json.loads(stats_path.read_text())
        assert data["all_time"]["games_played"] == 2
        assert save_count >= 2


# ---------------------------------------------------------------------------
# TestSaveSnapshotIsolation — save() must serialize a real snapshot, not a live
# reference, so concurrent loop mutations can't crash json.dumps (#1762)
# ---------------------------------------------------------------------------


class TestSaveSnapshotIsolation:
    @pytest.mark.asyncio
    async def test_concurrent_mutation_during_dump_does_not_lose_batch(self, tmp_path):
        """A mutation of self._stats while json.dumps runs must NOT raise
        'dictionary changed size during iteration' nor lose the batch — the
        executor must operate on an immutable deepcopy taken on the loop thread
        (#1762)."""
        import json as _json

        stats_path = tmp_path / "beatify" / "stats.json"
        service = _make_real_fs_service(stats_path)

        # Seed a realistic store with per-song entries (the dict record_song_result
        # mutates in place) plus a couple of games.
        for i in range(5):
            service._stats["songs"][f"song-{i}"] = {
                "times_played": i,
                "correct_guesses": i,
                "total_guesses": i,
            }
        service._stats["games"] = [{"id": f"g{i}"} for i in range(3)]
        service._stats["all_time"]["games_played"] = 3

        real_dumps = _json.dumps

        def _mutating_dumps(obj, *args, **kwargs):
            # Simulate the event loop mutating the LIVE store while the executor
            # serializes: record_song_result adds/updates song keys, record_game
            # appends/pops games. If ``obj`` were a live reference to
            # self._stats this iteration would raise RuntimeError.
            service._stats["songs"]["song-late"] = {"times_played": 99}
            del service._stats["songs"]["song-0"]
            service._stats["games"].append({"id": "g-late"})
            return real_dumps(obj, *args, **kwargs)

        with patch(
            "custom_components.beatify.services.stats.json.dumps",
            side_effect=_mutating_dumps,
        ):
            # Must not raise despite the concurrent mutation.
            await service.save()

        # The batch was written (not silently dropped) and reflects the snapshot
        # taken BEFORE the mid-dump mutation.
        assert stats_path.exists()
        data = _json.loads(stats_path.read_text())
        assert "song-late" not in data["songs"]
        assert "song-0" in data["songs"]
        assert len(data["games"]) == 3
        # A clean save leaves no retry pending.
        assert service._save_dirty is False

    @pytest.mark.asyncio
    async def test_snapshot_is_deepcopy_not_reference(self, tmp_path):
        """The object handed to json.dumps must be a distinct deepcopy, so
        nested containers aren't shared with the live store (#1762)."""
        import json as _json

        stats_path = tmp_path / "beatify" / "stats.json"
        service = _make_real_fs_service(stats_path)
        service._stats["songs"]["s1"] = {"times_played": 1}

        captured: dict = {}
        real_dumps = _json.dumps

        def _capturing_dumps(obj, *args, **kwargs):
            captured["obj"] = obj
            return real_dumps(obj, *args, **kwargs)

        with patch(
            "custom_components.beatify.services.stats.json.dumps",
            side_effect=_capturing_dumps,
        ):
            await service.save()

        snap = captured["obj"]
        assert snap is not service._stats
        assert snap["songs"] is not service._stats["songs"]
        assert snap["songs"]["s1"] is not service._stats["songs"]["s1"]
        # Mutating the live store after the snapshot must not touch the copy.
        service._stats["songs"]["s1"]["times_played"] = 999
        assert snap["songs"]["s1"]["times_played"] == 1

    @pytest.mark.asyncio
    async def test_serialize_runtimeerror_sets_dirty_for_retry(self, tmp_path):
        """Defense-in-depth: if serialization still raises RuntimeError/ValueError,
        save() must not propagate and must flag _save_dirty so the done-callback
        retries instead of dropping the batch (#1762)."""
        stats_path = tmp_path / "beatify" / "stats.json"
        service = _make_real_fs_service(stats_path)

        def _boom(*_args, **_kwargs):
            raise RuntimeError("dictionary changed size during iteration")

        with patch(
            "custom_components.beatify.services.stats.json.dumps",
            side_effect=_boom,
        ):
            # Must swallow the error, not raise.
            await service.save()

        assert service._save_dirty is True


class TestScheduleSaveDebounce:
    """#1708: per-round saves are debounced into a single write; game end and
    unload flush explicitly."""

    @pytest.mark.asyncio
    async def test_rapid_saves_coalesce_into_single_timer(self):
        from custom_components.beatify.services.stats import (
            STATS_SAVE_DEBOUNCE_SECONDS,
        )

        service = _make_service()
        service._hass.loop = MagicMock()
        handles = [MagicMock(name=f"h{i}") for i in range(3)]
        service._hass.loop.call_later.side_effect = handles

        with patch.object(service, "_schedule_save_now") as now:
            service.schedule_save()
            service.schedule_save()
            service.schedule_save()

            # Each call schedules a fresh timer and cancels the previous one, so
            # only the most recent timer survives — a burst of rounds ends in a
            # single pending write, not one per round.
            assert service._hass.loop.call_later.call_count == 3
            handles[0].cancel.assert_called_once()
            handles[1].cancel.assert_called_once()
            handles[2].cancel.assert_not_called()
            assert service._save_handle is handles[2]
            # No actual save has started yet — it is debounced.
            now.assert_not_called()

        # Firing the debounce callback kicks off exactly one immediate save.
        delay, fire = service._hass.loop.call_later.call_args.args
        assert delay == STATS_SAVE_DEBOUNCE_SECONDS
        with patch.object(service, "_schedule_save_now") as now:
            fire()
            now.assert_called_once()
        assert service._save_handle is None

    @pytest.mark.asyncio
    async def test_flush_cancels_pending_debounce_and_saves(self):
        service = _make_service()
        service._hass.loop = MagicMock()
        handle = MagicMock()
        service._hass.loop.call_later.return_value = handle

        with patch.object(service, "save", new_callable=AsyncMock) as save:
            service.schedule_save()
            assert service._save_handle is handle
            await service.async_flush()

        handle.cancel.assert_called_once()
        save.assert_awaited_once()
        assert service._save_handle is None

    @pytest.mark.asyncio
    async def test_shutdown_flushes_pending(self):
        service = _make_service()
        service._hass.loop = MagicMock()

        with patch.object(service, "save", new_callable=AsyncMock) as save:
            service.schedule_save()
            await service.async_shutdown()

        save.assert_awaited_once()
        assert service._save_handle is None

    @pytest.mark.asyncio
    async def test_record_game_flushes_immediately(self):
        service = _make_service()
        service._hass.loop = MagicMock()

        with patch.object(service, "save", new_callable=AsyncMock) as save:
            await service.record_game(_make_game_summary())

        # Game end is a flush point: written now, not left on the debounce timer.
        save.assert_awaited()
        assert service._save_handle is None


# ---------------------------------------------------------------------------
# TestPlaylistAvgScore — avg_score_per_round is maintained, not stuck at 0 (#1402)
# ---------------------------------------------------------------------------


class TestPlaylistAvgScore:
    def setup_method(self):
        self.service = _make_service()

    @pytest.mark.asyncio
    async def test_playlist_avg_score_updated(self):
        # rounds=5, players=2, total_points=200 -> avg_score_per_round = 20.0
        await self.service.record_game(_make_game_summary())
        ps = self.service._stats["playlists"]["80s Hits"]
        assert ps["avg_score_per_round"] == 20.0

    @pytest.mark.asyncio
    async def test_playlist_avg_score_weighted_across_games(self):
        # Game 1: avg 20.0, weight 10 (5*2).
        await self.service.record_game(_make_game_summary())
        # Game 2: rounds=10, players=1, total_points=100 -> avg 10.0, weight 10.
        await self.service.record_game(
            _make_game_summary(rounds=10, player_count=1, total_points=100)
        )
        ps = self.service._stats["playlists"]["80s Hits"]
        # (20*10 + 10*10) / 20 = 15.0
        assert ps["avg_score_per_round"] == 15.0


# ---------------------------------------------------------------------------
# TestGamesCap — detailed games list is bounded; all_time_avg survives (#1402)
# ---------------------------------------------------------------------------


class TestGamesCap:
    def setup_method(self):
        self.service = _make_service()

    @pytest.mark.asyncio
    async def test_games_list_capped(self):
        from custom_components.beatify.services.stats import MAX_DETAILED_GAMES

        # Record a few more than the cap.
        for _ in range(MAX_DETAILED_GAMES + 5):
            await self.service.record_game(_make_game_summary())
        assert len(self.service._stats["games"]) == MAX_DETAILED_GAMES

    @pytest.mark.asyncio
    async def test_all_time_avg_survives_cap(self):
        from custom_components.beatify.services.stats import MAX_DETAILED_GAMES

        # All games identical -> avg stays 20.0 even after capping drops the
        # earliest detailed entries (running aggregates back the average).
        for _ in range(MAX_DETAILED_GAMES + 50):
            await self.service.record_game(_make_game_summary())
        self.service._all_time_avg_cache = None
        assert round(self.service.all_time_avg, 2) == 20.0

    def test_legacy_stats_without_aggregates_still_compute_avg(self):
        """A pre-#1402 stats file (no total_weight) falls back to the games
        list so all_time_avg keeps working on upgrade."""
        self.service._stats = {
            "version": 1,
            "games": [
                {"rounds": 5, "player_count": 2, "avg_score_per_round": 30.0},
            ],
            "playlists": {},
            "all_time": {
                "games_played": 1,
                "highest_avg_score": 30.0,
                "highest_avg_game_id": "x",
            },
            "songs": {},
        }
        self.service._all_time_avg_cache = None
        assert self.service.all_time_avg == 30.0


# ---------------------------------------------------------------------------
# TestLoadUnreadableFile — OSError must not wipe the on-disk stats file (#1402)
# ---------------------------------------------------------------------------


class TestLoadUnreadableFile:
    @pytest.mark.asyncio
    async def test_oserror_on_read_starts_fresh_without_saving(self):
        service = _make_service()
        save_mock = AsyncMock()

        with (
            patch.object(type(service._stats_file), "exists", return_value=True),
            patch.object(
                type(service._stats_file),
                "read_text",
                side_effect=OSError("permission denied"),
            ),
            patch.object(service, "save", save_mock),
        ):
            # Must not raise.
            await service.load()

        # Fresh in-memory store, but no save() over the unreadable file.
        assert service._stats == service._empty_stats()
        save_mock.assert_not_awaited()
