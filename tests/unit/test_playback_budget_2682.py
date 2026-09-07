"""#2682 — the playback budget, and telling a throttled start from a dead URI.

The live test of ``v4.4.3-rc1`` timed 23 playback starts on the real
installation: median 4s to first audio, one at 14.6s against a 15.0s deadline.
Nothing failed, which is the point — 0.4s of headroom is a measurement of how
hard Apple happened to be throttling that minute, not a safety margin.

Two things follow, and this file covers both:

* the budget is now derived from Music Assistant's retry schedule instead of
  from a round number, and
* a start that was rate-limited no longer reads in Beatify's own log like a
  track that does not exist.
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.beatify.services.media_player import MediaPlayerService
from custom_components.beatify.services.playback.music_assistant import (
    MA_FIRST_PLAY_TIMEOUT_FACTOR,
    MA_PLAYBACK_TIMEOUT,
    MA_SLOW_START_SECONDS,
    MA_THROTTLE_MEMORY_SECONDS,
)

# Music Assistant's Apple Music rate limiter sleeps 2^(N-1) - 1 seconds in
# total before its Nth attempt. The live log showed 1.0s, 2.0s and 4.3s for a
# nominal 1/2/4, so the real schedule runs about 7% above nominal.
_JITTER = 4.3 / 4.0
# What the failed API calls themselves cost by the time attempt 5 goes out
# (~0.8s each, four of them).
_FAILED_CALL_COST = 3.0
# The speaker's own time to first audio, measured across the 23 starts.
_WARM_SPEAKER = 4.0
_COLD_SPEAKER = 10.1  # #1936, a speaker that had been idle a while


def _ma_backoff_before_attempt(n: int) -> float:
    """Seconds Music Assistant spends asleep before its ``n``-th attempt."""
    return (2 ** (n - 1) - 1) * _JITTER


def _make_state(
    state: str = "idle",
    media_title: str = "Old Song",
    media_position: float = 0,
    media_position_updated_at: str = "2020-01-01T00:00:00+00:00",
) -> MagicMock:
    mock = MagicMock()
    mock.state = state
    mock.attributes = {
        "friendly_name": "Test Speaker",
        "volume_level": 0.5,
        "media_artist": "Test Artist",
        "media_title": media_title,
        "media_position": media_position,
        "media_position_updated_at": media_position_updated_at,
    }
    return mock


def _make_song(title: str = "New Song") -> dict:
    return {
        "title": title,
        "artist": "Test Artist",
        "uri": "spotify:track:abc123",
        "_resolved_uri": "spotify:track:abc123",
        "year": 1999,
    }


def _service(states) -> MediaPlayerService:
    """A Music Assistant service whose speaker walks ``states``."""
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    poll = 0

    def progression(*_args):
        nonlocal poll
        poll += 1
        return states[0] if poll <= 1 else states[1]

    hass.states.get = MagicMock(side_effect=progression)
    return MediaPlayerService(hass, "media_player.test", platform="music_assistant")


async def _play_and_time_out(svc: MediaPlayerService) -> bool:
    """Run one play_song that is guaranteed to exhaust its budget."""
    with (
        patch(
            "custom_components.beatify.services.media_player.asyncio.sleep",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.beatify.services.playback.music_assistant."
            "MA_PLAYBACK_TIMEOUT",
            0.01,
        ),
    ):
        return await svc.play_song(_make_song())


class TestBudgetArithmetic:
    """The budget is a point on Music Assistant's retry curve, not a round number."""

    def test_it_covers_a_start_throttled_to_mas_fifth_attempt(self):
        """~16.1s of backoff + ~3s of failed calls + a 4s warm start = ~23s."""
        fifth = _ma_backoff_before_attempt(5) + _FAILED_CALL_COST + _WARM_SPEAKER
        assert fifth == pytest.approx(23.1, abs=0.3)
        assert MA_PLAYBACK_TIMEOUT > fifth

    def test_it_stops_deliberately_short_of_the_sixth(self):
        """The sixth attempt lands near 40s.

        Waiting for it is the wrong trade: 40 seconds of silence in front of
        guests is worse than skipping the song, and three of those in a row is
        the two minutes before the game says anything at all.
        """
        sixth = _ma_backoff_before_attempt(6) + _FAILED_CALL_COST + _WARM_SPEAKER
        assert sixth == pytest.approx(40.3, abs=0.4)
        assert MA_PLAYBACK_TIMEOUT < sixth

    def test_the_measured_start_gains_ten_seconds_of_headroom(self):
        """The 14.6s start that produced the ticket had 0.4s left under 15s."""
        assert MA_PLAYBACK_TIMEOUT - 14.6 == pytest.approx(10.4)

    def test_the_first_play_budget_covers_a_cold_speaker_that_is_also_throttled(self):
        """#1936's factor still earns its keep after #2682 raised the base.

        A cold speaker (10.1s) throttled to the same fifth attempt is audible
        at ~29s — past the ordinary budget, inside the first-play one.
        """
        first_play = MA_PLAYBACK_TIMEOUT * MA_FIRST_PLAY_TIMEOUT_FACTOR
        cold_and_throttled = (
            _ma_backoff_before_attempt(5) + _FAILED_CALL_COST + _COLD_SPEAKER
        )
        assert cold_and_throttled == pytest.approx(29.2, abs=0.4)
        assert MA_PLAYBACK_TIMEOUT < cold_and_throttled < first_play

    def test_the_slow_start_mark_sits_above_every_healthy_start(self):
        """Twice the measured median: no warm start reaches it, every
        throttled one does."""
        assert MA_SLOW_START_SECONDS == pytest.approx(2 * _WARM_SPEAKER)
        assert MA_SLOW_START_SECONDS < 14.6

    def test_the_throttle_memory_outlives_the_gap_between_two_starts(self):
        """A round is up to 60s of music and the reveal dwell up to a 90s
        auto-advance, so a shorter memory would forget between rounds."""
        assert MA_THROTTLE_MEMORY_SECONDS >= 60 + 90


