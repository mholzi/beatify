#!/usr/bin/env python3
"""Backfill missing per-provider track URIs across Beatify playlists (#1289).

Fills gaps in ``uri_apple_music`` / ``uri_tidal`` / ``uri_deezer`` /
``uri_youtube_music`` for songs that already carry a Spotify ``uri``.

Resolvers
---------
* **Odesli / song.link** (primary, keyless) — one call per track maps the
  Spotify URI to Apple Music + Tidal + Deezer + YouTube in a single response.
  Requested with ``userCountry=DE`` so the country-scoped Apple/Tidal links
  resolve for this DE-centric catalogue. Free tier is ~10 req/min, so calls are
  throttled (``--odesli-sleep``, default 6s) and HTTP 429 is retried with
  exponential backoff.
* **Apple iTunes Search** (secondary for Apple, keyless) — when Odesli returns
  no Apple id, ``https://itunes.apple.com/search`` is queried (diacritic-folded
  + suffix-stripped + alt_artists variants). Every hit passes a fuzzy
  title+artist verify-gate (:func:`titles_match`) before being trusted, so the
  niche catalogue never collects confident-but-wrong Apple URIs.
* **Deezer ISRC** (secondary verify for Deezer) — the undocumented public
  ``https://api.deezer.com/track/isrc:<ISRC>`` endpoint maps a song's ISRC to a
  Deezer track id, used when Odesli has no Deezer link but the song has an ISRC.
* **YouTube** — Odesli's ``youtube`` link is used as a **0-quota first pass**,
  verified via the keyless ``youtube.com/oembed`` endpoint (artist+title must
  appear) to filter covers/live re-uploads. Only when that fails or is absent
  does the expensive **YouTube Data API ``search.list``** (100 quota units)
  run. A resume-cursor in the state file caps each run at a daily budget
  (``--youtube-budget``, default 90) and resumes across runs/days. Needs
  ``YOUTUBE_API_KEY``; absent → the phase is skipped (never crashes).

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
from datetime import datetime, timezone
import importlib.util
import os
import re
import sys
import time
import unicodedata
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
# Fuzzy title/artist matching (pure, unit-tested)
# ---------------------------------------------------------------------------
# Ported from ``custom_components/beatify/game/text_match.py`` so the backfill
# script stays standalone (no HA-runtime import). Used as the verify-gate for
# the keyless iTunes / YouTube-oembed resolvers below: a fuzzy title+artist
# match is required before a resolved id is trusted, otherwise the niche
# (Polish/Eurovision/…) catalogue collects confident-but-wrong URIs.

# NFD does not decompose these to base + combining mark, so fold them first.
_ASCII_FOLD = str.maketrans(
    {
        "ł": "l",
        "Ł": "l",
        "ø": "o",
        "Ø": "o",
        "đ": "d",
        "Đ": "d",
        "ß": "ss",
        "æ": "ae",
        "Æ": "ae",
        "œ": "oe",
        "Œ": "oe",
    }
)
_FEAT_RE = re.compile(r"\s+(?:feat\.?|ft\.?)\s+.*$", re.IGNORECASE)
_PARENTHETICAL_RE = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]\s*$")
_DASH_SUFFIX_RE = re.compile(r"\s+-\s+.*$")
_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WHITESPACE_RE = re.compile(r"\s+")
_LEADING_ARTICLE_RE = re.compile(r"^(?:the|a|an)\s+")
# Trennt die Namen in einem Katalog-``artist``-Feld. Spotify liefert alle
# Credits als EINEN String, mal komma-, mal semikolon-getrennt.
_ARTIST_SPLIT_RE = re.compile(r"\s*[;,]\s*")

# Keyless resolver endpoints (queried in the network helpers below).
ITUNES_SEARCH = "https://itunes.apple.com/search"
YOUTUBE_OEMBED = "https://www.youtube.com/oembed"
_YT_WATCH_ID_RE = re.compile(r"[?&]v=([A-Za-z0-9_-]{11})")
_YT_SHORT_ID_RE = re.compile(r"youtu\.be/([A-Za-z0-9_-]{11})")


def strip_diacritics(text: str) -> str:
    """Return ``text`` with diacritics folded to ASCII (ł→l, ż→z, ó→o, é→e)."""
    folded = (text or "").translate(_ASCII_FOLD)
    decomposed = unicodedata.normalize("NFD", folded)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def strip_suffixes(text: str) -> str:
    """Strip ``feat.``/``ft.``, trailing ``(…)``/``[…]`` and `` - <suffix>``.

    Case-preserving (used to build search queries), so applied before lowercase.
    """
    r = _FEAT_RE.sub("", text or "")
    r = _DASH_SUFFIX_RE.sub("", r)
    r = _PARENTHETICAL_RE.sub("", r)
    return _WHITESPACE_RE.sub(" ", r).strip()


def normalize_title(text: str) -> str:
    """Aggressive normalization for equality: fold, strip qualifiers + punct."""
    if not text:
        return ""
    r = strip_diacritics(text.lower())
    r = _FEAT_RE.sub("", r)
    r = _DASH_SUFFIX_RE.sub("", r)
    r = _PARENTHETICAL_RE.sub("", r)
    r = _PUNCT_RE.sub(" ", r)
    r = _WHITESPACE_RE.sub(" ", r).strip()
    return _LEADING_ARTICLE_RE.sub("", r)


def _normalize_loose(text: str) -> str:
    """Light normalization that KEEPS qualifiers (for YouTube oembed titles.

    A YouTube title is usually ``Artist - Title (Official Video)`` — the ``-``
    and parenthetical carry the real title, so the aggressive ``normalize_title``
    would wrongly discard it. Loose = lowercase + fold + de-punct + collapse.
    """
    if not text:
        return ""
    r = strip_diacritics(text.lower())
    r = _PUNCT_RE.sub(" ", r)
    return _WHITESPACE_RE.sub(" ", r).strip()


def levenshtein(a: str, b: str) -> int:
    """Levenshtein edit distance (pure two-row DP, no dependencies)."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(
                min(
                    current[j - 1] + 1,
                    previous[j] + 1,
                    previous[j - 1] + (0 if ca == cb else 1),
                )
            )
        previous = current
    return previous[-1]


