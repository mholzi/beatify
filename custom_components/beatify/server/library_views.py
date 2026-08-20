"""HTTP views for the library-provider pool ("Your Library").

Two endpoints backing the admin UI's library settings panel:

  GET  /beatify/api/library-pool         -> status + stats (is a pool built?
                                            is a build running? how many songs
                                            are game-ready?)
  POST /beatify/api/library-pool/build   -> kick off a background scan+enrich.
                                            Returns immediately; the UI polls
                                            the status endpoint for progress.

The build can take many minutes (MusicBrainz is throttled to ~1 req/s), so it
runs as a background task with progress published into
hass.data[DOMAIN]["library_build"]; a synchronous HTTP response would time out
the caller and block the admin UI.
"""

from __future__ import annotations

import contextlib
import io
import json
import logging
import shutil
import time
from typing import TYPE_CHECKING, Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from custom_components.beatify.const import DOMAIN
from custom_components.beatify.library.version import __version__ as ENGINE_VERSION
from custom_components.beatify.server.base import RateLimitMixin, _json_error
from custom_components.beatify.server.companion_auth import is_authorized_http

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

_LOGGER = logging.getLogger(__name__)

_BUILD_KEY = "library_build"


_SETTINGS_STORE_KEY = "beatify.library_settings"
_SETTINGS_STORE_VERSION = 1
_LIBRARY_YEAR_GATE_NAMES = ("strict", "balanced", "tags_ok")
_LIBRARY_YEAR_GATES = {"strict": 4, "balanced": 3, "tags_ok": 2}


def sanitize_library_settings(body: Any) -> dict[str, Any]:
    """Whitelist + clamp the shared library settings. Pure.

    These are stored server-side so EVERY device sees the same values —
    per-browser localStorage caused games started from another PC to silently
    run with that PC's defaults (observed: 'Top 5%%+Dance' on one machine,
    '50%%/no genres' on another, flip-flopping between games).
    """
    if not isinstance(body, dict):
        return {}
    out: dict[str, Any] = {}
    try:
        if body.get("popularity_percent") is not None:
            out["popularity_percent"] = max(
                1, min(100, int(body["popularity_percent"]))
            )
    except (TypeError, ValueError):
        pass
    try:
        if body.get("size") is not None:
            out["size"] = max(5, min(100, int(body["size"])))
    except (TypeError, ValueError):
        pass
    gate = body.get("year_gate")
    if isinstance(gate, str) and gate in _LIBRARY_YEAR_GATE_NAMES:
        out["year_gate"] = gate
    try:
        if body.get("scan_size") is not None:
            out["scan_size"] = max(0, min(1_000_000, int(body["scan_size"])))
    except (TypeError, ValueError):
        pass
    genres = body.get("genres")
    if isinstance(genres, list):
        out["genres"] = [str(g).strip() for g in genres if str(g).strip()][:20]
    return out


_REFRESH_KEY = "library_refresh"


def _refresh_state(hass: HomeAssistant) -> dict[str, Any]:
    return hass.data.setdefault(DOMAIN, {}).setdefault(
        _REFRESH_KEY,
        {"running": False, "phase": None, "done": 0, "total": 0, "error": None},
    )


def _build_state(hass: HomeAssistant) -> dict[str, Any]:
    return hass.data.setdefault(DOMAIN, {}).setdefault(
        _BUILD_KEY,
        {"running": False, "phase": None, "done": 0, "total": 0, "error": None},
    )


class LibraryPoolStatusView(HomeAssistantView):
    """Report library-pool status: built? building? stats?"""

    url = "/beatify/api/library-pool"
    name = "beatify:api:library-pool"
    requires_auth = False  # auth handled in-handler (Companion path, #1131)

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:
        if not is_authorized_http(request, self.hass):
            return _json_error("Unauthorized", 401, code="UNAUTHORIZED")

        from custom_components.beatify.library import async_load_pool, pool_stats

        build = _build_state(self.hass)
        pool = await async_load_pool(self.hass)
        payload: dict[str, Any] = {
            "provider_version": ENGINE_VERSION,
            "built": bool(pool and pool.get("songs")),
            "building": build["running"],
            "progress": (
                {
                    "phase": build["phase"],
                    "done": build["done"],
                    "total": build["total"],
                }
                if build["running"]
                else None
            ),
            "error": build.get("error"),
        }
        if pool:
            payload["stats"] = pool_stats(pool)
            payload["built_at"] = pool.get("_built_at")
            payload["engine_version"] = pool.get("_engine_version")
            payload["track_count"] = pool.get("_track_count")
            payload["library_total"] = pool.get("_library_total")

        from custom_components.beatify.library.pool import refresh_backlog_count

        payload["last_generate"] = self.hass.data.get(DOMAIN, {}).get(
            "library_last_generate"
        )
        refresh = _refresh_state(self.hass)
        payload["refresh"] = {
            "running": refresh["running"],
            "progress": (
                {"done": refresh["done"], "total": refresh["total"]}
                if refresh["running"]
                else None
            ),
            "backlog": refresh_backlog_count(pool)["total"] if pool else 0,
            "error": refresh.get("error"),
        }
        return self.json(payload)


