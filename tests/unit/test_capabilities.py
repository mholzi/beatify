"""Tests for CapabilitiesView — the wizard's Step 4 gate."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from custom_components.beatify.server.views import CapabilitiesView


def _hass(*, lights: int = 0, tts_services: dict | None = None) -> MagicMock:
    """Build a mock hass with N lights and the given TTS service map."""
    hass = MagicMock()

    # states.async_all("light") returns a list of fake state objects
    light_states = [MagicMock() for _ in range(lights)]

    def _async_all(domain: str):
        return light_states if domain == "light" else []

    hass.states.async_all.side_effect = _async_all

    # services.async_services() returns a dict keyed by domain
    services = {}
    if tts_services is not None:
        services["tts"] = tts_services
    hass.services.async_services.return_value = services

    return hass


def _body(response) -> dict:
    """Parse a web.Response JSON body without an aiohttp test client."""
    return json.loads(response.body.decode())


class TestCapabilitiesView:
    """Exercise the four capability combinations plus error paths."""

    @pytest.mark.asyncio
    async def test_lights_and_tts_both_available(self):
        view = CapabilitiesView(_hass(lights=3, tts_services={"speak": None}))
        response = await view.get(MagicMock())
        data = _body(response)

        assert data["has_lights"] is True
        assert data["light_count"] == 3
        assert data["has_tts"] is True
        assert data["tts_service_count"] == 1

    @pytest.mark.asyncio
    async def test_only_lights_no_tts(self):
        view = CapabilitiesView(_hass(lights=1, tts_services=None))
        data = _body(await view.get(MagicMock()))

        assert data["has_lights"] is True
        assert data["light_count"] == 1
        assert data["has_tts"] is False
        assert data["tts_service_count"] == 0

    @pytest.mark.asyncio
    async def test_only_tts_no_lights(self):
        view = CapabilitiesView(
            _hass(lights=0, tts_services={"cloud_say": None, "speak": None})
        )
        data = _body(await view.get(MagicMock()))

        assert data["has_lights"] is False
        assert data["light_count"] == 0
        assert data["has_tts"] is True
        assert data["tts_service_count"] == 2

    @pytest.mark.asyncio
    async def test_clean_ha_neither_available(self):
        view = CapabilitiesView(_hass(lights=0, tts_services=None))
        data = _body(await view.get(MagicMock()))

        assert data["has_lights"] is False
        assert data["light_count"] == 0
        assert data["has_tts"] is False
        assert data["tts_service_count"] == 0

    @pytest.mark.asyncio
    async def test_empty_tts_domain_treated_as_no_tts(self):
        """An empty tts: {} dict should NOT mark TTS available."""
        view = CapabilitiesView(_hass(lights=0, tts_services={}))
        data = _body(await view.get(MagicMock()))

        assert data["has_tts"] is False
        assert data["tts_service_count"] == 0
