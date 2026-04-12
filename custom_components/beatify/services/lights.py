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
    "subtle": {"brightness_scale": 1.0, "flash_duration": 0.8},
    "medium": {"brightness_scale": 1.0, "flash_duration": 0.5},
    "party": {"brightness_scale": 1.0, "flash_duration": 0.3},
}

# WLED preset defaults (user-configurable via admin UI)
WLED_PRESET_DEFAULTS: dict[str, int] = {
    "LOBBY": 1,
    "PLAYING": 2,
    "REVEAL": 3,
    "STREAK": 4,
    "COUNTDOWN": 5,
    "END": 6,
}

# Beat loop colors for PLAYING phase
BEAT_COLORS: list[list[int]] = [
    [0, 100, 255],
    [0, 180, 255],
    [0, 60, 200],
]

# Subtle mode: brightness offsets added to the saved (pre-game) brightness.
# Values are fractions of 255 (0.2 = +51 out of 255).
SUBTLE_BRIGHTNESS_OFFSETS: dict[str, float] = {
    "LOBBY": 0.0,
    "PLAYING": 0.2,
    "REVEAL": 0.4,
    "END": 0.4,
}


class PartyLightsService:
    """Control Home Assistant lights during Beatify games."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize with Home Assistant instance."""
        self._hass = hass
        self._entity_ids: list[str] = []
        self._intensity: str = "medium"
        self._saved_states: dict[str, dict[str, Any]] = {}
        self._base_brightness: int = 128
        self._current_phase: str | None = None
        self._active: bool = False
        self._beat_task: asyncio.Task | None = None
        self._light_mode: str = "dynamic"  # "static", "dynamic", "wled"
        self._wled_presets: dict[str, int] = dict(WLED_PRESET_DEFAULTS)
        self._wled_entities: set[str] = set()

    async def start(
        self,
        entity_ids: list[str],
        intensity: str = "medium",
        light_mode: str = "dynamic",
        wled_presets: dict[str, int] | None = None,
    ) -> None:
        """Save current light states and take control."""
        if not entity_ids:
            return

        self._entity_ids = list(entity_ids)
        self._intensity = intensity if intensity in INTENSITY_PRESETS else "medium"
        self._light_mode = light_mode if light_mode in ("static", "dynamic", "wled") else "dynamic"
        if wled_presets:
            self._wled_presets.update(wled_presets)
        self._saved_states = {}

        # Detect WLED entities by checking entity_id prefix
        self._wled_entities = set()
        for entity_id in self._entity_ids:
            state = self._hass.states.get(entity_id)
            if state and state.attributes.get("effect_list") is not None:
                # WLED entities expose effect_list; also check for wled in entity_id
                if "wled" in entity_id.lower():
                    self._wled_entities.add(entity_id)

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

        # Compute base brightness for subtle mode from saved states
        brightnesses = [
            s["brightness"]
            for s in self._saved_states.values()
            if s.get("state") != "off" and s.get("brightness") is not None
        ]
        self._base_brightness = int(sum(brightnesses) / len(brightnesses)) if brightnesses else 128

        self._active = True
        _LOGGER.info(
            "Party Lights started: %d lights, intensity=%s, mode=%s, wled=%d",
            len(self._entity_ids),
            self._intensity,
            self._light_mode,
            len(self._wled_entities),
        )

    async def set_phase(self, phase: Any) -> None:
        """Apply phase-appropriate colors/brightness."""
        if not self._active or not self._entity_ids:
            return

        phase_name = phase.value if hasattr(phase, "value") else str(phase)
        self._current_phase = phase_name

        # Stop beat loop when leaving PLAYING phase
        if phase_name != "PLAYING":
            await self.stop_beat_loop()

        if phase_name == "END":
            # END phase triggers celebration via separate call
            return

        # WLED mode: activate preset instead of setting colors
        if self._light_mode == "wled" and self._wled_entities:
            preset_id = self._wled_presets.get(phase_name)
            if preset_id is not None:
                for entity_id in self._wled_entities:
                    await self._apply_wled(entity_id, preset_id)
            # Apply normal colors to non-WLED entities
            non_wled = [e for e in self._entity_ids if e not in self._wled_entities]
            if non_wled:
                phase_data = PHASE_COLORS.get(phase_name)
                if phase_data:
                    await self._apply(non_wled, dict(phase_data), transition=1.0)
        else:
            phase_data = PHASE_COLORS.get(phase_name)
            if not phase_data:
                return

            service_data = dict(phase_data)
            if self._intensity == "subtle":
                offset = int(SUBTLE_BRIGHTNESS_OFFSETS.get(phase_name, 0.0) * 255)
                service_data["brightness"] = min(self._base_brightness + offset, 255)
            else:
                preset = INTENSITY_PRESETS.get(self._intensity, INTENSITY_PRESETS["medium"])
                if "brightness" in service_data:
                    service_data["brightness"] = int(
                        service_data["brightness"] * preset["brightness_scale"]
                    )

            await self._apply(self._entity_ids, service_data, transition=1.0)

        # Start beat loop when entering PLAYING in dynamic mode
        if phase_name == "PLAYING" and self._light_mode == "dynamic":
            await self.start_beat_loop()

    async def flash(self, color_name: str) -> None:
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

    async def start_beat_loop(self, bpm: int = 120) -> None:
        """Start a background beat-flash loop during PLAYING phase (#517)."""
        await self.stop_beat_loop()
        self._beat_task = asyncio.create_task(self._beat_loop(bpm))

    async def stop_beat_loop(self) -> None:
        """Cancel the beat-flash loop."""
        if self._beat_task is not None:
            self._beat_task.cancel()
            self._beat_task = None

    async def _beat_loop(self, bpm: int) -> None:
        """Pulse between blue shades at the given BPM."""
        interval = 60.0 / bpm
        i = 0
        try:
            while self._active:
                # Only pulse non-WLED entities
                entities = [e for e in self._entity_ids if e not in self._wled_entities]
                if entities:
                    await self._apply(
                        entities,
                        {"rgb_color": BEAT_COLORS[i % len(BEAT_COLORS)], "brightness": 200},
                        transition=0.1,
                    )
                i += 1
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            pass

    async def strobe(self, count: int = 5, interval: float = 0.4) -> None:
        """Rapid on/off strobe for countdown tension (#517)."""
        for _ in range(count):
            if not self._active:
                break
            await self._apply(
                self._entity_ids,
                {"rgb_color": [255, 0, 0], "brightness": 255},
                transition=0.05,
            )
            await asyncio.sleep(interval / 2)
            await self._apply(
                self._entity_ids,
                {"brightness": 10},
                transition=0.05,
            )
            await asyncio.sleep(interval / 2)
        # Restore phase color
        if self._current_phase and self._current_phase in PHASE_COLORS:
            phase_data = dict(PHASE_COLORS[self._current_phase])
            await self._apply(self._entity_ids, phase_data, transition=0.3)

    async def celebrate(self) -> None:
        """Rainbow cycle celebration for ~5 seconds."""
        if not self._active or not self._entity_ids:
            return

        _LOGGER.info("Party Lights celebration sequence started")
        if self._intensity == "subtle":
            offset = int(SUBTLE_BRIGHTNESS_OFFSETS["END"] * 255)
            brightness = min(self._base_brightness + offset, 255)
        else:
            brightness = 255
        for color in RAINBOW_COLORS:
            if not self._active:
                break
            await self._apply(
                self._entity_ids,
                {"rgb_color": color, "brightness": brightness},
                transition=0.3,
            )
            await asyncio.sleep(0.7)

    async def stop(self) -> None:
        """Restore saved light states."""
        if not self._active:
            return

        await self.stop_beat_loop()
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
                await self._hass.services.async_call(
                    "light", "turn_on", call_data, blocking=False
                )
            except Exception:  # noqa: BLE001
                _LOGGER.warning("Failed to control light: %s", entity_id)

    async def _apply_wled(self, entity_id: str, preset_id: int) -> None:
        """Activate a WLED preset by ID (#517)."""
        try:
            await self._hass.services.async_call(
                "select",
                "select_option",
                {"entity_id": entity_id.replace("light.", "select.") + "_preset", "option": str(preset_id)},
                blocking=False,
            )
        except Exception:  # noqa: BLE001
            # Fallback: try the number entity approach
            try:
                await self._hass.services.async_call(
                    "number",
                    "set_value",
                    {"entity_id": entity_id.replace("light.", "number.") + "_preset", "value": preset_id},
                    blocking=False,
                )
            except Exception:  # noqa: BLE001
                _LOGGER.warning("Failed to set WLED preset %d on %s", preset_id, entity_id)
