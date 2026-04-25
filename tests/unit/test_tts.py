"""Tests for TTSService — covers the dual-entity wiring required by #793."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.beatify.services.tts import TTSService


def _make_hass(tts_state: str = "idle", mp_state: str = "idle") -> MagicMock:
    """Build a hass mock where states.get returns the requested state per entity."""
    hass = MagicMock()
    hass.services.async_call = AsyncMock()

    def _get(entity_id: str):
        if entity_id.startswith("tts."):
            return MagicMock(state=tts_state)
        if entity_id.startswith("media_player."):
            return MagicMock(state=mp_state)
        return None

    hass.states.get = MagicMock(side_effect=_get)
    return hass


class TestTTSService:
    @pytest.mark.asyncio
    async def test_speak_passes_both_entity_ids_to_tts_speak(self):
        """#793: tts.speak needs entity_id (TTS) + media_player_entity_id (speaker)."""
        hass = _make_hass()
        svc = TTSService(
            hass,
            tts_entity_id="tts.google_gemini_tts",
            media_player_entity_id="media_player.living_denon",
        )

        await svc.speak("hello")

        hass.services.async_call.assert_awaited_once()
        args, kwargs = hass.services.async_call.call_args
        # First two positional args are (domain, service)
        assert args[0] == "tts"
        assert args[1] == "speak"
        # Service data dict — accept positional or keyword
        data = args[2] if len(args) > 2 else kwargs.get("service_data") or kwargs
        # Find the dict that has 'message' — call_args layout depends on Python version
        if isinstance(data, dict) and "message" in data:
            payload = data
        else:
            payload = next(
                v
                for v in (args + tuple(kwargs.values()))
                if isinstance(v, dict) and "message" in v
            )
        assert payload["entity_id"] == "tts.google_gemini_tts"
        assert payload["media_player_entity_id"] == "media_player.living_denon"
        assert payload["message"] == "hello"

    @pytest.mark.asyncio
    async def test_speak_skips_when_message_empty(self):
        hass = _make_hass()
        svc = TTSService(hass, "tts.x", "media_player.y")
        await svc.speak("")
        hass.services.async_call.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_speak_skips_when_either_id_missing(self):
        """Defensive: empty TTS or media_player id → skip without raising."""
        hass = _make_hass()
        await TTSService(hass, "", "media_player.y").speak("hello")
        await TTSService(hass, "tts.x", "").speak("hello")
        hass.services.async_call.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_speak_skips_when_tts_entity_unavailable(self):
        hass = _make_hass(tts_state="unavailable")
        svc = TTSService(hass, "tts.x", "media_player.y")
        await svc.speak("hello")
        hass.services.async_call.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_speak_skips_when_media_player_unavailable(self):
        hass = _make_hass(mp_state="unavailable")
        svc = TTSService(hass, "tts.x", "media_player.y")
        await svc.speak("hello")
        hass.services.async_call.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_speak_swallows_service_call_exceptions(self):
        """A failing service call must not propagate — TTS is best-effort."""
        hass = _make_hass()
        hass.services.async_call = AsyncMock(side_effect=RuntimeError("boom"))
        svc = TTSService(hass, "tts.x", "media_player.y")
        # Should not raise
        await svc.speak("hello")
