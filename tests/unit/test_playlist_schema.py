"""Schema gate for the shipped playlist JSON files (#1284).

These tests are the in-pytest mirror of ``scripts/validate_playlists.py``:
every playlist under ``custom_components/beatify/playlists/`` must conform to
``scripts/playlist_schema.json`` (required fields, types, year range, Spotify
URI format, ISRC format). A broken playlist now fails CI on the PR instead of
being caught later by the playlist-review job.

The dedicated CI step (``.github/workflows/validate.yml``) runs the script with
the same schema; this test guarantees the gate also fires in the normal test
matrix and is easy to run locally via ``pytest``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "scripts" / "playlist_schema.json"
PLAYLIST_DIR = REPO_ROOT / "custom_components" / "beatify" / "playlists"

PLAYLIST_FILES = sorted(PLAYLIST_DIR.rglob("*.json"))


def _validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def test_schema_is_itself_valid() -> None:
    # Raises SchemaError if the meta-schema is violated.
    _validator()


def test_playlist_files_discovered() -> None:
    assert PLAYLIST_FILES, f"no playlist files found under {PLAYLIST_DIR}"


@pytest.mark.parametrize("path", PLAYLIST_FILES, ids=[p.name for p in PLAYLIST_FILES])
def test_playlist_conforms_to_schema(path: Path) -> None:
    validator = _validator()
    data = json.loads(path.read_text(encoding="utf-8"))
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    messages = [
        f"at '{'/'.join(str(p) for p in e.path) or '<root>'}': {e.message}"
        for e in errors
    ]
    assert not messages, "schema violations:\n" + "\n".join(messages)
