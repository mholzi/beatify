"""Release-year resolution for library-sourced songs.

THE central data-quality problem for library-generated playlists: Beatify is a
*year-guessing* game, so every song needs a trustworthy original-release year.
Local file tags are unreliable for this -- they come from whoever ripped/tagged
the file, vary wildly between libraries, and compilations/remasters re-stamp the
pressing year (a 1975 track on a 2010 hits album is tagged 2010). On a friend's
worse-tagged library the problem is worse, and the *guest* pays for it.

So this resolver treats EXTERNAL sources as authoritative and tags as a last
resort that is OFF by default. Confidence tiers (high -> low):

    EXTERNAL_PRIMARY    MusicBrainz, match-quality-checked. Default & only tier
                        used unless the caller opts into more.
    EXTERNAL_SECONDARY  A second external source (e.g. Deezer release year),
                        used to recover coverage for MB misses when enabled.
    TAG_STUDIO          Tag year from a studio album/single -- only if the
                        caller explicitly allows tags.
    TAG_COMPILATION     Tag year from a compilation/live/soundtrack -- lowest;
                        almost certainly the pressing year, not the song's.
    NONE                Nothing usable -> excluded from the game.

The default generation gate is EXTERNAL_PRIMARY, i.e. a song needs a confident
MusicBrainz year to be playable. This favours accuracy over pool size; the
build reports coverage so the user can decide whether to relax the gate.

MusicBrainz matching is hardened: results are filtered by MB's own match
`score` AND the artist credit is verified against the query, then the earliest
plausible release among those confident matches is taken (so a remaster can't
outrank the original, while a same-title-different-song can't sneak in).

All decision logic here is pure and unit-tested; only the two `async_*`
functions touch the network.
"""

from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import IntEnum
from typing import Any

_LOGGER = logging.getLogger(__name__)

# Plausibility window for any resolved year.
YEAR_FLOOR = 1900

# Album types we do not trust for a release year (music_assistant_models
# AlbumType values: album, single, ep, compilation, soundtrack, live,
# unknown). #2583: a matching _TRUSTED_ALBUM_TYPES set was never consulted
# — the code only ever asks whether a type is in this one.
_COMPILATION_ALBUM_TYPES = {"compilation", "soundtrack", "live"}

_VARIOUS_ARTIST_MARKERS = {
    "various artists",
    "various",
    "va",
    "verschiedene interpreten",
    "artistes divers",
}

# Album-NAME patterns that signal a compilation/live release. Safety net for MA
# library tracks whose album is a metadata-light ItemMapping (no album_type).
_COMPILATION_NAME_RE = re.compile(
    r"\b("
    r"greatest hits|best of|the best of|collection|the collection|"
    r"compilation|anthology|essential|the essential|essentials|"
    r"hits|number ?ones|no\.? ?1'?s|singles|b-sides|rarities|"
    r"live at|live in|live from|unplugged|in concert|"
    r"soundtrack|original motion picture|ost|"
    r"now that's what i call"
    r")\b",
    re.IGNORECASE,
)

# Version suffixes to strip from a title before querying MusicBrainz, so a file
# named "Song - 2011 Remaster" still matches the original recording.
_VERSION_SUFFIX_RE = re.compile(
    r"\s*[\(\[-]\s*[^\)\]]*\b("
    r"remaster(ed)?|live|mono|stereo|version|edit|mix|deluxe|"
    r"explicit|radio edit|single version|album version|bonus|remix"
    r")\b[^\)\]]*[\)\]]?\s*$",
    re.IGNORECASE,
)


def _current_year() -> int:
    return datetime.now(timezone.utc).year


class YearConfidence(IntEnum):
    """How much we trust a resolved year. Higher is better."""

    NONE = 0
    TAG_COMPILATION = 1  # tag year from a comp/live/soundtrack -> pressing year
    TAG_STUDIO = 2  # tag year from a studio album/single by the real artist
    EXTERNAL_SECONDARY = 3  # a second external source (e.g. Deezer release year)
    EXTERNAL_PRIMARY = 4  # MusicBrainz, match-quality-verified -> authoritative
    # A human who owns the file and checked the release outranks any fuzzy
    # match. Set only by an explicit correction in the admin panel; the
    # strictest year gate must never exclude a song the host confirmed.
    USER_VERIFIED = 5


