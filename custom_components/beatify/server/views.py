"""HTTP views for Beatify admin interface."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntryState

from custom_components.beatify.const import DOMAIN, MA_SETUP_URL

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class AdminView(HomeAssistantView):
    """Serve the admin page."""

    url = "/beatify/admin"
    name = "beatify:admin"
    requires_auth = False  # Frictionless access per PRD

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the admin view."""
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:  # noqa: ARG002
        """Serve the admin HTML page."""
        html_path = Path(__file__).parent.parent / "www" / "admin.html"

        if not html_path.exists():
            _LOGGER.error("Admin page not found: %s", html_path)
            return web.Response(text="Admin page not found", status=500)

        html_content = html_path.read_text(encoding="utf-8")
        return web.Response(text=html_content, content_type="text/html")


class StatusView(HomeAssistantView):
    """API endpoint for admin page status."""

    url = "/beatify/api/status"
    name = "beatify:api:status"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the status view."""
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:  # noqa: ARG002
        """Return current status as JSON."""
        data = self.hass.data.get(DOMAIN, {})

        status = {
            "media_players": data.get("media_players", []),
            "playlists": data.get("playlists", []),
            "playlist_dir": data.get("playlist_dir", ""),
            "ma_configured": await self._check_ma_status(),
            "ma_setup_url": MA_SETUP_URL,
        }

        return web.json_response(status)

    async def _check_ma_status(self) -> bool:
        """Check if Music Assistant is configured and loaded."""
        entries = self.hass.config_entries.async_entries("music_assistant")
        return any(e.state == ConfigEntryState.LOADED for e in entries)
