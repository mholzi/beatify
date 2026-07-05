"""#1763: non-phase-changing in-round broadcasts must be coalesced.

The per-player in-round events (year submit progress, guess/vote tallies,
disconnect flags) used to call ``broadcast_state()`` directly — one full
get_state + redact + 2x json.dumps + N send_str per event, i.e. O(N^2) work on
a busy round. They now route through ``debounced_broadcast_state()`` (50ms
coalescing window). The *phase transition* out of PLAYING (round end -> REVEAL)
still broadcasts immediately via the round_end callback, so clients never wait
for the debounce to see the reveal.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.beatify.const import DOMAIN
from custom_components.beatify.game.state import GamePhase
from tests.conftest import make_game_state, make_songs

from custom_components.beatify.server.websocket import (  # isort: skip
    BeatifyWebSocketHandler,
)

pytestmark = pytest.mark.asyncio


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


async def _playing_game_with_two_players():
    """A PLAYING game with an admin (Alice) + a regular player (Bob)."""
    mock_hass = MagicMock()
    gs = make_game_state()
    gs.create_game(
        playlists=["t.json"],
        songs=make_songs(3),
        media_player="media_player.x",
        base_url="http://h",
    )
    gs._media_player_service = _stub_media_service()
    gs.platform = "music_assistant"
    mock_hass.data = {DOMAIN: {"game": gs}}

    handler = BeatifyWebSocketHandler(mock_hass)
    handler.broadcast_state = AsyncMock()
    handler.broadcast = AsyncMock()
    handler.debounced_broadcast_state = AsyncMock()
    # Mirror production wiring: the round-end reveal broadcasts immediately.
    gs.set_round_end_callback(handler.broadcast_state)

    alice_ws, bob_ws = _ws(), _ws()
    gs.add_player("Alice", alice_ws)
    gs.add_player("Bob", bob_ws)
    gs.get_player("Alice").connected = True
    gs.get_player("Bob").connected = True
    gs.get_player("Alice").is_admin = True
    gs.get_player("Bob").is_admin = False
    handler.connections.update({alice_ws, bob_ws})

    await gs.start_round()
    assert gs.phase == GamePhase.PLAYING
    return handler, gs, alice_ws, bob_ws


class TestInRoundBroadcastsDebounced:
    async def test_submit_progress_is_debounced_not_immediate(self):
        """A submit that does NOT complete the round coalesces via debounce."""
        handler, gs, alice_ws, bob_ws = await _playing_game_with_two_players()

        # Only Alice submits → Bob still outstanding → round NOT complete.
        await handler._handle_message(alice_ws, {"type": "submit", "year": 1985})

        handler.debounced_broadcast_state.assert_awaited()
        # No phase transition happened → no immediate broadcast.
        handler.broadcast_state.assert_not_awaited()

        gs._cancel_auto_advance()

    async def test_round_end_broadcasts_immediately(self):
        """The completing submit skips the debounce and reveals immediately."""
        handler, gs, alice_ws, bob_ws = await _playing_game_with_two_players()

        await handler._handle_message(alice_ws, {"type": "submit", "year": 1985})
        # Reset so we observe ONLY the completing submit's broadcasts.
        handler.debounced_broadcast_state.reset_mock()
        handler.broadcast_state.reset_mock()

        # Bob submits → round complete → early reveal fires the round_end
        # callback, which is the immediate broadcast_state.
        await handler._handle_message(bob_ws, {"type": "submit", "year": 1990})

        assert gs.phase == GamePhase.REVEAL
        # Immediate reveal broadcast, and NOT the debounced in-round path.
        handler.broadcast_state.assert_awaited()
        handler.debounced_broadcast_state.assert_not_awaited()

        gs._cancel_auto_advance()

    async def test_disconnect_flag_is_debounced(self):
        """A mid-round disconnect coalesces the connected=False flag broadcast."""
        handler, gs, alice_ws, bob_ws = await _playing_game_with_two_players()

        # Regular player Bob drops while the round is still open (Alice has not
        # submitted) → no reveal, no admin pause → only the flag broadcast.
        await handler._handle_disconnect(bob_ws)

        assert gs.get_player("Bob").connected is False
        handler.debounced_broadcast_state.assert_awaited()
        handler.broadcast_state.assert_not_awaited()

        gs._cancel_auto_advance()
