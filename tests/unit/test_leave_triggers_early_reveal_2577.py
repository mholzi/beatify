"""#2577: leaving on purpose has to trigger the early reveal too.

Four players, three have submitted. The fourth does not know the song and taps
"leave game" instead of guessing. Before this fix the other three sat on
"waiting for the others" until the round timer ran out — even though nobody was
outstanding any more.

A dropped connection from the same player would have ended the round at once:
that is #928, checked in `_handle_disconnect`. But that check resolves the
player through `get_player_by_ws`, and `handle_leave` has already removed them,
so it returns before reaching it. The deliberate exit was the one case that
stalled the room.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.beatify.server.ws_handlers.lifecycle import handle_leave


def _handler_and_state(*, is_admin: bool = False):
    spieler = MagicMock()
    spieler.name = "Ben"
    spieler.is_admin = is_admin

    state = MagicMock()
    state.get_player_by_ws = MagicMock(return_value=spieler)
    state.remove_player = MagicMock()
    state.trigger_early_reveal_if_complete = AsyncMock()

    handler = MagicMock()
    handler.broadcast_state = AsyncMock()

    ws = MagicMock()
    ws.send_json = AsyncMock()
    ws.close = AsyncMock()
    return handler, ws, state, spieler


class TestLeaveTriggersEarlyReveal:
    @pytest.mark.asyncio
    async def test_leave_checks_for_early_reveal(self):
        handler, ws, state, _ = _handler_and_state()

        await handle_leave(handler, ws, {}, state)

        state.remove_player.assert_called_once_with("Ben")
        state.trigger_early_reveal_if_complete.assert_awaited_once()
        handler.broadcast_state.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_a_failing_check_does_not_break_the_leave(self):
        """The player is already gone — a check that raises must not swallow
        the broadcast, or the room never learns they left."""
        handler, ws, state, _ = _handler_and_state()
        state.trigger_early_reveal_if_complete = AsyncMock(
            side_effect=RuntimeError("boom")
        )

        await handle_leave(handler, ws, {}, state)

        handler.broadcast_state.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_host_cannot_leave_and_nothing_is_checked(self):
        handler, ws, state, _ = _handler_and_state(is_admin=True)

        await handle_leave(handler, ws, {}, state)

        state.remove_player.assert_not_called()
        state.trigger_early_reveal_if_complete.assert_not_awaited()
