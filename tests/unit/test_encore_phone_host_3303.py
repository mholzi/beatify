"""#3303 — the encore offer (#2503) reaches the host who plays on their phone.

``encore_available`` / ``encore_rounds`` are admin-only, so the host's phone —
a player socket — never saw them and could only offer a rematch, which resets
the scores. The host's own player socket now gets a third payload variant: the
redacted player copy plus those two keys. Never the admin copy (it carries the
answer), and guests keep the plain redacted copy.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

from custom_components.beatify.const import ERR_NOT_ADMIN
from custom_components.beatify.server import serializers
from custom_components.beatify.server.serializers import (
    ADMIN_ONLY_KEYS,
    redact_state_for_player,
)
from custom_components.beatify.server.ws_handlers import _send_state_to
from tests.unit.test_websocket import _make_handler_and_game, _make_ws

_STATE = {
    "type": "state",
    "phase": "REVEAL",
    "total_rounds": 10,
    "admin_song": {"year": 1985},
    "encore_available": True,
    "encore_rounds": 5,
}


def _game_with_host_and_guest():
    handler, game_state, admin_page = _make_handler_and_game()
    host_ws, guest_ws = _make_ws(), _make_ws()
    game_state.add_player("Host", host_ws)
    game_state.add_player("Guest", guest_ws)
    game_state.get_player_by_ws(host_ws).is_admin = True
    game_state.get_player_by_ws(guest_ws).is_admin = False
    handler.connections.update({host_ws, guest_ws})
    return handler, game_state, admin_page, host_ws, guest_ws


async def _broadcast(handler, message) -> dict:
    sent: dict = {}

    async def _capture(ws, payload):
        sent[ws] = json.loads(payload)

    handler._safe_send = _capture
    await handler.broadcast(message)
    return sent


class TestHostPlayerPayload:
    def test_host_keys_are_admin_only_keys(self):
        host_keys = serializers.HOST_PLAYER_KEYS
        assert host_keys == {"encore_available", "encore_rounds"}
        assert host_keys <= ADMIN_ONLY_KEYS

    def test_host_copy_adds_only_the_encore_keys(self):
        player = redact_state_for_player(_STATE)
        host = serializers.state_for_host_player(_STATE, player)
        assert host["encore_available"] is True
        assert host["encore_rounds"] == 5
        assert "admin_song" not in host
        assert set(host) - set(player) == serializers.HOST_PLAYER_KEYS

    def test_no_encore_keys_returns_the_player_copy_itself(self):
        msg = {"type": "state", "phase": "REVEAL", "admin_song": {"year": 1}}
        player = redact_state_for_player(msg)
        assert serializers.state_for_host_player(msg, player) is player


class TestBroadcast:
    async def test_host_phone_gets_encore_keys_but_not_the_answer(self):
        handler, _gs, _admin, host_ws, guest_ws = _game_with_host_and_guest()
        sent = await _broadcast(handler, dict(_STATE))

        assert sent[host_ws]["encore_available"] is True
        assert sent[host_ws]["encore_rounds"] == 5
        assert "admin_song" not in sent[host_ws]

    async def test_guest_never_gets_encore_keys(self):
        handler, _gs, _admin, _host_ws, guest_ws = _game_with_host_and_guest()
        sent = await _broadcast(handler, dict(_STATE))

        assert "encore_available" not in sent[guest_ws]
        assert "encore_rounds" not in sent[guest_ws]
        assert "admin_song" not in sent[guest_ws]

    async def test_unauthenticated_admin_claim_gets_nothing_extra(self):
        """A player whose admin claim was refused is a guest for this purpose."""
        handler, game_state, _admin, host_ws, _guest = _game_with_host_and_guest()
        game_state.get_player_by_ws(host_ws).is_admin = False
        sent = await _broadcast(handler, dict(_STATE))

        assert "encore_available" not in sent[host_ws]

    async def test_admin_page_still_gets_the_full_copy(self):
        handler, _gs, admin_page, host_ws, _guest = _game_with_host_and_guest()
        await handler._handle_message(
            admin_page, {"type": "admin_connect", "ha_token": "valid-ha-token"}
        )
        sent = await _broadcast(handler, dict(_STATE))

        assert sent[admin_page]["admin_song"] == {"year": 1985}
        assert sent[admin_page]["encore_available"] is True


class TestSendStateTo:
    async def test_direct_send_to_host_carries_encore_keys(self):
        handler, game_state, _admin, host_ws, _guest = _game_with_host_and_guest()
        await _send_state_to(handler, host_ws, dict(_STATE), game_state)

        payload = host_ws.send_json.call_args.args[0]
        assert payload["encore_available"] is True
        assert "admin_song" not in payload

    async def test_direct_send_to_guest_does_not(self):
        handler, game_state, _admin, _host, guest_ws = _game_with_host_and_guest()
        await _send_state_to(handler, guest_ws, dict(_STATE), game_state)

        payload = guest_ws.send_json.call_args.args[0]
        assert "encore_available" not in payload


class TestGuestCannotExtend:
    async def test_guest_extend_rounds_is_refused(self):
        handler, game_state, _admin, _host, guest_ws = _game_with_host_and_guest()
        game_state.extend_rounds = AsyncMock()
        guest_ws.send_json.reset_mock()

        await handler._handle_message(
            guest_ws, {"type": "admin", "action": "extend_rounds"}
        )

        codes = [
            c.args[0].get("code")
            for c in guest_ws.send_json.call_args_list
            if c.args and isinstance(c.args[0], dict)
        ]
        assert ERR_NOT_ADMIN in codes
        game_state.extend_rounds.assert_not_called()
