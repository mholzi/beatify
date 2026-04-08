"""Tests for Beatify WebSocket handler (custom_components/beatify/server/websocket.py)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from custom_components.beatify.const import (
    DOMAIN,
    ERR_ADMIN_CANNOT_LEAVE,
    ERR_ADMIN_EXISTS,
    ERR_ALREADY_SUBMITTED,
    ERR_GAME_ENDED,
    ERR_GAME_FULL,
    ERR_GAME_NOT_STARTED,
    ERR_INVALID_ACTION,
    ERR_NAME_INVALID,
    ERR_NAME_TAKEN,
    ERR_NO_ARTIST_CHALLENGE,
    ERR_NO_MOVIE_CHALLENGE,
    ERR_NOT_ADMIN,
    ERR_NOT_IN_GAME,
    ERR_ROUND_EXPIRED,
    ERR_SESSION_NOT_FOUND,
    ERR_UNAUTHORIZED,
    YEAR_MAX,
    YEAR_MIN,
)
from custom_components.beatify.game.state import (
    ArtistChallenge,
    GamePhase,
    GameState,
    MovieChallenge,
)
from custom_components.beatify.server.websocket import BeatifyWebSocketHandler
from tests.conftest import make_game_state, make_songs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_handler_and_game(
    **game_kwargs,
) -> tuple[BeatifyWebSocketHandler, GameState, AsyncMock]:
    """Create a handler with a real GameState and a mock WebSocket."""
    mock_hass = MagicMock()
    game_state = make_game_state()
    songs = game_kwargs.pop("songs", make_songs(5))
    game_state.create_game(
        playlists=["test.json"],
        songs=songs,
        media_player="media_player.test",
        base_url="http://localhost:8123",
        **game_kwargs,
    )
    mock_hass.data = {DOMAIN: {"game": game_state}}

    handler = BeatifyWebSocketHandler(mock_hass)
    mock_ws = AsyncMock()
    mock_ws.send_json = AsyncMock()
    mock_ws.closed = False
    mock_ws.close = AsyncMock()

    return handler, game_state, mock_ws


def _make_ws() -> AsyncMock:
    """Create a fresh mock WebSocket."""
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    ws.closed = False
    ws.close = AsyncMock()
    return ws


# ---------------------------------------------------------------------------
# No active game
# ---------------------------------------------------------------------------


class TestNoActiveGame:
    async def test_no_game_in_hass_data(self):
        mock_hass = MagicMock()
        mock_hass.data = {}
        handler = BeatifyWebSocketHandler(mock_hass)
        ws = _make_ws()

        await handler._handle_message(ws, {"type": "join", "name": "Alice"})

        ws.send_json.assert_awaited_once()
        msg = ws.send_json.call_args[0][0]
        assert msg["type"] == "error"
        assert msg["code"] == ERR_GAME_NOT_STARTED

    async def test_game_without_game_id(self):
        mock_hass = MagicMock()
        game_state = make_game_state()
        # game_state exists but no game_id (no create_game called)
        mock_hass.data = {DOMAIN: {"game": game_state}}
        handler = BeatifyWebSocketHandler(mock_hass)
        ws = _make_ws()

        await handler._handle_message(ws, {"type": "submit", "year": 1990})

        msg = ws.send_json.call_args[0][0]
        assert msg["type"] == "error"
        assert msg["code"] == ERR_GAME_NOT_STARTED


# ---------------------------------------------------------------------------
# Join
# ---------------------------------------------------------------------------


class TestJoin:
    async def test_successful_join(self):
        handler, game_state, ws = _make_handler_and_game()

        await handler._handle_message(ws, {"type": "join", "name": "Alice"})

        assert "Alice" in game_state.players
        # Should receive join_ack, then state
        calls = ws.send_json.call_args_list
        types = [c[0][0]["type"] for c in calls]
        assert "join_ack" in types
        assert "state" in types

    async def test_join_ack_contains_session_id(self):
        handler, game_state, ws = _make_handler_and_game()

        await handler._handle_message(ws, {"type": "join", "name": "Alice"})

        join_ack = next(
            c[0][0]
            for c in ws.send_json.call_args_list
            if c[0][0]["type"] == "join_ack"
        )
        assert "session_id" in join_ack
        assert "game_id" in join_ack

    async def test_name_taken(self):
        handler, game_state, ws = _make_handler_and_game()
        game_state.add_player("Alice", _make_ws())
        ws2 = _make_ws()

        await handler._handle_message(ws2, {"type": "join", "name": "Alice"})

        msg = ws2.send_json.call_args[0][0]
        assert msg["type"] == "error"
        assert msg["code"] == ERR_NAME_TAKEN

    async def test_empty_name(self):
        handler, game_state, ws = _make_handler_and_game()

        await handler._handle_message(ws, {"type": "join", "name": ""})

        msg = ws.send_json.call_args[0][0]
        assert msg["type"] == "error"
        assert msg["code"] == ERR_NAME_INVALID

    async def test_game_full(self):
        handler, game_state, ws = _make_handler_and_game()
        from custom_components.beatify.const import MAX_PLAYERS

        for i in range(MAX_PLAYERS):
            game_state.add_player(f"P{i}", _make_ws())

        await handler._handle_message(ws, {"type": "join", "name": "Extra"})

        msg = ws.send_json.call_args[0][0]
        assert msg["type"] == "error"
        assert msg["code"] == ERR_GAME_FULL

    async def test_join_ended_game(self):
        handler, game_state, ws = _make_handler_and_game()
        game_state.phase = GamePhase.END

        await handler._handle_message(ws, {"type": "join", "name": "Alice"})

        msg = ws.send_json.call_args[0][0]
        assert msg["type"] == "error"
        assert msg["code"] == ERR_GAME_ENDED

    async def test_admin_join_sets_admin(self):
        handler, game_state, ws = _make_handler_and_game()

        await handler._handle_message(
            ws, {"type": "join", "name": "Host", "is_admin": True}
        )

        assert "Host" in game_state.players
        assert game_state.players["Host"].is_admin is True

    async def test_second_admin_join_rejected(self):
        handler, game_state, ws = _make_handler_and_game()
        admin_ws = _make_ws()
        game_state.add_player("Host", admin_ws)
        game_state.set_admin("Host")

        ws2 = _make_ws()
        await handler._handle_message(
            ws2, {"type": "join", "name": "Intruder", "is_admin": True}
        )

        msg = ws2.send_json.call_args[0][0]
        assert msg["type"] == "error"
        assert msg["code"] == ERR_ADMIN_EXISTS
        # Intruder should have been removed
        assert "Intruder" not in game_state.players

    async def test_admin_reconnect_during_pause(self):
        handler, game_state, ws = _make_handler_and_game()
        admin_ws = _make_ws()
        game_state.add_player("Host", admin_ws)
        game_state.set_admin("Host")
        game_state.add_player("Player2", _make_ws())
        game_state.start_game()
        # Simulate admin disconnect and game pause
        game_state.players["Host"].connected = False
        game_state.phase = GamePhase.PAUSED
        game_state.disconnected_admin_name = "Host"
        game_state._previous_phase = GamePhase.PLAYING
        game_state.deadline = int(game_state._now() * 1000) + 60_000

        new_ws = _make_ws()
        await handler._handle_message(
            new_ws, {"type": "join", "name": "Host", "is_admin": True}
        )

        # Game should be resumed
        assert game_state.phase == GamePhase.PLAYING


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------


class TestSubmit:
    async def test_valid_submit(self):
        handler, game_state, ws = _make_handler_and_game()
        game_state.add_player("Alice", ws)
        game_state.add_player("Bob", _make_ws())
        game_state.phase = GamePhase.PLAYING
        game_state.current_song = make_songs(1)[0]
        # Set deadline far in the future
        game_state.deadline = int(game_state._now() * 1000) + 60_000
        handler.connections.add(ws)

        await handler._handle_message(ws, {"type": "submit", "year": 1985})

        assert game_state.players["Alice"].submitted is True
        assert game_state.players["Alice"].current_guess == 1985
        # Should receive submit_ack
        ack = next(
            c[0][0]
            for c in ws.send_json.call_args_list
            if c[0][0]["type"] == "submit_ack"
        )
        assert ack["year"] == 1985

    async def test_submit_not_in_game(self):
        handler, game_state, ws = _make_handler_and_game()
        game_state.phase = GamePhase.PLAYING

        await handler._handle_message(ws, {"type": "submit", "year": 1985})

        msg = ws.send_json.call_args[0][0]
        assert msg["type"] == "error"
        assert msg["code"] == ERR_NOT_IN_GAME

    async def test_submit_wrong_phase(self):
        handler, game_state, ws = _make_handler_and_game()
        game_state.add_player("Alice", ws)
        game_state.phase = GamePhase.LOBBY

        await handler._handle_message(ws, {"type": "submit", "year": 1985})

        msg = ws.send_json.call_args[0][0]
        assert msg["type"] == "error"
        assert msg["code"] == ERR_INVALID_ACTION

    async def test_submit_already_submitted(self):
        handler, game_state, ws = _make_handler_and_game()
        game_state.add_player("Alice", ws)
        game_state.phase = GamePhase.PLAYING
        game_state.deadline = int(game_state._now() * 1000) + 60_000
        game_state.players["Alice"].submitted = True

        await handler._handle_message(ws, {"type": "submit", "year": 1985})

        msg = ws.send_json.call_args[0][0]
        assert msg["type"] == "error"
        assert msg["code"] == ERR_ALREADY_SUBMITTED

    async def test_submit_deadline_passed(self):
        handler, game_state, ws = _make_handler_and_game()
        game_state.add_player("Alice", ws)
        game_state.phase = GamePhase.PLAYING
        # Set deadline in the past
        game_state.deadline = int(game_state._now() * 1000) - 1000

        await handler._handle_message(ws, {"type": "submit", "year": 1985})

        msg = ws.send_json.call_args[0][0]
        assert msg["type"] == "error"
        assert msg["code"] == ERR_ROUND_EXPIRED

    async def test_submit_year_too_low(self):
        handler, game_state, ws = _make_handler_and_game()
        game_state.add_player("Alice", ws)
        game_state.phase = GamePhase.PLAYING
        game_state.deadline = int(game_state._now() * 1000) + 60_000

        await handler._handle_message(ws, {"type": "submit", "year": YEAR_MIN - 1})

        msg = ws.send_json.call_args[0][0]
        assert msg["type"] == "error"
        assert msg["code"] == ERR_INVALID_ACTION

    async def test_submit_year_too_high(self):
        handler, game_state, ws = _make_handler_and_game()
        game_state.add_player("Alice", ws)
        game_state.phase = GamePhase.PLAYING
        game_state.deadline = int(game_state._now() * 1000) + 60_000

        await handler._handle_message(ws, {"type": "submit", "year": YEAR_MAX + 1})

        msg = ws.send_json.call_args[0][0]
        assert msg["type"] == "error"
        assert msg["code"] == ERR_INVALID_ACTION

    async def test_submit_non_integer_year(self):
        handler, game_state, ws = _make_handler_and_game()
        game_state.add_player("Alice", ws)
        game_state.phase = GamePhase.PLAYING
        game_state.deadline = int(game_state._now() * 1000) + 60_000

        await handler._handle_message(ws, {"type": "submit", "year": "abc"})

        msg = ws.send_json.call_args[0][0]
        assert msg["type"] == "error"
        assert msg["code"] == ERR_INVALID_ACTION

    async def test_submit_with_bet(self):
        handler, game_state, ws = _make_handler_and_game()
        game_state.add_player("Alice", ws)
        game_state.add_player("Bob", _make_ws())
        game_state.phase = GamePhase.PLAYING
        game_state.current_song = make_songs(1)[0]
        game_state.deadline = int(game_state._now() * 1000) + 60_000
        handler.connections.add(ws)

        await handler._handle_message(ws, {"type": "submit", "year": 1985, "bet": True})

        assert game_state.players["Alice"].bet is True


# ---------------------------------------------------------------------------
# Reconnect
# ---------------------------------------------------------------------------


class TestReconnect:
    async def test_successful_reconnect(self):
        handler, game_state, ws = _make_handler_and_game()
        game_state.add_player("Alice", ws)
        session_id = game_state.players["Alice"].session_id
        game_state.players["Alice"].connected = False

        new_ws = _make_ws()
        await handler._handle_message(
            new_ws, {"type": "reconnect", "session_id": session_id}
        )

        # Should receive reconnect_ack and state
        types = [c[0][0]["type"] for c in new_ws.send_json.call_args_list]
        assert "reconnect_ack" in types
        assert "state" in types
        assert game_state.players["Alice"].connected is True
        assert game_state.players["Alice"].ws is new_ws

    async def test_reconnect_no_session_id(self):
        handler, game_state, ws = _make_handler_and_game()

        await handler._handle_message(ws, {"type": "reconnect"})

        msg = ws.send_json.call_args[0][0]
        assert msg["type"] == "error"
        assert msg["code"] == ERR_SESSION_NOT_FOUND

    async def test_reconnect_invalid_session_id(self):
        handler, game_state, ws = _make_handler_and_game()

        await handler._handle_message(ws, {"type": "reconnect", "session_id": "bogus"})

        msg = ws.send_json.call_args[0][0]
        assert msg["type"] == "error"
        assert msg["code"] == ERR_SESSION_NOT_FOUND

    async def test_reconnect_ended_game(self):
        handler, game_state, ws = _make_handler_and_game()
        game_state.add_player("Alice", ws)
        session_id = game_state.players["Alice"].session_id
        game_state.phase = GamePhase.END

        new_ws = _make_ws()
        await handler._handle_message(
            new_ws, {"type": "reconnect", "session_id": session_id}
        )

        msg = new_ws.send_json.call_args[0][0]
        assert msg["type"] == "error"
        assert msg["code"] == ERR_GAME_ENDED


# ---------------------------------------------------------------------------
# Leave
# ---------------------------------------------------------------------------


class TestLeave:
    async def test_player_leave(self):
        handler, game_state, ws = _make_handler_and_game()
        game_state.add_player("Alice", ws)
        handler.connections.add(ws)

        await handler._handle_message(ws, {"type": "leave"})

        # Player should be removed
        assert "Alice" not in game_state.players
        # Should receive "left" message
        left_msg = next(
            c[0][0] for c in ws.send_json.call_args_list if c[0][0]["type"] == "left"
        )
        assert left_msg["type"] == "left"

    async def test_admin_cannot_leave(self):
        handler, game_state, ws = _make_handler_and_game()
        game_state.add_player("Host", ws)
        game_state.set_admin("Host")

        await handler._handle_message(ws, {"type": "leave"})

        msg = ws.send_json.call_args[0][0]
        assert msg["type"] == "error"
        assert msg["code"] == ERR_ADMIN_CANNOT_LEAVE
        # Admin should still be in game
        assert "Host" in game_state.players

    async def test_leave_unknown_player_silent(self):
        handler, game_state, ws = _make_handler_and_game()
        # ws is not associated with any player

        await handler._handle_message(ws, {"type": "leave"})

        # Should not crash, no messages sent
        ws.send_json.assert_not_awaited()


# ---------------------------------------------------------------------------
# Steal
# ---------------------------------------------------------------------------


class TestSteal:
    async def test_steal_not_in_game(self):
        handler, game_state, ws = _make_handler_and_game()
        game_state.phase = GamePhase.PLAYING

        await handler._handle_message(ws, {"type": "steal", "target": "Bob"})

        msg = ws.send_json.call_args[0][0]
        assert msg["type"] == "error"
        assert msg["code"] == ERR_NOT_IN_GAME

    async def test_steal_no_target(self):
        handler, game_state, ws = _make_handler_and_game()
        game_state.add_player("Alice", ws)
        game_state.phase = GamePhase.PLAYING

        await handler._handle_message(ws, {"type": "steal"})

        msg = ws.send_json.call_args[0][0]
        assert msg["type"] == "error"
        assert msg["code"] == ERR_INVALID_ACTION

    async def test_successful_steal(self):
        handler, game_state, ws = _make_handler_and_game()
        game_state.add_player("Alice", ws)
        game_state.add_player("Bob", _make_ws())
        game_state.phase = GamePhase.PLAYING
        game_state.players["Alice"].steal_available = True
        game_state.players["Bob"].submitted = True
        game_state.players["Bob"].current_guess = 1990
        handler.connections.add(ws)

        await handler._handle_message(ws, {"type": "steal", "target": "Bob"})

        ack = next(
            c[0][0]
            for c in ws.send_json.call_args_list
            if c[0][0]["type"] == "steal_ack"
        )
        assert ack["success"] is True
        assert ack["year"] == 1990


# ---------------------------------------------------------------------------
# Artist guess
# ---------------------------------------------------------------------------


class TestArtistGuess:
    async def test_artist_guess_wrong_phase(self):
        handler, game_state, ws = _make_handler_and_game()
        game_state.phase = GamePhase.REVEAL

        await handler._handle_message(
            ws, {"type": "artist_guess", "artist": "The Beatles"}
        )

        msg = ws.send_json.call_args[0][0]
        assert msg["type"] == "error"
        assert msg["code"] == ERR_INVALID_ACTION

    async def test_artist_guess_not_in_game(self):
        handler, game_state, ws = _make_handler_and_game()
        game_state.phase = GamePhase.PLAYING

        await handler._handle_message(
            ws, {"type": "artist_guess", "artist": "The Beatles"}
        )

        msg = ws.send_json.call_args[0][0]
        assert msg["type"] == "error"
        assert msg["code"] == ERR_NOT_IN_GAME

    async def test_artist_guess_no_challenge(self):
        handler, game_state, ws = _make_handler_and_game()
        game_state.add_player("Alice", ws)
        game_state.phase = GamePhase.PLAYING
        game_state.artist_challenge = None

        await handler._handle_message(
            ws, {"type": "artist_guess", "artist": "The Beatles"}
        )

        msg = ws.send_json.call_args[0][0]
        assert msg["type"] == "error"
        assert msg["code"] == ERR_NO_ARTIST_CHALLENGE

    async def test_artist_guess_empty_artist(self):
        handler, game_state, ws = _make_handler_and_game()
        game_state.add_player("Alice", ws)
        game_state.phase = GamePhase.PLAYING
        game_state.artist_challenge = ArtistChallenge(
            correct_artist="A", options=["A", "B"]
        )

        await handler._handle_message(ws, {"type": "artist_guess", "artist": ""})

        msg = ws.send_json.call_args[0][0]
        assert msg["type"] == "error"
        assert msg["code"] == ERR_INVALID_ACTION

    async def test_artist_guess_success(self):
        handler, game_state, ws = _make_handler_and_game()
        game_state.add_player("Alice", ws)
        game_state.phase = GamePhase.PLAYING
        game_state.artist_challenge = ArtistChallenge(
            correct_artist="Artist 0", options=["Artist 0", "Other"]
        )
        game_state.artist_challenge_enabled = True
        handler.connections.add(ws)

        # Mock submit_artist_guess to return a controlled result
        game_state.submit_artist_guess = MagicMock(
            return_value={"correct": True, "first": True, "winner": "Alice"}
        )

        await handler._handle_message(
            ws, {"type": "artist_guess", "artist": "Artist 0"}
        )

        ack = next(
            c[0][0]
            for c in ws.send_json.call_args_list
            if c[0][0]["type"] == "artist_guess_ack"
        )
        assert ack["correct"] is True
        assert ack["first"] is True


# ---------------------------------------------------------------------------
# Movie guess
# ---------------------------------------------------------------------------


class TestMovieGuess:
    async def test_movie_guess_wrong_phase(self):
        handler, game_state, ws = _make_handler_and_game()
        game_state.phase = GamePhase.REVEAL

        await handler._handle_message(ws, {"type": "movie_guess", "movie": "Grease"})

        msg = ws.send_json.call_args[0][0]
        assert msg["type"] == "error"
        assert msg["code"] == ERR_INVALID_ACTION

    async def test_movie_guess_not_in_game(self):
        handler, game_state, ws = _make_handler_and_game()
        game_state.phase = GamePhase.PLAYING

        await handler._handle_message(ws, {"type": "movie_guess", "movie": "Grease"})

        msg = ws.send_json.call_args[0][0]
        assert msg["type"] == "error"
        assert msg["code"] == ERR_NOT_IN_GAME

    async def test_movie_guess_no_challenge(self):
        handler, game_state, ws = _make_handler_and_game()
        game_state.add_player("Alice", ws)
        game_state.phase = GamePhase.PLAYING
        game_state.movie_challenge = None

        await handler._handle_message(ws, {"type": "movie_guess", "movie": "Grease"})

        msg = ws.send_json.call_args[0][0]
        assert msg["type"] == "error"
        assert msg["code"] == ERR_NO_MOVIE_CHALLENGE

    async def test_movie_guess_empty_movie(self):
        handler, game_state, ws = _make_handler_and_game()
        game_state.add_player("Alice", ws)
        game_state.phase = GamePhase.PLAYING
        game_state.movie_challenge = MovieChallenge(
            correct_movie="A", options=["A", "B"]
        )

        await handler._handle_message(ws, {"type": "movie_guess", "movie": "  "})

        msg = ws.send_json.call_args[0][0]
        assert msg["type"] == "error"
        assert msg["code"] == ERR_INVALID_ACTION

    async def test_movie_guess_success(self):
        handler, game_state, ws = _make_handler_and_game()
        game_state.add_player("Alice", ws)
        game_state.phase = GamePhase.PLAYING
        game_state.movie_challenge = MovieChallenge(
            correct_movie="Grease", options=["Grease", "Footloose"]
        )
        handler.connections.add(ws)

        game_state.submit_movie_guess = MagicMock(
            return_value={
                "correct": True,
                "already_guessed": False,
                "rank": 1,
                "bonus": 5,
            }
        )

        await handler._handle_message(ws, {"type": "movie_guess", "movie": "Grease"})

        ack = next(
            c[0][0]
            for c in ws.send_json.call_args_list
            if c[0][0]["type"] == "movie_guess_ack"
        )
        assert ack["correct"] is True
        assert ack["rank"] == 1
        assert ack["bonus"] == 5


# ---------------------------------------------------------------------------
# Get state
# ---------------------------------------------------------------------------


class TestGetState:
    async def test_get_state_returns_state(self):
        handler, game_state, ws = _make_handler_and_game()

        await handler._handle_message(ws, {"type": "get_state"})

        msg = ws.send_json.call_args[0][0]
        assert msg["type"] == "state"
        assert "phase" in msg


# ---------------------------------------------------------------------------
# Unknown message type
# ---------------------------------------------------------------------------


class TestUnknownMessage:
    async def test_unknown_type_does_not_crash(self):
        handler, game_state, ws = _make_handler_and_game()

        # Should not raise
        await handler._handle_message(ws, {"type": "bogus_type"})

        # No error sent to client for unknown types (just logged)
        ws.send_json.assert_not_awaited()


# ---------------------------------------------------------------------------
# Admin connect (Issue #477)
# ---------------------------------------------------------------------------


class TestAdminConnect:
    """Tests for admin spectator WebSocket connection."""

    async def test_valid_token_stores_ws_and_sends_ack(self):
        handler, game_state, ws = _make_handler_and_game()
        handler.connections.add(ws)

        await handler._handle_message(
            ws, {"type": "admin_connect", "admin_token": game_state.admin_token}
        )

        assert game_state._admin_ws is ws
        # First call: ack, second call: state
        calls = ws.send_json.call_args_list
        assert calls[0][0][0]["type"] == "admin_connect_ack"
        assert calls[0][0][0]["game_id"] == game_state.game_id
        assert calls[1][0][0]["type"] == "state"

    async def test_invalid_token_rejected(self):
        handler, game_state, ws = _make_handler_and_game()

        await handler._handle_message(
            ws, {"type": "admin_connect", "admin_token": "wrong-token"}
        )

        assert game_state._admin_ws is None
        msg = ws.send_json.call_args[0][0]
        assert msg["type"] == "error"
        assert msg["code"] == ERR_UNAUTHORIZED

    async def test_missing_token_rejected(self):
        handler, game_state, ws = _make_handler_and_game()

        await handler._handle_message(ws, {"type": "admin_connect"})

        assert game_state._admin_ws is None
        msg = ws.send_json.call_args[0][0]
        assert msg["code"] == ERR_UNAUTHORIZED

    async def test_admin_command_from_admin_ws(self):
        """Admin spectator (not a player) can send admin commands.

        We test with set_volume since start_game requires a media player.
        The key assertion is that the command is NOT rejected with NOT_ADMIN.
        """
        handler, game_state, ws = _make_handler_and_game()
        handler.connections.add(ws)

        # Connect as admin spectator
        await handler._handle_message(
            ws, {"type": "admin_connect", "admin_token": game_state.admin_token}
        )
        ws.send_json.reset_mock()

        # Transition to PLAYING so set_volume makes sense
        game_state.phase = GamePhase.PLAYING

        # Send admin command from spectator WS
        await handler._handle_message(
            ws, {"type": "admin", "action": "set_volume", "direction": "up"}
        )

        # Should NOT get ERR_NOT_ADMIN
        for call in ws.send_json.call_args_list:
            msg = call[0][0]
            if msg.get("type") == "error":
                assert msg["code"] != ERR_NOT_ADMIN

    async def test_non_admin_ws_rejected(self):
        """Regular WS that didn't admin_connect cannot send admin commands."""
        handler, game_state, ws = _make_handler_and_game()

        await handler._handle_message(
            ws, {"type": "admin", "action": "start_game"}
        )

        msg = ws.send_json.call_args[0][0]
        assert msg["type"] == "error"
        assert msg["code"] == ERR_NOT_ADMIN

    async def test_disconnect_clears_admin_ws(self):
        handler, game_state, ws = _make_handler_and_game()
        game_state._admin_ws = ws

        await handler._handle_disconnect(ws)

        assert game_state._admin_ws is None

    async def test_game_reset_clears_admin_ws(self):
        handler, game_state, ws = _make_handler_and_game()
        game_state._admin_ws = ws

        game_state._reset_game_internals()

        assert game_state._admin_ws is None
