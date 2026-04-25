"""Config flow for Beatify."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class BeatifyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for Beatify."""

    VERSION = 1

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle a flow initialized by the user."""
        # Prevent multiple instances
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        # Check for available media players
        media_players = self._get_media_player_entities()
        has_media_players = len(media_players) > 0

        if user_input is not None:
            # User confirmed setup - create entry regardless of media player status
            # Store whether media players were available at setup time
            return self.async_create_entry(
                title="Beatify",
                data={"has_media_players": has_media_players},
            )

        # Build description with warning if no media players
        if not has_media_players:
            _LOGGER.warning("No media_player entities found in Home Assistant")
            warning_msg = (
                "⚠️ No media players found. Beatify requires at least one "
                "media_player entity to play music. You can proceed, but "
                "playback won't work until you add a media player."
            )
            description_placeholders = {"warning": warning_msg}
        else:
            # Show available media players with friendly names
            player_list = ", ".join(
                p.get("friendly_name", p["entity_id"]) for p in media_players
            )
            count = len(media_players)
            description_placeholders = {
                "warning": f"✓ Found {count} media player(s): {player_list}"
            }

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({}),
            description_placeholders=description_placeholders,
        )

    def _get_media_player_entities(self) -> list[dict[str, str]]:
        """
        Get list of available media_player entities with friendly names.

        Returns a list of dicts with entity_id and friendly_name for all
        media_player entities registered in Home Assistant.
        """
        entity_reg = er.async_get(self.hass)
        media_players = []

        for entry in entity_reg.entities.values():
            if entry.domain == "media_player":
                # Get friendly name from entity registry or fall back to entity_id
                friendly_name = entry.name or entry.original_name or entry.entity_id
                media_players.append(
                    {
                        "entity_id": entry.entity_id,
                        "friendly_name": friendly_name,
                    }
                )

        _LOGGER.debug(
            "Found %d media_player entities: %s",
            len(media_players),
            [p["entity_id"] for p in media_players],
        )
        return media_players
