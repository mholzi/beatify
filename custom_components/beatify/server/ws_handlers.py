"""Extracted WebSocket message handlers for Beatify.

Contains game-action handlers (join, submit, admin actions, steal, etc.)
split out from BeatifyWebSocketHandler to reduce module size.
Each function receives (handler, ws, data, game_state) where *handler*
is the BeatifyWebSocketHandler instance (needed for broadcasting and
task management).

See GitHub issue #606.
"""

from __future__ import annotations

import hmac
import logging
from typing import TYPE_CHECKING

from aiohttp import web

from custom_components.beatify.const import (
    ARTIST_BONUS_POINTS,
    DOMAIN,
    ERR_ADMIN_CANNOT_LEAVE,
    ERR_ADMIN_EXISTS,
    ERR_ALREADY_SUBMITTED,
    ERR_GAME_ENDED,
    ERR_GAME_FULL,
    ERR_GAME_NOT_STARTED,
    ERR_INVALID_ACTION,
    ERR_MEDIA_PLAYER_UNAVAILABLE,
    ERR_NAME_INVALID,
    ERR_NAME_TAKEN,
    ERR_NO_ARTIST_CHALLENGE,
    ERR_NO_MOVIE_CHALLENGE,
    ERR_NO_SONGS_REMAINING,
    ERR_NOT_ADMIN,
    ERR_NOT_IN_GAME,
    ERR_ROUND_EXPIRED,
    ERR_SESSION_NOT_FOUND,
    ERR_SESSION_TAKEOVER,
    ERR_UNAUTHORIZED,
    YEAR_MAX,
    YEAR_MIN,
)
from custom_components.beatify.game.state import GamePhase, GameState
from custom_components.beatify.server.serializers import build_state_message

if TYPE_CHECKING:
    from custom_components.beatify.server.websocket import BeatifyWebSocketHandler

_LOGGER = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Player action handlers
# ---------------------------------------------------------------------------


async def handle_join(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Handle player join request."""
    name = data.get("name", "").strip()
    is_admin = data.get("is_admin", False)

    success, error_code = game_state.add_player(name, ws)

    if success:
        player = game_state.get_player(name)

        if is_admin:
            if game_state.disconnected_admin_name:
                if name.lower() == game_state.disconnected_admin_name.lower():
                    if handler._admin_disconnect_task:
                        handler._admin_disconnect_task.cancel()
                        handler._admin_disconnect_task = None
                        _LOGGER.info(
                            "Admin reconnected, cancelled pause task: %s", name
                        )
                    handler.cancel_pending_removal(name)
                    if game_state.phase == GamePhase.PAUSED:
                        if await game_state.resume_game():
                            _LOGGER.info("Game resumed by admin reconnection")
                else:
                    game_state.remove_player(name)
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
                    game_state.remove_player(name)
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
                    game_state.remove_player(name)
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
            handler.cancel_pending_removal(name)

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

        # Send join acknowledgment with session_id (Story 11.1)
        if player:
            await ws.send_json(
                {
                    "type": "join_ack",
                    "session_id": player.session_id,
                    "game_id": game_state.game_id,
                }
            )

        # Send full state to newly joined player
        state_msg = build_state_message(game_state)
        if not state_msg:
            return
        try:
            await ws.send_json(state_msg)
        except Exception as err:  # noqa: BLE001
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


async def handle_admin_connect(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Handle admin spectator connection (Issue #477)."""
    token = data.get("admin_token")
    if not token or not hmac.compare_digest(token, game_state.admin_token):
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_UNAUTHORIZED,
                "message": "Invalid admin token",
            }
        )
        return

    game_state._admin_ws = ws
    _LOGGER.info("Admin spectator connected via WebSocket")

    await ws.send_json({"type": "admin_connect_ack", "game_id": game_state.game_id})
    state_msg = build_state_message(game_state)
    if state_msg:
        await ws.send_json(state_msg)


