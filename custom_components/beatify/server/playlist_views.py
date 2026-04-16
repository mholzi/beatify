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

# #703: input length limits on credential / import endpoints.
_MAX_CLIENT_ID_LEN = 128
_MAX_CLIENT_SECRET_LEN = 256
_MAX_URL_LEN = 2048
_MAX_NAME_LEN = 200
_MAX_FILE_LEN = 300
_MAX_QUERY_LEN = 200


def _sanitize_error(message: str) -> str:
    """Strip anything that looks like a credential from an error message (#690).

    Token-validation errors can echo back Authorization headers or
    base64-encoded client_id:client_secret pairs. Deliberately does NOT
    redact URL paths (which include `/` and alphanumerics) — that just
    obscures debugging.
    """
    import re as _re
    # Authorization headers and Bearer tokens are the real credential leak vectors.
    cleaned = _re.sub(r"(?i)authorization\s*[:=]\s*\S+", "<redacted>", message)
    cleaned = _re.sub(r"(?i)bearer\s+\S+", "Bearer <redacted>", cleaned)
    # Base64-style client_id:client_secret blobs use [A-Za-z0-9+/=] — but so do
    # URLs. To avoid redacting URL paths, require the run to NOT contain `/`.
    cleaned = _re.sub(r"[A-Za-z0-9+=]{40,}", "<redacted>", cleaned)
    return cleaned


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


# -- In-process import progress tracker (#714) ------------------------------
# Stored on hass.data under DOMAIN. Not persisted — good enough for a single
# HA session. Entries: {url: {"status": "...", "pct": int, "message": str}}
_PROGRESS_KEY = "beatify.playlist_import_progress"


def _set_progress(hass: HomeAssistant, key: str, **fields: object) -> None:
    bucket = hass.data.setdefault(_PROGRESS_KEY, {})
    entry = bucket.setdefault(key, {})
    entry.update(fields)


def _get_progress(hass: HomeAssistant, key: str) -> dict | None:
    return hass.data.get(_PROGRESS_KEY, {}).get(key)


