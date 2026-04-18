"""Shared base class and helpers for Beatify HTTP views."""

from __future__ import annotations

import hmac
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from custom_components.beatify.const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Version is set here and bumped alongside manifest.json in release commits.
# We avoid reading manifest.json at runtime because HA imports custom components
# inside the event loop, and any file I/O (even at module level) triggers
# blocking call warnings in HA 2026.2+.
_VERSION = "3.2.0-rc25"


def _get_version() -> str:
    """Get the integration version."""
    return _VERSION


def _read_file(path: Path) -> str:
    """Read file contents (runs in executor)."""
    return path.read_text(encoding="utf-8")


_html_cache: dict[str, str] = {}


async def _get_html(hass: HomeAssistant, path: Path) -> str | None:
    """Read HTML file with in-memory caching."""
    key = str(path)
    if key in _html_cache:
        return _html_cache[key]
    if not path.exists():
        return None
    content = await hass.async_add_executor_job(_read_file, path)
    _html_cache[key] = content
    return content


def _json_error(message: str, status: int, *, code: str = "ERROR") -> web.Response:
    """Return a consistent JSON error response."""
    return web.json_response({"error": code, "message": message}, status=status)


def _verify_admin_token(request: web.Request, game_state: Any) -> bool:
    """Verify admin token from Authorization header or query param (#386).

    Accepts:
    - Header: Authorization: Bearer <token>
    - Query: ?admin_token=<token>
    """
    if not game_state or not game_state.admin_token:
        return False
    token = None
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
    if not token:
        token = request.query.get("admin_token")
    if not token:
        return False
    return hmac.compare_digest(token, game_state.admin_token)


class RateLimitMixin:
    """Mixin providing IP-based rate limiting for views."""

    RATE_LIMIT_REQUESTS: int = 5
    RATE_LIMIT_WINDOW: int = 60  # seconds

    def _init_rate_limits(self) -> None:
        """Initialize rate limit state. Call from __init__."""
        self._rate_limits: dict[str, list[float]] = {}
        self._last_sweep: float = 0.0

    def _check_rate_limit(self, ip: str) -> bool:
        """Check if IP is within rate limit."""
        now = time.time()
        cutoff = now - self.RATE_LIMIT_WINDOW
        if now - self._last_sweep > 300:
            self._rate_limits = {
                k: [t for t in v if t > cutoff]
                for k, v in self._rate_limits.items()
                if any(t > cutoff for t in v)
            }
            self._last_sweep = now
        times = [t for t in self._rate_limits.get(ip, []) if t > cutoff]
        self._rate_limits[ip] = times
        if len(times) >= self.RATE_LIMIT_REQUESTS:
            return False
        times.append(now)
        return True


class BeatifyAdminView(HomeAssistantView):
    """Base class for admin-protected Beatify views."""

    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the view with hass reference."""
        self.hass = hass

    # -- helpers available to subclasses --

    def _get_game_state(self) -> Any | None:
        """Return the current GameState or None."""
        return self.hass.data.get(DOMAIN, {}).get("game")

    def _verify_admin(self, request: web.Request) -> web.Response | None:
        """Verify admin token; return an error response if invalid, else None."""
        game_state = self._get_game_state()
        if not _verify_admin_token(request, game_state):
            return _json_error("Admin token required", 403, code="UNAUTHORIZED")
        return None
