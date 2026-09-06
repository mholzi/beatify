"""#2605: the speaker must not keep playing after the game ends.

Found by the live test on v4.4.2-rc2 (2026-09-05). After `end-game` the restore
handed the host's queue back and logged ``Queue restored on … (paused)``, while
`media_player.esszimmer` reported ``playing`` seventy seconds later — three
times in a row, on two different tracks.

**This issue was fixed once and came back.** The first attempt (#2606) moved
the pause behind ``shuffle_set`` / ``repeat_set`` and read the state back
instead of trusting ``blocking=False``. Measured against v4.4.2-rc3, the build
that contains it, the pause landed, was confirmed, and the speaker was playing
again five seconds later — for three minutes.

What #2606 got wrong was not the state check but its *window*. It looked for at
most two seconds and then stopped looking, and everything that restarts the
speaker on this hardware happens after that: a ``media_seek`` that was still in
flight (every call in the restore is ``blocking=False``, so the order of
submission is not the order of execution), a ``play_media`` that had not
finished loading the queue, or Music Assistant resuming its own queue.

So the guard here does not try to name the mechanism. It pauses, waits for the
speaker to go quiet, and then keeps watching for ``MA_PAUSE_SETTLE_HOLD``
seconds — pausing again on any relapse. The tests below model the device the
way the live run behaved: it obeys the pause, and then starts itself again.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.beatify.services.playback import queue_restore
from custom_components.beatify.services.playback.queue_restore import MaQueueRestorer

QUEUE = {
    "uri": "apple_music://track/1705321808",
    "name": "(I'll Never Be) María Magdalena",
    "elapsed_time": 0,
    "shuffle": False,
    "repeat_mode": "off",
}

ENTITY = "media_player.esszimmer"


@pytest.fixture(autouse=True)
def _fast_guard(monkeypatch):
    """Run the real guard on a compressed clock.

    The production budget is 5s of hold inside a 12s window — correct for a
    Sonos, unbearable in a unit suite. Only the durations shrink; the logic
    under test is untouched.
    """
    monkeypatch.setattr(queue_restore, "MA_PAUSE_CONFIRM_WAIT", 0.20)
    monkeypatch.setattr(queue_restore, "MA_PAUSE_SETTLE_HOLD", 0.30)
    monkeypatch.setattr(queue_restore, "MA_PAUSE_GUARD_WINDOW", 2.0)
    monkeypatch.setattr(queue_restore, "MA_PAUSE_POLL", 0.02)
    monkeypatch.setattr(queue_restore, "MA_QUEUE_RESTORE_WAIT", 0.20)
    monkeypatch.setattr(queue_restore, "MA_QUEUE_RESTORE_POLL", 0.02)


class Speaker:
    """A media player that obeys a pause and then starts itself again.

    This is the reopened #2605, reduced to its mechanism: ``media_pause``
    really does take — the state leaves ``playing`` — and ``resume_after``
    seconds later the device is playing once more. #2606 stopped looking two
    seconds after the pause, so from where it stood the teardown had worked.

    Args:
        resume_after: seconds between an accepted pause and the relapse.
        obeys_from: the pause command number from which the speaker stays
            quiet for good. ``None`` means it never settles.
    """

    def __init__(self, *, resume_after: float, obeys_from: int | None = None) -> None:
        self.resume_after = resume_after
        self.obeys_from = obeys_from
        self.pause_count = 0
        self.paused_at: float | None = None

    def pause(self) -> None:
        self.pause_count += 1
        self.paused_at = asyncio.get_event_loop().time()

    @property
    def state(self) -> str:
        if self.paused_at is None:
            return "playing"
        if self.obeys_from is not None and self.pause_count >= self.obeys_from:
            # `idle`, not `paused`: that is what Sonos through Music Assistant
            # actually settles to — measured 05.09.2026, visible in the service
            # response as playing → idle.
            return "idle"
        if asyncio.get_event_loop().time() - self.paused_at >= self.resume_after:
            return "playing"
        return "idle"


def _hass_for(speaker: Speaker | None = None, fixed_state: str = "playing"):
    """A hass whose speaker is either the stateful ``Speaker`` or a fixed state."""
    hass = MagicMock()

    async def _call(domain, service, data=None, **kwargs):
        if (domain, service) == ("media_player", "media_pause") and speaker:
            speaker.pause()
        return None

    hass.services.async_call = AsyncMock(side_effect=_call)

    def _get(_entity_id):
        st = MagicMock()
        st.state = speaker.state if speaker else fixed_state
        st.attributes = {"volume_level": 0.0}
        return st

    hass.states.get = MagicMock(side_effect=_get)
    return hass


def _guard(hass) -> MaQueueRestorer:
    """The guard on its own — no service, no strategy, no game (#2636).

    This used to read ``MediaPlayerService(hass, ENTITY,
    platform="music_assistant")``, which dragged in the URI cascade, the
    provider table, the analytics hook and the volume bookkeeping to test a
    ``media_pause``. The guard now takes a ``hass`` and nothing else.
    """
    return MaQueueRestorer(hass)


def _services_called(hass) -> list[tuple[str, str]]:
    return [c.args[:2] for c in hass.services.async_call.await_args_list]


def _pause_calls(hass) -> int:
    return sum(
        1 for c in _services_called(hass) if c == ("media_player", "media_pause")
    )


class TestTheGuardOutlivesTheSettling:
    """The regression tests for the REOPENED bug.

    Each one passes against a guard that keeps watching and fails against one
    that confirms the pause once and walks away — which is what #2606 did.
    """

    @pytest.mark.asyncio
    async def test_a_speaker_that_restarts_itself_is_paused_again(self):
        """The live symptom, exactly: pause accepted, playback back at +5s.

        #2606 read the state back once, inside two seconds, saw a speaker that
        had genuinely stopped, and reported success. Everything that restarts
        this device happens later than that.
        """
        speaker = Speaker(resume_after=0.08, obeys_from=2)
        hass = _hass_for(speaker)
        guard = _guard(hass)

        assert await guard.restore_on(ENTITY, QUEUE) is True

        assert speaker.pause_count >= 2, (
            "the speaker started playing again after the first pause and the "
            "guard never noticed — this is #2605 reopened"
        )
        assert speaker.state != "playing"

    @pytest.mark.asyncio
    async def test_the_restore_admits_it_when_the_speaker_will_not_stay_paused(self):
        """A speaker that keeps restarting must not be reported as paused.

        The log line saying `(paused)` over a playing room is what let this
        defect survive two live tests.
        """
        speaker = Speaker(resume_after=0.08)  # never settles
        hass = _hass_for(speaker)
        guard = _guard(hass)

        assert await guard.pause_and_confirm(ENTITY) is False
        assert speaker.pause_count >= 2

    @pytest.mark.asyncio
    async def test_the_log_line_says_the_speaker_is_still_playing(self, caplog):
        speaker = Speaker(resume_after=0.08)
        hass = _hass_for(speaker)
        guard = _guard(hass)

        with caplog.at_level("INFO"):
            await guard.restore_on(ENTITY, QUEUE)

        restored = [r for r in caplog.records if "Queue restored on" in r.getMessage()]
        assert restored, "no restore line was logged at all"
        assert "NOT CONFIRMED" in restored[-1].getMessage(), (
            "the log claims the speaker is paused while it is still playing"
        )

    @pytest.mark.asyncio
    async def test_buffering_is_not_a_paused_speaker(self):
        """MA reports `buffering` while a track loads.

        A confirmation that lands on it reads like a successful pause and is
        not one — the track starts a moment later. Treating it as playback is
        half of why a single reading cannot be trusted.
        """
        hass = _hass_for(fixed_state="buffering")
        guard = _guard(hass)

        assert await guard.pause_and_confirm(ENTITY) is False
        assert _pause_calls(hass) >= 2


class TestTheCommonCaseDoesNotPayForIt:
    @pytest.mark.asyncio
    async def test_a_speaker_that_stays_paused_is_paused_once(self):
        speaker = Speaker(resume_after=99.0, obeys_from=1)
        hass = _hass_for(speaker)
        guard = _guard(hass)

        assert await guard.restore_on(ENTITY, QUEUE) is True
        assert speaker.pause_count == 1

    @pytest.mark.asyncio
    async def test_a_vanished_entity_does_not_hold_up_the_teardown(self):
        """``states.get`` returning None means there is nothing left to pause."""
        hass = _hass_for()
        hass.states.get = MagicMock(return_value=None)
        guard = _guard(hass)

        assert await guard.restore_on(ENTITY, QUEUE) is True

    @pytest.mark.asyncio
    async def test_an_entity_that_vanishes_mid_hold_ends_the_watch(self):
        """The speaker can be removed while the guard is still watching it."""
        hass = _hass_for(fixed_state="idle")
        reads = {"n": 0}

        def _get(_entity_id):
            reads["n"] += 1
            if reads["n"] > 2:
                return None
            st = MagicMock()
            st.state = "idle"
            st.attributes = {}
            return st

        hass.states.get = MagicMock(side_effect=_get)
        guard = _guard(hass)

        assert await guard.pause_and_confirm(ENTITY) is True


class TestOrderingStillHolds:
    @pytest.mark.asyncio
    async def test_pause_is_the_last_thing_that_happens(self):
        """Shuffle and repeat run BEFORE the pause, not after it.

        Ordering is the half of #2606 that was right: with the pause in the
        middle, a speaker that resumes on ``repeat_set`` ends up playing while
        every individual call succeeded. It is not sufficient — none of these
        calls block, so submission order is not execution order, which is why
        the guard above exists as well — but it is still necessary.
        """
        speaker = Speaker(resume_after=99.0, obeys_from=1)
        hass = _hass_for(speaker)
        guard = _guard(hass)

        assert await guard.restore_on(ENTITY, QUEUE) is True

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
