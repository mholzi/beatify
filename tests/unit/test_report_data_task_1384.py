"""Tests for the data-quality report follow-up task (#1384).

Two regressions are guarded here:

1. ``handle_report_data`` must launch ``_create_gh_issue`` via HA's
   ``hass.async_create_background_task`` registry — not a bare
   ``asyncio.ensure_future`` that HA never sees (which HA may garbage-collect
   mid-flight and never cancels on unload).
2. ``_create_gh_issue`` must reuse HA's shared aiohttp ClientSession via
   ``async_get_clientsession(hass)`` instead of constructing a fresh
   ``aiohttp.ClientSession()`` per call.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.beatify.game.state import GamePhase
from custom_components.beatify.server import ws_handlers
from custom_components.beatify.server.ws_handlers import (
    _create_gh_issue,
    handle_report_data,
)
from tests.conftest import make_player


def _ws() -> AsyncMock:
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    ws.closed = False
    return ws


def _handler_and_state():
    """A handler whose hass exposes a spyable async_create_background_task."""
    handler = MagicMock()
    handler.hass = MagicMock()
    handler.hass.async_create_background_task = MagicMock()

    game_state = MagicMock()
    game_state.phase = GamePhase.REVEAL
    game_state.current_song = {
        "artist": "ABBA",
        "title": "Waterloo",
        "year": 1974,
        "_playlist_source": "70s.json",
    }
    game_state.game_id = "g1"
    game_state.get_player_by_ws.return_value = make_player("Alice")
    return handler, game_state


@pytest.mark.asyncio
async def test_report_data_launches_tracked_background_task():
    """The follow-up is registered as an HA background task, not orphaned."""
    handler, game_state = _handler_and_state()
    ws = _ws()
    handler.hass.async_add_executor_job = AsyncMock()

    coros: list = []

    def _capture(coro, name=None):
        coros.append((coro, name))
        coro.close()  # never scheduled in the test; avoid "never awaited" warning
        return MagicMock()

    handler.hass.async_create_background_task.side_effect = _capture

    # If the old bare ensure_future path were taken, this would fire instead.
    with patch.object(ws_handlers.asyncio, "ensure_future") as ensure_future:
        await handle_report_data(handler, ws, {}, game_state)

    handler.hass.async_create_background_task.assert_called_once()
    ensure_future.assert_not_called()

    # Named so it is identifiable in HA's task registry.
    assert coros[0][1] == "beatify-report-data"
    ws.send_json.assert_awaited_once_with({"type": "report_data_ack"})


@pytest.mark.asyncio
async def test_create_gh_issue_reuses_shared_session():
    """_create_gh_issue must use async_get_clientsession(hass), not a new one."""
    hass = MagicMock()

    resp = AsyncMock()
    resp.status = 200

    @asynccontextmanager
    async def _post(*args, **kwargs):
        yield resp

    session = MagicMock()
    session.post = _post

    with (
        patch.object(
            ws_handlers, "async_get_clientsession", return_value=session
        ) as get_session,
        patch.object(ws_handlers.aiohttp, "ClientSession") as new_session,
    ):
        await _create_gh_issue(hass, "ABBA", "Waterloo", 1974, "70s.json", "Alice")

    get_session.assert_called_once_with(hass)
    # A per-call session must never be constructed.
    new_session.assert_not_called()
