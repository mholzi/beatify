"""Popularity enrichment for the difficulty / familiarity slider.

A local Plex/Jellyfin library has no notion of *global* fame -- only the owner's
personal play counts, which reflect their taste, not how well-known a song is.
For a "how obscure should the songs be?" slider to mean anything, we need an
external popularity signal.

Sources (ALL worldwide -- never the host's play counts):

  * MA-native `metadata.popularity` (0..100): set only by streaming providers
    from their global metrics; preferred when present (free, already local).
  * Deezer public API (no key): track search returns a `rank` integer tracking
    global popularity. The zero-config workhorse for pure-local libraries.
  * Last.fm `track.getInfo` (optional free key): global `listeners`.

Every raw score is mapped onto a common 0..100 GLOBAL FAME scale
(`to_global_score`) and difficulty bands are cut on that ABSOLUTE value
(`absolute_band`). That is the fairness guarantee: "mainstream" means globally
famous, full stop -- a guest is never asked to know the host's niche favourites.
A library-relative percentile is also computed for the optional relative mode.

All pure functions here are unit-tested; only the `async_*` functions touch the
network.
"""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Any
from urllib.parse import quote

_LOGGER = logging.getLogger(__name__)

_DEEZER_SEARCH = "https://api.deezer.com/search"
_LASTFM_API = "https://ws.audioscrobbler.com/2.0/"


# --------------------------------------------------------------------------- #
# Networked enrichment (pool-build time only).
# --------------------------------------------------------------------------- #


def _norm_text(x: str) -> str:
    """Light normalization for match verification (local copy on purpose --
    importing generator._norm_key here would create an import cycle)."""
    import re as _re

    x = x.casefold()
    x = _re.sub(r"[\(\[].*?[\)\]]", " ", x)  # (remaster)/(live)/[mono]
    x = _re.split(r"\bfeat\.?\b|\bft\.?\b", x)[0]  # clip featuring credits
    x = _re.sub(r"[^a-z0-9]+", " ", x).strip()
    # trim common version words from the tail so "cold remastered" == "cold"
    # WITHOUT the startswith looseness that let "cold heart" match "cold".
    _tail = {
        "remaster",
        "remastered",
        "mono",
        "stereo",
        "live",
        "version",
        "edit",
        "single",
        "radio",
        "mix",
        "album",
    }
    words = x.split()
    while words and words[-1] in _tail:
        words.pop()
    return " ".join(words)


def deezer_result_matches(
    query_artist: str, query_title: str, res_artist: str, res_title: str
) -> bool:
    """True when a Deezer search result plausibly IS the queried recording.

    Blindly trusting the first fuzzy result attributed famous songs' ranks to
    obscure library tracks with similar titles (observed on real hardware:
    film-score cues surfacing in "top 5%"). Titles must match after
    normalization (equal, or one extends the other); artists must overlap
    (containment either way -- handles "Artist" vs "Artist & His Orchestra").
    """
    qa, qt = _norm_text(query_artist), _norm_text(query_title)
    ra, rt = _norm_text(res_artist or ""), _norm_text(res_title or "")
    if not qt or not rt or not qa or not ra:
        return False
    # STRICT title equality after normalization + tail-trim. startswith was
    # tried and rejected: it let "Cold Heart" inherit "Cold"'s query.
    title_ok = qt == rt
    artist_ok = qa in ra or ra in qa
    return title_ok and artist_ok


# #2583: `async_deezer_rank` stood here and returned the rank alone. It was
# superseded by `async_deezer_rank_album` below, which returns the rank AND
# the matched album id; pool.py has used only that one for a long time.


async def async_deezer_rank_album(
    session: Any, artist: str, title: str, *, timeout: float = 6.0
) -> tuple[float | None, int | None]:
    """Verified rank AND the matched track's Deezer album id (for genres)."""
    q = quote(f'artist:"{artist}" track:"{title}"')
    url = f"{_DEEZER_SEARCH}?q={q}&limit=5"
    try:
        async with session.get(url, timeout=timeout) as resp:
            if resp.status != 200:
                return None, None
            data = await resp.json()
    except (TimeoutError, asyncio.TimeoutError):
        return None, None
    except Exception:  # noqa: BLE001
        return None, None
    for item in data.get("data") or []:
        res_artist = ((item.get("artist") or {}).get("name")) or ""
        res_title = item.get("title") or item.get("title_short") or ""
        if not deezer_result_matches(artist, title, res_artist, res_title):
            continue
        rank = item.get("rank")
        album_id = (item.get("album") or {}).get("id")
        return (
            float(rank) if isinstance(rank, (int, float)) else None,
            int(album_id) if isinstance(album_id, int) else None,
        )
    return None, None


def parse_deezer_album_genres(data: dict[str, Any]) -> list[str]:
    """Genre names from a Deezer album payload. Pure; [] when none.

    Deezer album genres are coarse (Pop, Rock, Dance, Electro…) — exactly the
    "main types" wanted for the chips. Filters the placeholder 'All' genre.
    """
    out: list[str] = []
    for g in ((data.get("genres") or {}).get("data")) or []:
        name = str((g or {}).get("name") or "").strip()
        if name and name.lower() != "all" and name not in out:
            out.append(name)
    return out[:5]