class LibraryPoolBuildView(HomeAssistantView):
    """Start a background library scan + enrichment."""

    url = "/beatify/api/library-pool/build"
    name = "beatify:api:library-pool:build"
    requires_auth = False  # auth handled in-handler

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def post(self, request: web.Request) -> web.Response:
        if not is_authorized_http(request, self.hass):
            return _json_error("Unauthorized", 401, code="UNAUTHORIZED")

        build = _build_state(self.hass)
        if build["running"]:
            return _json_error(
                "A library scan is already running", 409, code="BUILD_IN_PROGRESS"
            )

        try:
            body = await request.json()
        except (ValueError, UnicodeDecodeError):
            body = {}

        use_musicbrainz = bool(body.get("use_musicbrainz", True))
        year_fallback = bool(body.get("year_fallback", False))
        lastfm_api_key = body.get("lastfm_api_key") or None
        try:
            target_size = int(body.get("target_size", 2500))
        except (TypeError, ValueError):
            target_size = 2500
        # 0 = prepare the whole library (can take days on huge libraries).
        target_size = None if target_size <= 0 else max(100, target_size)

        build.update(
            {"running": True, "phase": "starting", "done": 0, "total": 0, "error": None}
        )

        def _progress(phase: str, done: int, total: int) -> None:
            build.update({"phase": phase, "done": done, "total": total})

        async def _run() -> None:
            from custom_components.beatify.library import async_build_pool

            started = time.time()
            try:
                await async_build_pool(
                    self.hass,
                    use_musicbrainz=use_musicbrainz,
                    year_fallback=year_fallback,
                    lastfm_api_key=lastfm_api_key,
                    target_size=target_size,
                    progress_cb=_progress,
                )
                _LOGGER.info(
                    "Library pool build finished in %.0fs", time.time() - started
                )
            except Exception as err:
                _LOGGER.exception("Library pool build failed")
                build["error"] = str(err)
            finally:
                build["running"] = False

        self.hass.async_create_task(_run(), name="beatify_library_pool_build")
        return self.json({"started": True})


_GAME_OUTPUT_KEY = "beatify.game_output_settings"

# Public aliases for the removal hook (#2263). The integration has to clear
# these Stores when it is deleted, and a second copy of the key strings in
# __init__.py would drift the first time one of them is renamed here.
LIBRARY_SETTINGS_STORE_KEY = _SETTINGS_STORE_KEY
LIBRARY_GAME_OUTPUT_STORE_KEY = _GAME_OUTPUT_KEY
LIBRARY_STORE_VERSION = _SETTINGS_STORE_VERSION


async def async_save_game_output_settings(
    hass: HomeAssistant, patch: dict[str, Any]
) -> None:
    """Persist device/TTS/lights so the pre-start hook can re-apply them
    server-side — the client chain (localStorage wipe on force-reset,
    token resets, page-load races) proved unreliable for the reset path."""
    from homeassistant.helpers.storage import Store

    store = Store(hass, _SETTINGS_STORE_VERSION, _GAME_OUTPUT_KEY)
    current = await store.async_load() or {}
    current.update(patch)
    await store.async_save(current)


async def async_clear_game_output_settings(hass: HomeAssistant) -> None:
    """Drop the persisted device/TTS/lights settings (force-reset path).

    Keeps our Store consistent with upstream's "reset means reset" semantics
    (4.2.0 #2036): a reset wipes the client AND the server-side setup blob, so
    our re-apply source must go with it. Any later push repopulates it.
    """
    from homeassistant.helpers.storage import Store

    store = Store(hass, _SETTINGS_STORE_VERSION, _GAME_OUTPUT_KEY)
    await store.async_save({})


