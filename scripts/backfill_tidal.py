#!/usr/bin/env python3
"""Backfill missing ``uri_tidal`` fields in Beatify playlists via Odesli.

Many community playlists ship without Tidal URIs because the Odesli
(song.link) API rate-limits hard, so coverage has to be filled in several
calm "waves" rather than one pass. This script automates that: it is
**idempotent** (only touches tracks still missing a Tidal URI),
**rate-limit-resilient** (exponential backoff on HTTP 429, skip-on-persistent
instead of aborting, incremental save after every hit), and **budget-aware**
(a state file remembers genuine "not on Tidal" misses so they aren't re-queried
on every run).

Resolution: for each track with a Spotify ``uri`` but no ``uri_tidal``, query
Odesli with the Spotify track URL and map
``linksByPlatform.tidal.url`` -> ``tidal://track/<id>`` (matching the format
used across the catalogue).

State file (``scripts/.tidal-backfill-state.json``) maps each Spotify URI to
``{"status": hit|miss, "tried_at": "<iso>"}``:
  * ``hit``  -> resolved (also written into the playlist; not re-queried).
  * ``miss`` -> Odesli returned 200 but no Tidal link (genuine absence). Not
    re-queried unless ``--retry-misses`` is passed.
  * a 429-skip is NOT recorded as a miss, so the next wave retries it — the
    whole point: "rate-limited" must never be confused with "not on Tidal".

Usage:
    python scripts/backfill_tidal.py                 # one wave over all playlists
    python scripts/backfill_tidal.py --max 50        # cap queries this run
    python scripts/backfill_tidal.py PATH.json ...   # only the given playlists
    python scripts/backfill_tidal.py --dry-run       # list what would be queried, no network
    python scripts/backfill_tidal.py --retry-misses  # also re-query recorded misses

Exit code 0 on success (even with partial coverage), 1 on usage/IO error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PLAYLISTS_DIR = REPO_ROOT / "custom_components" / "beatify" / "playlists"
STATE_PATH = Path(__file__).resolve().parent / ".tidal-backfill-state.json"

ODESLI_API = "https://api.song.link/v1-alpha.1/links"
SPOTIFY_TRACK_RE = re.compile(r"^spotify:track:([A-Za-z0-9]+)$")
TIDAL_TRACK_RE = re.compile(r"/track/(\d+)")

# Pacing — gentle by default so a wave doesn't trigger the 429 wall itself.
BASE_DELAY_S = 6.0  # between successful requests
BACKOFF_BASE_S = 8.0  # 429 backoff: BACKOFF_BASE * attempt
MAX_429_ATTEMPTS = 3  # then skip (NOT recorded as a miss)
REQUEST_TIMEOUT_S = 25


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            sys.stderr.write(
                f"warning: unreadable state {STATE_PATH}, starting fresh\n"
            )
    return {}


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def _bump_version(version) -> str:
    """Bump a playlist ``MAJOR.MINOR`` version (minor +1).

    Catalogue versions are strings like ``"1.8"`` / ``"1.11"`` / ``"0.2"`` —
    the minor part is an integer, not a decimal, so 1.9 -> 1.10. Falls back to
    appending ``.1`` for odd/missing values so the bump never crashes a wave.
    """
    if not isinstance(version, str) or not version:
        return "1.1"
    parts = version.split(".")
    if len(parts) >= 2 and parts[-1].isdigit():
        parts[-1] = str(int(parts[-1]) + 1)
        return ".".join(parts)
    if version.isdigit():
        return f"{version}.1"
    return f"{version}.1"


def find_playlists(args_files: list[str]) -> list[Path]:
    if args_files:
        return [Path(f).resolve() for f in args_files]
    return sorted(PLAYLISTS_DIR.rglob("*.json"))


def query_odesli(spotify_id: str) -> tuple[str | None, str]:
    """Return (tidal_uri_or_None, outcome).

    outcome is one of: 'hit', 'miss' (200 but no Tidal), 'skip' (429 wall /
    transient error — retry next wave).
    """
    url = (
        ODESLI_API
        + "?"
        + urllib.parse.urlencode(
            {"url": f"https://open.spotify.com/track/{spotify_id}", "userCountry": "DE"}
        )
    )
    for attempt in range(1, MAX_429_ATTEMPTS + 1):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "beatify-tidal-backfill"}
            )
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
                data = json.loads(resp.read())
            tidal = data.get("linksByPlatform", {}).get("tidal", {}).get("url")
            if tidal:
                m = TIDAL_TRACK_RE.search(tidal)
                if m:
                    return f"tidal://track/{m.group(1)}", "hit"
            return None, "miss"  # 200, but no usable Tidal link
        except urllib.error.HTTPError as exc:
            if exc.code == 429:
                wait = BACKOFF_BASE_S * attempt
                sys.stderr.write(f"  429 backoff {wait:.0f}s (attempt {attempt})\n")
                time.sleep(wait)
                continue
            sys.stderr.write(f"  HTTP {exc.code} -> skip\n")
            return None, "skip"
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            sys.stderr.write(f"  error {exc} -> skip\n")
            return None, "skip"
    return None, "skip"  # exhausted 429 attempts — retry next wave


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Backfill uri_tidal via Odesli (idempotent, rate-limit-safe)."
    )
    ap.add_argument(
        "files", nargs="*", help="specific playlist JSON files (default: all)"
    )
    ap.add_argument(
        "--max",
        type=int,
        default=0,
        help="cap number of Odesli queries this run (0 = no cap)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="list what would be queried, no network/writes",
    )
    ap.add_argument(
        "--retry-misses",
        action="store_true",
        help="also re-query tracks previously recorded as 'miss'",
    )
    args = ap.parse_args()

    state = {} if args.dry_run else load_state()
    playlists = find_playlists(args.files)
    if not playlists:
        sys.stderr.write("error: no playlist files found\n")
        return 1

    todo: list[
        tuple[Path, dict, str]
    ] = []  # (file, dict, spotify_id) — collected first for a clean count
    files_cache: dict[Path, dict] = {}
    for pf in playlists:
        try:
            doc = json.loads(pf.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            sys.stderr.write(f"warning: skip unreadable {pf.name}: {exc}\n")
            continue
        files_cache[pf] = doc
        for track in doc.get("songs", []):
            if track.get("uri_tidal"):
                continue
            m = SPOTIFY_TRACK_RE.match(track.get("uri", "") or "")
            if not m:
                continue
            sid = m.group(1)
            uri = track["uri"]
            prev = state.get(uri)
            if prev and prev.get("status") == "miss" and not args.retry_misses:
                continue  # genuine absence already recorded — don't waste budget
            todo.append((pf, track, sid))

    print(
        f"{len(todo)} track(s) missing Tidal across {len(files_cache)} playlist(s)"
        f"{' (dry-run)' if args.dry_run else ''}"
    )
    if args.dry_run:
        for pf, track, _sid in todo[: args.max or len(todo)]:
            print(
                f"  WOULD QUERY  {pf.name}: {track.get('artist')} – {track.get('title')}"
            )
        return 0

    hits = misses = skips = 0
    queried = 0
    dirty: set[Path] = set()
    for pf, track, sid in todo:
        if args.max and queried >= args.max:
            print(f"reached --max {args.max}, stopping")
            break
        queried += 1
        tidal_uri, outcome = query_odesli(sid)
        if outcome == "hit":
            track["uri_tidal"] = tidal_uri
            state[track["uri"]] = {"status": "hit", "tried_at": _now_iso()}
            doc = files_cache[pf]
            # Bump the playlist version once per file per run, on its first hit,
            # so any wave that changes a playlist also advances its version.
            if pf not in dirty:
                old_v = doc.get("version")
                doc["version"] = _bump_version(old_v)
                print(f"  version  {pf.name}: {old_v} -> {doc['version']}")
            dirty.add(pf)
            hits += 1
            # incremental save so a later crash/429 wall never loses progress
            pf.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
            save_state(state)
            print(
                f"  OK  {pf.name}: {track.get('artist')} – {track.get('title')} -> {tidal_uri}"
            )
        elif outcome == "miss":
            state[track["uri"]] = {"status": "miss", "tried_at": _now_iso()}
            save_state(state)
            misses += 1
            print(f"  no tidal  {track.get('artist')} – {track.get('title')}")
        else:  # skip — NOT recorded as miss, retried next wave
            skips += 1
        time.sleep(BASE_DELAY_S)

    print(
        f"\nwave done: {hits} added, {misses} genuine misses, {skips} rate-limit skips "
        f"(retry next wave). Files updated: {len(dirty)}."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
