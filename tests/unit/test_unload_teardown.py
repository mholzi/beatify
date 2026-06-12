"""Regression tests for unload teardown of game tasks/timers/WebSockets (#1391).

``async_unload_entry`` used to pop ``hass.data[DOMAIN]`` without shutting down
the live game infrastructure. A game active at unload left the round-timer task,
intro timer, background metadata task, the REVEAL auto-advance task and the
fire-and-forget ``_bg_tasks`` running against an orphaned ``GameState``, plus the
WebSocket handler's pending tasks and every open player/admin connection — which
then raced a fresh ``GameState`` after reload (two timers driving one media
player).

These tests prove:
1. ``GameState.async_shutdown()`` cancels every running game task/timer.
2. ``BeatifyWebSocketHandler.async_close_all()`` cancels its pending tasks and
   closes every open WebSocket with a going-away code.
3. ``async_unload_entry`` invokes both before popping ``hass.data[DOMAIN]``.
"""

from __future__ import annotations

import asyncio
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.beatify.server.websocket import BeatifyWebSocketHandler
from tests.conftest import make_game_state


# ---------------------------------------------------------------------------
# 1. GameState.async_shutdown()
# ---------------------------------------------------------------------------


async def _never() -> None:
    """A coroutine that never completes — stands in for a live timer task."""
    await asyncio.Event().wait()


@pytest.mark.asyncio
async def test_async_shutdown_cancels_every_game_task():
    """async_shutdown cancels the round/intro/metadata/auto-advance/bg tasks."""
    game = make_game_state()
    rm = game._round_manager

    rm._timer_task = asyncio.ensure_future(_never())
    rm._intro_stop_task = asyncio.ensure_future(_never())
    rm._metadata_task = asyncio.ensure_future(_never())
    game._auto_advance_task = asyncio.ensure_future(_never())
    bg = asyncio.ensure_future(_never())
    game._bg_tasks.add(bg)

    handles = [
        rm._timer_task,
        rm._intro_stop_task,
        rm._metadata_task,
        game._auto_advance_task,
        bg,
    ]

    game.async_shutdown()
    # Give the loop a tick so the cancellations propagate.
    await asyncio.sleep(0)

    for task in handles:
        assert task.cancelled() or task.done(), f"{task!r} still running after shutdown"

    # Slots cleared so nothing dangles / re-cancels.
    assert rm._timer_task is None
    assert rm._intro_stop_task is None
    assert rm._metadata_task is None
    assert game._auto_advance_task is None
    assert game._bg_tasks == set()


@pytest.mark.asyncio
async def test_async_shutdown_idempotent_when_idle():
    """async_shutdown is a no-op when no game is running (no exceptions)."""
    game = make_game_state()
    # No tasks set anywhere — must not raise.
    game.async_shutdown()
    game.async_shutdown()


# ---------------------------------------------------------------------------
# 2. BeatifyWebSocketHandler.async_close_all()
# ---------------------------------------------------------------------------


def _make_handler() -> BeatifyWebSocketHandler:
    return BeatifyWebSocketHandler(MagicMock())


@pytest.mark.asyncio
async def test_async_close_all_cancels_pending_tasks():
    """Pending removals, admin-disconnect, and debounce tasks are cancelled."""
    handler = _make_handler()

    removal = asyncio.ensure_future(_never())
    admin = asyncio.ensure_future(_never())
    debounce = asyncio.ensure_future(_never())
    handler._pending_removals["Alice"] = removal
    handler._admin_disconnect_task = admin
    handler._broadcast_debounce_task = debounce

    await handler.async_close_all()
    await asyncio.sleep(0)

    assert removal.cancelled() or removal.done()
    assert admin.cancelled() or admin.done()
    assert debounce.cancelled() or debounce.done()
    assert handler._pending_removals == {}
    assert handler._admin_disconnect_task is None
    assert handler._broadcast_debounce_task is None


@pytest.mark.asyncio
async def test_async_close_all_closes_open_connections():
    """Every open WebSocket is closed with the going-away code; set is cleared."""
    from aiohttp import WSCloseCode

    handler = _make_handler()
    ws_open = AsyncMock()
    ws_open.closed = False
    ws_open.close = AsyncMock()
    ws_already_closed = AsyncMock()
    ws_already_closed.closed = True
    ws_already_closed.close = AsyncMock()

    handler.connections.add(ws_open)
    handler.connections.add(ws_already_closed)

    await handler.async_close_all()

    ws_open.close.assert_awaited_once()
    assert ws_open.close.await_args.kwargs["code"] == WSCloseCode.GOING_AWAY
    # An already-closed connection is not re-closed.
    ws_already_closed.close.assert_not_called()
    assert handler.connections == set()


