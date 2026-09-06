"""Music Assistant access for the library provider (MA 2.8.x).

IMPORTANT FINDING (verified against MA 2.8.8 / models 1.1.x, client 1.3.x):
The Home Assistant `music_assistant.get_library` *action* is NOT usable for this
feature. Its serializer (`media_item_dict_from_mass_item`) deliberately trims
every item down to {media_type, uri, name, version, image, favorite, explicit,
artists, album}, and the nested album is emitted as an ItemMapping -- so the
response carries **no year, no album_type, no popularity**. A scanner built on
that action would silently produce zero usable years.

So we go one layer deeper: the HA music_assistant integration holds a live
`MusicAssistantClient` on `config_entry.runtime_data.mass`. Calling
`mass.music.get_library_tracks(...)` returns the FULL `Track` models, with:

    track.name                       -> title
    track.artists[0].name            -> artist
    track.uri                        -> playable MA URI (uri_ma_library)
    track.album.year                 -> tag year (Album OR ItemMapping carry it)
    track.album.album_type           -> album/single/ep/compilation/live/...
    track.album.name                 -> album name (comp-name heuristic)
    track.album.artists[0].name      -> album artist (Various Artists detection)
    track.metadata.popularity        -> MA-native popularity (int|None) -- used
                                        FIRST, before Deezer/Last.fm
    track.metadata.release_date      -> datetime|None, secondary year source

We reuse the integration's own accessor when importable (version-correct), with
a tiny local fallback. Playback still goes through the existing
`music_assistant.play_media` HA service in services/media_player.py -- the client
is only used here for rich enumeration.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

MA_DOMAIN = "music_assistant"


def find_ma_config_entry_ids(hass: HomeAssistant) -> list[str]:
    """Return all loaded Music Assistant config entry IDs."""
    return [
        entry.entry_id
        for entry in hass.config_entries.async_entries(MA_DOMAIN)
        if entry.state.name == "LOADED"
    ]


def _get_client(hass: HomeAssistant, config_entry_id: str) -> Any:
    """Return the live MusicAssistantClient for a config entry.

    Prefer the integration's own accessor (tracks API changes for us); fall back
    to reading runtime_data.mass directly if the import path ever moves.
    """
    try:
        from homeassistant.components.music_assistant.helpers import (
            get_music_assistant_client,
        )

        return get_music_assistant_client(hass, config_entry_id)
    except Exception:  # noqa: BLE001
        entry = hass.config_entries.async_get_entry(config_entry_id)
        if entry is None or entry.state.name != "LOADED":
            raise RuntimeError("Music Assistant entry not loaded") from None
        return entry.runtime_data.mass


# --------------------------------------------------------------------------- #
# Enumeration via the MA client (full models).
# --------------------------------------------------------------------------- #


async def async_iter_all_library_tracks(
    hass: HomeAssistant,
    config_entry_id: str,
    *,
    page_size: int = 500,
    max_tracks: int | None = None,
    progress_cb: Any = None,
) -> list[dict[str, Any]]:
    """Page the entire track library, returning normalized dicts.

    Each dict: title, artist, uri, album, album_type, album_artist, year,
    release_year, ma_popularity. Missing fields are None.
    """
    mass = _get_client(hass, config_entry_id)
    out: list[dict[str, Any]] = []
    offset = 0
    while max_tracks is None or len(out) < max_tracks:
        try:
            tracks = await mass.music.get_library_tracks(
                limit=page_size, offset=offset, order_by="sort_name"
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.error("MA get_library_tracks failed at offset %d: %s", offset, err)
            break
        if not tracks:
            break
        for t in tracks:
            norm = _normalize_track(t)
            if norm:
                out.append(norm)
        if progress_cb:
            # Enumeration phase: total unknown (0) until the last page.
            progress_cb("enumerate", len(out), 0)
        if len(tracks) < page_size:
            break
        offset += page_size

    _LOGGER.info(
        "MA library: enumerated %d tracks (entry %s)", len(out), config_entry_id
    )
    return out


# --------------------------------------------------------------------------- #
# Track model -> plain dict. Uses getattr throughout so a minor model bump
# (renamed/missing optional field) degrades gracefully instead of crashing.
# --------------------------------------------------------------------------- #


def _name_of(obj: Any) -> str | None:
    name = getattr(obj, "name", None)
    if name:
        return str(name).strip()
    return None


def _first(seq: Any) -> Any:
    if isinstance(seq, (list, tuple)) and seq:
        return seq[0]
    return None


def _normalize_track(track: Any) -> dict[str, Any] | None:
    title = _name_of(track)
    uri = getattr(track, "uri", None)
    artist = _name_of(_first(getattr(track, "artists", None)))
    if not (title and uri and artist):
        return None

    album = getattr(track, "album", None)
    album_name = _name_of(album)
    album_year = getattr(album, "year", None) if album is not None else None
    album_type_raw = getattr(album, "album_type", None)
    album_type = str(album_type_raw) if album_type_raw is not None else None
    album_artist = _name_of(_first(getattr(album, "artists", None)))

    # Secondary year source from track metadata's release_date (datetime).
    release_year = None
    meta = getattr(track, "metadata", None)
    if meta is not None:
        rd = getattr(meta, "release_date", None)
        release_year = getattr(rd, "year", None)
        ma_pop = getattr(meta, "popularity", None)
        _genres_raw = getattr(meta, "genres", None)
    else:
        ma_pop = None
        _genres_raw = None
    # Genres (from MA's metadata, which mirrors Plex/Jellyfin tags). Kept
    # short + normalized; empty list when the server has none for the track.
    genres: list[str] = []
    if _genres_raw:
        try:
            genres = sorted({str(g).strip() for g in _genres_raw if str(g).strip()})[:8]
        except TypeError:
            genres = []

    # Prefer an explicit album.year; otherwise the release_date year.
    tag_year = album_year if isinstance(album_year, int) else release_year

    return {
        "genres": genres,
        "item_id": str(getattr(track, "item_id", "") or ""),
        "provider": str(getattr(track, "provider", "") or ""),
        "uri": str(uri),
        "title": title,
        "artist": artist,
        "album": album_name,
        "album_type": album_type,
        "album_artist": album_artist,
        "year": tag_year if isinstance(tag_year, int) else None,
        "release_year": release_year if isinstance(release_year, int) else None,
        "ma_popularity": float(ma_pop) if isinstance(ma_pop, (int, float)) else None,
    }


def split_library_uri(uri: str | None) -> tuple[str, str] | None:
    """Parse 'provider://track/item_id' MA URIs. Pure; None when unparseable.

    Lets older pool entries (created before item_id/provider were stored) join
    the genre-backfill pass.
    """
    if not uri or "://" not in uri:
        return None
    provider, _, rest = uri.partition("://")
    if not rest.startswith("track/"):
        return None
    item_id = rest[len("track/") :]
    if not provider or not item_id:
        return None
    return provider, item_id


def _genres_from_meta(meta: Any) -> list[str]:
    raw = getattr(meta, "genres", None) if meta is not None else None
    if not raw:
        return []
    try:
        return sorted({str(g).strip() for g in raw if str(g).strip()})[:8]
    except TypeError:
        return []


async def async_fetch_track_genres(
    hass: HomeAssistant,
    config_entry_id: str | None,
    jobs: list[tuple[str, str, str]],
    *,
    concurrency: int = 8,
    progress_cb: Any = None,
) -> dict[str, list[str]]:
    """Fetch genres via per-track DETAIL calls. LAN-local and fast.

    MA's LIST endpoints return slim models WITHOUT genre metadata (verified on
    a 16k-track scan that captured zero genres); only the detail fetch carries
    them. jobs = [(key, provider, item_id), ...]; returns {key: genres} for
    tracks that yielded any. Defensive about the client signature and never
    raises — genre absence must not break a scan.
    """
    client = _get_client(hass, config_entry_id)
    if client is None:
        return {}
    sem = asyncio.Semaphore(concurrency)
    out: dict[str, list[str]] = {}
    done = 0
    diag = {"track_ok": 0, "track_err": 0, "album_ok": 0, "no_genres": 0}
    _sample_logged = [False]

    async def _one(key: str, provider: str, item_id: str) -> None:
        nonlocal done
        async with sem:
            full = None
            try:
                full = await client.music.get_track(item_id, provider)
            except TypeError:
                try:
                    full = await client.music.get_track(
                        item_id=item_id, provider_instance_id_or_domain=provider
                    )
                except Exception as err:  # noqa: BLE001
                    diag["track_err"] += 1
                    if not _sample_logged[0]:
                        _LOGGER.warning(
                            "Genre fetch: get_track failed for %s/%s: %s",
                            provider,
                            item_id,
                            err,
                        )
                        _sample_logged[0] = True
            except Exception as err:  # noqa: BLE001
                diag["track_err"] += 1
                if not _sample_logged[0]:
                    _LOGGER.warning(
                        "Genre fetch: get_track raised for %s/%s: %s",
                        provider,
                        item_id,
                        err,
                    )
                    _sample_logged[0] = True
            genres: list[str] = []
            if full is not None:
                genres = _genres_from_meta(getattr(full, "metadata", None))
                # Fallback: Plex/Jellyfin often carry genre on the ALBUM, not
                # the track. Follow the track's album reference if present.
                if not genres:
                    album = getattr(full, "album", None)
                    alb_id = getattr(album, "item_id", None)
                    alb_prov = getattr(album, "provider", None) or provider
                    if alb_id:
                        try:
                            full_alb = await client.music.get_album(alb_id, alb_prov)
                            genres = _genres_from_meta(
                                getattr(full_alb, "metadata", None)
                            )
                            if genres:
                                diag["album_ok"] += 1
                        except Exception:  # noqa: BLE001
                            _LOGGER.debug(
                                "Album genre lookup failed for album %s/%s",
                                alb_prov,
                                alb_id,
                                exc_info=True,
                            )
                if genres:
                    diag["track_ok"] += 1 if key not in out else 0
                    out[key] = genres
                else:
                    diag["no_genres"] += 1
            done += 1
            if progress_cb and done % 50 == 0:
                progress_cb("genres", done, len(jobs))

    await asyncio.gather(*(_one(*j) for j in jobs))
    _log = _LOGGER.warning if (jobs and not out) else _LOGGER.info
    _log(
        "Genre fetch summary: %d jobs -> %d with genres (%d via album), "
        "%d no-genres, %d errors",
        len(jobs),
        len(out),
        diag["album_ok"],
        diag["no_genres"],
        diag["track_err"],
    )
    return out


async def async_probe_library_total(
    hass: HomeAssistant,
    config_entry_id: str | None = None,
    *,
    order_by: str = "sort_name",
) -> int | None:
    """Estimate the library's track count WITHOUT reading it (P3).

    Exponential probe for an empty page, then binary search on the boundary —
    ~2*log2(N) one-item requests instead of N/500 full pages.
    """
    client = _get_client(hass, config_entry_id)
    if client is None:
        return None

    async def _has(offset: int) -> bool:
        try:
            page = await client.music.get_library_tracks(
                limit=1, offset=offset, order_by=order_by
            )
        except Exception:  # noqa: BLE001
            return False
        return bool(page)

    if not await _has(0):
        return 0
    lo, hi = 0, 1024
    while await _has(hi):
        lo, hi = hi, hi * 2
        if hi > 5_000_000:  # sanity ceiling
            return hi
    while hi - lo > 1:
        mid = (lo + hi) // 2
        if await _has(mid):
            lo = mid
        else:
            hi = mid
    return hi


async def async_sample_new_tracks(
    hass: HomeAssistant,
    config_entry_id: str | None,
    cached_uris: set[str],
    needed: int,
    *,
    page_size: int = 500,
    order_by: str = "sort_name",
    progress_cb: Any = None,
) -> tuple[list[dict[str, Any]], int | None]:
    """Collect ~`needed` NOT-yet-scanned tracks via RANDOM page sampling (P3).

    Replaces the full-library enumeration (minutes at 300k tracks) for
    target-size scans: probe the total, then fetch random distinct pages
    until enough unseen tracks are gathered. Returns (tracks, library_total).
    Falls back to signalling exhaustion via a short list — the caller decides
    whether to full-enumerate (e.g. when the library is nearly fully scanned).
    """
    import random as _random

    total = await async_probe_library_total(hass, config_entry_id, order_by=order_by)
    if not total:
        return [], total
    client = _get_client(hass, config_entry_id)
    if client is None:
        return [], total

    offsets = list(range(0, total, page_size))
    _random.shuffle(offsets)
    max_pages = min(len(offsets), max(4, (needed // page_size + 1) * 8))
    collected: list[dict[str, Any]] = []
    seen: set[str] = set(cached_uris)

    for i, off in enumerate(offsets[:max_pages]):
        if len(collected) >= needed:
            break
        try:
            page = await client.music.get_library_tracks(
                limit=page_size, offset=off, order_by=order_by
            )
        except Exception:  # noqa: BLE001
            # One bad page must not abort a multi-hour scan; the caller sees a
            # short count and can re-run to fill the gap.
            _LOGGER.debug("Library page fetch failed at offset %s", off, exc_info=True)
            continue
        for track in page or []:
            t = _normalize_track(track)
            if t is None or t["uri"] in seen:
                continue
            seen.add(t["uri"])
            collected.append(t)
        if progress_cb:
            progress_cb("enumerate", len(collected), 0)
    return collected[:needed], total
