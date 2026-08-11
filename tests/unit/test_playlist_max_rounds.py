"""Tests for the selectable round count (#1475).

A game used to play every song of every selected playlist, so a 100-song
playlist meant a two-hour evening. ``max_rounds`` caps that. The value 0 means
"play everything" and is the pre-#1475 behaviour, so most of these tests exist
to pin down that 0 keeps meaning exactly that.

Two decisions are load-bearing and each has a test that fails if someone
reorders the code:

* the cap is applied **before** the ramp-up arc is built, so a shortened game
  still gets a full easy→hard curve rather than the front slice of a long one;
* the cap **samples** rather than slices, so picking three playlists and 20
  rounds does not hand out 20 songs from the first playlist alone.
"""

from __future__ import annotations

import random

from custom_components.beatify.game.playlist import (
    MIN_ROUNDS,
    SONG_ORDER_RAMPUP,
    PlaylistManager,
)


def _song(idx: int, uri: str, *, artist: str | None = None) -> dict:
    return {
        "title": f"Song {idx}",
        "artist": artist or f"Artist {idx}",
        "year": 1980 + (idx % 40),
        "uri": uri,
        "uri_spotify": uri,
    }


def _songs(count: int, *, prefix: str = "u") -> list[dict]:
    return [_song(i, f"{prefix}{i}") for i in range(count)]


def _drain(manager: PlaylistManager) -> list[dict]:
    order: list[dict] = []
    while True:
        song = manager.get_next_song()
        if song is None:
            break
        order.append(song)
        manager.mark_played(song["_resolved_uri"])
    return order


class TestMaxRoundsCap:
    def test_default_plays_every_song(self):
        """No cap given — unchanged behaviour, the whole playlist is played."""
        manager = PlaylistManager(_songs(50))
        assert len(_drain(manager)) == 50

    def test_zero_plays_every_song(self):
        """0 is the wire value for "all songs", not a cap of zero rounds."""
        manager = PlaylistManager(_songs(50), max_rounds=0)
        assert len(_drain(manager)) == 50

    def test_cap_shortens_the_game(self):
        random.seed(1475)
        manager = PlaylistManager(_songs(100), max_rounds=20)
        assert len(_drain(manager)) == 20

    def test_cap_below_the_floor_is_lifted_to_min_rounds(self):
        """Below ten rounds one lucky guess decides the game (Markus' call)."""
        random.seed(1475)
        manager = PlaylistManager(_songs(100), max_rounds=3)
        assert len(_drain(manager)) == MIN_ROUNDS

    def test_cap_larger_than_the_playlist_plays_everything(self):
        """No padding, no error — a 30-song playlist gives 30 rounds."""
        manager = PlaylistManager(_songs(30), max_rounds=200)
        assert len(_drain(manager)) == 30

    def test_short_playlist_is_not_padded_to_the_floor(self):
        """Six songs stay six rounds; MIN_ROUNDS is a floor on the *cap*."""
        manager = PlaylistManager(_songs(6), max_rounds=20)
        assert len(_drain(manager)) == 6

    def test_capped_songs_are_still_unique(self):
        random.seed(99)
        manager = PlaylistManager(_songs(100), max_rounds=25)
        uris = [s["_resolved_uri"] for s in _drain(manager)]
        assert len(set(uris)) == len(uris) == 25


class TestCapInteractsWithOrdering:
    def test_rampup_arc_is_built_over_the_capped_set(self):
        """The cap runs before the arc, so a short game keeps a full curve.

        If the truncation happened *after* ``_build_rampup_order()``, a 10-round
        game would be the ten easiest songs of the playlist and never reach the
        hard end. Pinning the arc's span is what catches that reordering.
        """
        random.seed(1475)
        difficulties = {f"u{i}": (i % 4) + 1 for i in range(100)}
        songs = _songs(100)

        manager = PlaylistManager(
            songs,
            song_order=SONG_ORDER_RAMPUP,
            difficulty_lookup=lambda uri: difficulties.get(uri),
            max_rounds=12,
        )
        order = _drain(manager)
        assert len(order) == 12

        levels = [difficulties[s["_resolved_uri"]] for s in order]
        assert levels == sorted(levels), f"arc not non-decreasing: {levels}"
        # The point of the check: a capped game still reaches the hard end
        # instead of being the front slice of an uncapped arc.
        assert max(levels) == 4

    def test_cap_samples_across_playlists_instead_of_slicing(self):
        """A multi-playlist selection stays mixed after the cap.

        Slicing the flattened bucket list would serve playlist A's songs only,
        because the buckets are concatenated in selection order. Sampling keeps
        every playlist represented — verified statistically over many seeds so
        the test does not depend on one lucky draw.
        """
        from_a = [_song(i, f"a{i}") for i in range(50)]
        from_b = [_song(i, f"b{i}") for i in range(50)]

        b_seen = 0
        runs = 30
        for seed in range(runs):
            random.seed(seed)
            manager = PlaylistManager(from_a + from_b, max_rounds=20)
            uris = [s["_resolved_uri"] for s in _drain(manager)]
            if any(u.startswith("b") for u in uris):
                b_seen += 1

        # Pure slicing would give 0. Sampling 20 of 100 makes an all-A draw
        # astronomically unlikely, so every run should contain playlist B.
        assert b_seen == runs, f"playlist B missing in {runs - b_seen}/{runs} runs"
