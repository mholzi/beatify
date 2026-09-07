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
def _fast_guard(monkeypatch, request):
    """Run the real guard on a compressed clock.

    The production budget is 5s of hold inside a 14s window, and an 18s watch
    for a track that never started — correct for a Sonos behind Apple Music,
    unbearable in a unit suite. Only the durations shrink; the logic under test
    is untouched.

    A class can set ``real_clock = True`` to opt out. Exactly one does: the
    arithmetic between the constants (#2707) is only worth asserting on the
    numbers that ship.
    """
    if getattr(request.cls, "real_clock", False):
        return
    monkeypatch.setattr(queue_restore, "MA_PAUSE_CONFIRM_WAIT", 0.20)
    monkeypatch.setattr(queue_restore, "MA_PAUSE_SETTLE_HOLD", 0.30)
    monkeypatch.setattr(queue_restore, "MA_PAUSE_GUARD_WINDOW", 2.0)
    # Kept clearly longer than the guard window, the way production keeps it
    # (18s against 14s): a test that only passes because the two are equal
    # would prove nothing about #2691.
    monkeypatch.setattr(queue_restore, "MA_LATE_START_WATCH", 3.0)
    monkeypatch.setattr(queue_restore, "MA_PAUSE_POLL", 0.02)
    monkeypatch.setattr(queue_restore, "MA_QUEUE_RESTORE_WAIT", 0.20)
    monkeypatch.setattr(queue_restore, "MA_QUEUE_RESTORE_POLL", 0.02)


class Speaker:
    """A media player that obeys a pause and then starts itself again.

    This is the reopened #2605, reduced to its mechanism: ``media_pause``
    really does take — the state leaves ``playing`` — and ``resume_after``
    seconds later the device is playing once more. #2606 stopped looking two
    seconds after the pause, so from where it stood the teardown had worked.

    ``starts_after`` adds the case #2691 found missing. Without it the fake is
    playing from the first read, which is the one thing a restored track is
    NOT: ``advance_to_end`` stopped the speaker, ``play_media`` is submitted
    non-blocking, and Music Assistant's Apple Music provider throttles and
    retries on its own backoff — 15.7s in this codebase's own notes, 14.6s
    measured live in #2682. Until it starts, the device answers ``idle``, which
    reads exactly like a settled pause, and **a pause sent in that stretch does
    nothing at all**. That last part is the defect: the guard used to confirm
    silence against a track that had not begun, and by the time it did begin
    nobody was looking.

    Args:
        resume_after: seconds between an accepted pause and the relapse.
        obeys_from: the number of EFFECTIVE pauses (see ``pause``) from which
            the speaker stays quiet for good. ``None`` means it never settles.
        starts_after: seconds from the first state read until Music Assistant
            actually starts the track. ``None`` means it is already playing.
    """

    def __init__(
        self,
        *,
        resume_after: float,
        obeys_from: int | None = None,
        starts_after: float | None = None,
    ) -> None:
        self.resume_after = resume_after
        self.obeys_from = obeys_from
        self.starts_after = starts_after
        # Every pause command HA sent, including the ones that hit an idle
        # player and did nothing.
        self.pause_count = 0
        # The pauses that actually stopped something. A guard that only ever
        # pauses a player that has not started yet scores zero here — which is
        # #2691 in one number.
        self.effective_pauses = 0
        self.paused_at: float | None = None
        self._playing = starts_after is None
        self._born: float | None = None

    def _tick(self) -> None:
        """Let the clock start the track if its moment has come."""
        now = asyncio.get_event_loop().time()
        if self._born is None:
            self._born = now
        if self._playing or self.starts_after is None:
            return
        if now - self._born >= self.starts_after:
            self._playing = True
            # A pause that arrived before the track existed did not survive it.
            self.paused_at = None

    def pause(self) -> None:
        self._tick()
        self.pause_count += 1
        if not self._playing:
            # `media_pause` on an idle player is a no-op. Counting it as one
            # would hide the very thing #2691 is about.
            return
        self.effective_pauses += 1
        self.paused_at = asyncio.get_event_loop().time()

    @property
    def state(self) -> str:
        self._tick()
        if not self._playing:
            return "idle"
        if self.paused_at is None:
            return "playing"
        if self.obeys_from is not None and self.effective_pauses >= self.obeys_from:
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


