"""Config flow for Beatify."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback
from homeassistant.helpers import config_validation as cv

from .const import (
    CONF_ENABLE_COMPANION_AUTH_BYPASS,
    DEFAULT_ENABLE_COMPANION_AUTH_BYPASS,
    DOMAIN,
)
from .services.media_player import async_get_media_players

_LOGGER = logging.getLogger(__name__)


class BeatifyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for Beatify."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> BeatifyOptionsFlow:
        """Return the options flow handler for Beatify (#1357)."""
        return BeatifyOptionsFlow()

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle a flow initialized by the user."""
        # Single-instance enforcement is declared via `single_config_entry` in
        # manifest.json (#1402 B6); HA aborts a second entry before this step
        # runs, so no unique-id dance is needed here.

        # Check for available media players using the SAME discovery that
        # async_setup_entry runs (#1402 B6). The previous registry-only scan
        # disagreed with runtime discovery — it counted disabled and
        # capability-unsupported (raw Cast) players the setup path filters out,
        # so the wizard could promise "✓ Found N media player(s)" for players
        # Beatify can't actually use. async_get_media_players reads live states,
        # skips unsupported platforms, and is async-safe.
        media_players = await async_get_media_players(self.hass)
        has_media_players = len(media_players) > 0

        if user_input is not None:
            # User confirmed setup - create entry regardless of media player
            # status. No entry data needed (the previously-stored
            # "has_media_players" flag was never read back — dead field, #1402).
            return self.async_create_entry(title="Beatify", data={})

        # Build description with warning if no media players
        if not has_media_players:
            _LOGGER.warning("No compatible media_player entities found")
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


class BeatifyOptionsFlow(OptionsFlow):
    """Options flow for Beatify (#1357).

    Exposes the single ``enable_companion_auth_bypass`` toggle. The bypass is
    OFF by default; enabling it weakens auth on the local network and should
    stay off unless the HA Android Companion app genuinely cannot authenticate.
    """

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Manage the Beatify options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self.config_entry.options.get(
            CONF_ENABLE_COMPANION_AUTH_BYPASS,
            DEFAULT_ENABLE_COMPANION_AUTH_BYPASS,
        )
        data_schema = vol.Schema(
            {
                vol.Optional(
                    CONF_ENABLE_COMPANION_AUTH_BYPASS,
                    default=current,
                ): cv.boolean,
            }
        )
        return self.async_show_form(step_id="init", data_schema=data_schema)
