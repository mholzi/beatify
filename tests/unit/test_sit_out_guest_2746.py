"""Taking a guest out of a running game, and letting them back (#2746).

The case that started the issue: a guest has to leave in the middle of a party.
``admin_kick_player`` refused twice — outside LOBBY, and for anyone still
connected — so there was no answer at all. The round went on waiting for
somebody who had gone home.

The design gate drew four options and the host picked **B**: every guest row is
removable, connected or not, in the lobby and in a running game. Both server
refusals drop, and what replaces them is **recoverability** rather than a
precondition. The worst outcome of a mis-tap in a dark room is a guest who taps
back in with their points intact — not a guest whose game was destroyed, which
is what option D would have cost.

The return path was the open question the gate left. It was answered on
2026-09-08: the guest comes back from **their own phone**, because the session
survives the removal and the phone already holds everything a return needs.
"""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.beatify.game.config import GameOptions
from custom_components.beatify.game.state import GamePhase, GameState

from tests.conftest import make_game_state


def _songs(n: int = 20) -> list[dict[str, Any]]:
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


class _LiveWs:
    """The bare minimum ``is_active`` looks at: an object that is not closed."""

    closed = False


def _live_ws() -> _LiveWs:
    return _LiveWs()


def _seat(state: GameState, name: str, score: int = 0, ws=None):
    ok, _ = state.add_player(name, ws=ws)
    assert ok, name
    player = state.get_player(name)
    player.score = score
    return player


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
    return state


class TestSittingOut:
    def test_the_session_survives_and_so_does_the_score(self, game: GameState):
        tom = _seat(game, "Tom", score=980)
        game._set_phase(GamePhase.PLAYING)

        assert game.sit_out_player("Tom") is True

        # Not deleted. That distinction is the whole design: a deleted guest
        # cannot come back, and the person who walks in from the kitchen finds
        # their points gone.
        assert game.get_player("Tom") is tom
        assert tom.score == 980
        assert tom.sat_out_by_host is True

    def test_the_round_stops_waiting_for_them(self, game: GameState):
        # all_submitted() counts only genuinely live sockets (#928), so both
        # guests need one — a None ws would make the room empty and the check
        # would pass for the wrong reason.
        _seat(game, "Tom", ws=_live_ws())
        _seat(game, "Nina", ws=_live_ws())
        game._set_phase(GamePhase.PLAYING)
        for p in game.players.values():
            p.submitted = False
        game.get_player("Nina").submitted = True

        assert game.all_submitted() is False
        game.sit_out_player("Tom")
        # out_of_play players are skipped by all_submitted(), so the reveal is
        # no longer held up by somebody who has left.
        assert game.all_submitted() is True

    def test_the_host_cannot_be_sat_out(self, game: GameState):
        host = _seat(game, "Markus")
        host.is_admin = True
        assert game.sit_out_player("Markus") is False
        assert host.sat_out_by_host is False

    def test_an_unknown_name_changes_nothing(self, game: GameState):
        _seat(game, "Tom")
        assert game.sit_out_player("Nobody") is False
        assert game.get_player("Tom").sat_out_by_host is False

    def test_a_new_game_brings_everyone_back(self, game: GameState):
        tom = _seat(game, "Tom")
        game.sit_out_player("Tom")
        tom.reset_for_new_game()
        assert tom.sat_out_by_host is False
        assert tom.rejoin_requested is False


class TestComingBack:
    def test_in_reveal_the_return_is_immediate(self, game: GameState):
        tom = _seat(game, "Tom", score=980)
        game._set_phase(GamePhase.REVEAL)
        game.sit_out_player("Tom")

        assert game.request_rejoin("Tom") is True
        assert tom.sat_out_by_host is False
        assert tom.score == 980

    def test_mid_round_the_return_waits_for_the_next_round(self, game: GameState):
        tom = _seat(game, "Tom")
        game._set_phase(GamePhase.PLAYING)
        game.sit_out_player("Tom")

        assert game.request_rejoin("Tom") is True
        # Parked, not applied: a guess landing halfway through a round would be
        # scored against a song this player did not hear from the start.
        assert tom.rejoin_requested is True
        assert tom.sat_out_by_host is True
        assert tom.out_of_play is True

        returned = game.apply_pending_rejoins()
        assert returned == ["Tom"]
        assert tom.sat_out_by_host is False
        assert tom.rejoin_requested is False
        assert tom.out_of_play is False

    def test_somebody_who_was_never_sat_out_cannot_rejoin(self, game: GameState):
        _seat(game, "Tom")
        assert game.request_rejoin("Tom") is False

    def test_sudden_death_that_has_started_cutting_closes_the_door(
        self, game: GameState
    ):
        tom = _seat(game, "Tom")
        nina = _seat(game, "Nina")
        game.sudden_death_mode = True
        game._set_phase(GamePhase.REVEAL)
        game.sit_out_player("Tom")
        nina.eliminated = True

        # The survivor field is fixed once the playoff begins; re-entering it
        # would change who is playing for the win.
        assert game.rejoin_allowed(tom) is False
        assert game.request_rejoin("Tom") is False
        assert tom.sat_out_by_host is True

    def test_sudden_death_that_has_not_cut_yet_still_lets_them_back(
        self, game: GameState
    ):
        # Measured on state, not on intent: the mode being switched on is not
        # the same as the field having started to narrow. A game configured for
        # Sudden Death that never reached round 2 has eliminated nobody.
        tom = _seat(game, "Tom")
        _seat(game, "Nina")
        game.sudden_death_mode = True
        game._set_phase(GamePhase.REVEAL)
        game.sit_out_player("Tom")

        assert game.rejoin_allowed(tom) is True
        assert game.request_rejoin("Tom") is True

    def test_a_finale_playoff_closes_the_door_too(self, game: GameState):
        tom = _seat(game, "Tom")
        game._set_phase(GamePhase.REVEAL)
        game.sit_out_player("Tom")
        game._finale_playoff_active = True

        assert game.rejoin_allowed(tom) is False

    def test_apply_pending_rejoins_ignores_everyone_else(self, game: GameState):
        _seat(game, "Tom")
        nina = _seat(game, "Nina")
        game._set_phase(GamePhase.PLAYING)
        game.sit_out_player("Tom")
        game.request_rejoin("Tom")

        assert game.apply_pending_rejoins() == ["Tom"]
        assert nina.sat_out_by_host is False
