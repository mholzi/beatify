"""Analytics, stats, and dashboard HTTP views for Beatify."""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from custom_components.beatify.const import DOMAIN
from custom_components.beatify.server.base import (
    RateLimitMixin,
    _get_html,
    _json_error,
    _verify_admin_token,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class DashboardView(HomeAssistantView):
    """Serve the spectator dashboard page."""

    url = "/beatify/dashboard"
    name = "beatify:dashboard"
    requires_auth = False  # Frictionless access per PRD

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the dashboard view."""
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:  # noqa: ARG002
        """Serve the dashboard HTML page."""
        html_path = Path(__file__).parent.parent / "www" / "dashboard.html"
        html_content = await _get_html(self.hass, html_path)
        if html_content is None:
            _LOGGER.error("Dashboard page not found: %s", html_path)
            return web.Response(text="Dashboard page not found", status=500)
        return web.Response(text=html_content, content_type="text/html")


class StatsView(HomeAssistantView):
    """API endpoint for game statistics (Story 14.4)."""

    url = "/beatify/api/stats"
    name = "beatify:api:stats"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:
        """Get game statistics summary and history."""
        # Issue #386: Admin token required when game is active
        game_state = self.hass.data.get(DOMAIN, {}).get("game")
        if (
            game_state
            and game_state.game_id
            and not _verify_admin_token(request, game_state)
        ):
            return _json_error("Admin token required", 403, code="UNAUTHORIZED")

        stats_service = self.hass.data.get(DOMAIN, {}).get("stats")

        if not stats_service:
            return web.json_response(
                {
                    "summary": {
                        "games_played": 0,
                        "highest_avg_score": 0.0,
                        "all_time_avg": 0.0,
                    },
                    "history": [],
                }
            )

        summary = await stats_service.get_summary()
        history = await stats_service.get_history(limit=10)

        return web.json_response(
            {
                "summary": summary,
                "history": history,
            }
        )


class AnalyticsView(RateLimitMixin, HomeAssistantView):
    """API endpoint for analytics dashboard data (Story 19.2)."""

    url = "/beatify/api/analytics"
    name = "beatify:api:analytics"
    requires_auth = False

    # Valid period values
    VALID_PERIODS = ("7d", "30d", "90d", "all")
    # Rate limiting: max requests per IP per minute
    RATE_LIMIT_REQUESTS = 30
    RATE_LIMIT_WINDOW = 60  # seconds

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass
        self._cache: dict | None = None
        self._cache_time: float = 0
        self._cache_ttl: float = 60.0  # 60 second cache
        self._init_rate_limits()

    async def get(self, request: web.Request) -> web.Response:
        """Get analytics metrics with caching and rate limiting."""

        # Rate limiting check
        client_ip = request.remote or "unknown"
        if not self._check_rate_limit(client_ip):
            return _json_error("Too many requests", 429, code="RATE_LIMITED")

        # Validate period parameter
        period = request.query.get("period", "30d")
        if period not in self.VALID_PERIODS:
            period = "30d"  # Fallback to default

        analytics = self.hass.data.get(DOMAIN, {}).get("analytics")

        if not analytics:
            return web.json_response(
                {
                    "period": period,
                    "total_games": 0,
                    "avg_players_per_game": 0,
                    "avg_score": 0,
                    "error_rate": 0,
                    "trends": {"games": 0, "players": 0, "score": 0, "errors": 0},
                    "generated_at": int(time.time()),
                }
            )

        # Check cache (invalidate if period changed or TTL expired)
        now = time.time()
        if (
            self._cache
            and self._cache.get("period") == period
            and (now - self._cache_time) < self._cache_ttl
        ):
            return web.json_response(self._cache)

        # Compute fresh metrics
        data = analytics.compute_metrics(period)
        self._cache = data
        self._cache_time = now

        return web.json_response(data)


class AnalyticsPageView(HomeAssistantView):
    """Serve the analytics dashboard page (Story 19.2)."""

    url = "/beatify/analytics"
    name = "beatify:analytics"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the view."""
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:  # noqa: ARG002
        """Serve analytics page."""
        www_path = Path(__file__).parent.parent / "www" / "analytics.html"
        content = await _get_html(self.hass, www_path)
        if content is None:
            return web.Response(text="Analytics page not found", status=404)
        return web.Response(text=content, content_type="text/html")


class SongStatsView(HomeAssistantView):
    """API endpoint for song statistics (Story 19.7)."""

    url = "/beatify/api/analytics/songs"
    name = "beatify:api:analytics:songs"
    requires_auth = False

    # Cache settings
    CACHE_TTL = 60.0  # 60 second cache

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass
        self._cache: dict | None = None
        self._cache_time: float = 0
        self._cache_playlist: str | None = None

    async def get(self, request: web.Request) -> web.Response:
        """Get song statistics with optional playlist filter (Story 19.7 AC3)."""

        # Get optional playlist filter
        playlist_filter = request.query.get("playlist")

        stats_service = self.hass.data.get(DOMAIN, {}).get("stats")

        if not stats_service:
            return web.json_response(
                {
                    "most_played": None,
                    "hardest": None,
                    "easiest": None,
                    "by_playlist": [],
                }
            )

        # Check cache (invalidate if playlist changed or TTL expired)
        now = time.time()
        if (
            self._cache
            and self._cache_playlist == playlist_filter
            and (now - self._cache_time) < self.CACHE_TTL
        ):
            return web.json_response(self._cache)

        # Compute fresh stats
        data = stats_service.compute_song_stats(playlist_filter)
        self._cache = data
        self._cache_time = now
        self._cache_playlist = playlist_filter

        return web.json_response(data)


class UsageView(HomeAssistantView):
    """Local usage stats for the Playlist Hub (v3.3).

    Powers the "Your most-played" and "Recently played" shelves. Data never
    leaves this HA host — derived entirely from the existing GameRecord log.
    """

    url = "/beatify/api/usage"
    name = "beatify:api:usage"
    requires_auth = False

    CACHE_TTL = 30.0  # seconds

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass
        self._cache: dict[str, tuple[float, list]] = {}

    async def get(self, request: web.Request) -> web.Response:
        """Return top-played or recently-played playlists for the current host."""
        kind = request.query.get("kind", "top")
        if kind not in ("top", "recent"):
            return _json_error(
                "kind must be 'top' or 'recent'", 400, code="BAD_REQUEST"
            )

        try:
            limit = int(request.query.get("limit", "8" if kind == "top" else "12"))
        except (TypeError, ValueError):
            return _json_error("limit must be an integer", 400, code="BAD_REQUEST")
        limit = max(1, min(limit, 50))

        analytics = self.hass.data.get(DOMAIN, {}).get("analytics")
        if not analytics:
            return web.json_response({"kind": kind, "limit": limit, "items": []})

        cache_key = f"{kind}:{limit}"
        now = time.time()
        cached = self._cache.get(cache_key)
        if cached and (now - cached[0]) < self.CACHE_TTL:
            return web.json_response({"kind": kind, "limit": limit, "items": cached[1]})

        if kind == "top":
            items = analytics.get_top_playlists(limit=limit)
        else:
            items = analytics.get_recent_playlists(limit=limit)

        self._cache[cache_key] = (now, items)
        return web.json_response({"kind": kind, "limit": limit, "items": items})
