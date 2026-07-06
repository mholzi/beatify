"""Tests for ramp-up (difficulty-arc) song ordering (#1726).

Covers the opt-in ``song_order="rampup"`` mode on :class:`PlaylistManager`
(easy early / hard late / hardest-known reserved for the finale / unknown
treated as medium / graceful fallback to uniform random) plus the
``rampup_order_enabled`` setting plumbing through ``GameState.create_game``.
"""

from __future__ import annotations

import random

from custom_components.beatify.game.playlist import (
    SONG_ORDER_RAMPUP,
    SONG_ORDER_RANDOM,
    PlaylistManager,
)
from tests.conftest import make_game_state

# Unknown difficulty maps to medium == 2 on the 1..4 star scale (#1726).
_MEDIUM = 2


def _song(idx: int, uri: str) -> dict:
    """A minimal Spotify song whose resolved URI is ``uri``."""
    return {
        "title": f"Song {idx}",
        "artist": f"Artist {idx}",
        "year": 1980 + idx,
        "uri": uri,
        "uri_spotify": uri,
    }


def _lookup_from(difficulties: dict[str, int | None]):
    """Build a difficulty-lookup callable from a ``{uri: stars|None}`` map."""

    def _lookup(uri: str) -> int | None:
        return difficulties.get(uri)

    return _lookup


def _drain(manager: PlaylistManager) -> list[dict]:
    """Play the whole game out, returning songs in the order served."""
    order: list[dict] = []
    while True:
        song = manager.get_next_song()
        if song is None:
            break
        order.append(song)
        manager.mark_played(song["_resolved_uri"])
    return order


def _effective(uri: str, difficulties: dict[str, int | None]) -> int:
    """Effective difficulty: known stars, or medium(2) when unknown."""
    stars = difficulties.get(uri)
    return stars if stars is not None else _MEDIUM


