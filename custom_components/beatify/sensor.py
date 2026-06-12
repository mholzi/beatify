"""Sensor platform for Beatify (Issue #441).

Exposes game state as Home Assistant sensor entities:
- beatify_current_round
- beatify_leader
- beatify_top_score
- beatify_player_count
- beatify_current_song
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
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
    """Set up Beatify sensor entities from a config entry."""
    game_state: GameState = hass.data[DOMAIN]["game"]
    device_info = build_device_info(hass, entry.entry_id)

    entities = [
        BeatifyCurrentRoundSensor(game_state, entry.entry_id, device_info),
        BeatifyLeaderSensor(game_state, entry.entry_id, device_info),
        BeatifyTopScoreSensor(game_state, entry.entry_id, device_info),
        BeatifyPlayerCountSensor(game_state, entry.entry_id, device_info),
        BeatifyCurrentSongSensor(game_state, entry.entry_id, device_info),
    ]
    async_add_entities(entities)


class BeatifySensorBase(SensorEntity):
    """Base class for Beatify sensors with push-based updates."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(
        self, game_state: GameState, entry_id: str, device_info: DeviceInfo
    ) -> None:
        self._game_state = game_state
        self._attr_unique_id = f"{entry_id}_{self._sensor_key}"
        # #1402 B6: attach every entity to a single Beatify device so the six
        # sensors don't float without a device in the registry.
        self._attr_device_info = device_info

    @property
    def _sensor_key(self) -> str:
        raise NotImplementedError

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
    def _game_active(self) -> bool:
        return self._game_state.game_id is not None and self._game_state.phase not in (
            GamePhase.LOBBY,
        )


class BeatifyCurrentRoundSensor(BeatifySensorBase):
    """Sensor for the current round number."""

    _attr_name = "Beatify current round"
    _attr_icon = "mdi:numeric"
    _sensor_key = "current_round"

    @property
    def native_value(self) -> int:
        return self._game_state.round

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "total_rounds": self._game_state.total_rounds,
            "phase": self._game_state.phase.value,
        }


class BeatifyLeaderSensor(BeatifySensorBase):
    """Sensor for the current game leader."""

    _attr_name = "Beatify leader"
    _attr_icon = "mdi:trophy"
    _sensor_key = "leader"

    @property
    def native_value(self) -> str | None:
        leader = self._game_state.leader
        if leader is None:
            return None
        return leader.name

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        leader = self._game_state.leader
        if leader is None:
            return {"score": 0, "player_count": 0}
        return {
            "score": leader.score,
            "player_count": len(self._game_state.players),
        }


class BeatifyTopScoreSensor(BeatifySensorBase):
    """Sensor for the top score."""

    _attr_name = "Beatify top score"
    _attr_icon = "mdi:star"
    _sensor_key = "top_score"

    @property
    def native_value(self) -> int:
        leader = self._game_state.leader
        if leader is None:
            return 0
        return leader.score


class BeatifyPlayerCountSensor(BeatifySensorBase):
    """Sensor for the player count."""

    _attr_name = "Beatify player count"
    _attr_icon = "mdi:account-group"
    _sensor_key = "player_count"

    @property
    def native_value(self) -> int:
        return len(self._game_state.players)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "players": [p.name for p in self._game_state.players.values()],
        }


class BeatifyCurrentSongSensor(BeatifySensorBase):
    """Sensor for the current song.

    Hidden (unknown) during PLAYING phase, shown during REVEAL/END/between games.
    Holds last played song between rounds/games.
    """

    _attr_name = "Beatify current song"
    _attr_icon = "mdi:music-note"
    _sensor_key = "current_song"

    def __init__(
        self, game_state: GameState, entry_id: str, device_info: DeviceInfo
    ) -> None:
        super().__init__(game_state, entry_id, device_info)
        self._last_title: str | None = None
        self._last_artist: str | None = None
        self._last_year: int | None = None

    @callback
    def _on_state_changed(self) -> None:
        """Refresh the cached song before writing state (#1402 B6).

        The cache update used to be a side effect of reading ``native_value``,
        which made an HA property impure — repeated reads (or a read that never
        happened) could leave the cache out of sync. The cache is now refreshed
        exactly once per game-state change, here, before ``async_write_ha_state``
        re-reads the now-pure properties.
        """
        phase = self._game_state.phase
        song = self._game_state.current_song
        if song and phase != GamePhase.PLAYING:
            self._last_title = song.get("title")
            self._last_artist = song.get("artist")
            self._last_year = song.get("year")
        super()._on_state_changed()

    @property
    def native_value(self) -> str | None:
        # Pure read: caching happens in _on_state_changed (#1402 B6).
        if self._game_state.phase == GamePhase.PLAYING:
            # Hidden during PLAYING phase
            return None
        return self._last_title

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        phase = self._game_state.phase

        if phase == GamePhase.PLAYING:
            return {"artist": None, "year": None}

        return {
            "artist": self._last_artist,
            "year": self._last_year,
        }