async def async_deezer_album_genres(
    session: Any, album_id: int, *, timeout: float = 6.0
) -> list[str]:
    """Fetch an album's genres from Deezer. Returns [] on any failure."""
    try:
        async with session.get(
            f"https://api.deezer.com/album/{int(album_id)}", timeout=timeout
        ) as resp:
            if resp.status != 200:
                return []
            return parse_deezer_album_genres(await resp.json())
    except Exception:  # noqa: BLE001
        return []


async def async_lastfm_listeners(
    session: Any, api_key: str, artist: str, title: str, *, timeout: float = 8.0
) -> float | None:
    """Stronger popularity via Last.fm global listener count (needs a key)."""
    params = {
        "method": "track.getInfo",
        "api_key": api_key,
        "artist": artist,
        "track": title,
        "autocorrect": "1",
        "format": "json",
    }
    try:
        async with session.get(_LASTFM_API, params=params, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            data = await resp.json()
    except (TimeoutError, asyncio.TimeoutError):
        return None
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Last.fm error for %s - %s: %s", artist, title, err)
        return None

    track = data.get("track") or {}
    listeners = track.get("listeners")
    try:
        return float(listeners)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# Deezer release-year (SECONDARY external year source).
#
# Used only to recover coverage for tracks MusicBrainz can't match, and only
# when the caller opts in (year_fallback). Deezer's release date is the date of
# the release the track sits on in Deezer's catalog -- for a normal single/album
# that's the real year; for a compilation it can be the pressing year, which is
# why this sits BELOW MusicBrainz in the confidence order. Two calls: a search
# to get the track id, then a track fetch for `release_date`. Pure parsers below
# are unit-tested with mock payloads.
# --------------------------------------------------------------------------- #

_DEEZER_TRACK = "https://api.deezer.com/track"


def parse_deezer_first_track_id(search_data: dict[str, Any]) -> int | None:
    """Pure: pull the first track id from a Deezer /search response."""
    items = search_data.get("data") if isinstance(search_data, dict) else None
    if isinstance(items, list) and items and isinstance(items[0], dict):
        tid = items[0].get("id")
        if isinstance(tid, int):
            return tid
        if isinstance(tid, str) and tid.isdigit():
            return int(tid)
    return None


def parse_deezer_release_year(track_data: dict[str, Any]) -> int | None:
    """Pure: extract a year from a Deezer /track response.

    Prefers the track's own `release_date`; falls back to the album's.
    """
    if not isinstance(track_data, dict):
        return None
    for source in (track_data, track_data.get("album") or {}):
        if not isinstance(source, dict):
            continue
        rd = source.get("release_date")
        if isinstance(rd, str) and len(rd) >= 4 and rd[:4].isdigit():
            year = int(rd[:4])
            if 1900 <= year <= 2100:
                return year
    return None


async def async_deezer_release_year(
    session: Any, artist: str, title: str, *, timeout: float = 8.0
) -> int | None:
    """Resolve a release year from Deezer (search -> track fetch). None on miss."""
    q = quote(f'artist:"{artist}" track:"{title}"')
    try:
        async with session.get(
            f"{_DEEZER_SEARCH}?q={q}&limit=1", timeout=timeout
        ) as resp:
            if resp.status != 200:
                return None
            search_data = await resp.json()
    except (TimeoutError, asyncio.TimeoutError):
        return None
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Deezer year search error for %s - %s: %s", artist, title, err)
        return None

    track_id = parse_deezer_first_track_id(search_data)
    if track_id is None:
        return None

    try:
        async with session.get(f"{_DEEZER_TRACK}/{track_id}", timeout=timeout) as resp:
            if resp.status != 200:
                return None
            track_data = await resp.json()
    except (TimeoutError, asyncio.TimeoutError):
        return None
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Deezer track fetch error for id %s: %s", track_id, err)
        return None

    return parse_deezer_release_year(track_data)


# --------------------------------------------------------------------------- #
# Pure normalization & banding.
# --------------------------------------------------------------------------- #

# Three familiarity bands by percentile (0.0 = most obscure, 1.0 = most famous).
BAND_DEEP_CUT = "deep_cut"
BAND_KNOWN = "known"
BAND_MAINSTREAM = "mainstream"

# Percentile cut points (relative mode). Tunable.
_KNOWN_FLOOR = 1.0 / 3.0
_MAINSTREAM_FLOOR = 2.0 / 3.0

# --------------------------------------------------------------------------- #
# WORLDWIDE fame scale.
#
# The fairness goal (a guest shouldn't have to know the *host's* favourites)
# requires an ABSOLUTE, worldwide popularity scale -- not one relative to the
# host's library. Every raw source is mapped onto a common 0..100 "global fame"
# score, and bands are cut on that absolute value. So "mainstream" means
# globally famous, full stop, regardless of whose library it came from.
# --------------------------------------------------------------------------- #

SOURCE_SCALE_0_100 = "scale_0_100"  # MA metadata.popularity, Spotify, Tidal
SOURCE_DEEZER_RANK = "deezer_rank"
SOURCE_LASTFM_LISTENERS = "lastfm_listeners"

# log10 ceilings: a value at 10**ceiling maps to a global score of 100.
_DEEZER_LOG_CEILING = 6.3  # Deezer rank ~1,000,000 at the very top
_LASTFM_LOG_CEILING = 7.0  # ~10,000,000 listeners at the very top

# Absolute global-score band floors (0..100). Tunable.
_ABS_MAINSTREAM_FLOOR = 60.0
_ABS_KNOWN_FLOOR = 30.0


def to_global_score(raw: float | None, source: str) -> float | None:
    """Map a raw popularity value from any source onto a 0..100 global-fame scale.

    Pure. None stays None. This is what makes the difficulty slider mean the same
    thing -- worldwide recognizability -- no matter which source supplied the data.
    """
    if raw is None:
        return None
    if source == SOURCE_SCALE_0_100:
        return max(0.0, min(100.0, float(raw)))
    if source == SOURCE_DEEZER_RANK:
        return max(
            0.0, min(100.0, math.log10(max(raw, 1.0)) / _DEEZER_LOG_CEILING * 100.0)
        )
    if source == SOURCE_LASTFM_LISTENERS:
        return max(
            0.0, min(100.0, math.log10(max(raw, 1.0)) / _LASTFM_LOG_CEILING * 100.0)
        )
    return None


def absolute_band(global_score: float | None) -> str | None:
    """Band on the ABSOLUTE worldwide fame score (the default, fair mode).

    None score -> None (unknown bucket). This is independent of the host's
    library composition, so a deep-cut in a Top-40 collection and a deep-cut in
    a jazz collection are judged by the same worldwide yardstick.
    """
    if global_score is None:
        return None
    if global_score >= _ABS_MAINSTREAM_FLOOR:
        return BAND_MAINSTREAM
    if global_score >= _ABS_KNOWN_FLOOR:
        return BAND_KNOWN
    return BAND_DEEP_CUT


def assign_percentiles(raw_scores: list[float | None]) -> list[float | None]:
    """Convert raw popularity scores to percentile ranks within the pool.

    Pure function. Songs with a score get a percentile in [0, 1] where 1.0 is
    the most popular in this pool. Songs with no score (None) stay None so the
    caller can bucket them as "unknown" rather than falsely "obscure".

    Ties share the average percentile of their group (standard fractional
    ranking).
    """
    scored_idx = [i for i, s in enumerate(raw_scores) if s is not None]
    out: list[float | None] = [None] * len(raw_scores)
    n = len(scored_idx)
    if n == 0:
        return out
    if n == 1:
        out[scored_idx[0]] = 1.0
        return out

    ordered = sorted(scored_idx, key=lambda i: raw_scores[i])  # type: ignore[arg-type]
    i = 0
    while i < n:
        j = i
        while j + 1 < n and raw_scores[ordered[j + 1]] == raw_scores[ordered[i]]:
            j += 1
        avg_rank = (i + j) / 2.0
        pct = avg_rank / (n - 1)  # normalize to [0, 1]
        for k in range(i, j + 1):
            out[ordered[k]] = pct
        i = j + 1
    return out


def familiarity_band(percentile: float | None) -> str | None:
    """Map a percentile to a band (RELATIVE mode). None -> None (unknown)."""
    if percentile is None:
        return None
    if percentile >= _MAINSTREAM_FLOOR:
        return BAND_MAINSTREAM
    if percentile >= _KNOWN_FLOOR:
        return BAND_KNOWN
    return BAND_DEEP_CUT


def percentile_band(percentile: float | None) -> str | None:
    """Band by rank WITHIN the user's own library (the fair, robust default).

    percentile is 0.0 (most obscure in this library) .. 1.0 (most popular).
    Thirds: top third -> mainstream, middle -> known, bottom -> deep_cut.
    None -> None (unknown popularity; bucketed separately, used only as fill).

    Why percentile, not an absolute rank threshold: raw popularity metrics
    (Deezer rank spans 0..~1e6) don't map to any fixed "famous" cutoff that
    works across libraries. Ranking within the pool guarantees the difficulty
    slider always splits THIS library into meaningful thirds.
    """
    if percentile is None:
        return None
    if percentile >= _MAINSTREAM_FLOOR:
        return BAND_MAINSTREAM
    if percentile >= _KNOWN_FLOOR:
        return BAND_KNOWN
    return BAND_DEEP_CUT


def slider_to_target_band(slider: int) -> str:
    """Map a 0-100 difficulty slider to a target familiarity band.

    0   = easiest  -> mainstream (everyone knows these)
    50  = balanced -> known
    100 = hardest  -> deep cuts (obscure; for experienced players)
    """
    slider = max(0, min(100, slider))
    if slider <= 33:
        return BAND_MAINSTREAM
    if slider <= 66:
        return BAND_KNOWN
    return BAND_DEEP_CUT