class TestATrackThatStartsLate:
    """#2691 — the third layer of #2605, and the one the fake could not reach.

    ``restore_on`` waits ``MA_QUEUE_RESTORE_WAIT`` for the restored track to
    report ``playing`` and then goes on to the guard whether it saw it or not.
    Everything downstream of that then agrees, wrongly: ``media_pause`` on an
    idle player is a no-op, the ``idle`` that ``advance_to_end``'s ``media_stop``
    left behind reads as a settled pause, the hold watches five seconds of that
    same untouched idle, and the log says ``(paused)``.

    Then Music Assistant starts the track. 15.7s is what this codebase records
    for Apple Music's throttle-and-retry (``game/state_lifecycle.py``); 14.6s is
    what #2682 measured on the live installation. Both are past the 5s wait, and
    the old 12s guard window did not reach them either.
    """

    @pytest.mark.asyncio
    async def test_a_track_that_starts_after_the_wait_is_still_paused(self):
        """The room must end up quiet even when the track begins late.

        Against the guard as it shipped in v4.4.3 this fails twice over: the
        speaker is never effectively paused, and it is playing when the restore
        claims to be done.
        """
        speaker = Speaker(resume_after=99.0, obeys_from=1, starts_after=1.0)
        hass = _hass_for(speaker)
        guard = _guard(hass)

        assert await guard.restore_on(ENTITY, QUEUE) is True

        assert speaker.effective_pauses >= 1, (
            "the track started after the restore stopped watching and was "
            "never actually paused — this is #2691"
        )
        assert speaker.state != "playing"

    @pytest.mark.asyncio
    async def test_the_pre_play_idle_is_not_accepted_as_a_settled_pause(self):
        """The guard alone, told the track never started.

        ``pause_and_confirm(started=False)`` must keep watching for the whole
        late-start window rather than take the first quiet reading as proof.
        The speaker here starts halfway through it.
        """
        speaker = Speaker(resume_after=99.0, obeys_from=1, starts_after=1.0)
        hass = _hass_for(speaker)
        guard = _guard(hass)

        assert await guard.pause_and_confirm(ENTITY, started=False) is True

        assert speaker.effective_pauses >= 1
        assert speaker.state != "playing"

    @pytest.mark.asyncio
    async def test_the_log_does_not_call_an_unstarted_track_paused(
        self, caplog, monkeypatch
    ):
        """A track that never started was not paused, and the line must say so.

        The v4.4.3 line reads ``Queue restored on … (paused)`` here, over a
        speaker nothing has been done to. That is the same green-log failure
        mode that let #2605 survive two live tests.
        """
        monkeypatch.setattr(queue_restore, "MA_LATE_START_WATCH", 0.30)
        speaker = Speaker(resume_after=99.0, obeys_from=1, starts_after=99.0)
        hass = _hass_for(speaker)
        guard = _guard(hass)

        with caplog.at_level("INFO"):
            assert await guard.restore_on(ENTITY, QUEUE) is True

        restored = [r for r in caplog.records if "Queue restored on" in r.getMessage()]
        assert restored, "no restore line was logged at all"
        assert "(paused)" not in restored[-1].getMessage(), (
            "the restore reports a pause it never performed — the track had "
            "not started (#2691)"
        )
        assert "2691" in restored[-1].getMessage()

    @pytest.mark.asyncio
    async def test_a_late_start_does_not_get_a_second_full_window(self):
        """Once the speaker has been seen playing, it is an ordinary relapse.

        The long watch exists because silence proves nothing before the track
        starts. After it starts, ``MA_PAUSE_SETTLE_HOLD`` is the right hold
        again — otherwise every late start would cost a second full window of
        teardown.
        """
        speaker = Speaker(resume_after=99.0, obeys_from=1, starts_after=0.1)
        hass = _hass_for(speaker)
        guard = _guard(hass)

        loop = asyncio.get_event_loop()
        began = loop.time()
        assert await guard.pause_and_confirm(ENTITY, started=False) is True
        spent = loop.time() - began

        assert spent < queue_restore.MA_LATE_START_WATCH / 2, (
            "the guard sat out the whole late-start window after the speaker "
            "had already been caught and paused"
        )


