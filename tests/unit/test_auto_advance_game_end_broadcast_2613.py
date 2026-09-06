"""#2613: ending the last round by timer must broadcast the new state.

The #2574 branch calls the game-end gate straight from REVEAL and returned
immediately, before the broadcast at the end of ``_reveal_auto_advance``. The
gate (``finalize_and_end``) records stats and runs ``advance_to_end``; neither
pushes anything to the sockets. ``admin_next_round`` awaits ``broadcast_state()``
right after the gate — the auto path did not.

Result before the fix: the host lets the final reveal timer run out, the backend
moves to END, stats are written and the podium TTS plays, while every phone and
the TV stay on REVEAL until someone reloads. With the finale tiebreaker armed it
is worse: the gate starts the playoff round in PLAYING with a new song while the
clients still show REVEAL, so the tied leaders cannot guess and the round runs
out empty.
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
    state.last_round = True
    state.start_round = AsyncMock()
    return state


class TestAutoAdvanceGameEndBroadcast:
    async def test_unattended_game_end_is_broadcast(self, monkeypatch):
        """END reached by timer has to reach the clients, not just the backend."""
        state = _game_in_reveal(monkeypatch)

        async def _end() -> None:
            state.phase = GamePhase.END

        state._on_game_end = AsyncMock(side_effect=_end)

        await state._reveal_auto_advance(0)

        state._on_game_end.assert_awaited_once()
        state._on_round_end.assert_awaited_once()
        # start_round() must stay out of it — that is the #2574 contract.
        state.start_round.assert_not_awaited()

    async def test_broadcast_runs_after_the_game_end_gate(self, monkeypatch):
        """Order matters: the clients must be told about the FINAL state."""
        state = _game_in_reveal(monkeypatch)
        reihenfolge: list[str] = []

        async def _end() -> None:
            reihenfolge.append("game_end")
            state.phase = GamePhase.END

        async def _broadcast() -> None:
            reihenfolge.append(f"broadcast:{state.phase.value}")

        state._on_game_end = AsyncMock(side_effect=_end)
        state._on_round_end = AsyncMock(side_effect=_broadcast)

        await state._reveal_auto_advance(0)

        assert reihenfolge == ["game_end", f"broadcast:{GamePhase.END.value}"]

    async def test_finale_playoff_round_is_broadcast(self, monkeypatch):
        """#1725 tiebreaker: the gate starts a playoff instead of ending.

        The phase goes back to PLAYING with a fresh song. Without the broadcast
        the tied leaders keep staring at REVEAL while their playoff round runs
        out.
        """
        state = _game_in_reveal(monkeypatch)

        async def _playoff() -> None:
            state.phase = GamePhase.PLAYING
            state.last_round = False

        state._on_game_end = AsyncMock(side_effect=_playoff)

        await state._reveal_auto_advance(0)

        state._on_round_end.assert_awaited_once()
        assert state.phase == GamePhase.PLAYING

    async def test_broadcast_failure_does_not_escape(self, monkeypatch):
        """A dead socket must not take the game-end path down with it."""
        state = _game_in_reveal(monkeypatch)
        state._on_game_end = AsyncMock()
        state._on_round_end = AsyncMock(side_effect=ConnectionError("socket gone"))

        await state._reveal_auto_advance(0)

        state._on_round_end.assert_awaited_once()

    async def test_no_broadcast_callback_wired_is_fine(self, monkeypatch):
        """REST/service path wires no handler — nothing to push, no crash."""
        state = _game_in_reveal(monkeypatch)
        state._on_game_end = AsyncMock()
        state._on_round_end = None

        await state._reveal_auto_advance(0)

        state._on_game_end.assert_awaited_once()