# Convenient default gate: external-only (the user's stated preference).
DEFAULT_MIN_CONFIDENCE = int(YearConfidence.EXTERNAL_PRIMARY)


@dataclass(frozen=True)
class ResolvedYear:
    """Result of resolving a single song's year."""

    year: int | None
    confidence: YearConfidence
    source: str

    @property
    def usable(self) -> bool:
        return self.year is not None and self.confidence > YearConfidence.NONE


def _plausible(year: int | None) -> bool:
    return isinstance(year, int) and YEAR_FLOOR <= year <= _current_year() + 1


def _norm(s: str) -> str:
    """Lowercase, strip accents/punctuation for robust string comparison."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def clean_title_for_query(title: str) -> str:
    """Strip trailing version suffixes so MB matches the underlying recording."""
    prev = None
    out = title.strip()
    # Apply repeatedly in case of stacked suffixes, e.g. "X (Live) [Remaster]".
    while out != prev:
        prev = out
        out = _VERSION_SUFFIX_RE.sub("", out).strip()
    return out or title.strip()


def title_query_candidates(title: str) -> list[str]:
    """Ordered MB query candidates for a decorated title. Pure.

    1. suffix-cleaned title (precise),
    2. hard-cleaned core (all (...)/[...] groups and " - tail" stripped),
    3. the RIGHT side of a " - " split — compilations often use
       "Main Title - Scarface" (generic-left / specific-RIGHT), where keeping
       the left side yields an unfindable generic ("Main Title"). Observed on
       hardware: that exact track kept its wrong 2022 reissue year through a
       refresh because candidates 1+2 both missed the canonical recording.
    Deduplicated case-insensitively, order preserved, max 3 queries (each is
    throttled, and later candidates run only if earlier ones fail).
    """
    out: list[str] = []
    seen: set[str] = set()

    def _add(x: str) -> None:
        x = (x or "").strip()
        if x and x.casefold() not in seen:
            seen.add(x.casefold())
            out.append(x)

    clean = clean_title_for_query(title)
    _add(clean)
    _add(hard_clean_title(clean))
    if " - " in clean:
        _add(hard_clean_title(clean.rsplit(" - ", 1)[1]))
    return out[:3]


def hard_clean_title(title: str) -> str:
    """Aggressive core-title extraction for a FALLBACK MB query.

    Compilation/reissue tracks carry arbitrary decorations the suffix list
    can't enumerate — "(Re-Recorded)", "(From \"Flashdance\")", "Scarface -
    Main Title". Because the MB query quotes the title as an exact phrase,
    those decorations exclude the CANONICAL recording from the results
    entirely, and earliest-among-confident then picks among reissues only
    (observed: Flashdance->2001, Scarface->2022, Rain Man->2010). This strips
    every trailing (...) / [...] group and any " - tail", keeping the core.
    Used only when the normal query yields no confident year.
    """
    import re as _re

    out = title.strip()
    prev = None
    while out != prev:
        prev = out
        out = _re.sub(r"\s*[\(\[][^\)\]]*[\)\]]\s*$", "", out).strip()
    # trailing " - Something" tail (keep the left side if non-empty)
    m = _re.match(r"^(.*\S)\s+-\s+[^-]{1,60}$", out)
    if m and len(m.group(1)) >= 3:
        out = m.group(1).strip()
    return out or title.strip()


def _looks_like_compilation(
    album_type: str | None,
    album_artist: str | None,
    album_name: str | None = None,
) -> bool:
    if album_type:
        # Robust against both "compilation" and "AlbumType.COMPILATION" reprs.
        norm = album_type.strip().lower().rsplit(".", 1)[-1]
        if norm in _COMPILATION_ALBUM_TYPES:
            return True
    if album_artist and album_artist.strip().lower() in _VARIOUS_ARTIST_MARKERS:
        return True
    return bool(album_name and _COMPILATION_NAME_RE.search(album_name))


def resolve_year(
    *,
    musicbrainz_year: int | None = None,
    secondary_external_year: int | None = None,
    tag_year: int | None = None,
    album_type: str | None = None,
    album_artist: str | None = None,
    album_name: str | None = None,
) -> ResolvedYear:
    """Resolve a song's original release year with a confidence tier.

    Pure function. External sources are authoritative; tags are the lowest
    tiers and only matter if the caller's gate is permissive.

    Priority:
      1. MusicBrainz (verified)         -> EXTERNAL_PRIMARY
      2. Secondary external (Deezer)    -> EXTERNAL_SECONDARY
      3. Studio-album tag year          -> TAG_STUDIO
      4. Compilation/live tag year      -> TAG_COMPILATION
      5. Nothing plausible              -> NONE
    """
    if _plausible(musicbrainz_year):
        return ResolvedYear(
            musicbrainz_year, YearConfidence.EXTERNAL_PRIMARY, "musicbrainz"
        )
    if _plausible(secondary_external_year):
        return ResolvedYear(
            secondary_external_year, YearConfidence.EXTERNAL_SECONDARY, "deezer"
        )
    if _plausible(tag_year):
        if _looks_like_compilation(album_type, album_artist, album_name):
            return ResolvedYear(
                tag_year, YearConfidence.TAG_COMPILATION, "tag:compilation"
            )
        return ResolvedYear(tag_year, YearConfidence.TAG_STUDIO, "tag:studio")
    return ResolvedYear(None, YearConfidence.NONE, "none")


# --------------------------------------------------------------------------- #
# MusicBrainz lookup (hardened).
# --------------------------------------------------------------------------- #

_MB_BASE = "https://musicbrainz.org/ws/2/recording"
# Per MusicBrainz etiquette, set a REAL contact here before running at scale.
_MB_USER_AGENT = "BeatifyLibraryProvider/1.0 (https://github.com/mholzi/beatify)"
_MB_MIN_INTERVAL = 1.1  # seconds between requests (<=1 req/s rule)
_MB_MIN_SCORE = 90  # reject MB matches below this (0-100) confidence


class MusicBrainzThrottle:
    """Serializes MB requests to <=1/sec across the whole pool build."""

    def __init__(self, min_interval: float = _MB_MIN_INTERVAL) -> None:
        self._min_interval = min_interval
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def wait(self) -> None:
        async with self._lock:
            loop = asyncio.get_running_loop()
            delta = loop.time() - self._last
            if delta < self._min_interval:
                await asyncio.sleep(self._min_interval - delta)
            self._last = asyncio.get_running_loop().time()


def _parse_mb_year(date_str: str | None) -> int | None:
    """MB dates are 'YYYY', 'YYYY-MM', or 'YYYY-MM-DD'. Take the year."""
    if not date_str:
        return None
    head = str(date_str).strip()[:4]
    if head.isdigit():
        year = int(head)
        if _plausible(year):
            return year
    return None


def _credit_names(recording: dict[str, Any]) -> list[str]:
    """Extract normalized artist names from an MB recording's artist-credit."""
    names: list[str] = []
    for credit in recording.get("artist-credit") or []:
        if not isinstance(credit, dict):
            continue
        for key in ("name",):
            v = credit.get(key)
            if isinstance(v, str) and v.strip():
                names.append(_norm(v))
        artist = credit.get("artist")
        if isinstance(artist, dict):
            v = artist.get("name")
            if isinstance(v, str) and v.strip():
                names.append(_norm(v))
    return names


