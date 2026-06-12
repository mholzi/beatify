"""Binary sensor platform for Beatify (Issue #441).

Exposes a binary sensor for whether a game is active:
- beatify_game_active
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .device import build_device_info
from .game.state import GamePhase, GameState

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Beatify binary sensor entities from a config entry."""
    game_state: GameState = hass.data[DOMAIN]["game"]
    device_info = build_device_info(hass, entry.entry_id)
    async_add_entities(
        [BeatifyGameActiveSensor(game_state, entry.entry_id, device_info)]
    )


class BeatifyGameActiveSensor(BinarySensorEntity):
    """Binary sensor indicating whether a Beatify game is active."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_name = "Beatify game active"
    _attr_icon = "mdi:gamepad-variant"

    def __init__(
        self, game_state: GameState, entry_id: str, device_info: DeviceInfo
    ) -> None:
        self._game_state = game_state
        self._attr_unique_id = f"{entry_id}_game_active"
        # #1402 B6: share the single Beatify device with the sensor platform.
        self._attr_device_info = device_info

    async def async_added_to_hass(self) -> None:
        """Register state callback when entity is added."""
        self._game_state.register_state_callback(self._on_state_changed)

    async def async_will_remove_from_hass(self) -> None:
        """Unregister state callback when entity is removed."""
        self._game_state.unregister_state_callback(self._on_state_changed)

    @callback
    def _on_state_changed(self) -> None:
        """Handle game state change."""
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        return self._game_state.game_id is not None and self._game_state.phase in (
            GamePhase.PLAYING,
            GamePhase.REVEAL,
            GamePhase.PAUSED,
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        # #1402 B6: reuse GameState.leader instead of recomputing the max() —
        # the property already owns the leader-selection logic (and its
        # empty-players guard), so duplicating it here risked divergence.
        leader = self._game_state.leader
        leader_name = leader.name if leader else None

        return {
            "phase": self._game_state.phase.value,
            "round": self._game_state.round,
            "leader": leader_name,
        }
