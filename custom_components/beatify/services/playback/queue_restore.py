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

The #2605 guard (:meth:`MaQueueRestorer.pause_and_confirm`) is the second fix
for a bug that came back once. It is reproduced here unchanged; its behaviour
is pinned by ``tests/unit/test_queue_restore_stays_paused_2605.py``.
"""

from __future__ import annotations

import asyncio
import logging
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
MA_PAUSE_GUARD_WINDOW = 12.0
MA_PAUSE_MAX_ATTEMPTS = 3
MA_PAUSE_POLL = 0.25

# #2605: "not playing" is too generous. MA reports `buffering` while a track
# loads, and a reading that lands there looks exactly like a successful pause —
# the track starts a second later anyway. Both states therefore count as "still
# going".
MA_ACTIVE_STATES = frozenset({"playing", "buffering"})


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
            if not await self._wait_for_playing(entity_id):
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
            paused = await self.pause_and_confirm(entity_id)
        except (HomeAssistantError, ServiceNotFound) as err:
            _LOGGER.warning("Queue restore on %s failed: %s", entity_id, err)
            return False
        else:
            _LOGGER.info(
                "Queue restored on %s: %s at %.0fs (%s)",
                entity_id,
                queue.get("name") or queue["uri"],
                queue.get("elapsed_time", 0),
                "paused"
                if paused
                else "PAUSE NOT CONFIRMED — see the warning above (#2605)",
            )
            return True

    async def pause_and_confirm(self, entity_id: str) -> bool:
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

        Returns:
            True when the speaker actually held the silence (or the entity is
            gone). False means unconfirmed — the warning in the log says why.
        """
        deadline = asyncio.get_event_loop().time() + MA_PAUSE_GUARD_WINDOW
        for versuch in range(1, MA_PAUSE_MAX_ATTEMPTS + 1):
            await self._hass.services.async_call(
                "media_player",
                "media_pause",
                {"entity_id": entity_id},
                blocking=False,
            )
            if not await self._wait_until_quiet(entity_id, deadline):
                _LOGGER.debug(
                    "Queue restore on %s: still playing after pause attempt %d",
                    entity_id,
                    versuch,
                )
            elif await self._stays_quiet(entity_id, deadline):
                if versuch > 1:
                    _LOGGER.info(
                        "Queue restore on %s: speaker stayed paused after "
                        "attempt %d (#2605)",
                        entity_id,
                        versuch,
                    )
                return True
            else:
                # This is the observation #2606 could not make: the pause
                # arrived, and the speaker started itself again afterwards.
                _LOGGER.info(
                    "Queue restore on %s: speaker started playing again after "
                    "pause attempt %d — pausing once more (#2605)",
                    entity_id,
                    versuch,
                )
            if asyncio.get_event_loop().time() >= deadline:
                break
        _LOGGER.warning(
            "Queue restore on %s: could not get the speaker to stay paused "
            "within %.0fs — it is still playing the host's queue (#2605)",
            entity_id,
            MA_PAUSE_GUARD_WINDOW,
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

    async def _stays_quiet(self, entity_id: str, deadline: float) -> bool:
        """Read the silence back for ``MA_PAUSE_SETTLE_HOLD`` seconds (#2605).

        This is precisely the step #2606 was missing. There the first quiet
        reading counted as proof — and because it fell inside a two-second
        window, it was a reading of a speaker that had not finished settling.

        Returns:
            False as soon as playback is reported again, or when the guard
            window runs out before the silence has held long enough.
        """
        loop = asyncio.get_event_loop()
        hold_until = loop.time() + MA_PAUSE_SETTLE_HOLD
        while True:
            now = loop.time()
            if now >= hold_until:
                return True
            if now >= deadline:
                return False
            await asyncio.sleep(MA_PAUSE_POLL)
            state = self._hass.states.get(entity_id)
            if state is None:
                return True
            if state.state in MA_ACTIVE_STATES:
                return False

    async def _wait_for_playing(self, entity_id: str) -> bool:
        """Poll until the speaker reports playback, at most MA_QUEUE_RESTORE_WAIT."""
        deadline = asyncio.get_event_loop().time() + MA_QUEUE_RESTORE_WAIT
        while asyncio.get_event_loop().time() < deadline:
            state = self._hass.states.get(entity_id)
            if state is not None and state.state == "playing":
                return True
            await asyncio.sleep(MA_QUEUE_RESTORE_POLL)
        return False