def _artist_matches(query_artist: str, recording: dict[str, Any]) -> bool:
    """True if the query artist matches the recording's credited artist.

    Bidirectional containment on normalized strings, so 'Eminem' matches an
    'Eminem feat. Rihanna' credit and vice versa, without matching unrelated
    artists that merely share a word.
    """
    q = _norm(query_artist)
    if not q:
        return False
    for name in _credit_names(recording):
        if not name:
            continue
        if q == name or q in name or name in q:
            return True
    return False


def extract_mb_genres(
    recordings: list[dict[str, Any]],
    query_artist: str,
    *,
    min_score: int = _MB_MIN_SCORE,
    limit: int = 5,
) -> list[str]:
    """Genre tags from confident MB recordings. Pure; [] when none.

    MB search results carry community 'tags' on recordings — the same payload
    we already fetch for years, so genres cost ZERO extra requests. Needed
    because MA's library metadata proved genre-empty for Plex-synced tracks
    (measured: 20,000 detail fetches -> 0 genres, 0 errors). Tags from all
    confident (score+artist-verified) recordings are merged by vote count.
    """
    votes: dict[str, int] = {}
    for rec in recordings:
        if not isinstance(rec, dict):
            continue
        score = rec.get("score")
        if isinstance(score, str) and score.isdigit():
            score = int(score)
        if not isinstance(score, int) or score < min_score:
            continue
        if not _artist_matches(query_artist, rec):
            continue
        for tag in rec.get("tags") or []:
            name = str((tag or {}).get("name") or "").strip()
            if not name or len(name) > 32:
                continue
            count = tag.get("count")
            n = int(count) if isinstance(count, int) else 1
            key = name.lower()
            votes[key] = votes.get(key, 0) + max(1, n)
    ranked = sorted(votes.items(), key=lambda kv: -kv[1])[:limit]
    return [name.title() for name, _ in ranked]


