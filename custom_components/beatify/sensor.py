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
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .game.state import GamePhase, GameState

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Beatify sensor entities from a config entry."""
    game_state: GameState = hass.data[DOMAIN]["game"]

    entities = [
        BeatifyCurrentRoundSensor(game_state, entry.entry_id),
        BeatifyLeaderSensor(game_state, entry.entry_id),
        BeatifyTopScoreSensor(game_state, entry.entry_id),
        BeatifyPlayerCountSensor(game_state, entry.entry_id),
        BeatifyCurrentSongSensor(game_state, entry.entry_id),
    ]
    async_add_entities(entities)


class BeatifySensorBase(SensorEntity):
    """Base class for Beatify sensors with push-based updates."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, game_state: GameState, entry_id: str) -> None:
        self._game_state = game_state
        self._attr_unique_id = f"{entry_id}_{self._sensor_key}"

    @property
    def _sensor_key(self) -> str:
        raise NotImplementedError

    async def async_added_to_hass(self) -> None:
        """Register state callback when entity is added."""
        self._game_state.register_state_callback(self._on_state_changed)

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
        players = self._game_state.players
        if not players:
            return None
        leader = max(players.values(), key=lambda p: p.score)
        return leader.name

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        players = self._game_state.players
        if not players:
            return {"score": 0, "player_count": 0}
        leader = max(players.values(), key=lambda p: p.score)
        return {
            "score": leader.score,
            "player_count": len(players),
        }


class BeatifyTopScoreSensor(BeatifySensorBase):
    """Sensor for the top score."""

    _attr_name = "Beatify top score"
    _attr_icon = "mdi:star"
    _sensor_key = "top_score"

    @property
    def native_value(self) -> int:
        players = self._game_state.players
        if not players:
            return 0
        return max(p.score for p in players.values())


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

    def __init__(self, game_state: GameState, entry_id: str) -> None:
        super().__init__(game_state, entry_id)
        self._last_title: str | None = None
        self._last_artist: str | None = None
        self._last_year: int | None = None

    @property
    def native_value(self) -> str | None:
        phase = self._game_state.phase
        song = self._game_state.current_song

        # Update cache when song info is available during non-PLAYING phases
        if song and phase != GamePhase.PLAYING:
            self._last_title = song.get("title")
            self._last_artist = song.get("artist")
            self._last_year = song.get("year")

        # Hidden during PLAYING phase
        if phase == GamePhase.PLAYING:
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