async def handle_admin(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Handle admin action messages — dispatches to admin sub-handlers."""
    action = data.get("action")

    is_admin_ws = game_state._admin_ws is not None and game_state._admin_ws is ws

    sender = None
    for player in list(game_state.players.values()):
        if player.ws == ws:
            sender = player
            break

    if not (is_admin_ws or (sender and sender.is_admin)):
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_NOT_ADMIN,
                "message": "Only admin can perform this action",
            }
        )
        return

    admin_handlers = {
        "start_game": admin_start_game,
        "next_round": admin_next_round,
        "stop_song": admin_stop_song,
        "set_volume": admin_set_volume,
        "seek_forward": admin_seek_forward,
        "end_game": admin_end_game,
        "dismiss_game": admin_dismiss_game,
        "rematch_game": admin_rematch_game,
        "set_language": admin_set_language,
        "confirm_intro_splash": admin_confirm_intro_splash,
        "set_party_lights": admin_set_party_lights,
        "toggle_party_lights": admin_toggle_party_lights,
        "stop_lights": admin_stop_lights,
        "kick_player": admin_kick_player,
    }
    sub_handler = admin_handlers.get(action)
    if sub_handler:
        await sub_handler(handler, ws, data, game_state)
    else:
        _LOGGER.warning("Unknown admin action: %s", action)


async def handle_get_state(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Handle dashboard/observer state request (Story 10.4)."""
    state_msg = build_state_message(game_state)
    if state_msg:
        await ws.send_json(state_msg)


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


# ---------------------------------------------------------------------------
# Admin sub-handlers
# ---------------------------------------------------------------------------


async def admin_start_game(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Handle admin start_game action."""
    if game_state.phase != GamePhase.LOBBY:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Game already started",
            }
        )
        return

    success = await game_state.start_round()
    if success:
        await handler.broadcast_state()
    else:
        error_code = ERR_GAME_NOT_STARTED
        error_message = "Failed to start game"

        if game_state.phase == GamePhase.PAUSED:
            pause_reason = game_state.pause_reason
            error_detail = game_state.last_error_detail
            if pause_reason == "media_player_error":
                error_code = ERR_MEDIA_PLAYER_UNAVAILABLE
                if error_detail:
                    error_message = f"Media player error: {error_detail}"
                else:
                    error_message = (
                        "Media player not responding - check speaker connection"
                    )
            elif pause_reason == "no_songs_available":
                error_message = "No playable songs for selected provider"
            else:
                error_message = f"Game paused: {pause_reason}"
        elif game_state.phase == GamePhase.END:
            error_code = ERR_NO_SONGS_REMAINING
            error_message = "No songs available in playlist"

        await ws.send_json(
            {
                "type": "error",
                "code": error_code,
                "message": error_message,
            }
        )


async def admin_next_round(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Handle admin next_round action."""
    if game_state.phase == GamePhase.PLAYING:
        await game_state.end_round()
    elif game_state.phase == GamePhase.REVEAL:
        if game_state.last_round:
            stats_service = handler.hass.data.get(DOMAIN, {}).get("stats")
            if stats_service:
                game_summary = game_state.finalize_game()
                await stats_service.record_game(
                    game_summary, difficulty=game_state.difficulty
                )
                _LOGGER.debug("Game stats recorded for natural end")

            await game_state.advance_to_end()
            await handler.broadcast_state()
        else:
            success = await game_state.start_round()
            if success:
                await handler.broadcast_state()
            else:
                stats_service = handler.hass.data.get(DOMAIN, {}).get("stats")
                if stats_service:
                    game_summary = game_state.finalize_game()
                    await stats_service.record_game(
                        game_summary, difficulty=game_state.difficulty
                    )
                    _LOGGER.debug("Game stats recorded (no songs remaining)")

                await game_state.advance_to_end()
                await handler.broadcast_state()
    else:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Cannot advance round in current phase",
            }
        )


