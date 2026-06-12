"""Regression tests for one-time HTTP route registration on reload (#1364).

A config-entry reload runs async_unload_entry followed by async_setup_entry.
aiohttp routes cannot be unregistered, and its dispatcher resolves to the FIRST
registered resource — so re-registering the ~28 views, the WebSocket route, and
the static paths on every setup would leave stale handlers shadowing the freshly
wired ones. For the WebSocket that is a functional break: round-end broadcasts
target the new (empty) handler while clients stay attached to the old one.

These tests stub the small ``homeassistant.*`` surface that the integration's
top-level ``__init__`` imports at module load, then drive ``async_setup_entry``
twice (initial setup + reload) against a mock ``hass`` and assert that routes are
registered exactly once and the WS route always dispatches to the *current*
handler stored in ``hass.data``.
"""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

# --------------------------------------------------------------------------
# Stub the homeassistant modules imported at module load by the integration's
# top-level __init__ (and its transitive runtime imports). Mirrors the stubbing
# pattern already used in tests/conftest.py. Must run before importing the
# integration package.
# --------------------------------------------------------------------------


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


@pytest.fixture
def mock_hass():
    """A mock hass whose http router records every registered view/route."""
    registered_views = []
    added_routes = {}

    http = MagicMock()
    http.register_view.side_effect = registered_views.append
    http.async_register_static_paths = AsyncMock()

    def _add_get(path, handler):
        added_routes[path] = handler

    http.app.router.add_get.side_effect = _add_get

    hass = MagicMock()
    hass.data = {}
    hass.http = http
    # async_add_executor_job just runs the callable synchronously for the test.
    hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *a: fn(*a))
    hass.config_entries.async_forward_entry_setups = AsyncMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)

    hass._registered_views = registered_views
    hass._added_routes = added_routes
    return hass


@pytest.fixture(autouse=True)
def _patch_heavy_helpers(monkeypatch):
    """Patch the integration's heavy async setup helpers to no-ops."""
    monkeypatch.setattr(
        beatify_init,
        "async_ensure_playlist_directory",
        AsyncMock(return_value="/tmp/p"),
    )
    monkeypatch.setattr(
        beatify_init, "async_discover_playlists", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        beatify_init, "async_get_media_players", AsyncMock(return_value=[])
    )

    # StatsService / AnalyticsStorage do real Store I/O — replace with stubs that
    # carry just the attributes async_setup_entry reads/wires.
    stats = MagicMock()
    stats.load = AsyncMock()
    stats.games_played = 0
    monkeypatch.setattr(beatify_init, "StatsService", MagicMock(return_value=stats))

    analytics = MagicMock()
    analytics.load = AsyncMock()
    analytics.total_games = 0
    monkeypatch.setattr(
        beatify_init, "AnalyticsStorage", MagicMock(return_value=analytics)
    )


def _make_entry(entry_id: str = "entry-1"):
    return SimpleNamespace(entry_id=entry_id)


@pytest.mark.asyncio
async def test_routes_registered_once_across_reload(mock_hass):
    """Initial setup registers routes; a reload must NOT re-register them."""
    entry = _make_entry()

    assert await beatify_init.async_setup_entry(mock_hass, entry) is True
    first_view_count = len(mock_hass._registered_views)
    assert first_view_count > 20, "expected the full view set on first setup"
    assert "/beatify/ws" in mock_hass._added_routes
    assert mock_hass.http.async_register_static_paths.await_count == 1
    assert mock_hass.data[beatify_init._ROUTES_REGISTERED] is True

    # --- reload: unload then setup again ---
    assert await beatify_init.async_unload_entry(mock_hass, entry) is True
    # unload pops hass.data[DOMAIN]; the route-guard flag lives outside DOMAIN
    # and must survive so the second setup skips registration.
    assert mock_hass.data.get(beatify_init._ROUTES_REGISTERED) is True

    assert await beatify_init.async_setup_entry(mock_hass, entry) is True

    # No new views, no second WS route add, no second static-path registration.
    assert len(mock_hass._registered_views) == first_view_count
    assert mock_hass.http.app.router.add_get.call_count == 1
    assert mock_hass.http.async_register_static_paths.await_count == 1


@pytest.mark.asyncio
async def test_ws_route_dispatches_to_current_handler(mock_hass):
    """The registered WS route resolves the live handler from hass.data."""
    entry = _make_entry()
    await beatify_init.async_setup_entry(mock_hass, entry)

    ws_dispatch = mock_hass._added_routes["/beatify/ws"]
    handler_after_setup = mock_hass.data[DOMAIN]["ws_handler"]

    # Swap in a fresh handler (what a reload produces) and confirm the SAME
    # registered route now dispatches to the new instance, not the old one.
    new_handler = MagicMock()
    new_handler.handle = AsyncMock(return_value="dispatched")
    mock_hass.data[DOMAIN]["ws_handler"] = new_handler
    assert new_handler is not handler_after_setup

    request = MagicMock()
    result = await ws_dispatch(request)

    new_handler.handle.assert_awaited_once_with(request)
    assert result == "dispatched"


@pytest.mark.asyncio
async def test_ws_route_503_when_handler_missing(mock_hass):
    """If hass.data has no ws_handler, the route returns 503 (not an error)."""
    entry = _make_entry()
    await beatify_init.async_setup_entry(mock_hass, entry)
    ws_dispatch = mock_hass._added_routes["/beatify/ws"]

    # Simulate the integration being torn down (hass.data[DOMAIN] popped).
    mock_hass.data.pop(DOMAIN, None)

    response = await ws_dispatch(MagicMock())
    assert response.status == 503