class TestSlowStartEvidence:
    """A slow but SUCCESSFUL start is the only in-band throttling signal."""

    @pytest.mark.asyncio
    async def test_a_slow_start_warns_and_is_remembered(self, caplog):
        svc = _service([_make_state("idle"), _make_state("idle")])
        with caplog.at_level(logging.WARNING):
            svc._strategy._note_start_duration(
                14.6, "apple_music://track/1", 25.0, first_play=False
            )
        assert svc._strategy._recent_slow_start() is not None
        assert "Rate Limiter" in caplog.text
        assert "14.6" in caplog.text

    @pytest.mark.asyncio
    async def test_a_fast_start_says_nothing_and_arms_nothing(self, caplog):
        svc = _service([_make_state("idle"), _make_state("idle")])
        with caplog.at_level(logging.DEBUG):
            svc._strategy._note_start_duration(
                4.0, "apple_music://track/1", 25.0, first_play=False
            )
        assert svc._strategy._recent_slow_start() is None
        assert "Rate Limiter" not in caplog.text

    @pytest.mark.asyncio
    async def test_a_slow_first_play_is_not_evidence(self):
        """#1936 measured a cold speaker at 10.1s with nothing throttling it.

        Counting that would arm the throttle explanation at the start of every
        single game, which would make it worthless.
        """
        svc = _service([_make_state("idle"), _make_state("idle")])
        svc._strategy._note_start_duration(
            11.0, "apple_music://track/1", 33.3, first_play=True
        )
        assert svc._strategy._recent_slow_start() is None

    @pytest.mark.asyncio
    async def test_the_evidence_expires(self):
        """Throttling is a property of the minute; an hour-old slow start says
        nothing about now."""
        svc = _service([_make_state("idle"), _make_state("idle")])
        now = asyncio.get_event_loop().time()
        svc._strategy._last_slow_start = (now - MA_THROTTLE_MEMORY_SECONDS - 1, 14.6)
        assert svc._strategy._recent_slow_start() is None


