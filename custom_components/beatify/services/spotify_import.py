"""Spotify playlist import service for Beatify."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.util import slugify

_LOGGER = logging.getLogger(__name__)

ODESLI_BASE = "https://api.song.link/v1-alpha.1/links"
SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_API_BASE = "https://api.spotify.com/v1"
MAX_SONGS = 200


def parse_spotify_playlist_id(url: str) -> str:
    """Parse playlist ID from various Spotify URL formats."""
    # spotify:playlist:37i9dQZF1DXcBWIGoYBM5M
    if url.startswith("spotify:playlist:"):
        return url.split(":")[-1]

    # https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=xxx
    parsed = urlparse(url)
    match = re.match(r"/playlist/([a-zA-Z0-9]+)", parsed.path)
    if match:
        return match.group(1)

    raise ValueError(f"Cannot parse Spotify playlist ID from: {url}")


async def async_fetch_spotify_token(
    session: aiohttp.ClientSession,
    client_id: str,
    client_secret: str,
) -> str:
    """Fetch access token using Spotify Client Credentials flow."""
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
        return result["access_token"]


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
            release_date = album.get("release_date", "")
            year = int(release_date[:4]) if release_date and len(release_date) >= 4 else 0

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


async def async_enrich_via_odesli(
    session: aiohttp.ClientSession,
    spotify_uri: str,
) -> dict[str, str]:
    """Enrich a track with cross-platform URIs via Odesli/song.link."""
    try:
        encoded_uri = quote(spotify_uri, safe="")
        url = f"{ODESLI_BASE}?url={encoded_uri}&userCountry=US"

        async with session.get(url) as resp:
            if resp.status != 200:
                _LOGGER.debug("Odesli returned %s for %s", resp.status, spotify_uri)
                return {
                    "uri_youtube_music": "",
                    "uri_apple_music": "",
                    "uri_tidal": "",
                    "uri_deezer": "",
                }
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
        return {
            "uri_youtube_music": "",
            "uri_apple_music": "",
            "uri_tidal": "",
            "uri_deezer": "",
        }


async def async_save_credentials(
    hass: HomeAssistant, client_id: str, client_secret: str
) -> None:
    """Save Spotify credentials to disk."""
    creds_path = Path(hass.config.path("beatify/spotify_credentials.json"))

    def _write() -> None:
        creds_path.parent.mkdir(parents=True, exist_ok=True)
        creds_path.write_text(
            json.dumps({"client_id": client_id, "client_secret": client_secret}, indent=2)
        )

    await hass.async_add_executor_job(_write)


async def async_load_credentials(hass: HomeAssistant) -> dict[str, str]:
    """Load Spotify credentials from disk."""
    creds_path = Path(hass.config.path("beatify/spotify_credentials.json"))

    def _read() -> dict[str, str]:
        if not creds_path.exists():
            return {}
        return json.loads(creds_path.read_text())

    return await hass.async_add_executor_job(_read)


async def async_import_playlist(
    hass: HomeAssistant,
    spotify_url: str,
    name: str | None = None,
) -> dict[str, Any]:
    """Import a Spotify playlist and enrich with cross-platform URIs."""
    playlist_id = parse_spotify_playlist_id(spotify_url)

    credentials = await async_load_credentials(hass)
    if not credentials:
        raise ValueError("Spotify credentials not configured. Save them first.")

    client_id = credentials["client_id"]
    client_secret = credentials["client_secret"]

    semaphore = asyncio.Semaphore(1)

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
            async with semaphore:
                uris = await async_enrich_via_odesli(session, track["uri"])
                await asyncio.sleep(0.2)

            song = {
                "year": track["year"],
                "uri": track["uri"],
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
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(playlist_data, indent=2, ensure_ascii=False))

    await hass.async_add_executor_job(_save)

    _LOGGER.info(
        "Imported playlist '%s' with %d songs to %s",
        name,
        len(enriched_songs),
        output_path,
    )

    return {
        "name": name,
        "song_count": len(enriched_songs),
        "file_path": str(output_path),
    }
