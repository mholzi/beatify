"""Tests for SavePlaylistView (#1057).

Save locally writes a generator-produced playlist JSON to
``<config>/beatify/playlists/user/<slug>.json``. The user/ subfolder is
deliberately distinct from community/ so the bundled-copy path that runs on
every HACS update never touches user-saved files (the bundled tree has no
user/ directory to copy from).

The discovery loader maps both community/ and user/ files to
``source: "community"`` so the Playlist Hub Community tab shows everything in
one place.
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

from custom_components.beatify.game.playlist import async_discover_playlists
from custom_components.beatify.server.playlist_views import (
    SavePlaylistView,
    _slugify_playlist_name,
)


GOLD_SONG = {
    "artist": "U96",
    "title": "Das Boot",
    "year": 1991,
    "isrc": "DEPI81403435",
    "uri": "spotify:track:5A3IdgGphzKS2etiGFB73S",
    "uri_apple_music": "applemusic://track/965771834",
    "uri_youtube_music": "https://music.youtube.com/watch?v=0snTYLgg9w0",
    "uri_deezer": "deezer://track/94877938",
}


def _valid_playlist(name: str = "My Test Mix") -> dict:
    return {
        "name": name,
        "version": "1.0",
        "tags": ["test"],
        "language": "en",
        "author": "Tester",
        "added_date": "2026-05-20",
        "description": "Generator output for tests.",
        "songs": [dict(GOLD_SONG)],
    }


def _request_with_body(body: bytes):
    """Build a POST request whose real `.json()` will read `body`."""
    reader = StreamReader(
        mock.Mock(_reading_paused=False), 2**16, loop=asyncio.get_event_loop()
    )
    reader.feed_data(body)
    reader.feed_eof()
    return make_mocked_request(
        "POST",
        "/beatify/api/playlists/save",
        headers={"Content-Type": "application/json"},
        payload=reader,
    )


def _authorized():
    """Patch is_authorized_http to allow the POST through (#1368)."""
    return mock.patch(
        "custom_components.beatify.server.playlist_views.is_authorized_http",
        new=MagicMock(return_value=True),
    )


def _view_with_tmp_config(tmp_path: Path) -> SavePlaylistView:
    hass = MagicMock()
    # get_playlist_directory resolves to <config>/beatify/playlists.
    hass.config.path = MagicMock(return_value=str(tmp_path / "beatify" / "playlists"))
    # Run executor jobs inline so the file actually lands on disk during the test.
    hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *args: fn(*args))
    return SavePlaylistView(hass)


class TestSlugify:
    """The server-side slug must match what the generator JS would have produced."""

    def test_basic_lowercase_and_dashes(self):
        assert _slugify_playlist_name("My Test Mix") == "my-test-mix"

    def test_strips_diacritics(self):
        assert _slugify_playlist_name("Übermenschliche Hits") == "ubermenschliche-hits"

    def test_collapses_punctuation(self):
        assert _slugify_playlist_name("70's & 80's: Greatest!") == "70-s-80-s-greatest"

    def test_empty_falls_back_to_placeholder(self):
        assert _slugify_playlist_name("") == "untitled-playlist"
        assert _slugify_playlist_name("   ") == "untitled-playlist"

    def test_trims_to_60_chars(self):
        long_name = "A" * 200
        assert len(_slugify_playlist_name(long_name)) == 60


