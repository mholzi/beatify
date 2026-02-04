"""
Integration Tests: WebSocket Message Handling

Tests the WebSocket server's message handling:
- Join flow (player name → session creation → state broadcast)
- Submit guess (year + bet → scoring → state update)
- Admin actions (start, stop, volume, end game)
- Reconnection (session recovery within timeout)

Note: These tests require the actual WebSocket server implementation.
Currently marked as skip until server module is built.
"""

from __future__ import annotations

import pytest

# =============================================================================
# JOIN FLOW TESTS
# =============================================================================


@pytest.mark.integration
class TestJoinFlow:
    """Tests for player join message handling."""

    @pytest.mark.skip(reason="Requires ws_client fixture with HA integration")
    async def test_player_join_creates_session(self, ws_client):
        """Join message should create player session and broadcast state."""
        async with ws_client.ws_connect("/beatify/ws") as ws:
            await ws.send_json({"type": "join", "name": "Alice"})
            msg = await ws.receive_json()

            assert msg["type"] == "state"
            assert any(p["name"] == "Alice" for p in msg["players"])

    @pytest.mark.skip(reason="Requires ws_client fixture with HA integration")
    async def test_duplicate_name_rejected(self, ws_client):
        """Duplicate player names should be rejected."""
        async with ws_client.ws_connect("/beatify/ws") as ws1:
            await ws1.send_json({"type": "join", "name": "Alice"})
            await ws1.receive_json()  # State broadcast

            async with ws_client.ws_connect("/beatify/ws") as ws2:
                await ws2.send_json({"type": "join", "name": "Alice"})
                msg = await ws2.receive_json()

                assert msg["type"] == "error"
                assert msg["code"] == "NAME_TAKEN"

    @pytest.mark.skip(reason="Requires ws_client fixture with HA integration")
    async def test_empty_name_rejected(self, ws_client):
        """Empty player names should be rejected."""
        async with ws_client.ws_connect("/beatify/ws") as ws:
            await ws.send_json({"type": "join", "name": ""})
            msg = await ws.receive_json()

            assert msg["type"] == "error"
            assert msg["code"] == "NAME_INVALID"

    @pytest.mark.skip(reason="Requires ws_client fixture with HA integration and 20 pre-joined players")
    async def test_game_full_rejected(self, ws_client):
        """Joining full game should be rejected (Story 3.2)."""
        # This test requires 20 players to be added first
        # Implementation would need to add MAX_PLAYERS players
        # then try to add one more
        async with ws_client.ws_connect("/beatify/ws") as ws:
            await ws.send_json({"type": "join", "name": "Player21"})
            msg = await ws.receive_json()

            assert msg["type"] == "error"
            assert msg["code"] == "GAME_FULL"


# =============================================================================
# SUBMIT GUESS TESTS
# =============================================================================


@pytest.mark.integration
class TestSubmitGuess:
    """Tests for guess submission handling."""

    @pytest.mark.skip(reason="WebSocket server not yet implemented")
    async def test_submit_guess_during_playing(self, ws_client):
        """Submitting guess during PLAYING phase should succeed."""
        async with ws_client.ws_connect("/beatify/ws") as ws:
            await ws.send_json({"type": "join", "name": "Alice"})
            await ws.receive_json()

            # Start game (requires 2 players, handled by fixture)
            await ws.send_json({"type": "submit", "guess": 1985, "bet": False})
            msg = await ws.receive_json()

            assert msg["type"] == "state"
            player = next(p for p in msg["players"] if p["name"] == "Alice")
            assert player["submitted"] is True

    @pytest.mark.skip(reason="WebSocket server not yet implemented")
    async def test_submit_guess_in_lobby_rejected(self, ws_client):
        """Submitting guess in LOBBY phase should be rejected."""
        async with ws_client.ws_connect("/beatify/ws") as ws:
            await ws.send_json({"type": "join", "name": "Alice"})
            await ws.receive_json()

            await ws.send_json({"type": "submit", "guess": 1985, "bet": False})
            msg = await ws.receive_json()

            assert msg["type"] == "error"
            assert msg["code"] == "GAME_NOT_STARTED"


# =============================================================================
# ADMIN ACTION TESTS
# =============================================================================


@pytest.mark.integration
class TestAdminActions:
    """Tests for admin control messages."""

    @pytest.mark.skip(reason="WebSocket server not yet implemented")
    async def test_admin_start_game(self, ws_client):
        """Admin should be able to start game with 2+ players."""
        async with ws_client.ws_connect("/beatify/ws?admin=true") as admin_ws:
            # Join as admin
            await admin_ws.send_json({"type": "join", "name": "Admin"})
            await admin_ws.receive_json()

            # Add another player (via separate connection in fixture)
            # ...

            await admin_ws.send_json({"type": "admin", "action": "start_game"})
            msg = await admin_ws.receive_json()

            assert msg["type"] == "state"
            assert msg["phase"] == "PLAYING"

    @pytest.mark.skip(reason="WebSocket server not yet implemented")
    async def test_non_admin_cannot_start(self, ws_client):
        """Non-admin should not be able to start game."""
        async with ws_client.ws_connect("/beatify/ws") as ws:
            await ws.send_json({"type": "join", "name": "Alice"})
            await ws.receive_json()

            await ws.send_json({"type": "admin", "action": "start_game"})
            msg = await ws.receive_json()

            assert msg["type"] == "error"
            assert msg["code"] == "NOT_ADMIN"


