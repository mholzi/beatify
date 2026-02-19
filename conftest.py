"""
Root conftest.py: stub all homeassistant (HA) modules so beatify game
logic can be imported and tested without a running HA instance.

Must live at the repo root — pytest processes it before any test file
or tests/conftest.py imports happen.
"""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock


def _make_pkg(name: str) -> ModuleType:
    """Register a real (empty) package so sub-imports work."""
    mod = ModuleType(name)
    mod.__path__ = []          # type: ignore[attr-defined]
    mod.__package__ = name
    sys.modules[name] = mod
    return mod


def _make_leaf(name: str) -> MagicMock:
    """Register a MagicMock leaf module (attribute access is unrestricted)."""
    mock = MagicMock()
    mock.__name__ = name
    mock.__spec__ = None
    sys.modules[name] = mock
    return mock


# ---------------------------------------------------------------------------
# Stub homeassistant package hierarchy
# ---------------------------------------------------------------------------

_PACKAGES = [
    "homeassistant",
    "homeassistant.components",
    "homeassistant.helpers",
    "homeassistant.util",
]

_LEAVES = [
    "homeassistant.components.frontend",
    "homeassistant.components.http",
    "homeassistant.components.media_player",
    "homeassistant.components.media_player.const",
    "homeassistant.core",
    "homeassistant.config_entries",
    "homeassistant.helpers.aiohttp_client",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.storage",
    "homeassistant.helpers.entity",
    "homeassistant.helpers.event",
    "homeassistant.exceptions",
    "homeassistant.util.dt",
]

for _pkg in _PACKAGES:
    if _pkg not in sys.modules:
        _make_pkg(_pkg)

for _leaf in _LEAVES:
    if _leaf not in sys.modules:
        _make_leaf(_leaf)

# Wire child attributes onto parent packages so `from homeassistant.X import Y` works
_ha = sys.modules["homeassistant"]
_ha.components = sys.modules["homeassistant.components"]   # type: ignore[attr-defined]
_ha.helpers = sys.modules["homeassistant.helpers"]         # type: ignore[attr-defined]
_ha.util = sys.modules["homeassistant.util"]               # type: ignore[attr-defined]
