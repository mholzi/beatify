"""Resolve external song picks against the enriched library pool.

This is the bridge that makes AI-curated (or hand-written) playlists safe for
the library provider: an LLM (or a human) supplies picks as plain
``{"artist": ..., "title": ...}`` pairs -- never URIs, never years -- and this
module resolves each pick against the user's own pool, attaching the verified
year and the playable ``uri_ma_library`` from the pool entry. Anything the
pool can't confidently match is reported back as unmatched instead of being
guessed at.

Why picks must not carry URIs or years: an LLM will happily hallucinate both,
and the whole point of the library provider is that years are externally
verified and URIs are guaranteed-playable. The pool is the single source of
truth; picks are only selectors into it.

Matching is normalized (case/accents/punctuation-insensitive, version-suffix
stripped, feat.-credit tolerant on the artist) via the same `_norm_key`
machinery the generator uses for dedupe, so "Bohemian Rhapsody - 2011
Remaster" by "Queen" matches the pool's "Bohemian Rhapsody".

Pure module: no Home Assistant, no network. Unit-tested.
"""

from __future__ import annotations

from typing import Any

from .generator import _norm_key, _to_song_entry, entry_key
from .year_resolver import YearConfidence


def build_pool_index(
    pool_songs: list[dict[str, Any]],
    *,
    min_confidence: int = int(YearConfidence.EXTERNAL_PRIMARY),
) -> dict[str, dict[str, Any]]:
    """Index usable pool songs by normalized (artist|title) key. Pure.

    Only songs that clear the year-confidence gate and carry a playable URI are
    indexed -- resolving a pick against the pool must never yield a song the
    game itself would refuse. On key collisions the higher-confidence entry
    wins (mirrors the generator's dedupe rule).
    """
    index: dict[str, dict[str, Any]] = {}
    for s in pool_songs:
        if s.get("year") is None:
            continue
        if int(s.get("year_confidence", 0)) < min_confidence:
            continue
        if not s.get("uri_ma_library"):
            continue
        key = entry_key(s)
        prev = index.get(key)
        if prev is None or int(s.get("year_confidence", 0)) > int(
            prev.get("year_confidence", 0)
        ):
            index[key] = s
    return index


def resolve_picks(
    picks: list[dict[str, Any]],
    pool_index: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Resolve picks against a pool index. Pure.

    Args:
        picks: ``[{"artist": str, "title": str}, ...]`` -- extra keys ignored.
        pool_index: from :func:`build_pool_index`.

    Returns:
        (songs, unmatched):
          songs      -- Beatify song entries (verified year + uri_ma_library),
                        deduped, in pick order.
          unmatched  -- the picks that found no pool match (echoed back with a
                        ``reason`` so a UI can show *why* per row).
    """
    songs: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    seen: set[str] = set()

    for pick in picks:
        if not isinstance(pick, dict):
            continue
        artist = str(pick.get("artist") or "").strip()
        title = str(pick.get("title") or "").strip()
        if not artist or not title:
            unmatched.append(
                {"artist": artist, "title": title, "reason": "missing artist or title"}
            )
            continue
        key = _norm_key(artist, title)
        if key in seen:
            continue  # duplicate pick -- silently collapse
        entry = pool_index.get(key)
        if entry is None:
            unmatched.append(
                {
                    "artist": artist,
                    "title": title,
                    "reason": "not in your library (or no verified year)",
                }
            )
            continue
        seen.add(key)
        songs.append(_to_song_entry(entry))

    return songs, unmatched


def build_export_index(
    pool_songs: list[dict[str, Any]],
    *,
    limit: int = 2000,
    min_confidence: int = int(YearConfidence.EXTERNAL_PRIMARY),
) -> dict[str, Any]:
    """Compact, LLM-friendly index of the usable library. Pure.

    Emits only what a curator needs to pick songs -- artist, title, year, and
    the familiarity band -- ordered most-famous-first so a truncated sample
    still contains the songs a party is most likely to want. Deliberately
    excludes URIs (nothing to hallucinate against) and internal fields.
    """
    usable = [
        s
        for s in pool_songs
        if s.get("year") is not None
        and int(s.get("year_confidence", 0)) >= min_confidence
        and s.get("uri_ma_library")
    ]
    usable.sort(
        key=lambda s: (s.get("global_score") is None, -(s.get("global_score") or 0.0))
    )

    tracks = [
        {
            "artist": s.get("artist"),
            "title": s.get("title"),
            "year": s.get("year"),
            "fame": s.get("familiarity_band") or "unknown",
        }
        for s in usable[: max(0, limit)]
    ]
    return {
        "tracks": tracks,
        "total_usable": len(usable),
        "truncated": len(usable) > len(tracks),
    }
