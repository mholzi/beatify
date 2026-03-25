"""Party Lights service for Beatify — automated light control during games (#331)."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Phase colors (rgb_color values)
PHASE_COLORS: dict[str, dict[str, Any]] = {
    "LOBBY": {"rgb_color": [147, 112, 219], "brightness": 102},
    "PLAYING": {"rgb_color": [0, 100, 255], "brightness": 153},
    "REVEAL": {"color_temp_kelvin": 3000, "brightness": 204},
    "END": {"brightness": 255},
}

# Flash colors
FLASH_COLORS: dict[str, list[int]] = {
    "gold": [255, 215, 0],
    "green": [0, 255, 0],
    "red": [255, 0, 0],
    "orange": [255, 165, 0],
}

# Rainbow colors for celebration
RAINBOW_COLORS: list[list[int]] = [
    [255, 0, 0],
    [255, 127, 0],
    [255, 255, 0],
    [0, 255, 0],
    [0, 0, 255],
    [75, 0, 130],
    [148, 0, 211],
]

# Intensity presets: (brightness_scale, flash_duration)
INTENSITY_PRESETS: dict[str, dict[str, float]] = {
    "subtle": {"brightness_scale": 0.6, "flash_duration": 0.8},
    "medium": {"brightness_scale": 1.0, "flash_duration": 0.5},
    "party": {"brightness_scale": 1.0, "flash_duration": 0.3},
}


class PartyLightsService:
    """Control Home Assistant lights during Beatify games."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize with Home Assistant instance."""
        self._hass = hass
        self._entity_ids: list[str] = []
        self._intensity: str = "medium"
        self._saved_states: dict[str, dict[str, Any]] = {}
        self._current_phase: str | None = None
        self._active: bool = False

    async def start(self, entity_ids: list[str], intensity: str = "medium") -> None:
        """Save current light states and take control."""
        if not entity_ids:
            return

        self._entity_ids = list(entity_ids)
        self._intensity = intensity if intensity in INTENSITY_PRESETS else "medium"
        self._saved_states = {}

        # Save current states for restoration
        for entity_id in self._entity_ids:
            state = self._hass.states.get(entity_id)
            if state:
                self._saved_states[entity_id] = {
                    "state": state.state,
                    "brightness": state.attributes.get("brightness"),
                    "rgb_color": state.attributes.get("rgb_color"),
                    "color_temp_kelvin": state.attributes.get("color_temp_kelvin"),
                }

        self._active = True
        _LOGGER.info(
            "Party Lights started: %d lights, intensity=%s",
            len(self._entity_ids),
            self._intensity,
        )

    async def set_phase(self, phase: Any) -> None:
        """Apply phase-appropriate colors/brightness."""
        if not self._active or not self._entity_ids:
            return

        phase_name = phase.value if hasattr(phase, "value") else str(phase)
        self._current_phase = phase_name

        if phase_name == "END":
            # END phase triggers celebration via separate call
            return

        phase_data = PHASE_COLORS.get(phase_name)
        if not phase_data:
            return

        service_data = dict(phase_data)
        # Scale brightness by intensity
        preset = INTENSITY_PRESETS.get(self._intensity, INTENSITY_PRESETS["medium"])
        if "brightness" in service_data:
            service_data["brightness"] = int(
                service_data["brightness"] * preset["brightness_scale"]
            )

        await self._apply(self._entity_ids, service_data, transition=1.0)

    async def flash(self, color_name: str, duration: float = 0.5) -> None:
        """Quick flash effect — turn on with color, sleep, restore phase color."""
        if not self._active or not self._entity_ids:
            return

        rgb = FLASH_COLORS.get(color_name)
        if not rgb:
            return

        preset = INTENSITY_PRESETS.get(self._intensity, INTENSITY_PRESETS["medium"])
        flash_dur = preset["flash_duration"]

        # Flash on
        await self._apply(
            self._entity_ids,
            {"rgb_color": rgb, "brightness": 255},
            transition=0.1,
        )

        await asyncio.sleep(flash_dur)

        # Restore phase color
        if self._current_phase and self._current_phase in PHASE_COLORS:
            phase_data = dict(PHASE_COLORS[self._current_phase])
            if "brightness" in phase_data:
                phase_data["brightness"] = int(
                    phase_data["brightness"] * preset["brightness_scale"]
                )
            await self._apply(self._entity_ids, phase_data, transition=0.3)

    async def celebrate(self) -> None:
        """Rainbow cycle celebration for ~5 seconds."""
        if not self._active or not self._entity_ids:
            return

        _LOGGER.info("Party Lights celebration sequence started")
        for color in RAINBOW_COLORS:
            if not self._active:
                break
            await self._apply(
                self._entity_ids,
                {"rgb_color": color, "brightness": 255},
                transition=0.3,
            )
            await asyncio.sleep(0.7)

    async def stop(self) -> None:
        """Restore saved light states."""
        if not self._active:
            return

        self._active = False
        _LOGGER.info("Party Lights stopping, restoring %d lights", len(self._saved_states))

        for entity_id, saved in self._saved_states.items():
            try:
                if saved["state"] == "off":
                    await self._hass.services.async_call(
                        "light",
                        "turn_off",
                        {"entity_id": entity_id},
                        blocking=False,
                    )
                else:
                    restore_data: dict[str, Any] = {"entity_id": entity_id}
                    if saved.get("brightness") is not None:
                        restore_data["brightness"] = saved["brightness"]
                    if saved.get("rgb_color") is not None:
                        restore_data["rgb_color"] = list(saved["rgb_color"])
                    if saved.get("color_temp_kelvin") is not None:
                        restore_data["color_temp_kelvin"] = saved["color_temp_kelvin"]
                    await self._hass.services.async_call(
                        "light",
                        "turn_on",
                        restore_data,
                        blocking=False,
                    )
            except Exception:  # noqa: BLE001
                _LOGGER.warning("Failed to restore light: %s", entity_id)

        self._saved_states = {}
        self._entity_ids = []
        self._current_phase = None

    def _get_capability(self, entity_id: str) -> str:
        """Check entity attributes for supported_color_modes."""
        state = self._hass.states.get(entity_id)
        if not state:
            return "onoff"

        color_modes = state.attributes.get("supported_color_modes", [])
        if not color_modes:
            return "onoff"

        # Check from most capable to least
        if any(m in color_modes for m in ("rgb", "rgbw", "rgbww", "hs", "xy")):
            return "rgb"
        if any(m in color_modes for m in ("color_temp",)):
            return "ct"
        if any(m in color_modes for m in ("brightness",)):
            return "dim"
        return "onoff"

    async def _apply(
        self,
        entity_ids: list[str],
        service_data: dict[str, Any],
        transition: float = 1.0,
    ) -> None:
        """Batch call hass.services for lights, adapting per capability."""
        for entity_id in entity_ids:
            cap = self._get_capability(entity_id)
            call_data: dict[str, Any] = {
                "entity_id": entity_id,
                "transition": transition,
            }

            if cap == "rgb":
                # Full color support
                if "rgb_color" in service_data:
                    call_data["rgb_color"] = service_data["rgb_color"]
                if "color_temp_kelvin" in service_data:
                    call_data["color_temp_kelvin"] = service_data["color_temp_kelvin"]
                if "brightness" in service_data:
                    call_data["brightness"] = service_data["brightness"]
            elif cap == "ct":
                # Color temp only — map rgb to warm/cool
                if "color_temp_kelvin" in service_data:
                    call_data["color_temp_kelvin"] = service_data["color_temp_kelvin"]
                elif "rgb_color" in service_data:
                    # Map colors to warm (2700K) or cool (6500K)
                    r, g, b = service_data["rgb_color"]
                    call_data["color_temp_kelvin"] = 2700 if r > b else 6500
                if "brightness" in service_data:
                    call_data["brightness"] = service_data["brightness"]
            elif cap == "dim":
                # Brightness only
                if "brightness" in service_data:
                    call_data["brightness"] = service_data["brightness"]
            else:
                # On/off only — just turn on
                pass

            try:
                asyncio.create_task(
                    self._hass.services.async_call(
                        "light", "turn_on", call_data, blocking=False
                    )
                )
            except Exception:  # noqa: BLE001
                _LOGGER.warning("Failed to control light: %s", entity_id)
