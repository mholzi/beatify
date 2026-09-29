"""#3081 — a second admin page must not strip the first one of its admin rights.

The handler kept one slot for the admin spectator socket. ``admin_connect``
overwrote it, and the disconnect path set it to ``None``. So when the host
opened the admin page on a second tab or device and closed it again, the first
admin page — still open, never reconnecting — was no longer recognised: every
``admin`` action, ``next_round`` included, came back as ``NOT_ADMIN`` and the
page showed a dead button.

Admin spectator sockets are now tracked as a set. A disconnect forgets only the
socket that closed. Who may become an admin socket is unchanged: only an
``admin_connect`` carrying a valid Home Assistant token registers one.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

from custom_components.beatify.const import ERR_NOT_ADMIN, ERR_UNAUTHORIZED
from custom_components.beatify.game.state import GamePhase
from custom_components.beatify.server.ws_handlers import admin_rematch_game
from tests.unit.test_websocket import _make_handler_and_game, _make_ws


async def _admin_connect(handler, ws) -> None:
    # The mock hass' auth manager accepts any string as an HA access token.
    await handler._handle_message(
        ws, {"type": "admin_connect", "ha_token": "valid-ha-token"}
    )


def _errors(ws) -> list[dict]:
    return [
        call.args[0]
        for call in ws.send_json.call_args_list
        if call.args
        and isinstance(call.args[0], dict)
        and call.args[0].get("type") == "error"
    ]


def _in_reveal(game_state) -> None:
    game_state.phase = GamePhase.REVEAL
    game_state.last_round = False
    game_state.resolve_title_artist_if_pending = AsyncMock()
    game_state.start_round = AsyncMock(return_value=True)


class TestSecondAdminPageLeaves:
    async def test_first_admin_page_can_still_advance_the_round(self):
        """The regression from the issue: connect B, close B, next_round on A."""
        handler, game_state, page_a = _make_handler_and_game()
        page_b = _make_ws()
        handler.connections.update({page_a, page_b})
        handler.broadcast_state = AsyncMock()

        await _admin_connect(handler, page_a)
        await _admin_connect(handler, page_b)
        handler.connections.discard(page_b)
        await handler._handle_disconnect(page_b)

        _in_reveal(game_state)
        page_a.send_json.reset_mock()
        await handler._handle_message(page_a, {"type": "admin", "action": "next_round"})

        assert _errors(page_a) == []
        game_state.start_round.assert_awaited_once()

    async def test_first_admin_page_is_still_admin_while_both_are_open(self):
        handler, game_state, page_a = _make_handler_and_game()
        page_b = _make_ws()
        handler.broadcast_state = AsyncMock()

        await _admin_connect(handler, page_a)
        await _admin_connect(handler, page_b)

        assert handler.is_admin_socket(page_a)
        assert handler.is_admin_socket(page_b)

        _in_reveal(game_state)
        page_a.send_json.reset_mock()
        await handler._handle_message(page_a, {"type": "admin", "action": "next_round"})

        assert _errors(page_a) == []
        game_state.start_round.assert_awaited_once()

    async def test_disconnect_forgets_only_the_closed_socket(self):
        handler, _game_state, page_a = _make_handler_and_game()
        page_b = _make_ws()

        await _admin_connect(handler, page_a)
        await _admin_connect(handler, page_b)
        await handler._handle_disconnect(page_b)

        assert handler.is_admin_socket(page_a)
        assert not handler.is_admin_socket(page_b)
        assert handler.admin_sockets == [page_a]

    async def test_closed_second_page_cannot_act_as_admin(self):
        handler, game_state, page_a = _make_handler_and_game()
        page_b = _make_ws()

        await _admin_connect(handler, page_a)
        await _admin_connect(handler, page_b)
        await handler._handle_disconnect(page_b)

        _in_reveal(game_state)
        page_b.send_json.reset_mock()
        await handler._handle_message(page_b, {"type": "admin", "action": "next_round"})

        assert [e["code"] for e in _errors(page_b)] == [ERR_NOT_ADMIN]
        game_state.start_round.assert_not_awaited()

    async def test_every_admin_page_gets_the_unredacted_broadcast(self):
        """Both open admin pages are spectators; players still get redacted."""
        handler, game_state, page_a = _make_handler_and_game()
        page_b = _make_ws()
        player_ws = _make_ws()
        game_state.add_player("Guest", player_ws)
        handler.connections.update({page_a, page_b, player_ws})
        await _admin_connect(handler, page_a)
        await _admin_connect(handler, page_b)

        sent: dict = {}

        async def _capture(ws, payload):
            sent[ws] = payload

        handler._safe_send = _capture
        handler._redact_for_player = MagicMock(return_value={"redacted": True})
        await handler.broadcast({"type": "state", "secret": "answer"})

        assert json.loads(sent[page_a]) == {"type": "state", "secret": "answer"}
        assert json.loads(sent[page_b]) == {"type": "state", "secret": "answer"}
        assert json.loads(sent[player_ws]) == {"redacted": True}


class TestAuthorizationUnchanged:
    async def test_single_admin_page_still_works(self):
        handler, game_state, page_a = _make_handler_and_game()
        handler.broadcast_state = AsyncMock()
        await _admin_connect(handler, page_a)

        _in_reveal(game_state)
        page_a.send_json.reset_mock()
        await handler._handle_message(page_a, {"type": "admin", "action": "next_round"})

        assert _errors(page_a) == []
        game_state.start_round.assert_awaited_once()

    async def test_single_admin_page_disconnect_clears_it(self):
        handler, _game_state, page_a = _make_handler_and_game()
        await _admin_connect(handler, page_a)

        await handler._handle_disconnect(page_a)

        assert handler.admin_sockets == []
        assert handler.admin_ws is None

    async def test_rejected_admin_connect_does_not_register(self):
        handler, _game_state, page_a = _make_handler_and_game()
        stranger = _make_ws()
        await _admin_connect(handler, page_a)
        handler.hass.auth.async_validate_access_token = MagicMock(return_value=None)

        await _admin_connect(handler, stranger)

        assert [e["code"] for e in _errors(stranger)] == [ERR_UNAUTHORIZED]
        assert not handler.is_admin_socket(stranger)
        assert handler.admin_sockets == [page_a]

    async def test_plain_socket_is_still_refused_next_to_admin_pages(self):
        handler, game_state, page_a = _make_handler_and_game()
        stranger = _make_ws()
        await _admin_connect(handler, page_a)

        _in_reveal(game_state)
        await handler._handle_message(
            stranger, {"type": "admin", "action": "next_round"}
        )

        assert [e["code"] for e in _errors(stranger)] == [ERR_NOT_ADMIN]
        game_state.start_round.assert_not_awaited()

    async def test_game_teardown_forgets_every_admin_page(self):
        handler, game_state, page_a = _make_handler_and_game()
        page_b = _make_ws()
        await _admin_connect(handler, page_a)
        await _admin_connect(handler, page_b)

        game_state._reset_game_internals()

        assert handler.admin_sockets == []


class TestRematchKeepsEveryAdminPage:
    async def test_phone_rematch_restores_both_open_admin_pages(self):
        handler, game_state, phone_ws = _make_handler_and_game()
        game_state.add_player("Host", phone_ws)
        game_state.set_admin("Host")
        game_state.phase = GamePhase.END
        page_a, page_b = _make_ws(), _make_ws()
        await _admin_connect(handler, page_a)
        await _admin_connect(handler, page_b)

        handler.cleanup_game_tasks = AsyncMock()
        game_state.announce_rematch = AsyncMock()
        handler.broadcast = AsyncMock()
        handler.broadcast_state = AsyncMock()

        await admin_rematch_game(
            handler, phone_ws, {"action": "rematch_game"}, game_state
        )

        assert handler.admin_sockets == [page_a, page_b]
        assert not handler.is_admin_socket(phone_ws)
        for page in (page_a, page_b):
            updates = [
                c.args[0]
                for c in page.send_json.call_args_list
                if c.args and c.args[0].get("type") == "admin_token_update"
            ]
            assert updates, "every admin page gets the new admin_token"
