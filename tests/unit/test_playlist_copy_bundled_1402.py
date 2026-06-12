"""Tests for non-blocking _copy_bundled_playlists (#1402 B3).

The bundled-playlist copy previously ran ``exists()`` / ``mkdir()`` directly on
the event loop and re-stat'd the destination after already computing its
existence. These tests pin the observable behaviour (the copy still creates the
nested ``community/`` destination dir, copies new files, and is idempotent) so
the refactor that moved those syscalls into the executor stays correct.

They run against the real bundled playlists shipped in the package (which
include a nested ``community/`` subdir), so the mkdir-in-executor path is
exercised end-to-end.
"""

from __future__ import annotations

from custom_components.beatify.game.playlist import _copy_bundled_playlists


async def test_copies_bundled_playlists_into_nested_dirs(tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()

    await _copy_bundled_playlists(dest)

    copied = list(dest.glob("**/*.json"))
    assert copied, "expected bundled playlists to be copied into dest"
    # The bundled set includes a nested community/ subdir — its parent dir must
    # have been created in the executor (mkdir folded into _copy_file).
    assert (dest / "community").is_dir()
    assert list((dest / "community").glob("*.json"))


async def test_copy_is_idempotent(tmp_path):
    dest = tmp_path / "dest"
    dest.mkdir()

    await _copy_bundled_playlists(dest)
    first = {p.relative_to(dest) for p in dest.glob("**/*.json")}

    # Second run: everything is already up to date — must not error or drop files.
    await _copy_bundled_playlists(dest)
    second = {p.relative_to(dest) for p in dest.glob("**/*.json")}

    assert first == second
