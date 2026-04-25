"""TTS announcement service for Beatify — voice announcements during games (#447)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class TTSService:
    """Announce game events via Home Assistant TTS.

    HA's modern ``tts.speak`` service requires two identifiers: a TTS provider
    entity (e.g. ``tts.google_gemini_tts``) and a media player to route the
    audio through. #793 reported that Beatify was only passing one — the
    audio generated but had nowhere to play, so announcements went silent
    on every modern TTS entity (Gemini, Cloud, etc.).

    Beatify reuses the game's existing speaker as the media player —
    announcements should come out of the same speaker as the music.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        tts_entity_id: str,
        media_player_entity_id: str,
    ) -> None:
        """Initialize with HA instance, TTS provider entity, and target speaker."""
        self._hass = hass
        self._tts_entity_id = tts_entity_id
        self._media_player_entity_id = media_player_entity_id

    async def speak(self, message: str) -> None:
        """Speak a message via TTS. Fails gracefully if either entity is unavailable."""
        if not message:
            return
        if not self._tts_entity_id or not self._media_player_entity_id:
            _LOGGER.warning(
                "TTS skipped — missing identifier (tts=%r, media_player=%r)",
                self._tts_entity_id,
                self._media_player_entity_id,
            )
            return

        tts_state = self._hass.states.get(self._tts_entity_id)
        if not tts_state or tts_state.state == "unavailable":
            _LOGGER.warning(
                "TTS entity unavailable, skipping announcement: %s",
                self._tts_entity_id,
            )
            return

        mp_state = self._hass.states.get(self._media_player_entity_id)
        if not mp_state or mp_state.state == "unavailable":
            _LOGGER.warning(
                "Media player unavailable, skipping TTS: %s",
                self._media_player_entity_id,
            )
            return

        try:
            await self._hass.services.async_call(
                "tts",
                "speak",
                {
                    "entity_id": self._tts_entity_id,
                    "media_player_entity_id": self._media_player_entity_id,
                    "message": message,
                },
                blocking=False,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.warning(
                "TTS announcement failed (tts=%s, media_player=%s)",
                self._tts_entity_id,
                self._media_player_entity_id,
            )
