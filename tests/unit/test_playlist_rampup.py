"""Tests for ramp-up (difficulty-arc) song ordering (#1726).

Covers the opt-in ``song_order="rampup"`` mode on :class:`PlaylistManager`
(easy early / hard late / hardest-known reserved for the finale / unknown
treated as medium / graceful fallback to uniform random) plus the
``rampup_order_enabled`` setting plumbing through ``GameState.create_game``.
"""

from __future__ import annotations

import random
from unittest.mock import AsyncMock, MagicMock

from custom_components.beatify.game.config import GameOptions
from custom_components.beatify.game.playlist import (
    SONG_ORDER_RAMPUP,
    SONG_ORDER_RANDOM,
    PlaylistManager,
)
from custom_components.beatify.game.state import GamePhase
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


# ---------------------------------------------------------------------------
# #3029 — songs released from the reserve must be playable in a ramp-up game
# ---------------------------------------------------------------------------


def _stub_media_service():
    svc = MagicMock()
    svc.is_available.return_value = True
    svc.play_song = AsyncMock(return_value=True)
    svc.verify_responsive = AsyncMock(return_value=(True, None))
    svc.restore_volume = AsyncMock(return_value=True)
    svc.restore_queue = AsyncMock(return_value=True)
    svc.stop = AsyncMock(return_value=True)
    return svc


class TestRampUpWithReserve:
    """Encore (#2503) and finale playoff (#2547) release capped-out songs.

    ``get_next_song`` reads only the arc in ramp-up mode, so a release that
    reached the pool but not the arc ended the game instead of playing on.
    """

    def _capped_rampup_game(self, pool: int = 30, cap: int = 10):
        random.seed(3029)
        songs = [_song(i, f"spotify:track:rampup{i:016d}") for i in range(pool)]
        difficulties: dict[str, int | None] = {
            s["uri"]: (i % 4) + 1 for i, s in enumerate(songs)
        }
        state = make_game_state()
        state.set_stats_service(_FakeStats(difficulties))
        state.create_game(
            playlists=["test.json"],
            songs=songs,
            media_player="media_player.test",
            base_url="http://localhost:8123",
            options=GameOptions(max_rounds=cap),
            rampup_order_enabled=True,
        )
        manager = state._playlist_manager
        assert manager._rampup_order is not None
        assert manager.reserve_count() == pool - cap
        return state, difficulties

    def test_encore_songs_are_served_after_the_arc(self):
        state, difficulties = self._capped_rampup_game()
        manager = state._playlist_manager
        # Play the arc down to its last song, then open the encore window
        # exactly as the reveal of the second-to-last round does.
        for _ in range(state.total_rounds - 1):
            song = manager.get_next_song()
            assert song is not None
            manager.mark_played(song["_resolved_uri"])
        state.round = state.total_rounds - 1
        state._encore_window = True
        state._set_phase(GamePhase.REVEAL)

        assert state.extend_rounds() == 5
        assert manager.get_remaining_count() == 6

        rest = _drain(manager)
        # Before the fix: only the one remaining arc song, then None.
        assert len(rest) == 6
        encore_levels = [_effective(s["_resolved_uri"], difficulties) for s in rest[1:]]
        assert encore_levels == sorted(encore_levels)
        assert manager.get_remaining_count() == 0

    async def test_finale_playoff_plays_in_a_rampup_game(self):
        state, _ = self._capped_rampup_game()
        state._media_player_service = _stub_media_service()
        state.platform = "music_assistant"
        for name in ("Alice", "Bob"):
            state.add_player(name, None)
            state.get_player(name).connected = True
        state.finale_tiebreaker_enabled = True
        await state.start_round()
        manager = state._playlist_manager
        for song in list(manager._songs):
            manager.mark_played(song["_precomputed_uri"])
        state.phase = GamePhase.REVEAL
        state.get_player("Alice").score = 10
        state.get_player("Bob").score = 10
        assert state.songs_remaining == 0

        # Before the fix: the song was released into the pool, start_round
        # found the arc exhausted and set END, so the playoff never ran.
        assert await state.maybe_start_finale_playoff() is True
        assert state.phase == GamePhase.PLAYING
