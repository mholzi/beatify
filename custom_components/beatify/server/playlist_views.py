"""Playlist-related HTTP views for Beatify."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from custom_components.beatify.game.playlist import async_discover_playlists
from custom_components.beatify.server.base import (
    RateLimitMixin,
    _json_error,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class PlaylistRequestsView(RateLimitMixin, HomeAssistantView):
    """API for managing playlist requests (Story 44).

    Stores requests in a JSON file on the HA server so they persist
    across browser sessions and devices.
    """

    url = "/beatify/api/playlist-requests"
    name = "beatify:api:playlist-requests"
    requires_auth = False

    MAX_REQUESTS = 100
    MAX_FIELD_LENGTH = 500
    RATE_LIMIT_REQUESTS = 10
    RATE_LIMIT_WINDOW = 60  # seconds

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass
        self._storage_path = Path(hass.config.path("beatify/playlist_requests.json"))
        self._init_rate_limits()

    def _sanitize_item(self, item: object) -> dict | None:
        """Validate and sanitize a single playlist request item."""
        if not isinstance(item, dict):
            return None
        sanitized = {}
        for key, value in item.items():
            if not isinstance(key, str) or len(key) > 50:
                continue
            if isinstance(value, str):
                sanitized[key] = value[: self.MAX_FIELD_LENGTH]
            elif isinstance(value, (int, float, bool)):
                sanitized[key] = value
        return sanitized if sanitized else None

    def _load_requests(self) -> dict:
        """Load requests from storage file."""
        if self._storage_path.exists():
            try:
                return json.loads(self._storage_path.read_text(encoding="utf-8"))
            except Exception as e:  # noqa: BLE001
                _LOGGER.error("Failed to load playlist requests: %s", e)
        return {"requests": [], "last_poll": None}

    def _save_requests(self, data: dict) -> bool:
        """Save requests to storage file."""
        try:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            self._storage_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            return True
        except Exception as e:  # noqa: BLE001
            _LOGGER.error("Failed to save playlist requests: %s", e)
            return False

    async def get(self, request: web.Request) -> web.Response:  # noqa: ARG002
        """Get all playlist requests."""
        data = await self.hass.async_add_executor_job(self._load_requests)
        return web.json_response(data)

    async def post(self, request: web.Request) -> web.Response:
        """Save playlist requests (replaces all data)."""
        # Rate limiting
        client_ip = request.remote or "unknown"
        if not self._check_rate_limit(client_ip):
            return _json_error("Too many requests", 429, code="RATE_LIMITED")

        try:
            body = await request.json(content_type=None)
        except Exception:  # noqa: BLE001
            return _json_error("Invalid JSON", 400, code="INVALID_REQUEST")

        # Validate data structure
        if not isinstance(body.get("requests"), list):
            return _json_error("Missing or invalid requests array", 400, code="INVALID_REQUEST")

        raw_requests = body["requests"][: self.MAX_REQUESTS]

        # Sanitize each item
        sanitized = []
        for item in raw_requests:
            clean = self._sanitize_item(item)
            if clean is not None:
                sanitized.append(clean)

        # Build storage object
        data = {
            "requests": sanitized,
            "last_poll": body.get("last_poll"),
        }

        # Save to file
        success = await self.hass.async_add_executor_job(self._save_requests, data)
        if not success:
            return _json_error("Failed to save request", 500, code="SAVE_FAILED")

        return web.json_response({"success": True, "requests": data["requests"]})


class SpotifyCredentialsView(HomeAssistantView):
    """Save/validate Spotify API credentials (#165)."""

    url = "/beatify/api/spotify-credentials"
    name = "beatify:api:spotify-credentials"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass

    async def post(self, request: web.Request) -> web.Response:
        """Save and validate Spotify credentials."""
        from custom_components.beatify.services.spotify_import import (  # noqa: PLC0415
            async_fetch_spotify_token,
            async_save_credentials,
        )

        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return web.json_response({"error": "Invalid JSON"}, status=400)

        client_id = body.get("client_id", "").strip()
        client_secret = body.get("client_secret", "").strip()
        if not client_id or not client_secret:
            return web.json_response(
                {"error": "client_id and client_secret required"}, status=400
            )

        # Validate by attempting to fetch a token
        import aiohttp  # noqa: PLC0415

        try:
            async with aiohttp.ClientSession() as session:
                token = await async_fetch_spotify_token(session, client_id, client_secret)
                if not token:
                    return web.json_response(
                        {"error": "Invalid credentials — Spotify rejected the token request"},
                        status=401,
                    )
        except Exception as err:  # noqa: BLE001
            return web.json_response(
                {"error": f"Failed to validate credentials: {err}"},
                status=500,
            )

        await async_save_credentials(self.hass, client_id, client_secret)
        return web.json_response({"success": True})

    async def get(self, request: web.Request) -> web.Response:  # noqa: ARG002
        """Check if credentials are configured."""
        from custom_components.beatify.services.spotify_import import (  # noqa: PLC0415
            async_load_credentials,
        )

        creds = await async_load_credentials(self.hass)
        return web.json_response({"configured": creds is not None})


class ImportPlaylistView(HomeAssistantView):
    """Import a Spotify playlist (#165)."""

    url = "/beatify/api/import-playlist"
    name = "beatify:api:import-playlist"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass

    async def post(self, request: web.Request) -> web.Response:
        """Import a Spotify playlist and save as Beatify JSON."""
        from custom_components.beatify.services.spotify_import import (  # noqa: PLC0415
            async_import_playlist,
        )

        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return web.json_response({"error": "Invalid JSON"}, status=400)

        spotify_url = body.get("spotify_url", "").strip()
        playlist_name = body.get("name", "").strip() or None
        if not spotify_url:
            return web.json_response(
                {"error": "spotify_url required"}, status=400
            )

        try:
            result = await async_import_playlist(
                self.hass, spotify_url, name=playlist_name
            )
            return web.json_response(result)
        except ValueError as err:
            return web.json_response({"error": str(err)}, status=400)
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Playlist import failed")
            return web.json_response(
                {"error": f"Import failed: {err}"}, status=500
            )


class EditPlaylistView(HomeAssistantView):
    """Edit an imported playlist (PR #549)."""

    url = "/beatify/api/edit-playlist"
    name = "beatify:api:edit-playlist"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:
        """Return playlist JSON for the given filename."""
        filename = request.query.get("file", "").strip()
        if not filename:
            return web.json_response({"error": "file parameter required"}, status=400)

        playlist_dir = Path(self.hass.config.path("beatify/playlists"))
        file_path = playlist_dir / filename

        # Prevent path traversal
        try:
            file_path = file_path.resolve()
            playlist_dir_resolved = playlist_dir.resolve()
            if not file_path.is_relative_to(playlist_dir_resolved):
                return web.json_response({"error": "Invalid file path"}, status=400)
        except Exception:  # noqa: BLE001
            return web.json_response({"error": "Invalid file path"}, status=400)

        def _read() -> dict | None:
            if not file_path.exists():
                return None
            return json.loads(file_path.read_text(encoding="utf-8"))

        data = await self.hass.async_add_executor_job(_read)
        if data is None:
            return web.json_response({"error": "Playlist not found"}, status=404)

        return web.json_response({
            "file": filename,
            "name": data.get("name", ""),
            "tags": data.get("tags", []),
            "songs": data.get("songs", []),
        })

    async def post(self, request: web.Request) -> web.Response:
        """Save updated playlist data."""
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return web.json_response({"error": "Invalid JSON"}, status=400)

        filename = body.get("file", "").strip()
        if not filename:
            return web.json_response({"error": "file required"}, status=400)

        playlist_dir = Path(self.hass.config.path("beatify/playlists"))
        file_path = playlist_dir / filename

        # Prevent path traversal
        try:
            file_path = file_path.resolve()
            playlist_dir_resolved = playlist_dir.resolve()
            if not file_path.is_relative_to(playlist_dir_resolved):
                return web.json_response({"error": "Invalid file path"}, status=400)
        except Exception:  # noqa: BLE001
            return web.json_response({"error": "Invalid file path"}, status=400)

        # Read existing data to preserve version and other fields
        def _read_existing() -> dict:
            if file_path.exists():
                return json.loads(file_path.read_text(encoding="utf-8"))
            return {}

        existing = await self.hass.async_add_executor_job(_read_existing)

        # Update fields
        existing["name"] = body.get("name", existing.get("name", ""))
        existing["tags"] = body.get("tags", existing.get("tags", []))
        existing["songs"] = body.get("songs", existing.get("songs", []))

        def _save() -> None:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(
                json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8"
            )

        await self.hass.async_add_executor_job(_save)

        # Refresh playlist discovery so changes appear immediately
        await async_discover_playlists(self.hass)

        return web.json_response({"success": True})

    async def delete(self, request: web.Request) -> web.Response:
        """Remove a song by index from a playlist."""
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return web.json_response({"error": "Invalid JSON"}, status=400)

        filename = body.get("file", "").strip()
        remove_index = body.get("remove_index")
        if not filename or remove_index is None:
            return web.json_response(
                {"error": "file and remove_index required"}, status=400
            )

        playlist_dir = Path(self.hass.config.path("beatify/playlists"))
        file_path = playlist_dir / filename

        # Prevent path traversal
        try:
            file_path = file_path.resolve()
            playlist_dir_resolved = playlist_dir.resolve()
            if not file_path.is_relative_to(playlist_dir_resolved):
                return web.json_response({"error": "Invalid file path"}, status=400)
        except Exception:  # noqa: BLE001
            return web.json_response({"error": "Invalid file path"}, status=400)

        def _read() -> dict | None:
            if not file_path.exists():
                return None
            return json.loads(file_path.read_text(encoding="utf-8"))

        data = await self.hass.async_add_executor_job(_read)
        if data is None:
            return web.json_response({"error": "Playlist not found"}, status=404)

        songs = data.get("songs", [])
        try:
            idx = int(remove_index)
        except (ValueError, TypeError):
            return web.json_response({"error": "Invalid remove_index"}, status=400)
        if idx < 0 or idx >= len(songs):
            return web.json_response({"error": "Index out of range"}, status=400)

        songs.pop(idx)
        data["songs"] = songs

        def _save() -> None:
            file_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )

        await self.hass.async_add_executor_job(_save)

        return web.json_response({
            "success": True,
            "song_count": len(songs),
        })


