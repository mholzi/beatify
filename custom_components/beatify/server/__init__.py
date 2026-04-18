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
    """Register static file paths for serving CSS, JS, and images.

    cache_headers=False: HA's default sends ``Cache-Control: public, max-age=2678400``
    (31 days). Combined with HACS updates that don't always touch every file, users
    ended up with admin.html pointing at ``?v=3.2.0-rcN`` while the browser held
    onto a month-old admin.min.js under that same URL. Switching to conditional
    GETs (ETag / Last-Modified) means the browser revalidates on every load and
    picks up fresh bytes the moment the file on disk changes.
    """
    www_path = Path(__file__).parent.parent / "www"

    await hass.http.async_register_static_paths(
        [StaticPathConfig("/beatify/static", str(www_path), cache_headers=False)]
    )

    _LOGGER.debug("Registered static path: /beatify/static -> %s", www_path)