# =============================================================================
# RECONNECTION TESTS
# =============================================================================


@pytest.mark.integration
class TestReconnection:
    """Tests for session recovery on reconnect."""

    @pytest.mark.skip(reason="WebSocket server not yet implemented")
    async def test_reconnect_within_timeout(self, ws_client):
        """Reconnecting within 60s should restore session."""
        async with ws_client.ws_connect("/beatify/ws") as ws:
            await ws.send_json({"type": "join", "name": "Alice"})
            state = await ws.receive_json()
            session_id = state["session_id"]

        # Simulate disconnect (ws closed)
        # Reconnect with session_id
        async with ws_client.ws_connect(f"/beatify/ws?session={session_id}") as ws2:
            msg = await ws2.receive_json()

            assert msg["type"] == "state"
            player = next(p for p in msg["players"] if p["name"] == "Alice")
            assert player["connected"] is True


# =============================================================================
# ERROR HANDLING TESTS
# =============================================================================


@pytest.mark.integration
class TestErrorHandling:
    """Tests for WebSocket error responses."""

    @pytest.mark.skip(reason="WebSocket server not yet implemented")
    async def test_invalid_message_type(self, ws_client):
        """Unknown message type should return error."""
        async with ws_client.ws_connect("/beatify/ws") as ws:
            await ws.send_json({"type": "invalid_type"})
            msg = await ws.receive_json()

            assert msg["type"] == "error"
            assert msg["code"] == "UNKNOWN_TYPE"

    @pytest.mark.skip(reason="WebSocket server not yet implemented")
    async def test_malformed_json(self, ws_client):
        """Malformed JSON should return error."""
        async with ws_client.ws_connect("/beatify/ws") as ws:
            await ws.send_str("not valid json")
            msg = await ws.receive_json()

            assert msg["type"] == "error"
            assert msg["code"] == "PARSE_ERROR"


# =============================================================================
# REMATCH FLOW TESTS (Issue #108)
# =============================================================================


@pytest.mark.integration
class TestRematchFlow:
    """Tests for rematch game flow (Issue #108)."""

    @pytest.mark.skip(reason="WebSocket server not yet implemented")
    async def test_rematch_only_allowed_from_end_phase(self, ws_client):
        """Rematch action should only work from END phase."""
        async with ws_client.ws_connect("/beatify/ws") as ws:
            # Try rematch from PLAYING phase
            await ws.send_json({"type": "admin", "action": "rematch_game"})
            msg = await ws.receive_json()

            assert msg["type"] == "error"
            assert msg["code"] == "INVALID_ACTION"
            assert "END phase" in msg["message"]

    @pytest.mark.skip(reason="WebSocket server not yet implemented")
    async def test_rematch_from_playing_returns_error(self, ws_client):
        """Rematch from PLAYING phase should return error."""
        async with ws_client.ws_connect("/beatify/ws") as ws:
            # Admin tries rematch during active game
            await ws.send_json({"type": "admin", "action": "rematch_game"})
            msg = await ws.receive_json()

            assert msg["type"] == "error"
            assert msg["code"] == "INVALID_ACTION"

    @pytest.mark.skip(reason="WebSocket server not yet implemented")
    async def test_dismiss_only_allowed_from_end_phase(self, ws_client):
        """Dismiss action should only work from END phase."""
        async with ws_client.ws_connect("/beatify/ws") as ws:
            # Try dismiss from PLAYING phase
            await ws.send_json({"type": "admin", "action": "dismiss_game"})
            msg = await ws.receive_json()

            assert msg["type"] == "error"
            assert msg["code"] == "INVALID_ACTION"
            assert "END phase" in msg["message"]

    @pytest.mark.skip(reason="WebSocket server not yet implemented")
    async def test_rematch_preserves_player_count(self, ws_client, game_in_end_phase):
        """Rematch should preserve all connected players."""
        # game_in_end_phase fixture provides game with players in END phase
        async with ws_client.ws_connect("/beatify/ws") as ws:
            initial_player_count = len(game_in_end_phase.players)

            await ws.send_json({"type": "admin", "action": "rematch_game"})
            msg = await ws.receive_json()

            # Should receive rematch_started event
            assert msg["type"] == "rematch_started"

            # Next message should be state with LOBBY phase
            state_msg = await ws.receive_json()
            assert state_msg["type"] == "state"
            assert state_msg["phase"] == "LOBBY"
            assert len(state_msg["players"]) == initial_player_count

    @pytest.mark.skip(reason="WebSocket server not yet implemented")
    async def test_rematch_broadcasts_rematch_started_event(self, ws_client, game_in_end_phase):
        """Rematch should broadcast rematch_started event to all clients."""
        async with ws_client.ws_connect("/beatify/ws") as ws:
            await ws.send_json({"type": "admin", "action": "rematch_game"})
            msg = await ws.receive_json()

            assert msg["type"] == "rematch_started"
