"""Generate a Beatify playlist by sampling the enriched library pool.

This is the piece that makes the game "infinitely re-playable": the slow work
(library scan + year/popularity enrichment) is done once into a cached pool;
each game samples a fresh playlist from it in microseconds. Re-roll = re-sample.

Design goals encoded here:
  * Trust:        only include songs whose resolved year clears `min_confidence`
                  (default: verified MusicBrainz years only).
  * Difficulty:   bias selection toward the slider's familiarity band, but spill
                  over into adjacent bands if the band is too small to fill the
                  requested size (a half-empty game is worse than a slightly
                  easier one).
  * Fairness:     bands are cut on ABSOLUTE worldwide fame by default, so a
                  guest never has to know the host's niche favourites.
  * Spread:       balance across decades so the year-guessing game isn't 30
                  songs from 2015-2020.
  * No dupes:     dedupe by normalized (artist, title) so the same song from two
                  albums can't appear twice.

Output is a dict in Beatify's exact playlist schema, so it flows through the
existing PlaylistManager / MediaPlayerService unchanged. The only new field is
`uri_ma_library`, the Music-Assistant URI captured at scan time.

`generate_playlist` is pure (seedable RNG) and unit-tested.
"""

from __future__ import annotations

import random
import re
import unicodedata
from collections import defaultdict
from typing import Any

from .popularity import (
    BAND_DEEP_CUT,
    BAND_KNOWN,
    BAND_MAINSTREAM,
    absolute_band,
    percentile_band,
)
from .year_resolver import YearConfidence

# Band adjacency for spillover when the target band is too small.
_BAND_SPILL_ORDER = {
    BAND_MAINSTREAM: [BAND_MAINSTREAM, BAND_KNOWN, BAND_DEEP_CUT],
    BAND_KNOWN: [BAND_KNOWN, BAND_MAINSTREAM, BAND_DEEP_CUT],
    BAND_DEEP_CUT: [BAND_DEEP_CUT, BAND_KNOWN, BAND_MAINSTREAM],
}


# Precompiled once at import: `_norm_key` runs twice per song, so on an 18k
# pool these two patterns were looked up 72,000 times per generated playlist.
_VERSION_SUFFIX_RE = re.compile(
    r"\s*[\(\[-].*?(remaster|remastered|live|mono|stereo|version|"
    r"edit|mix|deluxe|feat\.?|featuring|explicit|radio).*?[\)\]]?$"
)
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

#: Pool entries carry the precomputed dedupe key under this field (written by
#: :func:`custom_components.beatify.library.pool.finalize_pool`). Pools built
#: before that existed simply lack it and are recomputed on the fly.
NORM_KEY_FIELD = "_norm_key"