async def admin_stop_song(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Handle admin stop_song action."""
    if game_state.phase != GamePhase.PLAYING:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "No song playing",
            }
        )
        return

    if game_state.song_stopped:
        return

    await game_state.stop_media()
    game_state.song_stopped = True
    _LOGGER.info("Admin stopped song in round %d", game_state.round)
    await handler.broadcast({"type": "song_stopped"})


async def admin_set_volume(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Handle admin set_volume action."""
    direction = data.get("direction")
    if direction not in ("up", "down"):
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Invalid volume direction",
            }
        )
        return

    new_level = game_state.adjust_volume(direction)
    success = await game_state.set_volume_on_player(new_level)
    if not success:
        _LOGGER.warning("Failed to set volume to %.0f%%", new_level * 100)

    _LOGGER.info("Volume adjusted %s to %.0f%%", direction, new_level * 100)
    await ws.send_json(
        {
            "type": "volume_changed",
            "level": new_level,
        }
    )


async def admin_seek_forward(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Handle admin seek_forward action (#498)."""
    if game_state.phase not in (GamePhase.PLAYING, GamePhase.REVEAL):
        return
    seconds = data.get("seconds", 10)
    success = await game_state.seek_forward(seconds)
    if success:
        _LOGGER.info("Media seeked forward %ds", seconds)


async def admin_end_game(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Handle admin end_game action."""
    if game_state.phase not in (GamePhase.PLAYING, GamePhase.REVEAL):
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Cannot end game in current phase",
            }
        )
        return

    await game_state.stop_media()

    stats_service = handler.hass.data.get(DOMAIN, {}).get("stats")
    if stats_service:
        game_summary = game_state.finalize_game()
        await stats_service.record_game(game_summary, difficulty=game_state.difficulty)
        _LOGGER.debug("Game stats recorded for early end")

    await game_state.advance_to_end()
    _LOGGER.info(
        "Admin ended game early at round %d - players preserved for rematch",
        game_state.round,
    )
    await handler.broadcast_state()


async def admin_dismiss_game(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Handle admin dismiss_game action."""
    if game_state.phase != GamePhase.END:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Can only dismiss from END phase",
            }
        )
        return

    await game_state.end_game()
    _LOGGER.info("Game dismissed - all players cleared")
    await handler.broadcast({"type": "game_ended"})
    await handler.broadcast_state()
    await handler.cleanup_game_tasks()


async def admin_rematch_game(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Handle admin rematch_game action."""
    if game_state.phase != GamePhase.END:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Can only rematch from END phase",
            }
        )
        return

    player_count = len(game_state.players)
    game_state.rematch_game()
    _LOGGER.info("Rematch started with %d players", player_count)

    game_state._admin_ws = ws
    await ws.send_json(
        {
            "type": "admin_token_update",
            "admin_token": game_state.admin_token,
            "game_id": game_state.game_id,
        }
    )
    await handler.broadcast({"type": "rematch_started"})
    await handler.broadcast_state()


async def admin_set_language(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Handle admin set_language action."""
    if game_state.phase != GamePhase.LOBBY:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Can only change language in lobby",
            }
        )
        return

    language = data.get("language", "en")
    if language not in ("en", "de", "es", "fr", "nl"):
        language = "en"

    game_state.language = language
    _LOGGER.info("Game language set to: %s", language)
    await handler.broadcast_state()


