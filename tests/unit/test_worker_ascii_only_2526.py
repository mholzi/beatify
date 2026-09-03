"""The Cloudflare worker source must stay pure ASCII (#2526).

``cf-workers/beatify-api.js`` is deployed by copying the file into the
Cloudflare dashboard rather than from a checkout. That copy path was at some
point round-tripped through a terminal-style buffer: the UTF-8 bytes were read
as Latin-1 and the resulting control characters written back in caret notation.
Every non-ASCII literal in the deployed worker was destroyed by it, so the
issues the worker files landed as
``data: wrong year reported \xc3\xa2^@^T Kendrick Lamar ...`` instead of
carrying an em dash -- a garbled, unsearchable public issue list.

Escaping the characters (``\\u2014`` instead of a literal em dash) makes the
source immune: the escape itself is ASCII, so no Latin-1 round trip can touch
it, while the runtime output is byte-identical. These tests keep the file that
way.
"""

from __future__ import annotations

from pathlib import Path

WORKER = Path(__file__).resolve().parents[2] / "cf-workers" / "beatify-api.js"


def test_worker_source_exists() -> None:
    assert WORKER.is_file(), f"worker source missing at {WORKER}"


def test_worker_source_is_pure_ascii() -> None:
    """No byte >= 0x80 anywhere in the worker source.

    Use ``\\uXXXX`` / ``\\u{XXXXX}`` escapes for characters that must reach
    GitHub, and plain ASCII punctuation in comments.
    """
    data = WORKER.read_bytes()
    offenders = [
        (line_no, line.decode("utf-8", "replace"))
        for line_no, line in enumerate(data.split(b"\n"), start=1)
        if any(byte >= 0x80 for byte in line)
    ]
    assert not offenders, (
        "non-ASCII bytes in cf-workers/beatify-api.js -- the deploy copy path "
        "mangles them (#2526). Write them as \\u escapes instead:\n"
        + "\n".join(f"  line {n}: {text}" for n, text in offenders)
    )


def test_generated_issue_titles_keep_their_escaped_characters() -> None:
    """The auto-filed title templates still carry their dashes/emoji, escaped."""
    src = WORKER.read_text(encoding="ascii")
    assert "`data: wrong year reported \\u2014 ${artist} \\u2013 ${title}`" in src, (
        "the wrong-year title lost its escaped em/en dash"
    )
    assert "title: `\\u{1F3B5} Playlist Request: ${playlist_name}`" in src, (
        "the playlist-request title lost its escaped music note"
    )