async def async_load_game_output_settings(hass: HomeAssistant) -> dict[str, Any]:
    """Load the persisted device/TTS/lights settings ({} when unset)."""
    from homeassistant.helpers.storage import Store

    store = Store(hass, _SETTINGS_STORE_VERSION, _GAME_OUTPUT_KEY)
    return await store.async_load() or {}


async def async_load_library_settings(hass: HomeAssistant) -> dict[str, Any]:
    """Load the shared, server-side library settings ({} when unset)."""
    from homeassistant.helpers.storage import Store

    store = Store(hass, _SETTINGS_STORE_VERSION, _SETTINGS_STORE_KEY)
    return await store.async_load() or {}


class LibraryPoolPreviewView(HomeAssistantView):
    """Live 'how many songs match these settings' counter for the panel."""

    url = "/beatify/api/library-pool/preview"
    name = "beatify:api:library-pool:preview"
    requires_auth = False  # auth handled in-handler

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:
        if not is_authorized_http(request, self.hass):
            return _json_error("Unauthorized", 401, code="UNAUTHORIZED")
        from custom_components.beatify.library.generator import count_eligible
        from custom_components.beatify.library.pool import async_load_pool

        pool = await async_load_pool(self.hass)
        songs = (pool or {}).get("songs") or []
        try:
            pop = int(request.query.get("pop", "") or 0)
        except ValueError:
            pop = 0
        pop = max(1, min(100, pop)) if pop else None
        genres_raw = (request.query.get("genres") or "").strip()
        genres = {g.strip() for g in genres_raw.split(",") if g.strip()} or None
        gate = request.query.get("gate", "strict")
        min_conf = _LIBRARY_YEAR_GATES.get(gate, _LIBRARY_YEAR_GATES["strict"])
        n = count_eligible(
            songs,
            popularity_min_percentile=(1.0 - pop / 100.0) if pop else None,
            genres=genres,
            min_confidence=min_conf,
        )
        return self.json({"eligible": n})


class LibrarySettingsView(HomeAssistantView):
    """Shared, server-side library game settings (GET/POST).

    Stored via HA's Store helper so all devices/browsers see the same slider,
    size, gate, scan-size and genre selection.
    """

    url = "/beatify/api/library-settings"
    name = "beatify:api:library-settings"
    requires_auth = False  # auth handled in-handler

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    def _store(self) -> Any:
        from homeassistant.helpers.storage import Store

        return Store(self.hass, _SETTINGS_STORE_VERSION, _SETTINGS_STORE_KEY)

    async def get(self, request: web.Request) -> web.Response:
        if not is_authorized_http(request, self.hass):
            return _json_error("Unauthorized", 401, code="UNAUTHORIZED")
        data = await self._store().async_load()
        return self.json(data or {})

    async def post(self, request: web.Request) -> web.Response:
        if not is_authorized_http(request, self.hass):
            return _json_error("Unauthorized", 401, code="UNAUTHORIZED")
        try:
            body = await request.json()
        except ValueError:
            return _json_error("Invalid JSON", 400, code="INVALID_REQUEST")
        current = await self._store().async_load() or {}
        current.update(sanitize_library_settings(body))
        await self._store().async_save(current)
        return self.json(current)


class LibraryPoolRefreshView(HomeAssistantView):
    """Start a background REFRESH pass (re-resolve years + re-verify pop).

    Separate from the scan (v0.7.1): re-resolving a large backlog is
    MB-throttled and can take hours, so it must not hide inside a quick scan.
    Runs concurrently with a scan if desired (atomic pool writes, last write
    wins; the refresh only touches already-present entries).
    """

    url = "/beatify/api/library-pool/refresh"
    name = "beatify:api:library-pool:refresh"
    requires_auth = False  # auth handled in-handler

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def post(self, request: web.Request) -> web.Response:
        if not is_authorized_http(request, self.hass):
            return _json_error("Unauthorized", 401, code="UNAUTHORIZED")

        refresh = _refresh_state(self.hass)
        if refresh["running"]:
            return _json_error(
                "A refresh is already running", 409, code="REFRESH_IN_PROGRESS"
            )

        refresh.update(
            {"running": True, "phase": "refresh", "done": 0, "total": 0, "error": None}
        )

        def _progress(phase: str, done: int, total: int) -> None:
            refresh.update({"phase": phase, "done": done, "total": total})

        async def _run() -> None:
            from custom_components.beatify.library.pool import async_refresh_pool

            try:
                result = await async_refresh_pool(
                    self.hass, use_musicbrainz=True, progress_cb=_progress
                )
                _LOGGER.info("Library refresh finished: %s", result)
            except Exception as err:
                _LOGGER.exception("Library refresh failed")
                refresh["error"] = str(err)
            finally:
                refresh["running"] = False

        self.hass.async_create_background_task(_run(), "beatify_library_refresh")
        return self.json({"started": True})


