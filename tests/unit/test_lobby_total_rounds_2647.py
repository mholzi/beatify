"""The lobby must be able to say how many rounds this game has (#2647).

``total_rounds`` is known from ``create_game`` on — it is the size of the
filtered, deduplicated playable pool — but it was serialized only in the
PLAYING phase.  The one screen whose entire job is telling the room what it is
about to play therefore had no round count, and ``dashboard.js`` fell back to a
hardcoded ``10``: a number nobody had chosen and one that is wrong for most
playlists.

Same shape as #1867 did for ``round_duration``: put it in the base payload so
every phase carries it, and pin that it is the number the round manager will
actually count to.
"""

from __future__ import annotations

from custom_components.beatify.game.serializers import GameStateSerializer
from custom_components.beatify.game.state import GamePhase
from tests.conftest import make_game_state, make_songs


def _game(song_count: int = 7):
    gs = make_game_state()
    gs.create_game(
        playlists=["test.json"],
        songs=make_songs(song_count),
        media_player="media_player.test",
        base_url="http://localhost:8123",
    )
    return gs


def test_present_in_the_lobby_before_any_round_exists():
    gs = _game(7)
    assert gs.phase == GamePhase.LOBBY
    state = GameStateSerializer.serialize(gs)
    assert state["total_rounds"] == 7


def test_present_in_every_phase():
    gs = _game(7)
    for phase in (
        GamePhase.LOBBY,
        GamePhase.PLAYING,
        GamePhase.REVEAL,
        GamePhase.PAUSED,
        GamePhase.END,
    ):
        gs.phase = phase
        state = GameStateSerializer.serialize(gs)
        assert state is not None
        assert state["total_rounds"] == 7, f"missing in {phase}"


def test_it_is_the_number_the_round_manager_counts_to():
    """Not a literal: a serializer reading some other attribute holding 7
    would pass that. Compare against the value 'Round X of Y' is built from.
    """
    gs = _game(5)
    state = GameStateSerializer.serialize(gs)
    assert state["total_rounds"] == gs.total_rounds
