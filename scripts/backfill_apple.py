#!/usr/bin/env python3
"""Backfill missing ``uri_apple_music`` fields in Beatify playlists via iTunes.

Companion to ``backfill_tidal.py``. Same wave-based, idempotent, budget-aware
shape — but a fundamentally different **resolution problem**, which is why the
gate below exists.

Why not ISRC
------------
The obvious route would be ``itunes.apple.com/lookup?isrc=...``, since 94.5% of
the catalogue carries an ISRC. It does not work: the public endpoint answers
HTTP 200 with ``resultCount: 0`` **even for tracks that are demonstrably on
Apple Music**. Verified 2026-07-29 against four control tracks that already
carry a stored ``uri_apple_music`` (Papa Roach "Last Resort", Nickelback,
Creed, 3 Doors Down) — all four returned 0. The parameter is simply not
supported. Reading those zeroes as "not in Apple's catalogue" would be wrong.

So resolution goes through ``/search?term=artist title``, which **guesses**.
Two failure modes were visible in the very first five samples:

  * wrong track  — Frei.Wild "Alles ist weg" -> "Alles, alles was mir..."
  * wrong release — Papa Roach "Last Resort" -> id 1492001883, while the
    catalogue stores 1440907630 (same song, different album)

An ungated backfill would therefore manufacture exactly the ``wrong_track``
defects that the daily playlist-review then has to find and repair. Hence:

The gate
--------
A search result is only accepted when **all** of these hold:

  1. the track's primary artist is **one of** the artists credited in
     ``artistName`` after normalisation (casefold, punctuation stripped,
     ``&``/``and`` unified, ``feat.``-tails cut)
  2. title similarity >= ``--title-threshold`` (default 0.87, difflib ratio on
     normalised titles)
  3. the year in ``releaseDate`` is within ``--year-tolerance`` of ``year``
     (default 1; a release can straddle a year boundary)
  4. no parenthetical suffix on either side names a different recording
     (``suffix_conflict``)

Anything else is **rejected, not guessed**. Rejections are recorded separately
from genuine absences so the two can be told apart later — a rejection may
become resolvable with a better matcher, a miss will not.

Note on rule 1: this is membership, not equality (changed 2026-08-05, #1980).
Apple frequently orders a multi-artist credit differently than the catalogue —
"Tatanka, Zatox & Wild Motherfuckers" for our "Zatox" — and lead-vs-lead
comparison rejected those correct matches. Only the *primary* catalogue artist
is required to be present: Apple moves featured guests into the title, so
demanding the full catalogue set would reject "Harris & Ford, BassWar & CaoX,
Bobby John" against "Harris & Ford & BassWar & CaoX".

Note on rule 3: for old songs that only exist on remaster/compilation albums,
``releaseDate`` is the *reissue* date, so rule 3 will reject some correct
matches. That is deliberate — precision over recall. ``--probe`` reports the
rejection breakdown so the thresholds can be calibrated against real data
before any wave writes anything.

Note on rule 4: rule 2 compares a parenthetical-stripped form as well, so a
suffix on one side alone costs no similarity at all. That is right for
"(2000 Remaster)" and wrong for "(Extended Mix)" — both score 1.00, so **no
threshold can separate them** and the suffix must be inspected directly. Rule 4
accepts a one-sided suffix only when the other title mentions the same words
anywhere ("The Afterlife - Radio Edit" vs "The Afterlife (Radio Edit)") or when
it is recording-neutral per ``_NEUTRAL_SUFFIX_RE``. This costs recall: real
"(Radio Edit)" and "(Extended Version)" catalogue entries now land in
``rejected`` rather than ``hit``. That is the intended direction — they stay
retrievable via ``--retry-rejected``, whereas a wrong URI in the catalogue is
only found again by the daily playlist-review.

State file (``scripts/.apple-backfill-state.json``) maps each Spotify URI to
``{"status": hit|miss|rejected, ...}``:
  * ``hit``      -> accepted and written into the playlist; not re-queried.
  * ``miss``     -> search returned zero results (genuine absence).
  * ``rejected`` -> results came back but none passed the gate; re-queried only
    with ``--retry-rejected`` (e.g. after loosening a threshold).
  * a rate-limit skip is NOT recorded, so the next wave retries it — "throttled"
    must never be confused with "not on Apple Music".

Usage:
    python scripts/backfill_apple.py                      # one wave over all playlists
    python scripts/backfill_apple.py --max 60             # cap queries this run
    python scripts/backfill_apple.py --max-minutes 30     # cap wall-clock this run
    python scripts/backfill_apple.py PATH.json ...        # only the given playlists
    python scripts/backfill_apple.py --dry-run            # list what would be queried, no network
    python scripts/backfill_apple.py --probe PATH.json    # network + gate, NO writes (calibration)
    python scripts/backfill_apple.py --retry-rejected     # re-query previously rejected tracks

Exit code 0 on success (even with partial coverage), 1 on usage/IO error.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PLAYLISTS_DIR = REPO_ROOT / "custom_components" / "beatify" / "playlists"
STATE_PATH = Path(__file__).resolve().parent / ".apple-backfill-state.json"

ITUNES_SEARCH = "https://itunes.apple.com/search"
SPOTIFY_TRACK_RE = re.compile(r"^spotify:track:([A-Za-z0-9]+)$")

# Storefronts tried in order; the first gate-passing result wins. `de` first
# because a large part of the remaining gap is German-language repertoire.
STOREFRONTS = ("de", "us")

# Pacing — iTunes throttles around 20 requests/minute per source address.
BASE_DELAY_S = 3.5
BACKOFF_BASE_S = 10.0
MAX_THROTTLE_ATTEMPTS = 3
REQUEST_TIMEOUT_S = 20

_FEAT_RE = re.compile(r"\s*[\(\[]?\b(feat|ft|featuring|with)\b\.?\s.*$", re.I)
_PAREN_RE = re.compile(r"\s*[\(\[][^)\]]*[)\]]")
_PAREN_CONTENT_RE = re.compile(r"[\(\[]([^)\]]*)[)\]]")
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")
_ARTIST_SPLIT_RE = re.compile(r"\s*[,;/]\s*|\s+(?:&|feat\.?|ft\.?|x|vs\.?)\s+", re.I)

# Parenthetical suffixes that name the same *recording* — packaging or mastering
# wording, not a different take. Only these may appear on one side alone.
# Deliberately a short closed list: every entry here is a licence to accept a
# title the other side does not carry, so it is reviewed in the diff.
_NEUTRAL_SUFFIX_RE = re.compile(
    r"^(?:\d{4}\s+)?(?:digital\s+)?(?:"
    r"remaster(?:ed)?(?:\s+version)?(?:\s+\d{4})?"
    r"|deluxe(?:\s+edition)?"
    r"|album\s+version"
    r"|single\s+version"
    r"|original\s+(?:version|mix)"
    r"|bonus\s+track"
    r"|explicit|clean"
    r")$",
    re.I,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def normalise(text: str, *, drop_parens: bool = False) -> str:
    """Fold a title/artist to a comparable form.

    Deliberately conservative: diacritics are kept (``Böhse`` must not collapse
    onto ``Bohse`` and start matching unrelated artists), only case, punctuation,
    ``&``/``and`` and whitespace are unified.
    """
    if not text:
        return ""
    out = unicodedata.normalize("NFC", text)
    out = _FEAT_RE.sub("", out)
    if drop_parens:
        out = _PAREN_RE.sub("", out)
    out = out.casefold()
    out = out.replace("&", " and ")
    out = _PUNCT_RE.sub(" ", out)
    return _WS_RE.sub(" ", out).strip()


def primary_artist(artist: str) -> str:
    """First credited artist — search results carry the lead artist only."""
    if not artist:
        return ""
    return _ARTIST_SPLIT_RE.split(artist, maxsplit=1)[0]


def artist_set(artist: str) -> set[str]:
    """All credited artists, normalised.

    Split on the raw string, not the normalised one: ``normalise`` turns ``&``
    into ``and``, which would stop it being a separator.
    """
    if not artist:
        return set()
    return {n for n in (normalise(p) for p in _ARTIST_SPLIT_RE.split(artist)) if n}


def parenthetical_suffixes(text: str) -> list[str]:
    """Normalised contents of every ``(...)``/``[...]`` group.

    ``feat.``-tails are cut first — ``normalise`` already handles those, and a
    featured guest is not a different recording.
    """
    if not text:
        return []
    stripped = _FEAT_RE.sub("", unicodedata.normalize("NFC", text))
    out = []
    for raw in _PAREN_CONTENT_RE.findall(stripped):
        norm = normalise(raw)
        if norm:
            out.append(norm)
    return out


def suffix_conflict(a: str, b: str) -> str | None:
    """The first suffix that one title carries and the other does not account for.

    ``title_similarity`` compares a parenthetical-stripped form too, so a suffix
    on one side alone costs nothing — which is right for ``(2000 Remaster)`` and
    wrong for ``(Extended Mix)``. Both reach similarity 1.00, so no threshold can
    separate them; the suffix has to be looked at directly.

    A suffix is fine when either
      * the other side mentions it anywhere in its title (``The Afterlife -
        Radio Edit`` vs ``The Afterlife (Radio Edit)`` — same words, different
        punctuation), or
      * it is recording-neutral per ``_NEUTRAL_SUFFIX_RE``.

    Anything else names a different take and is returned for rejection.
    """
    for src, other in ((a, b), (b, a)):
        other_norm = normalise(other)
        for suffix in parenthetical_suffixes(src):
            if suffix in other_norm:
                continue
            if _NEUTRAL_SUFFIX_RE.match(suffix):
                continue
            return suffix
    return None


def title_similarity(a: str, b: str) -> float:
    """Best ratio over the raw and the parenthetical-stripped forms.

    ``Kryptonite`` vs ``Kryptonite (2000 Remaster)`` should not be punished for
    a suffix that says nothing about track identity. Suffixes that *do* say
    something are caught by ``suffix_conflict``, not here.
    """
    best = difflib.SequenceMatcher(None, normalise(a), normalise(b)).ratio()
    bare = difflib.SequenceMatcher(
        None, normalise(a, drop_parens=True), normalise(b, drop_parens=True)
    ).ratio()
    return max(best, bare)


def release_year(result: dict) -> int | None:
    raw = result.get("releaseDate") or ""
    if len(raw) >= 4 and raw[:4].isdigit():
        return int(raw[:4])
    return None


def evaluate(track: dict, result: dict, *, title_threshold: float,
             year_tolerance: int) -> tuple[bool, str]:
    """Apply the gate. Returns (accepted, reason)."""
    want_artist = normalise(primary_artist(track.get("artist", "")))
    got_artists = artist_set(result.get("artistName", ""))
    # Membership, not equality: Apple often orders a multi-artist credit
    # differently ("Tatanka, Zatox & Wild Motherfuckers" for our "Zatox"), and
    # the lead-artist-only comparison then rejected a correct match. Checking
    # the *primary* catalogue artist rather than the whole catalogue set is
    # deliberate — Apple moves featured guests into the title, so requiring the
    # full set to be present would reject e.g. "Harris & Ford, BassWar & CaoX,
    # Bobby John" against "Harris & Ford & BassWar & CaoX".
    if not want_artist or want_artist not in got_artists:
        return False, f"artist {result.get('artistName')!r} != {track.get('artist')!r}"

    sim = title_similarity(track.get("title", ""), result.get("trackName", ""))
    if sim < title_threshold:
        return False, (
            f"title {result.get('trackName')!r} vs {track.get('title')!r} "
            f"(similarity {sim:.2f} < {title_threshold:.2f})"
        )

    clash = suffix_conflict(track.get("title", ""), result.get("trackName", ""))
    if clash:
        return False, (
            f"suffix {result.get('trackName')!r} vs {track.get('title')!r} "
            f"(unmatched {clash!r})"
        )

    want_year = track.get("year")
    got_year = release_year(result)
    if isinstance(want_year, int) and got_year is not None:
        if abs(got_year - want_year) > year_tolerance:
            return False, (
                f"year {got_year} vs {want_year} (off by {abs(got_year - want_year)} "
                f"> {year_tolerance})"
            )
    return True, f"similarity {sim:.2f}"


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            sys.stderr.write(f"warning: unreadable state {STATE_PATH}, starting fresh\n")
    return {}


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def _bump_version(version) -> str:
    """Bump a playlist ``MAJOR.MINOR`` version (minor +1).

    Minor is an integer, not a decimal, so 1.9 -> 1.10. Mirrors
    ``backfill_tidal.py`` so both jobs move versions the same way.
    """
    if not isinstance(version, str) or not version:
        return "1.1"
    parts = version.split(".")
    if len(parts) >= 2 and parts[-1].isdigit():
        parts[-1] = str(int(parts[-1]) + 1)
        return ".".join(parts)
    return f"{version}.1"


def find_playlists(args_files: list[str]) -> list[Path]:
    if args_files:
        return [Path(f).resolve() for f in args_files]
    return sorted(PLAYLISTS_DIR.rglob("*.json"))


def itunes_search(term: str, storefront: str, limit: int) -> tuple[list[dict], str]:
    """Return (results, outcome) with outcome in 'ok' | 'skip'."""
    url = ITUNES_SEARCH + "?" + urllib.parse.urlencode(
        {"term": term, "entity": "song", "limit": limit, "country": storefront}
    )
    for attempt in range(1, MAX_THROTTLE_ATTEMPTS + 1):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "beatify-apple-backfill"}
            )
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_S) as resp:
                body = resp.read().decode("utf-8", "replace")
            return json.loads(body).get("results", []), "ok"
        except urllib.error.HTTPError as exc:
            if exc.code in (403, 429, 503):
                wait = BACKOFF_BASE_S * attempt
                sys.stderr.write(
                    f"  HTTP {exc.code} backoff {wait:.0f}s (attempt {attempt})\n"
                )
                time.sleep(wait)
                continue
            sys.stderr.write(f"  HTTP {exc.code} -> skip\n")
            return [], "skip"
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            sys.stderr.write(f"  error {exc} -> skip\n")
            return [], "skip"
    return [], "skip"  # throttled out — retry next wave, NOT a miss


def resolve(track: dict, *, title_threshold: float, year_tolerance: int,
            limit: int) -> tuple[str | None, str, str]:
    """Return (apple_uri_or_None, outcome, detail).

    outcome: 'hit' | 'miss' (no results anywhere) | 'rejected' (results, none
    passed the gate) | 'skip' (throttled/transient).
    """
    term = f"{primary_artist(track.get('artist', ''))} {track.get('title', '')}".strip()
    if not term:
        return None, "rejected", "no artist/title to search on"

    saw_any = False
    first_reason = ""
    for storefront in STOREFRONTS:
        results, outcome = itunes_search(term, storefront, limit)
        if outcome == "skip":
            return None, "skip", f"throttled on storefront {storefront}"
        if not results:
            continue
        saw_any = True
        for result in results:
            accepted, reason = evaluate(
                track, result,
                title_threshold=title_threshold, year_tolerance=year_tolerance,
            )
            if accepted:
                tid = result.get("trackId")
                if not tid:
                    continue
                return (
                    f"applemusic://track/{tid}",
                    "hit",
                    f"{storefront}: {result.get('artistName')} – "
                    f"{result.get('trackName')} ({reason})",
                )
            if not first_reason:
                first_reason = f"{storefront}: {reason}"
        time.sleep(BASE_DELAY_S)

    if not saw_any:
        return None, "miss", "no results in any storefront"
    return None, "rejected", first_reason


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Backfill uri_apple_music via iTunes search (gated, idempotent)."
    )
    ap.add_argument("files", nargs="*", help="specific playlist JSON files (default: all)")
    ap.add_argument("--max", type=int, default=0,
                    help="cap number of tracks resolved this run (0 = no cap)")
    ap.add_argument("--max-minutes", type=float, default=0,
                    help="stop the wave after this many minutes of wall-clock (0 = no limit)")
    ap.add_argument("--dry-run", action="store_true",
                    help="list what would be queried, no network/writes")
    ap.add_argument("--probe", action="store_true",
                    help="query + apply the gate but write NOTHING (threshold calibration)")
    ap.add_argument("--retry-rejected", action="store_true",
                    help="also re-query tracks previously rejected by the gate")
    ap.add_argument("--retry-misses", action="store_true",
                    help="also re-query tracks recorded as genuine misses")
    ap.add_argument("--title-threshold", type=float, default=0.87,
                    help="minimum title similarity to accept a match (default 0.87)")
    ap.add_argument("--year-tolerance", type=int, default=1,
                    help="allowed |releaseDate year - track year| (default 1)")
    ap.add_argument("--limit", type=int, default=5,
                    help="search results inspected per storefront (default 5)")
    args = ap.parse_args()

    state = {} if args.dry_run else load_state()
    playlists = find_playlists(args.files)
    if not playlists:
        sys.stderr.write("error: no playlist files found\n")
        return 1

    todo: list[tuple[Path, dict]] = []
    files_cache: dict[Path, dict] = {}
    for pf in playlists:
        try:
            doc = json.loads(pf.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            sys.stderr.write(f"warning: skip unreadable {pf.name}: {exc}\n")
            continue
        files_cache[pf] = doc
        for track in doc.get("songs", []):
            if track.get("uri_apple_music"):
                continue
            if not SPOTIFY_TRACK_RE.match(track.get("uri", "") or ""):
                continue
            prev = state.get(track["uri"], {}).get("status")
            if prev == "miss" and not args.retry_misses:
                continue
            if prev == "rejected" and not args.retry_rejected:
                continue
            todo.append((pf, track))

    mode = " (dry-run)" if args.dry_run else " (probe — no writes)" if args.probe else ""
    print(f"{len(todo)} track(s) missing Apple Music across "
          f"{len(files_cache)} playlist(s){mode}")

    if args.dry_run:
        for pf, track in todo[: args.max or len(todo)]:
            print(f"  WOULD QUERY  {pf.name}: {track.get('artist')} – {track.get('title')}")
        return 0

    hits = misses = rejected = skips = 0
    reject_reasons: dict[str, int] = {}
    processed = 0
    dirty: set[Path] = set()
    deadline = time.monotonic() + args.max_minutes * 60 if args.max_minutes else None

    for pf, track in todo:
        if args.max and processed >= args.max:
            print(f"reached --max {args.max}, stopping")
            break
        if deadline is not None and time.monotonic() >= deadline:
            print(f"reached --max-minutes {args.max_minutes:g}, stopping")
            break
        processed += 1
        uri, outcome, detail = resolve(
            track,
            title_threshold=args.title_threshold,
            year_tolerance=args.year_tolerance,
            limit=args.limit,
        )
        label = f"{track.get('artist')} – {track.get('title')}"
        if outcome == "hit":
            hits += 1
            print(f"  OK        {pf.name}: {label} -> {uri}  [{detail}]")
            if args.probe:
                continue
            track["uri_apple_music"] = uri
            state[track["uri"]] = {"status": "hit", "tried_at": _now_iso()}
            doc = files_cache[pf]
            if pf not in dirty:
                old_v = doc.get("version")
                doc["version"] = _bump_version(old_v)
                print(f"  version   {pf.name}: {old_v} -> {doc['version']}")
            dirty.add(pf)
            pf.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n")
            save_state(state)
        elif outcome == "rejected":
            rejected += 1
            kind = detail.split(" ", 1)[1].split(" ")[0] if " " in detail else detail
            reject_reasons[kind] = reject_reasons.get(kind, 0) + 1
            print(f"  REJECT    {label}  [{detail}]")
            if not args.probe:
                state[track["uri"]] = {"status": "rejected", "tried_at": _now_iso(),
                                       "reason": detail}
                save_state(state)
        elif outcome == "miss":
            misses += 1
            print(f"  no apple  {label}")
            if not args.probe:
                state[track["uri"]] = {"status": "miss", "tried_at": _now_iso()}
                save_state(state)
        else:
            skips += 1
        time.sleep(BASE_DELAY_S)

    print(f"\nwave done: {hits} accepted, {rejected} rejected by gate, "
          f"{misses} genuine misses, {skips} throttle skips (retry next wave). "
          f"Files updated: {len(dirty)}.")
    if reject_reasons:
        print("rejections by kind:")
        for kind, count in sorted(reject_reasons.items(), key=lambda kv: -kv[1]):
            print(f"  {count:4d}  {kind}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