def _clean_part(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = _VERSION_SUFFIX_RE.sub("", s)
    return _NON_ALNUM_RE.sub(" ", s).strip()


def _norm_key(artist: str, title: str) -> str:
    """Normalized dedupe key: lowercased, accent-stripped, version-suffix-free."""
    return f"{_clean_part(artist)}|{_clean_part(title)}"


def entry_key(entry: dict[str, Any]) -> str:
    """Dedupe key for a pool entry — precomputed if the pool has it.

    Older pools (written before ``_norm_key`` was stored) have no such field;
    they fall back to computing it, so nothing breaks on an existing install.
    """
    key = entry.get(NORM_KEY_FIELD)
    if isinstance(key, str) and key:
        return key
    return _norm_key(entry.get("artist") or "", entry.get("title") or "")


def _decade(year: int) -> int:
    return (year // 10) * 10


# Coarse-genre adjacency for graceful fallback: when "Top N% of <genre>"
# can't fill a game, related genres are tried BEFORE widening down the
# popularity ranking — "Top 5% Trance" then fills with top-5% House/Dance
# rather than with the most famous mis-tagged songs deep in the Trance tag
# (label pollution floats famous songs to the top of any tag they leak
# into; observed: Michael Jackson in a Trance game). Names match the coarse
# Deezer/MB labels case-insensitively; unknown names simply match nothing.
GENRE_RELATED: dict[str, tuple[str, ...]] = {
    "trance": ("house", "dance", "electro", "techno", "progressive house"),
    "house": ("dance", "electro", "techno", "trance", "deep house"),
    "techno": ("electro", "house", "dance", "trance"),
    "dance": ("house", "electro", "disco", "pop"),
    "electro": ("dance", "house", "techno", "electronic"),
    "electronic": ("electro", "dance", "house", "ambient"),
    "synth pop": ("new wave", "electro", "dance", "pop"),
    "new wave": ("synth pop", "post-punk", "pop rock"),
    "rock": ("classic rock", "hard rock", "alternative rock", "pop rock", "indie rock"),
    "classic rock": ("rock", "hard rock", "blues rock"),
    "hard rock": ("rock", "metal", "classic rock"),
    "metal": ("hard rock", "heavy metal", "rock"),
    "alternative rock": ("rock", "indie rock", "grunge"),
    "indie rock": ("alternative rock", "rock", "indie pop"),
    "pop": ("dance", "pop rock", "synth pop", "indie pop"),
    "pop rock": ("pop", "rock", "soft rock"),
    "jazz": ("blues", "soul", "swing", "funk"),
    "blues": ("jazz", "blues rock", "soul"),
    "soul": ("r&b", "funk", "jazz", "motown"),
    "r&b": ("soul", "hip hop", "pop"),
    "funk": ("soul", "disco", "r&b"),
    "disco": ("dance", "funk", "pop"),
    "hip hop": ("rap", "r&b"),
    "rap": ("hip hop", "r&b"),
    "classical": ("modern classical", "opera", "soundtrack"),
    "modern classical": ("classical", "ambient", "soundtrack"),
    "soundtrack": ("films/games", "classical"),
    "films/games": ("soundtrack",),
    "country": ("folk", "americana", "rock"),
    "folk": ("country", "singer-songwriter", "acoustic"),
    "reggae": ("ska", "dancehall"),
    "schlager": ("pop", "volksmusik"),
    "ambient": ("electronic", "chillout", "downtempo"),
    "chillout": ("ambient", "downtempo", "lounge"),
}


def related_genres(genres: set[str] | None) -> set[str]:
    """Adjacent genres for the given selection (casefolded; excludes the
    originals). Pure; empty set when nothing is related/known."""
    if not genres:
        return set()
    base = {g.strip().casefold() for g in genres if g and g.strip()}
    out: set[str] = set()
    for g in base:
        out.update(GENRE_RELATED.get(g, ()))
    return out - base


def count_eligible(
    pool: list[dict[str, Any]],
    *,
    popularity_min_percentile: float | None = None,
    genres: set[str] | None = None,
    min_confidence: int = int(YearConfidence.EXTERNAL_PRIMARY),
) -> int:
    """How many songs the current settings can draw from. Pure.

    Mirrors generate_playlist's window-path filters (confidence gate, uri,
    dedupe, genre any-match, percentile window, hybrid fame floor) WITHOUT
    the recent-exclusion (which varies per game). A parity test asserts this
    stays in sync with generate_playlist's _eligible_count.
    """
    usable = [
        s
        for s in pool
        if int(s.get("year_confidence", 0)) >= min_confidence
        and s.get("uri_ma_library")
        and s.get("year")
    ]
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for s_ in usable:
        key = entry_key(s_)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(s_)
    if genres:
        want = {g.strip().casefold() for g in genres if g and g.strip()}
        if want:
            deduped = [
                s_
                for s_ in deduped
                if any(str(g).casefold() in want for g in (s_.get("genres") or []))
            ]
    lo = popularity_min_percentile if popularity_min_percentile is not None else 0.0
    abs_floor = 40.0 + 30.0 * lo if lo >= 0.5 else None
    return sum(
        1
        for s_ in deduped
        if s_.get("popularity_percentile") is not None
        and lo <= s_["popularity_percentile"] <= 1.0
        and (abs_floor is None or (s_.get("global_score") or 0.0) >= abs_floor)
    )


def generate_playlist(
    pool: list[dict[str, Any]],
    *,
    size: int = 30,
    difficulty_band: str = BAND_KNOWN,
    popularity_max_percentile: float | None = None,
    popularity_min_percentile: float | None = None,
    genres: set[str] | None = None,
    min_confidence: int = int(YearConfidence.EXTERNAL_PRIMARY),
    balance_decades: bool = True,
    include_unknown_popularity: bool = True,
    banding: str = "percentile",
    name: str | None = None,
    rng: random.Random | None = None,
    exclude_uris: set[str] | None = None,
) -> dict[str, Any]:
    """Sample a Beatify-schema playlist dict from an enriched pool.

    Args:
        pool: enriched song dicts (see module docstring).
        size: target number of songs.
        difficulty_band: BAND_MAINSTREAM | BAND_KNOWN | BAND_DEEP_CUT.
        min_confidence: minimum YearConfidence to include a song.
        balance_decades: flatten the decade distribution when picking.
        include_unknown_popularity: if True, songs with no popularity data are
            eligible (used to fill if a band is short) instead of dropped.
        banding: "absolute" (default) bands by WORLDWIDE fame so a guest only
            ever faces globally-recognizable songs at the easy end -- the fair
            mode. "relative" bands by rank within the host's own library.
        name: optional playlist name.
        rng: optional seeded Random for deterministic tests.

    Returns:
        {"name", "version", "_generated", "tags", "songs": [...]} ready to feed
        to PlaylistManager. May contain fewer than `size` songs if the trusted
        pool is smaller; callers should surface that to the user.
    """
    rng = rng or random.Random()

    # 1) Trust gate: drop anything we don't believe the year of.
    trusted = [
        s
        for s in pool
        if s.get("year") is not None
        and int(s.get("year_confidence", 0)) >= min_confidence
        and s.get("uri_ma_library")
    ]

    # 2) Dedupe by normalized (artist, title); keep the higher-confidence copy.
    by_key: dict[str, dict[str, Any]] = {}
    for s in trusted:
        key = entry_key(s)
        prev = by_key.get(key)
        if prev is None or int(s.get("year_confidence", 0)) > int(
            prev.get("year_confidence", 0)
        ):
            by_key[key] = s
    deduped = list(by_key.values())

    # 2a) Genre filter (any-match, case-insensitive). Applied before windows
    #     and bands so every selection mode respects it. A pre-filter snapshot
    #     is kept for the related-genre fallback below.
    pre_genre_deduped = list(deduped)
    if genres:
        want = {g.strip().casefold() for g in genres if g and g.strip()}
        if want:
            deduped = [
                s
                for s in deduped
                if any(str(g).casefold() in want for g in (s.get("genres") or []))
            ]

    # 2b) Recently-played exclusion (repeat-avoidance across games).
    if exclude_uris:
        _fresh = [s for s in deduped if s.get("uri_ma_library") not in exclude_uris]
        # only apply if enough songs remain to fill the game, else ignore it
        if len(_fresh) >= size:
            deduped = _fresh

    # 3) Percentile-WINDOW selection (precise slider) takes precedence over
    #    coarse bands when a window is supplied. Songs with no popularity
    #    percentile are excluded from a narrow window (that's the whole point of
    #    "Popular"); they're only added back as fill for a wide/low-pop window.
    if popularity_max_percentile is not None or popularity_min_percentile is not None:
        lo = popularity_min_percentile if popularity_min_percentile is not None else 0.0
        hi = popularity_max_percentile if popularity_max_percentile is not None else 1.0
        # HYBRID floor: percentile is relative to THIS pool, so in a
        # soundtrack-/rarity-heavy library "top 5%" would still surface the
        # least-obscure of the obscure. For narrow (popular) windows we
        # therefore ALSO require real-world fame via the absolute score
        # (log-scaled Deezer rank): the narrower the window, the higher the
        # floor: 40 + 30*lo. lo=0.95 ("top 5%") -> floor 68.5; lo=0.7 -> 61;
        # wide windows (lo < 0.5) -> no absolute floor (deep cuts are the
        # point there).
        abs_floor = 40.0 + 30.0 * lo if lo >= 0.5 else None
        scored_pool = [s for s in deduped if s.get("popularity_percentile") is not None]
        in_window = [
            s
            for s in scored_pool
            if lo <= s["popularity_percentile"] <= hi
            and (abs_floor is None or (s.get("global_score") or 0.0) >= abs_floor)
        ]
        rng.shuffle(in_window)
        candidates = in_window
        window_widened = False
        genres_expanded: list[str] = []
        # RELATED-GENRE fill (user-designed): before widening down the
        # popularity ranking, try songs of ADJACENT genres inside the same
        # window — "Top 5% Trance" fills with top-5% House/Dance, which is
        # what a trance fan expects, instead of famous mis-tagged songs.
        if len(candidates) < size and genres:
            rel = related_genres(genres)
            if rel:
                have = {s_.get("uri_ma_library") for s_ in candidates}
                rel_pool = [
                    s_
                    for s_ in pre_genre_deduped
                    if s_.get("uri_ma_library") not in have
                    and (
                        not exclude_uris or s_.get("uri_ma_library") not in exclude_uris
                    )
                    and any(str(g).casefold() in rel for g in (s_.get("genres") or []))
                    and s_.get("popularity_percentile") is not None
                    and lo <= s_["popularity_percentile"] <= hi
                    and (
                        abs_floor is None
                        or (s_.get("global_score") or 0.0) >= abs_floor
                    )
                ]
                if rel_pool:
                    rng.shuffle(rel_pool)
                    used = rel_pool[: max(0, size - len(candidates))]
                    if used:
                        candidates = candidates + used
                        found = set()
                        for s_ in used:
                            for g in s_.get("genres") or []:
                                if str(g).casefold() in rel:
                                    found.add(str(g))
                        genres_expanded = sorted(found)
        # GRACEFUL WIDENING: a narrow window intersected with a genre filter
        # can leave < size songs. Filling with unknown-popularity songs here
        # flooded "Top 5% Jazz" games with obscure film cues (genre-tagged via
        # MB/Deezer, popularity-unknown). Instead, widen DOWNWARD through the
        # scored songs — "top 5% Jazz" degrades to "the most popular Jazz you
        # own", never to random obscurities.
        if len(candidates) < size and len(scored_pool) > len(candidates):
            ranked = sorted(
                scored_pool,
                key=lambda s: -(s.get("popularity_percentile") or 0.0),
            )
            candidates = ranked[:size]
            window_widened = len(candidates) > len(in_window)
        # Unknown-popularity songs remain a LAST resort, only when even the
        # widened scored pool can't fill a game and the window reaches into
        # the obscure end anyway.
        # The gate MUST test `lo`, not `hi`: a "Top P%" window is [1-P/100,
        # 1.0], so `hi` is ALWAYS 1.0 and this fill fired for every window
        # including Top 1% — dropping unranked obscurities into games that
        # asked for the most famous songs in the library (reported: a French
        # Aladdin dub, popularity_percentile=None, in a Top 1% round).
        # Unknown-popularity songs are only acceptable when the request
        # itself reaches into the obscure end.
        if include_unknown_popularity and lo <= 0.34 and len(candidates) < size:
            unknown = [s for s in deduped if s.get("popularity_percentile") is None]
            rng.shuffle(unknown)
            candidates.extend(unknown)
        chosen = (
            _select_decade_balanced(candidates, size, rng)
            if balance_decades
            else candidates[:size]
        )
        songs = [_to_song_entry(s) for s in chosen]
        return {
            "name": name or _auto_name(difficulty_band, len(songs)),
            "version": "1.0",
            "_generated": True,
            "_popularity_window": [lo, hi],
            "_eligible_count": len(in_window),
            "_window_widened": window_widened,
            "_genres_expanded": genres_expanded,
            "tags": ["library", "generated"],
            "songs": songs,
        }

    # 3-band fallback (no explicit window): bucket by familiarity band.
    #    absolute (default): worldwide fame -> fair for guests.
    #    relative:           rank within this library -> always fills bands.
    banded: dict[str, list[dict[str, Any]]] = defaultdict(list)
    unknown_pop: list[dict[str, Any]] = []
    for s in deduped:
        # Default: the stored percentile band (fair within this library).
        # "absolute" kept only for tests/back-compat via global_score.
        if banding == "absolute":
            band = s.get("familiarity_band") or absolute_band(s.get("global_score"))
        else:
            band = s.get("familiarity_band") or percentile_band(
                s.get("popularity_percentile")
            )
        if band is None:
            unknown_pop.append(s)
        else:
            banded[band].append(s)

    # 4) Build the candidate ordering: target band first, then spill outward.
    spill = _BAND_SPILL_ORDER.get(difficulty_band, [BAND_KNOWN])
    candidates: list[dict[str, Any]] = []
    for band in spill:
        bucket = banded.get(band, [])[:]
        rng.shuffle(bucket)
        candidates.extend(bucket)
    if include_unknown_popularity:
        rng.shuffle(unknown_pop)
        candidates.extend(unknown_pop)

    # 5) Select `size`, balancing decades if requested.
    chosen = (
        _select_decade_balanced(candidates, size, rng)
        if balance_decades
        else candidates[:size]
    )

    songs = [_to_song_entry(s) for s in chosen]
    return {
        "name": name or _auto_name(difficulty_band, len(songs)),
        "version": "1.0",
        "_generated": True,
        "_difficulty_band": difficulty_band,
        "tags": ["library", "generated", difficulty_band],
        "songs": songs,
    }


def _select_decade_balanced(
    candidates: list[dict[str, Any]], size: int, rng: random.Random
) -> list[dict[str, Any]]:
    """Round-robin across decades to flatten the year distribution.

    `candidates` is assumed pre-shuffled within band priority, so taking the
    next item per decade preserves the familiarity bias while spreading years.
    """
    by_decade: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for s in candidates:
        year = s.get("year")
        if isinstance(year, int):
            by_decade[_decade(year)].append(s)

    decades = sorted(by_decade.keys())
    if not decades:
        return candidates[:size]

    chosen: list[dict[str, Any]] = []
    cursors = {d: 0 for d in decades}
    rotate = rng.randrange(len(decades))
    order = decades[rotate:] + decades[:rotate]

    while len(chosen) < size:
        progressed = False
        for d in order:
            if len(chosen) >= size:
                break
            c = cursors[d]
            if c < len(by_decade[d]):
                chosen.append(by_decade[d][c])
                cursors[d] += 1
                progressed = True
        if not progressed:
            break  # every decade exhausted
    return chosen


def _to_song_entry(s: dict[str, Any]) -> dict[str, Any]:
    """Project a pool entry into a Beatify song dict."""
    entry: dict[str, Any] = {
        "year": int(s["year"]),
        "title": s["title"],
        "artist": s["artist"],
        "uri_ma_library": s["uri_ma_library"],
    }
    if s.get("alt_artists"):
        entry["alt_artists"] = s["alt_artists"]
    if s.get("album"):
        entry["album"] = s["album"]
    # Internal breadcrumbs (ignored by the game, handy for debugging the slider).
    entry["_global_score"] = s.get("global_score")
    entry["_popularity_percentile"] = s.get("popularity_percentile")
    entry["_year_source"] = s.get("year_source")
    return entry


def _auto_name(band: str, count: int) -> str:
    label = {
        BAND_MAINSTREAM: "Crowd-Pleasers",
        BAND_KNOWN: "Mixed Bag",
        BAND_DEEP_CUT: "Deep Cuts",
    }.get(band, "Library Mix")
    return f"Your Library: {label} ({count} songs)"
