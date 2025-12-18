"""Server module for Beatify HTTP endpoints."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from homeassistant.components.http import StaticPathConfig

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


async def async_register_static_paths(hass: HomeAssistant) -> None:
    """Register static file paths for serving CSS, JS, and images."""
    www_path = Path(__file__).parent.parent / "www"

    await hass.http.async_register_static_paths([
        StaticPathConfig("/beatify/static", str(www_path), cache_headers=True)
    ])

    _LOGGER.debug("Registered static path: /beatify/static -> %s", www_path)
