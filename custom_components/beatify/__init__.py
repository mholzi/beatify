"""
Custom integration to integrate Beatify with Home Assistant.

Beatify is a party game integration that works with Music Assistant
to play music guessing games.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.components.frontend import (
    async_register_built_in_panel,
    async_remove_panel,
)

from .const import DOMAIN
from .game.playlist import (
    async_discover_playlists,
    async_ensure_playlist_directory,
)
from .game.state import GameState
from .server import async_register_static_paths
from .server.views import (
    AdminView,
    DashboardView,
    EndGameView,
    GameStatusView,
    LauncherView,
    PlayerView,
    StartGameplayView,
    StartGameView,
    StatusView,
)
from .server.websocket import BeatifyWebSocketHandler
from .services.media_player import async_get_media_players

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Beatify from a config entry."""
    _LOGGER.debug("Setting up Beatify integration")

    # Initialize domain data storage
    hass.data.setdefault(DOMAIN, {})

    # Ensure playlist directory exists
    playlist_dir = await async_ensure_playlist_directory(hass)

    # Discover media players and playlists
    media_players = await async_get_media_players(hass)
    playlists = await async_discover_playlists(hass)

    _LOGGER.info(
        "Found %d media players, %d playlists",
        len(media_players),
        len(playlists),
    )

    # Initialize game state
    game_state = GameState()

    # Initialize WebSocket handler
    ws_handler = BeatifyWebSocketHandler(hass)

    # Set up round end callback for timer expiry (Story 4.5)
    game_state.set_round_end_callback(ws_handler.broadcast_state)

    # Store discovery results and game infrastructure
    hass.data[DOMAIN] = {
        "entry_id": entry.entry_id,
        "media_players": media_players,
        "playlists": playlists,
        "playlist_dir": str(playlist_dir),
        "game": game_state,
        "ws_handler": ws_handler,
    }

    # Register HTTP views
    hass.http.register_view(AdminView(hass))
    hass.http.register_view(LauncherView(hass))
    hass.http.register_view(StatusView(hass))
    hass.http.register_view(StartGameView(hass))
    hass.http.register_view(StartGameplayView(hass))
    hass.http.register_view(EndGameView(hass))
    hass.http.register_view(PlayerView(hass))
    hass.http.register_view(GameStatusView(hass))
    hass.http.register_view(DashboardView(hass))

    # Register WebSocket endpoint
    hass.http.app.router.add_get("/beatify/ws", ws_handler.handle)

    # Register static file paths
    await async_register_static_paths(hass)

    # Register sidebar panel (Story 10.3)
    # Uses iframe to launcher page which opens admin in new tab
    async_register_built_in_panel(
        hass,
        component_name="iframe",
        sidebar_title="Beatify",
        sidebar_icon="mdi:music-circle",
        frontend_url_path="beatify",
        config={"url": "/beatify/launcher"},
        require_admin=False,
    )
    _LOGGER.debug("Beatify sidebar panel registered")

    _LOGGER.info("Beatify integration setup complete")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:  # noqa: ARG001
    """Unload a config entry."""
    _LOGGER.debug("Unloading Beatify integration")

    # Remove sidebar panel (Story 10.3)
    try:
        async_remove_panel(hass, "beatify")
        _LOGGER.debug("Beatify sidebar panel removed")
    except KeyError:
        _LOGGER.debug("Beatify sidebar panel was not registered, skipping removal")

    # Clean up domain data
    if DOMAIN in hass.data:
        hass.data.pop(DOMAIN)

    _LOGGER.info("Beatify integration unloaded")
    return True


async def async_refresh_discovery(hass: HomeAssistant) -> None:
    """Refresh media player and playlist discovery."""
    if DOMAIN not in hass.data:
        return

    media_players = await async_get_media_players(hass)
    playlists = await async_discover_playlists(hass)

    hass.data[DOMAIN]["media_players"] = media_players
    hass.data[DOMAIN]["playlists"] = playlists

    _LOGGER.debug(
        "Refreshed discovery: %d media players, %d playlists",
        len(media_players),
        len(playlists),
    )
