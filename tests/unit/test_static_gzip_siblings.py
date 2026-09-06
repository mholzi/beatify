"""A committed ``.gz`` sibling must never outlive the file it compresses (#2640).

HA registers ``/beatify/static`` through aiohttp's static handler. aiohttp does
not compress on the fly; it serves ``<file>.gz`` verbatim whenever the request
carries ``Accept-Encoding: gzip`` — which every browser does. That makes a stale
sibling worse than no sibling at all: it wins over the fresh file for every real
visitor, and aiohttp builds the ETag from the *compressed* file's mtime and size
(``web_fileresponse._get_file_path_stat_encoding``), so the browser then caches
the old bytes as if they were current. A ``curl`` without the header sees the
fresh file and reports nothing wrong.

``npm run build:check`` owns the question of *which* files must carry a sibling.
This module owns the narrower invariant, and owns it without needing node: every
``.gz`` in the shipped tree decompresses byte-for-byte to the file next to it,
and none of them is an orphan.
"""

from __future__ import annotations

import gzip
from pathlib import Path

WWW_DIR = Path(__file__).resolve().parents[2] / "custom_components" / "beatify" / "www"


def _gz_problems(www_dir: Path) -> list[str]:
    """Report every ``.gz`` that lies about the file it sits next to."""
    problems: list[str] = []
    for gz in sorted(www_dir.rglob("*.gz")):
        source = gz.with_suffix("")  # strips the trailing .gz
        rel = gz.relative_to(www_dir)
        if not source.is_file():
            problems.append(f"{rel} (orphan — nothing on disk it belongs to)")
            continue
        try:
            plain = gzip.decompress(gz.read_bytes())
        except (OSError, EOFError) as err:
            problems.append(f"{rel} (not a readable gzip stream: {err})")
            continue
        if plain != source.read_bytes():
            problems.append(f"{rel} (stale — does not decompress to {source.name})")
    return problems


def test_shipped_gz_siblings_match_their_source() -> None:
    """The tree that HACS copies onto the box carries no stale sibling."""
    assert _gz_problems(WWW_DIR) == []


def test_the_tree_actually_ships_siblings() -> None:
    """Guard the guard: an empty tree would make the check above vacuous."""
    assert len(list(WWW_DIR.rglob("*.gz"))) > 20


def test_fresh_sibling_is_accepted(tmp_path: Path) -> None:
    (tmp_path / "app.js").write_bytes(b"console.log('v2');\n")
    (tmp_path / "app.js.gz").write_bytes(gzip.compress(b"console.log('v2');\n"))
    assert _gz_problems(tmp_path) == []


def test_stale_sibling_is_reported(tmp_path: Path) -> None:
    """The whole point: the source moved on, the sibling did not."""
    (tmp_path / "app.js").write_bytes(b"console.log('v2');\n")
    (tmp_path / "app.js.gz").write_bytes(gzip.compress(b"console.log('v1');\n"))

    problems = _gz_problems(tmp_path)

    assert len(problems) == 1
    assert "app.js.gz" in problems[0]
    assert "stale" in problems[0]


def test_orphan_sibling_is_reported(tmp_path: Path) -> None:
    """A sibling whose source was deleted or renamed still gets served."""
    (tmp_path / "gone.js.gz").write_bytes(gzip.compress(b"console.log('v1');\n"))

    problems = _gz_problems(tmp_path)

    assert len(problems) == 1
    assert "orphan" in problems[0]


def test_corrupt_sibling_is_reported(tmp_path: Path) -> None:
    """Truncated by a half-finished copy: the browser gets an unusable body."""
    (tmp_path / "app.js").write_bytes(b"console.log('v2');\n")
    (tmp_path / "app.js.gz").write_bytes(gzip.compress(b"console.log('v2');\n")[:12])

    problems = _gz_problems(tmp_path)

    assert len(problems) == 1
    assert "not a readable gzip stream" in problems[0]
