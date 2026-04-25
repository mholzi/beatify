"""TTS announcement service for Beatify — voice announcements during games (#447)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class TTSService:
    """Announce game events via Home Assistant TTS."""

    def __init__(self, hass: HomeAssistant, entity_id: str) -> None:
        """Initialize with Home Assistant instance and target media player."""
        self._hass = hass
        self._entity_id = entity_id

    async def speak(self, message: str) -> None:
        """Speak a message via TTS. Fails gracefully if entity is unavailable."""
        if not message:
            return

        state = self._hass.states.get(self._entity_id)
        if not state or state.state == "unavailable":
            _LOGGER.warning(
                "TTS entity unavailable, skipping announcement: %s", self._entity_id
            )
            return

        try:
            await self._hass.services.async_call(
                "tts",
                "speak",
                {
                    "entity_id": self._entity_id,
                    "message": message,
                },
                blocking=False,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.warning("TTS announcement failed for entity: %s", self._entity_id)
