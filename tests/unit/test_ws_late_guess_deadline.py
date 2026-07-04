"""Regression tests for #1662 (late-guess gap).

The Artist / Movie / Title&Artist challenge WS handlers must reject guesses
submitted after the round deadline has passed — mirroring the year handler's
``is_deadline_passed()`` guard (``ws_handlers/guessing.py``). Without it, in the
window between deadline expiry and the ``end_round`` phase flip a late guess
could still bank points/bonus while ``phase`` was still ``PLAYING``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.beatify.const import DOMAIN, ERR_ROUND_EXPIRED
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


def _ws() -> AsyncMock:
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    ws.closed = False
    ws.close = AsyncMock()
    return ws


async def _playing_game_with_player():
    """A game in PLAYING phase whose deadline has just expired."""
    mock_hass = MagicMock()
    gs = make_game_state()
    gs.create_game(
        playlists=["t.json"],
        songs=make_songs(3),
        media_player="media_player.x",
        base_url="http://h",
    )
    gs._media_player_service = _stub_media_service()
    gs.platform = "music_assistant"  # skip the verify_responsive branch
    mock_hass.data = {DOMAIN: {"game": gs}}
    handler = BeatifyWebSocketHandler(mock_hass)
    handler.broadcast_state = AsyncMock()
    handler.broadcast = AsyncMock()
    handler.debounced_broadcast_state = AsyncMock()

    ws = _ws()
    gs.add_player("Alice", ws)
    gs.players["Alice"].connected = True
    await gs.start_round()
    assert gs.phase == GamePhase.PLAYING
    # Round is still PLAYING, but the deadline has elapsed.
    gs.is_deadline_passed = MagicMock(return_value=True)
    return handler, gs, ws


def _sent_codes(ws: AsyncMock) -> list[str]:
    return [
        call.args[0].get("code")
        for call in ws.send_json.call_args_list
        if call.args and isinstance(call.args[0], dict)
    ]


class TestLateGuessRejected:
    @pytest.mark.parametrize(
        ("message", "flag"),
        [
            ({"type": "artist_guess", "artist": "Whoever"}, "has_artist_guess"),
            ({"type": "movie_guess", "movie": "Whatever"}, "has_movie_guess"),
            (
                {"type": "title_artist_guess", "title": "T", "artist": "A"},
                "has_title_artist_guess",
            ),
        ],
    )
    async def test_guess_after_deadline_is_rejected(self, message, flag):
        """A late guess gets ROUND_EXPIRED and is never recorded."""
        handler, gs, ws = await _playing_game_with_player()

        await handler._handle_message(ws, message)

        # Handler answered with the round-expired error ...
        assert ERR_ROUND_EXPIRED in _sent_codes(ws)
        # ... and never marked the guess as submitted (no points/bonus banked).
        assert getattr(gs.players["Alice"], flag) is False

        gs._cancel_auto_advance()
