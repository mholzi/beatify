"""Playlist-related HTTP views for Beatify."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from custom_components.beatify.server.base import (
    RateLimitMixin,
    _json_error,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class PlaylistRequestsView(RateLimitMixin, HomeAssistantView):
    """API for managing playlist requests (Story 44).

    Stores requests in a JSON file on the HA server so they persist
    across browser sessions and devices.
    """

    url = "/beatify/api/playlist-requests"
    name = "beatify:api:playlist-requests"
    requires_auth = False

    MAX_REQUESTS = 100
    MAX_FIELD_LENGTH = 500
    RATE_LIMIT_REQUESTS = 10
    RATE_LIMIT_WINDOW = 60  # seconds

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass
        self._storage_path = Path(hass.config.path("beatify/playlist_requests.json"))
        self._init_rate_limits()

    def _sanitize_item(self, item: object) -> dict | None:
        """Validate and sanitize a single playlist request item."""
        if not isinstance(item, dict):
            return None
        sanitized = {}
        for key, value in item.items():
            if not isinstance(key, str) or len(key) > 50:
                continue
            if isinstance(value, str):
                sanitized[key] = value[: self.MAX_FIELD_LENGTH]
            elif isinstance(value, (int, float, bool)):
                sanitized[key] = value
        return sanitized if sanitized else None

    def _load_requests(self) -> dict:
        """Load requests from storage file."""
        if self._storage_path.exists():
            try:
                return json.loads(self._storage_path.read_text(encoding="utf-8"))
            except Exception as e:  # noqa: BLE001
                _LOGGER.error("Failed to load playlist requests: %s", e)
        return {"requests": [], "last_poll": None}

    def _save_requests(self, data: dict) -> bool:
        """Save requests to storage file."""
        try:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            self._storage_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            return True
        except Exception as e:  # noqa: BLE001
            _LOGGER.error("Failed to save playlist requests: %s", e)
            return False

    async def get(self, request: web.Request) -> web.Response:  # noqa: ARG002
        """Get all playlist requests."""
        data = await self.hass.async_add_executor_job(self._load_requests)
        return web.json_response(data)

    async def post(self, request: web.Request) -> web.Response:
        """Save playlist requests (replaces all data)."""
        # Rate limiting
        client_ip = request.remote or "unknown"
        if not self._check_rate_limit(client_ip):
            return _json_error("Too many requests", 429, code="RATE_LIMITED")

        try:
            body = await request.json(content_type=None)
        except Exception:  # noqa: BLE001
            return _json_error("Invalid JSON", 400, code="INVALID_REQUEST")

        # Validate data structure
        if not isinstance(body.get("requests"), list):
            return _json_error(
                "Missing or invalid requests array", 400, code="INVALID_REQUEST"
            )

        raw_requests = body["requests"][: self.MAX_REQUESTS]

        # Sanitize each item
        sanitized = []
        for item in raw_requests:
            clean = self._sanitize_item(item)
            if clean is not None:
                sanitized.append(clean)

        # Build storage object
        data = {
            "requests": sanitized,
            "last_poll": body.get("last_poll"),
        }

        # Save to file
        success = await self.hass.async_add_executor_job(self._save_requests, data)
        if not success:
            return _json_error("Failed to save request", 500, code="SAVE_FAILED")

        return web.json_response({"success": True, "requests": data["requests"]})