async def admin_confirm_intro_splash(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Handle admin confirm_intro_splash action (#403)."""
    await game_state.confirm_intro_splash()
    await handler.broadcast_state()


async def admin_set_party_lights(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Handle admin set_party_lights action."""
    entity_ids = data.get("entity_ids", [])
    intensity = data.get("intensity", "medium")
    light_mode = data.get("light_mode", "dynamic")
    wled_presets = data.get("wled_presets")
    enabled = data.get("enabled", True)

    if enabled and entity_ids:
        await game_state.configure_party_lights(
            entity_ids, intensity, light_mode, wled_presets
        )
        _LOGGER.info(
            "Party Lights configured: %d lights, intensity=%s, mode=%s",
            len(entity_ids),
            intensity,
            light_mode,
        )
    else:
        await game_state.disable_party_lights()
        _LOGGER.info("Party Lights disabled")

    await ws.send_json({"type": "party_lights_updated", "enabled": enabled})


async def admin_toggle_party_lights(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Handle admin toggle_party_lights action."""
    if game_state._party_lights and game_state._party_lights._active:
        await game_state.disable_party_lights()
        await ws.send_json({"type": "party_lights_updated", "enabled": False})
    else:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Party Lights not configured — set up in game settings first",
            }
        )


async def admin_stop_lights(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Handle admin stop_lights action — emergency stop for party lights."""
    await game_state.disable_party_lights()
    _LOGGER.info("Party lights stopped by admin")
    await handler.broadcast_state()


async def admin_kick_player(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Handle admin kick_player action — remove a disconnected player from lobby (#659)."""
    if game_state.phase != GamePhase.LOBBY:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Players can only be removed during lobby phase",
            }
        )
        return

    target_name = data.get("player_name", "").strip()
    if not target_name:
        return

    target = game_state.get_player(target_name)
    if not target:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Player not found: " + target_name,
            }
        )
        return

    if target.is_admin:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Cannot remove admin",
            }
        )
        return

    if target.connected:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Cannot remove a connected player",
            }
        )
        return

    game_state.remove_player(target.name)
    _LOGGER.info("Admin kicked disconnected player: %s", target.name)
    await handler.broadcast_state()


# ---------------------------------------------------------------------------
# Player game-play handlers
# ---------------------------------------------------------------------------


async def handle_submit(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Handle guess submission from player."""
    player = None
    for p in list(game_state.players.values()):
        if p.ws == ws:
            player = p
            break

    if not player:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_NOT_IN_GAME,
                "message": "Not in game",
            }
        )
        return

    if game_state.phase != GamePhase.PLAYING:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Not in playing phase",
            }
        )
        return

    if player.submitted:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_ALREADY_SUBMITTED,
                "message": "Already submitted",
            }
        )
        return

    if game_state.is_deadline_passed():
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_ROUND_EXPIRED,
                "message": "Time's up!",
            }
        )
        return

    year = data.get("year")
    if not isinstance(year, int) or year < YEAR_MIN or year > YEAR_MAX:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Invalid year",
            }
        )
        return

    bet = data.get("bet", False)
    player.bet = bool(bet)

    submission_time = game_state.current_time()
    player.submit_guess(year, submission_time)

    await ws.send_json(
        {
            "type": "submit_ack",
            "year": year,
        }
    )

    # Issue #581: Only broadcast here when NOT all guesses are complete.
    # If all guesses are in, trigger_early_reveal_if_complete() will
    # transition to REVEAL and broadcast via the round_end callback,
    # avoiding a redundant double broadcast.
    if not game_state.check_all_guesses_complete():
        await handler.broadcast_state()

    _LOGGER.debug(
        "Early reveal check: phase=%s, artist_challenge=%s",
        game_state.phase.value,
        game_state.artist_challenge_enabled,
    )
    await game_state.trigger_early_reveal_if_complete()

    _LOGGER.info(
        "Player %s submitted guess: %d at %.2f", player.name, year, submission_time
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
        except Exception:  # noqa: BLE001
            pass
        _LOGGER.info("Session takeover: %s (old tab disconnected)", player.name)

    player.ws = ws
    player.connected = True
    handler.cancel_pending_removal(player.name)

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
        await ws.send_json(state_msg)

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
    player = None
    player_name = None
    for name, p in list(game_state.players.items()):
        if p.ws == ws:
            player = p
            player_name = name
            break

    if not player:
        return

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


async def handle_get_steal_targets(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Handle request for available steal targets (Story 15.3 AC2, AC5)."""
    player = None
    for p in list(game_state.players.values()):
        if p.ws == ws:
            player = p
            break

    if not player:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_NOT_IN_GAME,
                "message": "Not in game",
            }
        )
        return

    if not player.steal_available:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "No steal available",
            }
        )
        return

    targets = game_state.get_steal_targets(player.name)
    await ws.send_json(
        {
            "type": "steal_targets",
            "targets": targets,
        }
    )


