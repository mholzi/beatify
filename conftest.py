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
    mod.__path__ = []  # type: ignore[attr-defined]
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
    "homeassistant.components.media_player",
    "homeassistant.components.media_player.const",
    "homeassistant.core",
    "homeassistant.config_entries",
    "homeassistant.helpers.aiohttp_client",
    "homeassistant.helpers.entity_platform",
    "homeassistant.helpers.storage",
    "homeassistant.helpers.entity",
    "homeassistant.helpers.event",
    "homeassistant.util.dt",
]

for _pkg in _PACKAGES:
    if _pkg not in sys.modules:
        _make_pkg(_pkg)

for _leaf in _LEAVES:
    if _leaf not in sys.modules:
        _make_leaf(_leaf)


# `homeassistant.components.http` needs special handling: views inherit from
# `HomeAssistantView`, so it must be a real class (not a MagicMock attribute)
# or every `class XView(RateLimitMixin, HomeAssistantView)` definition trips
# a metaclass conflict at import time. Provide a minimal real stub instead.
def _stub_http_module() -> None:
    if "homeassistant.components.http" in sys.modules:
        existing = sys.modules["homeassistant.components.http"]
        # If a previous run already installed a real HomeAssistantView, leave it.
        if hasattr(existing, "HomeAssistantView") and isinstance(
            existing.HomeAssistantView, type
        ):
            return
    http_mod = ModuleType("homeassistant.components.http")
    http_mod.__path__ = []  # type: ignore[attr-defined]

    class HomeAssistantView:  # noqa: D401 — runtime stub, signatures not enforced
        """Minimal stand-in so HTTP views can subclass without metaclass conflicts."""

        url: str = ""
        name: str = ""
        requires_auth: bool = False

    class StaticPathConfig:  # noqa: D401 — runtime stub
        """Stand-in for HA's static-path registration object."""

        def __init__(self, *args, **kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

    http_mod.HomeAssistantView = HomeAssistantView  # type: ignore[attr-defined]
    http_mod.StaticPathConfig = StaticPathConfig  # type: ignore[attr-defined]
    sys.modules["homeassistant.components.http"] = http_mod


_stub_http_module()


# `homeassistant.exceptions` needs real Exception subclasses, not MagicMock
# attributes — production code does `except (HomeAssistantError, ServiceNotFound)`
# and Python rejects catch-clauses that aren't actual exception types.
def _stub_exceptions_module() -> None:
    if "homeassistant.exceptions" in sys.modules:
        existing = sys.modules["homeassistant.exceptions"]
        if hasattr(existing, "HomeAssistantError") and isinstance(
            existing.HomeAssistantError, type
        ):
            return
    exc_mod = ModuleType("homeassistant.exceptions")

    class HomeAssistantError(Exception):
        """Stand-in for HA's base error class."""

    class ServiceNotFound(HomeAssistantError):
        """Stand-in for HA's missing-service error."""

    class ServiceValidationError(HomeAssistantError):
        """Stand-in for HA's service argument validation error."""

    exc_mod.HomeAssistantError = HomeAssistantError  # type: ignore[attr-defined]
    exc_mod.ServiceNotFound = ServiceNotFound  # type: ignore[attr-defined]
    exc_mod.ServiceValidationError = ServiceValidationError  # type: ignore[attr-defined]
    sys.modules["homeassistant.exceptions"] = exc_mod


_stub_exceptions_module()


# Wire child attributes onto parent packages so `from homeassistant.X import Y` works
_ha = sys.modules["homeassistant"]
_ha.components = sys.modules["homeassistant.components"]  # type: ignore[attr-defined]
_ha.helpers = sys.modules["homeassistant.helpers"]  # type: ignore[attr-defined]
_ha.util = sys.modules["homeassistant.util"]  # type: ignore[attr-defined]
