"""Shared base class and helpers for Beatify HTTP views."""

from __future__ import annotations

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

# Fallback version string used only if manifest.json could not be read at
# integration setup (very rare — would mean a malformed install). The real
# version is loaded from manifest.json once during async_setup_entry and
# cached in hass.data[DOMAIN]['version'] (#784).
#
# We deliberately do NOT read manifest.json at module import time: HA 2026.2+
# flags any blocking I/O at module level, including the reload path where the
# event loop is already running.
_VERSION_FALLBACK = "unknown"


def _get_version(hass: HomeAssistant | None = None) -> str:
    """
    Get the integration version.

    Reads from ``hass.data[DOMAIN]['version']`` (populated at setup_entry from
    manifest.json) when ``hass`` is provided. Falls back to the unknown sentinel
    if hass isn't available or the key isn't populated yet.
    """
    if hass is not None:
        try:
            data = hass.data.get(DOMAIN, {})
            version = data.get("version")
            if version:
                return version
        except (AttributeError, KeyError):  # pragma: no cover — defensive
            pass
    return _VERSION_FALLBACK


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
    """Base class for admin-protected Beatify views.

    #998: gating is delegated to Home Assistant's own auth — ``requires_auth``
    makes HA's middleware reject any request without a valid HA bearer token
    before the handler runs. The former per-game ``admin_token`` check is
    retired: a logged-in HA user *is* the admin.
    """

    requires_auth = True

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the view with hass reference."""
        self.hass = hass

    # -- helpers available to subclasses --

    def _get_game_state(self) -> Any | None:
        """Return the current GameState or None."""
        return self.hass.data.get(DOMAIN, {}).get("game")
