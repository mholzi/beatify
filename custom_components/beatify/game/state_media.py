"""Media-player & party-lights output subsystem for :class:`GameState`.

Issue #1271 next-increment extraction: the external-output cluster — media
transport (``stop_media``, ``set_volume_on_player``, ``seek_forward``,
``play_deferred_song``), party-lights control (``configure_party_lights``,
``disable_party_lights``, ``_lights_set_phase``, ``_lights_flash``) and the
host-side ``adjust_volume`` helper — is pulled out of the ``game/state.py``
God-Object into this ``MediaControlMixin``.

The mixin is **behavior-preserving**: it carries the exact same methods that
previously lived on ``GameState`` (originally Stories 6.4 / Issues #321 /
#331 / #498). ``GameState`` inherits them, so its public API and every
caller / test are unchanged.

The mixin relies on attributes the host class owns and that live on ``self``
at runtime:

* ``self._media_player_service`` — :class:`MediaPlayerProtocol` instance (or
  ``None`` before the first round), the transport all playback flows through.
* ``self._party_lights`` — :class:`PartyLightsProtocol` instance (or ``None``).
* ``self._hass`` — Home Assistant instance (to construct the lights service).
* ``self._bg_tasks`` — set of fire-and-forget background tasks.
* ``self.volume_level`` — current game volume, clamped 0.0–1.0.

It carries no state of its own and imports nothing from ``state.py`` at
runtime (``GamePhase`` is a typing-only import), so the extraction introduces
no cyclic imports.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from custom_components.beatify.const import VOLUME_STEP

if TYPE_CHECKING:
    from .state import GamePhase

_LOGGER = logging.getLogger(__name__)


class MediaControlMixin:
    """Media-player & party-lights output behavior for :class:`GameState`.

    See module docstring for the host-class attributes this mixin reads.
    """

    async def stop_media(self) -> None:
        """Stop media playback if a media player service is available (#321)."""
        if self._media_player_service:
            await self._media_player_service.stop()

    async def set_volume_on_player(self, level: float) -> bool:
        """Apply volume level to the media player (#321).

        Returns:
            True if successful, False if failed or no media player.
        """
        if self._media_player_service:
            return await self._media_player_service.set_volume(level)
        return False

    async def seek_forward(self, seconds: int) -> bool:
        """Seek media player forward by given seconds (#498)."""
        if self._media_player_service:
            return await self._media_player_service.seek_forward(seconds)
        return False

    async def play_deferred_song(self, song: dict) -> bool:
        """Play a song that was deferred for intro splash (#321).

        Returns:
            True if playback started, False otherwise.
        """
        if self._media_player_service:
            return await self._media_player_service.play_song(song)
        return False

    # ------------------------------------------------------------------
    # Party Lights (#331)
    # ------------------------------------------------------------------

    async def configure_party_lights(
        self,
        entity_ids: list[str],
        intensity: str = "medium",
        light_mode: str = "dynamic",
        wled_presets: dict[str, int] | None = None,
    ) -> None:
        """Configure and start Party Lights for the game."""
        # Lazy import: only the concrete class for instantiation; type hints
        # use PartyLightsProtocol (module-level) to keep the import graph acyclic.
        from custom_components.beatify.services.lights import PartyLightsService  # noqa: PLC0415

        # #1402 B2: a reconfigure (admin changes intensity / mode / entities
        # mid-game via admin_set_party_lights) previously replaced the active
        # service outright — the old one was never stopped, so its captured
        # pre-party light states were dropped and the new service's start()
        # re-captured states that are now the PARTY colors it had applied. On
        # game-end the new service would then "restore" lights to party colors,
        # permanently losing the user's real original states. Carry the genuine
        # pre-party snapshot forward into the new instance so overlapping
        # entities still restore to their true original look.
        inherited_states = (
            self._party_lights.snapshot_saved_states() if self._party_lights else None
        )

        self._party_lights = PartyLightsService(self._hass)
        await self._party_lights.start(
            entity_ids,
            intensity,
            light_mode,
            wled_presets,
            inherited_states=inherited_states,
        )

    async def disable_party_lights(self) -> None:
        """Stop Party Lights and restore original light states."""
        if self._party_lights:
            await self._party_lights.stop()
            self._party_lights = None

    async def _lights_set_phase(self, phase: GamePhase) -> None:
        """Set Party Lights phase color (fire-and-forget)."""
        if self._party_lights:
            try:
                await self._party_lights.set_phase(phase)
            except Exception:  # noqa: BLE001
                _LOGGER.warning("Party Lights phase change failed")

    async def _lights_flash(self, color: str) -> None:
        """Flash Party Lights (fire-and-forget)."""
        if self._party_lights:
            try:
                task = asyncio.create_task(self._party_lights.flash(color))
                self._bg_tasks.add(task)
                task.add_done_callback(self._bg_tasks.discard)
            except Exception:  # noqa: BLE001
                _LOGGER.warning("Party Lights flash failed")

    def adjust_volume(self, direction: str) -> float:
        """
        Adjust volume level by step (Story 6.4).

        Args:
            direction: "up" to increase, "down" to decrease

        Returns:
            New volume level (clamped 0.0 to 1.0)

        """
        # Sync with actual media player volume before adjusting
        if self._media_player_service:
            self.volume_level = self._media_player_service.get_volume()

        if direction == "up":
            self.volume_level = min(1.0, self.volume_level + VOLUME_STEP)
        elif direction == "down":
            self.volume_level = max(0.0, self.volume_level - VOLUME_STEP)

        return self.volume_level
