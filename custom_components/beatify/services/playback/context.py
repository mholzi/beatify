"""The speaker a playback strategy talks to, and the reads it may make.

Split out of :mod:`custom_components.beatify.services.media_player` for #2636.

A strategy needs surprisingly little: which Home Assistant, which entity, and
which music provider the user picked. Everything else the old 2300-line class
carried around — analytics, the pre-flight cache, volume bookkeeping, the
metadata wait — belongs to the service shell and is deliberately NOT reachable
from here. That is what makes a strategy testable on its own: a unit test
builds a ``PlayerContext`` over a mock ``hass`` and never constructs a
``MediaPlayerService`` at all.

The two state reads live here rather than on the strategies because both the
shell and every strategy need them, and because their defensiveness (an
exception out of ``hass.states.get`` must degrade to "unknown", not abort a
round) is a property of reading THIS entity, not of any one platform.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


async def _no_queue_capture() -> None:
    """Default #2143 hook: a context nobody wired remembers no queue."""
    return None


class PlayerContext:
    """One speaker, plus the handful of things a strategy may ask of it.

    Args:
        hass: Home Assistant instance.
        entity_id: the media player entity this context speaks for.
        platform: platform identifier from the entity registry — read by the
            dispatch in :func:`..playback.build_strategy`, not by strategies.
        provider: the music provider the wizard settled on.
        save_queue: the #2143 hook. Music Assistant's ``enqueue: "replace"``
            wipes whatever the host had queued, so the strategy calls this
            immediately before the first replace of a game. The bookkeeping
            (capture once, hand back at game end, carry across a speaker
            switch) stays in the service shell, which is where the game
            lifecycle lives; the hook is only the "now is the moment" signal.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        entity_id: str,
        platform: str = "unknown",
        provider: str = "spotify",
        *,
        save_queue: Callable[[], Awaitable[Any]] | None = None,
    ) -> None:
        self.hass = hass
        self.entity_id = entity_id
        self.platform = platform
        self.provider = provider
        self._save_queue = save_queue or _no_queue_capture

        # #1927 follow-up / #808 follow-up: the attempt record. Both the shell
        # (which seeds it from the dispatcher's URI) and the Music Assistant
        # strategy (which overwrites it per candidate) write these, and
        # ``state_lifecycle`` reads them off the service. One owner, two
        # writers — so they live on the thing both sides already share.
        self.last_attempted_uri: str | None = None
        self.last_failure_reason: str | None = None

    async def save_queue(self) -> None:
        """Tell the shell that the host's queue is about to be replaced."""
        await self._save_queue()

    def state(self):
        """Read entity state, return None on any exception.

        Resilience for the playback-confirmation read sites in the Music
        Assistant strategy. A transient exception from ``hass.states.get()``
        (rare but possible during HA restarts / state-machine reload) used to
        propagate up and abort the whole song play, even though the existing
        code paths gracefully handle a None return. Catching here lets the flow
        downgrade to "state unknown" and continue. (#777 follow-up — the
        polling-resilience scope flagged in TestMAPollingResilience.)
        """
        try:
            return self.hass.states.get(self.entity_id)
        except Exception as err:  # noqa: BLE001 — defensive read of HA state
            _LOGGER.warning(
                "hass.states.get(%s) raised %s; treating as unknown",
                self.entity_id,
                err,
            )
            return None

    async def state_with_retry(self, retries: int = 3, delay: float = 0.5):
        """Read entity state with short retry loop; for the post-timeout site
        where having a state is critical for the title-advance check.

        Most reads succeed on attempt 1; this only kicks in when HA's state
        machine is briefly unreadable (HA restart edge, MA reload). Returns
        None if all attempts return None.
        """
        for attempt in range(retries):
            state = self.state()
            if state is not None:
                return state
            if attempt < retries - 1:
                await asyncio.sleep(delay)
        return None
