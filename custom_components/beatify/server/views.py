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
from custom_components.beatify.game.state import GamePhase
from custom_components.beatify.game.playlist import async_discover_playlists
from custom_components.beatify.server.base import (
    RateLimitMixin,
    _get_html,
    _get_version,
    _json_error,
    _read_file,
)
from custom_components.beatify.server.serializers import (
    build_status_response,
)
from custom_components.beatify.services.lights import PartyLightsService
from custom_components.beatify.services.media_player import async_get_media_players

# Re-export game views
from custom_components.beatify.server.game_views import (  # noqa: F401
    EndGameView,
    ForceResetView,
    GameStatusView,
    RematchGameView,
    StartGameplayView,
    StartGameView,
)

# Re-export playlist views
from custom_components.beatify.server.playlist_views import (  # noqa: F401
    PlaylistRequestsView,
)

# Re-export stats views
from custom_components.beatify.server.stats_views import (  # noqa: F401
    AnalyticsPageView,
    AnalyticsView,
    DashboardView,
    SongStatsView,
    StatsView,
    UsageView,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HTML-serving views (kept here -- they are tightly coupled to static assets)
# ---------------------------------------------------------------------------

# Entry-point HTML must never be cached by the browser. Otherwise the `?v=rcN`
# cache-busters on the referenced JS/CSS never get read — the browser serves a
# months-old admin.html from its own cache and the new RC is invisible until
# the user opens a private window. no-cache + no-store + must-revalidate is
# the belt-and-suspenders version; we want revalidation on every navigation.
_NO_CACHE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _html_response(text: str) -> web.Response:
    """Return an HTML response that browsers will always revalidate."""
    return web.Response(text=text, content_type="text/html", headers=_NO_CACHE_HEADERS)


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
        html_content = await _get_html(self.hass, html_path)
        if html_content is None:
            _LOGGER.error("Admin page not found: %s", html_path)
            return web.Response(text="Admin page not found", status=500)
        return _html_response(html_content)


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
        html_content = await _get_html(self.hass, html_path)
        if html_content is None:
            _LOGGER.error("Launcher page not found: %s", html_path)
            return web.Response(text="Launcher page not found", status=500)
        return _html_response(html_content)


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
        html_content = await _get_html(self.hass, html_path)
        if html_content is None:
            _LOGGER.error("Player page not found: %s", html_path)
            return web.Response(text="Player page not found", status=500)
        return _html_response(html_content)


class SwJsView(HomeAssistantView):
    """Serve sw.js from /beatify/sw.js so the SW can claim /beatify/ scope (#780).

    The file on disk lives under www/ and is also reachable via /beatify/static/sw.js,
    but browsers limit a service worker's max scope to its own path. Registering
    /beatify/static/sw.js can only control /beatify/static/..., which defeats the
    purpose. Serving the same bytes at /beatify/sw.js lets the wider /beatify/
    scope register cleanly without needing a Service-Worker-Allowed header dance.
    """

    url = "/beatify/sw.js"
    name = "beatify:sw"
    requires_auth = False  # Must load unauthenticated on first admin/player visit

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the sw.js view."""
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:  # noqa: ARG002
        """Serve the service worker script."""
        sw_path = Path(__file__).parent.parent / "www" / "sw.js"
        try:
            content = await self.hass.async_add_executor_job(_read_file, sw_path)
        except OSError:
            _LOGGER.error("Service worker script not found: %s", sw_path)
            return web.Response(text="Service worker not found", status=500)
        # Must be served as JS. No-cache so CACHE_VERSION bumps propagate without
        # waiting for HTTP cache to expire on the SW bootstrap itself.
        return web.Response(
            text=content,
            content_type="application/javascript",
            headers=_NO_CACHE_HEADERS,
        )


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
            version=_get_version(self.hass),
            media_players=media_players,
            playlists=playlists,
        )

        return web.json_response(status)


class CapabilitiesView(HomeAssistantView):
    """Advertise which HA capabilities Beatify can light up in the wizard."""

    url = "/beatify/api/capabilities"
    name = "beatify:api:capabilities"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the capabilities view."""
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:  # noqa: ARG002
        """Return flags the wizard's Step 4 uses to gate toggles."""
        light_count = len(self.hass.states.async_all("light"))
        tts_services = self.hass.services.async_services().get("tts", {})
        return web.json_response(
            {
                "has_lights": light_count > 0,
                "light_count": light_count,
                "has_tts": bool(tts_services),
                "tts_service_count": len(tts_services),
            }
        )


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
        if game_state and game_state.phase in (GamePhase.PLAYING, GamePhase.REVEAL):
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
        """Speak a test message via TTS.

        Modern HA ``tts.speak`` requires both a TTS provider entity and a
        media player to route through (#793). Caller passes both:
        ``entity_id`` (the TTS entity) and ``media_player_entity_id``.
        """
        client_ip = request.remote or "unknown"
        if not self._check_rate_limit(client_ip):
            return _json_error("Too many requests", 429, code="RATE_LIMITED")
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return web.json_response({"error": "Invalid JSON"}, status=400)

        entity_id = body.get("entity_id", "")
        media_player_entity_id = body.get("media_player_entity_id", "")
        message = body.get("message", "")[: self.MAX_TTS_MESSAGE_LENGTH]
        if not entity_id or not message:
            return web.json_response(
                {"error": "entity_id and message required"}, status=400
            )
        if not media_player_entity_id:
            return web.json_response(
                {
                    "error": (
                        "media_player_entity_id required — TTS needs a speaker "
                        "to route through. Pick a media player in the wizard "
                        "first, then test TTS."
                    )
                },
                status=400,
            )

        tts_state = self.hass.states.get(entity_id)
        if not tts_state or tts_state.domain != "tts":
            return web.json_response(
                {
                    "error": (
                        f"{entity_id!r} is not a TTS entity. Expected "
                        "something like 'tts.google_translate_say' or "
                        "'tts.google_gemini_tts'."
                    )
                },
                status=400,
            )
        mp_state = self.hass.states.get(media_player_entity_id)
        if not mp_state or mp_state.domain != "media_player":
            return web.json_response(
                {"error": f"{media_player_entity_id!r} is not a media player"},
                status=400,
            )

        try:
            await self.hass.services.async_call(
                "tts",
                "speak",
                {
                    "entity_id": entity_id,
                    "media_player_entity_id": media_player_entity_id,
                    "message": message,
                },
                blocking=False,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception(
                "TTS test failed (tts=%s, media_player=%s)",
                entity_id,
                media_player_entity_id,
            )
            return web.json_response({"error": "TTS call failed"}, status=500)

        return web.json_response({"ok": True})