def _resolve_pool_entry(
    hass: HomeAssistant,
    songs: list[dict[str, Any]],
    *,
    uri: str = "",
    title: str = "",
    artist: str = "",
) -> dict[str, Any] | None:
    """Find the pool entry a correction refers to.

    The reveal screen identifies a song by NAME, not URI: upstream's reveal
    payload deliberately withholds playable URIs from clients, so the host's
    screen has none either. The recently-played list (which does hold URIs,
    server-side) disambiguates when a library contains several entries with
    the same artist and title; a plain name match is the fallback.
    """
    if uri:
        return next((s_ for s_ in songs if s_.get("uri_ma_library") == uri), None)
    if not (title or artist):
        return None

    def _norm(value: Any) -> str:
        return " ".join(str(value or "").casefold().split())

    want = (_norm(artist), _norm(title))
    recent = hass.data.get(DOMAIN, {}).get("library_recent_songs", [])
    for item in recent:
        if (_norm(item.get("artist")), _norm(item.get("title"))) == want:
            match = next(
                (s_ for s_ in songs if s_.get("uri_ma_library") == item.get("uri")),
                None,
            )
            if match is not None:
                return match
    return next(
        (
            s_
            for s_ in songs
            if (_norm(s_.get("artist")), _norm(s_.get("title"))) == want
        ),
        None,
    )


class LibraryRecentSongsView(HomeAssistantView):
    """Songs from recent games, so the host can fix one after the fact.

    The reveal screen catches corrections in the moment; this catches the
    ones noticed later ("that Whitney track said 2024"). Same dialog, calmer
    moment.
    """

    url = "/beatify/api/library-pool/recent"
    name = "beatify:api:library-pool:recent"
    requires_auth = False  # auth handled in-handler

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:
        if not is_authorized_http(request, self.hass):
            return _json_error("Unauthorized", 401, code="UNAUTHORIZED")

        from custom_components.beatify.library import corrections
        from custom_components.beatify.library import pool as _pool

        recent = self.hass.data.get(DOMAIN, {}).get("library_recent_songs", [])
        if not recent:
            return web.json_response({"songs": []})

        # Report the CURRENT pool state per song: a year already corrected
        # should show as corrected, not as whatever the game played with.
        cached = await _pool.async_load_pool(self.hass)
        by_uri = {
            s_.get("uri_ma_library"): s_
            for s_ in (cached or {}).get("songs", [])
            if s_.get("uri_ma_library")
        }
        flags = self.hass.data.get(DOMAIN, {}).get("library_flags", {})
        out = []
        for item in recent[:40]:
            uri = item.get("uri")
            entry = by_uri.get(uri) or {}
            flag = flags.get(uri) or {}
            out.append(
                {
                    "uri": uri,
                    "title": entry.get("title") or item.get("title"),
                    "artist": entry.get("artist") or item.get("artist"),
                    "year": entry.get("year", item.get("year")),
                    "year_source": entry.get("year_source"),
                    "corrected": corrections.is_locked(entry) if entry else False,
                    # Players flagged this during a game — worth the host's
                    # attention first, since someone in the room heard it and
                    # disagreed with the year.
                    "flagged": int(flag.get("count") or 0),
                }
            )
        # Flagged-but-unfixed songs first: they are the ones a human already
        # noticed. Otherwise keep play order (most recent first).
        out.sort(key=lambda s_: 0 if s_["flagged"] and not s_["corrected"] else 1)
        return web.json_response({"songs": out})


