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


def _song(**overrides: object) -> dict:
    """Minimal song that satisfies the schema, with fields overridden per test."""
    song = {
        "artist": "Falco",
        "title": "Rock Me Amadeus",
        "year": 1985,
        "uri": "spotify:track:1EB3Z38oKDKVp4K2yEO2dl",
        "fun_fact": "f",
        "fun_fact_de": "f",
        "fun_fact_es": "f",
        "fun_fact_fr": "f",
        "fun_fact_nl": "f",
    }
    song.update(overrides)
    return song


def _playlist(song: dict) -> dict:
    return {"name": "t", "version": "1.0", "tags": ["t"], "songs": [song]}


def test_baseline_song_is_valid() -> None:
    # Without this, every rejection test below would pass for the wrong reason.
    assert not list(_validator().iter_errors(_playlist(_song())))


# The malformed forms that reached `main` before #2247: a bare numeric ID, an
# Apple web URL and an empty string. `get_song_uri()` hands these to Music
# Assistant verbatim, and for a regional entry the legacy field is dropped
# (#1379), so there is no fallback behind a broken value.
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("uri_apple_music", "1519834045"),
        ("uri_apple_music", "https://music.apple.com/us/album/x/257853869?i=257853898"),
        ("uri_apple_music", ""),
        ("uri_deezer", "122357172"),
        ("uri_deezer", ""),
        ("uri_tidal", "12345678"),
        ("uri_youtube_music", "e_yafwjcf-w"),
    ],
)
def test_malformed_provider_uri_is_rejected(field: str, value: str) -> None:
    errors = list(_validator().iter_errors(_playlist(_song(**{field: value}))))
    assert errors, f"{field}={value!r} must not pass the schema gate"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("uri_apple_music", "applemusic://track/1519834045"),
        ("uri_apple_music", None),
        ("uri_deezer", "deezer://track/122357172"),
        ("uri_tidal", "tidal://track/12345678"),
        ("uri_youtube_music", "https://music.youtube.com/watch?v=e_yafwjcf-w"),
        ("uri_youtube_music", "https://www.youtube.com/watch?v=KQRaj1vcnrs"),
    ],
)
def test_well_formed_provider_uri_is_accepted(field: str, value: str | None) -> None:
    errors = list(_validator().iter_errors(_playlist(_song(**{field: value}))))
    assert not errors, [e.message for e in errors]


def test_region_map_rejects_bare_id_but_accepts_uri_and_null() -> None:
    validator = _validator()
    bad = _playlist(_song(uri_apple_music_by_region={"us": "1519834045"}))
    assert list(validator.iter_errors(bad)), "bare region ID must not pass (#2247)"

    good = _playlist(
        _song(
            uri_apple_music_by_region={
                "us": "applemusic://track/1519834045",
                "fr": None,
            }
        )
    )
    assert not list(validator.iter_errors(good))


def test_fun_fact_it_is_optional_and_typed() -> None:
    """#2234: Italian fun facts must not gate the catalogue.

    The five older ``fun_fact_*`` fields are required. Adding ``fun_fact_it``
    the same way would fail this very gate for all 6261 songs until every one
    carries an Italian fact, turning a catalogue chore into a release blocker.
    """
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    song = schema["$defs"]["song"]

    assert "fun_fact_it" not in song["required"], "fun_fact_it must stay optional"
    assert song["properties"]["fun_fact_it"]["type"] == "string"

    validator = _validator()
    # Absent: still valid.
    assert not list(validator.iter_errors(_playlist(_song())))
    # Present: still valid.
    assert not list(
        validator.iter_errors(_playlist(_song(fun_fact_it="Fu il primo brano…")))
    )
    # Wrong type: rejected, so a null does not slip in unnoticed.
    assert list(validator.iter_errors(_playlist(_song(fun_fact_it=None))))
