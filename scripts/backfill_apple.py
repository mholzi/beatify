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

Two-stage search (2026-08-08)
-----------------------------
The gate can only judge what the search returns, and the search term used to be
the primary artist plus the **full** title. iTunes ranks on the whole string, so
a distinctive parenthetical outweighs the song title: ``Sub Zero Project Stand
Strong (Q-BASE 2017 Hangar OST)`` answers with ``E-Force – Salute (Q-Base 2018
Hangar Ost)`` in both storefronts — different artist, different song, different
year — while the correct track never appears at all. Dropping the suffix puts
``Stand Strong (feat. Meccah Dawn)`` at rank 1 in ``de`` and ``us``.

``search_terms`` therefore yields the historical term first and, only when the
title actually carries a parenthetical, a second one without it. Stage 1 is
unchanged and still wins on a tie, so this can only add matches, never move an
existing one. **The gate is untouched** — stage 2 widens what it gets to see,
not what it accepts.

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
import importlib.util
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

# Separators a stripped parenthetical can leave dangling at the end of a title.
_TRAILING_SEP_RE = re.compile(r"[\s\-–—/,:;]+$")

# Die Gate-Bausteine liegen seit 2026-08-11 in scripts/uri_gate.py, damit der
# All-rounder sie mitbenutzen kann statt sie zu kopieren. `scripts/` ist kein
# Package, deshalb der Pfad-Import — dieselbe Technik, die auch die Tests nutzen.
_GATE_PATH = Path(__file__).resolve().parent / "uri_gate.py"
_gate_spec = importlib.util.spec_from_file_location("beatify_uri_gate", _GATE_PATH)
uri_gate = importlib.util.module_from_spec(_gate_spec)
sys.modules["beatify_uri_gate"] = uri_gate
_gate_spec.loader.exec_module(uri_gate)

_NEUTRAL_SUFFIX_RE = uri_gate._NEUTRAL_SUFFIX_RE
_SOUNDTRACK_ORIGIN_RE = uri_gate._SOUNDTRACK_ORIGIN_RE
_PAREN_RE = uri_gate._PAREN_RE
_ARTIST_SPLIT_RE = uri_gate._ARTIST_SPLIT_RE
_WS_RE = uri_gate._WS_RE
normalise = uri_gate.normalise
primary_artist = uri_gate.primary_artist
artist_set = uri_gate.artist_set
artist_matches = uri_gate.artist_matches
parenthetical_suffixes = uri_gate.parenthetical_suffixes
suffix_conflict = uri_gate.suffix_conflict


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")


def strip_parentheticals(text: str) -> str:
    """Title without its ``(...)``/``[...]`` groups and the debris they leave.

    Only for building a *search* term — the gate keeps comparing full titles.
    Trailing separators matter: ``Lost in Dreams (Q-BASE 2017 Warehouse OST) -
    (D-Fence Remix)`` would otherwise become ``Lost in Dreams -`` and carry the
    dangling dash into the query.
    """
    if not text:
        return ""
    out = _PAREN_RE.sub(" ", text)
    out = _WS_RE.sub(" ", out).strip()
    return _TRAILING_SEP_RE.sub("", out).strip()


def search_terms(track: dict) -> list[str]:
    """Query strings to try, most specific first.

    Stage 1 is the historical term (primary artist + **full** title). Stage 2
    drops the parenthetical groups, and exists because iTunes ranks on the whole
    string: a distinctive event suffix outweighs the song title and can return a
    wholly unrelated track, so the right candidate never reaches the gate.

    The case this was built from — ``Sub Zero Project`` / ``Stand Strong
    (Q-BASE 2017 Hangar OST)``. With the suffix, Apple answers with two
    ``E-Force – Salute (Q-Base 2018 Hangar Ost)`` rows in both storefronts:
    different artist, different song, different year. Without it, the correct
    ``Stand Strong (feat. Meccah Dawn)`` is rank 1 in ``de`` **and** ``us``.

    Stage 2 is skipped when it would repeat stage 1, so titles without a
    parenthetical cost no extra request.
    """
    artist = primary_artist(track.get("artist", "") or "")
    title = (track.get("title", "") or "").strip()
    terms: list[str] = []
    full = f"{artist} {title}".strip()
    if full:
        terms.append(full)
    bare = strip_parentheticals(title)
    if bare and bare != title:
        reduced = f"{artist} {bare}".strip()
        if reduced and reduced not in terms:
            terms.append(reduced)
    return terms


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


