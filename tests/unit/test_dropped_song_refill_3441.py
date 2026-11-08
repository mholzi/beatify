"""A dropped song is replaced from the round cap's reserve (#3441).

Spotify via Music Assistant, rate-limited: four playable songs timed out and
were dropped from a 98-song playlist capped at 10 rounds. Each drop lowered
``total_rounds`` (#3279), so the game ended after six rounds although 88 songs
were still held back in the reserve (#2547). The host's song swap already
refills from the reserve (#3321); a dropped song now does the same.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.beatify.game.config import GameOptions
from custom_components.beatify.game.state import GamePhase
from tests.conftest import make_game_state, make_songs


def _make_game(songs: int, max_rounds: int):
    gs = make_game_state()
    gs.create_game(
        playlists=["test.json"],
        songs=make_songs(songs),
        media_player="media_player.esszimmer",
        base_url="http://localhost:8123",
        options=GameOptions(max_rounds=max_rounds),
    )
    svc = MagicMock()
    svc.is_available.return_value = True
    svc.last_failure_reason = None
    svc.last_attempted_uri = None
    svc.stop = AsyncMock(return_value=True)
    gs._media_player_service = svc
    gs.media_player = "media_player.esszimmer"
    gs.platform = "music_assistant"
    return gs, svc


def _fail_then_play(svc, failures: int, reason: str) -> None:
    results = iter([False] * failures + [True])

    async def play(_song):
        ok = next(results)
        svc.last_failure_reason = None if ok else reason
        return ok

    svc.play_song = AsyncMock(side_effect=play)


@pytest.mark.asyncio
@pytest.mark.parametrize("reason", ["unavailable", "rate_limited"])
async def test_dropped_song_keeps_total_rounds_with_reserve(reason: str) -> None:
    gs, svc = _make_game(songs=30, max_rounds=10)
    manager = gs._playlist_manager
    assert gs.total_rounds == 10
    reserve_before = manager.reserve_count()
    assert reserve_before == 20

    _fail_then_play(svc, failures=1, reason=reason)
    await gs.start_round()

    assert gs.phase is GamePhase.PLAYING
    assert gs.round == 1
    assert gs.total_rounds == 10
    assert manager.reserve_count() == reserve_before - 1
    # Round 1 played, one song dropped and replaced: nine still to come.
    assert manager.get_remaining_count() == 9


@pytest.mark.asyncio
async def test_dropped_song_still_shortens_game_without_reserve() -> None:
    """No reserve left: the #3279 accounting still lowers the total."""
    gs, svc = _make_game(songs=5, max_rounds=10)
    assert gs.total_rounds == 5
    assert gs._playlist_manager.reserve_count() == 0

    _fail_then_play(svc, failures=1, reason="unavailable")
    await gs.start_round()

    assert gs.round == 1
    assert gs.total_rounds == 4