class TestRampUpOrdering:
    def test_easy_songs_come_first_hard_songs_last(self):
        """The arc is monotonically non-decreasing in difficulty."""
        random.seed(1726)
        difficulties = {
            f"u{i}": stars for i, stars in enumerate([4, 1, 3, 2, 1, 4, 3, 2])
        }
        songs = [_song(i, uri) for i, uri in enumerate(difficulties)]

        manager = PlaylistManager(
            songs,
            song_order=SONG_ORDER_RAMPUP,
            difficulty_lookup=_lookup_from(difficulties),
        )
        order = _drain(manager)

        levels = [_effective(s["_resolved_uri"], difficulties) for s in order]
        assert levels == sorted(levels), f"arc not non-decreasing: {levels}"
        # Final third is at least as hard, on average, as the first third.
        third = max(1, len(levels) // 3)
        assert sum(levels[-third:]) / third >= sum(levels[:third]) / third

    def test_hardest_known_song_is_the_finale(self):
        """The single hardest KNOWN song is served last (the finale)."""
        random.seed(7)
        difficulties = {"a": 1, "b": 4, "c": 2, "d": 3, "e": 1}
        songs = [_song(i, uri) for i, uri in enumerate(difficulties)]

        manager = PlaylistManager(
            songs,
            song_order=SONG_ORDER_RAMPUP,
            difficulty_lookup=_lookup_from(difficulties),
        )
        order = _drain(manager)

        assert order[-1]["_resolved_uri"] == "b"  # the only 4-star

    def test_hardest_finale_beats_unknown_songs(self):
        """Unknowns (medium=2) never displace the hardest KNOWN finale."""
        random.seed(99)
        # Only one song has a known (hard) rating; the rest are unknown → medium.
        difficulties: dict[str, int | None] = {
            "known_hard": 4,
            "x1": None,
            "x2": None,
            "x3": None,
        }
        songs = [_song(i, uri) for i, uri in enumerate(difficulties)]

        manager = PlaylistManager(
            songs,
            song_order=SONG_ORDER_RAMPUP,
            difficulty_lookup=_lookup_from(difficulties),
        )
        order = _drain(manager)

        assert order[-1]["_resolved_uri"] == "known_hard"
        # Unknown songs are ordered as medium (2), before the hard finale.
        assert order[0]["_resolved_uri"].startswith("x")

    def test_unknown_songs_treated_as_medium(self):
        """Unknown songs sit between easy(1) and hard(3) — i.e. medium(2)."""
        random.seed(3)
        difficulties: dict[str, int | None] = {
            "easy": 1,
            "unknown": None,
            "hard": 3,
        }
        songs = [_song(i, uri) for i, uri in enumerate(difficulties)]

        manager = PlaylistManager(
            songs,
            song_order=SONG_ORDER_RAMPUP,
            difficulty_lookup=_lookup_from(difficulties),
        )
        order = [s["_resolved_uri"] for s in _drain(manager)]

        # easy → unknown(medium) → hard
        assert order == ["easy", "unknown", "hard"]

    def test_all_songs_served_exactly_once(self):
        """No song is dropped or duplicated by the arc."""
        random.seed(11)
        difficulties = {f"u{i}": (i % 4) + 1 for i in range(12)}
        songs = [_song(i, uri) for i, uri in enumerate(difficulties)]

        manager = PlaylistManager(
            songs,
            song_order=SONG_ORDER_RAMPUP,
            difficulty_lookup=_lookup_from(difficulties),
        )
        served = [s["_resolved_uri"] for s in _drain(manager)]

        assert sorted(served) == sorted(difficulties)
        assert len(served) == len(set(served))

    def test_skipped_song_advances_the_arc(self):
        """A song marked played out-of-band is skipped, arc continues in order."""
        random.seed(5)
        difficulties = {"a": 1, "b": 2, "c": 3, "d": 4}
        songs = [_song(i, uri) for i, uri in enumerate(difficulties)]

        manager = PlaylistManager(
            songs,
            song_order=SONG_ORDER_RAMPUP,
            difficulty_lookup=_lookup_from(difficulties),
        )
        # Simulate the easiest song being unplayable (skipped before it is served).
        manager.mark_played("a")
        order = [s["_resolved_uri"] for s in _drain(manager)]

        assert order == ["b", "c", "d"]
        assert "a" not in order


class TestRampUpFallbacks:
    def test_default_mode_is_uniform_random(self):
        """Without opting in, no arc is built — the random path is untouched."""
        difficulties = {"a": 1, "b": 4}
        songs = [_song(i, uri) for i, uri in enumerate(difficulties)]

        manager = PlaylistManager(songs)  # default song_order="random"

        assert manager._song_order == SONG_ORDER_RANDOM
        assert manager._rampup_order is None
        # Still serves every song.
        assert len(_drain(manager)) == 2

    def test_rampup_without_lookup_falls_back(self):
        """Ramp-up requested but no lookup supplied → no arc (random)."""
        songs = [_song(i, f"u{i}") for i in range(3)]

        manager = PlaylistManager(songs, song_order=SONG_ORDER_RAMPUP)

        assert manager._rampup_order is None
        assert len(_drain(manager)) == 3

    def test_zero_known_difficulty_degrades_to_random(self):
        """All-unknown difficulty → arc build returns None → uniform random."""
        difficulties: dict[str, int | None] = {"a": None, "b": None, "c": None}
        songs = [_song(i, uri) for i, uri in enumerate(difficulties)]

        manager = PlaylistManager(
            songs,
            song_order=SONG_ORDER_RAMPUP,
            difficulty_lookup=_lookup_from(difficulties),
        )

        assert manager._rampup_order is None  # degraded
        assert len(_drain(manager)) == 3


class _FakeStats:
    """Minimal StatsService stand-in exposing get_song_difficulty (#1726)."""

    def __init__(self, difficulties: dict[str, int | None]) -> None:
        self._difficulties = difficulties

    def get_song_difficulty(self, uri: str) -> dict | None:
        stars = self._difficulties.get(uri)
        return {"stars": stars} if stars is not None else None


class TestCreateGamePlumbing:
    def _songs(self, difficulties: dict[str, int | None]) -> list[dict]:
        return [_song(i, uri) for i, uri in enumerate(difficulties)]

    def test_flag_defaults_off_and_no_arc(self):
        """Default create_game keeps uniform random (no arc)."""
        state = make_game_state()
        difficulties = {"a": 1, "b": 4}
        state.set_stats_service(_FakeStats(difficulties))

        state.create_game(
            playlists=["test.json"],
            songs=self._songs(difficulties),
            media_player="media_player.test",
            base_url="http://localhost:8123",
        )

        assert state.rampup_order_enabled is False
        assert state._playlist_manager._rampup_order is None

    def test_flag_plumbs_through_and_builds_arc(self):
        """rampup_order_enabled=True lands on state AND builds a difficulty arc."""
        random.seed(42)
        state = make_game_state()
        difficulties = {"a": 1, "b": 4, "c": 2, "d": 3}
        state.set_stats_service(_FakeStats(difficulties))

        state.create_game(
            playlists=["test.json"],
            songs=self._songs(difficulties),
            media_player="media_player.test",
            base_url="http://localhost:8123",
            rampup_order_enabled=True,
        )

        assert state.rampup_order_enabled is True
        manager = state._playlist_manager
        assert manager._rampup_order is not None
        order = _drain(manager)
        levels = [_effective(s["_resolved_uri"], difficulties) for s in order]
        assert levels == sorted(levels)
        assert order[-1]["_resolved_uri"] == "b"  # hardest known = finale

    def test_flag_on_but_no_stats_degrades_to_random(self):
        """Ramp-up on without a connected StatsService → graceful random."""
        state = make_game_state()  # no stats service connected
        difficulties = {"a": 1, "b": 4}

        state.create_game(
            playlists=["test.json"],
            songs=self._songs(difficulties),
            media_player="media_player.test",
            base_url="http://localhost:8123",
            rampup_order_enabled=True,
        )

        assert state.rampup_order_enabled is True
        # No difficulty data reachable → arc degrades to uniform random.
        assert state._playlist_manager._rampup_order is None