class LibrarySongLookupView(HomeAssistantView):
    """Candidates for a song the host thinks is wrong.

    Answers "what did we match, and what else could this be?" — the input to
    the correction dialog. Accepts an optional corrected title/artist so the
    host can re-search under the right name when the track was misidentified
    rather than merely mis-dated.
    """

    url = "/beatify/api/library-pool/lookup"
    name = "beatify:api:library-pool:lookup"
    requires_auth = False  # auth handled in-handler (Companion path, #1131)

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def post(self, request: web.Request) -> web.Response:
        if not is_authorized_http(request, self.hass):
            return _json_error("Unauthorized", 401, code="UNAUTHORIZED")
        try:
            body = await request.json()
        except ValueError:
            return _json_error("Invalid JSON", 400, code="INVALID_REQUEST")

        uri = str(body.get("uri") or "").strip()

        from custom_components.beatify.library import corrections
        from custom_components.beatify.library import pool as _pool
        from custom_components.beatify.library.year_resolver import (
            MusicBrainzThrottle,
            async_musicbrainz_candidates,
        )

        cached = await _pool.async_load_pool(self.hass)
        entry = _resolve_pool_entry(
            self.hass,
            (cached or {}).get("songs", []),
            uri=uri,
            title=str(body.get("song_title") or ""),
            artist=str(body.get("song_artist") or ""),
        )
        if entry is None:
            return _json_error("Song not in the library pool", 404, code="NOT_FOUND")

        # Search under the corrected name when one is supplied, so a
        # misidentified track can be found under what it actually is.
        title = str(body.get("title") or entry.get("title") or "")
        artist = str(body.get("artist") or entry.get("artist") or "")

        session = async_get_clientsession(self.hass)
        throttle = MusicBrainzThrottle()
        raw = await async_musicbrainz_candidates(session, artist, title, throttle)
        ranked = corrections.rank_candidates(raw, artist=artist, title=title)

        return web.json_response(
            {
                "current": {
                    "title": entry.get("title"),
                    "artist": entry.get("artist"),
                    "album": entry.get("album"),
                    "year": entry.get("year"),
                    "year_source": entry.get("year_source"),
                    "year_confidence": entry.get("year_confidence"),
                    "genres": entry.get("genres") or [],
                    **corrections.correction_summary(entry),
                },
                "candidates": ranked,
                "searched": {"title": title, "artist": artist},
            }
        )


class LibrarySongCorrectView(HomeAssistantView):
    """Apply a host correction to one pool entry.

    The pool is the host's own data, so a wrong year is fixed here rather
    than reported to whoever published a playlist. Corrections are stored at
    USER_VERIFIED confidence and skipped by later scans and refresh passes.
    """

    url = "/beatify/api/library-pool/correct"
    name = "beatify:api:library-pool:correct"
    requires_auth = False  # auth handled in-handler

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def post(self, request: web.Request) -> web.Response:
        if not is_authorized_http(request, self.hass):
            return _json_error("Unauthorized", 401, code="UNAUTHORIZED")
        try:
            body = await request.json()
        except ValueError:
            return _json_error("Invalid JSON", 400, code="INVALID_REQUEST")

        uri = str(body.get("uri") or "").strip()

        from custom_components.beatify.library import corrections
        from custom_components.beatify.library import pool as _pool

        year, err = corrections.validate_year(body.get("year"))
        if err:
            return _json_error(err, 400, code="INVALID_REQUEST")
        title = body.get("title")
        artist = body.get("artist")
        if year is None and not title and not artist:
            return _json_error("Nothing to correct", 400, code="INVALID_REQUEST")

        cached = await _pool.async_load_pool(self.hass)
        if not cached:
            return _json_error("No library pool", 404, code="LIBRARY_POOL_MISSING")

        songs = cached.get("songs") or []
        target = _resolve_pool_entry(
            self.hass,
            songs,
            uri=uri,
            title=str(body.get("song_title") or ""),
            artist=str(body.get("song_artist") or ""),
        )
        index = (
            next((i for i, s_ in enumerate(songs) if s_ is target), None)
            if target is not None
            else None
        )
        if index is None:
            return _json_error("Song not in the library pool", 404, code="NOT_FOUND")

        updated = corrections.apply_correction(
            songs[index],
            year=year,
            title=title,
            artist=artist,
            note=body.get("note"),
        )
        songs[index] = updated
        cached["songs"] = songs
        await _pool._write_pool(self.hass, cached)

        _LOGGER.info(
            "Library correction: %s - %s -> year=%s%s",
            updated.get("artist"),
            updated.get("title"),
            updated.get("year"),
            " (identity corrected)" if updated.get("original_title") else "",
        )
        return web.json_response({"ok": True, "song": updated})


