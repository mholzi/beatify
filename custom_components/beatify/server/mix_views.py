"""Smart Playlist Mixer HTTP view for Beatify (#1538).

Assembles a transient, de-duplicated song set on the fly from the existing
playlist catalogue based on the tags the host picks in the "Mix" tab
(decade / style / region / special — the same taxonomy that already drives the
playlist filter bar, see ``www/js/admin/constants.js`` ``TAG_CATEGORIES``).

Design goals (kept deliberately minimal-invasive):

* No new game-start path. The mixer writes the assembled set to a playlist
  JSON on disk and returns its ``path``; the frontend then feeds that path into
  the *existing* ``/beatify/api/start-game`` flow exactly like any hand-picked
  playlist. So all the validated start-game logic (provider checks, platform
  capabilities, PlaylistManager dedup/selection) is reused untouched.
* Transient mixes land in ``<config>/beatify/playlists/mix/__mix__.json`` and
  are overwritten on every run — they are an implementation detail, not a
  saved artefact. The ``mix/`` folder is treated as ``bundled`` by discovery
  (only ``community``/``user`` count as community), so a transient mix never
  pollutes the Community tab.
* When the host ticks "save as community playlist" the assembled set is instead
  persisted into ``user/<slug>.json`` (the same place ``SavePlaylistView`` uses)
  so ``async_discover_playlists`` surfaces it in the Community tab on refresh.
"""

from __future__ import annotations

import json
import logging
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from custom_components.beatify.const import PROVIDER_DEFAULT
from custom_components.beatify.game.playlist import (
    async_discover_playlists,
    get_playlist_directory,
    get_song_uri,
    validate_playlist,
)
from custom_components.beatify.server.base import (
    RateLimitMixin,
    _json_error,
    _read_file,
)
from custom_components.beatify.server.companion_auth import is_authorized_http
from custom_components.beatify.server.playlist_views import _slugify_playlist_name

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Allowed target song counts — must mirror the segmented control in the Mix tab
# (admin.html: 30 / 50 / 100). Anything else is coerced to the default.
ALLOWED_TARGET_COUNTS = (30, 50, 100)
DEFAULT_TARGET_COUNT = 50

# Upper bound on tags accepted per request (cheap DoS guard; the real taxonomy
# is far smaller).
MAX_TAGS = 40

# Filename stem for the transient (non-saved) mix. Overwritten every run.
TRANSIENT_MIX_STEM = "__mix__"


def _assemble_mix_songs(
    playlists_meta: list[dict[str, Any]],
    selected_tags: set[str],
    target_count: int,
    provider: str,
    read_file,
    playlist_dir: Path,
) -> tuple[list[dict[str, Any]], int]:
    """Collect, de-dupe and cap candidate songs from tag-matching playlists.

    A playlist matches if ANY of its tags is in ``selected_tags`` (union
    semantics): "80s + 90s pop" should pull from every playlist touching the
    80s, the 90s OR pop, then dedupe. Songs are de-duplicated by their
    provider-resolved URI (``get_song_uri``) — the same key the in-game
    PlaylistManager uses — then shuffled and capped at ``target_count``.

    Returns ``(songs, matched_playlist_count)``.
    """
    candidates: list[dict[str, Any]] = []
    matched = 0

    for meta in playlists_meta:
        if not meta.get("is_valid"):
            continue
        tags = set(meta.get("tags") or [])
        if not (tags & selected_tags):
            continue
        # Never re-mix a previous transient mix into a new one.
        path = meta.get("path") or ""
        if Path(path).name == f"{TRANSIENT_MIX_STEM}.json":
            continue

        full_path = Path(path)
        try:
            data = json.loads(read_file(full_path))
        except (OSError, ValueError) as err:  # pragma: no cover - I/O edge
            _LOGGER.debug("Mix: skipping unreadable playlist %s: %s", path, err)
            continue

        matched += 1
        for song in data.get("songs", []):
            if not isinstance(song, dict):
                continue
            # Must have a year and at least one usable URI for the selected
            # provider — otherwise it can never play and only wastes a slot.
            if "year" not in song:
                continue
            if not get_song_uri(song, provider):
                continue
            candidates.append(song)

    # De-dupe by provider-resolved URI (mirrors PlaylistManager.__init__).
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for song in candidates:
        uri = get_song_uri(song, provider)
        if not uri or uri in seen:
            continue
        seen.add(uri)
        unique.append(song)

    # Shuffle so repeated mixes with the same tags feel fresh, then cap. We keep
    # the FULL original song dicts (all uri_* fields, alt_artists, fun_fact, …)
    # so the assembled playlist passes validate_playlist and plays on every
    # provider — not just the one previewed.
    random.shuffle(unique)
    if len(unique) > target_count:
        unique = unique[:target_count]
    return unique, matched


