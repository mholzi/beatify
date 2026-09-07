"""#2645 — the host gets a pause that is theirs, and an announcement with it.

Before this, every reason a Beatify game could be paused for was one the
*server* had decided: the admin socket dropped, the speaker stopped answering,
the playlist ran dry. ``GameState.pause_game(reason)`` had been sitting there
the whole time with no way for a host to call it. The host had Stop — which
takes the music away, leaves the clock running and scores the entire room as
"missed" — and locking the phone, which trips ``admin_disconnected``.

Three things are worth failing a build over, and all three are behavioural:

1. **A host pause happens, and it is not a stop.** The phase is PAUSED and the
   reason is the one the host sent, so all three screens can name it.
2. **A pause the server owns cannot be re-labelled.** "Pizza is here" must
   never be able to cover a speaker that stopped answering: the room would then
   settle in to wait for a host who is himself waiting for a speaker.
3. **The fourth tile really swaps the pause for a plain Stop.** That tile is
   the old Stop standing next to the pause reasons with its consequence spelled
   out, and a tile that only *looks* actionable would make the juxtaposition a
   lie. Picking it has to leave the pause and silence the song, so the round
   runs on.

The rendering half lives in
``custom_components/beatify/www/js/__tests__/host-pause-2645.test.js``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.beatify.const import (
    HOST_PAUSE_REASON,
    HOST_PAUSE_REASON_DOOR,
    HOST_PAUSE_REASON_FOOD,
    HOST_PAUSE_REASONS,
)
from custom_components.beatify.game.serializers import GameStateSerializer
from custom_components.beatify.game.state import GamePhase
from custom_components.beatify.server.ws_handlers.admin import (
    admin_pause_game,
    admin_stop_song,
)
from tests.conftest import make_songs
from tests.unit.test_websocket import _make_handler_and_game


def _running_game(phase: GamePhase = GamePhase.PLAYING):
    """A game mid-round with a host seated on a phone and a stubbed speaker."""
    handler, game_state, host_ws = _make_handler_and_game(songs=make_songs(5))
    game_state.add_player("Host", host_ws)
    game_state.set_admin("Host")
    game_state.phase = phase
    game_state.current_song = {"year": 1984, "title": "Take On Me", "artist": "a-ha"}

    speaker = MagicMock()
    speaker.stop = AsyncMock()
    speaker.play = AsyncMock()
    speaker.get_playback_state.return_value = "playing"
    game_state._media_player_service = speaker

    handler.broadcast = AsyncMock()
    handler.broadcast_state = AsyncMock()
    return handler, game_state, host_ws


def _errors(ws) -> list[dict]:
    return [
        call.args[0]
        for call in ws.send_json.call_args_list
        if call.args and call.args[0].get("type") == "error"
    ]


# ---------------------------------------------------------------------------
# 1. The pause itself
# ---------------------------------------------------------------------------


class TestTheHostCanPause:
    async def test_a_bare_tap_pauses_the_game(self):
        handler, game_state, ws = _running_game()

        await admin_pause_game(handler, ws, {"action": "pause_game"}, game_state)

        assert game_state.phase == GamePhase.PAUSED
        assert game_state.pause_reason == HOST_PAUSE_REASON
        assert _errors(ws) == []

    async def test_the_room_is_told(self):
        """A pause only the host can see is not a pause — the TV must repaint."""
        handler, game_state, ws = _running_game()

        await admin_pause_game(handler, ws, {"action": "pause_game"}, game_state)

        handler.broadcast_state.assert_awaited()

    async def test_a_named_reason_is_carried_through(self):
        handler, game_state, ws = _running_game()

        await admin_pause_game(
            handler, ws, {"reason": HOST_PAUSE_REASON_FOOD}, game_state
        )

        assert game_state.pause_reason == HOST_PAUSE_REASON_FOOD

    async def test_it_stops_the_music_rather_than_only_the_clock(self):
        """The half Stop already did — the pause has to do it too."""
        handler, game_state, ws = _running_game()

        await admin_pause_game(handler, ws, {}, game_state)

        game_state._media_player_service.stop.assert_awaited()

    async def test_it_is_not_a_stop(self):
        """`song_stopped` is Stop's flag. A pause must not raise it: the resume
        watchdog (#2576) and the reveal auto-advance (#2690) both read it as
        'the host silenced this round on purpose'."""
        handler, game_state, ws = _running_game()

        await admin_pause_game(handler, ws, {}, game_state)

        assert game_state.song_stopped is False

    async def test_the_reveal_can_be_paused_too(self):
        """The doorbell does not wait for the round boundary."""
        handler, game_state, ws = _running_game(GamePhase.REVEAL)

        await admin_pause_game(handler, ws, {}, game_state)

        assert game_state.phase == GamePhase.PAUSED

    async def test_the_lobby_cannot_be_paused(self):
        handler, game_state, ws = _running_game(GamePhase.LOBBY)

        await admin_pause_game(handler, ws, {}, game_state)

        assert game_state.phase == GamePhase.LOBBY
        assert _errors(ws), "the host must be told why nothing happened"

    async def test_an_invented_reason_is_refused_and_pauses_nothing(self):
        """The reason reaches three screens as a headline. An open string would
        put whatever a client sent on a TV in front of the room."""
        handler, game_state, ws = _running_game()

        await admin_pause_game(handler, ws, {"reason": "pizza"}, game_state)

        assert game_state.phase == GamePhase.PLAYING
        assert _errors(ws)


# ---------------------------------------------------------------------------
# 2. The announcement, and who may write it
# ---------------------------------------------------------------------------


class TestTheAnnouncementCanBeChanged:
    async def test_a_second_reason_relabels_without_leaving_the_pause(self):
        handler, game_state, ws = _running_game()
        await admin_pause_game(
            handler, ws, {"reason": HOST_PAUSE_REASON_FOOD}, game_state
        )

        await admin_pause_game(
            handler, ws, {"reason": HOST_PAUSE_REASON_DOOR}, game_state
        )

        assert game_state.phase == GamePhase.PAUSED
        assert game_state.pause_reason == HOST_PAUSE_REASON_DOOR
        assert _errors(ws) == []

    async def test_the_relabel_reaches_the_screens(self):
        handler, game_state, ws = _running_game()
        await admin_pause_game(handler, ws, {}, game_state)
        handler.broadcast_state.reset_mock()

        await admin_pause_game(
            handler, ws, {"reason": HOST_PAUSE_REASON_FOOD}, game_state
        )

        handler.broadcast_state.assert_awaited()

    async def test_a_speaker_failure_cannot_be_dressed_up_as_pizza(self):
        handler, game_state, ws = _running_game()
        await game_state.pause_game("media_player_error")
        handler.broadcast_state.reset_mock()

        await admin_pause_game(
            handler, ws, {"reason": HOST_PAUSE_REASON_FOOD}, game_state
        )

        assert game_state.pause_reason == "media_player_error"
        assert _errors(ws)
        handler.broadcast_state.assert_not_awaited()

    async def test_an_admin_disconnect_cannot_be_relabelled_either(self):
        handler, game_state, ws = _running_game()
        await game_state.pause_game("admin_disconnected")

        await admin_pause_game(handler, ws, {}, game_state)

        assert game_state.pause_reason == "admin_disconnected"
        assert _errors(ws)

    def test_every_reason_the_handler_accepts_is_in_the_shared_set(self):
        """The frontend mirrors this set; a code added on one side only would
        render as its raw string on the TV."""
        assert HOST_PAUSE_REASON in HOST_PAUSE_REASONS
        assert HOST_PAUSE_REASON_FOOD in HOST_PAUSE_REASONS
        assert HOST_PAUSE_REASON_DOOR in HOST_PAUSE_REASONS
        assert "media_player_error" not in HOST_PAUSE_REASONS
        assert "admin_disconnected" not in HOST_PAUSE_REASONS


# ---------------------------------------------------------------------------
# 3. The fourth tile: the old Stop, standing next to the pause reasons
# ---------------------------------------------------------------------------


class TestJustTheMusicOff:
    async def test_it_lifts_the_pause_and_silences_the_song(self):
        handler, game_state, ws = _running_game()
        await admin_pause_game(handler, ws, {}, game_state)

        await admin_stop_song(handler, ws, {"action": "stop_song"}, game_state)

        assert game_state.phase == GamePhase.PLAYING
        assert game_state.song_stopped is True
        assert _errors(ws) == []

    async def test_the_clock_really_runs_again(self):
        """The tile's sentence promises exactly this. A resume that left the
        game paused would make it the second Stop-shaped trap in one screen."""
        handler, game_state, ws = _running_game()
        await admin_pause_game(handler, ws, {}, game_state)

        await admin_stop_song(handler, ws, {}, game_state)

        assert game_state.pause_reason is None

    async def test_a_server_pause_is_not_convertible(self):
        """Resuming into a dead speaker to then stop a song that never played
        is not a thing a host can have meant."""
        handler, game_state, ws = _running_game()
        await game_state.pause_game("media_player_error")

        await admin_stop_song(handler, ws, {}, game_state)

        assert game_state.phase == GamePhase.PAUSED
        assert _errors(ws)

    async def test_a_plain_stop_mid_round_is_unchanged(self):
        """The path that existed before #2645 must still behave."""
        handler, game_state, ws = _running_game()

        await admin_stop_song(handler, ws, {}, game_state)

        assert game_state.phase == GamePhase.PLAYING
        assert game_state.song_stopped is True
        assert _errors(ws) == []

    async def test_stop_outside_a_round_is_still_refused(self):
        handler, game_state, ws = _running_game(GamePhase.REVEAL)

        await admin_stop_song(handler, ws, {}, game_state)

        assert _errors(ws)


# ---------------------------------------------------------------------------
# What the screens are given to render with
# ---------------------------------------------------------------------------


class TestThePausedPayload:
    @pytest.mark.parametrize(
        "phase", [GamePhase.PLAYING, GamePhase.REVEAL], ids=["playing", "reveal"]
    )
    async def test_the_payload_says_which_phase_the_pause_interrupted(self, phase):
        """The "Just the music off" tile is only offered when there is a round
        left to run on, and the screens decide that off this field."""
        handler, game_state, ws = _running_game(phase)
        await admin_pause_game(handler, ws, {}, game_state)

        payload = GameStateSerializer.serialize(game_state)

        assert payload["paused_from"] == phase.value

    async def test_the_reason_travels_with_it(self):
        handler, game_state, ws = _running_game()
        await admin_pause_game(
            handler, ws, {"reason": HOST_PAUSE_REASON_FOOD}, game_state
        )

        payload = GameStateSerializer.serialize(game_state)

        assert payload["pause_reason"] == HOST_PAUSE_REASON_FOOD

    async def test_the_guest_socket_is_allowed_to_see_it(self):
        """The host's phone is a player socket. Filtered out, its pause screen
        would render the announcement list for a round it cannot see."""
        from custom_components.beatify.server.serializers import PLAYER_VISIBLE_KEYS

        assert "paused_from" in PLAYER_VISIBLE_KEYS
        assert "pause_reason" in PLAYER_VISIBLE_KEYS