class LibraryPoolBackupView(HomeAssistantView):
    """Download the enriched pool + settings as one gzipped bundle.

    The pool costs hours of rate-limited external lookups; before this
    endpoint the only way to save it was shell access to /config. The payload
    is gzipped in an executor (a large pool compresses ~10x, and doing it on
    the event loop would stall every other HA request while it ran).
    """

    url = "/beatify/api/library-pool/backup"
    name = "beatify:api:library-pool:backup"
    requires_auth = False  # auth handled in-handler (Companion path, #1131)

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:
        if not is_authorized_http(request, self.hass):
            return _json_error("Unauthorized", 401, code="UNAUTHORIZED")

        from custom_components.beatify.library import pool as _pool
        from custom_components.beatify.library.backup import build_backup_bundle
        from custom_components.beatify.library.version import __version__

        cached = await _pool.async_load_pool(self.hass)
        if not cached:
            return _json_error(
                "No library pool to back up yet — run a scan first.",
                404,
                code="LIBRARY_POOL_MISSING",
            )
        settings = await async_load_library_settings(self.hass)
        bundle = build_backup_bundle(cached, settings, provider_version=__version__)

        def _pack() -> bytes:
            import gzip

            raw = json.dumps(bundle, ensure_ascii=False).encode("utf-8")
            return gzip.compress(raw, compresslevel=6)

        payload = await self.hass.async_add_executor_job(_pack)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        songs = len(cached.get("songs") or [])
        _LOGGER.info(
            "Library backup downloaded (%d songs, %d bytes)", songs, len(payload)
        )
        return web.Response(
            body=payload,
            headers={
                "Content-Disposition": (
                    f'attachment; filename="beatify-library-backup-{stamp}.json.gz"'
                ),
                "X-Beatify-Songs": str(songs),
            },
            content_type="application/gzip",
        )


class LibraryPoolRestoreView(HomeAssistantView):
    """Restore a pool from an uploaded bundle (replace or merge).

    Query/body ``mode``: ``replace`` (a true restore) or ``merge`` (union by
    track URI, keeping the better entry — lets a user fold a scan done
    elsewhere into the current pool without losing work).

    Safety: the current pool is copied aside before anything is written, the
    upload is size-capped in both compressed and decompressed form, and the
    merged result is re-finalized so percentiles are recomputed rather than
    carried over stale.
    """

    url = "/beatify/api/library-pool/restore"
    name = "beatify:api:library-pool:restore"
    requires_auth = False  # auth handled in-handler

    # A 300k-song pool is ~90 MB raw / ~10 MB gzipped. These caps sit well
    # above any legitimate pool while refusing decompression bombs.
    MAX_UPLOAD_BYTES = 128 * 1024 * 1024
    MAX_DECOMPRESSED_BYTES = 512 * 1024 * 1024

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def post(self, request: web.Request) -> web.Response:
        if not is_authorized_http(request, self.hass):
            return _json_error("Unauthorized", 401, code="UNAUTHORIZED")

        mode = (request.query.get("mode") or "replace").strip().lower()
        if mode not in ("replace", "merge"):
            return _json_error("Invalid restore mode", 400, code="INVALID_REQUEST")

        body = await request.read()
        if not body:
            return _json_error("Empty upload", 400, code="INVALID_REQUEST")
        if len(body) > self.MAX_UPLOAD_BYTES:
            return _json_error("Backup file too large", 413, code="TOO_LARGE")

        def _parse() -> tuple[Any, str | None]:
            import gzip

            raw = body
            if raw[:2] == b"\x1f\x8b":  # gzip magic
                try:
                    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as fh:
                        raw = fh.read(self.MAX_DECOMPRESSED_BYTES + 1)
                except OSError as err:
                    return None, f"Could not decompress backup: {err}"
                if len(raw) > self.MAX_DECOMPRESSED_BYTES:
                    return None, "Backup expands to an implausible size"
            try:
                return json.loads(raw.decode("utf-8")), None
            except (UnicodeDecodeError, json.JSONDecodeError) as err:
                return None, f"Backup file is not valid JSON: {err}"

        data, parse_err = await self.hass.async_add_executor_job(_parse)
        if parse_err:
            return _json_error(parse_err, 400, code="INVALID_BACKUP")

        from custom_components.beatify.library import pool as _pool
        from custom_components.beatify.library.backup import (
            describe_bundle,
            merge_pool_entries,
            validate_backup_bundle,
        )

        bundle, err = validate_backup_bundle(data)
        if err or bundle is None:
            return _json_error(err or "Invalid backup", 400, code="INVALID_BACKUP")

        incoming_pool = bundle["pool"]
        summary = describe_bundle(bundle)

        # Keep a copy of what we are about to overwrite. A restore is
        # destructive by definition; the user should never need our word for
        # it that the old pool is recoverable.
        path = _pool.pool_path(self.hass)
        restore_backup_name: str | None = None
        if path.exists():

            def _stash() -> str:
                stamp = time.strftime("%Y%m%d-%H%M%S")
                target = path.with_name(f"library_pool.pre-restore-{stamp}.json")
                shutil.copy2(path, target)
                return target.name

            with contextlib.suppress(OSError):
                restore_backup_name = await self.hass.async_add_executor_job(_stash)

        current = await _pool.async_load_pool(self.hass) if mode == "merge" else None
        entries, stats = merge_pool_entries(current, incoming_pool)

        # Percentiles/bands are pool-relative: re-finalize instead of trusting
        # the values that travelled in the file.
        merged = _pool.finalize_pool(
            entries,
            built_at=int(incoming_pool.get("_built_at") or time.time()),
            config_entry_id=(
                (current or {}).get("_config_entry_id")
                or incoming_pool.get("_config_entry_id")
            ),
            library_total=incoming_pool.get("_library_total")
            or (current or {}).get("_library_total"),
            target_size=incoming_pool.get("_target_size"),
        )
        await _pool._write_pool(self.hass, merged)

        # Settings ride along on a replace-restore (a fresh install should come
        # back configured), but never clobber live settings on a merge.
        settings_restored = False
        if mode == "replace" and bundle.get("settings"):
            with contextlib.suppress(Exception):
                from homeassistant.helpers.storage import Store

                store = Store(self.hass, _SETTINGS_STORE_VERSION, _SETTINGS_STORE_KEY)
                await store.async_save(sanitize_library_settings(bundle["settings"]))
                settings_restored = True

        # URIs belong to the MA server that produced them; restoring a pool
        # from a different server is allowed (playback has a name fallback)
        # but the user deserves to know why tracks might not resolve.
        from custom_components.beatify.library.ma_client import (
            find_ma_config_entry_ids,
        )

        current_entries = set(find_ma_config_entry_ids(self.hass) or [])
        source_entry = incoming_pool.get("_config_entry_id")
        foreign = bool(
            source_entry and current_entries and source_entry not in current_entries
        )

        _LOGGER.info(
            "Library pool restored (mode=%s): %d songs (+%d new, %d improved), "
            "settings_restored=%s foreign_source=%s",
            mode,
            stats["total"],
            stats["added"],
            stats["improved"],
            settings_restored,
            foreign,
        )
        return web.json_response(
            {
                "ok": True,
                "mode": mode,
                "stats": stats,
                "summary": summary,
                "settings_restored": settings_restored,
                "foreign_source": foreign,
                "previous_pool_saved_as": restore_backup_name,
            }
        )


