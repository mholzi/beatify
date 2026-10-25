"""#3283: state listeners must run where Home Assistant really runs them.

The #3278 stale-start guard never worked on a real install. Its listener was a
plain function, and ``async_track_state_change_event`` hands a plain function to
a ``SyncWorker`` thread. There ``asyncio.get_event_loop()`` raised "There is no
current event loop in thread 'SyncWorker_15'" on every state change, so a song
Beatify had abandoned took over the speaker and nothing corrected it (3 of 15
rounds in the v4.8.6-rc3 live test).

The #3278 tests called the listener straight from the event loop, which is why
they passed. The tests here dispatch it the way Home Assistant does: a function
marked with ``@callback`` is called in the loop, anything else goes to an
executor thread.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock, patch

import pytest

from custom_components.beatify.services.media_player import MediaPlayerService
from custom_components.beatify.services.playback import music_assistant as ma

from .test_ma_stale_start_3278 import (
    CURRENT,
    SKIPPED,
    _event,
    _Harness,
    _skip_then_play,
    _song,
    _state,
)

# Home Assistant's executor threads are called SyncWorker_N.
_SYNC_WORKER = ThreadPoolExecutor(max_workers=2, thread_name_prefix="SyncWorker")


class _HaDispatch:
    """``async_track_state_change_event`` with Home Assistant's job dispatch.

    ``HassJob`` classifies the action: ``@callback`` (the ``_hass_callback``
    marker) runs in the event loop, a coroutine function becomes a task, and a
    plain function runs via ``loop.run_in_executor`` in a worker thread.
    """

    def __init__(self) -> None:
        self.listeners: list = []
        self.futures: list = []

    def track(self, _hass, _entities, action):
        self.listeners.append(action)
        return MagicMock()

    def fire(self, action, ev) -> None:
        loop = asyncio.get_running_loop()
        if getattr(action, "_hass_callback", False):
            action(ev)
        elif asyncio.iscoroutinefunction(action):
            self.futures.append(loop.create_task(action(ev)))
        else:
            self.futures.append(loop.run_in_executor(_SYNC_WORKER, action, ev))

    async def settle(self) -> None:
        """Wait for thread-run listeners; re-raises what they raised."""
        while self.futures:
            await self.futures.pop(0)


@pytest.mark.asyncio
async def test_guard_corrects_a_late_takeover_when_dispatched_like_ha():
    """The rc3 scenario, with the listener dispatched the way HA does it."""
    h = _Harness()
    ha = _HaDispatch()
    with patch.object(ma, "async_track_state_change_event", ha.track):
        await _skip_then_play(h)
        guard = ha.listeners[-1]
        plays_before = len(h.calls("music_assistant", "play_media"))

        # ~2 s after the round's song was confirmed, MA delivers the old one.
        ha.fire(guard, _event(_state("playing", "Bello e impossibile", SKIPPED, "t2")))
        await ha.settle()
        await h.run_tasks()

    plays = h.calls("music_assistant", "play_media")
    assert len(plays) == plays_before + 1
    assert plays[-1].args[2]["media_id"] == CURRENT


@pytest.mark.asyncio
async def test_start_wait_confirms_through_the_listener_with_an_abandoned_start():
    """The start wait's own listener reads the abandoned starts too (#3278).

    The confirming state arrives as an event, with a content id that is not
    one of the requested URI's tokens (MA reports its own id). Run in a worker
    thread the stale check raised, the start was never confirmed and the song
    was skipped.
    """
    h = _Harness()
    ha = _HaDispatch()
    with (
        patch.object(ma, "async_track_state_change_event", ha.track),
        patch.object(ma, "MA_PLAYBACK_TIMEOUT", 0.05),
    ):
        assert await h.strategy.play(_song(SKIPPED, "Bello e impossibile")) is False

    h.hass.states.get = MagicMock(return_value=_state("idle", ""))
    with (
        patch.object(ma, "async_track_state_change_event", ha.track),
        patch.object(ma, "MA_PLAYBACK_TIMEOUT", 2.0),
    ):
        listeners_before = len(ha.listeners)
        task = asyncio.create_task(h.strategy.play(_song(CURRENT, "The Riddle")))
        for _ in range(200):
            if len(ha.listeners) > listeners_before:
                break
            await asyncio.sleep(0.005)
        wait_listener = ha.listeners[-1]

        ha.fire(
            wait_listener,
            _event(_state("playing", "The Riddle", "library://track/4711", "t1")),
        )
        await ha.settle()
        assert await asyncio.wait_for(task, timeout=3.0) is True


@pytest.mark.asyncio
async def test_metadata_wait_listener_runs_in_the_event_loop():
    """The album-art wait sets asyncio.Events, which only the loop may do."""
    hass = MagicMock()
    hass.states.get = MagicMock(return_value=None)
    svc = MediaPlayerService(hass, "media_player.test")
    ha = _HaDispatch()
    with patch(
        "custom_components.beatify.services.media_player."
        "async_track_state_change_event",
        ha.track,
    ):
        task = asyncio.create_task(svc.wait_for_metadata_update("spotify:track:X"))
        for _ in range(200):
            if ha.listeners:
                break
            await asyncio.sleep(0.005)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert getattr(ha.listeners[0], "_hass_callback", False)