class SpotifySearchView(HomeAssistantView):
    """Search Spotify for tracks (PR #549)."""

    url = "/beatify/api/spotify-search"
    name = "beatify:api:spotify-search"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:
        """Search Spotify for tracks matching query."""
        from custom_components.beatify.services.spotify_import import (  # noqa: PLC0415
            async_fetch_spotify_token,
            async_load_credentials,
        )

        query = request.query.get("q", "").strip()
        if not query:
            return web.json_response({"error": "q parameter required"}, status=400)

        credentials = await async_load_credentials(self.hass)
        if not credentials:
            return web.json_response(
                {"error": "Spotify credentials not configured"}, status=400
            )

        import aiohttp  # noqa: PLC0415

        try:
            async with aiohttp.ClientSession() as session:
                token = await async_fetch_spotify_token(
                    session,
                    credentials["client_id"],
                    credentials["client_secret"],
                )

                from urllib.parse import quote  # noqa: PLC0415

                encoded_q = quote(query)
                url = (
                    f"https://api.spotify.com/v1/search"
                    f"?q={encoded_q}&type=track&limit=5"
                )
                headers = {"Authorization": f"Bearer {token}"}

                async with session.get(url, headers=headers) as resp:
                    if resp.status != 200:
                        return web.json_response(
                            {"error": "Spotify search failed"}, status=502
                        )
                    data = await resp.json()

            results = []
            for item in data.get("tracks", {}).get("items", []):
                artists = ", ".join(a["name"] for a in item.get("artists", []))
                album = item.get("album", {})
                release_date = album.get("release_date", "")
                year = (
                    int(release_date[:4])
                    if release_date and len(release_date) >= 4
                    else 0
                )
                results.append({
                    "title": item["name"],
                    "artist": artists,
                    "year": year,
                    "uri": item.get("uri", ""),
                })

            return web.json_response({"results": results})
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Spotify search failed")
            return web.json_response(
                {"error": f"Search failed: {err}"}, status=500
            )
