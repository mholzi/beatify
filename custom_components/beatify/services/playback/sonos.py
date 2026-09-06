"""Sonos playback (#2636).

Sonos speaks plain ``media_player.play_media`` with a Spotify URI, and that is
the whole platform. Its brevity next to
:mod:`.music_assistant` is the point of the split: it used to sit in the same
class body as 600 lines of Music Assistant confirmation logic, so a change here
was one indentation level from that.
"""

from __future__ import annotations

import logging
from asyncio import timeout as async_timeout
from typing import Any, ClassVar

from .base import PLAYBACK_TIMEOUT, PlaybackStrategy

_LOGGER = logging.getLogger(__name__)


class SonosStrategy(PlaybackStrategy):
    """Play via Sonos (URI-based)."""

    platforms: ClassVar[tuple[str, ...]] = ("sonos",)

    async def play(self, song: dict[str, Any]) -> bool:
        """Play via Sonos (URI-based)."""
        uri = song.get("_resolved_uri")
        _LOGGER.debug("Sonos playback: %s on %s", uri, self._entity_id)

        async with async_timeout(PLAYBACK_TIMEOUT):
            await self._hass.services.async_call(
                "media_player",
                "play_media",
                {
                    "entity_id": self._entity_id,
                    "media_content_id": uri,
                    "media_content_type": "music",
                },
                blocking=True,
            )
        return True