class TestTheLogTellsRelapseFromTimeout:
    """#2707 — ``_stays_quiet`` used to answer both questions with ``False``.

    A relapse and an expired window are opposite findings: one means the
    speaker started itself again, the other means the room was silent and the
    guard simply ran out of permission to look. Merging them produced the
    WARNING "it is still playing the host's queue" over a paused speaker —
    and that WARNING is the line the live test read to identify the mechanism
    behind #2605.
    """

    @pytest.mark.asyncio
    async def test_a_quiet_speaker_at_the_deadline_is_not_reported_as_playing(
        self, caplog, monkeypatch
    ):
        """Window shorter than the hold: the guard must run out, not accuse.

        This is the shape of the real thing — attempt 1 spends its full budget
        and the window ends underneath it — compressed into one attempt.
        """
        monkeypatch.setattr(queue_restore, "MA_PAUSE_SETTLE_HOLD", 0.60)
        monkeypatch.setattr(queue_restore, "MA_PAUSE_GUARD_WINDOW", 0.15)
        speaker = Speaker(resume_after=99.0, obeys_from=1)
        hass = _hass_for(speaker)
        guard = _guard(hass)

        with caplog.at_level("INFO"):
            assert await guard.pause_and_confirm(ENTITY) is True

        assert not [
            r
            for r in caplog.records
            if "still playing the host's queue" in r.getMessage()
        ], "the guard ran out of window over a silent speaker and called it playing"

    @pytest.mark.asyncio
    async def test_a_real_relapse_still_warns(self, caplog):
        """The other half of #2707: the WARNING has to keep meaning something.

        A speaker that genuinely will not stay paused must still produce it —
        the fix is about the false positive, not about softening the line.
        """
        speaker = Speaker(resume_after=0.08)  # never settles
        hass = _hass_for(speaker)
        guard = _guard(hass)

        with caplog.at_level("INFO"):
            assert await guard.pause_and_confirm(ENTITY) is False

        assert [
            r
            for r in caplog.records
            if "still playing the host's queue" in r.getMessage()
        ], "a speaker that never stayed paused was reported as fine"

    @pytest.mark.asyncio
    async def test_the_second_attempt_fits_inside_the_window(self, monkeypatch):
        """Attempt 2 must be able to run to the end, not be cut off by the cap.

        With the window sized at exactly two worst-case attempts, a speaker
        that relapses once and then settles is confirmed on attempt 2 rather
        than falling out of the loop with a warning.
        """
        cost = queue_restore.MA_PAUSE_CONFIRM_WAIT + queue_restore.MA_PAUSE_SETTLE_HOLD
        monkeypatch.setattr(queue_restore, "MA_PAUSE_GUARD_WINDOW", 2 * cost)
        speaker = Speaker(resume_after=0.25, obeys_from=2)
        hass = _hass_for(speaker)
        guard = _guard(hass)

        assert await guard.pause_and_confirm(ENTITY) is True
        assert speaker.pause_count == 2


class TestTheProductionBudget:
    """The numbers that ship, not the compressed ones (#2707).

    ``MA_PAUSE_MAX_ATTEMPTS = 3`` was decoration: one attempt can cost a full
    ``MA_PAUSE_CONFIRM_WAIT`` plus a full ``MA_PAUSE_SETTLE_HOLD``, and the
    window was a round 12.0 that fitted one of those and a bit.
    """

    real_clock = True

    def test_the_window_fits_at_least_two_worst_case_attempts(self):
        cost = queue_restore.MA_PAUSE_CONFIRM_WAIT + queue_restore.MA_PAUSE_SETTLE_HOLD
        assert queue_restore.MA_PAUSE_GUARD_WINDOW >= 2 * cost, (
            "a second pause attempt cannot finish inside the guard window, so "
            "MA_PAUSE_MAX_ATTEMPTS is a number the loop can never reach (#2707)"
        )

    def test_the_late_start_watch_outlives_apple_musics_backoff(self):
        """15.7s is the documented throttle-and-retry, 14.6s the measured one.

        Both are counted from the ``play_media``, so the watch only has to
        cover what is left after ``MA_QUEUE_RESTORE_WAIT`` — with margin,
        because neither number is a guarantee.
        """
        cover = queue_restore.MA_QUEUE_RESTORE_WAIT + queue_restore.MA_LATE_START_WATCH
        assert cover >= 20.0, (
            "a track that starts on Apple Music's own backoff (15.7s "
            "documented, 14.6s measured in #2682) finishes outside the watch "
            "and plays into an ended game (#2691)"
        )
