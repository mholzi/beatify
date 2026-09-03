"""#2544: a failed auto-advance that pauses the game must still broadcast.

`pause_game` only notifies the HA sensors, so when `start_round()` fails by
pausing (three playback timeouts, a rate limit) the backend sits in PAUSED
while every client still renders REVEAL with a Next button that answers
ERR_INVALID_ACTION. The recovery banner carrying Resume never appears and only
a page reload gets the host out. `admin_next_round` already broadcasts on this
branch; the auto path did not.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock


import custom_components.beatify.game.state_auto_advance as auto_advance_mod
from custom_components.beatify.game.state import GamePhase
from tests.conftest import make_game_state


def _game_in_reveal(monkeypatch):
    state = make_game_state()
    monkeypatch.setattr(auto_advance_mod.asyncio, "sleep", AsyncMock())
    state._song_finished = MagicMock(return_value=True)
    state._on_round_end = AsyncMock()
    state.phase = GamePhase.REVEAL
    return state


class TestAutoAdvancePauseBroadcast:
    async def test_pause_during_auto_advance_is_broadcast(self, monkeypatch):
        state = _game_in_reveal(monkeypatch)

        async def _pause() -> bool:
            state.phase = GamePhase.PAUSED
            return False

        state.start_round = AsyncMock(side_effect=_pause)

        await state._reveal_auto_advance(0)

        state._on_round_end.assert_awaited_once()

    async def test_failure_without_pause_still_stays_quiet(self, monkeypatch):
        """A failed start that leaves the phase on REVEAL is the pre-existing
        retry case and must not gain a spurious broadcast."""
        state = _game_in_reveal(monkeypatch)

        async def _fail() -> bool:
            return False

        state.start_round = AsyncMock(side_effect=_fail)

        await state._reveal_auto_advance(0)

        state._on_round_end.assert_not_awaited()

    async def test_successful_advance_still_broadcasts(self, monkeypatch):
        state = _game_in_reveal(monkeypatch)

        async def _ok() -> bool:
            state.phase = GamePhase.PLAYING
            return True

        state.start_round = AsyncMock(side_effect=_ok)

        await state._reveal_auto_advance(0)

        state._on_round_end.assert_awaited_once()
