"""#3103 -- Title & Artist + My Music must not demand a verified year.

Title & Artist asks for the title and the artist, never the year, so the
year-accuracy gate has nothing to protect there. Year mode keeps the gate and
its error unchanged.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.beatify.library.year_resolver import YearConfidence
from custom_components.beatify.server import game_views


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


# A library the scan found tag years for, but MusicBrainz verified none of.
UNVERIFIED = [
    _song(i, year=1980 + i, conf=YearConfidence.TAG_STUDIO) for i in range(1, 13)
] + [_song(99, year=None, conf=YearConfidence.NONE)]


async def _run(title_artist_mode, stored=None):
    hass = MagicMock()
    hass.data = {}

    async def _inline(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    hass.async_add_executor_job = _inline
    with (
        patch.object(
            game_views,
            "async_load_library_settings",
            AsyncMock(return_value=stored or {"size": 5}),
        ),
        patch(
            "custom_components.beatify.library.pool.async_load_pool_cached",
            AsyncMock(return_value={"songs": UNVERIFIED}),
        ),
        patch.object(game_views, "_recent_played_uris", return_value=None),
    ):
        return await game_views._generate_library_songs(
            hass, {}, title_artist_mode=title_artist_mode
        )


async def test_title_artist_mode_starts_without_verified_years():
    songs, err = await _run(True)
    assert err is None
    assert len(songs) == 5
    assert all(isinstance(s["year"], int) for s in songs)


async def test_year_mode_is_still_blocked_with_the_same_error():
    songs, err = await _run(False)
    assert songs == []
    body = json.loads(err.body)
    assert body["code"] == "LIBRARY_POOL_EMPTY"
    assert body["message_key"] == "LIBRARY_POOL_EMPTY"


async def test_title_artist_mode_still_skips_songs_with_no_year_at_all():
    songs, err = await _run(True, stored={"size": 100})
    assert err is None
    assert all(s["uri_ma_library"] != "library://track/99" for s in songs)
