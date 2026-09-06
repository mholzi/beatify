"""The consecutive playback-failure budget must not leak across games (#2614).

``_consecutive_playback_failures`` is the #1936 budget: the first timeouts in a
row skip the song silently, and only ``MAX_CONSECUTIVE_PLAYBACK_FAILURES`` of
them in a row mean "systemic" and pause the game with the re-authenticate
banner. The counter was cleared on a confirmed start and when the budget was
spent, but by no lifecycle boundary — so a game that ended two timeouts deep
handed the next game a budget of one, and a single slow start in its round 1
ended the evening for a provider that was working.

These tests pin the reset at all three boundaries that mint a new game
identity (``create_game`` / ``end_game`` / ``rematch_game``), plus the
behavior the host actually notices.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.beatify.const import MAX_CONSECUTIVE_PLAYBACK_FAILURES
from tests.conftest import make_game_state, make_songs


def _stub_media_service() -> MagicMock:
    svc = MagicMock()
    svc.is_available.return_value = True
    svc.last_failure_reason = "error"
    svc.last_attempted_uri = "apple_music://track/1122776156"
    svc.play_song = AsyncMock(return_value=True)
    svc.stop = AsyncMock(return_value=True)
    svc.restore_volume = AsyncMock(return_value=True)
    svc.restore_queue = AsyncMock(return_value=True)
    return svc


def _make_game():
    """A created game wired to a stub speaker, ready for start_round()."""
    gs = make_game_state()
    gs.create_game(
        playlists=["test.json"],
        songs=make_songs(30),
        media_player="media_player.esszimmer",
        base_url="http://localhost:8123",
    )
    gs._media_player_service = _stub_media_service()
    gs.media_player = "media_player.esszimmer"
    gs.platform = "music_assistant"
    return gs


# --------------------------------------------------------- the three boundaries


def test_create_game_clears_the_streak() -> None:
    gs = _make_game()
    gs._consecutive_playback_failures = MAX_CONSECUTIVE_PLAYBACK_FAILURES - 1

    gs.create_game(
        playlists=["test.json"],
        songs=make_songs(30),
        media_player="media_player.esszimmer",
        base_url="http://localhost:8123",
    )

    assert gs._consecutive_playback_failures == 0


@pytest.mark.asyncio
async def test_end_game_clears_the_streak() -> None:
    gs = _make_game()
    gs._consecutive_playback_failures = MAX_CONSECUTIVE_PLAYBACK_FAILURES - 1

    await gs.end_game()

    assert gs._consecutive_playback_failures == 0


def test_rematch_game_clears_the_streak() -> None:
    gs = _make_game()
    gs._consecutive_playback_failures = MAX_CONSECUTIVE_PLAYBACK_FAILURES - 1

    gs.rematch_game()

    assert gs._consecutive_playback_failures == 0


# ------------------------------------------------------------ what the host sees


@pytest.mark.asyncio
async def test_a_finished_game_does_not_shorten_the_next_games_budget() -> None:
    """Game A ended two timeouts deep; one timeout in game B must still skip.

    This is the report in #2614: the host ends a game whose last two songs
    timed out, starts a fresh one, and round 1 pauses on the re-authenticate
    banner after a single slow start instead of moving to the next song.
    """
    gs = _make_game()
    # Game A limps to its end one timeout short of the budget.
    gs._consecutive_playback_failures = MAX_CONSECUTIVE_PLAYBACK_FAILURES - 1
    await gs.end_game()

    # Game B — a fresh session on the same GameState.
    gs.create_game(
        playlists=["test.json"],
        songs=make_songs(30),
        media_player="media_player.esszimmer",
        base_url="http://localhost:8123",
    )
    svc = _stub_media_service()
    # Round 1 times out once, the next song plays.
    svc.play_song = AsyncMock(side_effect=[False, True])
    gs._media_player_service = svc
    gs.media_player = "media_player.esszimmer"
    gs.platform = "music_assistant"
    gs.pause_game = AsyncMock()

    with patch(
        "custom_components.beatify.game.state.asyncio.sleep",
        new_callable=AsyncMock,
    ):
        await gs.start_round()

    gs.pause_game.assert_not_awaited()
    assert svc.play_song.await_count == 2
