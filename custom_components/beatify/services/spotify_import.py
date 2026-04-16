"""Spotify playlist import service for Beatify."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import slugify

_LOGGER = logging.getLogger(__name__)

ODESLI_BASE = "https://api.song.link/v1-alpha.1/links"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_BASE = "https://api.spotify.com/v1"
MAX_SONGS = 200

# Spotify playlist IDs are base-62 and exactly 22 chars (#711).
_PLAYLIST_ID_RE = re.compile(r"^[A-Za-z0-9]{22}$")
_PLAYLIST_PATH_RE = re.compile(r"^/playlist/([A-Za-z0-9]{22})/?$")
_VALID_SPOTIFY_HOSTS = frozenset({"open.spotify.com", "play.spotify.com"})


def parse_spotify_playlist_id(url: str) -> str:
    """Parse playlist ID from various Spotify URL formats.

    Accepts:
        spotify:playlist:<22-char-id>
        https://open.spotify.com/playlist/<22-char-id>[?si=...]
    Rejects other hosts, paths, or malformed IDs (#699, #711).
    """
    # spotify:playlist:37i9dQZF1DXcBWIGoYBM5M
    if url.startswith("spotify:playlist:"):
        pid = url.split(":", 2)[-1]
        if _PLAYLIST_ID_RE.match(pid):
            return pid
        raise ValueError(f"Invalid Spotify playlist ID: {pid}")

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"Unsupported URL scheme: {parsed.scheme}")
    if parsed.hostname not in _VALID_SPOTIFY_HOSTS:
        raise ValueError(f"Not a Spotify URL: {parsed.hostname}")

    match = _PLAYLIST_PATH_RE.match(parsed.path)
    if match:
        return match.group(1)

    raise ValueError(f"Cannot parse Spotify playlist ID from: {url}")


# Token cache keyed by client_id — avoids refetching on every request (#691).
_token_cache: dict[str, dict[str, Any]] = {}
_TOKEN_EXPIRY_BUFFER = 60  # refresh 1 min before expiry


async def async_fetch_spotify_token(
    session: aiohttp.ClientSession,
    client_id: str,
    client_secret: str,
) -> str:
    """Fetch access token using Spotify Client Credentials flow with caching (#691)."""
    cached = _token_cache.get(client_id)
    now = time.time()
    if cached and now < cached["expires_at"] - _TOKEN_EXPIRY_BUFFER:
        return cached["token"]

    credentials = base64.b64encode(
        f"{client_id}:{client_secret}".encode()
    ).decode()

    headers = {
        "Authorization": f"Basic {credentials}",
        "Content-Type": "application/x-www-form-urlencoded",
    }
    data = {"grant_type": "client_credentials"}

    async with session.post(SPOTIFY_TOKEN_URL, headers=headers, data=data) as resp:
        resp.raise_for_status()
        result = await resp.json()

    token = result["access_token"]
    expires_in = int(result.get("expires_in", 3600))
    _token_cache[client_id] = {
        "token": token,
        "expires_at": now + expires_in,
    }
    return token


def _safe_parse_year(release_date: str) -> int:
    """Parse year from Spotify release_date, tolerating malformed values (#700)."""
    if not release_date:
        return 0
    try:
        # Spotify returns YYYY, YYYY-MM, or YYYY-MM-DD. Take the first 4 chars.
        return int(release_date[:4])
    except (ValueError, TypeError):
        _LOGGER.debug("Malformed Spotify release_date %r — defaulting to 0", release_date)
        return 0


async def async_fetch_playlist_tracks(
    session: aiohttp.ClientSession,
    token: str,
    playlist_id: str,
) -> list[dict[str, Any]]:
    """Fetch tracks from a Spotify playlist with pagination."""
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{SPOTIFY_API_BASE}/playlists/{playlist_id}/tracks"
    tracks: list[dict[str, Any]] = []

    while url and len(tracks) < MAX_SONGS:
        async with session.get(url, headers=headers) as resp:
            resp.raise_for_status()
            data = await resp.json()

        for item in data.get("items", []):
            if len(tracks) >= MAX_SONGS:
                break
            track = item.get("track")
            if not track or not track.get("name"):
                continue

            artists = ", ".join(a["name"] for a in track.get("artists", []))
            album = track.get("album", {})
            year = _safe_parse_year(album.get("release_date", ""))

            tracks.append({
                "title": track["name"],
                "artist": artists,
                "year": year,
                "uri": track.get("uri", ""),
            })

        url = data.get("next")

    return tracks


def _convert_apple_music_url(url: str) -> str:
    """Convert Apple Music URL to applemusic:// URI."""
    # Extract numeric ID from end of URL
    match = re.search(r"/(\d+)(?:\?|$)", url)
    if match:
        return f"applemusic://track/{match.group(1)}"
    return ""


def _convert_tidal_url(url: str) -> str:
    """Convert Tidal URL to tidal:// URI."""
    match = re.search(r"/track/(\d+)", url)
    if match:
        return f"tidal://track/{match.group(1)}"
    return ""


def _convert_deezer_url(url: str) -> str:
    """Convert Deezer URL to deezer:// URI."""
    match = re.search(r"/track/(\d+)", url)
    if match:
        return f"deezer://track/{match.group(1)}"
    return ""


_EMPTY_ENRICHMENT = {
    "uri_youtube_music": "",
    "uri_apple_music": "",
    "uri_tidal": "",
    "uri_deezer": "",
}


async def async_enrich_via_odesli(
    session: aiohttp.ClientSession,
    spotify_uri: str,
) -> dict[str, str]:
    """Enrich a track with cross-platform URIs via Odesli/song.link."""
    try:
        encoded_uri = quote(spotify_uri, safe="")
        url = f"{ODESLI_BASE}?url={encoded_uri}&userCountry=US"

        async with session.get(url) as resp:
            if resp.status == 429:
                # Log rate limits at WARNING so operators see enrichment loss (#694).
                _LOGGER.warning(
                    "Odesli rate-limited (429) for %s — track will have no cross-platform URIs",
                    spotify_uri,
                )
                return dict(_EMPTY_ENRICHMENT)
            if resp.status != 200:
                _LOGGER.debug("Odesli returned %s for %s", resp.status, spotify_uri)
                return dict(_EMPTY_ENRICHMENT)
            data = await resp.json()

        links_by_platform = data.get("linksByPlatform", {})

        # YouTube Music - keep URL as-is
        yt_url = links_by_platform.get("youtubeMusic", {}).get("url", "")

        # Apple Music - convert to applemusic:// URI
        apple_url = links_by_platform.get("appleMusic", {}).get("url", "")
        apple_uri = _convert_apple_music_url(apple_url) if apple_url else ""

        # Tidal - convert to tidal:// URI
        tidal_url = links_by_platform.get("tidal", {}).get("url", "")
        tidal_uri = _convert_tidal_url(tidal_url) if tidal_url else ""

        # Deezer - convert to deezer:// URI
        deezer_url = links_by_platform.get("deezer", {}).get("url", "")
        deezer_uri = _convert_deezer_url(deezer_url) if deezer_url else ""

        return {
            "uri_youtube_music": yt_url,
            "uri_apple_music": apple_uri,
            "uri_tidal": tidal_uri,
            "uri_deezer": deezer_uri,
        }

    except Exception as exc:  # noqa: BLE001
        _LOGGER.warning("Odesli enrichment failed for %s: %s", spotify_uri, exc)
        return dict(_EMPTY_ENRICHMENT)


_CREDS_STORE_KEY = "beatify.spotify_credentials"
_CREDS_STORE_VERSION = 1


def _get_store(hass: HomeAssistant) -> Store:
    """Get or create the HA Store for Spotify credentials."""
    return Store(hass, _CREDS_STORE_VERSION, _CREDS_STORE_KEY)


async def async_save_credentials(
    hass: HomeAssistant, client_id: str, client_secret: str
) -> None:
    """Save Spotify credentials via HA storage."""
    store = _get_store(hass)
    await store.async_save({"client_id": client_id, "client_secret": client_secret})


async def async_load_credentials(hass: HomeAssistant) -> dict[str, str] | None:
    """Load Spotify credentials from HA storage."""
    store = _get_store(hass)
    data = await store.async_load()
    return data if data else None


class PlaylistImportError(Exception):
    """Base class for playlist-import failures with friendly messages (#710)."""


class DuplicatePlaylistError(PlaylistImportError):
    """A playlist file with the same slug already exists (#695)."""


async def async_import_playlist(
    hass: HomeAssistant,
    spotify_url: str,
    name: str | None = None,
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Import a Spotify playlist and enrich with cross-platform URIs."""
    playlist_id = parse_spotify_playlist_id(spotify_url)

    credentials = await async_load_credentials(hass)
    if not credentials:
        raise ValueError("Spotify credentials not configured. Save them first.")

    client_id = credentials["client_id"]
    client_secret = credentials["client_secret"]


    async with aiohttp.ClientSession() as session:
        # Fetch token and tracks
        token = await async_fetch_spotify_token(session, client_id, client_secret)
        tracks = await async_fetch_playlist_tracks(session, token, playlist_id)

        if not tracks:
            raise ValueError(f"No tracks found in playlist {playlist_id}")

        # If no name provided, fetch playlist metadata
        if not name:
            headers = {"Authorization": f"Bearer {token}"}
            async with session.get(
                f"{SPOTIFY_API_BASE}/playlists/{playlist_id}",
                headers=headers,
            ) as resp:
                if resp.status == 200:
                    pl_data = await resp.json()
                    name = pl_data.get("name", f"spotify_{playlist_id}")
                else:
                    name = f"spotify_{playlist_id}"

        # Enrich each track via Odesli with rate limiting
        enriched_songs: list[dict[str, Any]] = []
        for track in tracks:
            uris = await async_enrich_via_odesli(session, track["uri"])
            await asyncio.sleep(0.2)

            spotify_uri = track["uri"]
            song = {
                "year": track["year"],
                # #705: write both `uri` (legacy) and `uri_spotify` (canonical)
                "uri": spotify_uri,
                "uri_spotify": spotify_uri,
                "artist": track["artist"],
                "title": track["title"],
                "uri_youtube_music": uris.get("uri_youtube_music", ""),
                "uri_apple_music": uris.get("uri_apple_music", ""),
                "uri_tidal": uris.get("uri_tidal", ""),
                "uri_deezer": uris.get("uri_deezer", ""),
                "alt_artists": [],
                "fun_fact": "",
                "fun_fact_de": "",
                "fun_fact_es": "",
                "fun_fact_fr": "",
                "fun_fact_nl": "",
            }
            enriched_songs.append(song)

    # Build playlist JSON
    playlist_data = {
        "name": name,
        "version": "1.0",
        "tags": [],
        "songs": enriched_songs,
    }

    # Save to disk
    slug = slugify(name)
    output_path = Path(hass.config.path(f"beatify/playlists/{slug}.json"))

    def _save() -> None:
        """Atomic write (#696) with duplicate-name detection (#695) and
        OSError → friendly error (#710)."""
        parent = output_path.parent
        try:
            parent.mkdir(parents=True, exist_ok=True)
        except OSError as err:
            raise PlaylistImportError(
                f"Cannot create playlist directory: {err.strerror or err}"
            ) from err

        if output_path.exists() and not overwrite:
            raise DuplicatePlaylistError(
                f"A playlist named '{name}' already exists. "
                f"Re-submit with overwrite=true to replace it."
            )

        # Write to a temp file in the same dir, then atomically rename (#696).
        tmp_fd, tmp_path = tempfile.mkstemp(dir=parent, suffix=".json.tmp")
        try:
            with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                json.dump(playlist_data, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, output_path)
        except OSError as err:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            if err.errno == 28:  # ENOSPC
                raise PlaylistImportError(
                    "Disk full — could not save playlist. Free up space and retry."
                ) from err
            if err.errno == 13:  # EACCES
                raise PlaylistImportError(
                    "Permission denied writing playlist file."
                ) from err
            raise PlaylistImportError(
                f"Failed to write playlist: {err.strerror or err}"
            ) from err
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    await hass.async_add_executor_job(_save)

    _LOGGER.info(
        "Imported playlist '%s' with %d songs to %s",
        name,
        len(enriched_songs),
        output_path,
    )

    enriched_count = sum(
        1 for s in enriched_songs
        if s.get("uri_youtube_music") or s.get("uri_apple_music") or s.get("uri_deezer")
    )

    # #704: do NOT leak full server filesystem path to frontend.
    return {
        "name": name,
        "slug": slug,
        "song_count": len(enriched_songs),
        "enriched_count": enriched_count,
    }
