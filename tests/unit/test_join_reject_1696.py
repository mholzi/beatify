"""Regression tests for #1696 — rejected admin claim must not delete a
pre-existing (reconnected) player's record.

Background: ``handle_join`` calls ``add_player`` *before* the admin-claim
checks. For a disconnected name that takes the reconnection path and re-attaches
the existing ``PlayerSession`` (score + session_id intact). Historically every
rejection branch then called ``remove_player(name)``, which deleted that whole
record — so an unauthenticated visitor could erase a real player's score by
sending ``{join, name:<disconnected player>, is_admin:true}``.

The fix consults the already-computed ``was_existing_player`` flag: reconnected
players get their reconnection reverted (``connected=False``, ``ws=None``) while
brand-new players are still removed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from custom_components.beatify.const import (
    DOMAIN,
    ERR_ADMIN_EXISTS,
    ERR_INVALID_ACTION,
    ERR_UNAUTHORIZED,
)
from custom_components.beatify.game.state import GamePhase, GameState
from custom_components.beatify.server.websocket import BeatifyWebSocketHandler
from tests.conftest import make_game_state, make_songs


def _make_handler_and_game() -> tuple[BeatifyWebSocketHandler, GameState, AsyncMock]:
    """Handler with a real GameState and a mock WebSocket (mirrors test_websocket)."""
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
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    ws.closed = False
    ws.close = AsyncMock()
    return handler, game_state, ws


def _make_ws() -> AsyncMock:
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    ws.closed = False
    ws.close = AsyncMock()
    return ws


def _disconnect(game_state: GameState, name: str) -> None:
    """Simulate a player whose WS dropped (reconnect path becomes eligible)."""
    player = game_state.get_player(name)
    player.connected = False
    player.ws = None


class TestRejectPreservesReconnectedPlayer:
    async def test_unauth_admin_claim_does_not_delete_disconnected_player(self):
        """(a) An unauthenticated is_admin join for a disconnected player must
        NOT delete that player's record — score + session_id survive, and the
        reconnection is reverted (connected stays False)."""
        handler, game_state, _ = _make_handler_and_game()

        # Existing player with a score, now disconnected.
        game_state.add_player("Alice", _make_ws())
        alice = game_state.get_player("Alice")
        alice.score = 4200
        original_session_id = alice.session_id
        _disconnect(game_state, "Alice")

        # Unauthenticated visitor claims admin under Alice's name (no ha_token).
        attacker_ws = _make_ws()
        await handler._handle_message(
            attacker_ws, {"type": "join", "name": "Alice", "is_admin": True}
        )

        # Rejection was sent.
        msg = attacker_ws.send_json.call_args[0][0]
        assert msg["type"] == "error"
        assert msg["code"] == ERR_UNAUTHORIZED

        # Record survived with score + session intact.
        preserved = game_state.get_player("Alice")
        assert preserved is not None
        assert preserved.score == 4200
        assert preserved.session_id == original_session_id
        assert preserved.is_admin is False
        # Reconnection reverted — the attacker's WS is not attached.
        assert preserved.connected is False
        assert preserved.ws is None

    async def test_admin_exists_reject_preserves_reconnected_player(self):
        """(b) A legitimate reconnect (valid token) that is rejected because an
        admin already exists must keep the player's state."""
        handler, game_state, _ = _make_handler_and_game()

        # A real admin already holds the room.
        game_state.add_player("Host", _make_ws())
        game_state.set_admin("Host")

        # Regular player with a score, now disconnected.
        game_state.add_player("Alice", _make_ws())
        game_state.get_player("Alice").score = 1500
        _disconnect(game_state, "Alice")

        # Alice reconnects but (mistakenly) asks for admin — valid token.
        new_ws = _make_ws()
        await handler._handle_message(
            new_ws,
            {"type": "join", "name": "Alice", "is_admin": True, "ha_token": "t"},
        )

        msg = new_ws.send_json.call_args[0][0]
        assert msg["type"] == "error"
        assert msg["code"] == ERR_ADMIN_EXISTS

        preserved = game_state.get_player("Alice")
        assert preserved is not None
        assert preserved.score == 1500
        assert preserved.connected is False
        assert preserved.ws is None

    async def test_non_lobby_admin_claim_preserves_reconnected_player(self):
        """Non-LOBBY admin claim rejection must also preserve a reconnected
        player's record (ERR_INVALID_ACTION branch)."""
        handler, game_state, _ = _make_handler_and_game()

        game_state.add_player("Alice", _make_ws())
        game_state.get_player("Alice").score = 900
        # Need a second player so the game can start.
        game_state.add_player("Bob", _make_ws())
        game_state.start_game()
        assert game_state.phase != GamePhase.LOBBY

        _disconnect(game_state, "Alice")

        new_ws = _make_ws()
        await handler._handle_message(
            new_ws,
            {"type": "join", "name": "Alice", "is_admin": True, "ha_token": "t"},
        )

        msg = new_ws.send_json.call_args[0][0]
        assert msg["type"] == "error"
        assert msg["code"] == ERR_INVALID_ACTION

        preserved = game_state.get_player("Alice")
        assert preserved is not None
        assert preserved.score == 900
        assert preserved.connected is False
        assert preserved.ws is None

    async def test_new_player_still_removed_on_reject(self):
        """(c) A brand-new player (not a reconnect) is still removed when the
        admin claim is rejected — the anti-orphan behavior is unchanged."""
        handler, game_state, _ = _make_handler_and_game()

        ws = _make_ws()
        await handler._handle_message(
            ws, {"type": "join", "name": "Ghost", "is_admin": True}
        )

        msg = ws.send_json.call_args[0][0]
        assert msg["type"] == "error"
        assert msg["code"] == ERR_UNAUTHORIZED
        # No stray record left behind.
        assert game_state.get_player("Ghost") is None
