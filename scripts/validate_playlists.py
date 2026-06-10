#!/usr/bin/env python3
"""Validate Beatify playlist JSON files against the playlist schema.

Used as a CI gate (see .github/workflows/validate.yml) so that broken
URIs / years / missing fields fail the PR instead of being caught later by
the playlist-review job. See issue #1284.

Checks per file:
  1. File is valid JSON.                         -> hard failure (fails CI)
  2. File conforms to scripts/playlist_schema.json (required fields, types,
     year range, Spotify URI format, ISRC format). -> hard failure (fails CI)
  3. Light lint: duplicate (non-null) Spotify URIs within the same file.
     -> warning only (does NOT fail CI; issue #1284 marks duplicate-lint
        optional). Surfaces existing data smells without blocking legacy
        files. Pass --strict to turn warnings into failures.

Exit code 0 = no hard errors, 1 = at least one hard error
(or any warning when --strict is set).

Usage:
    python scripts/validate_playlists.py            # validate all playlists
    python scripts/validate_playlists.py a.json b.json   # validate given files
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover - guidance for local runs
    sys.stderr.write(
        "error: 'jsonschema' is not installed. Run: pip install jsonschema\n"
    )
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "scripts" / "playlist_schema.json"
PLAYLIST_DIR = REPO_ROOT / "custom_components" / "beatify" / "playlists"


def load_schema_validator() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def discover_playlists() -> list[Path]:
    return sorted(PLAYLIST_DIR.rglob("*.json"))


def validate_file(
    path: Path, validator: Draft202012Validator
) -> tuple[list[str], list[str]]:
    """Validate one file.

    Returns ``(errors, warnings)``:
      - errors:   hard problems (invalid JSON / schema violations) that fail CI.
      - warnings: soft lint findings (duplicate URIs) that do not fail CI
                  unless --strict is set.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return ([f"invalid JSON: {exc}"], [])

    errors: list[str] = []
    warnings: list[str] = []

    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.path)):
        location = "/".join(str(p) for p in err.path) or "<root>"
        errors.append(f"schema: at '{location}': {err.message}")

    # Light lint: duplicate Spotify URIs within the same playlist.
    if isinstance(data, dict) and isinstance(data.get("songs"), list):
        uris = [s["uri"] for s in data["songs"] if isinstance(s, dict) and s.get("uri")]
        dupes = [uri for uri, count in Counter(uris).items() if count > 1]
        for uri in dupes:
            warnings.append(f"lint: duplicate uri within file: {uri}")

    return (errors, warnings)


def main(argv: list[str]) -> int:
    strict = "--strict" in argv
    paths = [a for a in argv if a != "--strict"]

    validator = load_schema_validator()

    if paths:
        files = [Path(a).resolve() for a in paths]
    else:
        files = discover_playlists()

    if not files:
        sys.stderr.write(f"error: no playlist files found under {PLAYLIST_DIR}\n")
        return 1

    total_errors = 0
    total_warnings = 0
    for path in files:
        rel = path.relative_to(REPO_ROOT) if path.is_relative_to(REPO_ROOT) else path
        errors, warnings = validate_file(path, validator)
        total_errors += len(errors)
        total_warnings += len(warnings)
        if errors:
            print(f"FAIL {rel}")
        elif warnings:
            print(f"warn {rel}")
        else:
            print(f"ok   {rel}")
        for msg in errors:
            print(f"  ❌ {msg}")
        for msg in warnings:
            print(f"  ⚠️  {msg}")

    print()
    if total_warnings:
        print(f"⚠️  {total_warnings} lint warning(s) (non-blocking unless --strict).")
    if total_errors:
        print(
            f"❌ Playlist validation failed: {total_errors} error(s) in {len(files)} file(s)."
        )
        return 1
    if strict and total_warnings:
        print("❌ --strict: treating warnings as errors.")
        return 1

    print(f"✅ All {len(files)} playlist file(s) valid (schema gate passed).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
