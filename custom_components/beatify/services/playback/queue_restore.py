"""Handing the host's speaker back at the end of a game (#2143), and making
the pause stick (#2605/#2671).

Split out of :mod:`custom_components.beatify.services.media_player` for #2636.

Deliberately NOT a playback strategy, although every line of it is Music
Assistant's. The distinction matters and it is the one place where #2636's
"three strategies" framing does not fit the code: a restore is keyed on the
SNAPSHOT, not on the speaker Beatify happens to be pointed at now. A game that
starts on a Music Assistant speaker and switches to a Sonos one still owes the
first speaker its queue back, and that debt is settled through
``music_assistant.play_media`` even though the service's current platform is
``sonos``. Routing the restore through the current strategy would silently drop
it — so it lives here, taking an entity id and a snapshot, and asks nothing
about platforms.

The #2605 guard (:meth:`MaQueueRestorer.pause_and_confirm`) is the third fix
for a bug that came back twice. Its behaviour is pinned by
``tests/unit/test_queue_restore_stays_paused_2605.py``.

The two corrections in that third round are both about what the guard could
*not* see:

* #2691 — the guard used to confirm silence on a track that had never started.
  ``media_pause`` on an idle player is a no-op, and the ``idle`` left behind by
  ``advance_to_end``'s ``media_stop`` reads exactly like a settled pause. When
  Music Assistant started the track afterwards — Apple Music throttles and
  retries at roughly 15.7s, and #2682 measured 14.6s live — nobody was
  watching. A restore that never saw ``playing`` now holds the watch for the
  whole window instead of accepting the pre-play ``idle`` as proof.
* #2707 — ``_stays_quiet`` reported a relapse and a deadline expiry with the
  same ``False``, so the caller could not tell them apart and the closing
  WARNING claimed the speaker was still playing while it was in fact paused.
  It now returns a :class:`QuietOutcome`, and the window is sized from the
  attempt budget rather than guessed at.
"""

from __future__ import annotations

import asyncio
import logging
from enum import Enum
from typing import TYPE_CHECKING, Any

from homeassistant.exceptions import HomeAssistantError, ServiceNotFound

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# #2143: how long the queue restore waits for the host's track to actually
# start before it seeks to the saved position. Deliberately far below
# MA_PLAYBACK_TIMEOUT: this runs during game teardown, where every second is a
# second the admin UI sits on a dead screen. Missing the window costs the
# position, not the track — the song comes back either way, just from 0:00.
MA_QUEUE_RESTORE_WAIT = 5.0
MA_QUEUE_RESTORE_POLL = 0.25
# #2605: the pause at the end of the queue restore is read back — and the check
# has to OUTLIVE the device settling rather than fit inside it.
#
# The first attempt (#2606) looked once, inside a two-second window, and then
# stopped looking. On the real installation (Sonos through Music Assistant) the
# speaker reported `idle` inside exactly that window, the pause counted as
# confirmed — and from second five onwards it was playing again, for three
# minutes. The window was the defect, not the state check.
#
# So now: confirm, and then KEEP WATCHING. The teardown only counts as done
# once the speaker has stayed quiet for MA_PAUSE_SETTLE_HOLD seconds in a row;
# if it starts again before that, it is paused again. MA_PAUSE_GUARD_WINDOW
# caps the whole thing so `end-game` cannot hang on a speaker something else
# owns.
MA_PAUSE_CONFIRM_WAIT = 2.0
MA_PAUSE_SETTLE_HOLD = 5.0
MA_PAUSE_MAX_ATTEMPTS = 3
MA_PAUSE_POLL = 0.25
# #2707: the window used to be a round 12.0 that had nothing to do with what an
# attempt costs. One attempt can spend a full MA_PAUSE_CONFIRM_WAIT waiting for
# the speaker to go quiet plus a full MA_PAUSE_SETTLE_HOLD holding the silence,
# so a second attempt could not fit and MA_PAUSE_MAX_ATTEMPTS was decoration.
# The window is therefore derived from the attempt cost instead of guessed at:
# two worst-case attempts always fit, and a third fits whenever the relapse
# arrives before the hold is over — which is the shape every live run has had
# (the speaker restarts itself about five seconds after the pause).
MA_PAUSE_ATTEMPT_COST = MA_PAUSE_CONFIRM_WAIT + MA_PAUSE_SETTLE_HOLD
MA_PAUSE_GUARD_WINDOW = 2 * MA_PAUSE_ATTEMPT_COST

