"""Home Assistant bus events for scenes and announcements (#3306).

Two events, both fired on the HA event bus so an automation can react to the
game without polling the sensors:

* ``beatify_round_revealed`` — once per round, after the reveal has gone out to
  the room. Lights to the round winner's colour, a TTS line with the year.
* ``beatify_game_ended`` — once per game, when the podium is up.

What goes into a payload is decided by one rule: **nothing a guest could not
already read off the TV at that moment.** The bus is readable by every HA user
and by every integration, and an automation author might forward an event to
a phone or a smart display in the room. So the round event fires only *after*
REVEAL is broadcast and carries the public reveal card (artist, title, year)
and the names at the top — never URIs, the admin-only fun facts, player
session ids, or anything from a round still being played. The game event
carries the final standings the podium shows.

The module does not import the server package, so both the websocket handler
and ``finalize_and_end`` can call into it without an import cycle.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from .const import EVENT_GAME_ENDED, EVENT_ROUND_REVEALED
from .game.state import GamePhase, GameState

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


def _leaders(leaderboard: list[dict[str, Any]]) -> list[str]:
    """Names sharing rank 1 (a tie for first names everyone in it)."""
    return [str(entry["name"]) for entry in leaderboard if entry.get("rank") == 1]


def round_revealed_key(game_state: GameState) -> tuple[str, int] | None:
    """Return the once-per-round identity of a revealed round, or None.

    None means "not a reveal": the game is not in REVEAL, or there is no game.
    The caller remembers the last key it fired for, so a second broadcast of
    the same reveal (the vote window closing, a resume back into REVEAL) does
    not fire the event again.
    """
    if game_state.phase is not GamePhase.REVEAL or not game_state.game_id:
        return None
    return (game_state.game_id, game_state.round)


def build_round_revealed_payload(game_state: GameState) -> dict[str, Any]:
    """Public data of the reveal that was just broadcast to the room."""
    song = game_state.current_song or {}
    return {
        "game_id": game_state.game_id,
        "round": game_state.round,
        "total_rounds": game_state.total_rounds,
        "last_round": bool(game_state.last_round),
        # #2646: a dropped round has no result — screens show "dropped", not a
        # score change, and an automation should be able to tell the same.
        "voided": bool(game_state.round_voided),
        "song": {
            "artist": song.get("artist"),
            "title": song.get("title"),
            "year": song.get("year"),
        },
        "leaders": _leaders(game_state.get_leaderboard()),
    }


def build_game_ended_payload(game_state: GameState) -> dict[str, Any]:
    """The final standings the podium shows."""
    final = game_state.get_final_leaderboard()
    return {
        "game_id": game_state.game_id,
        "rounds_played": game_state.round,
        "winners": _leaders(final),
        "leaderboard": [
            {
                "rank": entry.get("rank"),
                "name": entry.get("name"),
                "score": entry.get("score"),
            }
            for entry in final
        ],
    }


def fire_round_revealed(hass: HomeAssistant, game_state: GameState) -> None:
    """Fire ``beatify_round_revealed``. Never raises into the game."""
    try:
        hass.bus.async_fire(
            EVENT_ROUND_REVEALED, build_round_revealed_payload(game_state)
        )
    except Exception:  # noqa: BLE001 — an event must never break a round
        _LOGGER.warning("Could not fire %s", EVENT_ROUND_REVEALED, exc_info=True)


def fire_game_ended(hass: HomeAssistant, game_state: GameState) -> None:
    """Fire ``beatify_game_ended``. Never raises into the game."""
    try:
        hass.bus.async_fire(EVENT_GAME_ENDED, build_game_ended_payload(game_state))
    except Exception:  # noqa: BLE001 — an event must never break the podium
        _LOGGER.warning("Could not fire %s", EVENT_GAME_ENDED, exc_info=True)
