"""A guest the host sat out does not read "Exact!" on the reveal (#3001).

Round-end scoring skips every ``out_of_play`` player, so a sat-out guest
(#2746) kept ``missed_round = False`` from ``reset_round`` with ``years_off``
unset. The phone's reveal branches on ``missed_round`` and reads a missing
``years_off`` as 0 — the rc3 live test showed "NAILED IT! · Exact! · +0" for a
guest who had not guessed. The round now flags them as missed, the same state
every other non-guesser gets, and their frozen totals stay untouched.
"""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.beatify.game.config import GameOptions
from custom_components.beatify.game.serializers import GameStateSerializer
from custom_components.beatify.game.state import GamePhase, GameState

from tests.conftest import make_game_state


def _songs(n: int = 5) -> list[dict[str, Any]]:
    return [
        {
            "year": 1980 + i,
            "title": f"Song {i}",
            "artist": f"Artist {i}",
            "uri": f"spotify:track:test{i:022d}",
            "uri_spotify": f"spotify:track:test{i:022d}",
        }
        for i in range(n)
    ]


@pytest.fixture
def game() -> GameState:
    state = make_game_state()
    state.create_game(
        playlists=["test.json"],
        songs=_songs(),
        media_player="media_player.party",
        base_url="http://localhost:8123",
        options=GameOptions(),
    )
    for name in ("Dieter", "Ben", "Anna"):
        ok, _ = state.add_player(name, ws=None)
        assert ok, name
    state._set_phase(GamePhase.PLAYING)
    for p in state.players.values():
        p.reset_round()
    return state


def test_sat_out_guest_is_flagged_missed_and_keeps_the_score(game: GameState):
    dieter = game.get_player("Dieter")
    dieter.score = 40
    dieter.streak = 2
    game.sit_out_player("Dieter")
    game.get_player("Anna").submit_guess(1990, 0.0)

    game._score_all_players(1990, list(game.players.values()))

    assert dieter.missed_round is True
    assert dieter.years_off is None
    assert dieter.round_score == 0
    # Frozen like any out_of_play player (#1748): nothing else moves.
    assert dieter.score == 40
    assert dieter.streak == 2
    assert dieter.round_scores == []
    # Same flag as the guest who simply did not answer…
    assert game.get_player("Ben").missed_round is True
    # …and the one who guessed right is untouched.
    assert game.get_player("Anna").missed_round is False
    assert game.get_player("Anna").years_off == 0


def test_the_reveal_payload_carries_the_flag(game: GameState):
    game.sit_out_player("Dieter")
    game._score_all_players(1990, list(game.players.values()))

    row = next(
        p
        for p in GameStateSerializer.get_reveal_players_state(game)
        if p["name"] == "Dieter"
    )
    assert row["missed_round"] is True
    assert row["years_off"] is None


def test_a_rejoin_in_reveal_keeps_the_missed_verdict(game: GameState):
    # #2746: in REVEAL the return is immediate. The reveal on screen is still
    # the round they sat out, so the verdict must not flip back.
    dieter = game.get_player("Dieter")
    game.sit_out_player("Dieter")
    game._score_all_players(1990, list(game.players.values()))
    game._set_phase(GamePhase.REVEAL)

    assert game.request_rejoin("Dieter") is True
    assert dieter.sat_out_by_host is False
    assert dieter.missed_round is True


def test_eliminated_and_playoff_spectators_are_unchanged(game: GameState):
    ben = game.get_player("Ben")
    anna = game.get_player("Anna")
    ben.eliminated = True
    anna.playoff_spectator = True

    game._score_all_players(1990, list(game.players.values()))

    assert ben.missed_round is False
    assert anna.missed_round is False
