"""#2574: the finale tiebreaker must also fire when the last round ends by timer.

`maybe_start_finale_playoff` only starts a playoff while ``phase == REVEAL`` —
deliberately, because a tie is only real once the round that produced it has
final scores. The manual path (``admin_next_round``) checks ``last_round`` and
calls the game-end gate straight from REVEAL. The auto-advance path called
``start_round()`` instead, which flips the phase to END on an exhausted
playlist; by the time the gate ran, the playoff had already declined itself.

Result before the fix: with the tiebreaker enabled and two players tied at the
top, the game ended in a shared win whenever the host let the reveal timer run
out instead of tapping Next.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import custom_components.beatify.game.state_auto_advance as auto_advance_mod
from custom_components.beatify.game.state import GamePhase
from tests.conftest import make_game_state


def _game_in_reveal(monkeypatch, *, last_round: bool):
    state = make_game_state()
    monkeypatch.setattr(auto_advance_mod.asyncio, "sleep", AsyncMock())
    state._song_finished = MagicMock(return_value=True)
    state._on_round_end = AsyncMock()
    state.phase = GamePhase.REVEAL
    state.last_round = last_round
    return state


class TestFinaleTiebreakerOnAutoAdvance:
    async def test_last_round_ends_from_reveal(self, monkeypatch):
        """The gate has to run while the phase is still REVEAL."""
        state = _game_in_reveal(monkeypatch, last_round=True)
        gesehen: list[GamePhase] = []

        async def _gate() -> None:
            gesehen.append(state.phase)

        state._on_game_end = AsyncMock(side_effect=_gate)
        state.start_round = AsyncMock()

        await state._reveal_auto_advance(0)

        state._on_game_end.assert_awaited_once()
        assert gesehen == [GamePhase.REVEAL]
        # start_round would have flipped the phase to END before the gate.
        state.start_round.assert_not_awaited()

    async def test_normal_round_still_starts_the_next_one(self, monkeypatch):
        """Everything that is not the last round is untouched."""
        state = _game_in_reveal(monkeypatch, last_round=False)
        state._on_game_end = AsyncMock()
        state.start_round = AsyncMock(return_value=True)

        await state._reveal_auto_advance(0)

        state.start_round.assert_awaited_once()
        state._on_game_end.assert_not_awaited()

    async def test_last_round_without_a_wired_gate_falls_back(self, monkeypatch):
        """REST/service path and older tests wire no handler — the old route
        through ``start_round()`` still has to work there."""
        state = _game_in_reveal(monkeypatch, last_round=True)
        state._on_game_end = None

        async def _exhausted() -> bool:
            state.phase = GamePhase.END
            return False

        state.start_round = AsyncMock(side_effect=_exhausted)
        state.advance_to_end = AsyncMock()

        await state._reveal_auto_advance(0)

        state.start_round.assert_awaited_once()
        state.advance_to_end.assert_awaited_once()
