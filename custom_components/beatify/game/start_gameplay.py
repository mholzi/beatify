"""The surface-independent half of starting a game (#2929).

Two surfaces start a game: the admin websocket (``server/ws_handlers/admin.py``)
and the REST endpoint (``StartGameplayView`` in ``server/game_views.py``). Every
rule about *starting* one therefore had to be written twice, and the two copies
had drifted apart:

* only the REST path enforced the sudden-death floor, so the same game started
  over the websocket ran with sudden death active below the minimum;
* only the websocket path announced ``game_starting``, so a REST start left the
  TV and the player phones on the lobby view for the ~10-15 s the speaker needs.

Which rules applied depended on which surface pressed the button, which is not a
decision anyone made. The surface a host actually uses is the websocket, so the
gap fell on the common path and the REST-driven live test never saw it.

Error *rendering* stays with the surfaces on purpose: one writes JSON down a
socket, the other returns an HTTP response with its own status codes. What lives
here is the decisions, not their presentation — a refusal comes back as a
machine-readable reason and each surface says it in its own words.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from custom_components.beatify.const import MIN_PLAYERS, SUDDEN_DEATH_MIN_PLAYERS

if TYPE_CHECKING:
    from custom_components.beatify.game.state import GameState

#: The game is not in LOBBY — somebody already started it.
REFUSE_ALREADY_STARTED = "already_started"
#: Fewer than ``MIN_PLAYERS`` have joined (#2497).
REFUSE_NOT_ENOUGH_PLAYERS = "not_enough_players"


def refusal_to_start(game_state: GameState) -> str | None:
    """Why this game may not start, or ``None`` when it may.

    #2497 put the minimum-player floor at the two places a *user* starts a game
    rather than inside ``start_round()``, which runs for every round. Keeping
    the floor here keeps that intent and removes the second copy.
    """
    from custom_components.beatify.game.state import GamePhase

    if game_state.phase != GamePhase.LOBBY:
        return REFUSE_ALREADY_STARTED
    if len(game_state.players) < MIN_PLAYERS:
        return REFUSE_NOT_ENOUGH_PLAYERS
    return None


def apply_sudden_death_floor(game_state: GameState) -> str | None:
    """Turn sudden death off below its floor; return a warning if it did.

    Issue #827: players join the LOBBY *after* ``create_game`` clears sessions,
    so the floor can only be enforced at the LOBBY -> PLAYING transition. The
    wizard also disables the toggle client-side; this is the server-side
    backstop for direct API callers.

    Auto-disable rather than refuse, so the host is not stuck with a game that
    will not start. #2699: the comparison and the message read the same
    constant, so raising the floor in ``const.py`` cannot leave this text
    promising the old number.
    """
    if not game_state.sudden_death_mode:
        return None
    connected = sum(1 for p in game_state.players.values() if p.connected)
    if connected >= SUDDEN_DEATH_MIN_PLAYERS:
        return None
    game_state.set_sudden_death(False)
    return (
        f"Sudden Death needs at least {SUDDEN_DEATH_MIN_PLAYERS} "
        "players — starting without it."
    )


async def begin_gameplay(
    game_state: GameState, ws_handler: Any | None
) -> tuple[bool, str | None]:
    """Run the LOBBY -> PLAYING transition. Returns ``(success, warning)``.

    Callers are expected to have checked :func:`refusal_to_start` first — this
    does not repeat it, because each surface has to answer a refusal in its own
    format and would have to branch anyway.

    #1287: ``start_round()`` blocks for ~10-15 s while Music Assistant connects
    the speaker and round 1 is prepared, and only then is PLAYING broadcast.
    ``game_starting`` is fired first so phones and the TV switch to the vinyl
    loader immediately instead of sitting on the lobby view.
    """
    warning = apply_sudden_death_floor(game_state)
    if ws_handler is not None:
        await ws_handler.broadcast({"type": "game_starting"})
    success = await game_state.start_round()
    return success, warning
