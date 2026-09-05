"""#2579: one data-quality report per player and round.

The report button sits next to the reveal, and players are deliberately not
authenticated — that is the point of a party game where guests scan a QR code.
Without a guard, one guest with a script could raise arbitrarily many
**public GitHub issues** from a single reveal phase and inflate
`data_quality_reports.json` until every further write got more expensive
(the file is fully read and rewritten each time).

The `disabled` attribute on the button lives in the frontend and is bypassable.

The Crate Digger counterpart in the same module has always capped itself —
"must never be able to grow unboundedly from repeated taps". This path now
does the same.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.beatify.game.state import GamePhase
from custom_components.beatify.server.ws_handlers import (
    MAX_DATA_QUALITY_REPORTS,
    _write_report,
    handle_report_data,
)


def _aufbau(runde: int = 7):
    spieler = MagicMock()
    spieler.name = "Ben"
    spieler.reported_round = None

    gs = MagicMock()
    gs.phase = GamePhase.REVEAL
    gs.round = runde
    gs.game_id = "g1"
    gs.get_player_by_ws = MagicMock(return_value=spieler)
    gs.current_song = {
        "artist": "Joe Cocker",
        "title": "You Can Leave Your Hat On",
        "year": 1986,
        "_playlist_source": "80er-hits.json",
    }

    handler = MagicMock()
    handler.hass = MagicMock()
    handler.hass.async_add_executor_job = AsyncMock()

    # Die Coroutine `_create_gh_issue` wird gebaut, aber nie erwartet — HA
    # nimmt sie sonst in seine Task-Registry. Hier schliessen wir sie, damit
    # pytest keine „never awaited"-Warnung wirft und die Absicht sichtbar ist.
    def _schluck(coro, name=None):
        coro.close()

    handler.hass.async_create_background_task = MagicMock(side_effect=_schluck)

    ws = MagicMock()
    ws.send_json = AsyncMock()
    return handler, ws, gs, spieler


class TestOneReportPerRound:
    @pytest.mark.asyncio
    async def test_the_first_report_goes_through(self):
        handler, ws, gs, spieler = _aufbau()

        await handle_report_data(handler, ws, {}, gs)

        handler.hass.async_add_executor_job.assert_awaited_once()
        handler.hass.async_create_background_task.assert_called_once()
        assert spieler.reported_round == 7

    @pytest.mark.asyncio
    async def test_the_second_one_in_the_same_round_does_not(self):
        handler, ws, gs, spieler = _aufbau()

        await handle_report_data(handler, ws, {}, gs)
        handler.hass.async_add_executor_job.reset_mock()
        handler.hass.async_create_background_task.reset_mock()

        await handle_report_data(handler, ws, {}, gs)

        handler.hass.async_add_executor_job.assert_not_awaited()
        handler.hass.async_create_background_task.assert_not_called()
        # The player still gets an answer — silence would read as a broken button.
        letzte = ws.send_json.await_args_list[-1].args[0]
        assert letzte["type"] == "report_data_ack"
        assert letzte["duplicate"] is True

    @pytest.mark.asyncio
    async def test_the_next_round_may_report_again(self):
        handler, ws, gs, spieler = _aufbau()
        await handle_report_data(handler, ws, {}, gs)
        handler.hass.async_add_executor_job.reset_mock()

        gs.round = 8
        await handle_report_data(handler, ws, {}, gs)

        handler.hass.async_add_executor_job.assert_awaited_once()
        assert spieler.reported_round == 8


class TestFileCap:
    def test_the_file_stops_growing(self, tmp_path):
        pfad = tmp_path / "beatify" / "data_quality_reports.json"
        for i in range(MAX_DATA_QUALITY_REPORTS + 25):
            _write_report(pfad, {"n": i})

        inhalt = json.loads(pfad.read_text(encoding="utf-8"))
        assert len(inhalt) == MAX_DATA_QUALITY_REPORTS
        # The newest survive — the oldest are already GitHub issues.
        assert inhalt[-1]["n"] == MAX_DATA_QUALITY_REPORTS + 24
