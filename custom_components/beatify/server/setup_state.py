"""Server-side persistence of the admin's "setup complete" flag (#1663).

The first-run wizard writes the host's picks (speaker + game settings) to
``localStorage``. That makes a fully-configured instance look *unconfigured*
the moment the host opens the admin on a new device or browser — the home view
drops back to the setup prompt instead of the ready-to-play landing.

This module persists the host's setup blob on the HA server so any device can
learn that setup is done and re-hydrate the same picks. The blob is stored
*verbatim* (opaque to the server) so the frontend owns its own schema — the
server never has to track the client-side settings shape.

All disk I/O here is blocking and MUST be offloaded to the executor by callers
(see ``async_add_executor_job``) so it never runs on the HA event loop.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

SETUP_FILENAME = "setup.json"


def _setup_path(hass: HomeAssistant) -> Path:
    """Return the on-disk path of the persisted setup blob."""
    return Path(hass.config.path("beatify")) / SETUP_FILENAME


def read_setup(hass: HomeAssistant) -> dict[str, Any] | None:
    """Read the persisted setup blob (blocking I/O).

    Returns ``None`` when nothing has been saved yet or the file is unreadable
    / malformed — callers treat all of these as "not configured on the server".
    """
    path = _setup_path(hass)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _LOGGER.warning("Failed to read Beatify setup blob at %s", path)
        return None
    return data if isinstance(data, dict) else None


def write_setup(hass: HomeAssistant, blob: dict[str, Any]) -> None:
    """Persist the setup blob to disk (blocking I/O)."""
    path = _setup_path(hass)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(blob, indent=2, ensure_ascii=False), encoding="utf-8")


def clear_setup(hass: HomeAssistant) -> bool:
    """Delete the persisted setup blob (blocking I/O). Returns whether one existed.

    #2036: the force-reset escape hatch clears the host's ``localStorage`` and
    reloads, but the blob written here survived — and ``reconcileSavedSetup()``
    then wrote the speaker straight back into the freshly emptied storage on the
    very next page load (the "server wins" rule from #1927). The wizard's
    ``shouldTrigger()`` saw a configured host again and stayed shut, so a reset
    landed back on the ready-to-host screen it was supposed to leave.

    Deleting the file rather than writing ``{}`` keeps a single notion of
    "nothing saved": ``read_setup`` already returns ``None`` for a missing file,
    so no caller needs to learn a second empty shape.
    """
    path = _setup_path(hass)
    try:
        path.unlink()
    except FileNotFoundError:
        return False
    return True
