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


# `homeassistant.core.callback` must behave like the real decorator (#3283):
# mark the function and return it unchanged. As a bare MagicMock attribute it
# would replace every ``@callback`` function with a mock, and tests that mimic
# Home Assistant's dispatch read the marker to decide whether a listener runs
# in the event loop (marked) or in a worker thread (not marked).
def _ha_callback(func):
    func._hass_callback = True
    return func


sys.modules["homeassistant.core"].callback = _ha_callback  # type: ignore[attr-defined]


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
        """Stand-in for HA's base error class.

        Accepts the translation keywords the real class takes (#3306), so a
        test can assert on *which* translated refusal an action raised.
        """

        def __init__(
            self,
            *args,
            translation_domain=None,
            translation_key=None,
            translation_placeholders=None,
        ) -> None:
            super().__init__(*args)
            self.translation_domain = translation_domain
            self.translation_key = translation_key
            self.translation_placeholders = translation_placeholders

    class ServiceNotFound(HomeAssistantError):
        """Stand-in for HA's missing-service error."""

    class ServiceValidationError(HomeAssistantError):
        """Stand-in for HA's service argument validation error."""

    class Unauthorized(HomeAssistantError):
        """Stand-in for HA's permission error (#3306)."""

        def __init__(self, context=None, user_id=None, **kwargs) -> None:
            super().__init__("Unauthorized")
            self.context = context
            self.user_id = user_id

    class UnknownUser(Unauthorized):
        """Stand-in for HA's unknown-user error (#3306)."""

    exc_mod.HomeAssistantError = HomeAssistantError  # type: ignore[attr-defined]
    exc_mod.ServiceNotFound = ServiceNotFound  # type: ignore[attr-defined]
    exc_mod.ServiceValidationError = ServiceValidationError  # type: ignore[attr-defined]
    exc_mod.Unauthorized = Unauthorized  # type: ignore[attr-defined]
    exc_mod.UnknownUser = UnknownUser  # type: ignore[attr-defined]
    sys.modules["homeassistant.exceptions"] = exc_mod


_stub_exceptions_module()


# `voluptuous` is a Home Assistant runtime dependency, not a test dependency.
# The integration's action schemas (#3306) are built at import time, so give
# the package import a passthrough stand-in when the real library is absent.
# Schemas are not exercised here: every action re-checks its own input.
def _stub_voluptuous_module() -> None:
    try:
        import voluptuous  # noqa: F401, PLC0415
    except ImportError:
        vol_mod = ModuleType("voluptuous")
        vol_mod.Schema = lambda schema=None, **kwargs: schema  # type: ignore[attr-defined]
        vol_mod.Optional = lambda key, **kwargs: key  # type: ignore[attr-defined]
        vol_mod.Required = lambda key, **kwargs: key  # type: ignore[attr-defined]
        vol_mod.In = lambda container, **kwargs: container  # type: ignore[attr-defined]
        sys.modules["voluptuous"] = vol_mod


_stub_voluptuous_module()


# Wire child attributes onto parent packages so `from homeassistant.X import Y` works
_ha = sys.modules["homeassistant"]
_ha.components = sys.modules["homeassistant.components"]  # type: ignore[attr-defined]
_ha.helpers = sys.modules["homeassistant.helpers"]  # type: ignore[attr-defined]
_ha.util = sys.modules["homeassistant.util"]  # type: ignore[attr-defined]
