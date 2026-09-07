"""Library-sourced playlist provider for Beatify.

Generates Beatify playlists from the user's own Plex / Jellyfin / local library
(via Music Assistant) instead of relying on curated, streaming-specific
playlists. This sidesteps mholzi's blocker in issue #45 ("users may not have the
songs from a curated playlist") by construction: every song is sourced from the
user's library, so it is always present and always playable.

Two hard problems this package solves (see year_resolver.py / popularity.py):
  1. Trustworthy release years (the game scores year guesses): external sources
     are authoritative (MusicBrainz, match-verified), with tags gated out by
     default so unreliable years never reach a game.
  2. A real difficulty / familiarity slider via worldwide popularity (MA-native,
     or keyless Deezer / optional Last.fm), banded on an absolute global-fame
     scale so it's fair across different people's libraries.

Public surface:
  async_build_pool(hass, ...)        -> scan + enrich + cache (slow, run once)
  async_generate_library_playlist()  -> sample a fresh playlist (instant)
  pool_stats(pool)                   -> counts for the admin UI

Note: the pure-logic modules (year_resolver, popularity, generator) have no
Home Assistant dependency and can be imported standalone. The HA-dependent
pieces (pool, ma_client) are imported lazily so this package's logic remains
unit-testable without Home Assistant installed.
"""

from __future__ import annotations

import functools
import logging
from typing import TYPE_CHECKING, Any

from .generator import generate_playlist
from .popularity import slider_to_target_band
from .version import __version__
from .year_resolver import YearConfidence

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

__all__ = [
    "__version__",
    "async_build_pool",
    "async_generate_library_playlist",
    "async_load_pool",
    "async_load_pool_cached",
    "pool_path",
    "pool_stats",
]


def __getattr__(name: str) -> Any:
    """Lazily expose the HA-dependent pool helpers.

    Importing them at module top level would pull in `homeassistant`, which
    breaks standalone use/tests of the pure logic. PEP 562 module __getattr__
    defers that import until one of these names is actually accessed.
    """
    if name in (
        "async_build_pool",
        "async_load_pool",
        "async_load_pool_cached",
        "pool_path",
        "pool_stats",
    ):
        from . import pool as _pool

        return getattr(_pool, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


async def async_generate_library_playlist(
    hass: HomeAssistant,
    *,
    size: int = 30,
    difficulty_slider: int = 50,
    popularity_percent: int | None = None,
    genres: list[str] | None = None,
    min_confidence: int = int(YearConfidence.EXTERNAL_PRIMARY),
    balance_decades: bool = True,
    exclude_uris: set[str] | None = None,
) -> dict[str, Any] | None:
    """Load the cached pool and sample a fresh game playlist.

    Returns a Beatify-schema playlist dict, or None if no pool has been built
    yet (caller should prompt the user to run the pool build first).

    `min_confidence` defaults to EXTERNAL_PRIMARY: only songs with a verified
    MusicBrainz year are used, since tag years are unreliable and unfair across
    libraries. Relax to EXTERNAL_SECONDARY to also use Deezer-fallback years
    (requires building with year_fallback=True), or to TAG_STUDIO to permit
    studio-album tag years when external coverage is thin.

    `difficulty_slider` is 0 (famous / easy) .. 100 (obscure / hard) and maps to
    a WORLDWIDE familiarity band -- orthogonal to Beatify's scoring difficulty.
    """
    from . import pool as _pool

    # #2694: read-only, cached parse. This runs twice per game — at game
    # creation and again from the pre-start hook that fires on the host's
    # "Start" tap — and re-parsing an 11 MB pool blocked the event loop both
    # times. The cache keys on the file's mtime+size, so a scan or correction
    # invalidates it by itself. NOTHING below may mutate `cached`.
    #
    # The familiarity_band recompute that used to sit here (older pools stored
    # an absolute, miscalibrated band) now happens once per pool version
    # inside pool.prepare_pool_for_generate, in the executor.
    cached = await _pool.async_load_pool_cached(hass)
    if not cached or not cached.get("songs"):
        _LOGGER.warning("No library pool built yet; run beatify.build_library_pool")
        return None

    band = slider_to_target_band(difficulty_slider)

    # popularity_percent (0..100) is the new precise control: it means "draw
    # from the most-popular P% of the library". P=100 -> whole library (any
    # popularity); P=10 -> only the top 10% by worldwide rank. Maps to a
    # percentile window [1 - P/100, 1.0]. When absent, fall back to the band.
    pop_min_pct = None
    if popularity_percent is not None:
        p = max(1, min(100, int(popularity_percent)))
        pop_min_pct = 1.0 - (p / 100.0)

    # #2694: generate_playlist is pure and CPU-bound (dedupe + filtering +
    # decade balancing over the whole pool). On an 18k-song library it blocked
    # the event loop for ~40 ms here on Apple Silicon and several hundred on a
    # Raspberry Pi, immediately in front of the first play_song. Off to a
    # worker thread it goes.
    playlist = await hass.async_add_executor_job(
        functools.partial(
            generate_playlist,
            cached["songs"],
            size=size,
            difficulty_band=band,
            popularity_min_percentile=pop_min_pct,
            genres=set(genres) if genres else None,
            min_confidence=min_confidence,
            balance_decades=balance_decades,
            exclude_uris=exclude_uris,
        )
    )
    # Observability: one INFO line per generation so setting/effect mismatches
    # are visible in the HA log instead of needing UI archaeology.
    # Self-diagnosing UI: persist the summary so the panel can show what the
    # last game actually used — no log access needed (logger.set_level resets
    # on every HA restart, which made the log-based verification vanish).
    import time as _time

    from custom_components.beatify.const import DOMAIN as _DOMAIN

    hass.data.setdefault(_DOMAIN, {})["library_last_generate"] = {
        "ts": int(_time.time()),
        "size": size,
        "pop_percent": popularity_percent,
        "genres": sorted(genres) if genres else [],
        "eligible": playlist.get("_eligible_count"),
        "chosen": len(playlist.get("songs") or []),
        "widened": bool(playlist.get("_window_widened")),
        "genres_expanded": playlist.get("_genres_expanded") or [],
    }

    _LOGGER.info(
        "Library generate: size=%d pop_percent=%s window_min_pct=%s genres=%s "
        "eligible=%s chosen=%d excluded_recent=%d widened=%s expanded=%s",
        size,
        popularity_percent,
        f"{pop_min_pct:.2f}" if pop_min_pct is not None else None,
        sorted(genres) if genres else None,
        playlist.get("_eligible_count"),
        len(playlist.get("songs") or []),
        len(exclude_uris or ()),
        bool(playlist.get("_window_widened")),
        playlist.get("_genres_expanded") or None,
    )
    if not playlist["songs"]:
        _LOGGER.warning(
            "Library pool has no songs meeting confidence>=%d; "
            "rebuild with MusicBrainz enabled or lower the trust gate.",
            min_confidence,
        )
    return playlist
