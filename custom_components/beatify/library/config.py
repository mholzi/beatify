"""Sanitising the library settings a client sends (#2930).

``parse_library_config`` used to live in ``server/game_views.py`` as a private
helper, and ``server/library_views.py`` reached across for it with an import
inside a function — one half of the import cycle #2930 is about. It belongs
here: it is pure, it knows nothing about HTTP, and what it describes is the
library's own vocabulary.

The year gates moved with it for a second reason. They existed **twice**, once
in each of those two files — ``game_views`` with the comment explaining what the
tiers mean, ``library_views`` as a bare dict. Two copies of the same mapping in
the two modules that could not import each other is the cycle's cost in
miniature; here there is one.
"""

from __future__ import annotations

from typing import Any

#: UI value -> minimum ``YearConfidence`` tier (see ``library.year_resolver``).
YEAR_GATES = {
    "strict": 4,  # EXTERNAL_PRIMARY: verified MusicBrainz years only (default)
    "balanced": 3,  # + EXTERNAL_SECONDARY: Deezer release years
    "tags_ok": 2,  # + TAG_STUDIO: studio-album tag years (least strict)
}

SIZE_MIN = 5
SIZE_MAX = 100
SIZE_DEFAULT = 30


def parse_library_config(
    library_config: dict[str, Any],
) -> tuple[int, int, int, int | None, list[str]]:
    """Sanitize the library settings from the request body. Pure.

    Returns ``(size, difficulty_slider, min_confidence, popularity_percent,
    genres)``. ``popularity_percent`` is 1..100 ("draw from the most-popular
    P%") or ``None``.

    Every field is clamped rather than rejected: the callers are HTTP endpoints
    and a host who sends a nonsense size should get a game, not a 400.
    """
    library_config = library_config or {}
    try:
        size = int(library_config.get("size", SIZE_DEFAULT))
    except (TypeError, ValueError):
        size = SIZE_DEFAULT
    size = max(SIZE_MIN, min(SIZE_MAX, size))

    try:
        slider = int(library_config.get("difficulty", 50))
    except (TypeError, ValueError):
        slider = 50
    slider = max(0, min(100, slider))

    gate = YEAR_GATES.get(
        str(library_config.get("year_gate", "strict")), YEAR_GATES["strict"]
    )

    pop_percent: int | None = None
    if library_config.get("popularity_percent") is not None:
        try:
            pop_percent = max(1, min(100, int(library_config["popularity_percent"])))
        except (TypeError, ValueError):
            pop_percent = None

    genres_raw = library_config.get("genres")
    genres: list[str] = []
    if isinstance(genres_raw, list):
        genres = [str(g).strip() for g in genres_raw if str(g).strip()][:20]

    return size, slider, gate, pop_percent, genres


#: Where a Crate Digger game draws its songs from (#2939).
SOURCE_LIBRARY = "library"
SOURCE_PLAYLIST = "playlist"
SOURCES = (SOURCE_LIBRARY, SOURCE_PLAYLIST)


def sanitize_ma_playlist(raw: Any) -> dict[str, str] | None:
    """Whitelist a stored/sent MA playlist reference. Pure; None if unusable."""
    if not isinstance(raw, dict):
        return None
    item_id = str(raw.get("item_id") or "").strip()[:100]
    provider = str(raw.get("provider") or "").strip()[:100]
    if not item_id or not provider:
        return None
    name = str(raw.get("name") or "").strip()[:200]
    return {"item_id": item_id, "provider": provider, "name": name}


def parse_library_source(
    library_config: dict[str, Any],
) -> tuple[str, dict[str, str] | None]:
    """Return ``(source, ma_playlist)`` from the library settings. Pure.

    Playlist mode needs a playlist; without one the game falls back to the
    whole library rather than refusing to start.
    """
    library_config = library_config or {}
    source = str(library_config.get("source") or SOURCE_LIBRARY)
    playlist = sanitize_ma_playlist(library_config.get("ma_playlist"))
    if source != SOURCE_PLAYLIST or playlist is None:
        return SOURCE_LIBRARY, None
    return SOURCE_PLAYLIST, playlist
