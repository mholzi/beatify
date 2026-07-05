"""Tests for the memoised playlist discovery cache (#1704).

The status endpoint used to re-read + re-parse + re-validate the whole playlist
corpus on the event loop on every ``/api/status`` request. Discovery is now
memoised in ``hass.data[DOMAIN]`` keyed by an on-disk signature (path set + each
file's mtime + size): unchanged corpus → cache hit (no re-parse); any
save / mix / delete changes the signature → transparent invalidation, no
staleness and no explicit hook in the write paths.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock
from unittest.mock import MagicMock

from custom_components.beatify.game import playlist as pl


def _song(tag: str, year: int = 1985) -> dict:
    uri = "spotify:track:" + tag.rjust(22, "0")
    return {"artist": "A " + tag, "title": "T " + tag, "year": year, "uri": uri}


def _playlist(name: str, tags: list[str], songs: list[dict]) -> dict:
    return {
        "name": name,
        "version": "1.0",
        "tags": tags,
        "language": "en",
        "author": "Tester",
        "added_date": "2026-06-24",
        "songs": songs,
    }


def _write(pdir: Path, filename: str, name: str, tags: list[str], songs) -> None:
    (pdir / filename).write_text(
        json.dumps(_playlist(name, tags, songs)), encoding="utf-8"
    )


def _fake_hass(pdir: Path):
    """Minimal hass double: real dict `.data`, config.path → the playlist dir.

    Discovery offloads its work via ``asyncio.get_running_loop().run_in_executor``
    (not ``hass.async_add_executor_job``), so a plain object with a real
    ``data`` dict is enough — the cache must survive across calls, which a
    MagicMock dict would not.
    """
    hass = MagicMock()
    hass.config.path = MagicMock(return_value=str(pdir))
    hass.data = {}
    return hass


def _catalogue(tmp_path: Path) -> Path:
    pdir = tmp_path / "beatify" / "playlists"
    pdir.mkdir(parents=True)
    _write(pdir, "80s.json", "80s", ["1980s", "pop"], [_song("0001"), _song("0002")])
    _write(pdir, "90s.json", "90s", ["1990s", "pop"], [_song("0003", 1995)])
    return pdir


class TestDiscoveryCache:
    async def test_second_call_is_cache_hit_no_reparse(self, tmp_path):
        pdir = _catalogue(tmp_path)
        hass = _fake_hass(pdir)

        with mock.patch.object(
            pl, "validate_playlist", wraps=pl.validate_playlist
        ) as spy:
            metas1, songs1 = await pl.async_discover_playlists_detailed(hass)
            calls_first = spy.call_count
            assert calls_first == 2  # both playlists parsed + validated

            # Nothing changed on disk → cache hit → no re-parse, same objects.
            metas2, songs2 = await pl.async_discover_playlists_detailed(hass)
            assert spy.call_count == calls_first
            assert metas2 is metas1
            assert songs2 is songs1

    async def test_save_new_playlist_invalidates_cache(self, tmp_path):
        pdir = _catalogue(tmp_path)
        hass = _fake_hass(pdir)

        metas1 = await pl.async_discover_playlists(hass)
        names1 = {m["name"] for m in metas1}
        assert "Fresh" not in names1

        # A save writes a new file (e.g. user/<slug>.json) — the signature
        # changes, so the very next discovery must see it (no staleness).
        (pdir / "user").mkdir()
        _write(pdir / "user", "fresh.json", "Fresh", ["pop"], [_song("0009", 2001)])

        with mock.patch.object(
            pl, "validate_playlist", wraps=pl.validate_playlist
        ) as spy:
            metas2 = await pl.async_discover_playlists(hass)
            assert spy.call_count > 0  # re-parsed
        names2 = {m["name"] for m in metas2}
        assert "Fresh" in names2
        assert metas2 is not metas1

    async def test_inplace_edit_invalidates_cache(self, tmp_path):
        """An in-place content edit (mtime/size change) also invalidates —
        directory mtime alone would miss this, so the signature includes each
        file's mtime_ns + size."""
        pdir = _catalogue(tmp_path)
        hass = _fake_hass(pdir)

        await pl.async_discover_playlists_detailed(hass)

        # Overwrite an existing file with a different song count.
        _write(
            pdir,
            "80s.json",
            "80s",
            ["1980s", "pop"],
            [_song("0001"), _song("0002"), _song("0005")],
        )

        metas, songs_by_path = await pl.async_discover_playlists_detailed(hass)
        edited = next(m for m in metas if m["filename"] == "80s.json")
        assert edited["song_count"] == 3

    async def test_songs_by_path_carries_parsed_songs(self, tmp_path):
        """The detailed variant returns the parsed songs per path so the mixer
        reuses the parse instead of re-reading each file (#1704)."""
        pdir = _catalogue(tmp_path)
        hass = _fake_hass(pdir)

        metas, songs_by_path = await pl.async_discover_playlists_detailed(hass)
        for meta in metas:
            assert meta["path"] in songs_by_path
            assert len(songs_by_path[meta["path"]]) == meta["song_count"]

    async def test_missing_dir_returns_empty_and_caches(self, tmp_path):
        pdir = tmp_path / "beatify" / "playlists"  # not created
        hass = _fake_hass(pdir)

        metas1, songs1 = await pl.async_discover_playlists_detailed(hass)
        assert metas1 == []
        assert songs1 == {}
        # Second call is a cache hit (empty signature unchanged).
        metas2, _ = await pl.async_discover_playlists_detailed(hass)
        assert metas2 is metas1
