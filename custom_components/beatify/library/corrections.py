"""Crate Digger — user corrections to the enriched pool.

A library game is played against the host's OWN data, so when a song shows the
wrong year the fix belongs here, not in a report to whoever published a
playlist. This module holds the pure logic behind that:

* ranking MusicBrainz candidates for a song so the host can pick the right
  recording (or see that the track was misidentified entirely),
* applying a correction to a pool entry, and
* marking it so later scans and refresh passes never overwrite it.

Corrections are recorded at :data:`YearConfidence.USER_VERIFIED`, above every
automatic source: a human who owns the file and looked at the release is a
better authority than a fuzzy search, and the strictest year gate must never
exclude a song the host has personally confirmed.
"""

from __future__ import annotations

import time
from typing import Any

from .generator import NORM_KEY_FIELD
from .year_resolver import YearConfidence, _norm

# Marks an entry a human has fixed. Enrichment and refresh both skip these, so
# a rescan cannot silently undo the host's work.
CORRECTION_SOURCE = "user"


def score_candidate(
    candidate: dict[str, Any],
    *,
    query_artist: str,
    query_title: str,
) -> float:
    """Rank a MusicBrainz candidate for display. Pure.

    Higher is better. MusicBrainz's own score dominates, with bonuses for an
    exact artist or title match and a penalty for candidates carrying no
    usable year — those cannot answer the question the host is asking.
    """
    score = float(candidate.get("score") or 0)
    if _norm(str(candidate.get("artist") or "")) == _norm(query_artist):
        score += 25
    if _norm(str(candidate.get("title") or "")) == _norm(query_title):
        score += 25
    if not candidate.get("year"):
        # Decisive, not merely a nudge: the host is choosing a YEAR, so a
        # candidate that has none cannot answer the question no matter how
        # well its name matches. Keep it visible (it may confirm the
        # identity) but always below anything that can actually be picked.
        score -= 1000
    return score


def rank_candidates(
    candidates: list[dict[str, Any]],
    *,
    artist: str,
    title: str,
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Best-first, de-duplicated by (artist, title, year). Pure.

    MusicBrainz returns many pressings of one recording; the host wants
    distinct answers to "which song and which year is this", not a list of
    releases.
    """
    seen: set[tuple[str, str, Any]] = set()
    scored: list[tuple[float, dict[str, Any]]] = []
    for cand in candidates:
        if not isinstance(cand, dict):
            continue
        key = (
            _norm(str(cand.get("artist") or "")),
            _norm(str(cand.get("title") or "")),
            cand.get("year"),
        )
        if key in seen:
            continue
        seen.add(key)
        scored.append(
            (score_candidate(cand, query_artist=artist, query_title=title), cand)
        )
    scored.sort(key=lambda pair: -pair[0])
    return [cand for _score, cand in scored[:limit]]


def validate_year(value: Any) -> tuple[int | None, str | None]:
    """Coerce a user-entered year. Returns ``(year, error)``. Pure."""
    if value is None or value == "":
        return None, None
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None, "Year must be a number"
    current = time.gmtime().tm_year
    if not (1860 <= year <= current + 1):
        return None, f"Year must be between 1860 and {current + 1}"
    return year, None


def apply_correction(
    entry: dict[str, Any],
    *,
    year: int | None = None,
    title: str | None = None,
    artist: str | None = None,
    note: str | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Return ``entry`` updated with a host correction. Pure.

    Identity corrections (title/artist) are kept alongside the originals: the
    file on disk still has the old tags, and a future scan must be able to
    recognise the same track. ``genres_checked`` is reset when the identity
    changes, because genres derived from a misidentified track are equally
    wrong — the next enrichment pass will re-fetch them for the corrected
    name while leaving the human-set year alone.
    """
    updated = dict(entry)
    stamp = int(now if now is not None else time.time())

    identity_changed = False
    if title is not None and str(title).strip():
        new_title = str(title).strip()
        if _norm(new_title) != _norm(str(entry.get("title") or "")):
            updated.setdefault("original_title", entry.get("title"))
            updated["title"] = new_title
            identity_changed = True
    if artist is not None and str(artist).strip():
        new_artist = str(artist).strip()
        if _norm(new_artist) != _norm(str(entry.get("artist") or "")):
            updated.setdefault("original_artist", entry.get("artist"))
            updated["artist"] = new_artist
            identity_changed = True

    if year is not None:
        updated["year"] = int(year)
        updated["year_confidence"] = int(YearConfidence.USER_VERIFIED)
        updated["year_source"] = CORRECTION_SOURCE

    if identity_changed:
        # The precomputed dedupe key (#2694) was derived from the OLD name.
        # Drop it; entry_key falls back to computing one until the next
        # finalize_pool writes a fresh one.
        updated.pop(NORM_KEY_FIELD, None)
        # Genres inferred for the wrong track are wrong too; let the next
        # enrichment pass redo them for the corrected identity.
        updated["genres_checked"] = 0
        updated["genres"] = []
        # Popularity was matched on the old name — re-verify it as well.
        updated["popularity_verified"] = False

    updated["user_corrected"] = True
    updated["corrected_at"] = stamp
    if note:
        updated["correction_note"] = str(note)[:200]
    return updated


def is_locked(entry: dict[str, Any]) -> bool:
    """True when a host correction must not be overwritten by automation."""
    return bool(entry.get("user_corrected")) or entry.get("year_source") == (
        CORRECTION_SOURCE
    )


def correction_summary(entry: dict[str, Any]) -> dict[str, Any]:
    """What the UI shows about an existing correction. Pure."""
    return {
        "corrected": is_locked(entry),
        "corrected_at": entry.get("corrected_at"),
        "original_title": entry.get("original_title"),
        "original_artist": entry.get("original_artist"),
        "note": entry.get("correction_note"),
    }
