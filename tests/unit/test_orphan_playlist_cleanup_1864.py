"""#1864 — runtime copies of relocated bundled playlists must be pruned.

``_copy_bundled_playlists`` only ever created or version-bumped its destination.
When a shipped playlist moved inside the bundle, the copy at the old path was
never removed: it stayed discoverable, stayed in the picker under the same
display name, and stayed playable, so a host could pick a playlist and silently
get an outdated copy of it.

The deletions here are the dangerous half of the fix, so most of these tests are
about what must *survive*.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.beatify.game.playlist import (
    _index_bundled_by_name,
    _prune_relocated_playlists,
)


def _write(path: Path, version: str = "1.0", songs: int = 1) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {"version": version, "songs": [{"title": f"s{i}"} for i in range(songs)]}
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def dest(tmp_path: Path) -> Path:
    d = tmp_path / "runtime"
    d.mkdir()
    return d


@pytest.fixture
def bundled(tmp_path: Path) -> Path:
    b = tmp_path / "bundled"
    b.mkdir()
    return b


def _index(bundled: Path) -> dict[str, Path]:
    return _index_bundled_by_name(sorted(bundled.glob("**/*.json")), bundled)


class TestPrunesStrandedCopies:
    def test_flat_copy_is_removed_when_playlist_moved_to_community(self, dest, bundled):
        """The reported case: gen-z-anthems moved into community/."""
        _write(bundled / "community" / "gen-z-anthems.json", version="1.3")
        _write(dest / "community" / "gen-z-anthems.json", version="1.3")
        stale = _write(dest / "gen-z-anthems.json", version="1.2")

        removed = _prune_relocated_playlists(dest, _index(bundled))

        assert removed == ["gen-z-anthems.json"]
        assert not stale.exists()
        assert (dest / "community" / "gen-z-anthems.json").exists()

    def test_community_copy_is_removed_when_playlist_ships_flat(self, dest, bundled):
        """Direction is 'not where we ship it now', not 'flat is stale'.

        Several playlists moved the other way — 70s-hits ships flat today while
        the reporting instance still had a community/ copy of it.
        """
        _write(bundled / "70s-hits.json", version="1.12")
        _write(dest / "70s-hits.json", version="1.12")
        stale = _write(dest / "community" / "70s-hits.json", version="1.0")

        removed = _prune_relocated_playlists(dest, _index(bundled))

        assert removed == [str(Path("community/70s-hits.json"))]
        assert not stale.exists()
        assert (dest / "70s-hits.json").exists()

    def test_reports_every_removal(self, dest, bundled):
        for name in ("a", "b", "c"):
            _write(bundled / "community" / f"{name}.json")
            _write(dest / "community" / f"{name}.json")
            _write(dest / f"{name}.json")

        removed = _prune_relocated_playlists(dest, _index(bundled))

        assert sorted(removed) == ["a.json", "b.json", "c.json"]


class TestNeverTouchesWhatItShouldNot:
    def test_user_created_playlist_survives(self, dest, bundled):
        """kristina_party.json has no bundled counterpart — hands off."""
        _write(bundled / "community" / "gen-z-anthems.json")
        _write(dest / "community" / "gen-z-anthems.json")
        mine = _write(dest / "kristina_party.json", songs=6)

        removed = _prune_relocated_playlists(dest, _index(bundled))

        assert removed == []
        assert mine.exists()

    def test_retired_playlist_we_no_longer_ship_survives(self, dest, bundled):
        """We cannot tell a dropped playlist from a hand-made one — keep both."""
        _write(bundled / "community" / "current.json")
        _write(dest / "community" / "current.json")
        retired = _write(dest / "renamed-away.json")

        removed = _prune_relocated_playlists(dest, _index(bundled))

        assert removed == []
        assert retired.exists()

    def test_user_subtree_is_skipped_even_on_a_name_collision(self, dest, bundled):
        """`user/` belongs to the user, name clash or not."""
        _write(bundled / "70s-hits.json")
        _write(dest / "70s-hits.json")
        theirs = _write(dest / "user" / "70s-hits.json", version="9.9")

        removed = _prune_relocated_playlists(dest, _index(bundled))

        assert removed == []
        assert theirs.exists()

    def test_current_copy_is_kept(self, dest, bundled):
        _write(bundled / "community" / "gen-z-anthems.json")
        current = _write(dest / "community" / "gen-z-anthems.json")

        assert _prune_relocated_playlists(dest, _index(bundled)) == []
        assert current.exists()

    def test_never_strands_a_playlist_when_the_current_copy_is_missing(
        self, dest, bundled
    ):
        """If the copy loop did not land the current file, keep the old one.

        Deleting here would leave the host with no copy at all.
        """
        _write(bundled / "community" / "gen-z-anthems.json")
        only_copy = _write(dest / "gen-z-anthems.json", version="1.2")

        removed = _prune_relocated_playlists(dest, _index(bundled))

        assert removed == []
        assert only_copy.exists()

    def test_ambiguous_bundled_basename_disables_pruning_for_that_name(
        self, dest, bundled
    ):
        """Two shipped files with one basename → we cannot know which is current."""
        _write(bundled / "dupe.json")
        _write(bundled / "community" / "dupe.json")
        _write(bundled / "community" / "safe.json")

        index = _index(bundled)
        assert "dupe.json" not in index
        assert "safe.json" in index

        a = _write(dest / "dupe.json")
        b = _write(dest / "community" / "dupe.json")
        c = _write(dest / "user" / "dupe.json")

        assert _prune_relocated_playlists(dest, index) == []
        assert a.exists() and b.exists() and c.exists()


class TestIntegrationWithCopy:
    @pytest.mark.asyncio
    async def test_copy_then_prune_leaves_exactly_the_shipped_set(
        self, tmp_path, monkeypatch
    ):
        """End-to-end through _copy_bundled_playlists: stale out, user file in."""
        from custom_components.beatify.game import playlist as playlist_mod

        # _copy_bundled_playlists derives the bundle from __file__:
        # Path(__file__).parent.parent / "playlists"
        pkg = tmp_path / "beatify"
        fake_module = pkg / "game" / "playlist.py"
        fake_module.parent.mkdir(parents=True)
        src = pkg / "playlists"

        _write(src / "70s-hits.json", version="1.12")
        _write(src / "community" / "gen-z-anthems.json", version="1.3")

        # A runtime dir carrying the damage from an older layout.
        dest = tmp_path / "runtime"
        dest.mkdir()
        _write(dest / "gen-z-anthems.json", version="1.2")
        _write(dest / "community" / "70s-hits.json", version="1.0")
        _write(dest / "kristina_party.json", songs=6)

        monkeypatch.setattr(playlist_mod, "__file__", str(fake_module))
        await playlist_mod._copy_bundled_playlists(dest)

        survivors = {str(p.relative_to(dest)) for p in sorted(dest.glob("**/*.json"))}
        assert survivors == {
            "70s-hits.json",
            str(Path("community/gen-z-anthems.json")),
            "kristina_party.json",
        }
        assert json.loads((dest / "70s-hits.json").read_text())["version"] == "1.12"
