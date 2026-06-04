"""TTS announcement service for Beatify — voice announcements during games (#447)."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


def _match_language(language: str | None, supported: list[str] | None) -> str | None:
    """Resolve a game language to a code the TTS engine actually supports.

    Returns the engine's own code (so game ``"de"`` resolves to ``"de-DE"`` when
    that's what the engine advertises), or ``None`` when the language can't be
    matched — callers then omit it rather than forcing a code the engine would
    reject (which makes some engines drop the announcement entirely). Matching is
    case-insensitive and treats ``-``/``_`` separators alike, first exact then by
    base language.
    """
    if not language or not supported:
        return None
    target = language.lower()
    for code in supported:
        if code.lower() == target:
            return code
    for code in supported:
        base = code.lower().replace("_", "-").split("-", 1)[0]
        if base == target:
            return code
    return None


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

    async def speak(self, message: str, language: str | None = None) -> None:
        """Speak a message via TTS. Fails gracefully if either entity is unavailable.

        ``language`` (e.g. ``"de"``) is the game language. It is forwarded to
        ``tts.speak`` ONLY when the target entity advertises support for it
        (resolved to the engine's own code, e.g. ``"de-DE"``). If support can't
        be confirmed it is omitted and the engine uses its configured voice —
        forcing an unsupported code makes some engines silently drop the
        announcement. The message text is already localized either way.
        """
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

        service_data = {
            "entity_id": self._tts_entity_id,
            "media_player_entity_id": self._media_player_entity_id,
            "message": message,
        }
        resolved = (
            _match_language(language, self._supported_languages()) if language else None
        )
        if resolved:
            service_data["language"] = resolved

        try:
            await self._hass.services.async_call(
                "tts",
                "speak",
                service_data,
                blocking=False,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.warning(
                "TTS announcement failed (tts=%s, media_player=%s)",
                self._tts_entity_id,
                self._media_player_entity_id,
            )

    def _supported_languages(self) -> list[str] | None:
        """Best-effort read of the TTS entity's advertised language codes.

        Locates the ``tts`` entity component regardless of HA version (it scans
        ``hass.data`` for the component rather than assuming a key) and returns
        the entity's ``supported_languages``. Returns ``None`` on any problem so
        the caller safely omits the language rather than guessing one.
        """
        try:
            from homeassistant.helpers.entity_component import (  # noqa: PLC0415
                EntityComponent,
            )

            for value in self._hass.data.values():
                if (
                    isinstance(value, EntityComponent)
                    and getattr(value, "domain", None) == "tts"
                ):
                    entity = value.get_entity(self._tts_entity_id)
                    langs = getattr(entity, "supported_languages", None)
                    return list(langs) if langs else None
        except Exception:  # noqa: BLE001 — introspection is strictly best-effort
            return None
        return None
