"""Media player discovery service for Beatify."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


async def async_get_media_players(hass: HomeAssistant) -> list[dict]:
    """Get all available media player entities."""
    media_players = [
        {
            "entity_id": state.entity_id,
            "friendly_name": state.attributes.get("friendly_name", state.entity_id),
            "state": state.state,
        }
        for state in hass.states.async_all("media_player")
    ]

    _LOGGER.debug("Found %d media players", len(media_players))
    return media_players
