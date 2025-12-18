"""
Custom integration to integrate Beatify with Home Assistant.

Beatify is a party game integration that works with Music Assistant
to play music guessing games.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .const import DOMAIN
from .game.playlist import (
    async_discover_playlists,
    async_ensure_playlist_directory,
)
from .server import async_register_static_paths
from .server.views import AdminView, StatusView
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

    # Store discovery results
    hass.data[DOMAIN] = {
        "entry_id": entry.entry_id,
        "media_players": media_players,
        "playlists": playlists,
        "playlist_dir": str(playlist_dir),
    }

    # Register HTTP views
    hass.http.register_view(AdminView(hass))
    hass.http.register_view(StatusView(hass))

    # Register static file paths
    await async_register_static_paths(hass)

    _LOGGER.info("Beatify integration setup complete")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:  # noqa: ARG001
    """Unload a config entry."""
    _LOGGER.debug("Unloading Beatify integration")

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
