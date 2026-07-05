"""Connection & session lifecycle WebSocket handlers (#1588 split).

Join, reconnect, leave, state/ping/onboarding/reaction and the round-timeout
watchdog. Extracted verbatim from the former monolithic ``ws_handlers`` module
— behavior is unchanged.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiohttp import web

from custom_components.beatify.const import (
    ERR_ADMIN_CANNOT_LEAVE,
    ERR_ADMIN_EXISTS,
    ERR_GAME_ENDED,
    ERR_GAME_FULL,
    ERR_INVALID_ACTION,
    ERR_NAME_INVALID,
    ERR_NAME_TAKEN,
    ERR_SESSION_NOT_FOUND,
    ERR_SESSION_TAKEOVER,
    ERR_UNAUTHORIZED,
)
from custom_components.beatify.game.state import GamePhase, GameState
from custom_components.beatify.server.serializers import build_state_message
from custom_components.beatify.server.ws_handlers._helpers import (
    _is_ha_authenticated,
    _send_state_to,
)

if TYPE_CHECKING:
    from custom_components.beatify.server.websocket import BeatifyWebSocketHandler

_LOGGER = logging.getLogger(__name__)


def _undo_admin_claim(
    game_state: GameState, name: str, was_existing_player: bool
) -> None:
    """Undo the ``add_player`` side effects when an admin claim is rejected.

    #1696 (security / data-loss): ``add_player`` runs *before* the admin-claim
    checks. For a disconnected name it takes the reconnection path and
    re-attaches the pre-existing ``PlayerSession`` (with its score + session_id
    intact). If a rejection branch then fires, blindly calling
    ``remove_player(name)`` would delete that whole record — letting an
    unauthenticated visitor erase a real player's score by sending
    ``{join, name:<disconnected player>, is_admin:true}``.

    So: only fully remove a *brand-new* player (``was_existing_player`` False).
    For a reconnected existing player, merely revert the reconnection
    (``connected=False``, ``ws=None``) — restoring the prior disconnected state
    without touching score/session.
    """
    if was_existing_player:
        player = game_state.get_player(name)
        if player is not None:
            player.connected = False
            player.ws = None
    else:
        game_state.remove_player(name)


async def handle_join(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Handle player join request."""
    name = data.get("name", "").strip()
    is_admin = data.get("is_admin", False)
    # #1662: demoted to DEBUG — fires on every join and floods INFO logs.
    meta = getattr(ws, "beatify_request_meta", None)
    _LOGGER.debug(
        "[WS-Debug] join name=%r is_admin=%s ha_token_present=%s phase=%s meta=%s",
        name,
        is_admin,
        bool(data.get("ha_token")),
        game_state.phase.value
        if hasattr(game_state.phase, "value")
        else game_state.phase,
        meta,
    )

    # #841 Phase 3: distinguish a reconnect from a fresh join for the TTS
    # hook below — a player record already existing under this name means
    # add_player() will take its reconnection path.
    was_existing_player = game_state.get_player(name) is not None

    success, error_code = game_state.add_player(name, ws)
    _LOGGER.debug(
        "[WS-Debug] join add_player name=%r success=%s error_code=%s was_existing=%s",
        name,
        success,
        error_code,
        was_existing_player,
    )

    if success:
        player = game_state.get_player(name)

        if is_admin:
            # #998: claiming the host role requires a logged-in HA user.
            # Normal players join with no auth — only the admin claim is
            # gated. add_player() already ran, so undo it on rejection.
            authed = _is_ha_authenticated(handler, data, ws)
            _LOGGER.debug(
                "[WS-Debug] join is_admin=True _is_ha_authenticated=%s",
                authed,
            )
            if not authed:
                _undo_admin_claim(game_state, name, was_existing_player)
                await ws.send_json(
                    {
                        "type": "error",
                        "code": ERR_UNAUTHORIZED,
                        "message": "Home Assistant login required to host",
                    }
                )
                return
            # #790: Existing admin reclaiming their own role should always be
            # allowed, regardless of phase. Without this check, an admin whose
            # WS dropped (network blip, AirPlay-induced HA hiccup) tries to
            # reconnect with their original name, hits the "Only allow new
            # admin claim during LOBBY" rejection, and gets remove_player'd
            # — losing admin entirely. The existing player record matching
            # by name with is_admin=True means this is the same human host.
            is_own_admin_reclaim = (
                player is not None
                and player.is_admin
                and not any(
                    p.is_admin and p.name.lower() != name.lower()
                    for p in list(game_state.players.values())
                )
            )
            if is_own_admin_reclaim:
                # Cancel any pending pause task — admin is back.
                if handler._admin_disconnect_task:
                    handler._admin_disconnect_task.cancel()
                    handler._admin_disconnect_task = None
                    _LOGGER.info("Admin reconnected (own reclaim): %s", name)
                if game_state.phase == GamePhase.PAUSED:
                    if await game_state.resume_game():
                        _LOGGER.info("Game resumed by admin reclaim during PAUSED")
            elif game_state.disconnected_admin_name:
                if name.lower() == game_state.disconnected_admin_name.lower():
                    if handler._admin_disconnect_task:
                        handler._admin_disconnect_task.cancel()
                        handler._admin_disconnect_task = None
                        _LOGGER.info(
                            "Admin reconnected, cancelled pause task: %s", name
                        )
                    if game_state.phase == GamePhase.PAUSED:
                        if await game_state.resume_game():
                            _LOGGER.info("Game resumed by admin reconnection")
                else:
                    _undo_admin_claim(game_state, name, was_existing_player)
                    await ws.send_json(
                        {
                            "type": "error",
                            "code": ERR_ADMIN_EXISTS,
                            "message": "Only the original host can reconnect",
                        }
                    )
                    return
            else:
                existing_admin = any(
                    p.is_admin
                    for p in list(game_state.players.values())
                    if p.name != name
                )
                if existing_admin:
                    _undo_admin_claim(game_state, name, was_existing_player)
                    await ws.send_json(
                        {
                            "type": "error",
                            "code": ERR_ADMIN_EXISTS,
                            "message": "Game already has an admin",
                        }
                    )
                    return
                # Issue #417: Only allow new admin claim during LOBBY
                if game_state.phase != GamePhase.LOBBY:
                    _LOGGER.warning(
                        "Rejected admin claim from %s during %s phase",
                        name,
                        game_state.phase.value,
                    )
                    _undo_admin_claim(game_state, name, was_existing_player)
                    await ws.send_json(
                        {
                            "type": "error",
                            "code": ERR_INVALID_ACTION,
                            "message": "Admin claim only allowed during lobby phase",
                        }
                    )
                    return
                else:
                    game_state.set_admin(name)
        else:
            # Issue #420: If this player matches disconnected admin by name,
            # cancel the admin disconnect task even without is_admin flag
            if game_state.disconnected_admin_name:
                if name.lower() == game_state.disconnected_admin_name.lower():
                    if handler._admin_disconnect_task:
                        handler._admin_disconnect_task.cancel()
                        handler._admin_disconnect_task = None
                        _LOGGER.info(
                            "Admin reconnected without admin flag, "
                            "cancelled pause task: %s",
                            name,
                        )

            # Issue #841 Phase 3: announce the join / reconnect over TTS.
            if player is not None:
                if was_existing_player:
                    await game_state.announce_player_reconnect(player.name)
                else:
                    await game_state.announce_player_join(player.name)

        # Send join acknowledgment with session_id (Story 11.1)
        if player:
            await ws.send_json(
                {
                    "type": "join_ack",
                    "session_id": player.session_id,
                    "game_id": game_state.game_id,
                }
            )

        # Send state to newly joined player (redacted — #1366)
        state_msg = build_state_message(game_state)
        if not state_msg:
            return
        try:
            await _send_state_to(ws, state_msg, game_state)
        except (ConnectionError, RuntimeError) as err:
            _LOGGER.warning("Failed to send state to new player: %s", err)
            return
        await handler.debounced_broadcast_state()
    else:
        error_messages = {
            ERR_NAME_TAKEN: "Name taken, choose another",
            ERR_NAME_INVALID: "Please enter a name",
            ERR_GAME_FULL: "Game is full",
            ERR_GAME_ENDED: "This game has ended",
        }
        await ws.send_json(
            {
                "type": "error",
                "code": error_code,
                "message": error_messages.get(error_code, "Join failed"),
            }
        )


