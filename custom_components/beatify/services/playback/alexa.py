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

from ...providers import alexa_content_types
from .base import PLAYBACK_TIMEOUT, PlaybackStrategy

_LOGGER = logging.getLogger(__name__)

# Which catalog an Echo is told to search, per provider (#2713). Derived from
# the provider registry rather than written out here: a provider Alexa can
# actually serve declares ``alexa_content_type`` once, and a provider that
# cannot falls through to the warning below instead of being quietly missing
# from an if-chain.
_CONTENT_TYPES = alexa_content_types()

#: What an unmapped provider is played as. Kept as the historic fallback rather
#: than a hard failure, but never silently — see the warning in :meth:`play`.
_FALLBACK_CONTENT_TYPE = "APPLE_MUSIC"


class AlexaStrategy(PlaybackStrategy):
    """Play via Alexa (text search-based)."""

    platforms: ClassVar[tuple[str, ...]] = ("alexa_media", "alexa")
    playback_method: ClassVar[str] = "text_search"
    setup_warning: ClassVar[str | None] = "Service must be linked in Alexa app"
    setup_caveat: ClassVar[str | None] = (
        "Uses voice search - may occasionally play different version"
    )

    async def play(self, song: dict[str, Any]) -> bool:
        """Play via Alexa (text search-based)."""
        search_text = self._get_alexa_search_text(song)
        content_type = _CONTENT_TYPES.get(self._provider)
        if content_type is None:
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
            content_type = _FALLBACK_CONTENT_TYPE

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