def titles_match(a: str, b: str) -> bool:
    """Fuzzy equality of two title/artist strings after ``normalize_title``.

    True when the normalized forms are equal or within a length-scaled edit
    budget (~1 edit per 5 chars, min 1) — tolerant of a stray remaster tag or
    typo, strict enough to reject a different song. Empty either side → False.
    """
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    budget = max(1, min(len(na), len(nb)) // 5)
    return levenshtein(na, nb) <= budget


def _tokens_present(needle: str, hay: str, *, min_len: int = 3) -> bool:
    """True if every significant token of ``needle`` appears in ``hay`` (loose)."""
    toks = [t for t in needle.split() if len(t) >= min_len] or needle.split()
    if not toks:
        return False
    hay_set = set(hay.split())
    return all(t in hay_set for t in toks)


def split_credited_artists(artist: str) -> list[str]:
    """Split a catalogue ``artist`` credit string into the individual names.

    The catalogue stores every credited Spotify artist in ONE field, joined by
    a comma or a semicolon: ``"Justin Bieber, Nicki Minaj"``,
    ``"Tanel Padar;Dave Benton"``. Nothing else in the pipeline needs the parts,
    so this is deliberately dumb — it splits, it does not try to understand.
    """
    return [p.strip() for p in _ARTIST_SPLIT_RE.split(artist or "") if p.strip()]


def _lead_artist_with_features(artist: str, r_artist: str, r_title: str) -> bool:
    """Accept an iTunes hit that credits only the LEAD of a multi-artist track.

    The mismatch this repairs (#2211): the catalogue names every artist in one
    joined string, iTunes names only the lead in ``artistName`` and pushes the
    guests into ``trackName`` — ``"Justin Bieber, Nicki Minaj"`` versus
    ``"Justin Bieber"`` + ``"Beauty and a Beat (feat. Nicki Minaj)"``. Compared
    head-on the two artist strings blow the edit budget of :func:`titles_match`,
    so a plainly correct match was discarded. Measured on 2026-08-17 over a
    random sample of 25 of the 185 open Apple gaps: 7 rejections came from this
    comparison, 6 of them on the right recording.

    True only when BOTH halves hold:

    1. the iTunes artist matches the **first** catalogue name, and
    2. every remaining catalogue name shows up on the iTunes side — in the
       track title (``feat. …``) or in the artist string (``A & B``).

    Half 2 is what keeps this from being a loosening. Without it the rule would
    accept a solo re-release of the same title as the featured version. It is
    also why a band whose own name carries a comma is safe: splitting
    ``"Earth, Wind & Fire"`` yields a "guest" ``"Wind & Fire"`` that no iTunes
    row will carry, so the rule simply never fires and the existing checks
    decide alone.

    The single-name case returns False on purpose. When the catalogue credits
    one artist and iTunes credits another as lead — Kayah's *Śpij Kochanie Śpij*
    against ``kk8 — Śpij Kochanie Śpij (feat. Kayah)`` — that is a different
    recording, and the gate is right to refuse it.
    """
    names = split_credited_artists(artist)
    if len(names) < 2:
        return False
    lead, guests = names[0], names[1:]
    gate = _gate()
    lead_ok = titles_match(r_artist, lead) or (
        gate is not None and gate.artist_matches(lead, r_artist)
    )
    if not lead_ok:
        return False
    hay = _normalize_loose(f"{r_title} {r_artist}")
    return all(_tokens_present(_normalize_loose(g), hay) for g in guests)


def _dedup(items: list[str]) -> list[str]:
    """Order-preserving de-dup of non-empty strings."""
    out: list[str] = []
    for it in items:
        if it and it not in out:
            out.append(it)
    return out


# ---------------------------------------------------------------------------
# Shared verify-gate (scripts/uri_gate.py)
# ---------------------------------------------------------------------------
# Dieses Skript und scripts/backfill_apple.py entscheiden dieselbe Frage — ist
# der Suchtreffer wirklich unsere Aufnahme — und taten es in zwei verschiedenen
# Formen. Am 11.08.2026 gemessen: `normalize_title` entfernt Klammerzusaetze,
# bevor es vergleicht, also sind "The Night" und "The Night (Extended Mix)" fuer
# dieses Gate identisch. Genau diese Regression hat #1980 im Apple-Skript
# behoben — und der Apple-Backfill-Agent faehrt DIESES Skript.
#
# Die gemeinsamen Bausteine liegen deshalb in scripts/uri_gate.py und werden hier
# per Pfad geladen (weder `scripts/` noch dieses Verzeichnis sind ein Package).
# Der Pfad ist aus der Dateilage abgeleitet, nicht aus --repo-root: der Import
# passiert vor dem Argument-Parsing.
_GATE: Any = None
_GATE_WARNED = False


def _gate() -> Any:
    """Load ``scripts/uri_gate.py`` once; ``None`` when it is unavailable.

    A missing gate must not stop a backfill run — but it must be loud. Silent
    degradation to the weaker rules is exactly the failure mode this project
    keeps getting bitten by, so the fallback prints once and says what it means.
    """
    global _GATE, _GATE_WARNED
    if _GATE is not None:
        return _GATE
    # Nach oben laufen statt eine Ebenenzahl zu raten: der erste Versuch stand auf
    # parents[3] und traf .claude/scripts/uri_gate.py — die Warnung unten hat das
    # sofort gezeigt, was genau ihr Zweck ist. Die Suche ueberlebt auch, wenn das
    # Skill-Verzeichnis einmal verschoben wird.
    here = Path(__file__).resolve()
    path = None
    for parent in here.parents:
        candidate = parent / "scripts" / "uri_gate.py"
        if candidate.is_file():
            path = candidate
            break
    if path is None:
        if not _GATE_WARNED:
            print(
                "WARNUNG: scripts/uri_gate.py oberhalb von "
                f"{here} nicht gefunden — das Gate faellt auf die schwaechere "
                "Fuzzy-Regel zurueck und kann einen Remix nicht vom Original "
                "unterscheiden.",
                file=sys.stderr,
            )
            _GATE_WARNED = True
        return None
    try:
        spec = importlib.util.spec_from_file_location("beatify_uri_gate", path)
        if spec is None or spec.loader is None:
            raise ImportError(f"kein Loader fuer {path}")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["beatify_uri_gate"] = mod
        spec.loader.exec_module(mod)
        _GATE = mod
    except Exception as exc:  # pragma: no cover - Umgebungsfehler
        if not _GATE_WARNED:
            print(
                f"WARNUNG: {path} nicht ladbar ({exc}) — das Gate faellt auf die "
                "schwaechere Fuzzy-Regel zurueck und kann einen Remix nicht vom "
                "Original unterscheiden.",
                file=sys.stderr,
            )
            _GATE_WARNED = True
    return _GATE


def _pick_itunes_match(
    results: list[dict], title: str, artist: str, alt_artists: list[str]
) -> str | None:
    """Verify-gate: first iTunes result whose title AND artist fuzzy-match.

    The artist may match the primary ``artist`` OR any ``alt_artists`` entry
    (covers writer/original-performer credits). Returns the numeric trackId of
    the first gate-passing result, else None (never guesses on title alone).
    """
    gate = _gate()
    for r in results or []:
        track_id = _numeric_id(r.get("trackId"))
        if not track_id:
            continue
        r_title = r.get("trackName") or r.get("trackCensoredName") or ""
        r_artist = r.get("artistName") or ""
        if not titles_match(r_title, title):
            continue
        # Suffix-Pruefung. `titles_match` sieht Klammerzusaetze nicht, weil
        # `normalize_title` sie entfernt — ohne diese Zeile nimmt das Gate einen
        # Extended Mix als Original an (gemessen 11.08.2026 an drei Faellen).
        if gate is not None:
            clash = gate.suffix_conflict(title, r_title)
            if clash:
                continue
        artist_ok = titles_match(r_artist, artist) or any(
            titles_match(r_artist, alt) for alt in (alt_artists or [])
        )
        # Schreibweisen-Varianten als ZUSATZ, nicht als Ersatz: punktierte
        # Abkuerzungen (Run-DMC / Run-D.M.C.) und Uebermengen (Jimi Hendrix in
        # The Jimi Hendrix Experience) scheitern an der Editierdistanz.
        if not artist_ok and gate is not None:
            artist_ok = gate.artist_matches(artist, r_artist) or any(
                gate.artist_matches(alt, r_artist) for alt in (alt_artists or [])
            )
        # Feature-Regel als LETZTE Stufe, nicht als Ersatz: greift nur, wenn
        # `artist` mehrere Namen fuehrt und iTunes bloss den ersten nennt, die
        # uebrigen aber nachweislich mitfuehrt (#2211). `alt_artists` faengt das
        # nicht ab — das Feld meint Coverversionen, keine Features.
        if not artist_ok:
            artist_ok = _lead_artist_with_features(artist, r_artist, r_title)
        if artist_ok:
            return track_id
    return None


def odesli_youtube_video_id(payload: dict) -> str | None:
    """Extract an 11-char YouTube video id from an Odesli response, if any."""
    links = (payload or {}).get("linksByPlatform", {}) or {}
    for key in ("youtubeMusic", "youtube"):
        url = (links.get(key) or {}).get("url")
        if not url:
            continue
        m = _YT_WATCH_ID_RE.search(url) or _YT_SHORT_ID_RE.search(url)
        if m:
            return m.group(1)
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
# Per-Provider-Miss-Cache (pure, unit-tested)
#
# Bis 2026-08-13 fragten Apple, Deezer und YouTube bei JEDEM Lauf jeden noch
# offenen Song erneut bei Odesli ab. `backfill_tidal.py` merkt sich seit jeher,
# welche Tracks der Anbieter nachweislich nicht hat, und ueberspringt sie —
# hier fehlte das Gegenstueck, und die Laeufe verbrannten ihr Odesli-Kontingent
# auf Absagen, die schon bekannt waren.
#
# Zwei Eigenheiten, die den Cache von backfill_tidal.py unterscheiden:
#
#   1. **Pro Provider, nicht pro Track.** Ein Song kann bei Deezer fehlen und
#      bei Apple existieren. Ein Cache auf Track-Ebene wuerde die noch
#      offenen Provider desselben Songs mit abwuergen.
#   2. **Nur eintragen, was wirklich versucht wurde.** Ist Odesli nicht
#      erreichbar (429, Netzfehler -> ``payload is None``), darf KEIN Miss
#      geschrieben werden. Sonst wird aus "gerade gesperrt" dauerhaft "gibt es
#      nicht" — genau der Fehler, den backfill_tidal.py im Kopf seiner Datei
#      ausdruecklich ausschliesst.
#
# Anders als bei Tidal verfaellt ein Miss hier nach ``--miss-ttl-days`` (Vorgabe
# 90). Ein Anbieter, der einen Song spaeter aufnimmt, wird dadurch von selbst
# wiedergefunden.
# ---------------------------------------------------------------------------
MISS_TTL_DAYS_DEFAULT = 90


def load_provider_misses(path: Path) -> dict:
    """Return the per-provider miss map from the shared state file."""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    misses = data.get("provider_misses")
    return misses if isinstance(misses, dict) else {}


def save_provider_misses(path: Path, misses: dict) -> None:
    """Persist the miss map, leaving every other key of the file untouched."""
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            data = {}
    data["provider_misses"] = misses
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def _miss_is_fresh(stamp: str, now: datetime, ttl_days: int) -> bool:
    """True if ``stamp`` is a parsable timestamp within ``ttl_days`` of now."""
    if ttl_days <= 0:
        return True
    try:
        then = datetime.strptime(stamp, "%Y-%m-%dT%H:%MZ")
    except (TypeError, ValueError):
        return False  # unparsable -> treat as expired, i.e. query again
    return (now - then).days < ttl_days


def filter_cached_misses(
    gaps: list[str],
    uri: str,
    misses: dict,
    now: datetime,
    ttl_days: int = MISS_TTL_DAYS_DEFAULT,
    retry_misses: bool = False,
) -> list[str]:
    """Drop providers already recorded as a fresh miss for ``uri``.

    Returns the gaps still worth querying. ``retry_misses`` disables the cache
    entirely; an expired or unparsable entry is treated as "ask again".
    """
    if retry_misses or not gaps:
        return list(gaps)
    entry = misses.get(uri) or {}
    return [g for g in gaps if not _miss_is_fresh(entry.get(g, ""), now, ttl_days)]


# Provider, die auch ohne Odesli einen eigenen Aufloesungsweg haben:
# Apple ueber die iTunes-Suche, Deezer ueber ISRC bzw. Deezer-Suche.
# Beide stehen im Code ausserhalb des ``payload``-Blocks.
ODESLI_INDEPENDENT = ("apple_music", "deezer")


def attempted_providers(non_yt_gaps: list[str], odesli_ok: bool) -> list[str]:
    """Welche Provider wurden in diesem Durchgang wirklich befragt?

    Antwortet Odesli (``odesli_ok``), gilt das fuer alle offenen Provider.
    Ist Odesli nicht erreichbar, wurden nur die beiden Wege gegangen, die
    unabhaengig davon laufen — fuer alle anderen darf KEIN Miss entstehen,
    sonst wird aus einer Sperre eine dauerhafte Absage.
    """
    if odesli_ok:
        return list(non_yt_gaps)
    return [g for g in non_yt_gaps if g in ODESLI_INDEPENDENT]


def record_provider_misses(
    misses: dict,
    uri: str,
    attempted: list[str],
    song: dict,
    now: datetime,
    http_status: int | None = None,
) -> int:
    """Record a miss for every attempted provider still unfilled. Returns count.

    ``attempted`` must contain only providers that were genuinely queried this
    run — never ones skipped because the source was unavailable.

    ``http_status`` is the code behind the refusal, or ``None`` when the source
    answered cleanly and simply had no link. It is stored alongside the
    timestamp so a later incident can be told apart from a genuine "no".
    """
    stamp = now.strftime("%Y-%m-%dT%H:%MZ")
    n = 0
    for prov in attempted:
        field = PROVIDER_FIELDS.get(prov)
        if not field or (song.get(field) or "").strip():
            continue
        # Wert ist ``{"at": <stamp>, "http": <code|None>}`` statt eines nackten
        # Zeitstempels (21.08.2026). Der Code ist die einzige Spur, an der sich
        # ein spaeterer Vorfall wieder aufraeumen laesst: als Odesli am 19.08.
        # begann, jede Anfrage mit 401 zu beantworten, war der Tidal-Speicher
        # reparierbar, WEIL er den Code fuehrte — 238 vergiftete Eintraege liessen
        # sich exakt greifen. Dieser Speicher fuehrte nur einen Zeitstempel; ein
        # gleichartiger Vorfall waere hier unsichtbar geblieben.
        #
        # Alte Eintraege sind blosse Strings. Leser duerfen deshalb NICHT davon
        # ausgehen, einen dict zu bekommen — ``pick_target_playlist.py`` liest
        # ohnehin nur die Schluessel und ist von der Form unberuehrt.
        misses.setdefault(uri, {})[prov] = {"at": stamp, "http": http_status}
        n += 1
    return n


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
    """Call Odesli for one Spotify track. Throttles + backs off on HTTP 429.

    Returns the parsed JSON on success, or ``None`` when the track can't be
    resolved right now (429 that exhausts its backoff retries, 404, any other
    HTTP status, or a transient network/parse error). It **never raises** — a
    raise here would abort the whole run, discard all partial progress and
    never reach the independent YouTube phase (#1687). A ``None`` simply skips
    Odesli for this song; the next wave retries it (idempotent, matching
    ``scripts/backfill_tidal.py``).
    """
    spotify_url = f"https://open.spotify.com/track/{spotify_id}"
    # ``userCountry=DE`` pins Odesli's ``linksByPlatform`` to the German
    # storefront. Odesli's Apple/Tidal links are country-scoped, so omitting it
    # made Apple/Tidal resolve worse for this DE-centric catalogue than
    # ``scripts/backfill_tidal.py`` (which always passes it). See #1687-followup.
    api = "https://api.song.link/v1-alpha.1/links?" + urllib.parse.urlencode(
        {"url": spotify_url, "userCountry": "DE"}
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
            # 429 with retries exhausted, 404, or any other HTTP status: skip
            # this provider for this song (do NOT raise / abort the run).
            return None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            # Transient network / parse error → skip, retry next wave.
            return None
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


def deezer_search(
    term: str, *, limit: int = 5, getter: Callable[[str], dict] = _http_get_json
) -> list[dict]:
    """Call the keyless Deezer search API. Returns ``data`` or ``[]``.

    Never raises: any HTTP/network/parse error → ``[]`` (same contract as
    :func:`itunes_search`).
    """
    q = urllib.parse.urlencode({"q": term, "limit": limit})
    try:
        data = getter(f"https://api.deezer.com/search?{q}")
    except Exception:
        return []
    if not data or data.get("error"):
        return []
    return data.get("data") or []


def _pick_deezer_match(
    results: list[dict], title: str, artist: str, alt_artists: list[str]
) -> str | None:
    """Verify-gate for Deezer hits — mirrors :func:`_pick_itunes_match`.

    Title AND artist must both fuzzy-match; the artist may be the primary one or
    any ``alt_artists`` entry. Never guesses on title alone: "Iron Man" without
    an artist check would happily return a cover band.
    """
    for r in results or []:
        track_id = _numeric_id(r.get("id"))
        if not track_id:
            continue
        r_title = r.get("title_short") or r.get("title") or ""
        r_artist = ((r.get("artist") or {}).get("name")) or ""
        if not titles_match(r_title, title):
            continue
        if titles_match(r_artist, artist) or any(
            titles_match(r_artist, alt) for alt in (alt_artists or [])
        ):
            return track_id
    return None


def resolve_deezer_via_search(
    song: dict, getter: Callable[[str], dict] = _http_get_json
) -> str | None:
    """Resolve a Deezer track id via search + gate, when ISRC and Odesli missed.

    Why this exists: the ISRC endpoint is exact but only as good as the ISRC we
    store. Catalogue rows frequently carry a reissue's ISRC that Deezer does not
    index, while Deezer does hold an earlier remaster of the same recording —
    measured 2026-08-10 on ``greatest-metal-songs``, where "Iron Man",
    "Paranoid", "The Trooper" and "The Number of the Beast" all failed by ISRC
    and all resolved by search. Apple already had this fallback; Deezer did not,
    which is why whole playlists sat at zero Deezer coverage.

    Query strategy mirrors :func:`resolve_apple_via_itunes`: most-specific first,
    deduped, stops at the first gate-pass.
    """
    title = (song.get("title") or "").strip()
    if not title:
        return None
    artist = (song.get("artist") or "").strip()
    alt_artists = song.get("alt_artists") or []

    stripped = strip_suffixes(title)
    titles = _dedup([title, stripped])
    artists = _dedup([a for a in (artist, strip_diacritics(artist)) if a])
    folded_titles = _dedup([strip_diacritics(t) for t in titles])

    terms: list[str] = []
    for a in artists:
        # Deezer's field-scoped syntax is far more precise than a bare term and
        # keeps "Paranoid" from matching a hundred unrelated tracks.
        for t in titles:
            terms.append(f'artist:"{a}" track:"{t}"')
        for t in folded_titles:
            terms.append(f'artist:"{a}" track:"{t}"')
        terms.append(f"{a} {stripped}")
    for alt in alt_artists:
        terms.append(f'artist:"{alt}" track:"{stripped}"')

    seen: set[str] = set()
    for term in terms:
        term = _WHITESPACE_RE.sub(" ", term).strip()
        if not term or term in seen:
            continue
        seen.add(term)
        did = _pick_deezer_match(
            deezer_search(term, getter=getter), title, artist, alt_artists
        )
        if did:
            return did
    return None


def youtube_search_ex(
    api_key: str,
    artist: str,
    title: str,
    getter: Callable[[str], dict] = _http_get_json,
) -> tuple[str | None, str]:
    """search.list for ``artist title``; return ``(video_id, status)``.

    ``status`` is the reason the caller needs and ``youtube_search_id`` throws
    away:

    ``hit``    ein verwertbares Video gefunden
    ``empty``  YouTube hat geantwortet und **nichts** gefunden — eine echte
               Absage, die in den Miss-Cache gehoert
    ``error``  HTTP-/Netz-/Parse-Fehler oder eine unbrauchbare Antwort. Hier
               ist **nichts** ueber den Song gelernt worden; ein Miss waere
               eine Sperre auf Verdacht.

    Die Unterscheidung ist der ganze Zweck der Funktion. Bis zum 15.08.2026
    lieferte ``youtube_search_id`` fuer beide Faelle ``None``, weshalb
    ``record_provider_misses`` YouTube pauschal ausgeschlossen hat — mit der
    Folge, dass eine erfolglos durchsuchte Luecke jeden Lauf erneut Quote
    kostete.
    """
    q = urllib.parse.quote(f"{artist} {title}")
    url = (
        "https://www.googleapis.com/youtube/v3/search"
        f"?part=snippet&type=video&maxResults=1&q={q}&key={api_key}"
    )
    try:
        data = getter(url)
    except Exception:
        # Bewusst breit: HTTPError, URLError, Timeout und JSON-Parsefehler
        # sind hier dasselbe — die Suche hat nicht stattgefunden.
        return None, "error"
    items = (data or {}).get("items") or []
    if not items:
        return None, "empty"
    vid = (items[0].get("id") or {}).get("videoId")
    if vid and _YT_ID.match(vid):
        return vid, "hit"
    # Antwort da, aber unbrauchbar (fehlende/kaputte id). Das ist kein Beleg
    # dafuer, dass es den Song nicht gibt.
    return None, "error"


def youtube_search_id(
    api_key: str,
    artist: str,
    title: str,
    getter: Callable[[str], dict] = _http_get_json,
) -> str | None:
    """search.list for ``artist title``; return the top video id (11 chars)."""
    return youtube_search_ex(api_key, artist, title, getter)[0]


def itunes_search(
    term: str,
    *,
    entity: str = "song",
    limit: int = 5,
    getter: Callable[[str], dict] = _http_get_json,
) -> list[dict]:
    """Call the keyless iTunes Search API. Returns ``results`` or ``[]``.

    Uses ``itunes.apple.com/search`` (public, no key) — NOT the Apple Music
    Developer API, which is token-gated + blocked in this environment.
    Never raises: any HTTP/network/parse error → ``[]``.
    """
    q = urllib.parse.urlencode({"term": term, "entity": entity, "limit": limit})
    try:
        data = getter(f"{ITUNES_SEARCH}?{q}")
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
    ):
        return []
    return (data or {}).get("results") or []


def resolve_apple_via_itunes(
    song: dict, getter: Callable[[str], dict] = _http_get_json
) -> str | None:
    """Resolve an Apple Music track id for ``song`` via iTunes Search + gate.

    Query strategy (most-specific first, deduped, stops at first gate-pass):
      1. ``<artist> <title>`` and a suffix-stripped title (remaster/feat/…).
      2. Diacritic-folded artist/title variants (Polish ł/ż/… → ASCII) — some
         catalogue rows carry accents the storefront index does not.
      3. ``alt_artists`` as a fallback performer when the primary doesn't match.
    Only a result that clears :func:`_pick_itunes_match` is returned.
    """
    title = (song.get("title") or "").strip()
    if not title:
        return None
    artist = (song.get("artist") or "").strip()
    alt_artists = song.get("alt_artists") or []

    stripped = strip_suffixes(title)
    titles = _dedup([title, stripped])
    artists = _dedup([a for a in (artist, strip_diacritics(artist)) if a])
    folded_titles = _dedup([strip_diacritics(t) for t in titles])

    terms: list[str] = []
    for a in artists:
        for t in titles:
            terms.append(f"{a} {t}")
        for t in folded_titles:
            terms.append(f"{a} {t}")
    for alt in alt_artists:
        terms.append(f"{alt} {stripped}")

    seen: set[str] = set()
    for term in terms:
        term = _WHITESPACE_RE.sub(" ", term).strip()
        if not term or term in seen:
            continue
        seen.add(term)
        results = itunes_search(term, getter=getter)
        aid = _pick_itunes_match(results, title, artist, alt_artists)
        if aid:
            return aid
    return None


def youtube_oembed_verify(
    video_id: str,
    artist: str,
    title: str,
    getter: Callable[[str], dict] = _http_get_json,
) -> bool:
    """Verify a YouTube video really is ``artist – title`` via keyless oembed.

    ``youtube.com/oembed`` returns the video ``title`` + channel ``author_name``
    at 0 quota cost. The gate passes only when the expected title AND artist
    tokens are present in that metadata — filtering covers / live / lyric
    re-uploads that Odesli's ``youtube`` link sometimes points at. Any
    HTTP/network/parse error → False (fall back to the paid search.list path).
    """
    watch = f"https://www.youtube.com/watch?v={video_id}"
    q = urllib.parse.urlencode({"url": watch, "format": "json"})
    try:
        data = getter(f"{YOUTUBE_OEMBED}?{q}")
    except (
        urllib.error.HTTPError,
        urllib.error.URLError,
        TimeoutError,
        json.JSONDecodeError,
    ):
        return False
    if not data:
        return False
    hay = _normalize_loose(f"{data.get('author_name', '')} {data.get('title', '')}")
    nt = _normalize_loose(title)
    na = _normalize_loose(artist)
    if not nt:
        return False
    title_ok = nt in hay or _tokens_present(nt, hay)
    artist_ok = (not na) or na in hay or _tokens_present(na, hay)
    return title_ok and artist_ok


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


def bump_version(version: Any) -> str:
    """Bump a playlist ``MAJOR.MINOR`` version (minor +1).

    Catalogue versions are strings like ``"1.8"`` / ``"1.11"`` / ``"0.1"`` — the
    minor part is an integer, not a decimal, so ``1.9 -> 1.10``. Falls back to
    appending ``.1`` for odd/missing values so the bump never crashes a run.
    Identical logic to ``scripts/backfill_tidal.py`` for catalogue consistency.
    """
    if not isinstance(version, str) or not version:
        return "1.1"
    parts = version.split(".")
    if len(parts) >= 2 and parts[-1].isdigit():
        parts[-1] = str(int(parts[-1]) + 1)
        return ".".join(parts)
    return f"{version}.1"


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

    # Run caps, same semantics as scripts/backfill_tidal.py. Without them a single
    # run is unbounded: Odesli's 429 backoff makes duration far less predictable
    # than query count, so a 100-track playlist can outlast any scheduling window
    # a caller reserved for it. Stopping early is safe because every filled URI is
    # flushed to disk per song below.
    queried = 0
    deadline = time.monotonic() + args.max_minutes * 60 if args.max_minutes else None
    stop_reason: str | None = None

    # Per-Provider-Miss-Cache: einmal je Lauf laden, am Ende einmal schreiben.
    # ``run_now`` ist der feste Bezugspunkt fuer Ablauf und Zeitstempel, damit
    # ein langer Lauf nicht mitten drin die TTL-Grenze verschiebt.
    provider_misses = load_provider_misses(state_path)
    run_now = datetime.now(timezone.utc).replace(tzinfo=None)
    miss_skipped = 0
    miss_recorded = 0

    for path in playlist_paths:
        if stop_reason:
            break
        data = json.loads(path.read_text())
        songs = data.get("songs", [])
        cov = coverage_for_playlist(rel_name(root, path), str(path), songs)
        cov.filled_this_run = {p: 0 for p in PROVIDER_FIELDS}
        version_bumped = False

        for song in songs:
            if args.max and queried >= args.max:
                stop_reason = f"reached --max {args.max}"
                break
            if deadline is not None and time.monotonic() >= deadline:
                stop_reason = f"reached --max-minutes {args.max_minutes:g}"
                break
            this_global_idx = global_idx
            global_idx += 1
            sid = spotify_track_id(song.get("uri"))
            gaps = song_gaps(song)
            if not sid or not gaps:
                continue
            # Provider ueberspringen, deren Absage schon bekannt und noch frisch
            # ist. Bleibt nichts uebrig, ist der Song fuer diesen Lauf erledigt,
            # ohne einen einzigen Odesli-Aufruf zu kosten.
            song_uri = (song.get("uri") or "").strip()
            gaps = filter_cached_misses(
                gaps,
                song_uri,
                provider_misses,
                run_now,
                ttl_days=args.miss_ttl_days,
                retry_misses=args.retry_misses,
            )
            if not gaps:
                miss_skipped += 1
                continue

            song_dirty = False
            yt_gap = "youtube_music" in gaps
            non_yt_gaps = [g for g in gaps if g != "youtube_music"]

            # ---- Fast-forward to the YouTube cursor (#2301) -----------------
            # Songs before the cursor were already offered to the YouTube phase
            # in an earlier run. The loop still walked them, paying one Odesli
            # call each — and Odesli is throttled to ``--odesli-sleep`` (6s by
            # default), so a 5-minute slice buys about 50 songs of walking.
            #
            # On 2026-08-22 that ate the window whole. Two runs, seven and five
            # slices, `spent_today` unchanged at 0/90: the YouTube phase had
            # twelve calls available and made none, because the loop never got
            # past the cursor before the deadline. Cursors are not small —
            # edm-anthems sits at 234, 80er-hits at 153.
            #
            # Under ``--youtube-first`` those songs are skipped outright. The
            # non-YouTube gaps they may still carry are not lost: Apple, Deezer
            # and Tidal have their own agents and their own windows. This flag
            # says which job this run is doing.
            if args.youtube_first and yt_gap and this_global_idx < yt_state.cursor:
                continue

            # ---- Odesli (apple/tidal/deezer + free YouTube-first pass) ----
            # Odesli is fetched for the Apple/Tidal/Deezer gaps AND, when a
            # YouTube key is set, to try its ``youtube`` link as a 0-quota
            # first pass before spending an expensive search.list call.
            #
            # That free pass is not free under ``--youtube-first`` (#2301).
            # It costs ``--odesli-sleep`` seconds per song, and the YouTube
            # search sits behind it in the same iteration, so the deadline
            # takes the search first. Measured on 2026-08-22, 15:32: five
            # five-minute slices, three of them reached search.list zero
            # times and the run ended at its 25-minute cap having spent
            # 24 of 90 permitted searches.
            #
            # So when this run exists to fill YouTube and YouTube is the
            # song's only gap, skip Odesli and pay the search directly.
            # The trade is quota for time: 100 units against a wait that
            # currently buys about 50 songs per slice. The other agents
            # (Apple, Deezer, Tidal) run without the flag and keep the
            # free pass unchanged.
            want_odesli = bool(non_yt_gaps) or (
                yt_gap and yt_key and not args.youtube_first
            )
            if want_odesli:
                # Counted before the call, so --max caps attempts rather than
                # successes — a run that only hits 429s must still terminate.
                queried += 1
                # payload is None when Odesli is unavailable (429 exhausted /
                # error) — skip Odesli for this song but keep going so the
                # independent YouTube phase below still runs (#1687).
                payload = fetch_odesli(sid, sleep=args.odesli_sleep)
                if payload is not None:
                    resolved = odesli_to_uris(payload)
                    for prov in non_yt_gaps:
                        val = resolved.get(prov)
                        if val:
                            song[PROVIDER_FIELDS[prov]] = val
                            cov.filled_this_run[prov] += 1
                            song_dirty = True
                    # YouTube free-first: trust Odesli's link only if oembed
                    # confirms artist+title (filters covers/live re-uploads).
                    if yt_gap and yt_key and not song.get("uri_youtube_music"):
                        vid = odesli_youtube_video_id(payload)
                        if vid and youtube_oembed_verify(
                            vid, song.get("artist", ""), song.get("title", "")
                        ):
                            song["uri_youtube_music"] = youtube_uri(vid)
                            cov.filled_this_run["youtube_music"] += 1
                            song_dirty = True
                # Apple iTunes-Search fallback (keyless, verify-gated) whenever
                # Odesli produced no Apple id — including when Odesli is down.
                if "apple_music" in non_yt_gaps and not song.get("uri_apple_music"):
                    aid = resolve_apple_via_itunes(song)
                    if aid:
                        song["uri_apple_music"] = apple_uri(aid)
                        cov.filled_this_run["apple_music"] += 1
                        song_dirty = True
                # Deezer, zwei Stufen, beide AUSSERHALB des ``payload``-Blocks.
                #
                # Die ISRC-Abfrage sass bis 2026-08-10 *innerhalb* — sie lief also nur,
                # wenn Odesli geantwortet hatte. Odesli antwortet aber regelmaessig mit
                # 429 (die stuendliche Tidal-Welle teilt sich dieselbe Quote), und dann
                # bekam Deezer gar nichts: kein Odesli-Link und keine ISRC-Abfrage.
                # Apple lief im selben Lauf weiter, weil sein iTunes-Fallback schon
                # immer hier draussen stand. Genau diese Asymmetrie erklaert Playlists
                # mit voller Apple- und null Deezer-Abdeckung.
                if "deezer" in non_yt_gaps and not song.get("uri_deezer"):
                    did = (
                        fetch_deezer_isrc(song["isrc"]) if song.get("isrc") else None
                    ) or resolve_deezer_via_search(song)
                    if did:
                        song["uri_deezer"] = deezer_uri(did)
                        cov.filled_this_run["deezer"] += 1
                        song_dirty = True
                # Miss nur fuer Provider vormerken, die wirklich befragt
                # wurden. War Odesli nicht erreichbar (``payload is None``),
                # gilt das ausschliesslich fuer die beiden Wege, die davon
                # unabhaengig laufen: Apples iTunes-Suche und Deezers
                # ISRC-/Such-Fallback.
                attempted = attempted_providers(non_yt_gaps, payload is not None)
                miss_recorded += record_provider_misses(
                    provider_misses, song_uri, attempted, song, run_now
                )
                time.sleep(args.odesli_sleep)

            # ---- YouTube Data API search.list (resume-cursor + daily budget) ----
            # Only reached when the free Odesli/oembed pass above did NOT fill
            # YouTube — this is the quota-spending fallback (100 units/call).
            if yt_gap and yt_key and not song.get("uri_youtube_music"):
                if this_global_idx >= yt_state.cursor:
                    if yt_state.can_spend():
                        vid, yt_status = youtube_search_ex(
                            yt_key, song.get("artist", ""), song.get("title", "")
                        )
                        yt_state.spend()
                        yt_state.cursor = this_global_idx + 1
                        if vid:
                            song["uri_youtube_music"] = youtube_uri(vid)
                            cov.filled_this_run["youtube_music"] += 1
                            song_dirty = True
                        elif yt_status == "empty":
                            # Gesucht und nichts gefunden: eine Absage wie
                            # jede andere. NUR dieser Zweig darf einen Miss
                            # schreiben — der Budget-Zweig unten und der
                            # Fehlerfall duerfen es nicht, sonst wird aus
                            # einer Tagesgrenze bzw. einer Stoerung eine
                            # Sperre auf 90 Tage.
                            miss_recorded += record_provider_misses(
                                provider_misses,
                                song_uri,
                                ["youtube_music"],
                                song,
                                run_now,
                            )
                    else:
                        yt_phase_note = (
                            f"daily budget {yt_state.budget} exhausted; "
                            f"resume at song #{yt_state.cursor}"
                        )
                # else: already passed this index in a prior run — leave for the
                # next cursor window; still fall through to the flush below.

            # Incremental flush: persist after every song that changed
            # something, so a later crash / 429 wall never discards prior
            # progress (matching backfill_tidal.py's per-hit save). The
            # playlist ``version`` is bumped once per file on its first write.
            if song_dirty and args.apply:
                if not version_bumped:
                    old_v = data.get("version")
                    data["version"] = bump_version(old_v)
                    version_bumped = True
                path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")

        coverages.append(cov)

    if stop_reason:
        print(f"{stop_reason}, stopping")

    if yt_key:
        save_state(state_path, yt_state)
    # BEWUSST ausserhalb des ``yt_key``-Blocks: Apple und Deezer laufen mit
    # ``--youtube-budget 0`` und ohne API-Key. Stuende das Schreiben unter der
    # Bedingung, wuerde der Cache genau fuer die beiden Agenten nie gefuellt,
    # fuer die er gebaut wurde.
    save_provider_misses(state_path, provider_misses)
    if miss_skipped or miss_recorded:
        print(
            f"miss cache: {miss_skipped} song(s) skipped entirely, "
            f"{miss_recorded} provider miss(es) recorded"
        )

    report = build_report(
        coverages,
        today,
        applied=args.apply,
        yt_phase_note=yt_phase_note,
        stop_reason=stop_reason,
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
    coverages: list[PlaylistCoverage],
    today: str,
    *,
    applied: bool,
    yt_phase_note: str,
    stop_reason: str | None = None,
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
        # A capped run covers only part of the catalogue. Saying so in the report
        # keeps a truncated run from reading like a complete one.
        *(
            [f"> Run stopped early: {stop_reason} — coverage below is partial."]
            if stop_reason
            else []
        ),
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
    p.add_argument(
        "--youtube-first",
        action="store_true",
        help=(
            "Skip songs the YouTube resume cursor has already passed instead of "
            "paying an Odesli call for them. For runs whose purpose is YouTube "
            "(#2301) — without it a short window is spent walking ground the "
            "YouTube phase already covered."
        ),
    )
    p.add_argument(
        "--max",
        type=int,
        default=0,
        help="cap number of Odesli queries this run (0 = no cap)",
    )
    p.add_argument(
        "--max-minutes",
        type=float,
        default=0,
        help="stop the run after this many minutes of wall-clock (0 = no limit)",
    )
    p.add_argument(
        "--retry-misses",
        action="store_true",
        help="ignore the per-provider miss cache and re-query recorded absences",
    )
    p.add_argument(
        "--miss-ttl-days",
        type=int,
        default=MISS_TTL_DAYS_DEFAULT,
        help=(
            "days a recorded miss stays binding before it is retried "
            f"(default: {MISS_TTL_DAYS_DEFAULT}; 0 = never expire)"
        ),
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
