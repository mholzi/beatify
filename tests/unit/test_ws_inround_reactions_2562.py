"""Tests for #2562 — reactions during the round for players who already submitted.

Two things are under test here and they are separate:

* the **gate**: who may react in which phase. During PLAYING it is the players
  who are done with the round — submitted, eliminated (#827) or sitting out a
  finale playoff (#2578). A player still dragging their slider may not.
* the **ack**: every reaction, accepted or throttled, comes back to the sender
  with the remaining cooldown, so the phone can draw a countdown instead of
  leaving a tap looking like a dead button.

The throttle itself is tested against the game state in
``tests/unit/test_state.py::TestRecordReaction``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.beatify.const import DOMAIN, REACTION_THROTTLE_SECONDS
from custom_components.beatify.game.state import GamePhase
from custom_components.beatify.server.ws_handlers.lifecycle import handle_reaction
from tests.conftest import make_game_state, make_songs

from custom_components.beatify.server.websocket import (  # isort: skip
    BeatifyWebSocketHandler,
)


def _stub_media_service() -> MagicMock:
    svc = MagicMock()
    svc.is_available.return_value = True
    svc.play_song = AsyncMock(return_value=True)
    svc.verify_responsive = AsyncMock(return_value=(True, None))
    return svc


def _ws() -> AsyncMock:
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    ws.closed = False
    ws.close = AsyncMock()
    return ws


class Clock:
    """A hand-wound clock so the throttle can be stepped over deterministically."""

    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


async def _playing_game(names=("Alice", "Bob")):
    """A started game in PLAYING with the given players connected."""
    clock = Clock()
    mock_hass = MagicMock()
    gs = make_game_state(time_fn=clock)
    gs.create_game(
        playlists=["t.json"],
        songs=make_songs(3),
        media_player="media_player.x",
        base_url="http://h",
    )
    gs._media_player_service = _stub_media_service()
    gs.platform = "music_assistant"
    mock_hass.data = {DOMAIN: {"game": gs}}
    handler = BeatifyWebSocketHandler(mock_hass)
    handler.broadcast_state = AsyncMock()
    handler.broadcast = AsyncMock()
    handler.debounced_broadcast_state = AsyncMock()

    sockets = {}
    for name in names:
        ws = _ws()
        gs.add_player(name, ws)
        gs.get_player(name).connected = True
        sockets[name] = ws
    await gs.start_round()
    assert gs.phase == GamePhase.PLAYING
    return handler, gs, sockets, clock


def _broadcast_emojis(handler: AsyncMock) -> list[str]:
    return [
        call.args[0]["emoji"]
        for call in handler.broadcast.call_args_list
        if call.args
        and isinstance(call.args[0], dict)
        and call.args[0].get("type") == "player_reaction"
    ]


def _acks(ws: AsyncMock) -> list[dict]:
    return [
        call.args[0]
        for call in ws.send_json.call_args_list
        if call.args
        and isinstance(call.args[0], dict)
        and call.args[0].get("type") == "reaction_ack"
    ]


async def _react(handler, gs, ws, emoji="🔥"):
    await handle_reaction(handler, ws, {"type": "reaction", "emoji": emoji}, gs)


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


class TestWhoMayReactDuringPlaying:
    @pytest.mark.asyncio
    async def test_player_who_has_not_submitted_is_ignored(self):
        handler, gs, ws, _clock = await _playing_game()
        await _react(handler, gs, ws["Alice"])
        assert _broadcast_emojis(handler) == []
        # Silence is right here: the bar is not even on their screen, so there
        # is no tap to explain away.
        assert _acks(ws["Alice"]) == []

    @pytest.mark.asyncio
    async def test_player_who_submitted_may_react(self):
        handler, gs, ws, _clock = await _playing_game()
        gs.get_player("Alice").submitted = True
        await _react(handler, gs, ws["Alice"], "😂")
        assert _broadcast_emojis(handler) == ["😂"]

    @pytest.mark.asyncio
    async def test_eliminated_player_may_react(self):
        # #827 has shown eliminated players the reaction bar during PLAYING for
        # a long time; the REVEAL-only gate dropped every tap on it.
        handler, gs, ws, _clock = await _playing_game()
        gs.get_player("Alice").eliminated = True
        await _react(handler, gs, ws["Alice"], "👏")
        assert _broadcast_emojis(handler) == ["👏"]

    @pytest.mark.asyncio
    async def test_playoff_spectator_may_react(self):
        handler, gs, ws, _clock = await _playing_game()
        gs.get_player("Alice").playoff_spectator = True
        await _react(handler, gs, ws["Alice"], "🤔")
        assert _broadcast_emojis(handler) == ["🤔"]

    @pytest.mark.asyncio
    async def test_reveal_still_open_to_everyone(self):
        handler, gs, ws, _clock = await _playing_game()
        gs.phase = GamePhase.REVEAL
        await _react(handler, gs, ws["Alice"], "😱")
        assert _broadcast_emojis(handler) == ["😱"]

    @pytest.mark.asyncio
    async def test_lobby_and_end_stay_closed(self):
        handler, gs, ws, _clock = await _playing_game()
        gs.get_player("Alice").submitted = True
        for phase in (GamePhase.LOBBY, GamePhase.PAUSED, GamePhase.END):
            gs.phase = phase
            await _react(handler, gs, ws["Alice"])
        assert _broadcast_emojis(handler) == []

    @pytest.mark.asyncio
    async def test_unknown_emoji_rejected(self):
        handler, gs, ws, _clock = await _playing_game()
        gs.get_player("Alice").submitted = True
        await _react(handler, gs, ws["Alice"], "🍕")
        assert _broadcast_emojis(handler) == []


# ---------------------------------------------------------------------------
# The throttle, seen through the handler
# ---------------------------------------------------------------------------


class TestThrottleThroughTheHandler:
    @pytest.mark.asyncio
    async def test_burst_reaches_the_room_once(self):
        handler, gs, ws, _clock = await _playing_game()
        gs.get_player("Alice").submitted = True
        for _ in range(10):
            await _react(handler, gs, ws["Alice"])
        assert _broadcast_emojis(handler) == ["🔥"]

    @pytest.mark.asyncio
    async def test_second_reaction_lands_after_the_interval(self):
        handler, gs, ws, clock = await _playing_game()
        gs.get_player("Alice").submitted = True
        await _react(handler, gs, ws["Alice"], "🔥")
        clock.advance(REACTION_THROTTLE_SECONDS)
        await _react(handler, gs, ws["Alice"], "👏")
        assert _broadcast_emojis(handler) == ["🔥", "👏"]

    @pytest.mark.asyncio
    async def test_one_players_cooldown_does_not_silence_another(self):
        handler, gs, ws, _clock = await _playing_game()
        gs.get_player("Alice").submitted = True
        gs.get_player("Bob").submitted = True
        await _react(handler, gs, ws["Alice"], "🔥")
        await _react(handler, gs, ws["Alice"], "😂")
        await _react(handler, gs, ws["Bob"], "😱")
        assert _broadcast_emojis(handler) == ["🔥", "😱"]


# ---------------------------------------------------------------------------
# The ack — what the phone draws its cooldown bar from
# ---------------------------------------------------------------------------


class TestReactionAck:
    @pytest.mark.asyncio
    async def test_accepted_reaction_acks_the_full_interval(self):
        handler, gs, ws, _clock = await _playing_game()
        gs.get_player("Alice").submitted = True
        await _react(handler, gs, ws["Alice"])
        assert _acks(ws["Alice"]) == [
            {
                "type": "reaction_ack",
                "retry_after": REACTION_THROTTLE_SECONDS,
                "throttled": False,
            }
        ]

    @pytest.mark.asyncio
    async def test_throttled_reaction_acks_the_remaining_time(self):
        handler, gs, ws, clock = await _playing_game()
        gs.get_player("Alice").submitted = True
        await _react(handler, gs, ws["Alice"])
        clock.advance(3.0)
        await _react(handler, gs, ws["Alice"])
        second = _acks(ws["Alice"])[1]
        assert second["throttled"] is True
        assert second["retry_after"] == pytest.approx(REACTION_THROTTLE_SECONDS - 3.0)

    @pytest.mark.asyncio
    async def test_the_ack_goes_only_to_the_sender(self):
        handler, gs, ws, _clock = await _playing_game()
        gs.get_player("Alice").submitted = True
        await _react(handler, gs, ws["Alice"])
        assert _acks(ws["Bob"]) == []
