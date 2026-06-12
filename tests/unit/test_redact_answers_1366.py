"""Tests for per-recipient answer redaction in broadcasts (#1366).

The broadcast payload carries the round's answers (``admin_song`` year;
``song.artist`` / ``song.title`` in title_artist_mode) so the spectator admin
/ TV can show them. Those frames were sent unfiltered to every connection, so a
player could read the answer off the WebSocket before guessing. These tests
pin the redaction: only the spectator admin WS gets the answers; every player
connection gets a redacted copy.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from custom_components.beatify.const import DOMAIN
from custom_components.beatify.game.state import GamePhase
from custom_components.beatify.server.serializers import (
    REDACTED_PLACEHOLDER,
    build_state_message,
    redact_state_for_player,
)
from custom_components.beatify.server.websocket import BeatifyWebSocketHandler
from tests.conftest import make_game_state, make_songs


def _playing_game(*, title_artist_mode: bool):
    gs = make_game_state()
    gs.create_game(
        playlists=["test.json"],
        songs=make_songs(3),
        media_player="media_player.test",
        base_url="http://localhost:8123",
        title_artist_mode=title_artist_mode,
    )
    gs.phase = GamePhase.PLAYING
    gs.current_song = {
        "title": "Hey Jude",
        "artist": "The Beatles",
        "year": 1968,
        "album_art": "/art.png",
    }
    if title_artist_mode:
        gs._challenge_manager.init_round(gs.current_song)
    return gs


# ---------------------------------------------------------------------------
# redact_state_for_player — pure function
# ---------------------------------------------------------------------------


class TestRedactStateForPlayer:
    def test_admin_song_stripped_during_playing(self):
        msg = build_state_message(_playing_game(title_artist_mode=False))
        assert "admin_song" in msg  # full payload carries the year answer
        assert msg["admin_song"]["year"] == 1968

        redacted = redact_state_for_player(msg)
        assert "admin_song" not in redacted
        # The original is not mutated.
        assert "admin_song" in msg

    def test_year_only_mode_keeps_song_artist_title(self):
        # Without title_artist_mode the song.artist/title are NOT the answer
        # (the year is), so they stay — only admin_song is stripped.
        msg = build_state_message(_playing_game(title_artist_mode=False))
        redacted = redact_state_for_player(msg)
        assert redacted["song"]["artist"] == "The Beatles"
        assert redacted["song"]["title"] == "Hey Jude"
        assert redacted["song"]["album_art"] == "/art.png"

    def test_title_artist_mode_masks_artist_and_title(self):
        msg = build_state_message(_playing_game(title_artist_mode=True))
        redacted = redact_state_for_player(msg)
        assert redacted["song"]["artist"] == REDACTED_PLACEHOLDER
        assert redacted["song"]["title"] == REDACTED_PLACEHOLDER
        # Album art must survive so the player can still play along.
        assert redacted["song"]["album_art"] == "/art.png"
        # admin_song still gone.
        assert "admin_song" not in redacted
        # Original untouched.
        assert msg["song"]["artist"] == "The Beatles"

    def test_reveal_payload_not_redacted(self):
        gs = _playing_game(title_artist_mode=True)
        gs.phase = GamePhase.REVEAL
        msg = build_state_message(gs)
        # REVEAL carries the truth at the right time and has no admin_song.
        redacted = redact_state_for_player(msg)
        assert redacted["song"]["artist"] == "The Beatles"
        assert redacted["song"]["title"] == "Hey Jude"
        assert redacted["song"]["year"] == 1968

    def test_lobby_payload_passthrough(self):
        gs = make_game_state()
        gs.create_game(
            playlists=["test.json"],
            songs=make_songs(3),
            media_player="media_player.test",
            base_url="http://localhost:8123",
        )
        msg = build_state_message(gs)  # LOBBY — no song, no admin_song
        assert redact_state_for_player(msg) is msg  # unchanged, same object


# ---------------------------------------------------------------------------
# broadcast — per-recipient routing
# ---------------------------------------------------------------------------


def _make_ws() -> AsyncMock:
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    ws.closed = False
    return ws


class TestBroadcastRedaction:
    def _handler(self, gs):
        mock_hass = MagicMock()
        mock_hass.data = {DOMAIN: {"game": gs}}
        return BeatifyWebSocketHandler(mock_hass)

    async def test_player_gets_redacted_admin_gets_full(self):
        gs = _playing_game(title_artist_mode=True)
        handler = self._handler(gs)

        admin_ws = _make_ws()
        player_ws = _make_ws()
        gs._admin_ws = admin_ws
        handler.connections = {admin_ws, player_ws}

        msg = build_state_message(gs)
        await handler.broadcast(msg)

        admin_payload = admin_ws.send_json.call_args[0][0]
        player_payload = player_ws.send_json.call_args[0][0]

        # Spectator admin keeps the answers.
        assert admin_payload["admin_song"]["year"] == 1968
        assert admin_payload["song"]["artist"] == "The Beatles"
        assert admin_payload["song"]["title"] == "Hey Jude"

        # Player gets them stripped / masked.
        assert "admin_song" not in player_payload
        assert player_payload["song"]["artist"] == REDACTED_PLACEHOLDER
        assert player_payload["song"]["title"] == REDACTED_PLACEHOLDER

    async def test_metadata_update_masked_for_player_in_ta_mode(self):
        gs = _playing_game(title_artist_mode=True)
        handler = self._handler(gs)

        admin_ws = _make_ws()
        player_ws = _make_ws()
        gs._admin_ws = admin_ws
        handler.connections = {admin_ws, player_ws}

        await handler.broadcast_metadata_update(
            {"artist": "The Beatles", "title": "Hey Jude", "album_art": "/art.png"}
        )

        admin_payload = admin_ws.send_json.call_args[0][0]
        player_payload = player_ws.send_json.call_args[0][0]
        assert admin_payload["song"]["artist"] == "The Beatles"
        assert player_payload["song"]["artist"] == REDACTED_PLACEHOLDER
        assert player_payload["song"]["title"] == REDACTED_PLACEHOLDER
        assert player_payload["song"]["album_art"] == "/art.png"
