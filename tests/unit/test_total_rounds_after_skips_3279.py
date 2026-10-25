"""Skipped songs must shorten the "of N" round counter (#3279).

A song dropped by a playback failure is marked played without a round being
committed, so the game ends early. ``total_rounds`` has to follow, otherwise the
final reveal reads "Round 7 of 10" next to a "Final Results" button.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.beatify.game.state import GamePhase
from tests.conftest import make_game_state, make_songs


def _make_game(n: int = 5):
    gs = make_game_state()
    gs.create_game(
        playlists=["test.json"],
        songs=make_songs(n),
        media_player="media_player.esszimmer",
        base_url="http://localhost:8123",
    )
    svc = MagicMock()
    svc.is_available.return_value = True
    svc.last_failure_reason = None
    svc.last_attempted_uri = None
    svc.play_song = AsyncMock(return_value=True)
    svc.stop = AsyncMock(return_value=True)
    gs._media_player_service = svc
    gs.media_player = "media_player.esszimmer"
    gs.platform = "music_assistant"
    return gs, svc


@pytest.mark.asyncio
async def test_skipped_songs_lower_total_rounds() -> None:
    gs, svc = _make_game(5)
    assert gs.total_rounds == 5

    results = iter([False, True])  # first song unavailable, second plays

    async def play(_song):
        ok = next(results)
        svc.last_failure_reason = None if ok else "unavailable"
        return ok

    svc.play_song = AsyncMock(side_effect=play)

    await gs.start_round()

    assert gs.phase is GamePhase.PLAYING
    assert gs.round == 1
    assert gs.total_rounds == 4
    assert gs._playlist_manager.get_remaining_count() == 3
