"""Play without a speaker: the TV screen or the host's phone is the speaker.

Music Assistant can turn the browser that shows its quiz into a player because
it brings its own web player. Beatify has none, and Spotify, Apple Music or
Tidal cannot play in a plain browser. What can is the public 30-second preview
(``previews.py``). So the browser target plays that clip, in the browser,
through an ``<audio>`` element.

Two pieces live here:

* :class:`BrowserClientRegistry` — which open page plays for which target.
  The TV page (``dashboard.js``) registers as ``"tv"``, the admin page
  (``admin.js``) as ``"phone"``. Exactly one page per role plays; a page that
  tapped "Sound on" claims the role from any other.
* :class:`BrowserStrategy` — the :class:`~.base.PlaybackStrategy` for the
  ``beatify_browser`` platform: find the preview, send it to that one page,
  and read the page's answer.

The WebSocket handler owns the sockets and forwards ``playback_register`` /
``playback_report`` frames here; this module never opens a connection itself.

Wire format, server -> page::

    {"type": "browser_audio", "action": "play", "url": ..., "id": n}
    {"type": "browser_audio", "action": "stop" | "resume"}
    {"type": "browser_audio", "action": "volume", "level": 0..1}
    {"type": "browser_audio", "action": "announce", "url": ...}
    {"type": "playback_registered", "role": ..., "active": bool}
    {"type": "playback_released", "role": ...}

page -> server::

    {"type": "playback_register", "role": "tv" | "phone", "claim": bool}
    {"type": "playback_report", "state": "playing" | "blocked" | "error"
                                         | "ended" | "paused", "id": n}
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, ClassVar

from custom_components.beatify.const import BROWSER_TARGET_ROLES, DOMAIN
from custom_components.beatify.providers import PLATFORM_BROWSER

from .base import PlaybackStrategy
from .previews import Preview, async_resolve_preview

if TYPE_CHECKING:
    from .context import PlayerContext

_LOGGER = logging.getLogger(__name__)

#: The roles a page can play under.
ROLES: tuple[str, ...] = ("tv", "phone")

#: What a page may report about its audio.
REPORT_STATES = frozenset({"playing", "blocked", "error", "ended", "paused"})

#: Seconds to wait for the page to say whether the clip started. A page that
#: does not answer in time is trusted: the clip is buffering, and the round
#: must not stall on a slow TV.
PLAY_ACK_TIMEOUT = 5.0


class BrowserClientRegistry:
    """The open pages that play audio, one per role.

    A page that only *registers* (the TV page on load) takes a free role, or
    one whose holder is gone. A page that *claims* (after the host tapped
    "Sound on" on it) takes the role from whichever page held it, and that page
    is told so. That settles "several TV screens open": the one that was last
    switched on plays.
    """

    def __init__(self) -> None:
        self._clients: dict[str, Any] = {}
        self._state: dict[str, str] = {}
        self._pending: dict[int, tuple[str, asyncio.Future]] = {}
        self._ids = itertools.count(1)
        self._listeners: list[Callable[[], None]] = []

    # -- registration -------------------------------------------------------

    def register(self, role: str, ws: Any, *, claim: bool = False) -> Any | None:
        """Make ``ws`` the page for ``role``.

        Returns:
            The page that lost the role to this claim (to be told), or None.
            A plain registration never displaces a live page; it is simply not
            made the player, and the caller reports that back.
        """
        if role not in ROLES:
            raise ValueError(f"unknown browser role {role!r}")
        current = self._clients.get(role)
        if current is ws:
            return None
        if current is not None and not _closed(current) and not claim:
            return None
        self._clients[role] = ws
        self._state[role] = "idle"
        self._notify()
        return current if current is not None and not _closed(current) else None

    def unregister(self, ws: Any) -> list[str]:
        """Forget ``ws`` in every role it held; return those roles."""
        roles = [role for role, held in self._clients.items() if held is ws]
        for role in roles:
            del self._clients[role]
            self._state.pop(role, None)
            for req_id, (req_role, fut) in list(self._pending.items()):
                if req_role == role and not fut.done():
                    fut.set_result({"state": "gone"})
                    self._pending.pop(req_id, None)
        if roles:
            self._notify()
        return roles

    def holds(self, role: str, ws: Any) -> bool:
        """True when ``ws`` is the page playing for ``role``."""
        return self._clients.get(role) is ws

    def role_of(self, ws: Any) -> str | None:
        """The role ``ws`` plays under, or None."""
        for role, held in self._clients.items():
            if held is ws:
                return role
        return None

    def connected(self, role: str) -> bool:
        """True when a live page plays for ``role``."""
        ws = self._clients.get(role)
        return ws is not None and not _closed(ws)

    def status(self) -> dict[str, bool]:
        """``{role: connected}`` for every role."""
        return {role: self.connected(role) for role in ROLES}

    def playback_state(self, role: str) -> str | None:
        """The last state the page reported, ``"idle"`` before any."""
        if not self.connected(role):
            return None
        return self._state.get(role, "idle")

    def add_listener(self, listener: Callable[[], None]) -> None:
        """Call ``listener`` whenever a role changes hands."""
        self._listeners.append(listener)

    def _notify(self) -> None:
        for listener in list(self._listeners):
            with contextlib.suppress(Exception):
                listener()

    # -- messages -----------------------------------------------------------

    async def send(self, role: str, message: dict[str, Any]) -> bool:
        """Send ``message`` to the page for ``role``; False when nobody got it."""
        ws = self._clients.get(role)
        if ws is None or _closed(ws):
            return False
        try:
            await ws.send_json(message)
        except Exception as err:  # noqa: BLE001 — a dead socket is "not sent"
            _LOGGER.debug("Browser %s did not take a frame: %s", role, err)
            return False
        return True

    async def request(
        self, role: str, message: dict[str, Any], *, timeout: float
    ) -> dict[str, Any]:
        """Send ``message`` and wait for the page's report on it.

        Returns:
            The report, ``{"state": "unsent"}`` when there was nobody to send
            to, ``{"state": "gone"}`` when the page left while we waited, and
            ``{"state": "timeout"}`` when it did not answer in time.
        """
        req_id = next(self._ids)
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[req_id] = (role, fut)
        try:
            if not await self.send(role, {**message, "id": req_id}):
                return {"state": "unsent"}
            try:
                return await asyncio.wait_for(fut, timeout=timeout)
            except (TimeoutError, asyncio.TimeoutError):
                return {"state": "timeout"}
        finally:
            self._pending.pop(req_id, None)

    def handle_report(self, ws: Any, data: dict[str, Any]) -> bool:
        """Take a ``playback_report`` from ``ws``; False when it was ignored.

        A page that does not hold a role has nothing to report, so its frames
        are dropped — a second TV cannot answer for the one that plays.
        """
        role = self.role_of(ws)
        state = data.get("state")
        if role is None or state not in REPORT_STATES:
            return False
        self._state[role] = state
        req_id = data.get("id")
        if isinstance(req_id, int):
            pending = self._pending.get(req_id)
            if pending is not None and pending[0] == role and not pending[1].done():
                pending[1].set_result({"state": state})
        return True


def _closed(ws: Any) -> bool:
    return bool(getattr(ws, "closed", False))


def registry_from_hass(hass: Any) -> BrowserClientRegistry | None:
    """The registry the integration stored at setup, or None."""
    try:
        data = hass.data.get(DOMAIN, {})
    except AttributeError:
        return None
    registry = data.get("browser_clients") if isinstance(data, dict) else None
    return registry if isinstance(registry, BrowserClientRegistry) else None


class BrowserStrategy(PlaybackStrategy):
    """Play the song's 30-second preview in the browser that holds the role."""

    platforms: ClassVar[tuple[str, ...]] = (PLATFORM_BROWSER,)
    playback_method: ClassVar[str] = "preview"
    setup_caveat: ClassVar[str | None] = "30-second previews only"

    def __init__(
        self,
        context: PlayerContext,
        *,
        clients: BrowserClientRegistry | None = None,
    ) -> None:
        super().__init__(context)
        self._clients = clients
        #: The preview of the most recent successful start, for album art.
        self.last_preview: Preview | None = None

    @property
    def role(self) -> str | None:
        """The registry role this target plays under."""
        return BROWSER_TARGET_ROLES.get(self._entity_id)

    @property
    def clients(self) -> BrowserClientRegistry | None:
        """The page registry; looked up late so a strategy built before
        setup finished still finds it."""
        if self._clients is None:
            self._clients = registry_from_hass(self._hass)
        return self._clients

    def _storefront(self) -> str | None:
        config = getattr(self._hass, "config", None)
        country = getattr(config, "country", None) if config else None
        return str(country).strip().lower() or None if country else None

    async def _resolve(self, song: dict[str, Any]) -> Preview | None:
        # Late imports: the HA client session helper is not importable in the
        # bare unit-test environment, and the playlist module is game code.
        from homeassistant.helpers.aiohttp_client import (  # noqa: PLC0415
            async_get_clientsession,
        )

        from custom_components.beatify.game.playlist import (  # noqa: PLC0415
            get_song_uri,
        )

        storefront = self._storefront()
        apple_uri = get_song_uri(song, "apple_music", storefront)
        return await async_resolve_preview(
            async_get_clientsession(self._hass),
            song,
            apple_uri=apple_uri,
            storefront=storefront,
        )

    async def play(self, song: dict[str, Any]) -> bool:
        """Find the preview and hand it to the page that plays.

        Failure reasons follow the shared contract (``base.py``): a song with
        no preview, or one whose clip the browser cannot load, is
        ``"unavailable"`` and skipped without counting; no page to play on is
        ``"error"``, which pauses the game after a few tries like a dead
        speaker.
        """
        role = self.role
        clients = self.clients
        if role is None or clients is None or not clients.connected(role):
            _LOGGER.warning("No browser is playing for %s", self._entity_id)
            self.last_failure_reason = "error"
            return False

        preview = await self._resolve(song)
        if preview is None:
            _LOGGER.info(
                "No preview for %s - %s, skipping",
                song.get("artist"),
                song.get("title"),
            )
            self.last_failure_reason = "unavailable"
            return False

        reply = await clients.request(
            role,
            {"type": "browser_audio", "action": "play", "url": preview.url},
            timeout=PLAY_ACK_TIMEOUT,
        )
        state = reply.get("state")
        if state in ("unsent", "gone"):
            self.last_failure_reason = "error"
            return False
        if state == "error":
            # The clip itself would not load (an expired or blocked URL).
            self.last_failure_reason = "unavailable"
            return False
        # "playing", "timeout", or "blocked": the TV waits for "Sound on" and
        # starts the clip with it, which is the documented one-time step.
        self.last_failure_reason = None
        self.last_preview = preview
        return True
