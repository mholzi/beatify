"""Config flow for Beatify."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntryState, ConfigFlow, ConfigFlowResult

from .const import DOMAIN, MA_SETUP_URL

_LOGGER = logging.getLogger(__name__)


class BeatifyConfigFlow(ConfigFlow, domain=DOMAIN):
    """Config flow for Beatify."""

    VERSION = 1

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle a flow initialized by the user."""
        errors: dict[str, str] = {}

        # Prevent multiple instances
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()

        # Check Music Assistant availability
        if not await self._async_is_music_assistant_configured():
            _LOGGER.warning("Music Assistant not found or not loaded")
            errors["base"] = "ma_not_found"
            return self.async_show_form(
                step_id="user",
                errors=errors,
                description_placeholders={"ma_url": MA_SETUP_URL},
            )

        if user_input is not None:
            return self.async_create_entry(
                title="Beatify",
                data={},
            )

        return self.async_show_form(step_id="user")

    async def _async_is_music_assistant_configured(self) -> bool:
        """Check if Music Assistant is installed and fully loaded."""
        entries = self.hass.config_entries.async_entries("music_assistant")
        is_configured = any(
            entry.state == ConfigEntryState.LOADED for entry in entries
        )
        _LOGGER.debug(
            "Music Assistant check: %d entries, configured=%s",
            len(entries),
            is_configured,
        )
        return is_configured
