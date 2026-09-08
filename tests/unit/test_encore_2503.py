"""Encore — five more rounds, asked one round early (#2503).

Four options were drawn for this and the host picked **D**: the offer sits on
the reveal of the second-to-last round, and once the last round starts it is
gone. The three that lost are the reason the rules below look the way they do:

* **A** put a ``+5`` chip on the final reveal. Tapped again on each new last
  round, the ending keeps receding and "final round" stops meaning anything.
  That is why the window closes at round start and is not re-derivable
  afterwards.
* **B** and **C** put the control on the end screen, which needs a finished
  game to walk backwards out of ``END`` — a different order of change. Nothing
  here touches ``END``.
* **C** also pointed out that nothing on the end screen says Rematch resets
  every score. That line ships as its own small fix.

The mechanics were already in the repo: since #2547 the round cap keeps the
songs it drops in a reserve instead of discarding them, and the finale
tiebreaker already released them one at a time. An encore is the same release
with a different count and a raised cap.
"""

from __future__ import annotations

from typing import Any

from custom_components.beatify.game.config import GameOptions
from custom_components.beatify.game.state import GamePhase, GameState

from tests.conftest import make_game_state


def _songs(n: int = 30) -> list[dict[str, Any]]:
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


def _capped_game(cap: int = 10, pool: int = 30) -> GameState:
    """A game with a round cap, so songs sit in reserve."""
    state = make_game_state()
    state.create_game(
        playlists=["test.json"],
        songs=_songs(pool),
        media_player="media_player.party",
        base_url="http://localhost:8123",
        options=GameOptions(max_rounds=cap),
    )
    return state


def _play_up_to_reveal_before_last(state: GameState) -> None:
    """Mark songs played until exactly one is left, then enter REVEAL.

    Marking through the manager rather than driving real rounds keeps this a
    unit test: the condition under test is "one song left in the pool", which
    is what ``start_round`` reads too.
    """
    manager = state._playlist_manager
    for song in list(manager._songs)[: manager.get_total_count() - 1]:
        manager.mark_played(song["uri"])
    state.round = state.total_rounds - 1
    state._encore_window = (
        state.total_rounds > 1
        and not state.last_round
        and manager.get_remaining_count() == 1
    )
    state._set_phase(GamePhase.REVEAL)


class TestTheWindow:
    def test_open_on_the_reveal_before_the_last_round(self):
        state = _capped_game()
        _play_up_to_reveal_before_last(state)
        assert state.encore_available() is True

    def test_closed_during_playing(self):
        # The offer belongs to the pause between songs. Mid-song the host is
        # watching the room, not deciding how long the evening runs.
        state = _capped_game()
        _play_up_to_reveal_before_last(state)
        state._set_phase(GamePhase.PLAYING)
        assert state.encore_available() is False

    def test_closed_once_the_last_round_has_started(self):
        # The whole argument for this option over a chip on the final reveal.
        state = _capped_game()
        _play_up_to_reveal_before_last(state)
        state._encore_window = False  # what start_round does
        assert state.encore_available() is False

    def test_closed_with_an_empty_reserve(self):
        # No cap means no reserve: there is nothing to extend with, and a
        # control promising five more rounds would be lying.
        state = make_game_state()
        state.create_game(
            playlists=["test.json"],
            songs=_songs(12),
            media_player="media_player.party",
            base_url="http://localhost:8123",
            options=GameOptions(),
        )
        _play_up_to_reveal_before_last(state)
        assert state._playlist_manager.reserve_count() == 0
        assert state.encore_available() is False

    def test_closed_before_the_second_to_last_round(self):
        state = _capped_game()
        state._set_phase(GamePhase.REVEAL)
        assert state.encore_available() is False


class TestExtending:
    def test_five_more_rounds_and_the_scores_are_untouched(self):
        state = _capped_game(cap=10)
        ok, _ = state.add_player("Nina", ws=None)
        assert ok
        nina = next(p for p in state.players.values() if p.name == "Nina")
        nina.score = 2140
        _play_up_to_reveal_before_last(state)

        assert state.total_rounds == 10
        assert state.extend_rounds() == 5
        assert state.total_rounds == 15
        # The point of the whole feature.
        assert nina.score == 2140

    def test_the_cap_moves_with_the_pool(self):
        # If max_rounds stayed at ten, the next manager rebuild — a lobby
        # option patch, a rematch — would sample the game straight back down
        # and quietly undo the encore.
        state = _capped_game(cap=10)
        _play_up_to_reveal_before_last(state)
        state.extend_rounds()
        assert state.max_rounds == 15

    def test_a_second_tap_in_the_same_reveal_adds_five_more(self):
        # Drawn behaviour: "Tapped twice it says 30." The window survives its
        # own use — it is a flag on this reveal, not a re-derived count that
        # the first tap would falsify.
        state = _capped_game(cap=10, pool=30)
        _play_up_to_reveal_before_last(state)
        assert state.extend_rounds() == 5
        assert state.extend_rounds() == 5
        assert state.total_rounds == 20

    def test_a_short_reserve_still_gives_what_it_has(self):
        # Three more rounds answers "play a bit longer" better than a refusal
        # because the reserve was two songs short.
        state = _capped_game(cap=10, pool=13)
        _play_up_to_reveal_before_last(state)
        assert state.extend_rounds() == 3
        assert state.total_rounds == 13

    def test_extending_outside_the_window_changes_nothing(self):
        state = _capped_game(cap=10)
        _play_up_to_reveal_before_last(state)
        state._encore_window = False
        assert state.extend_rounds() == 0
        assert state.total_rounds == 10
        assert state.max_rounds == 10

    def test_the_released_songs_are_playable(self):
        # A round that has no song to play is not a round. The release has to
        # reach the buckets too, not only the flat pool (#2418).
        state = _capped_game(cap=10)
        _play_up_to_reveal_before_last(state)
        state.extend_rounds()
        assert state._playlist_manager.get_remaining_count() == 6
        assert state._playlist_manager.get_next_song() is not None


class TestTheTiebreakerStillWorks:
    def test_reserve_songs_for_playoff_still_releases_one(self):
        # release_reserved_songs is now shared with the encore; the finale
        # tiebreaker (#1725/#2547) must be unaffected by that.
        state = _capped_game(cap=10)
        before = state._playlist_manager.reserve_count()
        assert state._playlist_manager.reserve_songs_for_playoff(1) == 1
        assert state._playlist_manager.reserve_count() == before - 1
