"""A song swap must not shorten the game (#3321).

The host's "Play another song" (#3261) replaced the song and then ran the
dropped-song accounting of #3279, so every swap took a round off
``total_rounds``: a 10-round game with two swaps ended after 8 and the phones
counted "1/7", "2/6", "3/5". A swap replaces the song inside the same round. In
a capped game the songs the cap left out wait in reserve (#2547); one of them
makes up for the swapped-out song, so the game keeps its length. A song that
fails to play still lowers ``total_rounds`` as before.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

from custom_components.beatify.game.config import GameOptions
from custom_components.beatify.game.playlist import SONG_ORDER_RAMPUP, PlaylistManager
from custom_components.beatify.game.state import GamePhase, GameState
from tests.conftest import make_game_state


def _songs(n: int) -> list[dict[str, Any]]:
    return [
        {
            "year": 1970 + i,
            "title": f"Song {i}",
            "artist": f"Artist {i}",
            "uri": f"spotify:track:test{i:022d}",
            "uri_spotify": f"spotify:track:test{i:022d}",
        }
        for i in range(n)
    ]


def _stub_media_service() -> MagicMock:
    svc = MagicMock()
    svc.is_available.return_value = True
    svc.last_failure_reason = None
    svc.last_attempted_uri = None
    svc.play_song = AsyncMock(return_value=True)
    svc.verify_responsive = AsyncMock(return_value=(True, None))
    svc.restore_volume = AsyncMock(return_value=True)
    svc.restore_queue = AsyncMock(return_value=True)
    svc.stop = AsyncMock(return_value=True)
    return svc


def _player_ws() -> MagicMock:
    ws = MagicMock()
    ws.closed = False
    ws.send_json = AsyncMock()
    return ws


async def _start(*, pool: int, cap: int = 0) -> GameState:
    gs = make_game_state()
    gs.create_game(
        playlists=["t.json"],
        songs=_songs(pool),
        media_player="media_player.esszimmer",
        base_url="http://h",
        options=GameOptions(max_rounds=cap) if cap else None,
    )
    gs._media_player_service = _stub_media_service()
    gs.platform = "music_assistant"
    for name in ("Alice", "Bob"):
        gs.add_player(name, _player_ws())
        gs.get_player(name).connected = True
    assert await gs.start_round() is True
    return gs


async def _play_out(gs: GameState) -> int:
    """Finish the game round by round and return the last round number."""
    last = gs.round
    for _ in range(50):
        await gs.end_round()
        if not await gs.start_round() or gs.phase is GamePhase.END:
            break
        last = gs.round
    assert gs.phase is GamePhase.END
    return last


class TestSwapKeepsTheRoundCount:
    async def test_two_swaps_keep_a_ten_round_game_at_ten(self):
        gs = await _start(pool=30, cap=10)
        assert gs.total_rounds == 10
        manager = gs._playlist_manager
        swapped_out: list[str] = []

        for expected_round in (2, 3):
            await gs.end_round()
            assert await gs.start_round() is True
            assert gs.round == expected_round
            old_uri = gs.current_song["_resolved_uri"]
            played_before = set(manager._played_uris)

            assert await gs.skip_song() is None

            assert gs.round == expected_round
            assert gs.total_rounds == 10
            new_uri = gs.current_song["_resolved_uri"]
            assert new_uri != old_uri
            # Taken from the unplayed songs; the swapped-out one stays played.
            assert new_uri not in played_before
            assert old_uri in manager._played_uris
            swapped_out.append(old_uri)

        # The pool still covers every promised round.
        assert gs.round + manager.get_remaining_count() == 10

        # ...and the game really runs ten rounds, never repeating a swapped
        # song.
        served: list[str] = []
        real_play = gs._media_player_service.play_song

        async def record(song):
            served.append(song["_resolved_uri"])
            return await real_play(song)

        gs._media_player_service.play_song = AsyncMock(side_effect=record)
        assert await _play_out(gs) == 10
        assert gs.total_rounds == 10
        assert not set(served) & set(swapped_out)

    async def test_failed_song_still_lowers_total_rounds(self):
        """#3279 stays: a song that never played costs a round."""
        gs = await _start(pool=30, cap=10)
        svc = gs._media_player_service
        results = iter([False, True])

        async def play(_song):
            ok = next(results)
            svc.last_failure_reason = None if ok else "unavailable"
            return ok

        svc.play_song = AsyncMock(side_effect=play)
        await gs.end_round()
        assert await gs.start_round() is True

        assert gs.round == 2
        assert gs.total_rounds == 9

    async def test_swap_without_a_reserve_still_says_the_game_is_shorter(self):
        """No cap, no reserve: the swap used up a real round's song, so the
        counter has to follow or the last reveal reads "4 of 5"."""
        gs = await _start(pool=5)
        assert gs.total_rounds == 5

        assert await gs.skip_song() is None

        assert gs.round == 1
        assert gs.total_rounds == 4
        assert await _play_out(gs) == 4


class TestPoolExhausted:
    async def test_reserve_counts_as_songs_left(self):
        gs = await _start(pool=12, cap=10)
        manager = gs._playlist_manager
        assert manager.reserve_count() == 2
        assert gs.preview_round_end()["songs_left"] == 9 + 2

    async def test_refused_once_pool_and_reserve_are_spent(self):
        gs = await _start(pool=11, cap=10)
        manager = gs._playlist_manager
        # Leave only the running song: everything else counts as played.
        for song in list(manager._songs):
            manager.mark_played(song["_precomputed_uri"])
        assert manager.get_remaining_count() == 0
        assert manager.reserve_count() == 1

        # The reserve song is still there to swap to.
        assert await gs.skip_song() is None
        assert gs.total_rounds == 10
        assert manager.reserve_count() == 0
        assert gs.preview_round_end()["songs_left"] == 0

        old_uri = gs.current_song["_resolved_uri"]
        assert await gs.skip_song() == "no_songs"
        assert gs.current_song["_resolved_uri"] == old_uri
        assert gs.phase is GamePhase.PLAYING


class TestRampUpFinaleStaysLast:
    def test_swap_release_goes_before_the_finale(self):
        songs = _songs(20)
        stars = {s["uri"]: (4 if i == 0 else 1) for i, s in enumerate(songs)}
        manager = PlaylistManager(
            songs,
            song_order=SONG_ORDER_RAMPUP,
            difficulty_lookup=lambda uri: stars.get(uri),
            max_rounds=10,
        )
        order = manager._rampup_order
        assert order is not None
        finale = order[-1]["_precomputed_uri"]
        first = manager.get_next_song()
        assert first is not None
        manager.mark_played(first["_resolved_uri"])

        assert manager.release_reserved_songs(1, reason="Song swap", next_up=True)

        assert order[-1]["_precomputed_uri"] == finale
        assert len(order) == 11
        nxt = manager.get_next_song()
        assert nxt is not None
        assert nxt["_precomputed_uri"] not in {first["_resolved_uri"], finale}
