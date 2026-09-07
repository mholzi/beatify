"""#2718 — the ``kick_player`` contract the host's lobby now depends on again.

``admin_kick_player`` has been registered since #659 (April), but PR #1613
(26 June) deleted the only UI that ever sent it, along with the flat lobby the
button lived in. Nothing has exercised the handler from a client since. #2718
puts a tap target back on the host's lobby tiles, so these tests pin the four
rules the new client assumes when it decides which tile is a button at all:

* lobby phase only,
* the admin can never be removed,
* a *connected* player can never be removed,
* an away player is removed for good — name index, session map and player
  record — and the room is told.

The client mirrors the middle two by rendering only away, non-host guests as
buttons (``buildHomePlayerTiles``). If a rule here changes, that rendering is
wrong in the same commit.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from custom_components.beatify.const import DOMAIN, ERR_INVALID_ACTION
from custom_components.beatify.game.state import GamePhase, GameState
from custom_components.beatify.server.websocket import BeatifyWebSocketHandler
from tests.conftest import make_game_state, make_songs


def _ws() -> AsyncMock:
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    ws.closed = False
    ws.close = AsyncMock()
    return ws


def _handler_and_game() -> tuple[BeatifyWebSocketHandler, GameState]:
    mock_hass = MagicMock()
    game_state = make_game_state()
    game_state.create_game(
        playlists=["test.json"],
        songs=make_songs(5),
        media_player="media_player.test",
        base_url="http://localhost:8123",
    )
    mock_hass.data = {DOMAIN: {"game": game_state}}
    handler = BeatifyWebSocketHandler(mock_hass)
    handler.debounced_broadcast_state = AsyncMock()
    handler.broadcast_state = AsyncMock()
    handler.broadcast = AsyncMock()
    return handler, game_state


def _seat_host(handler: BeatifyWebSocketHandler, game_state: GameState) -> AsyncMock:
    """Seat the host and register their socket as the admin spectator WS."""
    ws = _ws()
    game_state.add_player("Markus", ws)
    game_state.set_admin("Markus")
    handler.admin_ws = ws
    return ws


def _seat_guest(game_state: GameState, name: str, *, away: bool = False) -> AsyncMock:
    ws = _ws()
    game_state.add_player(name, ws)
    if away:
        # Exactly what BeatifyWebSocketHandler._handle_disconnect does: the
        # session stays in the lobby with connected=False. That flag is what
        # the state broadcast ships as ``connected`` and what the host's tile
        # grid paints as "away".
        player = game_state.get_player(name)
        player.connected = False
        player.ws = None
    return ws


async def _kick(handler, admin_ws, name):
    await handler._handle_message(
        admin_ws, {"type": "admin", "action": "kick_player", "player_name": name}
    )


def _last_error(ws: AsyncMock) -> dict | None:
    for call in reversed(ws.send_json.call_args_list):
        msg = call[0][0]
        if msg.get("type") == "error":
            return msg
    return None


class TestKickRemovesAnAwayGuest:
    async def test_away_guest_is_gone_and_the_room_is_told(self):
        handler, game_state = _handler_and_game()
        admin_ws = _seat_host(handler, game_state)
        _seat_guest(game_state, "Kirsten", away=True)
        assert game_state.get_player("Kirsten") is not None

        await _kick(handler, admin_ws, "Kirsten")

        assert game_state.get_player("Kirsten") is None
        assert "Kirsten" not in [p.name for p in game_state.players.values()]
        # The slot is genuinely free: the freed seat is what #2718 is about.
        handler.broadcast_state.assert_awaited()
        assert _last_error(admin_ws) is None

    async def test_the_name_is_matched_case_insensitively(self):
        # The client sends back the display name it rendered; F6 made every
        # registry lookup case-insensitive, so a tile is not name-fragile.
        handler, game_state = _handler_and_game()
        admin_ws = _seat_host(handler, game_state)
        _seat_guest(game_state, "Kirsten", away=True)

        await _kick(handler, admin_ws, "kirsten")

        assert game_state.get_player("Kirsten") is None

    async def test_the_freed_name_can_join_again(self):
        # "They can scan the QR code again any time" is in the confirm modal,
        # so it had better be true.
        handler, game_state = _handler_and_game()
        admin_ws = _seat_host(handler, game_state)
        _seat_guest(game_state, "Kirsten", away=True)

        await _kick(handler, admin_ws, "Kirsten")
        game_state.add_player("Kirsten", _ws())

        rejoined = game_state.get_player("Kirsten")
        assert rejoined is not None
        assert rejoined.connected is True
        assert rejoined.is_admin is False


class TestKickIsRefused:
    async def test_a_connected_guest_is_refused(self):
        # The reason the client only offers the button on away tiles.
        handler, game_state = _handler_and_game()
        admin_ws = _seat_host(handler, game_state)
        _seat_guest(game_state, "Jonas")

        await _kick(handler, admin_ws, "Jonas")

        assert game_state.get_player("Jonas") is not None
        err = _last_error(admin_ws)
        assert err is not None
        assert err["code"] == ERR_INVALID_ACTION

    async def test_the_admin_is_refused_even_when_away(self):
        handler, game_state = _handler_and_game()
        admin_ws = _seat_host(handler, game_state)
        host = game_state.get_player("Markus")
        host.connected = False
        host.ws = None

        await _kick(handler, admin_ws, "Markus")

        assert game_state.get_player("Markus") is not None
        err = _last_error(admin_ws)
        assert err is not None
        assert err["code"] == ERR_INVALID_ACTION

    async def test_an_unknown_name_is_refused_without_touching_anybody(self):
        handler, game_state = _handler_and_game()
        admin_ws = _seat_host(handler, game_state)
        _seat_guest(game_state, "Kirsten", away=True)

        await _kick(handler, admin_ws, "Nobody")

        assert game_state.get_player("Kirsten") is not None
        err = _last_error(admin_ws)
        assert err is not None
        assert err["code"] == ERR_INVALID_ACTION

    async def test_an_empty_name_is_a_no_op(self):
        handler, game_state = _handler_and_game()
        admin_ws = _seat_host(handler, game_state)
        _seat_guest(game_state, "Kirsten", away=True)

        await _kick(handler, admin_ws, "")

        assert game_state.get_player("Kirsten") is not None
        assert _last_error(admin_ws) is None

    async def test_outside_the_lobby_it_is_refused(self):
        # Sudden Death is where an away survivor hurts most, but the handler
        # only ever operated in LOBBY — the tiles are a lobby surface, and the
        # client must not grow a kick button on the in-game screens expecting
        # this to work.
        handler, game_state = _handler_and_game()
        admin_ws = _seat_host(handler, game_state)
        _seat_guest(game_state, "Kirsten", away=True)
        game_state.phase = GamePhase.PLAYING

        await _kick(handler, admin_ws, "Kirsten")

        assert game_state.get_player("Kirsten") is not None
        err = _last_error(admin_ws)
        assert err is not None
        assert err["code"] == ERR_INVALID_ACTION

    async def test_a_guest_cannot_kick_another_guest(self):
        handler, game_state = _handler_and_game()
        _seat_host(handler, game_state)
        guest_ws = _seat_guest(game_state, "Jonas")
        _seat_guest(game_state, "Kirsten", away=True)

        await _kick(handler, guest_ws, "Kirsten")

        assert game_state.get_player("Kirsten") is not None
        err = _last_error(guest_ws)
        assert err is not None
        assert err["code"] != ERR_INVALID_ACTION  # NOT_ADMIN, refused earlier