class TestSavePlaylistView:
    @pytest.fixture(autouse=True)
    def _allow_auth(self):
        # #1368: post() now gates on is_authorized_http before any disk work.
        # These cases exercise the validation/persistence path, so authorize them.
        with _authorized():
            yield

    async def test_valid_payload_writes_to_user_subdir(self, tmp_path):
        view = _view_with_tmp_config(tmp_path)
        body = json.dumps({"playlist": _valid_playlist("My Mix")}).encode()
        resp = await view.post(_request_with_body(body))
        assert resp.status == 200
        data = json.loads(resp.body)
        assert data["success"] is True
        assert data["filename"] == "my-mix.json"
        # File must land under user/, not community/ — that's the HACS-safety
        # invariant: _copy_bundled_playlists has no user/ source to overwrite from.
        written = tmp_path / "beatify" / "playlists" / "user" / "my-mix.json"
        assert written.exists()
        saved = json.loads(written.read_text())
        assert saved["name"] == "My Mix"

    async def test_invalid_json_body_returns_400(self, tmp_path):
        view = _view_with_tmp_config(tmp_path)
        resp = await view.post(_request_with_body(b"{not valid json"))
        assert resp.status == 400
        assert json.loads(resp.body)["error"] == "INVALID_REQUEST"

    async def test_missing_playlist_object_returns_400(self, tmp_path):
        view = _view_with_tmp_config(tmp_path)
        resp = await view.post(_request_with_body(b'{"playlist": "not an object"}'))
        assert resp.status == 400
        assert json.loads(resp.body)["error"] == "INVALID_REQUEST"

    async def test_validation_failure_returns_400(self, tmp_path):
        view = _view_with_tmp_config(tmp_path)
        bad = {"name": "Broken", "songs": [{"title": "no uri"}]}
        resp = await view.post(
            _request_with_body(json.dumps({"playlist": bad}).encode())
        )
        assert resp.status == 400
        assert json.loads(resp.body)["error"] == "INVALID_PLAYLIST"

    async def test_slug_collision_picks_unique_name(self, tmp_path):
        view = _view_with_tmp_config(tmp_path)
        body = json.dumps({"playlist": _valid_playlist("Same Name")}).encode()

        resp1 = await view.post(_request_with_body(body))
        resp2 = await view.post(_request_with_body(body))

        assert resp1.status == 200
        assert resp2.status == 200
        assert json.loads(resp1.body)["filename"] == "same-name.json"
        assert json.loads(resp2.body)["filename"] == "same-name-2.json"

    async def test_rate_limit_returns_429(self, tmp_path):
        view = _view_with_tmp_config(tmp_path)
        view.RATE_LIMIT_REQUESTS = 1
        body = json.dumps({"playlist": _valid_playlist("Rate Test")}).encode()

        first = await view.post(_request_with_body(body))
        second = await view.post(_request_with_body(body))
        assert first.status == 200
        assert second.status == 429


class TestSavePlaylistViewAuth:
    """#1368: POST persists a caller-supplied JSON to disk and creates a new
    non-clobbering file on every save, so it must require auth.

    Before the fix any unauthenticated client on the LAN (or via the Nabu Casa
    remote URL) could repeatedly POST distinct playlists to exhaust the HA
    config volume (disk-exhaustion DoS) and pollute the Community tab — only IP
    rate limiting stood in the way.
    """

    async def test_unauthorized_post_is_rejected_401(self, tmp_path):
        view = _view_with_tmp_config(tmp_path)
        body = json.dumps({"playlist": _valid_playlist("Blocked")}).encode()
        with mock.patch(
            "custom_components.beatify.server.playlist_views.is_authorized_http",
            new=MagicMock(return_value=False),
        ):
            resp = await view.post(_request_with_body(body))
        assert resp.status == 401
        assert json.loads(resp.body)["error"] == "UNAUTHORIZED"

    async def test_unauthorized_post_does_not_write_to_disk(self, tmp_path):
        view = _view_with_tmp_config(tmp_path)
        body = json.dumps({"playlist": _valid_playlist("Blocked")}).encode()
        with mock.patch(
            "custom_components.beatify.server.playlist_views.is_authorized_http",
            new=MagicMock(return_value=False),
        ):
            await view.post(_request_with_body(body))
        view.hass.async_add_executor_job.assert_not_called()


class TestUserSubdirIsCommunityInDiscovery:
    """async_discover_playlists must classify user/ entries as community
    so saved playlists appear in the Playlist Hub Community tab (#1057)."""

    async def test_user_subdir_classified_as_community(self, tmp_path):
        playlist_dir = tmp_path / "beatify" / "playlists"
        user_dir = playlist_dir / "user"
        user_dir.mkdir(parents=True)
        (user_dir / "my-mix.json").write_text(json.dumps(_valid_playlist("My Mix")))

        hass = MagicMock()
        hass.config.path = MagicMock(return_value=str(playlist_dir))

        results = await async_discover_playlists(hass)
        matching = [p for p in results if p["filename"] == "my-mix.json"]
        assert len(matching) == 1
        assert matching[0]["source"] == "community"
