"""Real HA stubs for B6 platform tests (#1402).

The repo-root conftest.py registers most ``homeassistant.*`` leaf modules as
bare ``MagicMock`` objects so game logic imports cleanly. That is fine for code
that only *references* HA symbols, but the B6 platform modules need a few of
those symbols to behave like real classes/callables for assertions to be
meaningful:

* ``DeviceInfo`` must build a real (dict-like) mapping so we can assert on
  identifiers / name / sw_version.
* ``ConfigFlow`` must be a real base class accepting ``domain=...`` and
  exposing ``async_create_entry`` / ``async_show_form``.
* ``SensorEntity`` / ``BinarySensorEntity`` must be real classes to subclass.
* ``callback`` must be an identity decorator.

:func:`install` force-replaces just those symbols (the MagicMock leaves answer
``hasattr`` for everything, so we overwrite unconditionally). Call it once at
the top of a test module, BEFORE importing the beatify module under test.
"""

from __future__ import annotations

import sys
from types import ModuleType
from typing import Any


def _module(name: str) -> ModuleType:
    """Return a real ModuleType for ``name`` (replacing any MagicMock leaf)."""
    mod = sys.modules.get(name)
    if not isinstance(mod, ModuleType):
        mod = ModuleType(name)
        sys.modules[name] = mod
    return mod


class _DeviceInfo(dict):
    """Dict-backed stand-in for HA's DeviceInfo TypedDict."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)


class _ConfigFlow:
    """Tiny ConfigFlow stand-in accepting the ``domain=...`` subclass kwarg."""

    hass: Any = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__()

    def async_create_entry(self, **kwargs: Any) -> dict[str, Any]:
        return {"type": "create_entry", **kwargs}

    def async_show_form(self, **kwargs: Any) -> dict[str, Any]:
        return {"type": "form", **kwargs}


def install() -> None:
    """Force-install real HA stubs needed by the B6 platform modules."""
    core = _module("homeassistant.core")
    core.callback = lambda func: func  # type: ignore[attr-defined]
    if not isinstance(getattr(core, "HomeAssistant", None), type):
        core.HomeAssistant = object  # type: ignore[attr-defined]

    ce = _module("homeassistant.config_entries")
    ce.ConfigEntry = object  # type: ignore[attr-defined]
    ce.ConfigFlowResult = dict  # type: ignore[attr-defined]
    ce.ConfigFlow = _ConfigFlow  # type: ignore[attr-defined]

    # Base entity classes expose a no-op async_write_ha_state so _on_state_changed
    # can be invoked directly in tests.
    _entity_ns = {"async_write_ha_state": lambda self: None}
    sensor = _module("homeassistant.components.sensor")
    sensor.SensorEntity = type(  # type: ignore[attr-defined]
        "SensorEntity", (), dict(_entity_ns)
    )
    bsensor = _module("homeassistant.components.binary_sensor")
    bsensor.BinarySensorEntity = type(  # type: ignore[attr-defined]
        "BinarySensorEntity", (), dict(_entity_ns)
    )

    helpers_entity = _module("homeassistant.helpers.entity")
    helpers_entity.DeviceInfo = _DeviceInfo  # type: ignore[attr-defined]
    plat = _module("homeassistant.helpers.entity_platform")
    plat.AddEntitiesCallback = object  # type: ignore[attr-defined]

    # ``config_flow`` does ``import voluptuous as vol`` at module top — but
    # voluptuous is a Home Assistant runtime dep that is NOT installed in the
    # minimal CI unit-test env (requirements_test.txt only). Stub it so the
    # import resolves; config_flow only needs ``vol.Schema({})`` to build an
    # (empty) data schema, so a passthrough callable is enough.
    vol = _module("voluptuous")
    vol.Schema = lambda schema=None, **kwargs: schema  # type: ignore[attr-defined]
