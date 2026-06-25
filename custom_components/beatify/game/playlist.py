"""Playlist discovery and validation for Beatify."""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from custom_components.beatify.const import (
    PLAYLIST_DIR,
    PROVIDER_AMAZON_MUSIC,
    PROVIDER_APPLE_MUSIC,
    PROVIDER_DEFAULT,
    PROVIDER_DEEZER,
    PROVIDER_SPOTIFY,
    PROVIDER_TIDAL,
    PROVIDER_YOUTUBE_MUSIC,
    URI_PATTERN_APPLE_MUSIC,
    URI_PATTERN_DEEZER,
    URI_PATTERN_SPOTIFY,
    URI_PATTERN_TIDAL,
    URI_PATTERN_YOUTUBE_MUSIC,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

_URI_FIELDS = [
    ("uri", URI_PATTERN_SPOTIFY, "spotify:track:{22-char-id}"),
    ("uri_spotify", URI_PATTERN_SPOTIFY, "spotify:track:{22-char-id}"),
    ("uri_apple_music", URI_PATTERN_APPLE_MUSIC, "applemusic://track/id"),
    (
        "uri_youtube_music",
        URI_PATTERN_YOUTUBE_MUSIC,
        "https://music.youtube.com/watch?v=...",
    ),
    ("uri_tidal", URI_PATTERN_TIDAL, "tidal://track/{id}"),
    ("uri_deezer", URI_PATTERN_DEEZER, "deezer://track/{id}"),
]


class PlaylistManager:
    """Manages song selection and played tracking.

    When multiple playlists are selected, uses balanced selection (#525):
    picks a random playlist first (equal weight), then a random unplayed
    song from that playlist. This ensures equal representation regardless
    of playlist size. Cross-playlist duplicates are deduplicated by URI.
    """

    def __init__(
        self,
        songs: list[dict[str, Any]],
        provider: str = PROVIDER_DEFAULT,
        storefront: str | None = None,
    ) -> None:
        """Initialize with list of songs from loaded playlists.

        Args:
            songs: List of song dictionaries (may include _playlist_source tag)
            provider: Music provider to use
            storefront: For Apple Music, the user's regional storefront code
                (e.g. "us", "de"). Songs explicitly unavailable in that
                region (per ``uri_apple_music_by_region``) are filtered out
                up-front so they never appear in playback (#808 follow-up).

        """
        self._provider = provider
        self._storefront = storefront
        total_count = len(songs)
        filtered_songs, _ = filter_songs_for_provider(songs, provider, storefront)
        self._played_uris: set[str] = set()

        # Group songs into per-playlist buckets, deduplicating by URI.
        # Songs explicitly unavailable in the user's storefront (per
        # `uri_apple_music_by_region`) get filtered out here — they never
        # enter the playable pool, so the runtime never even tries to play
        # them.
        seen_uris: set[str] = set()
        buckets: dict[str, list[dict[str, Any]]] = {}
        regional_skipped = 0
        for song in filtered_songs:
            uri = get_song_uri(song, provider, storefront)
            if not uri:
                # Could be no URI for provider OR explicitly null in storefront.
                if (
                    provider == PROVIDER_APPLE_MUSIC
                    and storefront
                    and storefront in (song.get("uri_apple_music_by_region") or {})
                    and song["uri_apple_music_by_region"][storefront] is None
                ):
                    regional_skipped += 1
                continue
            if uri in seen_uris:
                continue
            seen_uris.add(uri)
            source = song.get("_playlist_source", "__default__")
            buckets.setdefault(source, []).append(song)

        self._buckets = buckets
        self._songs = [s for bucket in buckets.values() for s in bucket]
        self._multi_playlist = len(buckets) > 1

        deduped = sum(len(v) for v in buckets.values())
        _LOGGER.info(
            "PlaylistManager: %d/%d songs across %d playlist(s) for %s"
            + (f" [{storefront}]" if storefront else "")
            + (" (balanced mode)" if self._multi_playlist else ""),
            deduped,
            total_count,
            len(buckets),
            provider,
        )
        if regional_skipped:
            _LOGGER.info(
                "Filtered %d song(s) confirmed unavailable in storefront '%s' "
                "(#808: per-region Apple Music data)",
                regional_skipped,
                storefront,
            )

    def get_next_song(self) -> dict[str, Any] | None:
        """Get random unplayed song with balanced playlist selection.

        Returns:
            Song dict with _resolved_uri added, or None if all songs played

        """
        if not self._multi_playlist:
            return self._pick_from_pool(self._songs)

        # Balanced: pick a random non-exhausted playlist, then a song
        active_buckets = {
            k: [
                s
                for s in v
                if get_song_uri(s, self._provider, self._storefront)
                not in self._played_uris
            ]
            for k, v in self._buckets.items()
        }
        active_buckets = {k: v for k, v in active_buckets.items() if v}

        if not active_buckets:
            return None

        chosen_key = random.choice(list(active_buckets.keys()))  # noqa: S311
        song = random.choice(active_buckets[chosen_key])  # noqa: S311
        song_copy = song.copy()
        song_copy["_resolved_uri"] = get_song_uri(
            song, self._provider, self._storefront
        )
        return song_copy

    def _pick_from_pool(self, pool: list[dict[str, Any]]) -> dict[str, Any] | None:
        """Pick a random unplayed song from a flat pool."""
        available = [
            s
            for s in pool
            if get_song_uri(s, self._provider, self._storefront)
            not in self._played_uris
        ]
        if not available:
            return None
        song = random.choice(available)  # noqa: S311
        song_copy = song.copy()
        song_copy["_resolved_uri"] = get_song_uri(
            song, self._provider, self._storefront
        )
        return song_copy

    def mark_played(self, uri: str) -> None:
        """Mark a song as played.

        Args:
            uri: Song URI to mark as played

        """
        self._played_uris.add(uri)

    def reset(self) -> None:
        """Reset played tracking for new game."""
        self._played_uris.clear()

    def get_remaining_count(self) -> int:
        """Get count of unplayed songs.

        Returns:
            Number of songs not yet played (clamped to 0 for robustness, #707)

        """
        # #707: mark_played() accepts any URI (incl. unknown ones), so naive
        # subtraction can go negative. Clamp at 0.
        return max(0, len(self._songs) - len(self._played_uris))

    def has_playable_songs(self) -> bool:
        """True if this manager has any songs for its provider (#709)."""
        return len(self._songs) > 0

    def get_total_count(self) -> int:
        """Get total song count.

        Returns:
            Total number of songs in playlist

        """
        return len(self._songs)


# Validation constants
MIN_YEAR = 1900


def _max_year() -> int:
    """Dynamic upper bound — current year + 1 (#706).

    The previous hardcoded 2030 would silently reject newer songs.
    """
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).year + 1