class MixPlaylistView(RateLimitMixin, HomeAssistantView):
    """Assemble a Smart Playlist Mix from decade/style/region/special tags.

    POST body:
        {
            "tags": ["1980s", "1990s", "pop"],   # flat list across categories
            "target_count": 50,                   # 30 | 50 | 100
            "provider": "spotify",                # resolve URIs / dedup per provider
            "save_as_community": false,           # persist to Community tab
            "name": "Party Mix"                   # only used when saving
        }

    Response:
        {
            "success": true,
            "path": "<abs path under beatify/playlists/...>",
            "filename": "__mix__.json",
            "name": "Smart Mix · 80s, 90s, Pop",
            "song_count": 50,
            "playlist_count": 6,
            "saved": false
        }

    The returned ``path`` is fed straight into ``/beatify/api/start-game`` by
    the frontend, so no game-start logic is duplicated here.
    """

    url = "/beatify/api/playlists/mix"
    name = "beatify:api:playlists:mix"
    requires_auth = False

    RATE_LIMIT_REQUESTS = 20
    RATE_LIMIT_WINDOW = 60

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass
        self._init_rate_limits()

    async def post(self, request: web.Request) -> web.Response:
        """Assemble (and optionally persist) a tag-based mix."""
        # Same auth gate as SavePlaylistView/StartGameView: this endpoint reads
        # the whole catalogue and can write a file to the HA config volume.
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

        # --- Validate tags -------------------------------------------------
        raw_tags = body.get("tags", [])
        if not isinstance(raw_tags, list):
            return _json_error("'tags' must be an array", 400, code="INVALID_REQUEST")
        selected_tags = {
            t.strip() for t in raw_tags if isinstance(t, str) and t.strip()
        }
        if not selected_tags:
            return _json_error("No tags selected", 400, code="NO_TAGS")
        if len(selected_tags) > MAX_TAGS:
            return _json_error("Too many tags", 400, code="INVALID_REQUEST")

        # --- Validate target count ----------------------------------------
        target_count = body.get("target_count", DEFAULT_TARGET_COUNT)
        try:
            target_count = int(target_count)
        except (ValueError, TypeError):
            target_count = DEFAULT_TARGET_COUNT
        if target_count not in ALLOWED_TARGET_COUNTS:
            target_count = DEFAULT_TARGET_COUNT

        provider = body.get("provider") or PROVIDER_DEFAULT
        if not isinstance(provider, str):
            provider = PROVIDER_DEFAULT
        save_as_community = bool(body.get("save_as_community", False))

        # --- Discover + assemble ------------------------------------------
        playlists_meta = await async_discover_playlists(self.hass)
        playlist_dir = get_playlist_directory(self.hass)

        songs, matched = await self.hass.async_add_executor_job(
            _assemble_mix_songs,
            playlists_meta,
            selected_tags,
            target_count,
            provider,
            _read_file,
            playlist_dir,
        )

        if not songs:
            return _json_error(
                "No songs match the selected tags for this provider",
                404,
                code="EMPTY_MIX",
            )

        # --- Build the playlist document ----------------------------------
        # Title: human-readable list of the chosen tags (capitalised, deduped),
        # e.g. "Smart Mix · 1980s, 1990s, Pop".
        pretty = ", ".join(t[:1].upper() + t[1:] for t in sorted(selected_tags))
        playlist_name = (body.get("name") or f"Smart Mix · {pretty}").strip()[:120]

        playlist_doc: dict[str, Any] = {
            "name": playlist_name,
            "version": "1.0",
            "tags": sorted(selected_tags),
            "author": "Smart Playlist Mixer",
            "added_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "description": (
                f"Auto-assembled mix · {len(songs)} songs from "
                f"{matched} playlist(s), de-duplicated by URI."
            ),
            "songs": songs,
        }

        # Safety net: the source songs were already validated on discovery, but
        # re-validate the assembled doc so a malformed catalogue can never feed
        # start-game a broken playlist.
        is_valid, errors = validate_playlist(playlist_doc)
        if not is_valid:
            _LOGGER.warning("Mix produced an invalid playlist: %s", errors[:5])
            return _json_error(
                "Assembled mix failed validation",
                500,
                code="MIX_INVALID",
            )

        # --- Persist ------------------------------------------------------
        def _write_transient() -> Path:
            mix_dir = playlist_dir / "mix"
            mix_dir.mkdir(parents=True, exist_ok=True)
            target = mix_dir / f"{TRANSIENT_MIX_STEM}.json"
            target.write_text(
                json.dumps(playlist_doc, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            return target

        def _write_community() -> Path:
            slug = _slugify_playlist_name(playlist_name)
            user_dir = playlist_dir / "user"
            user_dir.mkdir(parents=True, exist_ok=True)
            final = user_dir / f"{slug}.json"
            counter = 2
            while final.exists():
                final = user_dir / f"{slug}-{counter}.json"
                counter += 1
            final.write_text(
                json.dumps(playlist_doc, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            return final

        try:
            writer = _write_community if save_as_community else _write_transient
            written = await self.hass.async_add_executor_job(writer)
        except OSError as err:
            _LOGGER.error("Failed to write mix playlist: %s", err)
            return _json_error("Failed to save mix", 500, code="SAVE_FAILED")

        return web.json_response(
            {
                "success": True,
                "path": str(written),
                "filename": written.name,
                "name": playlist_name,
                "song_count": len(songs),
                "playlist_count": matched,
                "saved": save_as_community,
            }
        )
