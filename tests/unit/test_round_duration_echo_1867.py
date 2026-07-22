"""The server must tell clients which round timer it is actually running (#1867).

`round_duration` was the one create-game setting the serializer did not echo.
That made it write-only from a client's perspective: posted once, never
readable again. A lobby could therefore advertise "45S" over a server counting
30.0s and every screen looked correct — the mismatch in #1867 only surfaced
through log archaeology.

These tests pin the echo itself, that it survives a duration the host did not
choose (the server default), and that it is present in the phase where the
lobby chip needs it — before any round exists.
"""

from __future__ import annotations

from custom_components.beatify.const import DEFAULT_ROUND_DURATION
from custom_components.beatify.game.serializers import GameStateSerializer
from custom_components.beatify.game.state import GamePhase
from tests.conftest import make_game_state, make_songs


def _game(**kwargs):
    gs = make_game_state()
    gs.create_game(
        playlists=["test.json"],
        songs=make_songs(3),
        media_player="media_player.test",
        base_url="http://localhost:8123",
        **kwargs,
    )
    return gs


def test_serializer_echoes_the_chosen_duration():
    gs = _game(round_duration=30)
    state = GameStateSerializer.serialize(gs)
    assert state["round_duration"] == 30


def test_serializer_echoes_the_default_when_client_sent_none():
    """The fallback must be visible too — it is the case nobody chose."""
    gs = _game()
    state = GameStateSerializer.serialize(gs)
    assert state["round_duration"] == DEFAULT_ROUND_DURATION


def test_present_in_lobby_before_any_round_exists():
    """The lobby chip reads this while phase is still LOBBY."""
    gs = _game(round_duration=60)
    assert gs.phase == GamePhase.LOBBY
    state = GameStateSerializer.serialize(gs)
    assert state["round_duration"] == 60


def test_present_in_every_phase():
    gs = _game(round_duration=60)
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
        assert state["round_duration"] == 60, f"missing in {phase}"


def test_echo_matches_the_value_the_round_timer_uses():
    """Guards the whole point: the echoed number is the one that counts down.

    Asserting a literal would still pass if the serializer read some other
    attribute that happened to hold 30, so compare against the round manager's
    own value — the field `_start_round_timer` builds the deadline from.
    """
    gs = _game(round_duration=30)
    state = GameStateSerializer.serialize(gs)
    assert state["round_duration"] == gs._round_manager.round_duration
