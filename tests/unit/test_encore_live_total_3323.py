"""#3323 — the encore adds to the LIVE total and closes after the tap.

Live test of v4.8.7-rc4: a game created with 10 rounds had lost five songs to
swaps and failed starts, so ``total_rounds`` had been lowered to 5 (#3279).
The phone host read "Moves the finish line to 10" (live total + 5), one tap
went 5 -> 15 because ``extend_rounds`` reset the total to the pool size — and
the pool still counts the dropped songs. The offer also stayed on screen with
"LAST ROUND NEXT" although fifteen rounds were left.
"""

from __future__ import annotations

from typing import Any

from custom_components.beatify.game.config import GameOptions
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


def _enter_reveal(state: GameState) -> None:
    """Open the window exactly as the reveal transition decides it."""
    manager = state._playlist_manager
    state._encore_window = (
        state.total_rounds > 1
        and not state.last_round
        and manager.get_remaining_count() == 1
    )
    state._set_phase(GamePhase.REVEAL)


def _game_shrunk_by_drops(reserve: int = 20) -> GameState:
    """10 configured rounds, five songs dropped, reveal of round 4 of 5."""
    state = make_game_state()
    state.create_game(
        playlists=["test.json"],
        songs=_songs(10 + reserve),
        media_player="media_player.party",
        base_url="http://localhost:8123",
        options=GameOptions(max_rounds=10),
    )
    manager = state._playlist_manager
    assert state.total_rounds == 10
    # Four committed rounds plus five dropped songs: nine marked played.
    for song in list(manager._songs)[:9]:
        manager.mark_played(song["uri"])
    state.round = 4
    state._shrink_total_rounds_to_pool()
    assert state.total_rounds == 5
    assert manager.get_total_count() == 10  # dropped songs stay in the pool
    _enter_reveal(state)
    return state


class TestLiveTotal:
    def test_encore_adds_five_to_the_live_total(self):
        state = _game_shrunk_by_drops()
        assert state.encore_available() is True
        assert state.extend_rounds() == 5
        assert state.total_rounds == 10  # not 15

    def test_hint_promises_what_the_tap_produces(self):
        state = _game_shrunk_by_drops()
        before = state.get_state()
        promised = before["total_rounds"] + before["encore_rounds"]
        assert promised == 10
        state.extend_rounds()
        assert state.total_rounds == promised

    def test_hint_matches_a_short_reserve(self):
        # Only three songs held back: the control says 3 and the hint 5 + 3.
        state = _game_shrunk_by_drops(reserve=3)
        before = state.get_state()
        assert before["encore_rounds"] == 3
        promised = before["total_rounds"] + before["encore_rounds"]
        assert state.extend_rounds() == 3
        assert state.total_rounds == promised == 8


class TestOfferClosesAfterTheTap:
    def test_encore_unavailable_after_the_tap(self):
        state = _game_shrunk_by_drops()
        state.extend_rounds()
        assert state.encore_available() is False
        assert state.get_state()["encore_available"] is False
        # A second tap in the same reveal changes nothing.
        assert state.extend_rounds() == 0
        assert state.total_rounds == 10

    def test_offer_reopens_before_the_new_last_round(self):
        state = _game_shrunk_by_drops()
        state.extend_rounds()
        manager = state._playlist_manager
        unplayed = [s for s in manager._songs if s["uri"] not in manager._played_uris]
        assert len(unplayed) == 6
        # Rounds 5..8: more than one song left after each, no offer.
        for song in unplayed[:4]:
            state._encore_window = False  # what start_round does
            manager.mark_played(song["uri"])
            state.round += 1
            _enter_reveal(state)
            assert state.encore_available() is False
        # Round 9's reveal is the one before the new last round (10).
        state._encore_window = False
        manager.mark_played(unplayed[4]["uri"])
        state.round += 1
        _enter_reveal(state)
        assert state.round == 9
        assert state.encore_available() is True
