"""A Music Assistant playlist as the song source for a Crate Digger game (#2939).

The host curates a playlist in Music Assistant; Beatify plays only songs from
it. Nothing new is scanned here: the playlist is a *filter* over the pool the
library scan already built, handed to the generator as ``only_uris``.

The part that must not be skipped is the explanation. A host who hand-picks
45 songs and gets a 37-song game has to see why, so every playlist track ends
up in exactly one bucket:

  usable          -- in the pool with a year that clears the current gate
  no_year         -- scanned, but its year is below the year-accuracy gate
  not_scanned     -- in the MA library, but the scan has not reached it yet
  not_in_library  -- MA says the track is not in the library at all (a
                     streaming or radio item added to the playlist)
  duplicate       -- a second version of a song already counted (the
                     generator dedupes by artist + title)

Matching, in order of trust:
  1. the track's library URI (MA built-in playlists carry it directly; for
     provider playlists ``ma_client`` looks up the library twin), against the
     pool's ``uri_ma_library``;
  2. normalized artist + title (the ``_norm_key`` the generator dedupes with
     and ``matcher.py`` resolves AI picks with), trying every credited artist
     so a compilation's "Various Artists" credit does not hide the real one.

Pure module: no Home Assistant, no network. Unit-tested.
"""

from __future__ import annotations

from typing import Any

from .config import YEAR_GATES
from .generator import _norm_key, entry_key

REASON_NO_YEAR = "no_year"
REASON_NOT_SCANNED = "not_scanned"
REASON_NOT_IN_LIBRARY = "not_in_library"
REASON_DUPLICATE = "duplicate"
REASONS = (REASON_NO_YEAR, REASON_NOT_SCANNED, REASON_NOT_IN_LIBRARY, REASON_DUPLICATE)


def _is_usable(entry: dict[str, Any], min_confidence: int) -> bool:
    return (
        entry.get("year") is not None
        and int(entry.get("year_confidence", 0)) >= min_confidence
        and bool(entry.get("uri_ma_library"))
    )


def _better(a: dict[str, Any] | None, b: dict[str, Any]) -> bool:
    """True if pool entry ``b`` should replace ``a`` in a name index."""
    if a is None:
        return True
    return int(b.get("year_confidence", 0)) > int(a.get("year_confidence", 0))


def build_playlist_indexes(
    pool_songs: list[dict[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Index the WHOLE pool (not just usable songs) by URI and by name key.

    Unlike ``matcher.build_pool_index`` this keeps songs below the year gate:
    telling "scanned, no reliable year" apart from "not scanned" needs them.
    """
    by_uri: dict[str, dict[str, Any]] = {}
    by_key: dict[str, dict[str, Any]] = {}
    for s in pool_songs:
        uri = s.get("uri_ma_library")
        if uri:
            by_uri[str(uri)] = s
        key = entry_key(s)
        if _better(by_key.get(key), s):
            by_key[key] = s
    return by_uri, by_key


def _match(
    track: dict[str, Any],
    by_uri: dict[str, dict[str, Any]],
    by_key: dict[str, dict[str, Any]],
) -> dict[str, Any] | None:
    lib_uri = track.get("library_uri")
    if lib_uri and lib_uri in by_uri:
        return by_uri[lib_uri]
    uri = track.get("uri")
    if uri and uri in by_uri:
        return by_uri[uri]
    title = str(track.get("title") or "").strip()
    if not title:
        return None
    artists = list(track.get("artists") or [])
    if track.get("artist") and track["artist"] not in artists:
        artists.insert(0, track["artist"])
    for artist in artists:
        hit = by_key.get(_norm_key(str(artist), title))
        if hit is not None:
            return hit
    return None


def _row(track: dict[str, Any], entry: dict[str, Any] | None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "title": (entry or {}).get("title") or track.get("title") or "",
        "artist": (entry or {}).get("artist") or track.get("artist") or "",
    }
    if entry is not None and entry.get("year") is not None:
        row["year"] = entry.get("year")
    return row


def classify_playlist_tracks(
    tracks: list[dict[str, Any]],
    pool_songs: list[dict[str, Any]],
    *,
    min_confidence: int = YEAR_GATES["strict"],
) -> dict[str, Any]:
    """Sort every playlist track into usable / a drop reason. Pure.

    Args:
        tracks: dicts from ``ma_client.async_fetch_playlist_tracks`` --
            title, artist, artists, uri, library_uri, in_library.
        pool_songs: the pool's ``songs`` list.
        min_confidence: the year gate the game will use.

    Returns:
        ``total``           -- tracks in the playlist
        ``usable``          -- songs the game can draw from
        ``usable_uris``     -- their ``uri_ma_library`` (the ``only_uris`` set)
        ``dropped``         -- {reason: [{title, artist, year?}, ...]}, every
                               reason present, possibly empty
        ``usable_by_gate``  -- {gate name: usable count} so the UI can offer
                               "relax year accuracy -> N usable" honestly
    """
    by_uri, by_key = build_playlist_indexes(pool_songs)
    dropped: dict[str, list[dict[str, Any]]] = {r: [] for r in REASONS}
    usable_uris: list[str] = []
    seen_keys: set[str] = set()
    matched: list[dict[str, Any]] = []

    for track in tracks:
        entry = _match(track, by_uri, by_key)
        if entry is None:
            if track.get("in_library") is False:
                dropped[REASON_NOT_IN_LIBRARY].append(_row(track, None))
            else:
                dropped[REASON_NOT_SCANNED].append(_row(track, None))
            continue
        matched.append(entry)
        if not _is_usable(entry, min_confidence):
            dropped[REASON_NO_YEAR].append(_row(track, entry))
            continue
        key = entry_key(entry)
        if key in seen_keys:
            dropped[REASON_DUPLICATE].append(_row(track, entry))
            continue
        seen_keys.add(key)
        usable_uris.append(str(entry["uri_ma_library"]))

    usable_by_gate: dict[str, int] = {}
    for gate_name, gate_conf in YEAR_GATES.items():
        keys = {entry_key(e) for e in matched if _is_usable(e, gate_conf)}
        usable_by_gate[gate_name] = len(keys)

    return {
        "total": len(tracks),
        "usable": len(usable_uris),
        "usable_uris": usable_uris,
        "dropped": dropped,
        "usable_by_gate": usable_by_gate,
    }


async def async_check_ma_playlist(
    hass: Any,
    *,
    item_id: str,
    provider: str,
    min_confidence: int,
    pool: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Fetch a MA playlist and classify it against the pool.

    Returns None when no pool is built. Raises when Music Assistant is not
    available or the playlist cannot be read -- callers turn that into an
    error the host sees.
    """
    from .ma_client import async_fetch_playlist_tracks, find_ma_config_entry_ids
    from .pool import async_load_pool_cached

    if pool is None:
        pool = await async_load_pool_cached(hass)
    if not pool or not pool.get("songs"):
        return None
    entry_id = pool.get("_config_entry_id")
    loaded = find_ma_config_entry_ids(hass)
    if not entry_id or entry_id not in loaded:
        if not loaded:
            raise RuntimeError("Music Assistant is not loaded")
        entry_id = loaded[0]
    tracks = await async_fetch_playlist_tracks(hass, entry_id, item_id, provider)
    return await hass.async_add_executor_job(
        lambda: classify_playlist_tracks(
            tracks, pool["songs"], min_confidence=min_confidence
        )
    )
