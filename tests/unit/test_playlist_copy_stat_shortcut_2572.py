"""Tests for the one-hop bundled-playlist copy (#2572).

The copy loop used to await a separate executor round-trip per playlist and
parse both JSON documents in full just to read ``version``. It now runs as a
single executor job with a stat-based shortcut. These tests pin the two things
that shortcut must never get wrong: it has to skip the parse in the common
case, and it must not swallow a real update.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from custom_components.beatify.game import playlist as playlist_mod
from custom_components.beatify.game.playlist import (
    _copy_bundled_playlists,
    _copy_bundled_playlists_sync,
)


def _write(path: Path, version: str, *, pad: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": version, "name": "x", "songs": [], "pad": pad}),
        encoding="utf-8",
    )


@pytest.fixture
def bundled(tmp_path: Path) -> Path:
    d = tmp_path / "bundled"
    d.mkdir()
    return d


@pytest.fixture
def dest(tmp_path: Path) -> Path:
    d = tmp_path / "dest"
    d.mkdir()
    return d


def test_first_run_copies_and_reports(bundled: Path, dest: Path) -> None:
    _write(bundled / "a.json", "1.0")
    _write(bundled / "community" / "b.json", "2.0")

    log, files = _copy_bundled_playlists_sync(bundled, dest)

    assert len(files) == 2
    assert (dest / "a.json").exists()
    assert (dest / "community" / "b.json").exists()
    assert sorted(m for _, m in log) == [
        "Copied bundled playlist a.json (v1.0)",
        "Copied bundled playlist b.json (v2.0)",
    ]


def test_unchanged_playlist_is_never_parsed(
    bundled: Path, dest: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The point of the whole change: no JSON parse on a steady-state restart."""
    _write(bundled / "a.json", "1.0")
    _copy_bundled_playlists_sync(bundled, dest)

    def _boom(path: Path) -> str:
        raise AssertionError(f"parsed {path} although nothing changed")

    monkeypatch.setattr(playlist_mod, "_get_playlist_version", _boom)
    log, _ = _copy_bundled_playlists_sync(bundled, dest)

    assert log == []


def test_newer_bundled_version_still_wins(bundled: Path, dest: Path) -> None:
    """A shipped update changes the size, so the shortcut steps aside."""
    src = bundled / "a.json"
    _write(src, "1.0")
    _copy_bundled_playlists_sync(bundled, dest)

    _write(src, "2.0", pad="grown by a release")
    log, _ = _copy_bundled_playlists_sync(bundled, dest)

    assert json.loads((dest / "a.json").read_text())["version"] == "2.0"
    assert log == [("info", "Updated playlist a.json: v1.0 -> v2.0")]


def test_same_size_but_older_destination_is_re_examined(
    bundled: Path, dest: Path
) -> None:
    """Equal size alone is not enough — an older copy must be looked at.

    A version bump from 1.0 to 9.0 leaves the byte count untouched. The mtime
    half of the check is what catches it.
    """
    src = bundled / "a.json"
    _write(src, "1.0")
    _copy_bundled_playlists_sync(bundled, dest)

    _write(src, "9.0")
    assert src.stat().st_size == (dest / "a.json").stat().st_size
    os.utime(dest / "a.json", ns=(0, 0))

    log, _ = _copy_bundled_playlists_sync(bundled, dest)

    assert json.loads((dest / "a.json").read_text())["version"] == "9.0"
    assert log == [("info", "Updated playlist a.json: v1.0 -> v9.0")]


def test_older_bundled_version_does_not_overwrite_a_newer_copy(
    bundled: Path, dest: Path
) -> None:
    src = bundled / "a.json"
    _write(src, "1.0")
    _copy_bundled_playlists_sync(bundled, dest)
    _write(dest / "a.json", "5.0", pad="user is ahead")

    log, _ = _copy_bundled_playlists_sync(bundled, dest)

    assert json.loads((dest / "a.json").read_text())["version"] == "5.0"
    assert log == []


def test_unreadable_playlist_is_reported_not_raised(
    bundled: Path, dest: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(bundled / "a.json", "1.0")
    _write(bundled / "b.json", "1.0")

    real_copy = playlist_mod._copy_playlist_file

    def _fail_on_a(src: Path, dst: Path) -> None:
        if src.name == "a.json":
            raise OSError("disk on fire")
        real_copy(src, dst)

    monkeypatch.setattr(playlist_mod, "_copy_playlist_file", _fail_on_a)
    log, _ = _copy_bundled_playlists_sync(bundled, dest)

    assert (dest / "b.json").exists()
    assert not (dest / "a.json").exists()
    assert ("warning", "Failed to process playlist a.json: disk on fire") in log


async def test_async_wrapper_uses_a_single_executor_hop(
    dest: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """66 playlists used to mean 66+ round-trips. Now it is copy + prune.

    Runs against the real bundled catalogue, so the count is the one an HA
    setup actually pays.
    """
    hops = 0
    loop = asyncio.get_running_loop()
    real = loop.run_in_executor

    def _counted(executor, func, *args):  # noqa: ANN001, ANN202
        nonlocal hops
        hops += 1
        return real(executor, func, *args)

    monkeypatch.setattr(loop, "run_in_executor", _counted)
    await _copy_bundled_playlists(dest)

    assert list(dest.glob("**/*.json")), "expected the real bundle to be copied"
    # exists() + copy job + prune job — and nothing per playlist.
    assert hops == 3
