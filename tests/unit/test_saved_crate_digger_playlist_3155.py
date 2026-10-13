"""A saved Crate Digger playlist must survive the create-game loader (#3155).

``_to_song_entry`` writes only ``uri_ma_library``; the loader gate used to
ignore that field, so every song was dropped (``NO_VALID_SONGS``).
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from custom_components.beatify.game import playlist as pl
from custom_components.beatify.game.playlist import get_song_uri
from custom_components.beatify.library.generator import _to_song_entry


def _hass(pdir):
    hass = MagicMock()
    hass.config.path = MagicMock(return_value=str(pdir))
    hass.data = {}
    return hass


async def test_saved_library_playlist_loads_and_is_playable(tmp_path):
    pdir = tmp_path / "beatify" / "playlists"
    pdir.mkdir(parents=True)
    songs = [
        _to_song_entry(
            {
                "year": 1985,
                "title": f"T{i}",
                "artist": f"A{i}",
                "uri_ma_library": f"library://track/{i}",
            }
        )
        for i in range(3)
    ]
    (pdir / "mix.json").write_text(
        json.dumps(
            {
                "name": "Crate mix",
                "version": "1.0",
                "tags": ["library", "generated"],
                "songs": songs,
            }
        ),
        encoding="utf-8",
    )

    loaded, warnings = await pl.async_load_songs_from_paths(_hass(pdir), ["mix.json"])

    assert len(loaded) == 3
    assert warnings == []
    assert get_song_uri(loaded[0], "ma_library") == "library://track/0"