class LibraryPoolExportView(HomeAssistantView):
    """Compact, LLM-friendly index of the usable library.

    Backing for AI curation: the admin UI embeds this index in a prompt the
    user runs in their own LLM (same trust model as the existing Playlist
    Generator, #1052 -- Beatify itself never calls an LLM). Only artist,
    title, year and fame band are exported; URIs stay server-side so there is
    nothing for a model to hallucinate against.
    """

    url = "/beatify/api/library-pool/export"
    name = "beatify:api:library-pool:export"
    requires_auth = False  # auth handled in-handler (Companion path, #1131)

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:
        if not is_authorized_http(request, self.hass):
            return _json_error("Unauthorized", 401, code="UNAUTHORIZED")

        from custom_components.beatify.library import async_load_pool
        from custom_components.beatify.library.matcher import build_export_index

        pool = await async_load_pool(self.hass)
        if not pool or not pool.get("songs"):
            return _json_error(
                "Library not scanned yet", 400, code="LIBRARY_POOL_MISSING"
            )

        try:
            limit = int(request.query.get("limit", "2000"))
        except ValueError:
            limit = 2000
        limit = max(1, min(5000, limit))
        return self.json(build_export_index(pool["songs"], limit=limit))


class LibraryPlaylistResolveView(RateLimitMixin, HomeAssistantView):
    """Resolve {artist,title} picks against the pool into a playable playlist.

    The counterpart of the export view: an LLM's (or a human's) picks come
    back as plain artist/title pairs; this endpoint attaches the verified year
    and uri_ma_library from the pool, and reports unmatched picks per row.
    The client then saves the returned playlist through the existing
    SavePlaylistView so all user playlists share one write path.
    """

    url = "/beatify/api/library-playlists/resolve"
    name = "beatify:api:library-playlists:resolve"
    requires_auth = False  # auth handled in-handler

    RATE_LIMIT_MAX_REQUESTS = 30
    RATE_LIMIT_WINDOW = 60
    MAX_PICKS = 300

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._init_rate_limits()

    async def post(self, request: web.Request) -> web.Response:
        if not is_authorized_http(request, self.hass):
            return _json_error("Unauthorized", 401, code="UNAUTHORIZED")
        client_ip = request.remote or "unknown"
        if not self._check_rate_limit(client_ip):
            return _json_error("Too many requests", 429, code="RATE_LIMITED")

        try:
            body = await request.json()
        except (ValueError, UnicodeDecodeError):
            return _json_error("Invalid JSON", 400, code="INVALID_REQUEST")
        if not isinstance(body, dict):
            return _json_error("Invalid request body", 400, code="INVALID_REQUEST")

        picks = body.get("picks")
        if not isinstance(picks, list) or not picks:
            return _json_error("Missing 'picks' list", 400, code="INVALID_REQUEST")
        if len(picks) > self.MAX_PICKS:
            return _json_error(
                f"Too many picks (max {self.MAX_PICKS})", 400, code="TOO_LARGE"
            )
        name = body.get("name")
        if not isinstance(name, str) or not name.strip():
            name = "Crate Digger Selection"

        from custom_components.beatify.library import async_load_pool
        from custom_components.beatify.library.matcher import (
            build_pool_index,
            resolve_picks,
        )

        pool = await async_load_pool(self.hass)
        if not pool or not pool.get("songs"):
            return _json_error(
                "Library not scanned yet", 400, code="LIBRARY_POOL_MISSING"
            )

        index = build_pool_index(pool["songs"])
        songs, unmatched = resolve_picks(picks, index)
        playlist = {
            "name": name.strip()[:100],
            "version": "1.0",
            "_generated": True,
            "tags": ["library", "curated"],
            "songs": songs,
        }
        return self.json(
            {"playlist": playlist, "matched": len(songs), "unmatched": unmatched}
        )


