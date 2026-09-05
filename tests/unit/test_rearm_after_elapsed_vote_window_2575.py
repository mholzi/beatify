"""#2575: resuming into an elapsed vote window has to re-arm the auto-advance.

Opening a title/artist vote window takes over the ``_auto_advance_task`` slot.
When the window's deadline passes while the game is paused, ``resume_game``
finalizes the scoring — and used to stop there. REVEAL was then parked with no
song-end advance and no idle-halt, so the game held until the host tapped Next.

The regular window path already re-arms after finalizing (#1755,
``state_vote_window.py``); the resume path never got the same follow-up. The
existing test for this branch mocks ``_finalize_title_artist_window`` and asserts
only that it was awaited, so it could not see the missing re-arm.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from custom_components.beatify.game.state import GamePhase
from tests.conftest import make_game_state


class TestRearmAfterElapsedVoteWindow:
    @pytest.mark.asyncio
    async def test_resume_rearms_auto_advance(self):
        state = make_game_state()
        state.phase = GamePhase.REVEAL
        state._title_artist_voting_open = True
        state._title_artist_vote_deadline = state._now() - 5  # abgelaufen
        await state.pause_game("admin_disconnected")

        state._finalize_title_artist_window = AsyncMock()
        state._schedule_song_end_auto_advance = AsyncMock()

        await state.resume_game()

        state._finalize_title_artist_window.assert_awaited_once()
        state._schedule_song_end_auto_advance.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_rearm_when_finalizing_ended_the_game(self):
        """Finalizing can end the game — then REVEAL is gone and arming a
        song-end advance would schedule work for a round that is over."""
        state = make_game_state()
        state.phase = GamePhase.REVEAL
        state._title_artist_voting_open = True
        state._title_artist_vote_deadline = state._now() - 5
        await state.pause_game("admin_disconnected")

        async def _ends_the_game() -> None:
            state.phase = GamePhase.END

        state._finalize_title_artist_window = AsyncMock(side_effect=_ends_the_game)
        state._schedule_song_end_auto_advance = AsyncMock()

        await state.resume_game()

        state._schedule_song_end_auto_advance.assert_not_called()
