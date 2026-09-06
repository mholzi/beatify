"""#2605: every way a game can end has to stop the speaker.

The reopened #2605 was two defects wearing one title. The loud one is in
``MediaPlayerService._pause_and_confirm`` — see
``test_queue_restore_stays_paused_2605.py``. The quiet one is here: not every
route to the podium asked the speaker to stop.

``advance_to_end`` is the documented universal terminal (see the phase-table
comment in ``game/state.py``), but the stop lived in its *callers*:

* ``admin_end_game`` — host taps End: stops first. ✅
* ``admin_next_round`` on the last round: stops first. ✅
* REST ``/beatify/api/end-game``: stops first. ✅
* the unattended final round — ``_reveal_auto_advance`` — does not. ❌

That last one is the round-exhaustion path, and it is not only reached when the
song has finished. Its wait loop breaks on ``self._song_finished() or elapsed >=
hard_cap``, where ``hard_cap`` is the configured REVEAL timer. With a REVEAL
timer set, the final round therefore ends *while the round's song is still
playing* and hands straight over to the game-end ceremony — podium on the TV,
Beatify's own track still on the speaker.

So the stop belongs at the terminal, where every route passes. It is idempotent,
so the callers that already stop lose nothing.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from custom_components.beatify.game.state import GamePhase
from tests.conftest import make_game_state, make_songs


def _game_in_reveal():
    game = make_game_state()
    game.create_game(
        playlists=["test.json"],
        songs=make_songs(2),
        media_player="media_player.esszimmer",
        base_url="http://localhost:8123",
    )
    game._set_phase(GamePhase.PLAYING)
    game._set_phase(GamePhase.REVEAL)
    game._media_player_service = AsyncMock()
    game._party_lights = None
    return game


class TestAdvanceToEndStopsTheSpeaker:
    @pytest.mark.asyncio
    async def test_the_terminal_stops_playback(self):
        """The unattended final round reaches END through here and nowhere else."""
        game = _game_in_reveal()

        await game.advance_to_end()

        assert game.phase is GamePhase.END
        game._media_player_service.stop.assert_awaited()

    @pytest.mark.asyncio
    async def test_the_stop_runs_before_the_podium_announcement(self):
        """announce_winner speaks through the same speaker.

        Stopping afterwards would cut the podium off mid-sentence, which is
        why the stop sits directly after the phase flip rather than at the end
        of the ceremony.
        """
        game = _game_in_reveal()
        order: list[str] = []
        game._media_player_service.stop = AsyncMock(
            side_effect=lambda: order.append("stop")
        )
        game.announce_winner = AsyncMock(side_effect=lambda: order.append("winner"))
        game.announce_podium = AsyncMock(side_effect=lambda: order.append("podium"))

        await game.advance_to_end()

        assert order == ["stop", "winner", "podium"]

    @pytest.mark.asyncio
    async def test_a_failing_stop_does_not_cost_the_podium(self):
        """A speaker that is gone must not take the end screen down with it."""
        game = _game_in_reveal()
        game._media_player_service.stop = AsyncMock(side_effect=RuntimeError("gone"))

        await game.advance_to_end()

        assert game.phase is GamePhase.END

    @pytest.mark.asyncio
    async def test_no_media_player_is_not_an_error(self):
        """Games without a speaker (no round ever started) end normally."""
        game = _game_in_reveal()
        game._media_player_service = None

        await game.advance_to_end()

        assert game.phase is GamePhase.END