async def handle_get_state(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Handle dashboard/observer state request (Story 10.4)."""
    state_msg = build_state_message(game_state)
    if state_msg:
        await _send_state_to(ws, state_msg, game_state)


async def handle_round_timeout(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Watchdog: a client's round countdown reached zero.

    The server's round timer is a single asyncio task — if it is cancelled or
    dies, the round freezes on PLAYING forever with no way out. Every player's
    browser also counts the round down independently; when one reports the
    deadline has passed while the round is still PLAYING, force the transition
    to REVEAL. end_round() is idempotent (it no-ops once the phase has moved
    on), so the server timer firing and nudges from several clients all racing
    is harmless. The WARNING is intentional — it is the breadcrumb that the
    server-side round timer failed to fire.
    """
    if game_state.phase == GamePhase.PLAYING and game_state.is_deadline_passed():
        _LOGGER.warning(
            "Round %d still PLAYING past its deadline — client watchdog "
            "forcing end_round (the server round timer did not fire)",
            game_state.round,
        )
        await game_state.end_round()
        await handler.broadcast_state()


async def handle_ping(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Reply to a client heartbeat ping.

    The client sends {type: 'ping'} on an interval and treats prolonged
    server silence as a dead (half-open) socket worth reconnecting. Echoing
    a pong keeps that heartbeat satisfied during quiet phases when no state
    broadcast would otherwise reach the client.
    """
    try:
        await ws.send_json({"type": "pong"})
    except (ConnectionError, RuntimeError) as err:
        _LOGGER.debug("Failed to send pong: %s", err)


async def handle_player_onboarded(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Handle player_onboarded message — flips PlayerSession.onboarded to True.

    Fired when a player completes or skips the post-QR onboarding tour.
    Idempotent: re-sending for an already-onboarded player is a no-op.
    """
    player = game_state.get_player_by_ws(ws)
    if not player:
        return
    if player.onboarded:
        return
    player.onboarded = True
    _LOGGER.info("Player completed onboarding: %s", player.name)
    await handler.broadcast_state()


async def handle_reaction(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Handle live reaction during reveal (Story 18.9)."""
    player = game_state.get_player_by_ws(ws)
    if not player:
        return

    if game_state.phase != GamePhase.REVEAL:
        return

    emoji = data.get("emoji", "")
    if emoji not in ["🔥", "😂", "😱", "👏", "🤔"]:
        return

    if game_state.record_reaction(player.name, emoji):
        await handler.broadcast(
            {
                "type": "player_reaction",
                "player_name": player.name,
                "emoji": emoji,
            }
        )


async def handle_reconnect(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Handle session-based reconnection (Story 11.2)."""
    session_id = data.get("session_id")
    if not session_id:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_SESSION_NOT_FOUND,
                "message": "Session ID required",
            }
        )
        return

    player = game_state.get_player_by_session_id(session_id)
    if not player:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_SESSION_NOT_FOUND,
                "message": "Session not found or game was reset",
            }
        )
        return

    if game_state.phase == GamePhase.END:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_GAME_ENDED,
                "message": "Game has ended",
            }
        )
        return

    # Handle dual-tab scenario
    if player.connected and player.ws and not player.ws.closed and player.ws is not ws:
        try:
            await player.ws.send_json(
                {
                    "type": "error",
                    "code": ERR_SESSION_TAKEOVER,
                    "message": "Session taken over by another tab",
                }
            )
            await player.ws.close()
        except (ConnectionError, RuntimeError):
            pass
        _LOGGER.info("Session takeover: %s (old tab disconnected)", player.name)

    player.ws = ws
    player.connected = True

    if player.is_admin:
        if handler._admin_disconnect_task:
            handler._admin_disconnect_task.cancel()
            handler._admin_disconnect_task = None
            _LOGGER.info("Admin reconnected via session, cancelled pause task")

        if game_state.phase == GamePhase.PAUSED:
            if await game_state.resume_game():
                _LOGGER.info("Game resumed by admin session reconnection")

    await ws.send_json(
        {
            "type": "reconnect_ack",
            "name": player.name,
            "success": True,
        }
    )

    state_msg = build_state_message(game_state)
    if state_msg:
        await _send_state_to(ws, state_msg, game_state)

    await handler.broadcast_state()

    _LOGGER.info(
        "Player reconnected via session: %s (score: %d)", player.name, player.score
    )


async def handle_leave(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Handle intentional leave game (Story 11.5)."""
    # #1664 PR-2: players keyed by player_id — resolve by WS, use display name
    player = game_state.get_player_by_ws(ws)
    if not player:
        return
    player_name = player.name

    if player.is_admin:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_ADMIN_CANNOT_LEAVE,
                "message": "Host cannot leave. End the game instead.",
            }
        )
        return

    game_state.remove_player(player_name)
    await ws.send_json({"type": "left"})
    await ws.close()
    await handler.broadcast_state()
    _LOGGER.info("Player left game intentionally: %s", player_name)
