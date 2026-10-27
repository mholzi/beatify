"""Metadata difficulty prior for ramp-up ordering on a fresh install (#3305)."""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from custom_components.beatify.game.playlist import (
    SONG_ORDER_RAMPUP,
    PlaylistManager,
    metadata_difficulty_prior,
)
from tests.conftest import make_game_state

PLAYLISTS = Path(__file__).parents[2] / "custom_components/beatify/playlists"


class _EmptyStats:
    """Stats store with no play history: every song is unrated."""

    def get_song_difficulty(self, uri):
        return None


def _drain(manager):
    out = []
    while (song := manager.get_next_song()) is not None:
        out.append(song)
        manager.mark_played(song["_resolved_uri"])
    return out


@pytest.mark.parametrize(
    ("song", "expected"),
    [
        ({"chart_info": {"billboard_peak": 5}}, 1),
        ({"chart_info": {"uk_peak": 10}}, 1),
        ({"chart_info": {"german_peak": 3}}, 1),
        ({"certifications": ["Gold (US)", "Platinum (UK)"]}, 1),
        ({"chart_info": {"billboard_peak": 40}}, 2),
        ({"chart_info": {"eurovision_position": 4, "country": "X"}}, 2),
        ({"certifications": ["Gold (US)"]}, 2),
        ({"certifications": "Gold (US)"}, 2),
        ({"awards": ["Grammy"]}, 2),
        ({}, 3),
        ({"chart_info": {}, "certifications": [], "awards": []}, 3),
        ({"certifications": "", "awards": ""}, 3),
        # Malformed values are treated as absent, never raise.
        ({"chart_info": None, "certifications": None, "awards": None}, 3),
        ({"chart_info": "x", "certifications": 7, "awards": {"a": 1}}, 3),
        ({"chart_info": {"billboard_peak": None, "uk_peak": "1"}}, 3),
        ({"chart_info": {"billboard_peak": True}}, 3),
        ({"chart_info": {"billboard_peak": 0}}, 3),
        ({"certifications": [None, "", 5]}, 3),
    ],
)
def test_prior_tiers(song, expected):
    assert metadata_difficulty_prior(song) == expected


def _real_songs():
    songs = []
    for name in ("80er-hits.json", "90er-hits.json", "70s-hits.json"):
        data = json.loads((PLAYLISTS / name).read_text(encoding="utf-8"))
        songs.extend(dict(s, _playlist_source=name) for s in data["songs"])
    return songs


def test_empty_stats_real_playlist_gives_easy_to_hard_arc():
    random.seed(3305)
    songs = _real_songs()
    manager = PlaylistManager(
        songs,
        song_order=SONG_ORDER_RAMPUP,
        difficulty_lookup=lambda uri: None,
        use_metadata_prior=True,
    )
    assert manager._rampup_order is not None
    order = _drain(manager)
    levels = [metadata_difficulty_prior(s) for s in order]
    assert len(set(levels)) > 1, "fixture must span several tiers"
    # Non-decreasing except the single hardest song held back for the finale.
    assert levels[:-1] == sorted(levels[:-1])
    assert levels[-1] == max(levels)


def test_without_prior_flag_empty_stats_stays_random():
    manager = PlaylistManager(
        _real_songs(),
        song_order=SONG_ORDER_RAMPUP,
        difficulty_lookup=lambda uri: None,
    )
    assert manager._rampup_order is None


def test_play_stats_override_prior():
    random.seed(1)
    # Famous song (prior 1) that stats say is hard (4); obscure (prior 3) rated easy.
    songs = [
        {"title": "A", "artist": "a", "year": 1980, "uri": "spotify:track:a",
         "chart_info": {"billboard_peak": 1}},
        {"title": "B", "artist": "b", "year": 1981, "uri": "spotify:track:b"},
        {"title": "C", "artist": "c", "year": 1982, "uri": "spotify:track:c",
         "certifications": ["Gold (US)"]},
    ]  # fmt: skip
    rated = {"spotify:track:a": 4, "spotify:track:b": 1}
    manager = PlaylistManager(
        songs,
        song_order=SONG_ORDER_RAMPUP,
        difficulty_lookup=rated.get,
        use_metadata_prior=True,
    )
    order = [s["title"] for s in _drain(manager)]
    # b=1 (stats), c=2 (prior), a=4 (stats beats prior 1) -> finale.
    assert order == ["B", "C", "A"]


def test_create_game_uses_prior_with_empty_stats_store():
    random.seed(11)
    state = make_game_state()
    state.set_stats_service(_EmptyStats())
    state.create_game(
        playlists=["test.json"],
        songs=_real_songs(),
        media_player="media_player.test",
        base_url="http://localhost:8123",
        rampup_order_enabled=True,
    )
    manager = state._playlist_manager
    assert manager._rampup_order is not None
    levels = [metadata_difficulty_prior(s) for s in manager._rampup_order]
    assert levels[:-1] == sorted(levels[:-1])
    assert len(set(levels)) > 1
