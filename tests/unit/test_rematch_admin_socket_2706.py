"""#2706 — a rematch from the host's phone must not claim the admin socket.

``rematch_game`` is reachable from either admin-capable socket, and
``www/js/player-end.js`` sends it over the host's **participant** socket. The
handler used to assign ``handler.admin_ws = ws`` unconditionally, so after a
phone-initiated rematch the phone was the spectator admin: ``broadcast()`` sent
it the unredacted payload (the year answer, the fun fact, the library URI) for
the whole rematch, while the admin page — which sends ``admin_connect`` once on
open and has no ``rematch_started`` handler — was left with the redacted copy
and blank reveal fields.

The slot now only changes hands to a genuine spectator socket. A rematch tapped
on a phone keeps the spectator socket the rebuild just cleared, as long as it is
still open.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

from custom_components.beatify.game.state import GamePhase
from custom_components.beatify.server.ws_handlers import admin_rematch_game
from tests.conftest import make_songs
from tests.unit.test_websocket import _make_handler_and_game, _make_ws


async def _game_at_end_with_both_sockets():
    """END phase, host seated on a phone, admin page on the spectator socket."""
    handler, game_state, phone_ws = _make_handler_and_game(songs=make_songs(5))
    game_state.add_player("Host", phone_ws)
    game_state.set_admin("Host")
    game_state.add_player("Guest", _make_ws())
    game_state.phase = GamePhase.END

    admin_page_ws = _make_ws()
    handler.admin_ws = admin_page_ws

    handler.cleanup_game_tasks = AsyncMock()
    game_state.announce_rematch = AsyncMock()
    handler.broadcast = AsyncMock()
    handler.broadcast_state = AsyncMock()
    return handler, game_state, phone_ws, admin_page_ws


def _token_updates(ws) -> list[dict]:
    return [
        call.args[0]
        for call in ws.send_json.call_args_list
        if call.args and call.args[0].get("type") == "admin_token_update"
    ]


class TestPhoneInitiatedRematch:
    async def test_the_phone_does_not_take_over_the_admin_socket(self):
        (
            handler,
            game_state,
            phone_ws,
            admin_page_ws,
        ) = await _game_at_end_with_both_sockets()

        await admin_rematch_game(
            handler, phone_ws, {"action": "rematch_game"}, game_state
        )

        assert handler.admin_ws is admin_page_ws
        assert handler.admin_ws is not phone_ws

    async def test_the_phone_keeps_getting_the_redacted_broadcast(self):
        """The harm the socket swap caused, asserted at the broadcast."""
        (
            handler,
            game_state,
            phone_ws,
            admin_page_ws,
        ) = await _game_at_end_with_both_sockets()
        handler.connections.add(phone_ws)

        await admin_rematch_game(
            handler, phone_ws, {"action": "rematch_game"}, game_state
        )

        # The real broadcast, not the stub the fixture installs.
        handler.broadcast = type(handler).broadcast.__get__(handler)
        await handler.broadcast(
            {
                "type": "state",
                "phase": "PLAYING",
                "admin_song": {"year": 1984, "fun_fact": "the answer"},
            }
        )

        phone_payload = json.loads(phone_ws.send_str.call_args[0][0])
        admin_payload = json.loads(admin_page_ws.send_str.call_args[0][0])
        assert "admin_song" not in phone_payload
        assert admin_payload["admin_song"]["year"] == 1984

    async def test_the_admin_page_is_told_about_the_new_token(self):
        (
            handler,
            game_state,
            phone_ws,
            admin_page_ws,
        ) = await _game_at_end_with_both_sockets()

        await admin_rematch_game(
            handler, phone_ws, {"action": "rematch_game"}, game_state
        )

        for socket in (phone_ws, admin_page_ws):
            updates = _token_updates(socket)
            assert len(updates) == 1
            assert updates[0]["admin_token"] == game_state.admin_token
            assert updates[0]["game_id"] == game_state.game_id

    async def test_a_closed_spectator_socket_is_not_replaced_by_the_phone(self):
        (
            handler,
            game_state,
            phone_ws,
            admin_page_ws,
        ) = await _game_at_end_with_both_sockets()
        admin_page_ws.closed = True

        await admin_rematch_game(
            handler, phone_ws, {"action": "rematch_game"}, game_state
        )

        # Nothing to restore, but the phone still must not inherit the slot.
        assert handler.admin_ws is None


class TestSpectatorInitiatedRematch:
    async def test_the_admin_page_still_claims_the_slot(self):
        """The door that must stay open: rematch tapped on the admin page.

        ``rematch_game`` nulls ``handler.admin_ws`` via its reset callback, so
        the spectator socket has to re-claim it here or the TV/admin view loses
        the unredacted feed for the whole rematch.
        """
        (
            handler,
            game_state,
            _phone_ws,
            admin_page_ws,
        ) = await _game_at_end_with_both_sockets()

        await admin_rematch_game(
            handler, admin_page_ws, {"action": "rematch_game"}, game_state
        )

        assert handler.admin_ws is admin_page_ws
        assert len(_token_updates(admin_page_ws)) == 1
