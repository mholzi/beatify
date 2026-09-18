"""#2876 — an admin socket coming back must not lift a host pause.

Phones drop the WebSocket on every screen lock, and the client sends
``reconnect`` on every socket open. ``handle_reconnect`` and the own-admin
reclaim branch of ``handle_join`` resumed *any* PAUSED game, so a host who
paused for the pizza and locked the phone came back to a round already
running out with nobody at the table. A ``media_player_error`` pause was
"resumed" straight into the broken speaker.

Only the pause the server took because the admin socket went away
(``admin_disconnected``) is lifted by the admin returning. Everything else
waits for the explicit ``resume_game`` admin action.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.beatify.const import (
    ADMIN_DISCONNECT_PAUSE_REASON,
    HOST_PAUSE_REASON,
    HOST_PAUSE_REASON_FOOD,
)
from custom_components.beatify.game.state import GamePhase
from tests.conftest import make_songs
from tests.unit.test_websocket import _make_handler_and_game, _make_ws

_AUTH = "custom_components.beatify.server.ws_handlers.lifecycle._is_ha_authenticated"


async def _paused_game(reason: str):
    """A game mid-round, paused for ``reason``, with the host's socket gone."""
    handler, game_state, host_ws = _make_handler_and_game(songs=make_songs(5))
    game_state.add_player("Host", host_ws)
    game_state.set_admin("Host")
    game_state.phase = GamePhase.PLAYING
    game_state.current_song = {"year": 1984, "title": "Take On Me", "artist": "a-ha"}

    speaker = MagicMock()
    speaker.stop = AsyncMock()
    speaker.play = AsyncMock()
    speaker.get_playback_state.return_value = "playing"
    game_state._media_player_service = speaker

    handler.broadcast = AsyncMock()
    handler.broadcast_state = AsyncMock()

    assert await game_state.pause_game(reason)
    host = game_state.get_player("Host")
    host.connected = False
    host.ws = None
    return handler, game_state


async def _reconnect_by_session(handler, game_state) -> None:
    session_id = game_state.get_player("Host").session_id
    await handler._handle_message(
        _make_ws(), {"type": "reconnect", "session_id": session_id}
    )


async def _reclaim_by_join(handler) -> None:
    with patch(_AUTH, return_value=True):
        await handler._handle_message(
            _make_ws(),
            {"type": "join", "name": "Host", "is_admin": True, "ha_token": "t"},
        )


class TestReconnectDoesNotLiftOtherPauses:
    @pytest.mark.parametrize(
        "reason", [HOST_PAUSE_REASON, HOST_PAUSE_REASON_FOOD, "media_player_error"]
    )
    async def test_session_reconnect_keeps_the_pause(self, reason):
        handler, game_state = await _paused_game(reason)

        await _reconnect_by_session(handler, game_state)

        assert game_state.get_player("Host").connected is True
        assert game_state.phase == GamePhase.PAUSED
        assert game_state.pause_reason == reason

    @pytest.mark.parametrize("reason", [HOST_PAUSE_REASON, "media_player_error"])
    async def test_join_reclaim_keeps_the_pause(self, reason):
        """Reloading the admin page goes through handle_join, not reconnect."""
        handler, game_state = await _paused_game(reason)

        await _reclaim_by_join(handler)

        assert game_state.get_player("Host").connected is True
        assert game_state.phase == GamePhase.PAUSED
        assert game_state.pause_reason == reason


class TestAdminDisconnectPauseStillLifts:
    async def test_session_reconnect_resumes(self):
        handler, game_state = await _paused_game(ADMIN_DISCONNECT_PAUSE_REASON)

        await _reconnect_by_session(handler, game_state)

        assert game_state.phase == GamePhase.PLAYING
        assert game_state.pause_reason is None

    async def test_join_reclaim_resumes(self):
        handler, game_state = await _paused_game(ADMIN_DISCONNECT_PAUSE_REASON)

        await _reclaim_by_join(handler)

        assert game_state.phase == GamePhase.PLAYING
        assert game_state.pause_reason is None
