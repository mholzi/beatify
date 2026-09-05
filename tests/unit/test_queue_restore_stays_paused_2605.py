"""#2605: the speaker must not keep playing after the game ends.

Found by the live test on v4.4.2-rc2 (2026-09-05). After `end-game` the restore
handed the host's queue back and logged ``Queue restored on … (paused)``, while
`media_player.esszimmer` reported ``playing`` seventy seconds later — three
times in a row, on two different tracks.

Two causes, both addressed here:

* the pause was fired with ``blocking=False`` and nobody read the state back,
* it ran *before* ``shuffle_set`` / ``repeat_set``, so anything those two do to
  the queue happened after the speaker had been asked to stop.

The old log line was written unconditionally in the ``else:`` branch — it
reported the intent, not the outcome, which is why the defect survived every
previous run of this file.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.beatify.services.media_player import MediaPlayerService

QUEUE = {
    "uri": "apple_music://track/1705321808",
    "name": "(I'll Never Be) María Magdalena",
    "elapsed_time": 0,
    "shuffle": False,
    "repeat_mode": "off",
}


def _hass(states: list[str]) -> MagicMock:
    """A hass whose speaker walks through ``states`` on successive reads.

    The last entry repeats forever, so a test can model "never stops" with a
    single element.
    """
    hass = MagicMock()
    hass.services.async_call = AsyncMock(return_value=None)
    seq = list(states)

    def _get(_entity_id):
        st = MagicMock()
        st.state = seq[0] if len(seq) == 1 else seq.pop(0)
        st.attributes = {"volume_level": 0.0}
        return st

    hass.states.get = MagicMock(side_effect=_get)
    return hass


def _service(hass) -> MediaPlayerService:
    return MediaPlayerService(
        hass, "media_player.esszimmer", platform="music_assistant"
    )


def _services_called(hass) -> list[tuple[str, str]]:
    return [c.args[:2] for c in hass.services.async_call.await_args_list]


class TestQueueRestoreStaysPaused:
    @pytest.mark.asyncio
    async def test_pause_is_the_last_thing_that_happens(self):
        """Shuffle and repeat run BEFORE the pause, not after it.

        Ordering is the half of the fix a state check cannot catch: with the
        pause in the middle, a speaker that resumes on ``repeat_set`` ends up
        playing while every individual call succeeded.
        """
        hass = _hass(["playing", "paused"])
        svc = _service(hass)

        assert await svc._restore_queue_on("media_player.esszimmer", QUEUE) is True

        calls = _services_called(hass)
        pause_at = calls.index(("media_player", "media_pause"))
        for domain, service in (
            ("media_player", "shuffle_set"),
            ("media_player", "repeat_set"),
        ):
            assert (domain, service) in calls, f"{service} was not called at all"
            assert calls.index((domain, service)) < pause_at, (
                f"{service} runs after the pause and can undo it"
            )

    @pytest.mark.asyncio
    async def test_pause_is_retried_when_the_speaker_keeps_playing(self):
        """A pause that does not take is sent once more.

        This is the live symptom: the call returns, nothing changes, and the
        old code moved on regardless.
        """
        hass = _hass(["playing"])  # never stops
        svc = _service(hass)

        await svc._restore_queue_on("media_player.esszimmer", QUEUE)

        pauses = [
            c for c in _services_called(hass) if c == ("media_player", "media_pause")
        ]
        assert len(pauses) == 2, f"expected one retry, got {len(pauses)} pause call(s)"

    @pytest.mark.asyncio
    async def test_no_retry_when_the_first_pause_lands(self):
        """The common case must not pay for the fix.

        A retry on every teardown would add seconds to every game end for a
        fault that is rare.
        """
        hass = _hass(["playing", "paused"])
        svc = _service(hass)

        await svc._restore_queue_on("media_player.esszimmer", QUEUE)

        pauses = [
            c for c in _services_called(hass) if c == ("media_player", "media_pause")
        ]
        assert len(pauses) == 1

    @pytest.mark.asyncio
    async def test_a_vanished_entity_does_not_hold_up_the_teardown(self):
        """``states.get`` returning None means there is nothing left to pause."""
        hass = _hass(["playing", "paused"])
        hass.states.get = MagicMock(return_value=None)
        svc = _service(hass)

        # Would hang for two full confirm windows if None were treated as "still playing".
        assert await svc._restore_queue_on("media_player.esszimmer", QUEUE) is True

    @pytest.mark.asyncio
    async def test_the_log_reports_the_outcome_not_the_intent(self, caplog):
        """The line that hid this defect for months.

        It said "(paused)" from inside the ``else:`` branch, so it was true of
        the attempt and false of the room.
        """
        hass = _hass(["playing"])  # never stops
        svc = _service(hass)

        with caplog.at_level("INFO"):
            await svc._restore_queue_on("media_player.esszimmer", QUEUE)

        restored = [r for r in caplog.records if "Queue restored on" in r.getMessage()]
        assert restored, "no restore line was logged at all"
        assert (
            "paused" not in restored[-1].getMessage().split("—")[0].lower()
            or "STILL PLAYING" in restored[-1].getMessage()
        ), "the log claims the speaker is paused while it is still playing"