@pytest.mark.asyncio
async def test_async_close_all_survives_close_error():
    """A close() that raises does not abort teardown of the remaining sockets."""
    handler = _make_handler()
    ws_bad = AsyncMock()
    ws_bad.closed = False
    ws_bad.close = AsyncMock(side_effect=RuntimeError("boom"))
    ws_good = AsyncMock()
    ws_good.closed = False
    ws_good.close = AsyncMock()
    handler.connections.update({ws_bad, ws_good})

    await handler.async_close_all()

    ws_good.close.assert_awaited_once()
    assert handler.connections == set()


# ---------------------------------------------------------------------------
# 3. async_unload_entry wiring
# ---------------------------------------------------------------------------
# Stub the homeassistant surface the integration's top-level __init__ imports at
# module load (mirrors tests/unit/test_setup_reload_routes.py).


def _ensure_module(name: str) -> ModuleType:
    mod = sys.modules.get(name)
    if mod is None:
        mod = ModuleType(name)
        sys.modules[name] = mod
    return mod


_ensure_module("homeassistant")
_ensure_module("homeassistant.components")
_frontend = _ensure_module("homeassistant.components.frontend")
_frontend.async_register_built_in_panel = MagicMock()
_frontend.async_remove_panel = MagicMock()

_http = _ensure_module("homeassistant.components.http")
_http.StaticPathConfig = MagicMock(name="StaticPathConfig")


class _HomeAssistantView:  # minimal base for server.views import
    url = ""
    name = ""
    requires_auth = False


_http.HomeAssistantView = _HomeAssistantView

_helpers = _ensure_module("homeassistant.helpers")
_aiohttp_client = _ensure_module("homeassistant.helpers.aiohttp_client")
_aiohttp_client.async_get_clientsession = MagicMock()
_event = _ensure_module("homeassistant.helpers.event")
_event.async_track_state_change_event = MagicMock()
_er = _ensure_module("homeassistant.helpers.entity_registry")
_er.async_get = MagicMock()
_exceptions = _ensure_module("homeassistant.exceptions")


class _HomeAssistantError(Exception):
    pass


class _ServiceNotFound(Exception):
    pass


_exceptions.HomeAssistantError = _HomeAssistantError
_exceptions.ServiceNotFound = _ServiceNotFound

import custom_components.beatify as beatify_init  # noqa: E402
from custom_components.beatify.const import DOMAIN  # noqa: E402


def _unload_hass(domain_data: dict) -> MagicMock:
    hass = MagicMock()
    hass.data = {DOMAIN: domain_data}
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    return hass


@pytest.mark.asyncio
async def test_unload_entry_shuts_down_game_and_closes_ws():
    """async_unload_entry tears down game + ws BEFORE popping hass.data."""
    game = MagicMock()
    game.async_shutdown = MagicMock()
    ws_handler = MagicMock()
    ws_handler.async_close_all = AsyncMock()

    hass = _unload_hass({"game": game, "ws_handler": ws_handler})
    entry = SimpleNamespace(entry_id="e1")

    assert await beatify_init.async_unload_entry(hass, entry) is True

    game.async_shutdown.assert_called_once()
    ws_handler.async_close_all.assert_awaited_once()
    # Domain data popped after teardown.
    assert DOMAIN not in hass.data


@pytest.mark.asyncio
async def test_unload_entry_tolerates_missing_game_infrastructure():
    """No game/ws_handler in hass.data → unload still succeeds, no crash."""
    hass = _unload_hass({})
    entry = SimpleNamespace(entry_id="e1")
    assert await beatify_init.async_unload_entry(hass, entry) is True
    assert DOMAIN not in hass.data


@pytest.mark.asyncio
async def test_unload_entry_swallows_teardown_errors():
    """A teardown error never blocks the unload (data still popped)."""
    game = MagicMock()
    game.async_shutdown = MagicMock(side_effect=RuntimeError("boom"))
    ws_handler = MagicMock()
    ws_handler.async_close_all = AsyncMock(side_effect=RuntimeError("boom"))

    hass = _unload_hass({"game": game, "ws_handler": ws_handler})
    entry = SimpleNamespace(entry_id="e1")

    assert await beatify_init.async_unload_entry(hass, entry) is True
    assert DOMAIN not in hass.data
