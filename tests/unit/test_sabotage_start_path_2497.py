"""#2497 — the sabotage grant and the minimum-player floor on the real paths.

Both used to live in ``GameState.start_game()``, which no production code
calls: the websocket admin handler and the REST start view both call
``start_round()`` directly, and the LOBBY -> PLAYING flip happens inside
``_initialize_round``. So sabotage tokens were never handed out in a real game
and a game could be started with a single player, while the unit tests that
drove ``start_game()`` directly kept passing.

These tests deliberately drive the paths a host actually uses.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from custom_components.beatify.const import DOMAIN, MIN_PLAYERS
from custom_components.beatify.game.state import GamePhase
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


def _handler_game(**create_kwargs):
    mock_hass = MagicMock()
    gs = make_game_state()
    gs.create_game(
        playlists=["t.json"],
        songs=make_songs(5),
        media_player="media_player.x",
        base_url="http://h",
        **create_kwargs,
    )
    gs._media_player_service = _stub_media_service()
    gs.platform = "music_assistant"
    mock_hass.data = {DOMAIN: {"game": gs}}
    handler = BeatifyWebSocketHandler(mock_hass)
    handler.broadcast_state = AsyncMock()
    handler.broadcast = AsyncMock()
    handler.debounced_broadcast_state = AsyncMock()
    return handler, gs


def _ws() -> AsyncMock:
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    ws.closed = False
    ws.close = AsyncMock()
    return ws


def _join(gs, names):
    sockets = {}
    for name in names:
        ws = _ws()
        gs.add_player(name, ws)
        gs.get_player(name).connected = True
        sockets[name] = ws
    return sockets


class TestSabotageGrantOnTheRealStartPath:
    async def test_start_round_hands_out_tokens(self):
        """The path the host actually takes must grant the tokens."""
        _, gs = _handler_game(sabotage_enabled=True)
        _join(gs, ["Alice", "Bob"])
        assert gs.get_player("Alice").sabotage_available is False

        await gs.start_round()

        assert gs.phase == GamePhase.PLAYING
        assert gs.get_player("Alice").sabotage_available is True
        assert gs.get_player("Bob").sabotage_available is True

    async def test_no_tokens_when_the_setting_is_off(self):
        _, gs = _handler_game(sabotage_enabled=False)
        _join(gs, ["Alice", "Bob"])

        await gs.start_round()

        assert gs.get_player("Alice").sabotage_available is False
        assert gs.get_player("Bob").sabotage_available is False

    async def test_a_spent_token_is_not_handed_back_next_round(self):
        """The grant belongs to the LOBBY transition, not to every round."""
        _, gs = _handler_game(sabotage_enabled=True)
        _join(gs, ["Alice", "Bob"])
        await gs.start_round()

        gs.get_player("Alice").sabotage_available = False  # as if spent
        await gs.end_round()
        await gs.start_round()

        assert gs.get_player("Alice").sabotage_available is False
        assert gs.get_player("Bob").sabotage_available is True


class TestMinimumPlayersOnTheRealStartPath:
    async def test_websocket_start_refuses_a_single_player(self):
        handler, gs = _handler_game()
        sockets = _join(gs, ["Alice"])
        ws = sockets["Alice"]
        gs.set_admin("Alice")
        ws.send_json.reset_mock()

        await handler._handle_message(ws, {"type": "admin", "action": "start_game"})

        sent = [c.args[0] for c in ws.send_json.call_args_list]
        assert any(m.get("type") == "error" for m in sent), sent
        assert gs.phase == GamePhase.LOBBY

    async def test_websocket_start_allows_the_minimum(self):
        handler, gs = _handler_game()
        names = [f"P{i}" for i in range(MIN_PLAYERS)]
        sockets = _join(gs, names)
        gs.set_admin(names[0])
        ws = sockets[names[0]]

        await handler._handle_message(ws, {"type": "admin", "action": "start_game"})

        assert gs.phase == GamePhase.PLAYING
