"""#3340: a stale admin next_round must not reveal a round that just started."""

from __future__ import annotations

from unittest.mock import AsyncMock

from custom_components.beatify.const import STALE_NEXT_ROUND_WINDOW_SECONDS
from custom_components.beatify.game.state import GamePhase
from custom_components.beatify.server.ws_handlers import admin_next_round
from tests.unit.test_websocket import _make_handler_and_game


def _playing(started_ago: float | None):
    handler, game_state, ws = _make_handler_and_game()
    game_state.phase = GamePhase.PLAYING
    game_state.round = 4
    now = 1_000_000.0
    game_state._now = lambda: now
    game_state.round_start_time = None if started_ago is None else now - started_ago
    game_state.end_round = AsyncMock()
    handler.broadcast_state = AsyncMock()
    return handler, game_state, ws


async def test_next_round_right_after_start_is_ignored(caplog):
    handler, game_state, ws = _playing(0.06)
    with caplog.at_level("INFO"):
        await admin_next_round(handler, ws, {"action": "next_round"}, game_state)
    game_state.end_round.assert_not_awaited()
    assert game_state.phase == GamePhase.PLAYING
    lines = [r.message for r in caplog.records if "stale next_round" in r.message]
    assert len(lines) == 1
    assert "round 4" in lines[0]
    assert "60 ms" in lines[0]


async def test_next_round_after_window_still_reveals():
    handler, game_state, ws = _playing(STALE_NEXT_ROUND_WINDOW_SECONDS + 0.5)
    await admin_next_round(handler, ws, {"action": "next_round"}, game_state)
    game_state.end_round.assert_awaited_once()


async def test_next_round_without_start_time_still_reveals():
    handler, game_state, ws = _playing(None)
    await admin_next_round(handler, ws, {"action": "next_round"}, game_state)
    game_state.end_round.assert_awaited_once()
