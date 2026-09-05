"""Extracted WebSocket message handlers for Beatify.

Contains game-action handlers (join, submit, admin actions, steal, etc.)
split out from BeatifyWebSocketHandler to reduce module size.
Each function receives (handler, ws, data, game_state) where *handler*
is the BeatifyWebSocketHandler instance (needed for broadcasting and
task management).

See GitHub issue #606.

#1588: the former 1932-line ``ws_handlers.py`` god module is now a package.
Handlers are grouped by domain into submodules and re-exported here so that
every existing ``from ...ws_handlers import X`` import keeps resolving:

* :mod:`._helpers`   — state-redaction + admin-auth helpers
* :mod:`.lifecycle`  — join / reconnect / leave / state / ping / onboarding /
  reaction / round-timeout watchdog
* :mod:`.admin`      — admin connect + the admin action dispatch table and
  every admin sub-handler
* :mod:`.guessing`   — submit / steal / artist / movie / title-artist guess,
  vote and override

The data-quality report handler (#911 / #1384) stays defined here because its
unit tests patch ``ws_handlers.async_get_clientsession`` / ``ws_handlers.aiohttp``
/ ``ws_handlers.asyncio`` directly on this package namespace.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

import aiohttp
from aiohttp import web
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.beatify.game.state import GamePhase, GameState
from custom_components.beatify.server.ws_handlers._helpers import (
    _is_ha_authenticated,
    _send_state_to,
    _ws_companion_trusted,
)
from custom_components.beatify.server.ws_handlers.admin import (
    admin_confirm_intro_splash,
    admin_dismiss_game,
    admin_end_game,
    admin_kick_player,
    admin_next_round,
    admin_rematch_game,
    admin_resume_game,
    admin_seek_forward,
    admin_set_language,
    admin_set_party_lights,
    admin_set_volume,
    admin_start_game,
    admin_stop_lights,
    admin_stop_song,
    admin_toggle_party_lights,
    handle_admin,
    handle_admin_connect,
)
from custom_components.beatify.server.ws_handlers.guessing import (
    _get_steal_error_message,
    handle_artist_guess,
    handle_get_sabotage_targets,
    handle_get_steal_targets,
    handle_movie_guess,
    handle_sabotage,
    handle_steal,
    handle_submit,
    handle_title_artist_guess,
    handle_title_artist_override,
    handle_title_artist_vote,
)
from custom_components.beatify.server.ws_handlers.lifecycle import (
    handle_get_state,
    handle_join,
    handle_leave,
    handle_ping,
    handle_player_onboarded,
    handle_reaction,
    handle_reconnect,
    handle_round_timeout,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from custom_components.beatify.server.websocket import BeatifyWebSocketHandler

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data quality report (Issue #911)
# ---------------------------------------------------------------------------


# #2579: wie viele Meldungen die Datei haelt. Sie ist eine Arbeitsliste fuer den
# music-data-check-Job, kein Archiv — die dauerhafte Spur ist das GitHub-Issue.
MAX_DATA_QUALITY_REPORTS = 500


def _write_report(reports_path: Path, report: dict) -> None:
    """Append a data quality report to the JSON file (blocking I/O).

    Runs in the executor (see ``handle_report_data``) so the mkdir/read/write
    never blocks the HA event loop (Issue #1372).
    """
    reports_path.parent.mkdir(parents=True, exist_ok=True)
    existing: list = []
    if reports_path.exists():
        existing = json.loads(reports_path.read_text(encoding="utf-8"))
    existing.append(report)
    # #2579: Deckel. Die Datei wird bei jedem Report komplett gelesen und neu
    # geschrieben — ohne Grenze wird jeder weitere Eintrag teurer als der
    # vorige. Aeltere fallen hinten weg; wer sie braucht, findet sie als
    # GitHub-Issue, das ist der eigentliche Ausgang dieser Meldungen.
    if len(existing) > MAX_DATA_QUALITY_REPORTS:
        existing = existing[-MAX_DATA_QUALITY_REPORTS:]
    reports_path.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _flag_library_song(hass: Any, song: dict, reporter: str) -> None:
    """Record a player's "wrong year" flag against a Crate Digger song.

    Kept in memory beside the recently-played list the panel already reads:
    a flag is a hint for this session's host, not a durable record, and it
    must never be able to grow unboundedly from repeated taps.
    """
    from custom_components.beatify.const import DOMAIN

    uri = song.get("uri_ma_library")
    if not uri:
        return
    store = hass.data.setdefault(DOMAIN, {})
    flags = store.setdefault("library_flags", {})
    entry = flags.setdefault(
        uri,
        {
            "uri": uri,
            "title": song.get("title"),
            "artist": song.get("artist"),
            "count": 0,
            "reporters": [],
        },
    )
    entry["count"] += 1
    if reporter and reporter not in entry["reporters"]:
        entry["reporters"] = (entry["reporters"] + [reporter])[-10:]
    # Bound the map so a long party cannot accumulate flags without limit.
    if len(flags) > 200:
        for key in list(flags)[:-200]:
            flags.pop(key, None)


async def handle_report_data(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Handle player report of wrong song data (Issue #911).

    Appends a record to beatify/data_quality_reports.json in the HA config
    directory and fires a GitHub issue via `gh` (best-effort, non-blocking).
    """
    player = game_state.get_player_by_ws(ws)
    if not player:
        return

    if game_state.phase != GamePhase.REVEAL:
        return

    # #2579: ein Report je Spieler und Runde.
    #
    # Der Knopf sitzt neben der Aufloesung, und Spieler sind bewusst nicht
    # angemeldet — das ist der Punkt eines Partyspiels, bei dem Gaeste einen
    # QR-Code scannen. Ohne Riegel konnte ein Gast mit einem Skript in einer
    # einzigen Reveal-Phase beliebig viele **oeffentliche GitHub-Issues**
    # ausloesen und die Report-Datei aufblaehen, bis jeder weitere Schreibvorgang
    # teurer wird. Das `disabled` am Knopf steht nur im Frontend und ist
    # umgehbar.
    #
    # Das Gegenstueck fuer Crate Digger (`_flag_library_song`, gleich unten)
    # kappt sich seit jeher ausdruecklich — „must never be able to grow
    # unboundedly from repeated taps". Dieser Pfad zieht damit nach.
    if player.reported_round == game_state.round:
        _LOGGER.debug(
            "Ignoring repeat data report from %s in round %s",
            player.name,
            game_state.round,
        )
        await ws.send_json({"type": "report_data_ack", "duplicate": True})
        return
    player.reported_round = game_state.round

    song = game_state.current_song or {}
    artist = song.get("artist", "Unknown")
    title = song.get("title", "Unknown")
    year = song.get("year")
    playlist_file = song.get("_playlist_source", "unknown")

    # Crate Digger: the song came from THIS HOST'S own library, so the normal
    # report path is worse than useless — it would append to the shared
    # data-quality file and open a GitHub issue about a track the maintainer
    # has never seen and cannot check. Players are still the ones who notice a
    # wrong year first, so keep the signal and change its destination: flag it
    # for the host, who can fix it in their own pool (the correction endpoints
    # are admin-authenticated, and a guest's phone should not be able to
    # rewrite someone's library metadata).
    if song.get("uri_ma_library"):
        _flag_library_song(handler.hass, song, player.name)
        _LOGGER.info(
            "Crate Digger: %s flagged %s — %s (%s) for the host",
            player.name,
            artist,
            title,
            year,
        )
        await ws.send_json({"type": "report_data_ack", "flagged_for_host": True})
        return

    report = {
        "date": datetime.now(timezone.utc).isoformat(),
        "artist": artist,
        "title": title,
        "year": year,
        "playlist_file": playlist_file,
        "reported_by": player.name,
        "game_id": game_state.game_id,
    }

    _LOGGER.info(
        "Data quality report from %s: %s — %s (%s) in %s",
        player.name,
        artist,
        title,
        year,
        playlist_file,
    )

    reports_path = (
        Path(handler.hass.config.path("beatify")) / "data_quality_reports.json"
    )
    try:
        # Filesystem I/O is blocking and must not run on the HA event loop
        # (Issue #1372) — offload the read-append-write to the executor.
        await handler.hass.async_add_executor_job(_write_report, reports_path, report)
    except (OSError, ValueError):
        _LOGGER.warning("Failed to write data quality report to %s", reports_path)

    # #1384: track the follow-up via HA's background-task registry so it can't
    # be garbage-collected mid-flight and is cancelled on integration unload —
    # instead of a bare asyncio.ensure_future that HA never sees.
    handler.hass.async_create_background_task(
        _create_gh_issue(handler.hass, artist, title, year, playlist_file, player.name),
        name="beatify-report-data",
    )

    await ws.send_json({"type": "report_data_ack"})


_WORKER_URL = "https://beatify-api.mholzi.workers.dev"


async def _create_gh_issue(
    hass: HomeAssistant,
    artist: str,
    title: str,
    year: int | None,
    playlist_file: str,
    reporter: str,
) -> None:
    """Report data quality issue via Cloudflare Worker (best-effort).

    #1384: reuses HA's shared aiohttp ClientSession via
    ``async_get_clientsession(hass)`` rather than spinning up (and tearing down)
    a fresh ``aiohttp.ClientSession`` per call.
    """
    try:
        session = async_get_clientsession(hass)
        async with session.post(
            f"{_WORKER_URL}/report-data",
            json={
                "artist": artist,
                "title": title,
                "year": year,
                "playlist_file": playlist_file,
                "reporter": reporter,
            },
            timeout=aiohttp.ClientTimeout(total=15),
        ) as resp:
            if resp.status not in (200, 201):
                _LOGGER.debug(
                    "Worker /report-data returned %s for %s — %s",
                    resp.status,
                    artist,
                    title,
                )
    except (aiohttp.ClientError, asyncio.TimeoutError, OSError):
        _LOGGER.debug(
            "Worker /report-data call failed (non-critical) for %s — %s", artist, title
        )


__all__ = [
    # helpers
    "_send_state_to",
    "_is_ha_authenticated",
    "_ws_companion_trusted",
    # lifecycle
    "handle_join",
    "handle_get_state",
    "handle_round_timeout",
    "handle_ping",
    "handle_player_onboarded",
    "handle_reaction",
    "handle_reconnect",
    "handle_leave",
    # admin
    "handle_admin_connect",
    "handle_admin",
    "admin_start_game",
    "admin_next_round",
    "admin_stop_song",
    "admin_set_volume",
    "admin_seek_forward",
    "admin_end_game",
    "admin_resume_game",
    "admin_dismiss_game",
    "admin_rematch_game",
    "admin_set_language",
    "admin_confirm_intro_splash",
    "admin_set_party_lights",
    "admin_toggle_party_lights",
    "admin_stop_lights",
    "admin_kick_player",
    # guessing
    "handle_submit",
    "handle_get_sabotage_targets",
    "handle_get_steal_targets",
    "handle_sabotage",
    "handle_steal",
    "_get_steal_error_message",
    "handle_artist_guess",
    "handle_movie_guess",
    "handle_title_artist_guess",
    "handle_title_artist_vote",
    "handle_title_artist_override",
    # report data
    "handle_report_data",
    "_write_report",
    "_create_gh_issue",
]
