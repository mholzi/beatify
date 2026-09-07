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

import logging
from typing import TYPE_CHECKING, Any

from custom_components.beatify.game.protocols import (
    GameOutputFactories,
    MediaPlayerProtocol,
    PartyLightsProtocol,
    TtsProtocol,
)

from .lights import PartyLightsService
from .media_player import MediaPlayerService, resolve_entity_platform
from .tts import TTSService

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


def ha_service_factories(hass: HomeAssistant) -> GameOutputFactories:
    """Return factories that build the real HA-backed services for ``hass``."""

    def _media_player(
        entity_id: str,
        *,
        platform: str = "unknown",
        provider: str = "spotify",
        inherited_states: dict[str, dict[str, Any]] | None = None,
    ) -> MediaPlayerProtocol:
        # #2693: the platform is DERIVED here, not taken on trust. Since #2636
        # it is the key `build_strategy` dispatches on, so a caller that
        # changes the speaker but forgets the platform (the Crate Digger
        # pre-start hook did exactly that) would route a Sonos entity through
        # `MusicAssistantStrategy` — the game starts, the first song times out,
        # and nothing in the log points at the cause.
        #
        # This factory already closes over `hass`, so the registry that owns
        # the answer is one call away. Deriving it here means the platform can
        # only ever describe the entity this very service is being built for,
        # whatever the caller believed.
        resolved = resolve_entity_platform(hass, entity_id)
        if resolved == "unknown":
            # No registry entry (YAML-only player, test double). Fall back to
            # what the caller passed rather than downgrading a known platform.
            resolved = platform
        elif resolved != platform and platform != "unknown":
            _LOGGER.warning(
                "Media player %s is on platform %s, not %s — using the "
                "registry (#2693)",
                entity_id,
                resolved,
                platform,
            )
        return MediaPlayerService(
            hass,
            entity_id,
            platform=resolved,
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
