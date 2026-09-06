"""Binds the game's output ports to the concrete Home Assistant services (#2638).

This module is the seam. ``game/`` declares what it needs
(``game/protocols.py``); ``services/`` knows how to build it against a live
``hass``; and this file is the single place where the two meet. It is imported
only from composition points (``custom_components/beatify/__init__.py`` and the
defensive fallback in ``server/game_views.py``), never from ``game/`` — which is
why the domain package no longer carries lazy ``services.`` imports to break an
import cycle.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from custom_components.beatify.game.protocols import (
    GameOutputFactories,
    MediaPlayerProtocol,
    PartyLightsProtocol,
    TtsProtocol,
)

from .lights import PartyLightsService
from .media_player import MediaPlayerService
from .tts import TTSService

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


def ha_service_factories(hass: HomeAssistant) -> GameOutputFactories:
    """Return factories that build the real HA-backed services for ``hass``."""

    def _media_player(
        entity_id: str,
        *,
        platform: str = "unknown",
        provider: str = "spotify",
        inherited_states: dict[str, dict[str, Any]] | None = None,
    ) -> MediaPlayerProtocol:
        return MediaPlayerService(
            hass,
            entity_id,
            platform=platform,
            provider=provider,
            inherited_states=inherited_states,
        )

    def _party_lights() -> PartyLightsProtocol:
        return PartyLightsService(hass)

    def _tts(
        *,
        tts_entity_id: str,
        media_player_entity_id: str,
    ) -> TtsProtocol:
        return TTSService(
            hass,
            tts_entity_id=tts_entity_id,
            media_player_entity_id=media_player_entity_id,
        )

    return GameOutputFactories(
        media_player=_media_player,
        party_lights=_party_lights,
        tts=_tts,
    )
