"""`last_round` describes a committed round, not one that is still starting (#3116).

`_start_round_locked` used to raise `last_round` for the upcoming round before
asking the speaker to play. Starting a song takes 4–25 s on Music Assistant,
and for all of that time the phase is still the previous round's REVEAL — the
one phase in which two consumers read the flag and end the game when it is set
(`admin_next_round` and the reveal auto-advance).

So a tap on Next, a pause or an unreachable speaker during the start of the
final round ended the game with its last song unplayed, and the stats recorded
one round too few.

The flag, the encore window and the round's returning-players list now change
together at the point where the round is committed. A start that is parked or
aborted leaves all three as the reveal had them.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.beatify.game.state import GamePhase
from tests.conftest import make_game_state, make_songs


def _stub_media_service() -> MagicMock:
    svc = MagicMock()
    svc.is_available.return_value = True
    svc.play_song = AsyncMock(return_value=True)
    svc.verify_responsive = AsyncMock(return_value=(True, None))
    svc.restore_volume = AsyncMock(return_value=True)
    svc.restore_queue = AsyncMock(return_value=True)
    svc.stop = AsyncMock(return_value=True)
    return svc


async def _game_before_its_final_round(songs: int = 3):
    """A game sitting in REVEAL with exactly one song left to play."""
    gs = make_game_state()
    gs.create_game(
        playlists=["t.json"],
        songs=make_songs(songs),
        media_player="media_player.x",
        base_url="http://h",
    )
    gs._media_player_service = _stub_media_service()
    gs.platform = "music_assistant"
    ws = MagicMock()
    ws.closed = False
    gs.add_player("Alice", ws)
    gs.get_player("Alice").connected = True

    for _ in range(songs - 1):
        assert await gs.start_round() is True
        assert gs.last_round is False
    gs.phase = GamePhase.REVEAL
    assert gs._playlist_manager.get_remaining_count() == 1
    return gs


class TestWhileTheFinalRoundIsStarting:
    @pytest.mark.asyncio
    async def test_flag_stays_down_until_the_song_has_started(self):
        gs = await _game_before_its_final_round()
        seen: dict[str, object] = {}

        async def play_song(_song):
            seen["phase"] = gs.phase
            seen["last_round"] = gs.last_round
            return True

        gs._media_player_service.play_song = AsyncMock(side_effect=play_song)

        assert await gs.start_round() is True

        # Parked in play_song: still the previous round's REVEAL, and nothing
        # may tell its consumers that the round on screen is the final one.
        assert seen == {"phase": GamePhase.REVEAL, "last_round": False}
        # Committed: now it is the final round.
        assert gs.phase is GamePhase.PLAYING
        assert gs.last_round is True

    @pytest.mark.asyncio
    async def test_encore_offer_and_returning_list_wait_for_the_commit(self):
        gs = await _game_before_its_final_round()
        gs._encore_window = True
        gs._returned_this_round = ["Bob"]
        gs.apply_pending_rejoins = MagicMock(return_value=["Carol"])
        seen: dict[str, object] = {}

        async def play_song(_song):
            seen["encore"] = gs._encore_window
            seen["returned"] = list(gs._returned_this_round)
            seen["rejoins_applied"] = gs.apply_pending_rejoins.called
            return True

        gs._media_player_service.play_song = AsyncMock(side_effect=play_song)

        assert await gs.start_round() is True

        assert seen == {"encore": True, "returned": ["Bob"], "rejoins_applied": False}
        assert gs._encore_window is False
        assert gs._returned_this_round == ["Carol"]


class TestAStartThatDoesNotHappen:
    @pytest.mark.asyncio
    async def test_pause_during_the_start_leaves_the_flag_down(self):
        gs = await _game_before_its_final_round()
        gs._encore_window = True
        gs.apply_pending_rejoins = MagicMock(return_value=["Carol"])

        async def play_song(_song):
            await gs.pause_game("admin_disconnected")
            return True

        gs._media_player_service.play_song = AsyncMock(side_effect=play_song)

        assert await gs.start_round() is False

        assert gs.phase is GamePhase.PAUSED
        assert gs.last_round is False
        # The reveal that will be resumed still carries its encore offer, and
        # the parked guests are still waiting for a round that really starts.
        assert gs._encore_window is True
        gs.apply_pending_rejoins.assert_not_called()
        # The song was not consumed: the final round is still to be played.
        assert gs._playlist_manager.get_remaining_count() == 1

    @pytest.mark.asyncio
    async def test_unavailable_speaker_leaves_the_flag_down(self):
        gs = await _game_before_its_final_round()
        gs._media_player_service.is_available.return_value = False

        assert await gs.start_round() is False

        assert gs.phase is GamePhase.PAUSED
        assert gs.last_round is False
        assert gs._playlist_manager.get_remaining_count() == 1

    @pytest.mark.asyncio
    async def test_retry_after_the_aborted_start_plays_the_final_round(self):
        gs = await _game_before_its_final_round()
        gs._media_player_service.is_available.return_value = False
        assert await gs.start_round() is False

        gs._media_player_service.is_available.return_value = True
        gs.phase = GamePhase.REVEAL
        assert await gs.start_round() is True

        assert gs.phase is GamePhase.PLAYING
        assert gs.last_round is True
