"""#3106 -- the My Music song count follows the game mode.

Since #3103 a Title & Artist game draws with a lowered year gate. The live
counter in the settings panel has to count with the same gate, otherwise it
shows 0 for a library the game plays fine.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.beatify.library.year_resolver import YearConfidence
from custom_components.beatify.server import library_views


def _song(i, *, year, conf):
    return {
        "title": f"T{i}",
        "artist": f"A{i}",
        "uri_ma_library": f"library://track/{i}",
        "genres": ["Rock"],
        "year": year,
        "year_confidence": int(conf),
        "popularity_percentile": 0.9,
        "global_score": 90.0,
    }


# Tag years only, none verified, plus one song with no year at all.
UNVERIFIED = [
    _song(i, year=1980 + i, conf=YearConfidence.TAG_STUDIO) for i in range(1, 13)
] + [_song(99, year=None, conf=YearConfidence.NONE)]


async def _eligible(query):
    request = MagicMock()
    request.query = query
    view = library_views.LibraryPoolPreviewView(MagicMock())
    view.json = lambda data: data  # the stubbed HomeAssistantView has no json()
    with (
        patch.object(library_views, "is_authorized_http", return_value=True),
        patch(
            "custom_components.beatify.library.pool.async_load_pool",
            AsyncMock(return_value={"songs": UNVERIFIED}),
        ),
    ):
        resp = await view.get(request)
    return resp["eligible"]


async def test_year_mode_counts_only_verified_years():
    assert await _eligible({"gate": "strict"}) == 0


async def test_title_artist_mode_counts_every_song_with_a_year():
    assert await _eligible({"gate": "strict", "ta": "1"}) == 12


async def test_title_artist_flag_never_raises_the_gate():
    relaxed = await _eligible({"gate": "tags_ok"})
    assert await _eligible({"gate": "tags_ok", "ta": "1"}) == relaxed
