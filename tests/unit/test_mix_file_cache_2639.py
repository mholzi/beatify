"""A transient mix file must not invalidate the discovery cache (#2639).

The Smart Playlist Mixer writes ``playlists/mix/__mix__-<uuid>.json`` right
before start-game, and unlinks stale ones an hour later. Both events used to
change the discovery signature, so the start-game call that follows — the one
that exists to reuse the cached parse (#1766) — and the 3 s lobby poll re-read,
re-parsed and re-validated the whole catalogue while the host waited on the
Start tap.

Discovery now skips transient mixes entirely. The second class of test here is
the more important one: the fix must not be allowed to grow into "the signature
ignores changes", so a real add, a real in-place edit and a real delete must all
still invalidate.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

from custom_components.beatify.game import playlist as pl
from custom_components.beatify.server.mix_views import (
    TRANSIENT_MIX_PREFIX,
    TRANSIENT_MIX_SUBDIR,
)


def _song(tag: str, year: int = 1985) -> dict:
    return {
        "artist": "Artist " + tag,
        "title": "Song " + tag,
        "year": year,
        "uri": "spotify:track:" + tag.rjust(22, "0"),
    }


def _write(pdir: Path, filename: str, name: str, tags: list[str], songs) -> Path:
    target = pdir / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            {
                "name": name,
                "version": "1.0",
                "tags": tags,
                "language": "en",
                "author": "Tester",
                "added_date": "2026-09-06",
                "songs": songs,
            }
        ),
        encoding="utf-8",
    )
    return target


def _fake_hass(pdir: Path):
    """Minimal hass double with a REAL ``data`` dict so the cache survives."""
    hass = MagicMock()
    hass.config.path = MagicMock(return_value=str(pdir))
    hass.data = {}
    hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *a: fn(*a))
    return hass


def _catalogue(tmp_path: Path) -> Path:
    pdir = tmp_path / "beatify" / "playlists"
    pdir.mkdir(parents=True)
    _write(pdir, "80s.json", "80s", ["1980s", "pop"], [_song("0001"), _song("0002")])
    _write(pdir, "90s.json", "90s", ["1990s", "pop"], [_song("0003", 1995)])
    return pdir


def _write_transient_mix(pdir: Path, stem: str = "a1b2c3d4") -> Path:
    """Write a file exactly where MixPlaylistView writes its transient doc."""
    return _write(
        pdir,
        f"{TRANSIENT_MIX_SUBDIR}/{TRANSIENT_MIX_PREFIX}-{stem}.json",
        "Smart Mix · Pop",
        ["pop"],
        [_song("0001"), _song("0003", 1995)],
    )


class TestMixDoesNotInvalidate:
    """The point of the fix: a mix write/delete leaves the cache intact."""

    async def test_mix_write_and_cleanup_keep_the_cache_hot(self, tmp_path):
        pdir = _catalogue(tmp_path)
        hass = _fake_hass(pdir)

        metas1, songs1 = await pl.async_discover_playlists_detailed(hass)

        with mock.patch.object(
            pl, "validate_playlist", wraps=pl.validate_playlist
        ) as spy:
            # 1. The mixer writes its transient document…
            mix_file = _write_transient_mix(pdir)
            metas2, songs2 = await pl.async_discover_playlists_detailed(hass)
            assert spy.call_count == 0, "mix write forced a catalogue re-parse"
            assert metas2 is metas1
            assert songs2 is songs1

            # 2. …and the hourly cleanup removes it again.
            mix_file.unlink()
            metas3, _ = await pl.async_discover_playlists_detailed(hass)
            assert spy.call_count == 0, "mix cleanup forced a catalogue re-parse"
            assert metas3 is metas1

    async def test_transient_mix_is_not_listed_as_a_playlist(self, tmp_path):
        """Side effect of the same bug: the mix showed up in the hub list as a
        ``source: "bundled"`` playlist until cleanup an hour later."""
        pdir = _catalogue(tmp_path)
        hass = _fake_hass(pdir)
        mix_file = _write_transient_mix(pdir)

        metas, songs_by_path = await pl.async_discover_playlists_detailed(hass)

        assert {m["filename"] for m in metas} == {"80s.json", "90s.json"}
        assert str(mix_file) not in songs_by_path

    async def test_end_to_end_mix_post_leaves_cache_intact(self, tmp_path):
        """Same claim, but driving the real ``MixPlaylistView.post``."""
        import asyncio

        from aiohttp import StreamReader
        from aiohttp.test_utils import make_mocked_request

        from custom_components.beatify.server.mix_views import MixPlaylistView

        pdir = _catalogue(tmp_path)
        hass = _fake_hass(pdir)
        view = MixPlaylistView(hass)

        # Warm the cache the way the lobby poll does.
        metas1, _ = await pl.async_discover_playlists_detailed(hass)

        body = json.dumps(
            {"tags": ["pop"], "target_count": 50, "provider": "spotify"}
        ).encode()
        reader = StreamReader(
            mock.Mock(_reading_paused=False), 2**16, loop=asyncio.get_event_loop()
        )
        reader.feed_data(body)
        reader.feed_eof()
        request = make_mocked_request(
            "POST",
            "/beatify/api/playlists/mix",
            headers={"Content-Type": "application/json"},
            payload=reader,
        )
        with mock.patch(
            "custom_components.beatify.server.mix_views.is_authorized_http",
            new=MagicMock(return_value=True),
        ):
            resp = await view.post(request)
        assert resp.status == 200
        mix_path = Path(json.loads(resp.body)["path"])
        assert mix_path.exists()

        # The start-game discovery right after the mix must be a cache hit.
        with mock.patch.object(
            pl, "validate_playlist", wraps=pl.validate_playlist
        ) as spy:
            metas2, _ = await pl.async_discover_playlists_detailed(hass)
        assert spy.call_count == 0
        assert metas2 is metas1


class TestRealChangesStillInvalidate:
    """The guard: the fix must not blunt the signature for real content."""

    async def test_new_playlist_still_invalidates(self, tmp_path):
        pdir = _catalogue(tmp_path)
        hass = _fake_hass(pdir)
        await pl.async_discover_playlists_detailed(hass)

        _write(pdir, "user/fresh.json", "Fresh", ["pop"], [_song("0009", 2001)])

        metas = await pl.async_discover_playlists(hass)
        assert "Fresh" in {m["name"] for m in metas}

    async def test_new_playlist_next_to_a_mix_still_invalidates(self, tmp_path):
        """The interesting ordering: a transient mix already sits in the dir
        when the real playlist lands. Skipping the mix must not skip the walk."""
        pdir = _catalogue(tmp_path)
        hass = _fake_hass(pdir)
        _write_transient_mix(pdir)
        await pl.async_discover_playlists_detailed(hass)

        _write(pdir, "user/fresh.json", "Fresh", ["pop"], [_song("0009", 2001)])

        metas = await pl.async_discover_playlists(hass)
        assert "Fresh" in {m["name"] for m in metas}

    async def test_inplace_edit_still_invalidates(self, tmp_path):
        pdir = _catalogue(tmp_path)
        hass = _fake_hass(pdir)
        _write_transient_mix(pdir)
        await pl.async_discover_playlists_detailed(hass)

        _write(
            pdir,
            "80s.json",
            "80s",
            ["1980s", "pop"],
            [_song("0001"), _song("0002"), _song("0005")],
        )

        metas = await pl.async_discover_playlists(hass)
        edited = next(m for m in metas if m["filename"] == "80s.json")
        assert edited["song_count"] == 3

    async def test_delete_still_invalidates(self, tmp_path):
        pdir = _catalogue(tmp_path)
        hass = _fake_hass(pdir)
        _write_transient_mix(pdir)
        await pl.async_discover_playlists_detailed(hass)

        (pdir / "90s.json").unlink()

        metas = await pl.async_discover_playlists(hass)
        names = {m["filename"] for m in metas}
        assert "90s.json" not in names, "delete did not invalidate the cache"
        assert "80s.json" in names