# ---------------------------------------------------------------------------
# Dauer-Abgleich als Zweitmeinung zum Jahr (#2116)
#
# Gemessen am 13.08.2026 an 22 der 58 Jahres-Ablehnungen aus dem Probe-Lauf vom
# 11./12.08.: bei **14 von 20** auswertbaren Faellen weicht die Spieldauer um
# hoechstens 2 s ab, bei **8** davon um exakt 0 ms — dieselbe Aufnahme, nur mit
# anderem Release-Jahr in den Metadaten.
#
# Entscheidend ist nicht der Anteil, sondern dass das Jahr nicht trennt: die
# Abweichungen der 14 richtigen Treffer lauten 2, 2, 2, 2, 2, 3, 3, 4, 7, 9, 14,
# 19, 34, 43 — und die beiden echten Fehltreffer liegen mit 18 und 23 mitten
# darin. Eine Abweichung von 43 Jahren gehoerte zu einer millisekundengleichen
# Aufnahme, eine von 23 Jahren zu einer Live-Fassung mit 38 s Unterschied.
#
# Die Toleranz von 2 s ist aus den Daten gegriffen: die Treffergruppe endet bei
# 920 ms, der naechste Fall beginnt bei 2303 ms. In dieser Luecke liegt die
# Grenze, sie ist nicht geraten.
#
# Die Dauer ersetzt das Jahr NICHT, sie ueberstimmt es nur in eine Richtung:
# ein Kandidat, den das Jahr verwirft, wird bei passender Dauer doch genommen.
# Umgekehrt wird nie etwas verworfen, das das Jahr akzeptiert haette.
# ---------------------------------------------------------------------------
DURATION_TOLERANCE_MS = 2000
_SPOTIFY_EMBED = "https://open.spotify.com/embed/track/{}"
_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def durations_match(
    ref_ms: object, cand_ms: object, tolerance_ms: int = DURATION_TOLERANCE_MS
) -> bool:
    """True if both durations are known and within ``tolerance_ms``.

    Unknown on either side returns False — eine fehlende Dauer ist kein Beleg
    fuer Gleichheit, und der Kandidat bleibt dann beim Jahres-Urteil.
    """
    if not isinstance(ref_ms, int) or not isinstance(cand_ms, int):
        return False
    if ref_ms <= 0 or cand_ms <= 0:
        return False
    return abs(ref_ms - cand_ms) <= tolerance_ms


def spotify_track_id(uri: object) -> str | None:
    """Extract the bare track id from ``spotify:track:<id>``."""
    if not isinstance(uri, str):
        return None
    m = re.fullmatch(r"spotify:track:([A-Za-z0-9]{10,})", uri.strip())
    return m.group(1) if m else None


def spotify_duration_ms(uri: object, opener=urllib.request.urlopen) -> int | None:
    """Read the reference duration from Spotify's public embed page.

    Keyless und nur auf dem Ablehnungspfad aufgerufen: die Dauer wird erst
    geholt, wenn das Jahres-Gate einen Kandidaten sonst verwerfen wuerde. Bei
    730 Apple-Luecken betraf das im Probe-Lauf 58 Tracks. Jeder Fehler fuehrt
    zu ``None``, also zum unveraenderten Jahres-Urteil.
    """
    tid = spotify_track_id(uri)
    if not tid:
        return None
    req = urllib.request.Request(
        _SPOTIFY_EMBED.format(tid), headers={"User-Agent": "Mozilla/5.0"}
    )
    try:
        raw = opener(req, timeout=20).read().decode("utf-8", "replace")
        m = _NEXT_DATA_RE.search(raw)
        if not m:
            return None
        data = json.loads(m.group(1))
        dur = data["props"]["pageProps"]["state"]["data"]["entity"]["duration"]
    except Exception:  # noqa: BLE001 — jede Stoerung faellt auf das Jahr zurueck
        return None
    return dur if isinstance(dur, int) and dur > 0 else None


