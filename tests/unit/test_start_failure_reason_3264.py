"""#3264 — a failed start says why it failed, on both start paths.

The nightly live test of 25.10.2026 hit a Music Assistant provider that could
not stream any track. ``start_round()`` tried three songs, paused the game with
``media_player_error`` and returned ``False``. The REST start then answered
"Failed to start - no songs" (``START_FAILED_NO_SONGS``) although all 112 songs
of the playlist were playable, pointing the host at the wrong fix. The
websocket start already read the pause reason; the REST start did not.

These tests drive both surfaces through the same failure and demand the same
``code`` and ``message_key``.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.beatify.const import DOMAIN
from custom_components.beatify.game.state import GamePhase
from custom_components.beatify.server.game_views import StartGameplayView
from custom_components.beatify.server.ws_handlers.admin import admin_start_game

from tests.conftest import make_game_state, make_songs


def _lobby():
    state = make_game_state()
    state.create_game(
        playlists=["test.json"],
        songs=make_songs(5),
        media_player="media_player.test",
        base_url="http://localhost:8123",
    )
    for i in range(2):
        ws = AsyncMock()
        ws.closed = False
        state.add_player(f"P{i}", ws)
        state.get_player(f"P{i}").connected = True
    return state


def _handler() -> MagicMock:
    handler = MagicMock()
    handler.broadcast = AsyncMock()
    handler.broadcast_state = AsyncMock()
    handler.broadcast_metadata_update = AsyncMock()
    return handler


def _failing_start(state, *, phase, pause_reason=None, detail=None):
    async def start_round(*_a, **_kw):
        state.phase = phase
        state.pause_reason = pause_reason
        state.last_error_detail = detail
        return False

    state.start_round = start_round
    return state


async def _over_websocket(state, handler):
    ws = AsyncMock()
    await admin_start_game(handler, ws, {}, state)
    return ws.send_json.call_args.args[0]


@patch(
    "custom_components.beatify.server.game_views.is_authorized_http",
    return_value=True,
)
async def _over_rest(state, handler, _auth):
    hass = MagicMock()
    hass.data = {DOMAIN: {"game": state, "ws_handler": handler}}
    resp = await StartGameplayView(hass).post(MagicMock())
    assert resp.status == 500
    return json.loads(resp.body)


CASES = [
    # (phase, pause_reason, detail, code, message_key)
    (
        GamePhase.PAUSED,
        "media_player_error",
        "Failed to get song stream metadata",
        "MEDIA_PLAYER_UNAVAILABLE",
        "MEDIA_PLAYER_ERROR",
    ),
    (
        GamePhase.PAUSED,
        "media_player_error",
        None,
        "MEDIA_PLAYER_UNAVAILABLE",
        "MEDIA_PLAYER_NOT_RESPONDING",
    ),
    (
        GamePhase.PAUSED,
        "no_songs_available",
        None,
        "GAME_NOT_STARTED",
        "NO_SONGS_FOR_PROVIDER",
    ),
    (GamePhase.END, None, None, "NO_SONGS_REMAINING", "NO_SONGS_IN_PLAYLIST"),
]


@pytest.mark.parametrize(("phase", "reason", "detail", "code", "key"), CASES)
async def test_both_paths_report_the_same_reason(phase, reason, detail, code, key):
    for start in (_over_websocket, _over_rest):
        state = _failing_start(
            _lobby(), phase=phase, pause_reason=reason, detail=detail
        )
        body = await start(state, _handler())
        assert body["code"] == code, start.__name__
        assert body["message_key"] == key, start.__name__
        if key == "MEDIA_PLAYER_ERROR":
            assert body["detail"] == detail, start.__name__


async def test_rest_playback_failure_is_not_called_no_songs():
    """The exact live-test case: songs were fine, the speaker was not."""
    state = _failing_start(
        _lobby(),
        phase=GamePhase.PAUSED,
        pause_reason="media_player_error",
        detail="Failed to get song stream metadata",
    )
    body = await _over_rest(state, _handler())
    assert body["message_key"] != "START_FAILED_NO_SONGS"
    assert "no songs" not in body["message"].lower()


async def test_rest_failure_broadcasts_the_paused_state():
    """#949 parity: the room must leave the loader for the recovery banner."""
    handler = _handler()
    state = _failing_start(
        _lobby(), phase=GamePhase.PAUSED, pause_reason="media_player_error"
    )
    await _over_rest(state, handler)
    handler.broadcast_state.assert_awaited()
