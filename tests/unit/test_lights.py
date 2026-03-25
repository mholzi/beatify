"""Tests for PartyLightsService (#331)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from custom_components.beatify.services.lights import (
    FLASH_COLORS,
    INTENSITY_PRESETS,
    PHASE_COLORS,
    RAINBOW_COLORS,
    PartyLightsService,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_hass(
    lights: dict[str, dict] | None = None,
) -> MagicMock:
    """Create a mock Home Assistant instance with light states."""
    hass = MagicMock()
    hass.services.async_call = AsyncMock()

    if lights is None:
        lights = {
            "light.living_room": {
                "state": "on",
                "attributes": {
                    "supported_color_modes": ["rgb"],
                    "brightness": 200,
                    "rgb_color": [255, 255, 255],
                },
            },
        }

    def _get_state(entity_id):
        data = lights.get(entity_id)
        if data is None:
            return None
        state = MagicMock()
        state.state = data["state"]
        state.entity_id = entity_id
        state.attributes = data.get("attributes", {})
        return state

    hass.states.get = _get_state
    return hass


def _make_phase(value: str):
    """Create a mock GamePhase enum."""
    phase = MagicMock()
    phase.value = value
    return phase


# ---------------------------------------------------------------------------
# start / stop
# ---------------------------------------------------------------------------


class TestStartStop:
    """Test start and stop lifecycle."""

    @pytest.mark.asyncio
    async def test_start_saves_state(self):
        hass = _make_hass()
        svc = PartyLightsService(hass)
        await svc.start(["light.living_room"])

        assert svc._active is True
        assert "light.living_room" in svc._saved_states
        saved = svc._saved_states["light.living_room"]
        assert saved["state"] == "on"
        assert saved["brightness"] == 200
        assert saved["rgb_color"] == [255, 255, 255]

    @pytest.mark.asyncio
    async def test_start_empty_list_does_nothing(self):
        hass = _make_hass()
        svc = PartyLightsService(hass)
        await svc.start([])
        assert svc._active is False

    @pytest.mark.asyncio
    async def test_start_unknown_entity_skipped(self):
        hass = _make_hass()
        svc = PartyLightsService(hass)
        await svc.start(["light.nonexistent"])
        assert svc._active is True
        assert "light.nonexistent" not in svc._saved_states

    @pytest.mark.asyncio
    async def test_start_invalid_intensity_defaults_medium(self):
        hass = _make_hass()
        svc = PartyLightsService(hass)
        await svc.start(["light.living_room"], intensity="extreme")
        assert svc._intensity == "medium"

    @pytest.mark.asyncio
    async def test_stop_restores_on_state(self):
        hass = _make_hass()
        svc = PartyLightsService(hass)
        await svc.start(["light.living_room"])
        await svc.stop()

        assert svc._active is False
        hass.services.async_call.assert_called_with(
            "light",
            "turn_on",
            {
                "entity_id": "light.living_room",
                "brightness": 200,
                "rgb_color": [255, 255, 255],
            },
            blocking=False,
        )

    @pytest.mark.asyncio
    async def test_stop_restores_off_state(self):
        hass = _make_hass(
            {
                "light.hallway": {
                    "state": "off",
                    "attributes": {"supported_color_modes": ["brightness"]},
                }
            }
        )
        svc = PartyLightsService(hass)
        await svc.start(["light.hallway"])
        await svc.stop()

        hass.services.async_call.assert_called_with(
            "light",
            "turn_off",
            {"entity_id": "light.hallway"},
            blocking=False,
        )

    @pytest.mark.asyncio
    async def test_stop_when_not_active_is_noop(self):
        hass = _make_hass()
        svc = PartyLightsService(hass)
        await svc.stop()
        hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_clears_state(self):
        hass = _make_hass()
        svc = PartyLightsService(hass)
        await svc.start(["light.living_room"])
        await svc.stop()

        assert svc._entity_ids == []
        assert svc._saved_states == {}
        assert svc._current_phase is None

    @pytest.mark.asyncio
    async def test_stop_handles_service_call_error(self):
        """Stop should not raise even if restore fails."""
        hass = _make_hass()
        hass.services.async_call = AsyncMock(side_effect=Exception("HA error"))
        svc = PartyLightsService(hass)
        await svc.start(["light.living_room"])
        # Should not raise
        await svc.stop()
        assert svc._active is False


# ---------------------------------------------------------------------------
# set_phase
# ---------------------------------------------------------------------------


class TestSetPhase:
    """Test phase-based light changes."""

    @pytest.mark.asyncio
    async def test_set_phase_playing(self):
        hass = _make_hass()
        svc = PartyLightsService(hass)
        await svc.start(["light.living_room"])

        phase = _make_phase("PLAYING")
        await svc.set_phase(phase)

        assert svc._current_phase == "PLAYING"

    @pytest.mark.asyncio
    async def test_set_phase_end_does_not_apply_colors(self):
        """END phase should not apply colors directly (celebrate() handles it)."""
        hass = _make_hass()
        svc = PartyLightsService(hass)
        await svc.start(["light.living_room"])
        hass.services.async_call.reset_mock()

        phase = _make_phase("END")
        await svc.set_phase(phase)

        # No service calls — END is handled by celebrate()
        hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_phase_when_inactive_is_noop(self):
        hass = _make_hass()
        svc = PartyLightsService(hass)
        # Don't start
        phase = _make_phase("PLAYING")
        await svc.set_phase(phase)
        hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_phase_unknown_phase_is_noop(self):
        hass = _make_hass()
        svc = PartyLightsService(hass)
        await svc.start(["light.living_room"])
        hass.services.async_call.reset_mock()

        phase = _make_phase("UNKNOWN")
        await svc.set_phase(phase)
        hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_subtle_intensity_scales_brightness(self):
        hass = _make_hass()
        svc = PartyLightsService(hass)
        await svc.start(["light.living_room"], intensity="subtle")
        hass.services.async_call.reset_mock()

        phase = _make_phase("PLAYING")
        await svc.set_phase(phase)

        # PLAYING brightness is 153, subtle scales by 0.6 → 91
        call_args = hass.services.async_call.call_args
        assert call_args[0][2]["brightness"] == int(153 * 0.6)


# ---------------------------------------------------------------------------
# flash
# ---------------------------------------------------------------------------


class TestFlash:
    """Test flash effects."""

    @pytest.mark.asyncio
    async def test_flash_gold(self):
        hass = _make_hass()
        svc = PartyLightsService(hass)
        await svc.start(["light.living_room"])
        svc._current_phase = "REVEAL"
        hass.services.async_call.reset_mock()

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await svc.flash("gold")

        # Should have called at least twice (flash on + restore)
        assert hass.services.async_call.call_count >= 2

    @pytest.mark.asyncio
    async def test_flash_unknown_color_is_noop(self):
        hass = _make_hass()
        svc = PartyLightsService(hass)
        await svc.start(["light.living_room"])
        hass.services.async_call.reset_mock()

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await svc.flash("pink")

        hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_flash_when_inactive_is_noop(self):
        hass = _make_hass()
        svc = PartyLightsService(hass)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await svc.flash("gold")

        hass.services.async_call.assert_not_called()


# ---------------------------------------------------------------------------
# celebrate
# ---------------------------------------------------------------------------


class TestCelebrate:
    """Test celebration sequence."""

    @pytest.mark.asyncio
    async def test_celebrate_cycles_rainbow(self):
        hass = _make_hass()
        svc = PartyLightsService(hass)
        await svc.start(["light.living_room"])
        hass.services.async_call.reset_mock()

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await svc.celebrate()

        # Should call once per rainbow color
        assert hass.services.async_call.call_count == len(RAINBOW_COLORS)

    @pytest.mark.asyncio
    async def test_celebrate_stops_when_deactivated(self):
        hass = _make_hass()
        svc = PartyLightsService(hass)
        await svc.start(["light.living_room"])
        hass.services.async_call.reset_mock()

        async def deactivate_after_first(*args, **kwargs):
            svc._active = False

        with patch("asyncio.sleep", new_callable=AsyncMock, side_effect=deactivate_after_first):
            await svc.celebrate()

        # Should have been called only once before deactivation
        assert hass.services.async_call.call_count == 1

    @pytest.mark.asyncio
    async def test_celebrate_when_inactive_is_noop(self):
        hass = _make_hass()
        svc = PartyLightsService(hass)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await svc.celebrate()

        hass.services.async_call.assert_not_called()


# ---------------------------------------------------------------------------
# _get_capability
# ---------------------------------------------------------------------------


class TestGetCapability:
    """Test light capability detection."""

    def test_rgb_light(self):
        hass = _make_hass(
            {"light.rgb": {"state": "on", "attributes": {"supported_color_modes": ["rgb"]}}}
        )
        svc = PartyLightsService(hass)
        assert svc._get_capability("light.rgb") == "rgb"

    def test_rgbw_light(self):
        hass = _make_hass(
            {"light.rgbw": {"state": "on", "attributes": {"supported_color_modes": ["rgbw"]}}}
        )
        svc = PartyLightsService(hass)
        assert svc._get_capability("light.rgbw") == "rgb"

    def test_hs_light(self):
        hass = _make_hass(
            {"light.hs": {"state": "on", "attributes": {"supported_color_modes": ["hs"]}}}
        )
        svc = PartyLightsService(hass)
        assert svc._get_capability("light.hs") == "rgb"

    def test_xy_light(self):
        hass = _make_hass(
            {"light.xy": {"state": "on", "attributes": {"supported_color_modes": ["xy"]}}}
        )
        svc = PartyLightsService(hass)
        assert svc._get_capability("light.xy") == "rgb"

    def test_color_temp_light(self):
        hass = _make_hass(
            {"light.ct": {"state": "on", "attributes": {"supported_color_modes": ["color_temp"]}}}
        )
        svc = PartyLightsService(hass)
        assert svc._get_capability("light.ct") == "ct"

    def test_brightness_light(self):
        hass = _make_hass(
            {"light.dim": {"state": "on", "attributes": {"supported_color_modes": ["brightness"]}}}
        )
        svc = PartyLightsService(hass)
        assert svc._get_capability("light.dim") == "dim"

    def test_onoff_light(self):
        hass = _make_hass(
            {"light.switch": {"state": "on", "attributes": {"supported_color_modes": ["onoff"]}}}
        )
        svc = PartyLightsService(hass)
        assert svc._get_capability("light.switch") == "onoff"

    def test_no_color_modes(self):
        hass = _make_hass(
            {"light.basic": {"state": "on", "attributes": {}}}
        )
        svc = PartyLightsService(hass)
        assert svc._get_capability("light.basic") == "onoff"

    def test_unknown_entity(self):
        hass = _make_hass()
        svc = PartyLightsService(hass)
        assert svc._get_capability("light.nonexistent") == "onoff"

    def test_multi_mode_prefers_rgb(self):
        hass = _make_hass(
            {"light.multi": {"state": "on", "attributes": {"supported_color_modes": ["color_temp", "rgb"]}}}
        )
        svc = PartyLightsService(hass)
        assert svc._get_capability("light.multi") == "rgb"


# ---------------------------------------------------------------------------
# _apply capability adaptation
# ---------------------------------------------------------------------------


class TestApplyCapability:
    """Test that _apply adapts service data per light capability."""

    @pytest.mark.asyncio
    async def test_ct_light_maps_blue_to_cool(self):
        """CT light receiving rgb_color should map blue to 6500K."""
        hass = _make_hass(
            {"light.ct": {"state": "on", "attributes": {"supported_color_modes": ["color_temp"]}}}
        )
        svc = PartyLightsService(hass)
        await svc.start(["light.ct"])
        hass.services.async_call.reset_mock()

        await svc._apply(
            ["light.ct"],
            {"rgb_color": [0, 100, 255], "brightness": 153},
            transition=1.0,
        )

        call_args = hass.services.async_call.call_args[0][2]
        assert call_args["color_temp_kelvin"] == 6500
        assert call_args["brightness"] == 153
        assert "rgb_color" not in call_args

    @pytest.mark.asyncio
    async def test_ct_light_maps_red_to_warm(self):
        """CT light receiving rgb_color should map red to 2700K."""
        hass = _make_hass(
            {"light.ct": {"state": "on", "attributes": {"supported_color_modes": ["color_temp"]}}}
        )
        svc = PartyLightsService(hass)
        await svc.start(["light.ct"])
        hass.services.async_call.reset_mock()

        await svc._apply(
            ["light.ct"],
            {"rgb_color": [255, 0, 0], "brightness": 153},
            transition=1.0,
        )

        call_args = hass.services.async_call.call_args[0][2]
        assert call_args["color_temp_kelvin"] == 2700

    @pytest.mark.asyncio
    async def test_dim_light_only_gets_brightness(self):
        hass = _make_hass(
            {"light.dim": {"state": "on", "attributes": {"supported_color_modes": ["brightness"]}}}
        )
        svc = PartyLightsService(hass)
        await svc.start(["light.dim"])
        hass.services.async_call.reset_mock()

        await svc._apply(
            ["light.dim"],
            {"rgb_color": [0, 100, 255], "brightness": 153},
            transition=1.0,
        )

        call_args = hass.services.async_call.call_args[0][2]
        assert call_args["brightness"] == 153
        assert "rgb_color" not in call_args
        assert "color_temp_kelvin" not in call_args

    @pytest.mark.asyncio
    async def test_onoff_light_gets_no_color_or_brightness(self):
        hass = _make_hass(
            {"light.sw": {"state": "on", "attributes": {"supported_color_modes": ["onoff"]}}}
        )
        svc = PartyLightsService(hass)
        await svc.start(["light.sw"])
        hass.services.async_call.reset_mock()

        await svc._apply(
            ["light.sw"],
            {"rgb_color": [0, 100, 255], "brightness": 153},
            transition=1.0,
        )

        call_args = hass.services.async_call.call_args[0][2]
        assert "rgb_color" not in call_args
        assert "brightness" not in call_args
        assert call_args["entity_id"] == "light.sw"

    @pytest.mark.asyncio
    async def test_apply_handles_service_error(self):
        """_apply should not raise if a light fails."""
        hass = _make_hass()
        hass.services.async_call = AsyncMock(side_effect=Exception("HA error"))
        svc = PartyLightsService(hass)
        await svc.start(["light.living_room"])

        # Should not raise
        await svc._apply(
            ["light.living_room"],
            {"rgb_color": [255, 0, 0], "brightness": 255},
        )


# ---------------------------------------------------------------------------
# Multiple lights
# ---------------------------------------------------------------------------


class TestMultipleLights:
    """Test behavior with multiple lights of different capabilities."""

    @pytest.mark.asyncio
    async def test_mixed_capabilities(self):
        """Apply should adapt per light, not globally."""
        hass = _make_hass(
            {
                "light.rgb": {"state": "on", "attributes": {"supported_color_modes": ["rgb"], "brightness": 100}},
                "light.dim": {"state": "on", "attributes": {"supported_color_modes": ["brightness"], "brightness": 50}},
                "light.sw": {"state": "off", "attributes": {"supported_color_modes": ["onoff"]}},
            }
        )
        svc = PartyLightsService(hass)
        await svc.start(["light.rgb", "light.dim", "light.sw"])

        assert len(svc._saved_states) == 3
        assert svc._saved_states["light.rgb"]["brightness"] == 100
        assert svc._saved_states["light.dim"]["brightness"] == 50
        assert svc._saved_states["light.sw"]["state"] == "off"
