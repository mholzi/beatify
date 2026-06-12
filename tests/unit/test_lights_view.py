"""Tests for LightsView (/beatify/api/lights) — the party-lights picker source.

The picker must not list ``unavailable`` lights: an unreachable entity can't be
controlled by anyone, so offering it only produces dead selections that silently
do nothing during the game.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from custom_components.beatify.server import views
from custom_components.beatify.server.views import LightsView


def _light(entity_id: str, state: str, color_modes: list[str]) -> MagicMock:
    s = MagicMock()
    s.entity_id = entity_id
    s.state = state
    s.attributes = {"supported_color_modes": color_modes, "friendly_name": entity_id}
    return s


def _hass(states: list) -> MagicMock:
    hass = MagicMock()
    hass.states.async_all.side_effect = lambda domain: (
        states if domain == "light" else []
    )
    return hass


def _body(response) -> dict:
    return json.loads(response.body.decode())


@pytest.mark.asyncio
async def test_unavailable_lights_are_hidden(monkeypatch):
    monkeypatch.setattr(views, "is_authorized_http", MagicMock(return_value=True))
    hass = _hass(
        [
            _light("light.regal", "off", ["color_temp", "rgb"]),
            _light("light.schreibtisch_rope", "unavailable", ["color_temp", "rgb"]),
            _light("light.on_strip", "on", ["rgb"]),
        ]
    )
    data = _body(await LightsView(hass).get(MagicMock()))
    ids = [light["entity_id"] for light in data["lights"]]
    # "off" is reachable and kept; only "unavailable" is dropped.
    assert ids == ["light.regal", "light.on_strip"]


@pytest.mark.asyncio
async def test_capability_mapping_for_listed_lights(monkeypatch):
    monkeypatch.setattr(views, "is_authorized_http", MagicMock(return_value=True))
    hass = _hass(
        [
            _light("light.rgb", "on", ["rgb"]),
            _light("light.ct", "on", ["color_temp"]),
            _light("light.dim", "on", ["brightness"]),
            _light("light.plain", "on", ["onoff"]),
        ]
    )
    data = _body(await LightsView(hass).get(MagicMock()))
    caps = {light["entity_id"]: light["capability"] for light in data["lights"]}
    assert caps == {
        "light.rgb": "rgb",
        "light.ct": "ct",
        "light.dim": "dim",
        "light.plain": "onoff",
    }
