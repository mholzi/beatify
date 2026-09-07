"""Build and cache the enriched library pool.

Two-phase model (this is what makes it both trustworthy AND instantly
re-playable):

  PHASE 1 - build_pool (slow, run once, cached):
     scan MA library -> resolve trustworthy years (MusicBrainz authoritative)
     -> fetch popularity (MA-native / Deezer / Last.fm) -> global fame scores
     -> write JSON. Rate-limited and incremental: re-running only enriches
     new/unenriched tracks, so a refresh is cheap after the first build.

  PHASE 2 - generator.generate_playlist (instant, every game):
     sample from the cached pool. No network. Re-roll = re-sample.

The cache lives at `<config>/beatify/playlists/user/_library_pool.json`.
Enrichment is best-effort: a track that MB/Deezer can't resolve still lands in
the pool with whatever confidence its tags earned. Only the year-confidence
gate (applied later, in the generator) decides what actually reaches a game.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import random
import time
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import corrections
from .generator import NORM_KEY_FIELD, _norm_key
from .ma_client import (
    async_fetch_track_genres,
    async_iter_all_library_tracks,
    async_sample_new_tracks,
    find_ma_config_entry_ids,
    split_library_uri,
)
from .popularity import (
    SOURCE_DEEZER_RANK,
    SOURCE_LASTFM_LISTENERS,
    SOURCE_SCALE_0_100,
    assign_percentiles,
    async_deezer_album_genres,
    async_deezer_rank_album,
    async_deezer_release_year,
    async_lastfm_listeners,
    percentile_band,
    to_global_score,
)
from .version import POOL_SCHEMA_VERSION
from .version import __version__ as ENGINE_VERSION
from .year_resolver import (
    DEFAULT_MIN_CONFIDENCE,
    MusicBrainzThrottle,
    YearConfidence,
    async_musicbrainz_year_genres,
    resolve_year,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# NOTE: deliberately OUTSIDE beatify/playlists/ — the playlist scanner globs
# **/*.json under that tree and would list the pool as a broken playlist in
# the "Mine" tab. The pool is engine data, not a playlist.
POOL_RELATIVE_PATH = "beatify/library_pool.json"

# Parsed-pool cache (issue #2694). An 18k-song pool is a ~11 MB JSON document
# and Crate Digger loads it TWICE per game — once at create, once from the
# pre-start hook that fires on the host's "Start" tap. The parse is keyed by
# the file's (path, mtime_ns, size), so any write — a scan checkpoint, a year
# correction, a manual edit — produces a new key and the next load re-reads.
# Held for a while, then dropped: a Raspberry Pi should not carry the pool in
# RAM between parties.
_POOL_CACHE_KEY = "library_pool_cache"
_POOL_CACHE_TTL = 900.0  # seconds

# Concurrency for popularity lookups (Deezer tolerates a few in flight).
# MusicBrainz is serialized separately by its 1 req/s throttle.
_RESOLVER_V = 3  # v3: dash-right-side query candidates (Main Title - Scarface class)
_POPULARITY_CONCURRENCY = 4
_CHECKPOINT_BATCH = 200
_GENRES_CHECK_V = 2  # int-versioned; bool True from older pools counts as v1  # write the pool every N enriched songs (crash-safe)


def select_scan_subset(
    tracks: list[dict[str, Any]],
    cached_uris: set[str],
    target_size: int | None,
    rng: random.Random | None = None,
) -> list[dict[str, Any]]:
    """Choose which tracks to process this scan. Pure.

    Huge libraries (100k+ songs) cannot be fully enriched in one sitting --
    MusicBrainz allows ~1 lookup/second, so 300k songs would take days.
    Semantics ("each rescan keeps what's prepared and ADDS more"):

      * every already-enriched track is always included (their re-processing
        is cheap: cached year/popularity are reused, no network), and
      * `target_size` counts NEW tracks to add on top -- a random sample of
        the not-yet-enriched remainder. None or <= 0 means all of them.

    The pool itself is merge-written, so it only ever grows.
    """
    cached = [t for t in tracks if t.get("uri") in cached_uris]
    rest = [t for t in tracks if t.get("uri") not in cached_uris]
    if target_size is None or target_size <= 0 or len(rest) <= target_size:
        return cached + rest
    rng = rng or random.Random()
    return cached + rng.sample(rest, target_size)


def pool_path(hass: HomeAssistant) -> Path:
    return Path(hass.config.path(POOL_RELATIVE_PATH))


async def async_load_pool(hass: HomeAssistant) -> dict[str, Any] | None:
    path = pool_path(hass)

    def _read() -> dict[str, Any] | None:
        for candidate in (path, path.with_suffix(".json.bak")):
            if not candidate.exists():
                continue
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as err:
                _LOGGER.warning("Could not read %s: %s", candidate.name, err)
                continue
            if candidate != path:
                _LOGGER.warning(
                    "Library pool unreadable; recovered previous scan from %s",
                    candidate.name,
                )
            return data
        return None

    try:
        return await hass.async_add_executor_job(_read)
    except Exception as err:  # noqa: BLE001
        _LOGGER.warning("Could not read library pool: %s", err)
        return None


def _pool_signature(path: Path) -> tuple[str, int, int] | None:
    """(path, mtime_ns, size) of the pool file, or None when it is unreadable.

    Any write to the pool — scan checkpoint, refresh, correction, or a manual
    edit — changes at least the mtime, so a stale parse can never be served.
    """
    try:
        st = path.stat()
    except OSError:
        return None
    return (str(path), st.st_mtime_ns, st.st_size)


def prepare_pool_for_generate(pool: dict[str, Any]) -> dict[str, Any]:
    """Do the per-song fix-ups the generate path needs, once. Blocking.

    Both of these used to run on the event loop on EVERY generate call:

    * ``familiarity_band`` — older pools stored an absolute (miscalibrated)
      band; recomputing it from the stored percentile gives existing pools the
      corrected difficulty split without a rescan.
    * ``_norm_key`` — pools written before #2694 have no precomputed dedupe
      key. Filling it here means the generator computes it once per pool
      version instead of twice per song per game.

    Call it from an executor. Mutates ``pool`` in place and returns it.
    """
    for entry in pool.get("songs") or ():
        pct = entry.get("popularity_percentile")
        if pct is not None:
            entry["familiarity_band"] = percentile_band(pct)
        if not entry.get(NORM_KEY_FIELD):
            entry[NORM_KEY_FIELD] = _norm_key(
                entry.get("artist") or "", entry.get("title") or ""
            )
    return pool


def _cache_store(hass: HomeAssistant) -> dict[str, Any]:
    from custom_components.beatify.const import DOMAIN

    return hass.data.setdefault(DOMAIN, {})


def invalidate_pool_cache(hass: HomeAssistant) -> None:
    """Forget the cached parse (and cancel its eviction timer)."""
    cached = _cache_store(hass).pop(_POOL_CACHE_KEY, None)
    if cached is not None:
        with contextlib.suppress(Exception):
            cached["evict"].cancel()


async def async_load_pool_cached(hass: HomeAssistant) -> dict[str, Any] | None:
    """Load the pool for READ-ONLY use, reusing the previous parse.

    Crate Digger loads the pool twice per game (game creation, then the
    pre-start hook on the host's "Start" tap) and an 18k-song pool is ~11 MB
    of JSON — a parse that blocked the event loop both times (#2694). The
    parse is cached under ``hass.data`` keyed by the file's mtime and size, so
    the second load is a dict lookup and any write invalidates it by itself.

    THE RETURNED DICT IS SHARED. Callers must not mutate it; anything that
    writes the pool back (build, refresh, corrections) must keep using
    :func:`async_load_pool`, which always returns a fresh parse.
    """
    path = pool_path(hass)
    store = _cache_store(hass)
    signature = await hass.async_add_executor_job(_pool_signature, path)

    cached = store.get(_POOL_CACHE_KEY)
    if cached is not None and signature is not None and cached["sig"] == signature:
        return cached["pool"]

    invalidate_pool_cache(hass)
    pool = await async_load_pool(hass)
    if pool is None:
        return None
    await hass.async_add_executor_job(prepare_pool_for_generate, pool)

    if signature is not None:
        # Drop it again after a while: an idle Raspberry Pi should not hold
        # the whole library in RAM between parties.
        store[_POOL_CACHE_KEY] = {
            "sig": signature,
            "pool": pool,
            "evict": hass.loop.call_later(
                _POOL_CACHE_TTL, lambda: store.pop(_POOL_CACHE_KEY, None)
            ),
        }
    return pool


def finalize_pool(
    entries: dict[str, dict[str, Any]],
    *,
    built_at: int,
    config_entry_id: str | None,
    library_total: int | None,
    target_size: int | None,
) -> dict[str, Any]:
    """Assemble the persisted pool dict from merged entries. Module-level so
    both async_build_pool and async_refresh_pool share it (the refresh path
    crashed twice on names that only existed inside the build closure —
    _CHECKPOINT_BATCH, then this function; extraction ends that class)."""
    songs = list(entries.values())
    global_scores = [x.get("global_score") for x in songs]
    percentiles = assign_percentiles(global_scores)
    for x, pct in zip(songs, percentiles):
        x["popularity_percentile"] = pct
        # Band by percentile within THIS library (fair + robust across
        # libraries); keep the absolute score only as an info hint.
        x["familiarity_band"] = percentile_band(pct)
        # Precomputed dedupe key (#2694): the generator needed it twice per
        # song per game, each time re-running NFKD + two regex passes. Written
        # once here, when the entry is created. Recomputed only for entries
        # that lack it (a rebuild does not redo the whole pool) or whose
        # artist/title changed (async_build_pool drops the field in that case).
        if not x.get(NORM_KEY_FIELD):
            x[NORM_KEY_FIELD] = _norm_key(x.get("artist") or "", x.get("title") or "")
    usable = sum(
        1 for x in songs if int(x.get("year_confidence", 0)) >= DEFAULT_MIN_CONFIDENCE
    )
    return {
        "_schema": POOL_SCHEMA_VERSION,
        "_engine_version": ENGINE_VERSION,
        "_built_at": built_at,
        "_config_entry_id": config_entry_id,
        "_track_count": len(songs),
        "_library_total": library_total,
        "_target_size": target_size,
        "_usable_count": usable,
        "songs": songs,
    }


async def async_build_pool(
    hass: HomeAssistant,
    *,
    config_entry_id: str | None = None,
    use_musicbrainz: bool = True,
    year_fallback: bool = False,
    lastfm_api_key: str | None = None,
    target_size: int | None = 2500,
    progress_cb: Callable[[str, int, int], None] | None = None,
) -> dict[str, Any]:
    """Scan, enrich, cache, and return the library pool.

    Args:
        config_entry_id: which MA server; defaults to the first loaded one.
        use_musicbrainz: enrich years via MusicBrainz (the authoritative source).
            Strongly recommended -- with the default external-only gate, songs
            without a MusicBrainz year are excluded from games.
        year_fallback: if True, recover a year from Deezer (secondary external)
            for tracks MusicBrainz can't match. The resulting years are
            EXTERNAL_SECONDARY confidence and only reach a game if the
            generation gate is relaxed to include them.
        lastfm_api_key: if set, use Last.fm listeners for popularity instead of
            Deezer rank.
        progress_cb: optional (phase, done, total) callback for UI feedback.

    Returns the pool dict (also written to disk).
    """
    if config_entry_id is None:
        ids = find_ma_config_entry_ids(hass)
        if not ids:
            raise RuntimeError("No loaded Music Assistant config entry found")
        config_entry_id = ids[0]

    started = time.time()

    # Reuse already-enriched entries so rebuilds are incremental. (Loaded
    # before enumeration now: sampling needs the cached URI set.)
    existing = await async_load_pool(hass)
    cache: dict[str, dict[str, Any]] = {}
    if existing and isinstance(existing.get("songs"), list):
        for s in existing["songs"]:
            if s.get("uri_ma_library"):
                cache[s["uri_ma_library"]] = s

    if target_size and target_size > 0:
        # P3: RANDOM-PAGE SAMPLING instead of reading all ~300k tracks before
        # every scan. Probes the library size (~2*log2 N one-item calls), then
        # fetches random pages until enough UNSEEN tracks are collected.
        sampled, library_total = await async_sample_new_tracks(
            hass,
            config_entry_id,
            set(cache),
            target_size,
            progress_cb=progress_cb,
        )
        if sampled or cache:
            raw_tracks = sampled
            library_total = library_total or (len(cache) + len(sampled))
        else:
            # Sampling found nothing and no cache exists — fall back to the
            # full read (tiny library or probe failure).
            raw_tracks = await async_iter_all_library_tracks(
                hass, config_entry_id, progress_cb=progress_cb
            )
            library_total = len(raw_tracks)
    else:
        # target 0/None = prepare the ENTIRE library: full read is the point.
        raw_tracks = await async_iter_all_library_tracks(
            hass, config_entry_id, progress_cb=progress_cb
        )
        library_total = len(raw_tracks)

    # Huge-library handling: with sampling, raw_tracks are already the new
    # candidates; with a full read, select the subset (cached-first).
    selected = (
        raw_tracks
        if (target_size and target_size > 0)
        else select_scan_subset(raw_tracks, set(cache), target_size)
    )

    # ADDITIVE scans (bug fix): cached tracks must not re-enter the enrichment
    # loop — a "1,000-song scan" was showing 16,000 because the 15k cached
    # entries were counted (and iterated) again. Instead, refresh their cheap
    # basic fields in-memory (title/artist/album/genres — this is what carries
    # genre backfill) and enrich ONLY the genuinely new tracks.
    new_tracks: list[dict[str, Any]] = []
    refreshed = 0
    for t in selected:
        uri = t.get("uri")
        entry = cache.get(uri)
        if entry is None:
            new_tracks.append(t)
            continue
        _prev_name = (entry.get("artist"), entry.get("title"))
        entry["title"] = t.get("title") or entry.get("title")
        entry["artist"] = t.get("artist") or entry.get("artist")
        entry["album"] = t.get("album") or entry.get("album")
        if (entry.get("artist"), entry.get("title")) != _prev_name:
            entry.pop(NORM_KEY_FIELD, None)  # stale; finalize_pool recomputes
        if t.get("genres"):
            entry["genres"] = t["genres"]
        refreshed += 1

    raw_tracks = new_tracks
    total = len(raw_tracks)

    # P1: genres come only from MA DETAIL fetches (list models are slim — a
    # 16k scan captured zero). Fetch for all NEW tracks plus cached entries
    # never checked. LAN-local, concurrent, failure-tolerant.
    genre_jobs: list[tuple[str, str, str]] = []
    for t in new_tracks:
        prov, item = t.get("provider"), t.get("item_id")
        if not (prov and item):
            parsed = split_library_uri(t.get("uri"))
            if parsed:
                prov, item = parsed
        if prov and item:
            genre_jobs.append((t["uri"], prov, item))
    backfill_keys: set[str] = set()

    def _genre_flag_v(entry: dict[str, Any]) -> int:
        v = entry.get("genres_checked")
        if v is True:
            return 1
        try:
            return int(v or 0)
        except (TypeError, ValueError):
            return 0

    for uri, entry in cache.items():
        if entry.get("genres") or _genre_flag_v(entry) >= _GENRES_CHECK_V:
            continue
        parsed = split_library_uri(uri)
        if parsed:
            genre_jobs.append((uri, parsed[0], parsed[1]))
            backfill_keys.add(uri)
    if genre_jobs:
        if progress_cb:
            progress_cb("genres", 0, len(genre_jobs))
        genre_map = await async_fetch_track_genres(
            hass, config_entry_id, genre_jobs, progress_cb=progress_cb
        )
        for t in new_tracks:
            if t["uri"] in genre_map:
                t["genres"] = genre_map[t["uri"]]
        for uri in backfill_keys:
            entry = cache.get(uri)
            if entry is not None:
                if uri in genre_map:
                    entry["genres"] = genre_map[uri]
                entry["genres_checked"] = _GENRES_CHECK_V
        _log = _LOGGER.warning if not genre_map else _LOGGER.info
        _log(
            "Library pool: genre detail-fetch — %d looked up, %d with genres",
            len(genre_jobs),
            len(genre_map),
        )
    _LOGGER.info(
        "Library pool: enriching %d NEW tracks (+%d cached refreshed, "
        "library=%d, target_size=%s)",
        total,
        refreshed,
        library_total,
        target_size,
    )

    session = _get_session(hass)
    throttle = MusicBrainzThrottle()

    pop_sem = asyncio.Semaphore(_POPULARITY_CONCURRENCY)

    async def _enrich_one(idx: int, t: dict[str, Any]) -> dict[str, Any]:
        uri = t["uri"]
        prior = cache.get(uri)

        # --- Year ---
        mb_year = None
        if use_musicbrainz:
            if prior and prior.get("year_source") == "musicbrainz":
                mb_year = prior.get("year")  # already resolved; don't re-hit MB
            else:
                mb_year, _mb_genres = await async_musicbrainz_year_genres(
                    session, t["artist"], t["title"], throttle
                )
                # Genre chain step 2 (MB tags — free, same responses): MA's
                # library metadata is genre-empty for Plex syncs (measured:
                # 20k detail fetches -> 0 genres), so external tags are the
                # real source.
                if not t.get("genres") and _mb_genres:
                    t["genres"] = _mb_genres

        # Secondary external year (Deezer): only when MB missed AND opted in.
        secondary_year = None
        if year_fallback and mb_year is None:
            if prior and prior.get("year_source") == "deezer":
                secondary_year = prior.get("year")
            else:
                async with pop_sem:
                    secondary_year = await async_deezer_release_year(
                        session, t["artist"], t["title"]
                    )

        resolved = resolve_year(
            musicbrainz_year=mb_year,
            secondary_external_year=secondary_year,
            tag_year=t.get("year"),
            album_type=t.get("album_type"),
            album_artist=t.get("album_artist"),
            album_name=t.get("album"),
        )

        # --- Popularity ---
        # Prefer MA's own popularity (free, already local). Only reach out to
        # Deezer/Last.fm when MA has none (typical for pure-local Plex/Jellyfin
        # files). ALL sources are WORLDWIDE metrics -- never the host's plays.
        pop_source = None
        if prior and prior.get("popularity_raw") is not None:
            pop_raw = prior["popularity_raw"]
            pop_source = prior.get("popularity_source")
        elif t.get("ma_popularity") is not None:
            pop_raw = t["ma_popularity"]
            pop_source = SOURCE_SCALE_0_100  # MA popularity is a 0..100 global metric
        else:
            async with pop_sem:
                if lastfm_api_key:
                    pop_raw = await async_lastfm_listeners(
                        session, lastfm_api_key, t["artist"], t["title"]
                    )
                    pop_source = SOURCE_LASTFM_LISTENERS
                else:
                    pop_raw, _dz_album = await async_deezer_rank_album(
                        session, t["artist"], t["title"]
                    )
                    pop_source = SOURCE_DEEZER_RANK
                    # Genre chain step 3: Deezer album genres (coarse Pop/
                    # Rock/Dance… — ideal for the chips) when MA+MB had none.
                    if not t.get("genres") and _dz_album:
                        t["genres"] = await async_deezer_album_genres(
                            session, _dz_album
                        )

        global_score = (
            to_global_score(pop_raw, pop_source) if pop_raw is not None else None
        )

        if progress_cb and idx % 25 == 0:
            progress_cb("enrich", idx, total)

        return {
            "title": t["title"],
            "artist": t["artist"],
            "album": t.get("album"),
            "genres": t.get("genres") or [],
            "item_id": t.get("item_id") or None,
            "provider": t.get("provider") or None,
            "genres_checked": _GENRES_CHECK_V,
            "popularity_verified": True,
            "_resolver_v": _RESOLVER_V,
            "uri_ma_library": uri,
            "year": resolved.year,
            "year_confidence": int(resolved.confidence),
            "year_source": resolved.source,
            "popularity_raw": pop_raw,
            "popularity_source": pop_source,
            "global_score": global_score,  # 0..100 WORLDWIDE fame (the fair axis)
        }

    # Enrich in batches with CHECKPOINT writes: an 8-hour scan of a huge
    # library must survive a Home Assistant restart. After every batch the
    # pool on disk is the merge of everything ever enriched (old entries are
    # never dropped -- the pool only grows), so an interruption costs at most
    # one batch and the next scan resumes from the cache.
    merged: dict[str, dict[str, Any]] = dict(cache)

    def _finalize(entries: dict[str, dict[str, Any]]) -> dict[str, Any]:
        return finalize_pool(
            entries,
            built_at=int(started),
            config_entry_id=config_entry_id,
            library_total=library_total,
            target_size=target_size,
        )

    done = 0
    for i in range(0, total, _CHECKPOINT_BATCH):
        batch = raw_tracks[i : i + _CHECKPOINT_BATCH]
        results = await asyncio.gather(
            *(_enrich_one(i + j, t) for j, t in enumerate(batch))
        )
        for entry in results:
            if entry.get("uri_ma_library"):
                merged[entry["uri_ma_library"]] = entry
        done += len(batch)
        await _write_pool(hass, _finalize(merged))  # checkpoint
        _LOGGER.debug("Library pool checkpoint: %d/%d", done, total)

    pool = _finalize(merged)
    await _write_pool(hass, pool)
    _LOGGER.info(
        "Library pool built: %d prepared (%d usable, verified year), %.0fs",
        pool["_track_count"],
        pool["_usable_count"],
        time.time() - started,
    )
    if progress_cb:
        progress_cb("done", total, total)
    return pool


async def _write_pool(hass: HomeAssistant, pool: dict[str, Any]) -> None:
    path = pool_path(hass)
    # The read cache keys on mtime+size, which already covers this; dropping it
    # explicitly closes the window where a rewrite happens to land on the same
    # mtime_ns AND the same byte count.
    invalidate_pool_cache(hass)

    def _write() -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        # ATOMIC write: an HA restart mid-write must never truncate the pool
        # (a truncated JSON silently cost a real user an 18k-song enriched
        # pool). Write to a temp file, fsync, keep the previous good pool as
        # .bak, then atomically replace.
        tmp = path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps(pool, ensure_ascii=False, indent=1))
            fh.flush()
            os.fsync(fh.fileno())
        if path.exists():
            with contextlib.suppress(OSError):
                os.replace(path, path.with_suffix(".json.bak"))
        os.replace(tmp, path)

    await hass.async_add_executor_job(_write)


def _get_session(hass: HomeAssistant) -> Any:
    """HA's shared aiohttp session (lazy import to keep module HA-optional)."""
    from homeassistant.helpers.aiohttp_client import async_get_clientsession

    return async_get_clientsession(hass)


def pool_stats(pool: dict[str, Any]) -> dict[str, Any]:
    """Summarize a pool for the status endpoint / admin panel. Pure."""
    songs = pool.get("songs") or []
    total = len(songs)

    strict = sum(
        1
        for s in songs
        if int(s.get("year_confidence", 0)) >= int(YearConfidence.EXTERNAL_PRIMARY)
    )
    balanced = sum(
        1
        for s in songs
        if int(s.get("year_confidence", 0)) >= int(YearConfidence.EXTERNAL_SECONDARY)
    )
    tags_ok = sum(
        1
        for s in songs
        if int(s.get("year_confidence", 0)) >= int(YearConfidence.TAG_STUDIO)
    )
    scored = sum(1 for s in songs if s.get("global_score") is not None)

    genre_counts: dict[str, int] = {}
    for s_ in songs:
        for g in s_.get("genres") or []:
            genre_counts[g] = genre_counts.get(g, 0) + 1
    top_genres = sorted(genre_counts.items(), key=lambda kv: -kv[1])[:24]

    return {
        "total": total,
        "usable": strict,
        "verified_strict": strict,
        "verified_balanced": balanced,
        "verified_tags": tags_ok,
        "scored": scored,
        "unscored": total - scored,
        "genres": [{"name": g, "count": c} for g, c in top_genres],
        "genre_coverage": sum(1 for s_ in songs if s_.get("genres")),
    }


# ---------------------------------------------------------------------------
# Separate REFRESH pass (v0.7.1): re-resolve years (v2 resolver) and re-verify
# popularity for entries created before those fixes. Runs as its OWN
# background job — decoupled from scans so a "1,000-song, 20-minute" scan is
# never silently turned into a multi-hour refresh. Progress is reported under
# the "refresh" phase and the whole pass is resumable (version-flagged +
# checkpointed).
# ---------------------------------------------------------------------------


def refresh_backlog_count(pool: dict[str, Any] | None) -> dict[str, int]:
    """How many entries still need year/popularity refresh. Pure."""
    if not pool or not isinstance(pool.get("songs"), list):
        return {"years": 0, "popularity": 0, "total": 0}
    songs = pool["songs"]
    years = sum(1 for e in songs if int(e.get("_resolver_v", 1)) < _RESOLVER_V)
    pops = sum(
        1
        for e in songs
        if e.get("popularity_raw") is not None
        and not e.get("popularity_verified")
        and int(e.get("_resolver_v", 1)) >= _RESOLVER_V
    )
    return {"years": years, "popularity": pops, "total": years + pops}


def _refreshed_pool(
    existing: dict[str, Any], merged: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """finalize_pool with scan metadata carried over from the existing pool."""
    return finalize_pool(
        merged,
        built_at=int(existing.get("_built_at") or time.time()),
        config_entry_id=existing.get("_config_entry_id"),
        library_total=existing.get("_library_total"),
        target_size=existing.get("_target_size"),
    )


async def async_refresh_pool(
    hass: HomeAssistant,
    *,
    use_musicbrainz: bool = True,
    progress_cb: Callable[[str, int, int], None] | None = None,
) -> dict[str, Any]:
    """Re-resolve years + re-verify popularity for stale pool entries.

    Independent of async_build_pool; safe to run alongside a scan (both
    load-modify-write the same pool with atomic writes and last-write-wins;
    the refresh only touches entries a scan wouldn't add). Returns a summary.
    """
    existing = await async_load_pool(hass)
    if not existing or not isinstance(existing.get("songs"), list):
        return {"refreshed": 0, "reason": "no_pool"}

    merged = {
        e["uri_ma_library"]: e for e in existing["songs"] if e.get("uri_ma_library")
    }
    session = _get_session(hass)
    throttle = MusicBrainzThrottle()
    pop_sem = asyncio.Semaphore(_POPULARITY_CONCURRENCY)

    year_q = [
        e
        for e in merged.values()
        if use_musicbrainz
        and int(e.get("_resolver_v", 1)) < _RESOLVER_V
        # Never re-resolve a year the host fixed by hand: a correction exists
        # precisely because the automatic answer was wrong, so overwriting it
        # would undo the fix on the next refresh.
        and not corrections.is_locked(e)
    ]
    _year_ids = {id(e) for e in year_q}
    pop_q = [
        e
        for e in merged.values()
        if e.get("popularity_raw") is not None
        and not e.get("popularity_verified")
        and id(e) not in _year_ids
    ]
    total = len(year_q) + len(pop_q)
    if not total:
        return {"refreshed": 0, "reason": "up_to_date"}

    _LOGGER.info(
        "Library refresh: %d year re-resolves, %d popularity re-verifications",
        len(year_q),
        len(pop_q),
    )

    async def _repop(e: dict[str, Any]) -> None:
        async with pop_sem:
            raw, dz_album = await async_deezer_rank_album(
                session, e["artist"], e["title"]
            )
            if not e.get("genres") and dz_album:
                e["genres"] = await async_deezer_album_genres(session, dz_album)
        e["popularity_raw"] = raw
        e["global_score"] = to_global_score(raw, SOURCE_DEEZER_RANK)
        e["popularity_verified"] = True

    done = 0
    for e in year_q:
        y, mb_genres = await async_musicbrainz_year_genres(
            session, e["artist"], e["title"], throttle
        )
        if not e.get("genres") and mb_genres:
            e["genres"] = mb_genres
        if y is not None and not corrections.is_locked(e):
            e["year"] = y
            e["year_confidence"] = int(YearConfidence.EXTERNAL_PRIMARY)
            e["year_source"] = "musicbrainz"
        e["_resolver_v"] = _RESOLVER_V
        await _repop(e)
        done += 1
        if progress_cb and done % 10 == 0:
            progress_cb("refresh", done, total)
        if done % _CHECKPOINT_BATCH == 0:
            await _write_pool(hass, _refreshed_pool(existing, merged))
    if pop_q:
        await asyncio.gather(*(_repop(e) for e in pop_q))
        done += len(pop_q)
    if progress_cb:
        progress_cb("refresh", done, total)

    await _write_pool(hass, _refreshed_pool(existing, merged))
    _LOGGER.info("Library refresh complete: %d entries", done)
    return {"refreshed": done, "years": len(year_q), "popularity": len(pop_q)}
