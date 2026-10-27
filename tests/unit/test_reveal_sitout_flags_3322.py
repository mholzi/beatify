"""#3322: REVEAL player payload carries the host sit-out flags.

The phone host's guest list (#3304) reads ``sat_out_by_host`` and
``rejoin_requested`` from the broadcast; during REVEAL they were missing, so a
sit-out did not show until the next PLAYING broadcast.
"""

from __future__ import annotations

from custom_components.beatify.game.serializers import GameStateSerializer
from custom_components.beatify.game.state import GamePhase
from tests.conftest import make_game_state, make_songs


def _game():
    gs = make_game_state()
    gs.create_game(
        playlists=["test.json"],
        songs=make_songs(3),
        media_player="media_player.test",
        base_url="http://localhost:8123",
    )
    gs.add_player("Alice", None)
    gs.add_player("Bob", None)
    return gs


def test_reveal_players_carry_sitout_flags():
    gs = _game()
    gs.get_player("Bob").sat_out_by_host = True
    gs.get_player("Bob").rejoin_requested = True
    gs.phase = GamePhase.REVEAL

    rows = {r["name"]: r for r in GameStateSerializer.get_reveal_players_state(gs)}

    assert rows["Bob"]["sat_out_by_host"] is True
    assert rows["Bob"]["rejoin_requested"] is True
    assert rows["Alice"]["sat_out_by_host"] is False
    assert rows["Alice"]["rejoin_requested"] is False


def test_reveal_flags_match_playing_payload():
    gs = _game()
    gs.get_player("Bob").sat_out_by_host = True
    gs.phase = GamePhase.REVEAL
    reveal = {r["name"]: r for r in GameStateSerializer.get_reveal_players_state(gs)}
    playing = {p["name"]: p for p in gs.get_players_state()}
    for name in reveal:
        for key in ("sat_out_by_host", "rejoin_requested"):
            assert reveal[name][key] == playing[name][key]
