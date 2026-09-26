"""The server tells clients whether the game has a round cap (#2958).

With ``max_rounds: 0`` ("play every song", #1475) ``total_rounds`` is only the
size of the playable song pool, so the TV printed "Round 1 of 266" and the
lobby said "266 rounds, …". The screens now drop the total for such a game,
which needs the host's choice itself on the wire — ``total_rounds`` alone
cannot tell a 10-song "all songs" game from a 10-round cap.
"""

from __future__ import annotations

from custom_components.beatify.game.serializers import GameStateSerializer
from custom_components.beatify.game.state import GamePhase
from custom_components.beatify.server.serializers import PLAYER_VISIBLE_KEYS
from tests.conftest import make_game_state, make_songs


def _game(**kwargs):
    gs = make_game_state()
    gs.create_game(
        playlists=["test.json"],
        songs=make_songs(30),
        media_player="media_player.test",
        base_url="http://localhost:8123",
        **kwargs,
    )
    return gs


def test_uncapped_game_echoes_zero():
    gs = _game()
    state = GameStateSerializer.serialize(gs)
    assert state["max_rounds"] == 0
    # The pool is still reported as total_rounds; only the cap says it is open.
    assert state["total_rounds"] == 30


def test_capped_game_echoes_the_cap():
    gs = _game(max_rounds=10)
    state = GameStateSerializer.serialize(gs)
    assert state["max_rounds"] == 10
    assert state["total_rounds"] == 10


def test_present_in_every_phase():
    gs = _game()
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
        assert state["max_rounds"] == 0, f"missing in {phase}"


def test_players_may_see_it():
    """A setting, not an answer — the phone header needs it too."""
    assert "max_rounds" in PLAYER_VISIBLE_KEYS
