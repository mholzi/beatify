"""The round cap has to hold for a multi-playlist selection too (#2418).

@boardnick0815 reported a game running past the round count he had chosen: the
setup screen showed 10 selected, the game-over screen showed 11 rounds played.

`PlaylistManager` capped `self._songs` with `random.sample`, but assigned
`self._buckets` before that and never regrouped them. `get_next_song()` reads
the pool only in the single-playlist case; with two or more playlists it takes
the balanced path, which reads the buckets — so the cap did nothing there.

Measured before the fix: two playlists of 150 with a cap of 10 served **all
300**, while `get_total_count()` went on reporting 10.

The existing cap tests all use a single playlist, which is exactly where both
paths agree — which is why this went unnoticed. These tests therefore **drain**
the manager until it is empty and count what it served, rather than asking
`get_total_count()`. That number was right the whole time; what it claimed
about the rest of the game was not.
"""

from __future__ import annotations

from typing import Any

from custom_components.beatify.game.playlist import MIN_ROUNDS, PlaylistManager


def _songs(prefix: str, count: int, source: str) -> list[dict[str, Any]]:
    """Playable Spotify songs tagged with a playlist source."""
    return [
        {
            "title": f"{prefix} {i}",
            "artist": "Test Artist",
            "year": 1990,
            "uri": f"spotify:track:{prefix}{i:04d}",
            "_playlist_source": source,
        }
        for i in range(count)
    ]


def _drain(pm: PlaylistManager, limit: int = 5000) -> int:
    """Serve songs until the manager runs out; return how many it served."""
    served = 0
    while served <= limit:
        song = pm.get_next_song()
        if song is None:
            return served
        pm.mark_played(song["_resolved_uri"])
        served += 1
    raise AssertionError(f"manager served more than {limit} songs — no end in sight")


class TestRoundCapAcrossPlaylists:
    """What the cap promises: the game stops after that many rounds."""

    def test_two_playlists_stop_at_the_cap(self) -> None:
        pm = PlaylistManager(
            _songs("a", 150, "one.json") + _songs("b", 150, "two.json"),
            provider="spotify",
            max_rounds=10,
        )
        assert _drain(pm) == 10

    def test_three_playlists_stop_at_the_cap(self) -> None:
        pm = PlaylistManager(
            _songs("a", 100, "one.json")
            + _songs("b", 100, "two.json")
            + _songs("c", 100, "three.json"),
            provider="spotify",
            max_rounds=20,
        )
        assert _drain(pm) == 20

    def test_single_playlist_still_stops_at_the_cap(self) -> None:
        # The case that always worked — kept so the regroup cannot break it.
        pm = PlaylistManager(
            _songs("a", 150, "one.json"), provider="spotify", max_rounds=10
        )
        assert _drain(pm) == 10

    def test_no_cap_still_plays_everything_across_playlists(self) -> None:
        # A fix that shortens uncapped games would be worse than the bug.
        pm = PlaylistManager(
            _songs("a", 40, "one.json") + _songs("b", 40, "two.json"),
            provider="spotify",
            max_rounds=0,
        )
        assert _drain(pm) == 80

    def test_cap_above_the_pool_leaves_it_alone(self) -> None:
        pm = PlaylistManager(
            _songs("a", 12, "one.json") + _songs("b", 12, "two.json"),
            provider="spotify",
            max_rounds=100,
        )
        assert _drain(pm) == 24

    def test_cap_below_the_floor_is_raised_to_it(self) -> None:
        # MIN_ROUNDS is enforced in the manager, so a hand-crafted request
        # cannot undercut it either — that holds across playlists as well.
        pm = PlaylistManager(
            _songs("a", 100, "one.json") + _songs("b", 100, "two.json"),
            provider="spotify",
            max_rounds=3,
        )
        assert _drain(pm) == MIN_ROUNDS


class TestPoolAndBucketsAgree:
    """The contract that broke: the announced count is the played count."""

    def test_total_count_matches_what_is_served(self) -> None:
        pm = PlaylistManager(
            _songs("a", 150, "one.json") + _songs("b", 150, "two.json"),
            provider="spotify",
            max_rounds=10,
        )
        announced = pm.get_total_count()
        assert _drain(pm) == announced

    def test_buckets_hold_exactly_the_pool(self) -> None:
        pm = PlaylistManager(
            _songs("a", 150, "one.json") + _songs("b", 150, "two.json"),
            provider="spotify",
            max_rounds=10,
        )
        in_buckets = [s for bucket in pm._buckets.values() for s in bucket]
        assert len(in_buckets) == len(pm._songs)
        assert {s["uri"] for s in in_buckets} == {s["uri"] for s in pm._songs}

    def test_balanced_mode_still_draws_from_both_playlists(self) -> None:
        # The balanced path exists to keep the mix; capping must not turn a
        # two-playlist game into a one-playlist game.
        sources = set()
        for _ in range(20):
            pm = PlaylistManager(
                _songs("a", 150, "one.json") + _songs("b", 150, "two.json"),
                provider="spotify",
                max_rounds=10,
            )
            sources.update(s["_playlist_source"] for s in pm._songs)
        assert sources == {"one.json", "two.json"}