def get_playlist_directory(hass: HomeAssistant) -> Path:
    """Get the playlist directory path."""
    return Path(hass.config.path(PLAYLIST_DIR))


async def async_ensure_playlist_directory(hass: HomeAssistant) -> Path:
    """Ensure playlist directory exists, create if missing.

    #717: `exists()` and `mkdir()` are blocking syscalls — run in executor.
    """
    playlist_dir = get_playlist_directory(hass)

    def _ensure() -> bool:
        """Return True if we created the directory."""
        if playlist_dir.exists():
            return False
        playlist_dir.mkdir(parents=True, exist_ok=True)
        return True

    created = await hass.async_add_executor_job(_ensure)
    if created:
        _LOGGER.info("Created playlist directory: %s", playlist_dir)

    # Copy bundled playlists if they don't exist in destination
    await _copy_bundled_playlists(playlist_dir)

    return playlist_dir


def _get_playlist_version(path: Path) -> str:
    """Get version from playlist file. Returns '0.0' if no version field."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("version", "0.0")
    except (OSError, ValueError):
        return "0.0"


def _compare_versions(v1: str, v2: str) -> int:
    """Compare version strings. Returns: -1 if v1<v2, 0 if equal, 1 if v1>v2."""

    def parse(v: str) -> tuple[int, ...]:
        return tuple(int(x) for x in v.split("."))

    try:
        p1, p2 = parse(v1), parse(v2)
        if p1 < p2:
            return -1
        if p1 > p2:
            return 1
        return 0
    except ValueError:
        return 0


async def _copy_bundled_playlists(dest_dir: Path) -> None:
    """Copy bundled playlists to destination, updating if bundled version is newer."""
    # Bundled playlists are in custom_components/beatify/playlists/
    bundled_dir = Path(__file__).parent.parent / "playlists"

    loop = asyncio.get_running_loop()

    # #1402 B3: `exists()` is a blocking syscall — run it (and the glob) in the
    # executor instead of on the event loop.
    if not await loop.run_in_executor(None, bundled_dir.exists):
        return

    def _copy_file(src: Path, dst: Path) -> None:
        """Copy file contents, creating parent dirs (runs in executor).

        #1402 B3: folds the previously-on-event-loop ``mkdir`` in here.
        """
        dst.parent.mkdir(parents=True, exist_ok=True)
        content = src.read_text(encoding="utf-8")
        dst.write_text(content, encoding="utf-8")

    def _get_versions(src: Path, dst: Path) -> tuple[str, str, bool]:
        """Get versions from both files + whether dst exists (runs in executor).

        #1402 B3: returns ``dst_exists`` so the caller reuses this single stat
        instead of re-running a blocking ``dst.exists()`` on the event loop.
        """
        bundled_ver = _get_playlist_version(src)
        dst_exists = dst.exists()
        existing_ver = _get_playlist_version(dst) if dst_exists else "0.0"
        return bundled_ver, existing_ver, dst_exists

    # Offload blocking glob to executor to avoid scandir in event loop (#516)
    playlist_files = await loop.run_in_executor(
        None, lambda: list(bundled_dir.glob("**/*.json"))
    )
    for playlist_file in playlist_files:
        # Preserve relative path (e.g. community/greatest-metal-songs.json)
        rel = playlist_file.relative_to(bundled_dir)
        dest_file = dest_dir / rel
        try:
            # Get versions (+ existence, reused below — _copy_file makes the dir)
            bundled_ver, existing_ver, dest_exists = await loop.run_in_executor(
                None, _get_versions, playlist_file, dest_file
            )

            if not dest_exists:
                # New playlist - copy it
                await loop.run_in_executor(None, _copy_file, playlist_file, dest_file)
                _LOGGER.info(
                    "Copied bundled playlist %s (v%s)", playlist_file.name, bundled_ver
                )
            elif _compare_versions(bundled_ver, existing_ver) > 0:
                # Bundled version is newer - update
                await loop.run_in_executor(None, _copy_file, playlist_file, dest_file)
                _LOGGER.info(
                    "Updated playlist %s: v%s -> v%s",
                    playlist_file.name,
                    existing_ver,
                    bundled_ver,
                )
            else:
                _LOGGER.debug(
                    "Playlist %s is up to date (v%s)", playlist_file.name, existing_ver
                )
        except OSError as err:
            _LOGGER.warning(
                "Failed to process playlist %s: %s", playlist_file.name, err
            )


def validate_playlist(
    data: dict[str, Any],
    *,
    rejected_songs: list[dict[str, Any]] | None = None,
) -> tuple[bool, list[str]]:
    """Validate playlist structure. Returns (is_valid, list_of_errors).

    Args:
        data: The parsed playlist document.
        rejected_songs: Optional out-param. When a list is passed, it is
            populated in place with one structured record per song that has
            at least one validation problem::

                {"index": 1, "title": "...", "artist": "...",
                 "reasons": ["year 1500 out of range", "no valid URI"]}

            This lets callers surface *which* tracks dropped and *why* to the
            host (#1576) instead of the positional ``errors`` strings alone.
            ``title``/``artist`` are ``None`` when missing. Passing this param
            never changes which songs/playlists are accepted or rejected — it
            only makes the existing rejections observable.

    """
    errors: list[str] = []
    max_year = _max_year()

    # Check required top-level fields
    if not isinstance(data.get("name"), str) or not data["name"].strip():
        errors.append("Missing or empty 'name' field")

    songs = data.get("songs")
    if not isinstance(songs, list):
        errors.append("Missing or invalid 'songs' array")
        return (False, errors)

    if len(songs) == 0:
        errors.append("Playlist has no songs")

    # Validate each song
    for i, song in enumerate(songs):
        if not isinstance(song, dict):
            errors.append(f"Song {i + 1}: not a valid object")
            if rejected_songs is not None:
                rejected_songs.append(
                    {
                        "index": i + 1,
                        "title": None,
                        "artist": None,
                        "reasons": ["not a valid object"],
                    }
                )
            continue

        # Per-song reasons collected without the "Song N:" prefix so callers
        # can render them per track. The prefixed variant is appended to the
        # flat ``errors`` list below to keep the legacy string output identical.
        song_reasons: list[str] = []

        # #697: title and artist are required for gameplay (challenge + reveal).
        title = song.get("title")
        if not isinstance(title, str) or not title.strip():
            song_reasons.append("missing or empty 'title'")
        artist = song.get("artist")
        if not isinstance(artist, str) or not artist.strip():
            song_reasons.append("missing or empty 'artist'")

        # Check year
        year = song.get("year")
        if not isinstance(year, int):
            song_reasons.append("missing or invalid 'year' (must be integer)")
        elif not (MIN_YEAR <= year <= max_year):
            song_reasons.append(f"year {year} out of range")

        # Check URIs - validate patterns and ensure at least one valid URI exists
        has_valid_uri = False
        for field, pattern, expected in _URI_FIELDS:
            value = song.get(field)
            if isinstance(value, str) and value.strip():
                if re.match(pattern, value):
                    has_valid_uri = True
                else:
                    song_reasons.append(f"'{field}' invalid (expected {expected})")

        # Error if no valid URI found
        if not has_valid_uri:
            song_reasons.append("no valid URI")

        # Story 20.2: Validate alt_artists if present (optional field)
        alt_artists = song.get("alt_artists")
        if alt_artists is not None:
            if not isinstance(alt_artists, list):
                song_reasons.append("'alt_artists' must be an array")
            else:
                for j, alt in enumerate(alt_artists):
                    if not isinstance(alt, str) or not alt.strip():
                        song_reasons.append(
                            f"'alt_artists[{j}]' must be non-empty string"
                        )
                # Log warning if fewer than 2 alternatives (weak challenge)
                valid_alts = [
                    a for a in alt_artists if isinstance(a, str) and a.strip()
                ]
                if len(valid_alts) < 2:
                    _LOGGER.debug(
                        "Song %d has only %d alt_artists (2 recommended)",
                        i + 1,
                        len(valid_alts),
                    )

        # Flush this song's reasons into the flat error list (prefixed, in the
        # same order as before) and, if requested, into the structured out-param.
        for reason in song_reasons:
            errors.append(f"Song {i + 1}: {reason}")
        if song_reasons and rejected_songs is not None:
            rejected_songs.append(
                {
                    "index": i + 1,
                    "title": title if isinstance(title, str) else None,
                    "artist": artist if isinstance(artist, str) else None,
                    "reasons": song_reasons,
                }
            )

    return (len(errors) == 0, errors)


def summarize_rejected_songs(
    rejected_songs: list[dict[str, Any]],
    *,
    limit: int = 5,
) -> str:
    """Render the structured rejections from :func:`validate_playlist`.

    Produces a short, host-readable one-liner such as::

        "Bohemian Rhapsody — Queen (year 1500 out of range); Song #4 (no
        valid URI); +3 more"

    Used for the INFO load summary (#1576) and the import error response so a
    host loading a flawed playlist sees *which* tracks dropped and *why*.
    """
    parts: list[str] = []
    for song in rejected_songs[:limit]:
        title = song.get("title")
        artist = song.get("artist")
        if title and artist:
            label = f"{title} — {artist}"
        elif title:
            label = str(title)
        else:
            label = f"Song #{song.get('index', '?')}"
        reasons = ", ".join(song.get("reasons", [])) or "invalid"
        parts.append(f"{label} ({reasons})")
    remaining = len(rejected_songs) - limit
    if remaining > 0:
        parts.append(f"+{remaining} more")
    return "; ".join(parts)


def get_song_uri(
    song: dict[str, Any],
    provider: str,
    storefront: str | None = None,
) -> str | None:
    """
    Get the URI for a song based on the provider.

    Args:
        song: Song dictionary with uri fields
        provider: Provider identifier (PROVIDER_SPOTIFY, PROVIDER_APPLE_MUSIC, or PROVIDER_YOUTUBE_MUSIC)
        storefront: For Apple Music, the user's regional storefront code
            (e.g. "us", "de", "gb"). Used to resolve per-region track IDs
            from ``uri_apple_music_by_region`` when present (#808 follow-up).
            None means "use the legacy single-URI field" (typically a US
            track ID). Other providers ignore this param.

    Returns:
        URI string for the provider/storefront, or None if not available.
        For Apple Music with a storefront set: returns None when the
        ``uri_apple_music_by_region`` map explicitly lists the region as
        unavailable (key present, value is None) — this lets the caller
        skip the song silently without ever calling MA.

    """
    if provider == PROVIDER_SPOTIFY:
        # For Spotify, prefer uri_spotify, fall back to legacy uri field
        return song.get("uri_spotify") or song.get("uri") or None
    if provider == PROVIDER_APPLE_MUSIC:
        # #808 follow-up: storefront-aware resolution. Beatify's playlists
        # historically stored a single Apple Music URI per song (typically
        # a US-storefront track ID); for users on other storefronts (DE,
        # GB, FR, ...) some subset isn't in their regional catalog. The
        # `uri_apple_music_by_region` map (populated by
        # `scripts/fetch_apple_music_regions.py`) gives per-region track
        # IDs (or explicit None for confirmed-unavailable).
        if storefront:
            regional = song.get("uri_apple_music_by_region") or {}
            if storefront in regional:
                # Explicit per-region answer (URI string OR None).
                return regional[storefront]
        # No storefront, or no per-region data: fall back to legacy field.
        return song.get("uri_apple_music") or None
    if provider == PROVIDER_YOUTUBE_MUSIC:
        # For YouTube Music, only use uri_youtube_music
        return song.get("uri_youtube_music") or None
    if provider == PROVIDER_TIDAL:
        # For Tidal, only use uri_tidal
        return song.get("uri_tidal") or None
    if provider == PROVIDER_DEEZER:
        # For Deezer, only use uri_deezer
        return song.get("uri_deezer") or None
    if provider == PROVIDER_AMAZON_MUSIC:
        # Amazon Music uses Alexa text search — there is no real per-track URI.
        # We still must return a *distinct* identity per song, because the
        # PlaylistManager uses this value both as the dedup key (__init__) and
        # as the played-tracking key (mark_played). Returning a single constant
        # for every song collapsed the whole playlist to one playable track and
        # ended every Alexa game after round 1 (#1361). Derive a stable key from
        # the song's artist+title so each track survives dedup and is tracked
        # independently. `_resolved_uri` is only ever consumed for Alexa
        # text-search (artist+title), never as a real media URI, so this
        # synthetic key is purely internal.
        artist = (song.get("artist") or "").strip().casefold()
        title = (song.get("title") or "").strip().casefold()
        if artist or title:
            return f"amazon:{artist}|{title}"
        # No metadata at all — fall back to the song's id so it stays distinct.
        song_id = song.get("id")
        if song_id is not None:
            return f"amazon:id:{song_id}"
        return None
    return None


def get_playback_uri(song: dict[str, Any]) -> str | None:
    """
    Get the URI a song is currently played back with.

    Prefers the provider-resolved URI (``_resolved_uri``, set once the song
    has been resolved against the active provider/storefront) and falls back
    to the song's generic ``uri`` field.

    Args:
        song: Song dictionary.

    Returns:
        The resolved playback URI, the generic URI, or None if neither set.

    """
    return song.get("_resolved_uri") or song.get("uri")


def filter_songs_for_provider(
    songs: list[dict[str, Any]],
    provider: str,
    storefront: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """
    Filter songs to only those available for the specified provider.

    Args:
        songs: List of song dictionaries
        provider: Provider identifier (PROVIDER_SPOTIFY or PROVIDER_APPLE_MUSIC)
        storefront: For Apple Music, the user's regional storefront code. Must
            be threaded through to ``get_song_uri`` so storefront-only tracks
            (present in ``uri_apple_music_by_region`` but absent from the legacy
            ``uri_apple_music`` field) are kept instead of dropped by a
            storefront-blind pre-filter (#1402 B3). Other providers ignore it.

    Returns:
        Tuple of (filtered_songs, skipped_count)

    """
    filtered: list[dict[str, Any]] = []
    skipped = 0

    for song in songs:
        uri = get_song_uri(song, provider, storefront)
        if uri:
            filtered.append(song)
        else:
            year = song.get("year", "unknown")
            _LOGGER.warning(
                "Skipping song (year %s) - no URI for provider '%s'", year, provider
            )
            skipped += 1

    return (filtered, skipped)


async def async_discover_playlists(hass: HomeAssistant) -> list[dict]:
    """Discover all playlist files in the playlist directory."""
    playlist_dir = get_playlist_directory(hass)
    playlists: list[dict] = []

    loop = asyncio.get_running_loop()

    # #1402 B3: `exists()` is a blocking syscall — run it in the executor.
    if not await loop.run_in_executor(None, playlist_dir.exists):
        _LOGGER.debug("Playlist directory does not exist: %s", playlist_dir)
        return playlists

    def _read_file(path: Path) -> str:
        """Read file contents (runs in executor)."""
        return path.read_text(encoding="utf-8")

    # Offload blocking glob to executor to avoid scandir in event loop (#516)
    json_files = await loop.run_in_executor(
        None, lambda: list(playlist_dir.glob("**/*.json"))
    )
    for json_file in json_files:
        try:
            rel = json_file.relative_to(playlist_dir)
            source = (
                "community"
                if rel.parts and rel.parts[0] in ("community", "user")
                else "bundled"
            )
            content = await loop.run_in_executor(None, _read_file, json_file)
            data = json.loads(content)
            rejected_songs: list[dict[str, Any]] = []
            is_valid, errors = validate_playlist(data, rejected_songs=rejected_songs)

            # Count songs per provider (Story 17.1), validating URI patterns (#708).
            songs = data.get("songs", [])

            def _count(field: str, pattern: str) -> int:
                n = 0
                for s in songs:
                    v = s.get(field)
                    if isinstance(v, str) and v and re.match(pattern, v):
                        n += 1
                return n

            spotify_count = sum(
                1
                for s in songs
                if (
                    (
                        isinstance(s.get("uri_spotify"), str)
                        and re.match(URI_PATTERN_SPOTIFY, s["uri_spotify"])
                    )
                    or (
                        isinstance(s.get("uri"), str)
                        and re.match(URI_PATTERN_SPOTIFY, s["uri"])
                    )
                )
            )
            apple_music_count = _count("uri_apple_music", URI_PATTERN_APPLE_MUSIC)
            youtube_music_count = _count("uri_youtube_music", URI_PATTERN_YOUTUBE_MUSIC)
            tidal_count = _count("uri_tidal", URI_PATTERN_TIDAL)
            deezer_count = _count("uri_deezer", URI_PATTERN_DEEZER)
            # Amazon Music uses Alexa text search — every song in the playlist is
            # playable, so the count always equals the total song count.
            amazon_music_count = len(songs)

            # #716: skip playlists with no songs entirely — they only confuse the UI.
            if not is_valid and len(songs) == 0:
                _LOGGER.debug(
                    "Skipping empty playlist from discovery: %s", json_file.name
                )
                continue

            playlists.append(
                {
                    "path": str(json_file),
                    "filename": json_file.name,
                    "name": data.get("name", json_file.stem),
                    "source": source,
                    "author": data.get("author"),
                    "description": data.get("description"),
                    "language": data.get("language"),
                    "added_date": data.get("added_date"),
                    "version": data.get("version"),
                    "tags": data.get("tags", []),  # Issue #70: Tag-based filtering
                    "song_count": len(songs),
                    "spotify_count": spotify_count,
                    "apple_music_count": apple_music_count,
                    "youtube_music_count": youtube_music_count,
                    "tidal_count": tidal_count,
                    "deezer_count": deezer_count,
                    "amazon_music_count": amazon_music_count,
                    "is_valid": is_valid,
                    "errors": errors,
                    # #1576: structured per-song rejections so the playlist
                    # browser can show *which* tracks dropped and why, not just
                    # the positional "Song N: ..." strings.
                    "rejected_songs": rejected_songs,
                }
            )
        except json.JSONDecodeError as e:
            try:
                rel = json_file.relative_to(playlist_dir)
                source = (
                    "community"
                    if rel.parts and rel.parts[0] in ("community", "user")
                    else "bundled"
                )
            except ValueError:
                source = "bundled"
            playlists.append(
                {
                    "path": str(json_file),
                    "filename": json_file.name,
                    "name": json_file.stem,
                    "source": source,
                    "author": None,
                    "description": None,
                    "language": None,
                    "added_date": None,
                    "version": None,
                    "tags": [],  # Issue #70
                    "song_count": 0,
                    "spotify_count": 0,
                    "apple_music_count": 0,
                    "youtube_music_count": 0,
                    "tidal_count": 0,
                    "deezer_count": 0,
                    "amazon_music_count": 0,
                    "is_valid": False,
                    "errors": [f"Invalid JSON: {e}"],
                    "rejected_songs": [],
                }
            )

    _LOGGER.debug("Found %d playlists", len(playlists))
    return playlists


async def async_load_and_validate_playlist(
    path: str | Path,
) -> tuple[dict | None, list[str]]:
    """Load and validate a playlist file."""
    path = Path(path)

    loop = asyncio.get_running_loop()

    # #1402 B3: `exists()` is a blocking syscall — run it in the executor.
    if not await loop.run_in_executor(None, path.exists):
        return (None, [f"File not found: {path}"])

    def _read_file(p: Path) -> str:
        """Read file contents (runs in executor)."""
        return p.read_text(encoding="utf-8")

    try:
        content = await loop.run_in_executor(None, _read_file, path)
        data = json.loads(content)
    except json.JSONDecodeError as e:
        return (None, [f"Invalid JSON: {e}"])

    rejected_songs: list[dict[str, Any]] = []
    is_valid, errors = validate_playlist(data, rejected_songs=rejected_songs)

    if is_valid:
        return (data, [])

    # #1576: a host loading a flawed playlist used to get zero feedback on
    # which tracks dropped (per-song problems were DEBUG-only). Log a concise
    # INFO summary naming the offending songs + reasons so it is visible in
    # the HA log without flipping the integration to DEBUG.
    if rejected_songs:
        _LOGGER.info(
            "Playlist %s: %d song(s) failed validation: %s",
            path.name,
            len(rejected_songs),
            summarize_rejected_songs(rejected_songs),
        )
    return (None, errors)