def pick_mb_year(
    recordings: list[dict[str, Any]],
    query_artist: str,
    *,
    min_score: int = _MB_MIN_SCORE,
) -> int | None:
    """Choose a trustworthy year from MB recording-search results. Pure.

    Returns the earliest plausible first-release-date among recordings that
    BOTH (a) clear the match-score threshold and (b) are credited to the query
    artist. Returns None if no recording meets both bars -- the caller then
    treats MB as "no answer" rather than guessing.

    Earliest-among-confident is deliberate: it collapses remaster/reissue
    recordings of the same song to the original year, while the score + artist
    gates keep out same-title-different-song matches.
    """
    confident_years: list[int] = []
    for rec in recordings:
        if not isinstance(rec, dict):
            continue
        score = rec.get("score")
        if isinstance(score, str) and score.isdigit():
            score = int(score)
        if not isinstance(score, int) or score < min_score:
            continue
        if not _artist_matches(query_artist, rec):
            continue
        y = _parse_mb_year(rec.get("first-release-date"))
        if y is not None:
            confident_years.append(y)
    return min(confident_years) if confident_years else None


async def async_musicbrainz_candidates(
    session: Any,  # aiohttp.ClientSession
    artist: str,
    title: str,
    throttle: MusicBrainzThrottle,
    *,
    timeout: float = 8.0,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Return MusicBrainz recording candidates for host review.

    Unlike :func:`async_musicbrainz_year`, which answers "what year is this"
    and discards everything it isn't sure about, this returns the raw field
    of options so the host can SEE what was matched — including the case
    where the automatic pick was a different song entirely. Artist filtering
    is deliberately NOT applied: a wrong artist in the pool is exactly the
    kind of misidentification the correction UI exists to fix.
    """
    query_title = clean_title_for_query(title) or title
    query = f'recording:"{_mb_escape(query_title)}"'
    if artist:
        query += f' AND artist:"{_mb_escape(artist)}"'
    params = {"query": query, "fmt": "json", "limit": str(limit)}
    headers = {"User-Agent": _MB_USER_AGENT}
    await throttle.wait()
    try:
        async with session.get(
            _MB_BASE, params=params, headers=headers, timeout=timeout
        ) as resp:
            if resp.status != 200:
                _LOGGER.debug(
                    "MB candidates %s for %s - %s", resp.status, artist, title
                )
                return []
            data = await resp.json()
    except Exception:  # noqa: BLE001
        _LOGGER.debug("MB candidate lookup failed for %s - %s", artist, title)
        return []

    out: list[dict[str, Any]] = []
    for rec in data.get("recordings") or []:
        if not isinstance(rec, dict):
            continue
        releases = rec.get("releases") or []
        first_release = releases[0] if releases else {}
        out.append(
            {
                "mbid": rec.get("id"),
                "title": rec.get("title"),
                "artist": ", ".join(_credit_names(rec)) or None,
                "year": _parse_mb_year(rec.get("first-release-date"))
                or _parse_mb_year(first_release.get("date")),
                "album": (first_release.get("title") if first_release else None),
                "score": rec.get("score"),
            }
        )
    return out


async def async_musicbrainz_year(
    session: Any,  # aiohttp.ClientSession
    artist: str,
    title: str,
    throttle: MusicBrainzThrottle,
    *,
    timeout: float = 8.0,
    min_score: int = _MB_MIN_SCORE,
) -> int | None:
    """Look up a verified original-release year on MusicBrainz.

    Returns None on any failure or low-confidence match. Uses the cleaned title
    (version suffixes stripped) so remasters match the underlying recording.
    """

    async def _query(q_title: str) -> int | None:
        query = f'recording:"{_mb_escape(q_title)}" AND artist:"{_mb_escape(artist)}"'
        params = {"query": query, "fmt": "json", "limit": "25"}
        headers = {"User-Agent": _MB_USER_AGENT}
        await throttle.wait()
        try:
            async with session.get(
                _MB_BASE, params=params, headers=headers, timeout=timeout
            ) as resp:
                if resp.status != 200:
                    _LOGGER.debug("MB %s for %s - %s", resp.status, artist, title)
                    return None
                data = await resp.json()
        except (TimeoutError, asyncio.TimeoutError):
            _LOGGER.debug("MB timeout for %s - %s", artist, title)
            return None
        except Exception as err:  # noqa: BLE001 - never let MB break a pool build
            _LOGGER.debug("MB error for %s - %s: %s", artist, title, err)
            return None
        return pick_mb_year(data.get("recordings") or [], artist, min_score=min_score)

    for candidate in title_query_candidates(title):
        year = await _query(candidate)
        if year is not None:
            return year
    return None


async def async_musicbrainz_year_genres(
    session: Any,
    artist: str,
    title: str,
    throttle: MusicBrainzThrottle,
    *,
    min_score: int = _MB_MIN_SCORE,
    timeout: float = 8.0,
) -> tuple[int | None, list[str]]:
    """Like async_musicbrainz_year, but also returns MB genre tags (free —
    same responses). Genres may be present even when no confident year is."""
    genres: list[str] = []

    async def _query(q_title: str) -> int | None:
        nonlocal genres
        query = f'recording:"{_mb_escape(q_title)}" AND artist:"{_mb_escape(artist)}"'
        params = {"query": query, "fmt": "json", "limit": "25"}
        headers = {"User-Agent": _MB_USER_AGENT}
        await throttle.wait()
        try:
            async with session.get(
                _MB_BASE, params=params, headers=headers, timeout=timeout
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
        except (TimeoutError, asyncio.TimeoutError):
            return None
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("MB error for %s - %s: %s", artist, title, err)
            return None
        recs = data.get("recordings") or []
        if not genres:
            genres = extract_mb_genres(recs, artist, min_score=min_score)
        return pick_mb_year(recs, artist, min_score=min_score)

    for candidate in title_query_candidates(title):
        year = await _query(candidate)
        if year is not None:
            return year, genres
    return None, genres


def _mb_escape(value: str) -> str:
    """Escape Lucene special chars for the MB query string."""
    out = value.replace("\\", "\\\\")
    for ch in ('"', ":", "(", ")", "[", "]", "{", "}", "^", "~", "?", "*"):
        out = out.replace(ch, " ")
    return out.strip()
