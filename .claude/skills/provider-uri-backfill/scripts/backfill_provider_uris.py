#!/usr/bin/env python3
"""Backfill missing per-provider track URIs across Beatify playlists (#1289).

Fills gaps in ``uri_apple_music`` / ``uri_tidal`` / ``uri_deezer`` /
``uri_youtube_music`` for songs that already carry a Spotify ``uri``.

Resolvers
---------
* **Odesli / song.link** (primary, keyless) — one call per track maps the
  Spotify URI to Apple Music + Tidal + Deezer in a single response. Free tier
  is ~10 req/min, so calls are throttled (``--odesli-sleep``, default 6s) and
  HTTP 429 is retried with exponential backoff.
* **Deezer ISRC** (secondary verify for Deezer) — the undocumented public
  ``https://api.deezer.com/track/isrc:<ISRC>`` endpoint maps a song's ISRC to a
  Deezer track id, used when Odesli has no Deezer link but the song has an ISRC.
* **YouTube Data API** (YouTube only) — Odesli's ``youtube`` field is
  unreliable for this catalog, so ``uri_youtube_music`` is filled via
  ``search.list`` (100 quota units each). A resume-cursor in the state file caps
  each run at a daily budget (``--youtube-budget``, default 90) and resumes
  across runs/days. Needs ``YOUTUBE_API_KEY``; absent → the phase is skipped
  with a logged note (never crashes).

Stored URI formats (matched byte-for-byte from existing data — verified live
against Odesli for tidal/deezer; see scripts/PROVIDER_FORMATS below):

    uri_apple_music    applemusic://track/<numeric>
    uri_tidal          tidal://track/<numeric>
    uri_deezer         deezer://track/<numeric>
    uri_youtube_music  https://music.youtube.com/watch?v=<11-char-id>

Safety: defaults to **dry-run** (report only). JSON files are only mutated when
``--apply`` is passed. Running the full backfill at scale is a deliberate
follow-up, not the default.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

# Providers we fill and their stored URI formats. The ``format`` callable turns
# a bare provider track id (string) into the exact stored URI. Keep these in
# sync with scripts/playlist_health-check + validate_playlists.py patterns.
PROVIDER_FIELDS = {
    "apple_music": "uri_apple_music",
    "tidal": "uri_tidal",
    "deezer": "uri_deezer",
    "youtube_music": "uri_youtube_music",
}

USER_AGENT = "beatify-provider-uri-backfill/1.0 (+https://github.com/mholzi/beatify)"


# ---------------------------------------------------------------------------
# Pure URI-format mapping (unit-tested, no network)
# ---------------------------------------------------------------------------
def apple_uri(track_id: str) -> str:
    return f"applemusic://track/{track_id}"


def tidal_uri(track_id: str) -> str:
    return f"tidal://track/{track_id}"


def deezer_uri(track_id: str) -> str:
    return f"deezer://track/{track_id}"


def youtube_uri(video_id: str) -> str:
    return f"https://music.youtube.com/watch?v={video_id}"


_NUMERIC = re.compile(r"^\d+$")
_YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")


def spotify_track_id(uri: str | None) -> str | None:
    """Extract the 22-char track id from ``spotify:track:<id>``."""
    if not uri:
        return None
    m = re.match(r"^spotify:track:([A-Za-z0-9]{22})$", uri)
    return m.group(1) if m else None


def _numeric_id(value: Any) -> str | None:
    """Coerce a provider id (str or int) to a bare numeric string, else None."""
    if value is None:
        return None
    s = str(value).strip()
    return s if _NUMERIC.match(s) else None


def odesli_to_uris(payload: dict) -> dict[str, str]:
    """Map an Odesli ``/links`` response to stored Beatify URIs per provider.

    Returns a dict like ``{"tidal": "tidal://track/123", ...}`` containing only
    the providers we could resolve into a byte-identical stored format. A
    provider whose id can't be confidently extracted is skipped (never guessed).
    """
    out: dict[str, str] = {}
    links = (payload or {}).get("linksByPlatform", {}) or {}
    entities = (payload or {}).get("entitiesByUniqueId", {}) or {}

    def entity_id_for(platform_key: str) -> str | None:
        eid = (links.get(platform_key) or {}).get("entityUniqueId")
        if not eid:
            return None
        return _numeric_id((entities.get(eid) or {}).get("id"))

    # --- Tidal: entity id is numeric (TIDAL_SONG::<id>) ---
    tid = entity_id_for("tidal")
    if tid is None:
        tid = _id_from_url((links.get("tidal") or {}).get("url"), r"/track/(\d+)")
    if tid:
        out["tidal"] = tidal_uri(tid)

    # --- Deezer: entity id is numeric (DEEZER_SONG::<id>) ---
    did = entity_id_for("deezer")
    if did is None:
        did = _id_from_url((links.get("deezer") or {}).get("url"), r"/track/(\d+)")
    if did:
        out["deezer"] = deezer_uri(did)

    # --- Apple Music: best-effort. Odesli keyless responses frequently omit
    # Apple entirely (observed live, 2026-06). When present, the entity/id is
    # the numeric storefront track id used by applemusic://track/<id>. ---
    aid = entity_id_for("appleMusic") or entity_id_for("itunes")
    if aid is None:
        aid = _id_from_url(
            (links.get("appleMusic") or links.get("itunes") or {}).get("url"),
            r"/(?:album/[^/]+/)?(?:i=)?(\d+)(?:[?&]i=(\d+))?",
        )
    if aid:
        out["apple_music"] = apple_uri(aid)

    return out


def _id_from_url(url: str | None, pattern: str) -> str | None:
    if not url:
        return None
    m = re.search(pattern, url)
    if not m:
        return None
    # Prefer the last captured numeric group (e.g. Apple ``?i=<song-id>``).
    for g in reversed(m.groups()):
        if g and _NUMERIC.match(g):
            return g
    return None


# ---------------------------------------------------------------------------
# Gap detection + coverage aggregation (pure, unit-tested)
# ---------------------------------------------------------------------------
@dataclass
class PlaylistCoverage:
    name: str
    path: str
    total: int = 0
    have: dict[str, int] = field(default_factory=dict)
    fillable: int = 0  # songs with spotify uri AND >=1 provider gap
    filled_this_run: dict[str, int] = field(default_factory=dict)


def song_gaps(song: dict) -> list[str]:
    """Provider keys that are missing (null/empty) for this song."""
    return [p for p, fld in PROVIDER_FIELDS.items() if not song.get(fld)]


def coverage_for_playlist(name: str, path: str, songs: list[dict]) -> PlaylistCoverage:
    cov = PlaylistCoverage(name=name, path=path, total=len(songs))
    cov.have = {p: 0 for p in PROVIDER_FIELDS}
    for s in songs:
        for p, fld in PROVIDER_FIELDS.items():
            if s.get(fld):
                cov.have[p] += 1
        if spotify_track_id(s.get("uri")) and song_gaps(s):
            cov.fillable += 1
    return cov


# ---------------------------------------------------------------------------
# Resume-cursor / state accounting (pure, unit-tested)
# ---------------------------------------------------------------------------
@dataclass
class YouTubeBudget:
    """Tracks the YouTube Data API daily budget + resume cursor.

    The cursor is the global index (across the flattened song list) of the next
    song to attempt YouTube resolution for, so runs resume where they stopped.
    """

    budget: int
    spent_today: int = 0
    cursor: int = 0
    date: str = ""

    def remaining(self) -> int:
        return max(0, self.budget - self.spent_today)

    def can_spend(self) -> bool:
        return self.remaining() > 0

    def spend(self) -> None:
        self.spent_today += 1


def load_state(path: Path, today: str, budget: int) -> YouTubeBudget:
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            data = {}
    yt = data.get("youtube", {})
    # Reset the daily counter when the date rolls over; keep the cursor so we
    # resume the catalog scan across days.
    spent = yt.get("spent_today", 0) if yt.get("date") == today else 0
    return YouTubeBudget(
        budget=budget,
        spent_today=spent,
        cursor=yt.get("cursor", 0),
        date=today,
    )


def save_state(path: Path, yt: YouTubeBudget) -> None:
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            data = {}
    data["youtube"] = {
        "date": yt.date,
        "spent_today": yt.spent_today,
        "cursor": yt.cursor,
        "budget": yt.budget,
    }
    path.write_text(json.dumps(data, indent=2) + "\n")


# ---------------------------------------------------------------------------
# HTTP helpers (network; mocked in tests)
# ---------------------------------------------------------------------------
def _http_get_json(url: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_odesli(
    spotify_id: str,
    *,
    sleep: float = 6.0,
    max_retries: int = 4,
    getter: Callable[[str], dict] = _http_get_json,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict | None:
    """Call Odesli for one Spotify track. Throttles + backs off on HTTP 429."""
    spotify_url = f"https://open.spotify.com/track/{spotify_id}"
    api = "https://api.song.link/v1-alpha.1/links?url=" + urllib.parse.quote(
        spotify_url, safe=""
    )
    backoff = sleep
    for attempt in range(max_retries + 1):
        try:
            return getter(api)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < max_retries:
                sleeper(backoff)
                backoff *= 2
                continue
            if e.code == 404:
                return None
            raise
    return None


def fetch_deezer_isrc(
    isrc: str, getter: Callable[[str], dict] = _http_get_json
) -> str | None:
    """Map an ISRC to a Deezer track id via the public endpoint. None if absent."""
    try:
        data = getter(f"https://api.deezer.com/track/isrc:{isrc}")
    except urllib.error.HTTPError:
        return None
    if not data or data.get("error"):
        return None
    return _numeric_id(data.get("id"))


def youtube_search_id(
    api_key: str,
    artist: str,
    title: str,
    getter: Callable[[str], dict] = _http_get_json,
) -> str | None:
    """search.list for ``artist title``; return the top video id (11 chars)."""
    q = urllib.parse.quote(f"{artist} {title}")
    url = (
        "https://www.googleapis.com/youtube/v3/search"
        f"?part=snippet&type=video&maxResults=1&q={q}&key={api_key}"
    )
    try:
        data = getter(url)
    except urllib.error.HTTPError:
        return None
    items = (data or {}).get("items") or []
    if not items:
        return None
    vid = (items[0].get("id") or {}).get("videoId")
    return vid if vid and _YT_ID.match(vid) else None


# ---------------------------------------------------------------------------
# Playlist IO
# ---------------------------------------------------------------------------
def discover_playlists(root: Path) -> list[Path]:
    base = root / "custom_components" / "beatify" / "playlists"
    files = sorted(base.glob("*.json"))
    files += sorted((base / "community").glob("*.json"))
    return files


def rel_name(root: Path, path: Path) -> str:
    base = root / "custom_components" / "beatify" / "playlists"
    return str(path.relative_to(base))


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def run(args: argparse.Namespace) -> int:
    root = Path(args.repo_root).resolve()
    state_path = (
        Path(args.state)
        if args.state
        else (Path(__file__).resolve().parent.parent / ".backfill-state.json")
    )
    today = time.strftime("%Y-%m-%d")
    yt_key = os.environ.get("YOUTUBE_API_KEY")
    yt_state = load_state(state_path, today, args.youtube_budget)

    playlist_paths = discover_playlists(root)
    if args.playlist:
        playlist_paths = [
            p
            for p in playlist_paths
            if p.stem == args.playlist or rel_name(root, p) == args.playlist
        ]
        if not playlist_paths:
            print(f"No playlist matched '{args.playlist}'", file=sys.stderr)
            return 2

    coverages: list[PlaylistCoverage] = []
    # Global flat index for the YouTube resume cursor.
    global_idx = 0
    yt_phase_note = (
        "skipped — YOUTUBE_API_KEY not set"
        if not yt_key
        else f"budget {yt_state.remaining()}/{yt_state.budget} left today, "
        f"cursor at song #{yt_state.cursor}"
    )

    for path in playlist_paths:
        data = json.loads(path.read_text())
        songs = data.get("songs", [])
        cov = coverage_for_playlist(rel_name(root, path), str(path), songs)
        cov.filled_this_run = {p: 0 for p in PROVIDER_FIELDS}
        dirty = False

        for song in songs:
            this_global_idx = global_idx
            global_idx += 1
            sid = spotify_track_id(song.get("uri"))
            gaps = song_gaps(song)
            if not sid or not gaps:
                continue

            # ---- Odesli (apple/tidal/deezer) ----
            non_yt_gaps = [g for g in gaps if g != "youtube_music"]
            if non_yt_gaps:
                payload = fetch_odesli(sid, sleep=args.odesli_sleep)
                resolved = odesli_to_uris(payload or {})
                for prov in non_yt_gaps:
                    val = resolved.get(prov)
                    if val:
                        song[PROVIDER_FIELDS[prov]] = val
                        cov.filled_this_run[prov] += 1
                        dirty = True
                # Deezer secondary verify via ISRC if Odesli missed it.
                if (
                    "deezer" in non_yt_gaps
                    and not song.get("uri_deezer")
                    and song.get("isrc")
                ):
                    did = fetch_deezer_isrc(song["isrc"])
                    if did:
                        song["uri_deezer"] = deezer_uri(did)
                        cov.filled_this_run["deezer"] += 1
                        dirty = True
                time.sleep(args.odesli_sleep)

            # ---- YouTube Data API (resume-cursor + daily budget) ----
            if "youtube_music" in gaps and yt_key:
                if this_global_idx < yt_state.cursor:
                    continue  # already passed this index in a prior run
                if not yt_state.can_spend():
                    yt_phase_note = (
                        f"daily budget {yt_state.budget} exhausted; "
                        f"resume at song #{yt_state.cursor}"
                    )
                    continue
                vid = youtube_search_id(
                    yt_key, song.get("artist", ""), song.get("title", "")
                )
                yt_state.spend()
                yt_state.cursor = this_global_idx + 1
                if vid:
                    song["uri_youtube_music"] = youtube_uri(vid)
                    cov.filled_this_run["youtube_music"] += 1
                    dirty = True

        coverages.append(cov)
        if dirty and args.apply:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")

    if yt_key:
        save_state(state_path, yt_state)

    report = build_report(
        coverages, today, applied=args.apply, yt_phase_note=yt_phase_note
    )
    out_path = (
        Path(args.output) if args.output else (root / "docs" / "provider-coverage.md")
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report)
    print(f"Wrote coverage report → {out_path}")
    print(f"Mode: {'APPLY (wrote JSON)' if args.apply else 'DRY-RUN (report only)'}")
    print(f"YouTube phase: {yt_phase_note}")
    return 0


def build_report(
    coverages: list[PlaylistCoverage], today: str, *, applied: bool, yt_phase_note: str
) -> str:
    label = {
        "apple_music": "Apple",
        "tidal": "Tidal",
        "deezer": "Deezer",
        "youtube_music": "YouTube",
    }
    total = sum(c.total for c in coverages)
    have_tot = {p: sum(c.have[p] for c in coverages) for p in PROVIDER_FIELDS}
    filled_tot = {
        p: sum(c.filled_this_run.get(p, 0) for c in coverages) for p in PROVIDER_FIELDS
    }

    lines = [
        "# Beatify Provider-URI Coverage",
        f"> Generated: {today}",
        f"> Mode: {'APPLY' if applied else 'DRY-RUN (no JSON written)'}",
        f"> YouTube phase: {yt_phase_note}",
        "",
        "## Summary",
        "",
        "| Provider | Have | Total | Coverage | Filled this run |",
        "|---|---:|---:|---:|---:|",
    ]
    for p in PROVIDER_FIELDS:
        pct = (100 * have_tot[p] / total) if total else 0
        lines.append(
            f"| {label[p]} | {have_tot[p]} | {total} | {pct:.1f}% | {filled_tot[p]} |"
        )
    lines += [
        "",
        "## Per-playlist coverage",
        "",
        "| Playlist | Songs | Apple | Tidal | Deezer | YouTube | Filled |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for c in sorted(coverages, key=lambda x: x.name):
        filled = sum(c.filled_this_run.values())
        lines.append(
            f"| {c.name} | {c.total} | "
            f"{c.have['apple_music']} | {c.have['tidal']} | "
            f"{c.have['deezer']} | {c.have['youtube_music']} | "
            f"{filled if filled else ''} |"
        )
    lines.append("")
    lines.append(
        "*Coverage = songs with a non-null URI for that provider. "
        "“Filled” = URIs this run added (0 in dry-run).*"
    )
    return "\n".join(lines) + "\n"


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--repo-root", default=".", help="Beatify repo root (default: cwd)")
    p.add_argument(
        "--playlist", help="Only process this playlist (basename or community/<name>)"
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help="Write filled URIs back to JSON (default: dry-run report only)",
    )
    p.add_argument(
        "--output", help="Coverage report path (default: docs/provider-coverage.md)"
    )
    p.add_argument(
        "--state",
        help="YouTube resume-state file (default: skill/.backfill-state.json)",
    )
    p.add_argument(
        "--odesli-sleep",
        type=float,
        default=6.0,
        help="Seconds between Odesli calls (free tier ~10/min, default 6)",
    )
    p.add_argument(
        "--youtube-budget",
        type=int,
        default=90,
        help="Max YouTube search.list calls per day (default 90)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