class TestIdleTimeoutIsClassified:
    """The speaker went idle. Was that Apple throttling, or a dead track?"""

    @pytest.mark.asyncio
    async def test_with_recent_evidence_it_reads_as_rate_limiting(self, caplog):
        svc = _service([_make_state("idle"), _make_state("idle")])
        svc._strategy._last_slow_start = (asyncio.get_event_loop().time(), 14.6)

        with caplog.at_level(logging.ERROR):
            assert await _play_and_time_out(svc) is False

        assert svc.last_failure_reason == "rate_limited"
        assert "Rate Limiter" in caplog.text
        assert "re-authenticating" in caplog.text  # ...as the thing NOT to do

    @pytest.mark.asyncio
    async def test_without_evidence_it_stays_the_old_systemic_error(self, caplog):
        svc = _service([_make_state("idle"), _make_state("idle")])

        with caplog.at_level(logging.ERROR):
            assert await _play_and_time_out(svc) is False

        assert svc.last_failure_reason == "error"
        assert "Rate Limiter" not in caplog.text
        assert "answering promptly" in caplog.text

    @pytest.mark.asyncio
    async def test_rate_limited_behaves_exactly_as_error_did(self):
        """#2682 changed the wording, not the game's behaviour.

        ``state_lifecycle`` gives only ``"unavailable"`` the free skip, so the
        new reason has to walk the counted path: skip, skip, pause. If it ever
        stopped counting, a genuinely dead provider on a household that had one
        slow start would never reach the recovery banner.
        """
        from custom_components.beatify.const import (  # noqa: PLC0415
            MAX_CONSECUTIVE_PLAYBACK_FAILURES,
        )
        from custom_components.beatify.game.state import GameState  # noqa: PLC0415
        from tests.conftest import make_game_state, make_songs  # noqa: PLC0415

        gs: GameState = make_game_state()
        gs.create_game(
            playlists=["test.json"],
            songs=make_songs(10),
            media_player="media_player.test",
            base_url="http://localhost:8123",
        )
        mock_service = MagicMock()
        mock_service.is_available.return_value = True
        mock_service.last_failure_reason = "rate_limited"
        mock_service.play_song = AsyncMock(return_value=False)
        gs._media_player_service = mock_service
        gs.media_player = "media_player.test"
        gs.platform = "music_assistant"
        gs.pause_game = AsyncMock()

        with patch(
            "custom_components.beatify.game.state.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            assert await gs.start_round() is False

        assert mock_service.play_song.await_count == MAX_CONSECUTIVE_PLAYBACK_FAILURES
        gs.pause_game.assert_awaited_once_with("media_player_error")


class TestStaleTitleTimeoutIsClassified:
    """The hardest pair to tell apart: both leave the prior track playing."""

    @staticmethod
    def _stuck_speaker():
        before = _make_state(
            "playing",
            media_title="Old Song",
            media_position=100,
            media_position_updated_at="2020-01-01T00:00:00+00:00",
        )
        after = _make_state(
            "playing",
            media_title="Old Song",  # never swapped
            media_position=101,
            media_position_updated_at="2020-01-01T00:00:05+00:00",
        )
        return [before, after]

    @pytest.mark.asyncio
    async def test_with_recent_evidence_it_names_the_rate_limiter(self, caplog):
        svc = _service(self._stuck_speaker())
        svc._strategy._last_slow_start = (asyncio.get_event_loop().time(), 14.6)

        with caplog.at_level(logging.WARNING):
            assert await _play_and_time_out(svc) is False

        assert "Rate Limiter" in caplog.text
        # Behaviour is unchanged — a skipped song either way (#795/#808).
        assert svc.last_failure_reason == "unavailable"

    @pytest.mark.asyncio
    async def test_without_evidence_it_stays_the_storefront_gap(self, caplog):
        svc = _service(self._stuck_speaker())

        with caplog.at_level(logging.WARNING):
            assert await _play_and_time_out(svc) is False

        assert "Rate Limiter" not in caplog.text
        assert "catalog/storefront" in caplog.text
        assert svc.last_failure_reason == "unavailable"
