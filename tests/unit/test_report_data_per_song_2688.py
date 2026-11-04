"""#2688: one data-quality report per song per game.

#2579 capped reports per (player, round). Joining needs nothing but a name, so
one phone can open twenty sockets under twenty names and file one public
GitHub issue each per reveal. The song is the thing being reported, so the
song is what the second gate keys on.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.beatify.game.state import GamePhase
from custom_components.beatify.server.ws_handlers import handle_report_data


def _spieler(name: str):
    p = MagicMock()
    p.name = name
    p.reported_round = None
    return p


def _aufbau(song=None):
    gs = MagicMock()
    gs.phase = GamePhase.REVEAL
    gs.round = 3
    gs.game_id = "g1"
    gs.reported_songs = set()
    gs.current_song = song or {
        "artist": "Joe Cocker",
        "title": "You Can Leave Your Hat On",
        "year": 1986,
        "_playlist_source": "80er-hits.json",
    }

    handler = MagicMock()
    handler.hass = MagicMock()
    handler.hass.async_add_executor_job = AsyncMock()

    def _schluck(coro, name=None):
        coro.close()

    handler.hass.async_create_background_task = MagicMock(side_effect=_schluck)
    return handler, gs


async def _melde(handler, gs, spieler):
    ws = MagicMock()
    ws.send_json = AsyncMock()
    gs.get_player_by_ws = MagicMock(return_value=spieler)
    await handle_report_data(handler, ws, {}, gs)
    return ws.send_json.await_args.args[0]


class TestOneReportPerSong:
    @pytest.mark.asyncio
    async def test_twenty_names_file_one_issue(self):
        handler, gs = _aufbau()

        acks = [await _melde(handler, gs, _spieler(f"Gast{i}")) for i in range(20)]

        handler.hass.async_create_background_task.assert_called_once()
        handler.hass.async_add_executor_job.assert_awaited_once()
        assert acks[0] == {"type": "report_data_ack"}
        assert all(
            a == {"type": "report_data_ack", "duplicate": True} for a in acks[1:]
        )

    @pytest.mark.asyncio
    async def test_case_does_not_make_a_new_song(self):
        handler, gs = _aufbau()
        await _melde(handler, gs, _spieler("A"))
        gs.current_song = {**gs.current_song, "artist": "JOE COCKER"}
        gs.round = 4

        await _melde(handler, gs, _spieler("B"))

        handler.hass.async_create_background_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_a_different_song_still_goes_through(self):
        handler, gs = _aufbau()
        await _melde(handler, gs, _spieler("A"))
        gs.round = 4
        gs.current_song = {"artist": "Nena", "title": "99 Luftballons", "year": 1983}

        await _melde(handler, gs, _spieler("B"))

        assert handler.hass.async_create_background_task.call_count == 2


class TestResetWithTheGame:
    def test_a_fresh_state_starts_empty(self):
        from custom_components.beatify.game.state import GameState

        assert GameState().reported_songs == set()
