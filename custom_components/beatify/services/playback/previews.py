"""Find the 30-second preview a browser can play for one song.

The browser target (``browser.py``) cannot play Spotify, Apple Music or Tidal:
those need a login and copy protection. What any browser can play without
either is the public preview clip:

* Deezer: ``https://api.deezer.com/track/{id}`` answers with a ``preview`` MP3
  URL, no key needed. Nearly every catalogue song carries ``uri_deezer``.
* Apple: ``https://itunes.apple.com/lookup?id={id}`` answers with a
  ``previewUrl`` (AAC). The fallback when Deezer has no preview for the id
  (removed, region-locked, or a preview-less release).

The URL is looked up once per round, just before the song plays, and handed to
the browser as it is. Nothing here downloads, stores or proxies the audio:
Deezer's terms forbid keeping it, and the signed preview URLs expire anyway.

Modelled on ``library/popularity.py``: the parsing is pure and unit-tested,
only the ``async_*`` function touches the network.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any

_LOGGER = logging.getLogger(__name__)

_DEEZER_TRACK = "https://api.deezer.com/track/{track_id}"
_ITUNES_LOOKUP = "https://itunes.apple.com/lookup"

_DEEZER_URI = re.compile(r"^deezer://track/(\d+)$")
_APPLE_URI = re.compile(r"^applemusic://track/(\d+)$")

#: Seconds to wait for one lookup. A round start is waiting on it.
LOOKUP_TIMEOUT = 6.0


@dataclass(frozen=True)
class Preview:
    """One playable preview clip."""

    #: The clip itself, an https URL the browser streams directly.
    url: str
    #: ``"deezer"`` or ``"apple"`` — which catalogue answered.
    source: str
    #: Cover art from the same answer, when it carried one.
    album_art: str | None = None


def deezer_track_id(song: dict[str, Any]) -> str | None:
    """The numeric Deezer track id from ``uri_deezer``, or None."""
    match = _DEEZER_URI.match(str(song.get("uri_deezer") or ""))
    return match.group(1) if match else None


def apple_track_id(uri: str | None) -> str | None:
    """The numeric Apple track id from an ``applemusic://track/{id}`` URI."""
    match = _APPLE_URI.match(str(uri or ""))
    return match.group(1) if match else None


def _https(url: Any) -> str | None:
    """``url`` when it is a non-empty https URL, else None."""
    if isinstance(url, str) and url.startswith("https://"):
        return url
    return None


def parse_deezer_track(data: Any) -> Preview | None:
    """The preview in a Deezer ``/track/{id}`` answer. Pure; None when absent.

    Deezer answers an unknown id with HTTP 200 and an ``error`` object, and a
    track without a clip with ``"preview": ""`` — both mean "no preview".
    """
    if not isinstance(data, dict) or data.get("error"):
        return None
    url = _https(data.get("preview"))
    if url is None:
        return None
    album = data.get("album") if isinstance(data.get("album"), dict) else {}
    art = _https(album.get("cover_xl")) or _https(album.get("cover_big"))
    return Preview(url=url, source="deezer", album_art=art)


def parse_itunes_lookup(data: Any) -> Preview | None:
    """The preview in an iTunes ``lookup`` answer. Pure; None when absent."""
    if not isinstance(data, dict):
        return None
    for item in data.get("results") or []:
        if not isinstance(item, dict):
            continue
        url = _https(item.get("previewUrl"))
        if url is None:
            continue
        art = _https(item.get("artworkUrl100"))
        if art:
            # The lookup only names the 100px thumbnail; the same path serves
            # any size, and the TV shows the cover large.
            art = art.replace("100x100bb", "600x600bb")
        return Preview(url=url, source="apple", album_art=art)
    return None


async def _get_json(session: Any, url: str, *, timeout: float) -> Any:
    """GET ``url`` and decode JSON; None on any failure."""
    try:
        async with session.get(url, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            # iTunes answers with text/javascript; decode regardless.
            return await resp.json(content_type=None)
    except (TimeoutError, asyncio.TimeoutError):
        return None
    except Exception:  # noqa: BLE001 — a lookup failure is "no preview"
        return None


async def async_resolve_preview(
    session: Any,
    song: dict[str, Any],
    *,
    apple_uri: str | None = None,
    storefront: str | None = None,
    timeout: float = LOOKUP_TIMEOUT,
) -> Preview | None:
    """The preview to play for ``song``: Deezer first, then Apple.

    Args:
        session: an aiohttp client session.
        song: the playlist song; ``uri_deezer`` is read from it.
        apple_uri: the song's Apple Music URI for the host's storefront, as
            ``game/playlist.py`` resolves it. None skips the Apple fallback.
        storefront: the host's Apple storefront ("de", "us"), so the lookup
            searches the catalogue the id belongs to.
        timeout: seconds per lookup.

    Returns:
        The preview, or None when neither catalogue has one — the caller
        skips the song like any other unplayable one.
    """
    deezer_id = deezer_track_id(song)
    if deezer_id:
        data = await _get_json(
            session, _DEEZER_TRACK.format(track_id=deezer_id), timeout=timeout
        )
        preview = parse_deezer_track(data)
        if preview is not None:
            return preview
        _LOGGER.debug("No Deezer preview for track %s", deezer_id)

    apple_id = apple_track_id(apple_uri)
    if apple_id:
        url = f"{_ITUNES_LOOKUP}?id={apple_id}&entity=song"
        if storefront:
            url += f"&country={storefront}"
        preview = parse_itunes_lookup(await _get_json(session, url, timeout=timeout))
        if preview is not None:
            return preview
        _LOGGER.debug("No Apple preview for track %s", apple_id)

    return None
