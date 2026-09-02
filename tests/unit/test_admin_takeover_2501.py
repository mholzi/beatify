"""#2501 (security) — the host's session must not be reachable by name.

``add_player`` keeps a deprecated case-insensitive name-based reconnect
fallback for clients that rejoin without a valid session_id. It re-attaches a
new socket to the existing ``PlayerSession`` and keeps its ``is_admin`` flag,
and every admin action is gated on exactly that flag. So a join that carried
the host's display name — which is on the TV for the whole room to read — and
*no* ``is_admin`` field inherited the host role without ever meeting the #998
token check, because nothing was declared for the check to guard.

The fallback stays open for ordinary players and closes for a host session.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.beatify.const import DOMAIN, ERR_UNAUTHORIZED
from custom_components.beatify.game.state import GameState
from custom_components.beatify.server.websocket import BeatifyWebSocketHandler
from tests.conftest import make_game_state, make_songs

_AUTH = "custom_components.beatify.server.ws_handlers.lifecycle._is_ha_authenticated"


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


def _seat_host(game_state: GameState, name: str = "Host") -> None:
    """Seat a host and drop their connection, as a network blip would."""
    game_state.add_player(name, _ws())
    game_state.set_admin(name)
    player = game_state.get_player(name)
    player.connected = False
    player.ws = None


class TestNameBasedTakeoverIsRefused:
    async def test_join_by_host_name_without_the_flag_is_refused(self):
        handler, game_state = _handler_and_game()
        _seat_host(game_state)
        host_session_id = game_state.get_player("Host").session_id

        attacker = _ws()
        await handler._handle_message(attacker, {"type": "join", "name": "Host"})

        msg = attacker.send_json.call_args[0][0]
        assert msg["type"] == "error"
        assert msg["code"] == ERR_UNAUTHORIZED

        # The attacker holds neither the socket nor the session secret.
        host = game_state.get_player("Host")
        assert host.is_admin is True
        assert host.connected is False
        assert host.ws is None
        assert host.session_id == host_session_id
        assert game_state.get_player_by_ws(attacker) is None

    async def test_a_stale_socket_does_not_open_the_door_either(self):
        """#646 lets a rejoin through when the old socket is closed but the
        connected flag has not been cleared yet. That branch is downstream of
        the guard, so it must not become the way around it."""
        handler, game_state = _handler_and_game()
        game_state.add_player("Host", _ws())
        game_state.set_admin("Host")
        game_state.get_player("Host").ws.closed = True  # connected still True

        attacker = _ws()
        await handler._handle_message(attacker, {"type": "join", "name": "Host"})

        assert attacker.send_json.call_args[0][0]["code"] == ERR_UNAUTHORIZED
        assert game_state.get_player_by_ws(attacker) is None

    async def test_an_unauthenticated_admin_claim_is_still_refused(self):
        """The declared claim was already gated by #998 — it stays gated, and
        the refusal must not cost the host their record (#1696)."""
        handler, game_state = _handler_and_game()
        _seat_host(game_state)
        game_state.get_player("Host").score = 4200

        attacker = _ws()
        await handler._handle_message(
            attacker, {"type": "join", "name": "Host", "is_admin": True}
        )

        assert attacker.send_json.call_args[0][0]["code"] == ERR_UNAUTHORIZED
        assert game_state.get_player("Host").score == 4200
        assert game_state.get_player("Host").is_admin is True


class TestTheDoorsThatMustStayOpen:
    async def test_an_ordinary_player_still_reconnects_by_name(self):
        """The fallback exists for old cookies and cleared storage. Closing it
        for everyone would strand players mid-game."""
        handler, game_state = _handler_and_game()
        game_state.add_player("Alice", _ws())
        alice = game_state.get_player("Alice")
        alice.score = 1500
        alice.connected = False
        alice.ws = None

        rejoin = _ws()
        await handler._handle_message(rejoin, {"type": "join", "name": "Alice"})

        sent = [c.args[0] for c in rejoin.send_json.call_args_list]
        assert not [m for m in sent if m.get("type") == "error"], sent
        assert game_state.get_player("Alice").connected is True
        assert game_state.get_player("Alice").score == 1500

    async def test_the_real_host_reclaims_with_a_verified_login(self):
        """With an HA login the name path is open again — that is the whole
        point: regaining the host role goes through the token check."""
        handler, game_state = _handler_and_game()
        _seat_host(game_state)

        host_again = _ws()
        with patch(_AUTH, return_value=True):
            await handler._handle_message(
                host_again,
                {"type": "join", "name": "Host", "is_admin": True, "ha_token": "t"},
            )

        sent = [c.args[0] for c in host_again.send_json.call_args_list]
        assert any(m.get("type") == "join_ack" for m in sent), sent
        host = game_state.get_player("Host")
        assert host.is_admin is True
        assert host.connected is True
        assert host.ws is host_again

    async def test_the_host_can_still_reconnect_by_session_id(self):
        """The authoritative path needs the secret from join_ack, so it is
        unaffected — and it is what a host's own browser actually uses."""
        handler, game_state = _handler_and_game()
        _seat_host(game_state)
        session_id = game_state.get_player("Host").session_id

        host_again = _ws()
        await handler._handle_message(
            host_again, {"type": "reconnect", "session_id": session_id}
        )

        assert game_state.get_player("Host").connected is True
        assert game_state.get_player("Host").is_admin is True
