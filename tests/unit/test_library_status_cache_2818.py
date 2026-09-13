"""The Crate Digger status poll must reuse the parsed pool (#2818).

The admin panel polls ``/library-pool`` every two seconds while a scan or
refresh runs, and the pool file only changes at checkpoints. The status view
used the uncached loader, so nearly every poll re-read and re-parsed an
~11 MB file with identical bytes. The read-only views (status, recent, lookup)
now go through ``async_load_pool_cached``; anything that writes the pool back
keeps the fresh parse.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from aiohttp import web

from custom_components.beatify.library import pool as pool_mod
from custom_components.beatify.server import library_views
from custom_components.beatify.server.library_views import LibraryPoolStatusView

COMPONENT = Path(__file__).resolve().parents[2] / "custom_components" / "beatify"


class FakeHass:
    """Enough Home Assistant to exercise the pool loader through a view."""

    def __init__(self, root: Path):
        self.data: dict = {}
        self.config = type("C", (), {"path": lambda _s, p: str(root / p)})()

    @property
    def loop(self):
        return asyncio.get_running_loop()

    async def async_add_executor_job(self, target, *args):
        return target(*args)


@pytest.fixture
def hass(tmp_path):
    fake = FakeHass(tmp_path)
    yield fake
    pool_mod.invalidate_pool_cache(fake)


def _write_pool(hass, count: int) -> Path:
    path = pool_mod.pool_path(hass)
    path.parent.mkdir(parents=True, exist_ok=True)
    songs = [
        {
            "title": f"Song {i}",
            "artist": f"Artist {i}",
            "uri_ma_library": f"library://track/{i}",
            "year": 1990 + i,
            "year_confidence": 3,
            "global_score": float(i),
        }
        for i in range(count)
    ]
    path.write_text(json.dumps({"songs": songs}), encoding="utf-8")
    return path


async def _poll(view: LibraryPoolStatusView) -> dict:
    # The unit-test HomeAssistantView is a stub without HA's ``json`` helper.
    if not hasattr(view, "json"):
        view.json = web.json_response
    with patch.object(
        library_views, "is_authorized_http", new=MagicMock(return_value=True)
    ):
        resp = await view.get(MagicMock())
    assert resp.status == 200
    return json.loads(resp.body)


class TestStatusPollReusesTheParse:
    async def test_repeated_polls_parse_the_pool_once(self, hass):
        _write_pool(hass, 3)
        view = LibraryPoolStatusView(hass)
        with patch.object(
            pool_mod, "async_load_pool", wraps=pool_mod.async_load_pool
        ) as parse:
            first = await _poll(view)
            second = await _poll(view)
            third = await _poll(view)
        assert parse.await_count == 1, "an unchanged pool must not be re-parsed"
        assert first["built"] is True
        assert first["stats"]["total"] == 3
        assert second == first == third

    async def test_a_checkpoint_write_is_picked_up(self, hass):
        _write_pool(hass, 3)
        view = LibraryPoolStatusView(hass)
        with patch.object(
            pool_mod, "async_load_pool", wraps=pool_mod.async_load_pool
        ) as parse:
            before = await _poll(view)
            # A different song count changes the size, so the signature moves
            # even on filesystems with coarse mtimes.
            _write_pool(hass, 7)
            after = await _poll(view)
        assert parse.await_count == 2
        assert before["stats"]["total"] == 3
        assert after["stats"]["total"] == 7

    async def test_status_does_not_mutate_the_shared_pool(self, hass):
        _write_pool(hass, 3)
        view = LibraryPoolStatusView(hass)
        await _poll(view)
        cached = await pool_mod.async_load_pool_cached(hass)
        snapshot = json.dumps(cached, sort_keys=True)
        await _poll(view)
        assert json.dumps(cached, sort_keys=True) == snapshot

    async def test_missing_pool_still_reports_not_built(self, hass):
        body = await _poll(LibraryPoolStatusView(hass))
        assert body["built"] is False
        assert "stats" not in body


def _view_body(code: str, class_name: str) -> str:
    body = code.split(f"class {class_name}(", 1)[1]
    return body.split("\nclass ", 1)[0]


class TestReadersCachedWritersFresh:
    @pytest.mark.parametrize(
        "view",
        ["LibraryPoolStatusView", "LibraryRecentSongsView", "LibrarySongLookupView"],
    )
    def test_read_only_views_use_the_cached_loader(self, view):
        code = (COMPONENT / "server" / "library_views.py").read_text(encoding="utf-8")
        body = _view_body(code, view)
        assert "async_load_pool_cached(" in body
        assert "async_load_pool(" not in body

    @pytest.mark.parametrize(
        "view",
        # Correct and Restore write the pool back; Backup and Export hand the
        # raw file content to the host and must not carry the generate-path
        # fix-ups the cached parse adds.
        [
            "LibrarySongCorrectView",
            "LibraryPoolRestoreView",
            "LibraryPoolBackupView",
            "LibraryPoolExportView",
        ],
    )
    def test_writers_and_exports_keep_the_fresh_parse(self, view):
        code = (COMPONENT / "server" / "library_views.py").read_text(encoding="utf-8")
        body = _view_body(code, view)
        assert "async_load_pool_cached" not in body
