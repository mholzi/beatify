"""Alexa playback (#2636).

Alexa has no URI: the Echo is asked, in words, for "<title> by <artist>", and
the content type tells it which service to look in. That voice search is the
platform's whole character — and the reason its failure modes have nothing in
common with the Music Assistant path's.
"""

from __future__ import annotations

import logging
from asyncio import timeout as async_timeout
from typing import Any, ClassVar

from .base import PLAYBACK_TIMEOUT, PlaybackStrategy

_LOGGER = logging.getLogger(__name__)


class AlexaStrategy(PlaybackStrategy):
    """Play via Alexa (text search-based)."""

    platforms: ClassVar[tuple[str, ...]] = ("alexa_media", "alexa")

    async def play(self, song: dict[str, Any]) -> bool:
        """Play via Alexa (text search-based)."""
        search_text = self._get_alexa_search_text(song)
        if self._provider == "spotify":
            content_type = "SPOTIFY"
        elif self._provider == "amazon_music":
            content_type = "AMAZON_MUSIC"
        elif self._provider == "apple_music":
            content_type = "APPLE_MUSIC"
        else:
            # Unknown provider slipped past the wizard gate. Previously every
            # non-spotify/non-amazon provider was silently mapped to
            # APPLE_MUSIC, so a deezer/tidal/ytmusic mismatch played the wrong
            # catalog with no diagnostic — the same silent-fail class as
            # #768/#808. Surface it (mirrors the #1276 dispatch warning) before
            # falling back to APPLE_MUSIC. (#1402)
            _LOGGER.warning(
                "Alexa dispatch: unexpected provider %r — no Alexa content-type "
                "mapping; falling back to APPLE_MUSIC for %s - %s (#1402)",
                self._provider,
                song.get("artist"),
                song.get("title"),
            )
            content_type = "APPLE_MUSIC"

        _LOGGER.debug(
            "Alexa playback: '%s' (%s) on %s",
            search_text,
            content_type,
            self._entity_id,
        )

        async with async_timeout(PLAYBACK_TIMEOUT):
            await self._hass.services.async_call(
                "media_player",
                "play_media",
                {
                    "entity_id": self._entity_id,
                    "media_content_id": search_text,
                    "media_content_type": content_type,
                },
                blocking=True,
            )
        return True

    def _get_alexa_search_text(self, song: dict[str, Any]) -> str:
        """Generate Alexa-compatible search text from song metadata."""
        artist = song.get("artist", "")
        title = song.get("title", "")

        # Playlists may store multiple artists as "A;B" — use only the first.
        if artist and ";" in artist:
            artist = artist.split(";")[0].strip()

        if artist and title:
            return f"{title} by {artist}"
        if title:
            return title
        _LOGGER.warning("Song missing artist/title for Alexa search")
        return "unknown song"