class LibraryPlaylistGenerateView(RateLimitMixin, HomeAssistantView):
    """Generate a fresh mix from the pool and save it as a user playlist.

    One-click "keep this mix": same sampling engine as game start, but the
    result is written to <config>/beatify/playlists/user/ (shared writer, so
    slugging/non-clobbering match SavePlaylistView) and appears in the Mine
    tab where it can be re-played, shared, or deleted.
    """

    url = "/beatify/api/library-playlists/generate"
    name = "beatify:api:library-playlists:generate"
    requires_auth = False  # auth handled in-handler

    RATE_LIMIT_MAX_REQUESTS = 15
    RATE_LIMIT_WINDOW = 60

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._init_rate_limits()

    async def post(self, request: web.Request) -> web.Response:
        if not is_authorized_http(request, self.hass):
            return _json_error("Unauthorized", 401, code="UNAUTHORIZED")
        client_ip = request.remote or "unknown"
        if not self._check_rate_limit(client_ip):
            return _json_error("Too many requests", 429, code="RATE_LIMITED")

        try:
            body = await request.json()
        except (ValueError, UnicodeDecodeError):
            body = {}
        if not isinstance(body, dict):
            body = {}

        from custom_components.beatify.library import (
            async_generate_library_playlist,
        )
        from custom_components.beatify.server.game_views import (
            _parse_library_config,
        )
        from custom_components.beatify.server.playlist_views import (
            write_user_playlist,
        )

        size, slider, min_confidence = _parse_library_config(body)
        playlist = await async_generate_library_playlist(
            self.hass,
            size=size,
            difficulty_slider=slider,
            min_confidence=min_confidence,
        )
        if playlist is None:
            return _json_error(
                "Library not scanned yet", 400, code="LIBRARY_POOL_MISSING"
            )
        if not playlist.get("songs"):
            return _json_error(
                "No songs meet the current year-accuracy setting",
                400,
                code="LIBRARY_POOL_EMPTY",
            )

        name = body.get("name")
        if isinstance(name, str) and name.strip():
            playlist["name"] = name.strip()[:100]

        try:
            written = await write_user_playlist(self.hass, playlist)
        except OSError as err:
            _LOGGER.error("Failed to save generated playlist: %s", err)
            return _json_error("Failed to save playlist", 500, code="SAVE_FAILED")

        return self.json(
            {
                "saved": True,
                "filename": written.name,
                "name": playlist["name"],
                "songs": len(playlist["songs"]),
            }
        )