# #2691: a restore whose track never reported `playing` gets a LONGER watch,
# because it has nothing to confirm — the `idle` it is reading predates the
# `play_media` and proves only that nothing has started YET.
#
# The number has to outlive Music Assistant's Apple Music provider, which
# throttles and retries on its own backoff — 14.6s measured on the live
# installation in #2682. Counted from the end of MA_QUEUE_RESTORE_WAIT, this
# covers 5 + 18 = 23s after the `play_media` went out.
#
# #2682 later derived the same 23s from MA's retry schedule rather than from a
# single measurement (see MA_PLAYBACK_TIMEOUT: backoff to MA's fifth attempt
# plus the speaker's own start is ~23s), so this window and the play budget now
# cover the same point on the same curve. They are still separate numbers on
# purpose: this one is bought with teardown latency the host is watching a
# spinner for, so it is not raised in step when the play budget moves.
#
# It is bought with teardown latency — the admin's end-game round trip can sit
# here for the whole 18s — and that is the deliberate trade: a spinner the host
# is already looking at, against the host's own music coming back up in a room
# where the game is over. #2605 has now been reopened twice for the second one.
MA_LATE_START_WATCH = 18.0

# #2605: "not playing" is too generous. MA reports `buffering` while a track
# loads, and a reading that lands there looks exactly like a successful pause —
# the track starts a second later anyway. Both states therefore count as "still
# going".
MA_ACTIVE_STATES = frozenset({"playing", "buffering"})


class QuietOutcome(Enum):
    """Why :meth:`MaQueueRestorer._stays_quiet` stopped watching (#2707).

    The three cases used to be two booleans, and the two that mattered shared
    the ``False``. A relapse means the speaker started itself again and has to
    be paused once more; an expiry means the guard ran out of window while the
    room was silent. Reporting the second as the first is what produced the
    WARNING "it is still playing the host's queue" over a paused speaker — the
    exact line the live test read to identify the mechanism behind #2605.
    """

    HELD = "held"
    """The silence lasted the full hold. The pause is confirmed."""

    RELAPSED = "relapsed"
    """Active playback was reported again. Pause it once more."""

    WINDOW_EXPIRED = "window-expired"
    """The guard window ran out while the speaker was quiet.

    Not a confirmation and not a failure: the room is silent, the guard simply
    stopped being allowed to look. The teardown counts it as paused and says so
    in the log rather than claiming either more or less than it saw.
    """