async def handle_steal(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Handle steal execution (Story 15.3 AC2, AC3)."""
    player = None
    for p in list(game_state.players.values()):
        if p.ws == ws:
            player = p
            break

    if not player:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_NOT_IN_GAME,
                "message": "Not in game",
            }
        )
        return

    target_name = data.get("target")
    if not target_name:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Target name required",
            }
        )
        return

    result = game_state.use_steal(player.name, target_name)

    if result["success"]:
        await ws.send_json(
            {
                "type": "steal_ack",
                "success": True,
                "target": result["target"],
                "year": result["year"],
            }
        )
        if not game_state.check_all_guesses_complete():
            await handler.broadcast_state()
        await game_state.trigger_early_reveal_if_complete()
    else:
        await ws.send_json(
            {
                "type": "error",
                "code": result["error"],
                "message": _get_steal_error_message(result["error"]),
            }
        )


def _get_steal_error_message(error_code: str) -> str:
    """Get human-readable message for steal error codes."""
    messages = {
        ERR_NOT_IN_GAME: "Not in game",
        ERR_INVALID_ACTION: "Cannot steal now",
        "NO_STEAL_AVAILABLE": "No steal available",
        "TARGET_NOT_SUBMITTED": "Target has not submitted yet",
        "CANNOT_STEAL_SELF": "Cannot steal from yourself",
    }
    return messages.get(error_code, "Steal failed")


async def handle_artist_guess(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Handle artist guess submission (Story 20.3)."""
    if game_state.phase != GamePhase.PLAYING:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Can only guess during PLAYING phase",
            }
        )
        return

    player = game_state.get_player_by_ws(ws)
    if not player:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_NOT_IN_GAME,
                "message": "Not in game",
            }
        )
        return

    if not game_state.artist_challenge:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_NO_ARTIST_CHALLENGE,
                "message": "No artist challenge this round",
            }
        )
        return

    artist = data.get("artist", "").strip()
    if not artist:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Artist cannot be empty",
            }
        )
        return

    guess_time = game_state.current_time()
    result = game_state.submit_artist_guess(player.name, artist, guess_time)
    player.has_artist_guess = True

    response: dict = {
        "type": "artist_guess_ack",
        "correct": result["correct"],
    }

    if result["correct"]:
        response["first"] = result["first"]
        if result["first"]:
            response["bonus_points"] = ARTIST_BONUS_POINTS
        else:
            response["winner"] = result["winner"]

    await ws.send_json(response)

    if result.get("first"):
        await handler.broadcast_state()

    await game_state.trigger_early_reveal_if_complete()

    _LOGGER.debug(
        "Artist guess from %s: '%s' -> correct=%s, first=%s",
        player.name,
        artist,
        result["correct"],
        result.get("first", False),
    )


async def handle_movie_guess(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Handle movie quiz guess submission (Issue #28)."""
    if game_state.phase != GamePhase.PLAYING:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Can only guess during PLAYING phase",
            }
        )
        return

    player = game_state.get_player_by_ws(ws)
    if not player:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_NOT_IN_GAME,
                "message": "Not in game",
            }
        )
        return

    if not game_state.movie_challenge:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_NO_MOVIE_CHALLENGE,
                "message": "No movie quiz this round",
            }
        )
        return

    movie = data.get("movie", "").strip()
    if not movie:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Movie cannot be empty",
            }
        )
        return

    guess_time = game_state.current_time()
    result = game_state.submit_movie_guess(player.name, movie, guess_time)
    player.has_movie_guess = True

    response: dict = {
        "type": "movie_guess_ack",
        "correct": result["correct"],
        "already_guessed": result["already_guessed"],
    }

    if result["correct"] and not result["already_guessed"]:
        response["rank"] = result["rank"]
        response["bonus"] = result["bonus"]

    await ws.send_json(response)
    await game_state.trigger_early_reveal_if_complete()

    _LOGGER.debug(
        "Movie guess from %s: '%s' -> correct=%s, rank=%s",
        player.name,
        movie,
        result["correct"],
        result.get("rank"),
    )
