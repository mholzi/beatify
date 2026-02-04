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

from .analytics import AnalyticsStorage
from .const import DOMAIN
from .game.playlist import (
    async_discover_playlists,
    async_ensure_playlist_directory,
)
from .game.state import GameState
from .server import async_register_static_paths
from .server.views import (
    AdminView,
    AnalyticsPageView,
    AnalyticsView,
    DashboardView,
    EndGameView,
    GameStatusView,
    LauncherView,
    PlayerView,
    PlaylistRequestsView,
    RematchGameView,
    SongStatsView,
    StartGameplayView,
    StartGameView,
    StatsView,
    StatusView,
)
from .server.websocket import BeatifyWebSocketHandler
from .services.media_player import async_get_media_players
from .services.stats import StatsService

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

    # Initialize stats service (Story 14.4)
    stats_service = StatsService(hass)
    await stats_service.load()
    _LOGGER.debug("Stats service initialized: %d games played", stats_service.games_played)

    # Initialize analytics storage (Story 19.1)
    analytics = AnalyticsStorage(hass)
    await analytics.load()
    _LOGGER.debug("Analytics initialized: %d games recorded", analytics.total_games)

    # Connect analytics to stats service for unified data collection
    stats_service.set_analytics(analytics)

    # Connect stats service to game state for performance tracking (Story 14.4)
    game_state.set_stats_service(stats_service)

    # Initialize WebSocket handler
    ws_handler = BeatifyWebSocketHandler(hass)

    # Set up round end callback for timer expiry (Story 4.5)
    game_state.set_round_end_callback(ws_handler.broadcast_state)

    # Set up metadata update callback for fast transitions (Issue #42)
    game_state.set_metadata_update_callback(ws_handler.broadcast_metadata_update)

    # Connect analytics to websocket handler for error recording (Story 19.1)
    ws_handler.set_analytics(analytics)

    # Store discovery results and game infrastructure
    hass.data[DOMAIN] = {
        "entry_id": entry.entry_id,
        "media_players": media_players,
        "playlists": playlists,
        "playlist_dir": str(playlist_dir),
        "game": game_state,
        "ws_handler": ws_handler,
        "stats": stats_service,
        "analytics": analytics,
    }

    # Register HTTP views
    hass.http.register_view(AdminView(hass))
    hass.http.register_view(LauncherView(hass))
    hass.http.register_view(StatusView(hass))
    hass.http.register_view(StartGameView(hass))
    hass.http.register_view(StartGameplayView(hass))
    hass.http.register_view(EndGameView(hass))
    hass.http.register_view(RematchGameView(hass))  # Issue #108
    hass.http.register_view(PlayerView(hass))
    hass.http.register_view(GameStatusView(hass))
    hass.http.register_view(DashboardView(hass))
    hass.http.register_view(StatsView(hass))
    hass.http.register_view(AnalyticsView(hass))
    hass.http.register_view(AnalyticsPageView(hass))
    hass.http.register_view(SongStatsView(hass))  # Story 19.7
    hass.http.register_view(PlaylistRequestsView(hass))  # Story 44

    # Register WebSocket endpoint
    hass.http.app.router.add_get("/beatify/ws", ws_handler.handle)

    # Register static file paths
    await async_register_static_paths(hass)

    # Register sidebar panel (Story 10.3)
    # Direct to admin page - works in mobile app WebView (no popup needed)
    async_register_built_in_panel(
        hass,
        component_name="iframe",
        sidebar_title="Beatify",
        sidebar_icon="mdi:music-circle",
        frontend_url_path="beatify",
        config={"url": "/beatify/admin"},
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
