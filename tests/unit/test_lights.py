"""Tests for PartyLightsService (#331)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.exceptions import HomeAssistantError

from custom_components.beatify.services.lights import (
    BEAT_COMMANDS_PER_SECOND,
    BEAT_MAX_LIGHTS,
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
    async def test_snapshot_saved_states_returns_copy(self):
        """#1402 B2: snapshot returns an independent deep-ish copy."""
        hass = _make_hass()
        svc = PartyLightsService(hass)
        await svc.start(["light.living_room"])

        snap = svc.snapshot_saved_states()
        assert snap["light.living_room"]["brightness"] == 200
        # Mutating the snapshot must not affect the live state.
        snap["light.living_room"]["brightness"] = 1
        assert svc._saved_states["light.living_room"]["brightness"] == 200

    @pytest.mark.asyncio
    async def test_start_inherited_states_override_fresh_capture(self):
        """#1402 B2: a reconfigure must preserve the GENUINE pre-party states.

        Without the inherited_states hand-off, the second service's start()
        re-captures whatever the lights currently show — which is the party
        color the first service applied — so its eventual stop() would "restore"
        lights to the party color, permanently losing the user's real original
        look. Passing the prior snapshot makes the new service restore to truth.
        """
        # Live HA state now reports the PARTY color (brightness 255, red) —
        # this is what a fresh capture would wrongly snapshot.
        hass = _make_hass(
            {
                "light.living_room": {
                    "state": "on",
                    "attributes": {
                        "supported_color_modes": ["rgb"],
                        "brightness": 255,
                        "rgb_color": [255, 0, 0],
                    },
                },
            }
        )
        # The genuine pre-party state the first service had captured.
        original = {
            "light.living_room": {
                "state": "on",
                "brightness": 80,
                "rgb_color": [255, 255, 255],
                "color_temp_kelvin": None,
            }
        }
        svc = PartyLightsService(hass)
        await svc.start(["light.living_room"], inherited_states=original)

        # The inherited (real) state wins over the fresh party-color capture.
        assert svc._saved_states["light.living_room"]["brightness"] == 80
        assert svc._saved_states["light.living_room"]["rgb_color"] == [255, 255, 255]

        # And stop() restores to the genuine original, not the party color.
        await svc.stop()
        hass.services.async_call.assert_any_call(
            "light",
            "turn_on",
            {
                "entity_id": "light.living_room",
                "brightness": 80,
                "rgb_color": [255, 255, 255],
            },
            blocking=False,
        )

    @pytest.mark.asyncio
    async def test_start_inherited_states_only_overlap(self):
        """#1402 B2: entities not in inherited_states are captured fresh."""
        hass = _make_hass(
            {
                "light.a": {
                    "state": "on",
                    "attributes": {"supported_color_modes": ["rgb"], "brightness": 200},
                },
                "light.b": {
                    "state": "on",
                    "attributes": {"supported_color_modes": ["rgb"], "brightness": 90},
                },
            }
        )
        inherited = {
            "light.a": {
                "state": "on",
                "brightness": 30,
                "rgb_color": None,
                "color_temp_kelvin": None,
            }
        }
        svc = PartyLightsService(hass)
        await svc.start(["light.a", "light.b"], inherited_states=inherited)

        # a inherits the real pre-party brightness; b is captured fresh.
        assert svc._saved_states["light.a"]["brightness"] == 30
        assert svc._saved_states["light.b"]["brightness"] == 90

    @pytest.mark.asyncio
    async def test_double_start_overwrites_saved_states(self):
        """Calling start() twice should save fresh states, not accumulate."""
        hass = _make_hass(
            {
                "light.a": {
                    "state": "on",
                    "attributes": {"supported_color_modes": ["rgb"], "brightness": 100},
                },
                "light.b": {
                    "state": "on",
                    "attributes": {"supported_color_modes": ["rgb"], "brightness": 50},
                },
            }
        )
        svc = PartyLightsService(hass)
        await svc.start(["light.a"])
        assert "light.a" in svc._saved_states

        # Second start with different lights — old state for light.a is lost
        await svc.start(["light.b"])
        assert "light.a" not in svc._saved_states
        assert "light.b" in svc._saved_states
        assert svc._entity_ids == ["light.b"]

    @pytest.mark.asyncio
    async def test_stop_restores_on_state(self):
        hass = _make_hass()
        svc = PartyLightsService(hass)
        await svc.start(["light.living_room"])
        await svc.stop()

        assert svc._active is False
        hass.services.async_call.assert_any_call(
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

        hass.services.async_call.assert_any_call(
            "light",
            "turn_off",
            {"entity_id": "light.hallway"},
            blocking=False,
        )

    @pytest.mark.asyncio
    async def test_stop_restores_multiple_lights(self):
        """Verify all lights are restored, not just the last one."""
        hass = _make_hass(
            {
                "light.a": {
                    "state": "on",
                    "attributes": {
                        "supported_color_modes": ["rgb"],
                        "brightness": 100,
                        "rgb_color": [255, 0, 0],
                    },
                },
                "light.b": {
                    "state": "off",
                    "attributes": {"supported_color_modes": ["brightness"]},
                },
            }
        )
        svc = PartyLightsService(hass)
        await svc.start(["light.a", "light.b"])
        await svc.stop()

        hass.services.async_call.assert_any_call(
            "light",
            "turn_on",
            {"entity_id": "light.a", "brightness": 100, "rgb_color": [255, 0, 0]},
            blocking=False,
        )
        hass.services.async_call.assert_any_call(
            "light",
            "turn_off",
            {"entity_id": "light.b"},
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
        hass.services.async_call = AsyncMock(side_effect=HomeAssistantError("HA error"))
        svc = PartyLightsService(hass)
        await svc.start(["light.living_room"])
        # Should not raise
        await svc.stop()
        assert svc._active is False

    @pytest.mark.asyncio
    async def test_start_saves_color_mode(self):
        """#1402: start() must remember the active color_mode for restore."""
        hass = _make_hass(
            {
                "light.ct": {
                    "state": "on",
                    "attributes": {
                        "supported_color_modes": ["color_temp", "rgb"],
                        "color_mode": "color_temp",
                        "brightness": 180,
                        "rgb_color": [255, 255, 255],
                        "color_temp_kelvin": 2700,
                    },
                }
            }
        )
        svc = PartyLightsService(hass)
        await svc.start(["light.ct"])
        assert svc._saved_states["light.ct"]["color_mode"] == "color_temp"

    @pytest.mark.asyncio
    async def test_stop_color_temp_mode_restores_only_kelvin(self):
        """#1402: a color_temp light reports BOTH rgb_color and color_temp_kelvin;
        restore must replay color_temp_kelvin only, never both in one turn_on."""
        hass = _make_hass(
            {
                "light.ct": {
                    "state": "on",
                    "attributes": {
                        "supported_color_modes": ["color_temp", "rgb"],
                        "color_mode": "color_temp",
                        "brightness": 180,
                        "rgb_color": [255, 255, 255],
                        "color_temp_kelvin": 2700,
                    },
                }
            }
        )
        svc = PartyLightsService(hass)
        await svc.start(["light.ct"])
        await svc.stop()

        hass.services.async_call.assert_any_call(
            "light",
            "turn_on",
            {
                "entity_id": "light.ct",
                "brightness": 180,
                "color_temp_kelvin": 2700,
            },
            blocking=False,
        )

    @pytest.mark.asyncio
    async def test_stop_rgb_mode_restores_only_rgb(self):
        """#1402: an rgb-mode light with a lingering color_temp_kelvin attribute
        must restore rgb_color only, never both."""
        hass = _make_hass(
            {
                "light.rgb": {
                    "state": "on",
                    "attributes": {
                        "supported_color_modes": ["color_temp", "rgb"],
                        "color_mode": "rgb",
                        "brightness": 120,
                        "rgb_color": [10, 20, 30],
                        "color_temp_kelvin": 4000,
                    },
                }
            }
        )
        svc = PartyLightsService(hass)
        await svc.start(["light.rgb"])
        await svc.stop()

        hass.services.async_call.assert_any_call(
            "light",
            "turn_on",
            {
                "entity_id": "light.rgb",
                "brightness": 120,
                "rgb_color": [10, 20, 30],
            },
            blocking=False,
        )

    @pytest.mark.asyncio
    async def test_stop_unknown_color_mode_prefers_rgb_not_both(self):
        """#1402: when color_mode is absent (older/partial state) but both color
        attributes were saved, restore picks rgb_color and never sends both."""
        hass = _make_hass(
            {
                "light.legacy": {
                    "state": "on",
                    "attributes": {
                        "supported_color_modes": ["rgb"],
                        "brightness": 90,
                        "rgb_color": [1, 2, 3],
                        "color_temp_kelvin": 3500,
                    },
                }
            }
        )
        svc = PartyLightsService(hass)
        await svc.start(["light.legacy"])
        await svc.stop()

        hass.services.async_call.assert_any_call(
            "light",
            "turn_on",
            {
                "entity_id": "light.legacy",
                "brightness": 90,
                "rgb_color": [1, 2, 3],
            },
            blocking=False,
        )


# ---------------------------------------------------------------------------
# set_phase
# ---------------------------------------------------------------------------


class TestSetPhase:
    """Test phase-based light changes."""

    @pytest.mark.asyncio
    async def test_set_phase_playing_applies_blue(self):
        hass = _make_hass()
        svc = PartyLightsService(hass)
        await svc.start(["light.living_room"])
        hass.services.async_call.reset_mock()

        phase = _make_phase("PLAYING")
        await svc.set_phase(phase)

        assert svc._current_phase == "PLAYING"
        call_args = hass.services.async_call.call_args[0][2]
        assert call_args["rgb_color"] == [0, 100, 255]
        assert call_args["brightness"] == 153

    @pytest.mark.asyncio
    async def test_set_phase_lobby_applies_purple(self):
        hass = _make_hass()
        svc = PartyLightsService(hass)
        await svc.start(["light.living_room"])
        hass.services.async_call.reset_mock()

        phase = _make_phase("LOBBY")
        await svc.set_phase(phase)

        assert svc._current_phase == "LOBBY"
        call_args = hass.services.async_call.call_args[0][2]
        assert call_args["rgb_color"] == [147, 112, 219]
        assert call_args["brightness"] == 102

    @pytest.mark.asyncio
    async def test_set_phase_reveal_applies_warm_ct(self):
        """REVEAL uses color_temp_kelvin, not rgb_color."""
        hass = _make_hass()
        svc = PartyLightsService(hass)
        await svc.start(["light.living_room"])
        hass.services.async_call.reset_mock()

        phase = _make_phase("REVEAL")
        await svc.set_phase(phase)

        call_args = hass.services.async_call.call_args[0][2]
        assert call_args["color_temp_kelvin"] == 3000
        assert call_args["brightness"] == 204
        assert "rgb_color" not in call_args

    @pytest.mark.asyncio
    async def test_set_phase_end_does_not_apply_colors(self):
        """END phase returns early — celebrate() handles the light effects."""
        hass = _make_hass()
        svc = PartyLightsService(hass)
        await svc.start(["light.living_room"])
        hass.services.async_call.reset_mock()

        phase = _make_phase("END")
        await svc.set_phase(phase)

        assert svc._current_phase == "END"
        hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_phase_when_inactive_is_noop(self):
        hass = _make_hass()
        svc = PartyLightsService(hass)
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

        # Subtle PLAYING: base brightness (200) + 20% of 255 (51) = 251
        call_args = hass.services.async_call.call_args[0][2]
        assert call_args["brightness"] == min(200 + int(0.2 * 255), 255)


# ---------------------------------------------------------------------------
# flash
# ---------------------------------------------------------------------------


class TestFlash:
    """Test flash effects."""

    @pytest.mark.asyncio
    async def test_flash_gold_sends_color_and_restores(self):
        hass = _make_hass()
        svc = PartyLightsService(hass)
        await svc.start(["light.living_room"])
        svc._current_phase = "PLAYING"
        hass.services.async_call.reset_mock()

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await svc.flash("gold")

        # First call: flash on with gold
        flash_call = hass.services.async_call.call_args_list[0]
        assert flash_call[0][2]["rgb_color"] == [255, 215, 0]
        assert flash_call[0][2]["brightness"] == 255

        # Second call: restore PLAYING phase color
        restore_call = hass.services.async_call.call_args_list[1]
        assert restore_call[0][2]["rgb_color"] == [0, 100, 255]
        assert restore_call[0][2]["brightness"] == 153

    @pytest.mark.asyncio
    async def test_flash_without_phase_does_not_restore(self):
        """Flash with no current phase should flash but skip restore."""
        hass = _make_hass()
        svc = PartyLightsService(hass)
        await svc.start(["light.living_room"])
        svc._current_phase = None
        hass.services.async_call.reset_mock()

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await svc.flash("gold")

        # Only the flash call, no restore
        assert hass.services.async_call.call_count == 1
        call_args = hass.services.async_call.call_args[0][2]
        assert call_args["rgb_color"] == [255, 215, 0]

    @pytest.mark.asyncio
    async def test_flash_with_end_phase_restores_brightness_only(self):
        """END phase has brightness but no rgb_color — restore should reflect that."""
        hass = _make_hass()
        svc = PartyLightsService(hass)
        await svc.start(["light.living_room"])
        svc._current_phase = "END"
        hass.services.async_call.reset_mock()

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await svc.flash("red")

        # Restore should send END phase data (brightness 255 only)
        restore_call = hass.services.async_call.call_args_list[1]
        assert restore_call[0][2]["brightness"] == 255
        assert "rgb_color" not in restore_call[0][2]

    @pytest.mark.asyncio
    async def test_flash_uses_preset_duration(self):
        """Flash duration comes from intensity preset, not the method default."""
        hass = _make_hass()
        svc = PartyLightsService(hass)
        await svc.start(["light.living_room"], intensity="party")
        svc._current_phase = "PLAYING"

        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await svc.flash("gold")

        # Party preset flash_duration is 0.3
        mock_sleep.assert_called_once_with(0.3)

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
# subtle-mode restore (flash) — #1389
# ---------------------------------------------------------------------------


class TestSubtleRestore:
    """flash() must restore the subtle (pre-game) brightness, not full."""

    @staticmethod
    def _subtle_hass():
        # Pre-game brightness 100 → base_brightness == 100 in subtle mode.
        return _make_hass(
            {
                "light.living_room": {
                    "state": "on",
                    "attributes": {
                        "supported_color_modes": ["rgb"],
                        "brightness": 100,
                        "rgb_color": [255, 255, 255],
                    },
                },
            }
        )

    @pytest.mark.asyncio
    async def test_flash_restores_subtle_brightness_not_full(self):
        hass = self._subtle_hass()
        svc = PartyLightsService(hass)
        await svc.start(["light.living_room"], intensity="subtle")
        svc._current_phase = "PLAYING"
        hass.services.async_call.reset_mock()

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await svc.flash("gold")

        # PLAYING raw brightness is 153 (full). Subtle restore must be
        # base (100) + 20% of 255 (51) = 151, NOT 153 and NOT 255.
        expected = min(100 + int(0.2 * 255), 255)
        restore_call = hass.services.async_call.call_args_list[1]
        assert restore_call[0][2]["brightness"] == expected
        assert restore_call[0][2]["brightness"] != 153
        assert restore_call[0][2]["rgb_color"] == [0, 100, 255]

    @pytest.mark.asyncio
    async def test_flash_restores_subtle_brightness_in_reveal_phase(self):
        """REVEAL has a 0.4 offset and no rgb_color — restore must honour both."""
        hass = self._subtle_hass()
        svc = PartyLightsService(hass)
        await svc.start(["light.living_room"], intensity="subtle")
        svc._current_phase = "REVEAL"
        hass.services.async_call.reset_mock()

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await svc.flash("red")

        # REVEAL raw brightness is 204 (full). Subtle restore must be
        # base (100) + 40% of 255 (102) = 202, NOT 204.
        expected = min(100 + int(0.4 * 255), 255)
        restore_call = hass.services.async_call.call_args_list[-1]
        assert restore_call[0][2]["brightness"] == expected
        assert restore_call[0][2]["brightness"] != 204
        assert restore_call[0][2]["color_temp_kelvin"] == 3000


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

        assert hass.services.async_call.call_count == len(RAINBOW_COLORS)
        # Verify first and last colors
        first_call = hass.services.async_call.call_args_list[0]
        assert first_call[0][2]["rgb_color"] == [255, 0, 0]
        last_call = hass.services.async_call.call_args_list[-1]
        assert last_call[0][2]["rgb_color"] == [148, 0, 211]

    @pytest.mark.asyncio
    async def test_celebrate_stops_when_deactivated(self):
        hass = _make_hass()
        svc = PartyLightsService(hass)
        await svc.start(["light.living_room"])
        hass.services.async_call.reset_mock()

        async def deactivate_after_first(*args, **kwargs):
            svc._active = False

        with patch(
            "asyncio.sleep",
            new_callable=AsyncMock,
            side_effect=deactivate_after_first,
        ):
            await svc.celebrate()

        assert hass.services.async_call.call_count == 1

    @pytest.mark.asyncio
    async def test_celebrate_when_inactive_is_noop(self):
        hass = _make_hass()
        svc = PartyLightsService(hass)

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await svc.celebrate()

        hass.services.async_call.assert_not_called()


# ---------------------------------------------------------------------------
# WLED END preset reachability (#1390)
# ---------------------------------------------------------------------------


class TestWledEndPreset:
    """The configured END WLED preset must fire despite the END early-return."""

    @pytest.mark.asyncio
    async def test_set_phase_end_applies_wled_preset(self):
        """END in wled mode applies the configured END preset, not raw rgb."""
        hass = _make_hass()
        svc = PartyLightsService(hass)
        await svc.start(["light.wled_strip"])
        # Configure wled mode + a WLED entity (detection happens in start()
        # via the entity registry; emulate the configured result here).
        svc._light_mode = "wled"
        svc._wled_entities = {"light.wled_strip"}
        hass.services.async_call.reset_mock()

        with patch.object(svc, "_apply_wled", new_callable=AsyncMock) as apply_wled:
            phase = _make_phase("END")
            await svc.set_phase(phase)

        assert svc._current_phase == "END"
        # END preset default is 6.
        apply_wled.assert_awaited_once_with("light.wled_strip", 6)
        # No raw rgb commands to lights for the WLED entity.
        hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_phase_end_honors_custom_end_preset(self):
        """A user-configured END preset overrides the default."""
        hass = _make_hass()
        svc = PartyLightsService(hass)
        await svc.start(
            ["light.wled_strip"],
            light_mode="wled",
            wled_presets={"END": 12},
        )
        svc._light_mode = "wled"
        svc._wled_entities = {"light.wled_strip"}
        hass.services.async_call.reset_mock()

        with patch.object(svc, "_apply_wled", new_callable=AsyncMock) as apply_wled:
            await svc.set_phase(_make_phase("END"))

        apply_wled.assert_awaited_once_with("light.wled_strip", 12)

    @pytest.mark.asyncio
    async def test_set_phase_end_non_wled_mode_skips_wled(self):
        """In non-wled mode END stays an early-return no-op (celebrate handles it)."""
        hass = _make_hass()
        svc = PartyLightsService(hass)
        await svc.start(["light.living_room"])
        hass.services.async_call.reset_mock()

        with patch.object(svc, "_apply_wled", new_callable=AsyncMock) as apply_wled:
            await svc.set_phase(_make_phase("END"))

        apply_wled.assert_not_awaited()
        hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_celebrate_skips_wled_entities_in_wled_mode(self):
        """Rainbow celebration must not overwrite the WLED END preset."""
        hass = _make_hass()
        svc = PartyLightsService(hass)
        await svc.start(["light.wled_strip", "light.living_room"])
        svc._light_mode = "wled"
        svc._wled_entities = {"light.wled_strip"}
        hass.services.async_call.reset_mock()

        with patch("asyncio.sleep", new_callable=AsyncMock):
            await svc.celebrate()

        # Every rainbow command targets only the non-WLED entity. Lamps are
        # grouped into one call carrying an entity_id list (#2708).
        targeted = {
            entity_id
            for call in hass.services.async_call.call_args_list
            for entity_id in call[0][2]["entity_id"]
        }
        assert targeted == {"light.living_room"}

    @pytest.mark.asyncio
    async def test_celebrate_wled_only_setup_is_noop(self):
        """If every entity is WLED, celebrate sends no raw rgb at all."""
        hass = _make_hass()
        svc = PartyLightsService(hass)
        await svc.start(["light.wled_strip"])
        svc._light_mode = "wled"
        svc._wled_entities = {"light.wled_strip"}
        hass.services.async_call.reset_mock()

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
            {
                "light.rgb": {
                    "state": "on",
                    "attributes": {"supported_color_modes": ["rgb"]},
                }
            }
        )
        svc = PartyLightsService(hass)
        assert svc._get_capability("light.rgb") == "rgb"

    def test_rgbw_light(self):
        hass = _make_hass(
            {
                "light.rgbw": {
                    "state": "on",
                    "attributes": {"supported_color_modes": ["rgbw"]},
                }
            }
        )
        svc = PartyLightsService(hass)
        assert svc._get_capability("light.rgbw") == "rgb"

    def test_hs_light(self):
        hass = _make_hass(
            {
                "light.hs": {
                    "state": "on",
                    "attributes": {"supported_color_modes": ["hs"]},
                }
            }
        )
        svc = PartyLightsService(hass)
        assert svc._get_capability("light.hs") == "rgb"

    def test_xy_light(self):
        hass = _make_hass(
            {
                "light.xy": {
                    "state": "on",
                    "attributes": {"supported_color_modes": ["xy"]},
                }
            }
        )
        svc = PartyLightsService(hass)
        assert svc._get_capability("light.xy") == "rgb"

    def test_color_temp_light(self):
        hass = _make_hass(
            {
                "light.ct": {
                    "state": "on",
                    "attributes": {"supported_color_modes": ["color_temp"]},
                }
            }
        )
        svc = PartyLightsService(hass)
        assert svc._get_capability("light.ct") == "ct"

    def test_brightness_light(self):
        hass = _make_hass(
            {
                "light.dim": {
                    "state": "on",
                    "attributes": {"supported_color_modes": ["brightness"]},
                }
            }
        )
        svc = PartyLightsService(hass)
        assert svc._get_capability("light.dim") == "dim"

    def test_onoff_light(self):
        hass = _make_hass(
            {
                "light.switch": {
                    "state": "on",
                    "attributes": {"supported_color_modes": ["onoff"]},
                }
            }
        )
        svc = PartyLightsService(hass)
        assert svc._get_capability("light.switch") == "onoff"

    def test_no_color_modes(self):
        hass = _make_hass({"light.basic": {"state": "on", "attributes": {}}})
        svc = PartyLightsService(hass)
        assert svc._get_capability("light.basic") == "onoff"

    def test_unknown_entity(self):
        hass = _make_hass()
        svc = PartyLightsService(hass)
        assert svc._get_capability("light.nonexistent") == "onoff"

    def test_multi_mode_prefers_rgb(self):
        hass = _make_hass(
            {
                "light.multi": {
                    "state": "on",
                    "attributes": {"supported_color_modes": ["color_temp", "rgb"]},
                }
            }
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
            {
                "light.ct": {
                    "state": "on",
                    "attributes": {"supported_color_modes": ["color_temp"]},
                }
            }
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
            {
                "light.ct": {
                    "state": "on",
                    "attributes": {"supported_color_modes": ["color_temp"]},
                }
            }
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
    async def test_ct_light_passes_through_color_temp_kelvin(self):
        """CT light receiving color_temp_kelvin directly should use it as-is."""
        hass = _make_hass(
            {
                "light.ct": {
                    "state": "on",
                    "attributes": {"supported_color_modes": ["color_temp"]},
                }
            }
        )
        svc = PartyLightsService(hass)
        await svc.start(["light.ct"])
        hass.services.async_call.reset_mock()

        await svc._apply(
            ["light.ct"],
            {"color_temp_kelvin": 3000, "brightness": 204},
            transition=1.0,
        )

        call_args = hass.services.async_call.call_args[0][2]
        assert call_args["color_temp_kelvin"] == 3000
        assert call_args["brightness"] == 204

    @pytest.mark.asyncio
    async def test_dim_light_only_gets_brightness(self):
        hass = _make_hass(
            {
                "light.dim": {
                    "state": "on",
                    "attributes": {"supported_color_modes": ["brightness"]},
                }
            }
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
            {
                "light.sw": {
                    "state": "on",
                    "attributes": {"supported_color_modes": ["onoff"]},
                }
            }
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
        assert call_args["entity_id"] == ["light.sw"]

    @pytest.mark.asyncio
    async def test_apply_handles_service_error(self):
        """_apply should not raise if a light fails."""
        hass = _make_hass()
        hass.services.async_call = AsyncMock(side_effect=HomeAssistantError("HA error"))
        svc = PartyLightsService(hass)
        await svc.start(["light.living_room"])

        # Should not raise
        await svc._apply(
            ["light.living_room"],
            {"rgb_color": [255, 0, 0], "brightness": 255},
        )

    @pytest.mark.asyncio
    async def test_apply_continues_after_one_call_fails(self):
        """A failing call must not abandon the lights in the other groups.

        Lamps that resolve to the same payload now travel in one call (#2708),
        so the unit that can fail is the group, not the lamp. Two capabilities
        means two groups: the first one erroring must not stop the second.
        """
        targeted: list[list[str]] = []

        async def fail_first_only(_domain, _service, data, **kwargs):
            targeted.append(data["entity_id"])
            if len(targeted) == 1:
                raise HomeAssistantError("HA error")

        hass = _make_hass(
            {
                "light.a": {
                    "state": "on",
                    "attributes": {"supported_color_modes": ["rgb"]},
                },
                "light.b": {
                    "state": "on",
                    "attributes": {"supported_color_modes": ["brightness"]},
                },
            }
        )
        hass.services.async_call = AsyncMock(side_effect=fail_first_only)
        svc = PartyLightsService(hass)
        await svc.start(["light.a", "light.b"])

        await svc._apply(
            ["light.a", "light.b"],
            {"rgb_color": [255, 0, 0], "brightness": 255},
        )

        assert targeted == [["light.a"], ["light.b"]]


# ---------------------------------------------------------------------------
# Multiple lights
# ---------------------------------------------------------------------------


class TestMultipleLights:
    """Test behavior with multiple lights of different capabilities."""

    @pytest.mark.asyncio
    async def test_mixed_capabilities_saved(self):
        """Start should save states for all reachable lights."""
        hass = _make_hass(
            {
                "light.rgb": {
                    "state": "on",
                    "attributes": {
                        "supported_color_modes": ["rgb"],
                        "brightness": 100,
                    },
                },
                "light.dim": {
                    "state": "on",
                    "attributes": {
                        "supported_color_modes": ["brightness"],
                        "brightness": 50,
                    },
                },
                "light.sw": {
                    "state": "off",
                    "attributes": {"supported_color_modes": ["onoff"]},
                },
            }
        )
        svc = PartyLightsService(hass)
        await svc.start(["light.rgb", "light.dim", "light.sw"])

        assert len(svc._saved_states) == 3
        assert svc._saved_states["light.rgb"]["brightness"] == 100
        assert svc._saved_states["light.dim"]["brightness"] == 50
        assert svc._saved_states["light.sw"]["state"] == "off"

    @pytest.mark.asyncio
    async def test_mixed_capabilities_apply_adapts_per_light(self):
        """_apply should send different service data per light capability."""
        hass = _make_hass(
            {
                "light.rgb": {
                    "state": "on",
                    "attributes": {"supported_color_modes": ["rgb"]},
                },
                "light.dim": {
                    "state": "on",
                    "attributes": {"supported_color_modes": ["brightness"]},
                },
            }
        )
        svc = PartyLightsService(hass)
        await svc.start(["light.rgb", "light.dim"])
        hass.services.async_call.reset_mock()

        await svc._apply(
            ["light.rgb", "light.dim"],
            {"rgb_color": [255, 0, 0], "brightness": 200},
        )

        assert hass.services.async_call.call_count == 2

        # RGB light gets color
        rgb_call = hass.services.async_call.call_args_list[0][0][2]
        assert rgb_call["rgb_color"] == [255, 0, 0]
        assert rgb_call["brightness"] == 200

        # Dim light gets brightness only
        dim_call = hass.services.async_call.call_args_list[1][0][2]
        assert "rgb_color" not in dim_call
        assert dim_call["brightness"] == 200


# ---------------------------------------------------------------------------
# #2708 — the beat loop's command budget
# ---------------------------------------------------------------------------


def _rgb_lamps(n: int) -> dict[str, dict]:
    """``n`` identical RGB lamps, the setup the beat loop is worst at."""
    return {
        f"light.lamp{i}": {
            "state": "on",
            "attributes": {
                "supported_color_modes": ["rgb"],
                "brightness": 200,
                "rgb_color": [255, 255, 255],
            },
        }
        for i in range(n)
    }


async def _run_beat_loop(svc, bpm: int, seconds: float) -> None:
    """Drive ``_beat_loop`` over ``seconds`` of virtual time.

    Real sleeping would make this a minute-long test; the loop's own interval
    is what advances the clock, so the measurement is of the real code.
    """
    clock = 0.0
    real_sleep = asyncio.sleep

    async def fake_sleep(delay, *args, **kwargs):
        nonlocal clock
        clock += delay
        if clock > seconds:
            raise asyncio.CancelledError
        await real_sleep(0)

    with patch("asyncio.sleep", fake_sleep):
        await svc._beat_loop(bpm)


class TestBeatLoopCommandBudget:
    """The beat loop must stay under what a Zigbee radio can absorb (#2708)."""

    @pytest.mark.asyncio
    async def test_same_capability_lamps_travel_in_one_call(self):
        """Six identical lamps are one service call, not six."""
        hass = _make_hass(_rgb_lamps(6))
        svc = PartyLightsService(hass)
        await svc.start(list(_rgb_lamps(6)))
        hass.services.async_call.reset_mock()

        await svc._apply(list(_rgb_lamps(6)), {"rgb_color": [0, 100, 255]})

        assert hass.services.async_call.call_count == 1
        data = hass.services.async_call.call_args[0][2]
        assert data["entity_id"] == [f"light.lamp{i}" for i in range(6)]
        assert data["rgb_color"] == [0, 100, 255]

    def test_pulse_is_half_time_by_default(self):
        """Six lamps at 120 BPM pulse every second beat, not every beat."""
        hass = _make_hass(_rgb_lamps(6))
        svc = PartyLightsService(hass)
        svc._entity_ids = list(_rgb_lamps(6))

        entities, interval = svc._beat_plan(120)

        assert len(entities) == 6
        assert interval == pytest.approx(1.0)  # two beats of 0.5 s

    def test_extra_lamps_hold_the_static_phase_colour(self):
        """Only the first BEAT_MAX_LIGHTS lamps pulse; the rest are left alone."""
        hass = _make_hass(_rgb_lamps(20))
        svc = PartyLightsService(hass)
        svc._entity_ids = list(_rgb_lamps(20))

        entities, _interval = svc._beat_plan(120)

        assert entities == [f"light.lamp{i}" for i in range(BEAT_MAX_LIGHTS)]

    @pytest.mark.parametrize("bpm", [60, 120, 180, 240])
    @pytest.mark.parametrize("lamps", [1, 2, 6, 20])
    def test_budget_holds_at_any_bpm_and_lamp_count(self, bpm, lamps):
        """The pulse rate never exceeds the downstream command budget."""
        hass = _make_hass(_rgb_lamps(lamps))
        svc = PartyLightsService(hass)
        svc._entity_ids = list(_rgb_lamps(lamps))

        entities, interval = svc._beat_plan(bpm)

        assert len(entities) / interval <= BEAT_COMMANDS_PER_SECOND + 1e-9
        # …and the pulse still lands on a beat.
        beat = 60.0 / bpm
        assert interval / beat == pytest.approx(round(interval / beat))

    @pytest.mark.asyncio
    async def test_twenty_lamps_over_a_thirty_second_round(self):
        """The measurement the issue asked for, on the real loop."""
        lamps = _rgb_lamps(20)
        hass = _make_hass(lamps)
        svc = PartyLightsService(hass)
        await svc.start(list(lamps))
        hass.services.async_call.reset_mock()

        await _run_beat_loop(svc, 120, 30.0)

        calls = hass.services.async_call.call_args_list
        commands = sum(len(c[0][2]["entity_id"]) for c in calls)
        # Before this change: 1,240 service calls and 1,240 lamp commands over
        # the same thirty seconds — 41 commands a second at a coordinator that
        # starts queueing at ten.
        assert len(calls) == 31  # one pulse a second, plus the one at t=0
        assert commands == 31 * BEAT_MAX_LIGHTS  # 186

    @pytest.mark.asyncio
    async def test_capability_is_resolved_once_per_lamp(self):
        """The loop must not re-read the state machine on every pulse."""
        lamps = _rgb_lamps(6)
        hass = _make_hass(lamps)
        svc = PartyLightsService(hass)
        await svc.start(list(lamps))

        probe = MagicMock(side_effect=hass.states.get)
        hass.states.get = probe

        await _run_beat_loop(svc, 120, 10.0)

        # Eleven pulses, six lamps — one lookup each, not sixty-six.
        assert probe.call_count == 6

    @pytest.mark.asyncio
    async def test_wled_entities_still_never_pulse(self):
        """The WLED carve-out survives the cap."""
        lamps = _rgb_lamps(3)
        hass = _make_hass(lamps)
        svc = PartyLightsService(hass)
        await svc.start(list(lamps))
        svc._wled_entities = {"light.lamp0"}

        entities, _interval = svc._beat_plan(120)

        assert entities == ["light.lamp1", "light.lamp2"]
