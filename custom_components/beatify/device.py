"""Shared HA device descriptor for Beatify entities (#1402 B6).

All Beatify sensor and binary_sensor entities attach to a single logical
"Beatify" device so they don't float without a device in the entity registry.
Both platforms build their ``DeviceInfo`` through :func:`build_device_info` to
keep identifiers, name, manufacturer and sw_version identical.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


def build_device_info(hass: HomeAssistant, entry_id: str) -> DeviceInfo:
    """Build the shared Beatify device descriptor.

    The ``sw_version`` is read from ``hass.data[DOMAIN]["version"]``, which
    async_setup_entry populates from manifest.json (#784) before forwarding the
    platforms — so it is always present by the time entities are created. A
    defensive fallback keeps the helper safe if called out of order.
    """
    version = hass.data.get(DOMAIN, {}).get("version", "unknown")
    return DeviceInfo(
        identifiers={(DOMAIN, entry_id)},
        name="Beatify",
        manufacturer="Beatify",
        sw_version=version,
    )
