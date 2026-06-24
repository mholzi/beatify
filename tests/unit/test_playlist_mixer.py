"""Tests for the Smart Playlist Mixer assembly/dedup logic (#1538).

``mix_playlist_songs`` is the pure core of the Smart Playlist Mixer: given the
discovered playlists, the host's tag selection and a target count, it assembles
a de-duplicated transient song set (by ``uri``) from every playlist matching all
selected tags. These tests cover tag matching (AND logic), dedup-by-uri across
playlists, the year + URI admission rule, the count cap and deterministic
shuffling.
"""

from __future__ import annotations

import random

from custom_components.beatify.game.playlist import mix_playlist_songs


def _song(uri: str, year: int = 1985, **extra) -> dict:
    """Build a minimal valid song (year + a usable URI)."""
    return {"uri": uri, "year": year, "title": uri, "artist": "x", **extra}


class TestMixPlaylistSongs:
    def test_empty_tags_matches_all_playlists(self):
        playlists = [
            {"tags": ["1980s"], "songs": [_song("spotify:track:a")]},
            {"tags": ["1990s"], "songs": [_song("spotify:track:b")]},
        ]
        result = mix_playlist_songs(playlists, [], 10)
        uris = {s["uri"] for s in result}
        assert uris == {"spotify:track:a", "spotify:track:b"}

    def test_and_logic_requires_all_tags(self):
        playlists = [
            {"tags": ["1980s", "pop"], "songs": [_song("spotify:track:a")]},
            {"tags": ["1980s"], "songs": [_song("spotify:track:b")]},
        ]
        # Only the playlist carrying BOTH tags should contribute.
        result = mix_playlist_songs(playlists, ["1980s", "pop"], 10)
        assert [s["uri"] for s in result] == ["spotify:track:a"]

    def test_dedup_by_uri_across_playlists(self):
        shared = "spotify:track:dup"
        playlists = [
            {"tags": ["1980s"], "songs": [_song(shared)]},
            {"tags": ["1980s"], "songs": [_song(shared)]},
        ]
        result = mix_playlist_songs(playlists, ["1980s"], 10)
        assert len(result) == 1

    def test_dedup_prefers_uri_then_provider_fields(self):
        # Same Spotify track via canonical `uri` in one playlist and
        # `uri_spotify` in another collapses to one entry.
        playlists = [
            {"tags": ["pop"], "songs": [{"uri": "spotify:track:x", "year": 1990}]},
            {
                "tags": ["pop"],
                "songs": [{"uri_spotify": "spotify:track:x", "year": 1990}],
            },
        ]
        result = mix_playlist_songs(playlists, ["pop"], 10)
        assert len(result) == 1

    def test_skips_songs_without_year_or_uri(self):
        playlists = [
            {
                "tags": ["pop"],
                "songs": [
                    _song("spotify:track:ok"),
                    {"year": 1980},  # no URI
                    {"uri": "spotify:track:noyear"},  # no year
                ],
            },
        ]
        result = mix_playlist_songs(playlists, ["pop"], 10)
        assert [s["uri"] for s in result] == ["spotify:track:ok"]

    def test_caps_at_target_count(self):
        songs = [_song(f"spotify:track:{i}") for i in range(50)]
        playlists = [{"tags": ["pop"], "songs": songs}]
        result = mix_playlist_songs(playlists, ["pop"], 10)
        assert len(result) == 10

    def test_zero_or_negative_count_returns_empty(self):
        playlists = [{"tags": ["pop"], "songs": [_song("spotify:track:a")]}]
        assert mix_playlist_songs(playlists, ["pop"], 0) == []
        assert mix_playlist_songs(playlists, ["pop"], -5) == []

    def test_deterministic_shuffle_with_seeded_rng(self):
        songs = [_song(f"spotify:track:{i}") for i in range(20)]
        playlists = [{"tags": ["pop"], "songs": songs}]
        a = mix_playlist_songs(playlists, ["pop"], 5, rng=random.Random(42))
        b = mix_playlist_songs(playlists, ["pop"], 5, rng=random.Random(42))
        assert [s["uri"] for s in a] == [s["uri"] for s in b]
        assert len(a) == 5

    def test_tolerates_missing_keys(self):
        # Malformed discovery entries (no tags / no songs) must not raise.
        playlists = [{}, {"tags": ["pop"]}, {"songs": [_song("spotify:track:a")]}]
        result = mix_playlist_songs(playlists, [], 10)
        assert [s["uri"] for s in result] == ["spotify:track:a"]

    def test_no_match_returns_empty(self):
        playlists = [{"tags": ["1980s"], "songs": [_song("spotify:track:a")]}]
        assert mix_playlist_songs(playlists, ["disco"], 10) == []
