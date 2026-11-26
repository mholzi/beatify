"""#3628: abandoned starts that land after the game ended must stay silent.

v5.1.0-rc8 live test (Spotify rate limited, Esszimmer + Küche grouped): two
songs Beatify gave up on during the game started 30-60 s after end-game and
played on both speakers, because the queue restore forgets the abandoned
starts and its pause guard stops after 14 s. The end-game now cancels on the
target and its group members and keeps a watch for the rest of the window.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.beatify.services.media_player import MediaPlayerService
from custom_components.beatify.services.playback import music_assistant as ma
from tests.unit.test_ma_stale_start_3278 import (
    CURRENT,
    ENTITY,
    SKIPPED,
    _event,
    _Harness,
    _skip_then_play,
    _state,
)

KITCHEN = "media_player.kuche_2"


def _grouped(h: _Harness) -> None:
    grouped = _state("playing", "Celebration", "spotify://track/host", "t5")
    grouped.attributes["group_members"] = [ENTITY, KITCHEN]
    h.hass.states.get = MagicMock(side_effect=lambda _e: grouped)


def _stops(h: _Harness) -> list[str]:
    return [c.args[2]["entity_id"] for c in h.calls("media_player", "media_stop")]


@pytest.mark.asyncio
async def test_end_game_cancels_on_the_target_and_every_group_member():
    h = _Harness()
    with patch.object(ma, "async_track_state_change_event", h.track):
        await _skip_then_play(h)
        _grouped(h)
        h.hass.services.async_call.reset_mock()
        assert await h.strategy.silence_late_starts() is True
    assert sorted(_stops(h)) == [ENTITY, KITCHEN]
    cleared = [
        c.args[2]["entity_id"] for c in h.calls("media_player", "clear_playlist")
    ]
    assert sorted(cleared) == [ENTITY, KITCHEN]


@pytest.mark.asyncio
async def test_late_start_after_end_game_is_stopped_on_the_speaker_it_hit():
    h = _Harness()
    with patch.object(ma, "async_track_state_change_event", h.track):
        await _skip_then_play(h)
        _grouped(h)
        await h.strategy.silence_late_starts()
        h.strategy.forget_pending_starts()  # what restore_queue does next
        watch, _ = h.subs[-1]
        h.hass.services.async_call.reset_mock()

        ev = _event(_state("playing", "Bello e impossibile", SKIPPED, "t9"))
        ev.data["entity_id"] = KITCHEN
        watch(ev)
        await h.run_tasks()
    assert _stops(h) == [KITCHEN]


@pytest.mark.asyncio
async def test_other_music_after_end_game_is_left_alone():
    """The restored host queue (or anything else) is not ours to stop."""
    h = _Harness()
    with patch.object(ma, "async_track_state_change_event", h.track):
        await _skip_then_play(h)
        _grouped(h)
        await h.strategy.silence_late_starts()
        watch, _ = h.subs[-1]
        h.hass.services.async_call.reset_mock()
        watch(_event(_state("playing", "Celebration", "spotify://track/host", "t6")))
        watch(_event(_state("paused", "Bello e impossibile", SKIPPED, "t7")))
        await h.run_tasks()
    assert _stops(h) == []


@pytest.mark.asyncio
async def test_watch_survives_forget_and_is_capped_and_expires():
    h = _Harness()
    with patch.object(ma, "async_track_state_change_event", h.track):
        await _skip_then_play(h)
        await h.strategy.silence_late_starts()
        _, unsub = h.subs[-1]
        h.strategy.forget_pending_starts()
        unsub.assert_not_called()  # outlives the #3278 guard teardown
        watch, _ = h.subs[-1]
        h.hass.services.async_call.reset_mock()
        for i in range(ma.MA_ENDGAME_MAX_STOPS + 3):
            watch(_event(_state("playing", "Bello", SKIPPED, f"t{i}")))
        await h.run_tasks()
        assert len(_stops(h)) == ma.MA_ENDGAME_MAX_STOPS
        h.strategy._disarm_endgame_watch()
        unsub.assert_called_once()


@pytest.mark.asyncio
async def test_new_game_disarms_the_watch():
    h = _Harness()
    with patch.object(ma, "async_track_state_change_event", h.track):
        await _skip_then_play(h)
        await h.strategy.silence_late_starts()
        _, unsub = h.subs[-1]
        with patch.object(ma, "MA_PLAYBACK_TIMEOUT", 0.05):
            await h.strategy.play({"title": "X", "artist": "Y", "uri": CURRENT})
    unsub.assert_called()


@pytest.mark.asyncio
async def test_nothing_abandoned_means_nothing_happens():
    """Off path: an ordinary end-game issues no extra calls and arms nothing."""
    h = _Harness()
    with patch.object(ma, "async_track_state_change_event", h.track):
        assert await h.strategy.silence_late_starts() is False
    assert h.subs == []
    assert h.hass.services.async_call.await_count == 0


@pytest.mark.asyncio
async def test_restore_queue_silences_before_it_forgets():
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    svc = MediaPlayerService(hass, ENTITY, platform="music_assistant")
    order: list[str] = []
    svc._strategy.silence_late_starts = AsyncMock(
        side_effect=lambda: order.append("silence")
    )
    svc._strategy.forget_pending_starts = MagicMock(
        side_effect=lambda: order.append("forget")
    )
    await svc.restore_queue()
    assert order == ["silence", "forget"]


@pytest.mark.asyncio
async def test_a_failing_silence_does_not_block_the_restore():
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    svc = MediaPlayerService(hass, ENTITY, platform="music_assistant")
    svc._strategy.silence_late_starts = AsyncMock(side_effect=RuntimeError("boom"))
    svc._strategy.forget_pending_starts = MagicMock()
    await svc.restore_queue()
    svc._strategy.forget_pending_starts.assert_called_once()