class SpotifyCredentialsView(RateLimitMixin, HomeAssistantView):
    """Save/validate Spotify API credentials (#165).

    Rate-limited (#712), input-length-limited (#703), credential-scrubbed
    error responses (#690). #689 (requires_auth) intentionally left False
    per the "Frictionless access per PRD" policy.
    """

    url = "/beatify/api/spotify-credentials"
    name = "beatify:api:spotify-credentials"
    requires_auth = False

    RATE_LIMIT_REQUESTS = 5
    RATE_LIMIT_WINDOW = 60

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass
        self._init_rate_limits()

    async def post(self, request: web.Request) -> web.Response:
        """Save and validate Spotify credentials."""
        # #712: rate-limit credential submissions.
        if not self._check_rate_limit(request.remote or "unknown"):
            return _json_error("Too many requests", 429, code="RATE_LIMITED")

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
        # #703: reject oversize inputs.
        if (
            len(client_id) > _MAX_CLIENT_ID_LEN
            or len(client_secret) > _MAX_CLIENT_SECRET_LEN
        ):
            return web.json_response(
                {"error": "Credential fields too long"}, status=413
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
        except aiohttp.ClientResponseError as err:
            # #690: log full detail server-side, return generic message.
            _LOGGER.warning("Spotify token validation failed: %s", err)
            if err.status in (400, 401):
                return web.json_response(
                    {"error": "Invalid Spotify credentials"}, status=401
                )
            return web.json_response(
                {"error": "Spotify token endpoint unreachable"}, status=502
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Credential validation failed")
            return web.json_response(
                {"error": _sanitize_error(f"Failed to validate credentials: {err}")},
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


class ImportPlaylistView(RateLimitMixin, HomeAssistantView):
    """Import a Spotify playlist (#165).

    Rate-limited (#712), input-limited (#703), progress-reportable (#714),
    duplicate-name handling (#695), friendly disk-error messages (#710).
    #689 (requires_auth) intentionally False per PRD.
    """

    url = "/beatify/api/import-playlist"
    name = "beatify:api:import-playlist"
    requires_auth = False

    RATE_LIMIT_REQUESTS = 3
    RATE_LIMIT_WINDOW = 60

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass
        self._init_rate_limits()

    async def post(self, request: web.Request) -> web.Response:
        """Import a Spotify playlist and save as Beatify JSON."""
        # #712
        if not self._check_rate_limit(request.remote or "unknown"):
            return _json_error("Too many requests", 429, code="RATE_LIMITED")

        from custom_components.beatify.services.spotify_import import (  # noqa: PLC0415
            DuplicatePlaylistError,
            PlaylistImportError,
            async_import_playlist,
        )

        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return web.json_response({"error": "Invalid JSON"}, status=400)

        spotify_url = body.get("spotify_url", "").strip()
        playlist_name = body.get("name", "").strip() or None
        overwrite = bool(body.get("overwrite", False))
        if not spotify_url:
            return web.json_response(
                {"error": "spotify_url required"}, status=400
            )
        # #703
        if len(spotify_url) > _MAX_URL_LEN:
            return web.json_response({"error": "spotify_url too long"}, status=413)
        if playlist_name and len(playlist_name) > _MAX_NAME_LEN:
            return web.json_response({"error": "name too long"}, status=413)

        # #714: minimal progress tracking — client polls GET ?url=...
        _set_progress(
            self.hass, spotify_url,
            status="in_progress", pct=0, message="Starting import…",
        )

        try:
            _set_progress(self.hass, spotify_url, pct=10, message="Fetching tracks…")
            result = await async_import_playlist(
                self.hass, spotify_url, name=playlist_name, overwrite=overwrite,
            )
        except DuplicatePlaylistError as duperr:
            _set_progress(
                self.hass, spotify_url, status="error", message=str(duperr),
            )
            return web.json_response(
                {"error": "DUPLICATE_PLAYLIST", "message": str(duperr)}, status=409,
            )
        except ValueError as err:
            _set_progress(
                self.hass, spotify_url, status="error", message=str(err),
            )
            return web.json_response({"error": str(err)}, status=400)
        except PlaylistImportError as perr:
            # #710: map disk/permission errors to friendly status codes.
            _set_progress(
                self.hass, spotify_url, status="error", message=str(perr),
            )
            msg = str(perr)
            if "Disk full" in msg:
                return web.json_response({"error": msg}, status=507)
            return web.json_response({"error": msg}, status=500)
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Playlist import failed")
            _set_progress(
                self.hass, spotify_url, status="error", message="Import failed",
            )
            return web.json_response(
                {"error": _sanitize_error(f"Import failed: {err}")}, status=500,
            )

        _set_progress(
            self.hass, spotify_url,
            status="done", pct=100, message="Import complete",
        )
        return web.json_response(result)

    async def get(self, request: web.Request) -> web.Response:
        """#714: return progress for an in-flight import.

        Query: ?url=<spotify_url>
        """
        key = request.query.get("url", "").strip()
        if not key:
            return web.json_response({"error": "url required"}, status=400)
        progress = _get_progress(self.hass, key)
        if not progress:
            return web.json_response({"status": "idle"})
        return web.json_response(progress)


class EditPlaylistView(HomeAssistantView):
    """Edit an imported playlist (PR #549). Atomic writes (#696)."""

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
        if len(filename) > _MAX_FILE_LEN:  # #703
            return web.json_response({"error": "file too long"}, status=413)

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
        if len(filename) > _MAX_FILE_LEN:  # #703
            return web.json_response({"error": "file too long"}, status=413)

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
            import os  # noqa: PLC0415
            import tempfile  # noqa: PLC0415

            file_path.parent.mkdir(parents=True, exist_ok=True)
            # #696: atomic write.
            tmp_fd, tmp_path = tempfile.mkstemp(
                dir=file_path.parent, suffix=".json.tmp",
            )
            try:
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                    json.dump(existing, f, indent=2, ensure_ascii=False)
                os.replace(tmp_path, file_path)
            except BaseException:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

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
        if len(filename) > _MAX_FILE_LEN:  # #703
            return web.json_response({"error": "file too long"}, status=413)

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
            import os  # noqa: PLC0415
            import tempfile  # noqa: PLC0415

            # #696: atomic write.
            tmp_fd, tmp_path = tempfile.mkstemp(
                dir=file_path.parent, suffix=".json.tmp",
            )
            try:
                with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2, ensure_ascii=False)
                os.replace(tmp_path, file_path)
            except BaseException:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise

        await self.hass.async_add_executor_job(_save)

        return web.json_response({
            "success": True,
            "song_count": len(songs),
        })


class SpotifySearchView(RateLimitMixin, HomeAssistantView):
    """Search Spotify for tracks (PR #549). Rate-limited (#712), input-limited (#703)."""

    url = "/beatify/api/spotify-search"
    name = "beatify:api:spotify-search"
    requires_auth = False

    RATE_LIMIT_REQUESTS = 20
    RATE_LIMIT_WINDOW = 60

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass
        self._init_rate_limits()

    async def get(self, request: web.Request) -> web.Response:
        """Search Spotify for tracks matching query."""
        # #712
        if not self._check_rate_limit(request.remote or "unknown"):
            return _json_error("Too many requests", 429, code="RATE_LIMITED")

        from custom_components.beatify.services.spotify_import import (  # noqa: PLC0415
            _safe_parse_year,
            async_fetch_spotify_token,
            async_load_credentials,
        )

        query = request.query.get("q", "").strip()
        if not query:
            return web.json_response({"error": "q parameter required"}, status=400)
        if len(query) > _MAX_QUERY_LEN:  # #703
            return web.json_response({"error": "q too long"}, status=413)

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
                year = _safe_parse_year(album.get("release_date", ""))
                spot_uri = item.get("uri", "")
                results.append({
                    "title": item["name"],
                    "artist": artists,
                    "year": year,
                    "uri": spot_uri,
                    "uri_spotify": spot_uri,  # #705
                })

            return web.json_response({"results": results})
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Spotify search failed")
            return web.json_response(
                {"error": _sanitize_error(f"Search failed: {err}")}, status=500
            )
