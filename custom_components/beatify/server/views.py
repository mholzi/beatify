"""HTTP views for Beatify admin interface.

This module serves as the main entry point for all Beatify views.
It contains HTML-serving views and shared infrastructure, and re-exports
views from sub-modules for backward compatibility.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from custom_components.beatify.const import DOMAIN
from custom_components.beatify.game.playlist import async_discover_playlists
from custom_components.beatify.server.base import (
    BeatifyAdminView,
    RateLimitMixin,
    _get_version,
    _json_error,
    _read_file,
    _verify_admin_token,
    _VERSION,
)
from custom_components.beatify.server.serializers import (
    build_status_response,
)
from custom_components.beatify.services.lights import PartyLightsService
from custom_components.beatify.services.media_player import async_get_media_players

# Re-export game views
from custom_components.beatify.server.game_views import (  # noqa: F401
    EndGameView,
    GameStatusView,
    RematchGameView,
    StartGameplayView,
    StartGameView,
)

# Re-export playlist views
from custom_components.beatify.server.playlist_views import (  # noqa: F401
    EditPlaylistView,
    ImportPlaylistView,
    PlaylistRequestsView,
    SpotifyCredentialsView,
    SpotifySearchView,
)

# Re-export stats views
from custom_components.beatify.server.stats_views import (  # noqa: F401
    AnalyticsPageView,
    AnalyticsView,
    DashboardView,
    SongStatsView,
    StatsView,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HTML-serving views (kept here -- they are tightly coupled to static assets)
# ---------------------------------------------------------------------------


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

        html_content = await self.hass.async_add_executor_job(_read_file, html_path)
        return web.Response(text=html_content, content_type="text/html")


class LauncherView(HomeAssistantView):
    """Serve the launcher page for HA sidebar (opens admin in new tab)."""

    url = "/beatify/launcher"
    name = "beatify:launcher"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the launcher view."""
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:  # noqa: ARG002
        """Serve the launcher HTML page."""
        html_path = Path(__file__).parent.parent / "www" / "launcher.html"

        if not html_path.exists():
            _LOGGER.error("Launcher page not found: %s", html_path)
            return web.Response(text="Launcher page not found", status=500)

        html_content = await self.hass.async_add_executor_job(_read_file, html_path)
        return web.Response(text=html_content, content_type="text/html")


class PlayerView(HomeAssistantView):
    """Serve the player page."""

    url = "/beatify/play"
    name = "beatify:play"
    requires_auth = False  # Frictionless access per PRD

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the player view."""
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:  # noqa: ARG002
        """Serve the player HTML page."""
        html_path = Path(__file__).parent.parent / "www" / "player.html"

        if not html_path.exists():
            _LOGGER.error("Player page not found: %s", html_path)
            return web.Response(text="Player page not found", status=500)

        html_content = await self.hass.async_add_executor_job(_read_file, html_path)
        return web.Response(text=html_content, content_type="text/html")


# ---------------------------------------------------------------------------
# API views (kept here -- lightweight and closely tied to core status)
# ---------------------------------------------------------------------------


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
        # Fetch media players fresh (not cached) - Story 8-2
        media_players = await async_get_media_players(self.hass)

        # Fetch playlists fresh (not cached) - Issue #135
        playlists = await async_discover_playlists(self.hass)
        self.hass.data.setdefault(DOMAIN, {})["playlists"] = playlists

        status = build_status_response(
            self.hass,
            version=_get_version(),
            media_players=media_players,
            playlists=playlists,
        )

        return web.json_response(status)


class LightsView(HomeAssistantView):
    """API endpoint for available light entities (#331)."""

    url = "/beatify/api/lights"
    name = "beatify:api:lights"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the lights view."""
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:  # noqa: ARG002
        """Return available light entities with capabilities."""
        lights = []
        for state in self.hass.states.async_all("light"):
            color_modes = state.attributes.get("supported_color_modes", [])
            if any(m in color_modes for m in ("rgb", "rgbw", "rgbww", "hs", "xy")):
                capability = "rgb"
            elif "color_temp" in color_modes:
                capability = "ct"
            elif "brightness" in color_modes:
                capability = "dim"
            else:
                capability = "onoff"

            lights.append(
                {
                    "entity_id": state.entity_id,
                    "friendly_name": state.attributes.get(
                        "friendly_name", state.entity_id
                    ),
                    "state": state.state,
                    "capability": capability,
                    "supported_color_modes": color_modes,
                }
            )

        return web.json_response({"lights": lights})


class PreviewLightsView(HomeAssistantView):
    """Trigger a party lights preview for selected entities (#408)."""

    url = "/beatify/api/preview-lights"
    name = "beatify:api:preview-lights"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass

    async def post(self, request: web.Request) -> web.Response:
        """Run a ~5s party lights preview on the given entity_ids."""
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return web.json_response({"error": "Invalid JSON"}, status=400)

        entity_ids = body.get("entity_ids", [])
        if not entity_ids:
            return web.json_response({"error": "No entity_ids provided"}, status=400)

        game_state = self.hass.data.get(DOMAIN, {}).get("game")
        if game_state and game_state.game_id:
            return web.json_response(
                {"error": "Cannot preview during active game"}, status=409
            )

        intensity = body.get("intensity", "party")

        try:
            preview = PartyLightsService(self.hass)
            await preview.start(entity_ids, intensity)
            await preview.celebrate()
            await preview.stop()
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Party lights preview failed")
            return web.json_response({"error": "Preview failed"}, status=500)

        return web.json_response({"ok": True})


class TtsTestView(RateLimitMixin, HomeAssistantView):
    """Send a test TTS announcement to verify setup."""

    url = "/beatify/api/tts-test"
    name = "beatify:api:tts-test"
    requires_auth = False

    MAX_TTS_MESSAGE_LENGTH = 500

    RATE_LIMIT_REQUESTS = 5
    RATE_LIMIT_WINDOW = 60  # seconds

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass
        self._init_rate_limits()

    async def post(self, request: web.Request) -> web.Response:
        """Speak a test message via TTS."""
        client_ip = request.remote or "unknown"
        if not self._check_rate_limit(client_ip):
            return _json_error("Too many requests", 429, code="RATE_LIMITED")
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return web.json_response({"error": "Invalid JSON"}, status=400)

        entity_id = body.get("entity_id", "")
        message = body.get("message", "")[:self.MAX_TTS_MESSAGE_LENGTH]
        if not entity_id or not message:
            return web.json_response(
                {"error": "entity_id and message required"}, status=400
            )

        state = self.hass.states.get(entity_id)
        if not state or state.domain not in ("media_player", "tts"):
            return web.json_response(
                {"error": "Invalid or unsupported entity_id"}, status=400
            )

        try:
            await self.hass.services.async_call(
                "tts",
                "speak",
                {"entity_id": entity_id, "message": message},
                blocking=False,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception("TTS test failed for entity: %s", entity_id)
            return web.json_response({"error": "TTS call failed"}, status=500)

        return web.json_response({"ok": True})
