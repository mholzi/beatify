"""Tests for MixPlaylistView (#1538 — Smart Playlist Mixer).

The mixer assembles a transient, de-duplicated song set from the existing
catalogue based on the tags the host picks, then either:

* writes it to ``<config>/beatify/playlists/mix/__mix__.json`` (transient,
  overwritten each run — fed straight into the existing start-game flow), or
* persists it to ``<config>/beatify/playlists/user/<slug>.json`` (Community tab)
  when "save as community playlist" is ticked.

These tests drive the real ``async_discover_playlists`` against on-disk fixtures
so the tag-matching + URI dedup + cap behaviour is exercised end-to-end.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import StreamReader
from aiohttp.test_utils import make_mocked_request

from custom_components.beatify.server.base import _read_file
from custom_components.beatify.server.mix_views import (
    MixPlaylistView,
    _assemble_mix_songs,
)


def _uri(tag: str) -> str:
    """Build a valid 22-char-id Spotify URI from a short tag (e.g. '0001')."""
    return "spotify:track:" + tag.rjust(22, "0")


def _song(tag: str, year: int = 1985, title: str | None = None) -> dict:
    uri = _uri(tag)
    return {
        "artist": "Artist " + tag,
        "title": title or ("Song " + tag),
        "year": year,
        "uri": uri,
    }


def _playlist(name: str, tags: list[str], songs: list[dict]) -> dict:
    return {
        "name": name,
        "version": "1.0",
        "tags": tags,
        "language": "en",
        "author": "Tester",
        "added_date": "2026-06-24",
        "description": f"{name} fixture.",
        "songs": songs,
    }


def _write_catalogue(tmp_path: Path) -> Path:
    """Lay down a small bundled-playlist catalogue and return the playlist dir."""
    pdir = tmp_path / "beatify" / "playlists"
    pdir.mkdir(parents=True)

    # 80s pop — 3 songs, one URI (track0001) shared with the 90s list below.
    (pdir / "80s-pop.json").write_text(
        json.dumps(
            _playlist(
                "80s Pop",
                ["1980s", "pop"],
                [
                    _song("0001", 1985),
                    _song("0002", 1986),
                    _song("0003", 1987),
                ],
            )
        ),
        encoding="utf-8",
    )
    # 90s pop — 2 songs, track0001 is a DUPLICATE of the 80s list.
    (pdir / "90s-pop.json").write_text(
        json.dumps(
            _playlist(
                "90s Pop",
                ["1990s", "pop"],
                [
                    _song("0001", 1985),  # dup
                    _song("0004", 1995),
                ],
            )
        ),
        encoding="utf-8",
    )
    # Rock — different tag, must NOT be pulled by a pop/decade mix.
    (pdir / "rock.json").write_text(
        json.dumps(
            _playlist(
                "Rock",
                ["1970s", "rock"],
                [_song("0009", 1975)],
            )
        ),
        encoding="utf-8",
    )
    return pdir


def _request_with_body(body: bytes):
    reader = StreamReader(
        mock.Mock(_reading_paused=False), 2**16, loop=asyncio.get_event_loop()
    )
    reader.feed_data(body)
    reader.feed_eof()
    return make_mocked_request(
        "POST",
        "/beatify/api/playlists/mix",
        headers={"Content-Type": "application/json"},
        payload=reader,
    )


def _authorized():
    return mock.patch(
        "custom_components.beatify.server.mix_views.is_authorized_http",
        new=MagicMock(return_value=True),
    )


def _view_with_catalogue(tmp_path: Path) -> MixPlaylistView:
    pdir = _write_catalogue(tmp_path)
    hass = MagicMock()
    hass.config.path = MagicMock(return_value=str(pdir))
    # Run executor jobs inline so discovery + file writes happen synchronously.
    hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *a: fn(*a))
    # async_discover_playlists uses asyncio.get_running_loop().run_in_executor;
    # under pytest-asyncio that's the running loop, fine for a default executor.
    return MixPlaylistView(hass)


# ---------------------------------------------------------------------------
# Pure assembly logic — no HA / no view, runnable standalone.
# ---------------------------------------------------------------------------
class TestAssembleMixSongs:
    def _meta(self, path: str, tags: list[str], valid: bool = True) -> dict:
        return {"path": path, "tags": tags, "is_valid": valid}

    def test_union_match_and_uri_dedup(self, tmp_path):
        pdir = _write_catalogue(tmp_path)
        meta = [
            self._meta(str(pdir / "80s-pop.json"), ["1980s", "pop"]),
            self._meta(str(pdir / "90s-pop.json"), ["1990s", "pop"]),
            self._meta(str(pdir / "rock.json"), ["1970s", "rock"]),
        ]
        # "pop" union: both pop lists match (3 + 2 songs = 5 raw), track0001 is a
        # dup → 4 unique. Rock list has no "pop" tag → excluded.
        songs, matched = _assemble_mix_songs(
            meta, {"pop"}, 100, "spotify", _read_file, pdir
        )
        assert matched == 2
        uris = {s["uri"] for s in songs}
        assert uris == {
            _uri("0001"),
            _uri("0002"),
            _uri("0003"),
            _uri("0004"),
        }
        assert len(songs) == 4  # de-duplicated

    def test_caps_at_target_count(self, tmp_path):
        pdir = _write_catalogue(tmp_path)
        meta = [
            self._meta(str(pdir / "80s-pop.json"), ["1980s", "pop"]),
            self._meta(str(pdir / "90s-pop.json"), ["1990s", "pop"]),
        ]
        songs, _ = _assemble_mix_songs(meta, {"pop"}, 2, "spotify", _read_file, pdir)
        assert len(songs) == 2  # capped below the 4 available

    def test_skips_invalid_playlists(self, tmp_path):
        pdir = _write_catalogue(tmp_path)
        meta = [
            self._meta(str(pdir / "80s-pop.json"), ["1980s", "pop"], valid=False),
        ]
        songs, matched = _assemble_mix_songs(
            meta, {"pop"}, 100, "spotify", _read_file, pdir
        )
        assert matched == 0
        assert songs == []


# ---------------------------------------------------------------------------
# Full view — exercises auth, discovery, persistence.
# ---------------------------------------------------------------------------
class TestMixPlaylistView:
    @pytest.fixture(autouse=True)
    def _allow_auth(self):
        with _authorized():
            yield

    async def test_transient_mix_writes_to_mix_subdir(self, tmp_path):
        view = _view_with_catalogue(tmp_path)
        body = json.dumps(
            {"tags": ["pop"], "target_count": 50, "provider": "spotify"}
        ).encode()
        resp = await view.post(_request_with_body(body))
        assert resp.status == 200
        data = json.loads(resp.body)
        assert data["success"] is True
        assert data["saved"] is False
        assert data["playlist_count"] == 2
        assert data["song_count"] == 4  # de-duplicated
        written = tmp_path / "beatify" / "playlists" / "mix" / "__mix__.json"
        assert written.exists()
        saved = json.loads(written.read_text())
        assert len(saved["songs"]) == 4

    async def test_save_as_community_writes_to_user_subdir(self, tmp_path):
        view = _view_with_catalogue(tmp_path)
        body = json.dumps(
            {
                "tags": ["pop"],
                "target_count": 30,
                "provider": "spotify",
                "save_as_community": True,
                "name": "Party Pop",
            }
        ).encode()
        resp = await view.post(_request_with_body(body))
        assert resp.status == 200
        data = json.loads(resp.body)
        assert data["saved"] is True
        written = tmp_path / "beatify" / "playlists" / "user" / "party-pop.json"
        assert written.exists()

    async def test_no_tags_returns_400(self, tmp_path):
        view = _view_with_catalogue(tmp_path)
        resp = await view.post(_request_with_body(json.dumps({"tags": []}).encode()))
        assert resp.status == 400
        assert json.loads(resp.body)["code"] == "NO_TAGS"

    async def test_unmatched_tags_returns_404(self, tmp_path):
        view = _view_with_catalogue(tmp_path)
        body = json.dumps({"tags": ["nonexistent-tag"]}).encode()
        resp = await view.post(_request_with_body(body))
        assert resp.status == 404
        assert json.loads(resp.body)["code"] == "EMPTY_MIX"

    async def test_invalid_json_returns_400(self, tmp_path):
        view = _view_with_catalogue(tmp_path)
        resp = await view.post(_request_with_body(b"{nope"))
        assert resp.status == 400

    async def test_unauthorized_returns_401(self, tmp_path):
        view = _view_with_catalogue(tmp_path)
        with mock.patch(
            "custom_components.beatify.server.mix_views.is_authorized_http",
            new=MagicMock(return_value=False),
        ):
            resp = await view.post(
                _request_with_body(json.dumps({"tags": ["pop"]}).encode())
            )
        assert resp.status == 401