class MaQueueRestorer:
    """Replays one captured queue snapshot onto one speaker.

    Holds a ``hass`` and nothing else — no entity, no provider, no service. A
    unit test builds one over a mock ``hass`` and exercises the whole #2605
    guard without standing up a ``MediaPlayerService``, a strategy or a game.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self._hass = hass

    async def restore_on(self, entity_id: str, queue: dict[str, Any] | None) -> bool:
        """Replay one captured queue snapshot onto one speaker."""
        if not queue or not queue.get("uri"):
            return False
        try:
            await self._hass.services.async_call(
                "music_assistant",
                "play_media",
                {
                    "media_id": queue["uri"],
                    "media_type": "track",
                    "enqueue": "replace",
                },
                target={"entity_id": entity_id},
                blocking=False,
            )
            # The seek below needs the track actually loaded — a seek against
            # the still-playing Beatify track would move the wrong song. Wait
            # for the speaker to report a position, bounded, then give up and
            # leave it playing from the start rather than hang the teardown.
            started = await self._wait_for_playing(entity_id)
            if not started:
                # #2691: this is NOT a cosmetic miss. The seek is skipped
                # below, which was always right, but the pause that follows is
                # then aimed at a player that is still idle from
                # `advance_to_end`'s `media_stop` — where `media_pause` is a
                # no-op and the reading that comes back is the state from
                # BEFORE the `play_media`. The guard has to be told, or it
                # confirms a silence nothing has disturbed yet.
                _LOGGER.debug(
                    "Queue restore on %s: track loaded but never confirmed", entity_id
                )
            elif queue.get("elapsed_time", 0) >= 1:
                await self._hass.services.async_call(
                    "media_player",
                    "media_seek",
                    {
                        "entity_id": entity_id,
                        "seek_position": queue["elapsed_time"],
                    },
                    blocking=False,
                )
            if queue.get("shuffle") is not None:
                await self._hass.services.async_call(
                    "media_player",
                    "shuffle_set",
                    {"entity_id": entity_id, "shuffle": bool(queue["shuffle"])},
                    blocking=False,
                )
            if queue.get("repeat_mode"):
                await self._hass.services.async_call(
                    "media_player",
                    "repeat_set",
                    {"entity_id": entity_id, "repeat": queue["repeat_mode"]},
                    blocking=False,
                )
            # #2605: the pause runs LAST, and it is guarded.
            #
            # It originally sat before `shuffle_set`/`repeat_set` and was fired
            # with `blocking=False` with nobody looking. Measured 2026-09-05:
            # the speaker read `playing` afterwards three times in a row — the
            # host's old queue playing on over the podium, at party volume.
            #
            # Every call above is deliberately `blocking=False` (MA hangs on
            # `blocking=True` for `play_media`, see `play_song`). Submission
            # order is therefore NOT execution order: the `media_seek` can land
            # after the pause and start Sonos playing again. Rather than guess
            # which call did it, `_pause_and_confirm` holds the silence instead
            # of measuring it once.
            paused = await self.pause_and_confirm(entity_id, started=started)
        except (HomeAssistantError, ServiceNotFound) as err:
            _LOGGER.warning("Queue restore on %s failed: %s", entity_id, err)
            return False
        else:
            _LOGGER.info(
                "Queue restored on %s: %s at %.0fs (%s)",
                entity_id,
                queue.get("name") or queue["uri"],
                queue.get("elapsed_time", 0),
                self._outcome_label(paused=paused, started=started),
            )
            return True

    @staticmethod
    def _outcome_label(*, paused: bool, started: bool) -> str:
        """What the closing restore line says about the speaker (#2691/#2707).

        Three states, not two. A restore whose track never reported ``playing``
        did not confirm a pause — it watched an idle speaker and can only say
        the room stayed quiet, whether that is because nothing ever started or
        because a late start was caught and stopped. Printing either as
        ``(paused)`` is what let #2691 hide inside a green log line.
        """
        if not paused:
            return "PAUSE NOT CONFIRMED — see the warning above (#2605)"
        if not started:
            return "quiet after the late-start watch, not a confirmed pause (#2691)"
        return "paused"

    async def pause_and_confirm(self, entity_id: str, *, started: bool = True) -> bool:
        """Pause, read it back — and then keep looking (#2605).

        A `media_pause` with ``blocking=False`` is a request, not a fact. That
        was the finding of #2605, and #2606 answered it by reading the state
        back. On the real installation that still did not hold: the pause
        landed, was confirmed, and from second five the speaker was playing
        again. The check sat in a two-second window; the device takes longer
        than that to settle.

        So the pause is not merely confirmed here, it is **held**:

        1. pause,
        2. wait until the speaker no longer reports active playback,
        3. then watch it for ``MA_PAUSE_SETTLE_HOLD`` seconds in a row.

        If it starts again during step 3 — whether from a ``media_seek`` still
        in flight, a ``play_media`` that had not finished loading, or Music
        Assistant resuming its own queue — it is paused again. The guard is
        deliberately blind to the mechanism; it reacts to what the room does.

        ``MA_PAUSE_GUARD_WINDOW`` caps the whole thing so a speaker something
        else owns cannot hang the ``end-game`` teardown.

        Args:
            entity_id: the speaker to hold quiet.
            started: whether the caller actually saw the restored track reach
                ``playing``. False switches the guard into its #2691 mode: the
                window becomes ``MA_LATE_START_WATCH`` and step 3 runs to the
                end of it instead of stopping after ``MA_PAUSE_SETTLE_HOLD``,
                because a speaker that has not started yet produces exactly the
                same ``idle`` reading as one that has settled. Silence is only
                evidence once there was something to silence.

        Returns:
            True when the speaker actually held the silence, when the window
            ran out with the room quiet, or when the entity is gone. False
            means it was still playing when the guard had to stop — the
            warning in the log says so, and only then.
        """
        loop = asyncio.get_event_loop()
        window = MA_PAUSE_GUARD_WINDOW if started else MA_LATE_START_WATCH
        deadline = loop.time() + window
        # Flips the moment the speaker is seen playing — including a late start
        # caught inside the #2691 watch. From then on this is an ordinary
        # relapse and gets the ordinary MA_PAUSE_SETTLE_HOLD, not another full
        # window of waiting.
        seen_playing = started
        for versuch in range(1, MA_PAUSE_MAX_ATTEMPTS + 1):
            await self._hass.services.async_call(
                "media_player",
                "media_pause",
                {"entity_id": entity_id},
                blocking=False,
            )
            if not await self._wait_until_quiet(entity_id, deadline):
                # `_wait_until_quiet` only gives up on a reading that is still
                # active, so this branch is always a genuinely playing speaker.
                seen_playing = True
                _LOGGER.debug(
                    "Queue restore on %s: still playing after pause attempt %d",
                    entity_id,
                    versuch,
                )
            else:
                hold = MA_PAUSE_SETTLE_HOLD if seen_playing else None
                outcome = await self._stays_quiet(entity_id, deadline, hold)
                if outcome is QuietOutcome.HELD:
                    if versuch > 1:
                        _LOGGER.info(
                            "Queue restore on %s: speaker stayed paused after "
                            "attempt %d (#2605)",
                            entity_id,
                            versuch,
                        )
                    return True
                if outcome is QuietOutcome.WINDOW_EXPIRED:
                    # #2707: quiet room, spent window. The old code fell
                    # through to the WARNING here and told the maintainer the
                    # speaker was still playing the host's queue.
                    if seen_playing:
                        _LOGGER.info(
                            "Queue restore on %s: %.0fs guard window ran out "
                            "with the speaker quiet after attempt %d — pause "
                            "held, though not for the full %.0fs (#2707)",
                            entity_id,
                            window,
                            versuch,
                            MA_PAUSE_SETTLE_HOLD,
                        )
                    else:
                        # #2691: the track never started at all. Worth an INFO
                        # rather than silence, because the host's music did not
                        # actually come back — the restore returns True for the
                        # room, not for the promise.
                        _LOGGER.info(
                            "Queue restore on %s: the track never started "
                            "within %.0fs and the speaker stayed quiet for all "
                            "of it (#2691)",
                            entity_id,
                            window,
                        )
                    return True
                # This is the observation #2606 could not make: the pause
                # arrived, and the speaker started itself again afterwards.
                # Under #2691 it is the late start finally landing.
                seen_playing = True
                _LOGGER.info(
                    "Queue restore on %s: speaker started playing again after "
                    "pause attempt %d — pausing once more (#2605)",
                    entity_id,
                    versuch,
                )
            if loop.time() >= deadline:
                break
        _LOGGER.warning(
            "Queue restore on %s: could not get the speaker to stay paused "
            "within %.0fs — it is still playing the host's queue (#2605)",
            entity_id,
            window,
        )
        return False

    async def _wait_until_quiet(self, entity_id: str, deadline: float) -> bool:
        """Wait until the speaker stops reporting active playback (#2605).

        ``media_pause`` settles Sonos-through-Music-Assistant to ``idle``, not
        to ``paused`` — measured 2026-09-05, visible in the service response as
        playing → idle. So this tests for "not active" rather than for one
        particular target state.

        ``None`` means the entity is gone. There is nothing left to pause then,
        and waiting on it would only stall the teardown.

        Returns:
            True as soon as the speaker is not reporting active playback.
            False only ever after a reading that WAS active — which is why the
            caller may treat it as "still playing" without a second check.
        """
        loop = asyncio.get_event_loop()
        limit = min(loop.time() + MA_PAUSE_CONFIRM_WAIT, deadline)
        while True:
            state = self._hass.states.get(entity_id)
            if state is None or state.state not in MA_ACTIVE_STATES:
                return True
            if loop.time() >= limit:
                return False
            await asyncio.sleep(MA_PAUSE_POLL)

    async def _stays_quiet(
        self, entity_id: str, deadline: float, hold: float | None
    ) -> QuietOutcome:
        """Read the silence back and say why the watch ended (#2605/#2707).

        Holding the silence is precisely the step #2606 was missing. There the
        first quiet reading counted as proof — and because it fell inside a
        two-second window, it was a reading of a speaker that had not finished
        settling.

        Args:
            entity_id: the speaker to watch.
            deadline: the guard window's end; never watched past it.
            hold: how many seconds of unbroken silence count as proof, or
                ``None`` to watch until the deadline. ``None`` is the #2691
                case: a track that never started has no settling to outlive,
                so no length of quiet is proof and the guard simply watches
                for as long as it is allowed to.

        Returns:
            The reason the watch stopped. ``RELAPSED`` and ``WINDOW_EXPIRED``
            used to share a ``False``, and the caller has to tell them apart —
            one needs another pause, the other needs the guard to stop lying
            about a silent room (#2707).
        """
        loop = asyncio.get_event_loop()
        hold_until = None if hold is None else loop.time() + hold
        while True:
            now = loop.time()
            if hold_until is not None and now >= hold_until:
                return QuietOutcome.HELD
            if now >= deadline:
                return QuietOutcome.WINDOW_EXPIRED
            await asyncio.sleep(MA_PAUSE_POLL)
            state = self._hass.states.get(entity_id)
            if state is None:
                return QuietOutcome.HELD
            if state.state in MA_ACTIVE_STATES:
                return QuietOutcome.RELAPSED

    async def _wait_for_playing(self, entity_id: str) -> bool:
        """Poll until the speaker reports playback, at most MA_QUEUE_RESTORE_WAIT."""
        deadline = asyncio.get_event_loop().time() + MA_QUEUE_RESTORE_WAIT
        while asyncio.get_event_loop().time() < deadline:
            state = self._hass.states.get(entity_id)
            if state is not None and state.state == "playing":
                return True
            await asyncio.sleep(MA_QUEUE_RESTORE_POLL)
        return False