def _year_would_reject(track: dict, result: dict, year_tolerance: int) -> bool:
    """True wenn allein das Jahr diesen Kandidaten verwerfen wuerde.

    Vorgeschaltet, damit die Referenzdauer nur dann geholt wird, wenn sie
    ueberhaupt gebraucht wird.
    """
    want_year = track.get("year")
    got_year = release_year(result)
    if not isinstance(want_year, int) or got_year is None:
        return False
    return abs(got_year - want_year) > year_tolerance


def evaluate(
    track: dict,
    result: dict,
    *,
    title_threshold: float,
    year_tolerance: int,
    ref_duration_ms: int | None = None,
    duration_tolerance_ms: int = DURATION_TOLERANCE_MS,
) -> tuple[bool, str]:
    """Apply the gate. Returns (accepted, reason)."""
    want_artist = primary_artist(track.get("artist", "") or "")
    got_credit = result.get("artistName", "") or ""
    # Membership, not equality: Apple often orders a multi-artist credit
    # differently ("Tatanka, Zatox & Wild Motherfuckers" for our "Zatox"), and
    # the lead-artist-only comparison then rejected a correct match. Checking
    # the *primary* catalogue artist rather than the whole catalogue set is
    # deliberate — Apple moves featured guests into the title, so requiring the
    # full set to be present would reject e.g. "Harris & Ford, BassWar & CaoX,
    # Bobby John" against "Harris & Ford & BassWar & CaoX".
    if not artist_matches(want_artist, got_credit):
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
        off = abs(got_year - want_year)
        if off > year_tolerance:
            # Zweitmeinung Dauer (#2116). Nur hier, nur in eine Richtung: was das
            # Jahr durchlaesst, wird nie nachtraeglich verworfen.
            cand_ms = result.get("trackTimeMillis")
            if durations_match(ref_duration_ms, cand_ms, duration_tolerance_ms):
                delta = abs(int(ref_duration_ms) - int(cand_ms))
                return True, (
                    f"similarity {sim:.2f}, Jahr {got_year} vs {want_year} "
                    f"(off by {off}) durch Dauer bestaetigt ({delta} ms Abweichung)"
                )
            return False, (
                f"year {got_year} vs {want_year} (off by {off} > {year_tolerance})"
            )
    return True, f"similarity {sim:.2f}"


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
    url = (
        ITUNES_SEARCH
        + "?"
        + urllib.parse.urlencode(
            {"term": term, "entity": "song", "limit": limit, "country": storefront}
        )
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


def resolve(
    track: dict,
    *,
    title_threshold: float,
    year_tolerance: int,
    limit: int,
    duration_fallback: bool = True,
    duration_tolerance_ms: int = DURATION_TOLERANCE_MS,
    duration_getter=spotify_duration_ms,
) -> tuple[str | None, str, str]:
    """Return (apple_uri_or_None, outcome, detail).

    outcome: 'hit' | 'miss' (no results anywhere) | 'rejected' (results, none
    passed the gate) | 'skip' (throttled/transient).
    """
    terms = search_terms(track)
    if not terms:
        return None, "rejected", "no artist/title to search on"

    saw_any = False
    reason_to_report = ""
    # Referenzdauer hoechstens EINMAL je Track holen, und nur wenn die
    # Zweitmeinung ueberhaupt gefragt ist. `_ref` bleibt "nicht geholt", bis das
    # erste Mal ein Jahr danebenliegt — die grosse Mehrheit der Tracks kostet
    # damit keinen zusaetzlichen Abruf.
    _ref: list = []  # leer = noch nicht geholt; [None] = geholt, nicht lesbar

    def ref_ms() -> int | None:
        if not duration_fallback:
            return None
        if not _ref:
            _ref.append(duration_getter(track.get("uri")))
        return _ref[0]

    for stage, term in enumerate(terms):
        # Tag stage-2 candidates so a rejection cannot be mistaken for a verdict
        # on the full-title query. Kept space-free — main() parses the reason as
        # "<tag>: <kind> ..." to tally the rejection breakdown.
        tag_suffix = "" if stage == 0 else "(bare)"
        stage_reason = ""
        for storefront in STOREFRONTS:
            results, outcome = itunes_search(term, storefront, limit)
            if outcome == "skip":
                return None, "skip", f"throttled on storefront {storefront}"
            if not results:
                continue
            saw_any = True
            for result in results:
                accepted, reason = evaluate(
                    track,
                    result,
                    title_threshold=title_threshold,
                    year_tolerance=year_tolerance,
                    ref_duration_ms=(
                        ref_ms()
                        if _year_would_reject(track, result, year_tolerance)
                        else None
                    ),
                    duration_tolerance_ms=duration_tolerance_ms,
                )
                if accepted:
                    tid = result.get("trackId")
                    if not tid:
                        continue
                    return (
                        f"applemusic://track/{tid}",
                        "hit",
                        f"{storefront}{tag_suffix}: {result.get('artistName')} – "
                        f"{result.get('trackName')} ({reason})",
                    )
                if not stage_reason:
                    stage_reason = f"{storefront}{tag_suffix}: {reason}"
            time.sleep(BASE_DELAY_S)
        # Report the *last* stage that produced candidates. A stage-1 rejection
        # is often a verdict on an unrelated track the suffix dragged in, and
        # recording it hid the real situation: "artist 'E-Force' != 'Sub Zero
        # Project'" read as "Apple credits it differently" when it meant "the
        # search returned something else entirely".
        if stage_reason:
            reason_to_report = stage_reason

    if not saw_any:
        return None, "miss", "no results in any storefront"
    return None, "rejected", reason_to_report


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Backfill uri_apple_music via iTunes search (gated, idempotent)."
    )
    ap.add_argument(
        "files", nargs="*", help="specific playlist JSON files (default: all)"
    )
    ap.add_argument(
        "--max",
        type=int,
        default=0,
        help="cap number of tracks resolved this run (0 = no cap)",
    )
    ap.add_argument(
        "--max-minutes",
        type=float,
        default=0,
        help="stop the wave after this many minutes of wall-clock (0 = no limit)",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="list what would be queried, no network/writes",
    )
    ap.add_argument(
        "--probe",
        action="store_true",
        help="query + apply the gate but write NOTHING (threshold calibration)",
    )
    ap.add_argument(
        "--retry-rejected",
        action="store_true",
        help="also re-query tracks previously rejected by the gate",
    )
    ap.add_argument(
        "--retry-misses",
        action="store_true",
        help="also re-query tracks recorded as genuine misses",
    )
    ap.add_argument(
        "--title-threshold",
        type=float,
        default=0.87,
        help="minimum title similarity to accept a match (default 0.87)",
    )
    ap.add_argument(
        "--year-tolerance",
        type=int,
        default=1,
        help="allowed |releaseDate year - track year| (default 1)",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=5,
        help="search results inspected per storefront (default 5)",
    )
    ap.add_argument(
        "--no-duration-fallback",
        action="store_true",
        help=(
            "disable the duration second opinion (#2116): a candidate rejected "
            "by the year gate stays rejected even when its runtime matches"
        ),
    )
    ap.add_argument(
        "--duration-tolerance-ms",
        type=int,
        default=DURATION_TOLERANCE_MS,
        help=(
            "max |our duration - candidate duration| that overrides a year "
            f"mismatch (default {DURATION_TOLERANCE_MS})"
        ),
    )
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

    mode = (
        " (dry-run)" if args.dry_run else " (probe — no writes)" if args.probe else ""
    )
    print(
        f"{len(todo)} track(s) missing Apple Music across "
        f"{len(files_cache)} playlist(s){mode}"
    )

    if args.dry_run:
        for pf, track in todo[: args.max or len(todo)]:
            print(
                f"  WOULD QUERY  {pf.name}: {track.get('artist')} – {track.get('title')}"
            )
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
            duration_fallback=not args.no_duration_fallback,
            duration_tolerance_ms=args.duration_tolerance_ms,
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
                state[track["uri"]] = {
                    "status": "rejected",
                    "tried_at": _now_iso(),
                    "reason": detail,
                }
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

    print(
        f"\nwave done: {hits} accepted, {rejected} rejected by gate, "
        f"{misses} genuine misses, {skips} throttle skips (retry next wave). "
        f"Files updated: {len(dirty)}."
    )
    if reject_reasons:
        print("rejections by kind:")
        for kind, count in sorted(reject_reasons.items(), key=lambda kv: -kv[1]):
            print(f"  {count:4d}  {kind}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
