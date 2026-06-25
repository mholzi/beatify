"""Extracted WebSocket message handlers for Beatify.

Contains game-action handlers (join, submit, admin actions, steal, etc.)
split out from BeatifyWebSocketHandler to reduce module size.
Each function receives (handler, ws, data, game_state) where *handler*
is the BeatifyWebSocketHandler instance (needed for broadcasting and
task management).

See GitHub issue #606.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import aiohttp
from aiohttp import web
from homeassistant.helpers.aiohttp_client import async_get_clientsession

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
    ERR_NO_TITLE_ARTIST_CHALLENGE,
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
from custom_components.beatify.server.companion_auth import is_companion_trusted_meta
from custom_components.beatify.server.serializers import (
    build_state_message,
    redact_state_for_player,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from custom_components.beatify.server.websocket import BeatifyWebSocketHandler

_LOGGER = logging.getLogger(__name__)


async def _send_state_to(
    ws: web.WebSocketResponse, state_msg: dict, game_state: GameState
) -> None:
    """Send a ``state`` message to a single recipient, redacted for players.

    #1366: ``state`` frames carry the round's answers (admin_song year;
    song.artist/title in title_artist_mode). Only the spectator admin WS
    (``game_state._admin_ws``) may receive them unfiltered; every other
    connection — including an admin who joined as a *participant* — gets a
    redacted copy, matching the per-recipient filtering in
    ``BeatifyWebSocketHandler.broadcast``.
    """
    payload = state_msg
    if ws is not game_state._admin_ws:
        payload = redact_state_for_player(state_msg)
    await ws.send_json(payload)


# ---------------------------------------------------------------------------
# Authentication helper (#998)
# ---------------------------------------------------------------------------


def _is_ha_authenticated(
    handler: BeatifyWebSocketHandler,
    data: dict,
    ws: web.WebSocketResponse | None = None,
) -> bool:
    """Return True if the message is authorized to claim admin role.

    Two paths are accepted (#1131):

    1. **Bearer token via ``ha_token`` field.** The standard #998 path:
       client obtains an HA access token via OAuth (desktop) or the
       Companion ``externalAppV2`` bridge (rc5+ Android) and sends it.
       Validated against ``hass.auth.async_validate_access_token``.

    2. **HA Android Companion trust on local network.** When the OAuth and
       Companion-bridge paths both fail (the #1120/#1131 saga), this
       fallback inspects the *original HTTP upgrade request* stashed on
       ``ws.beatify_request_meta`` for the UA + RFC1918 signature of an HA
       Android Companion WebView. Same trust model as the HTTP helper in
       ``companion_auth.py``.

    rc6 (#1120 diagnostics): logs *why* path 1 was rejected at warning
    level. We log only the first 12 chars of the token (HA tokens are JWT
    so the header prefix is deterministic and not secret) plus the length
    and exception class.
    """
    token = data.get("ha_token")
    if not token or not isinstance(token, str):
        if _ws_companion_trusted(ws, handler.hass):
            _LOGGER.info(
                "[WS auth] admin_connect: ha_token missing — accepting via "
                "Companion bypass (UA+RFC1918 match on upgrade request)"
            )
            return True
        _LOGGER.warning(
            "[WS auth] admin_connect rejected: ha_token field missing or non-string "
            "(type=%s)",
            type(data.get("ha_token")).__name__,
        )
        return False
    try:
        result = handler.hass.auth.async_validate_access_token(token)
    except Exception as err:  # noqa: BLE001 — any decode/validation error means "no"
        if _ws_companion_trusted(ws, handler.hass):
            _LOGGER.info(
                "[WS auth] admin_connect: ha_token unparseable (%s) — accepting "
                "via Companion bypass",
                type(err).__name__,
            )
            return True
        _LOGGER.warning(
            "[WS auth] admin_connect rejected: validator raised %s (len=%d, prefix=%s)",
            type(err).__name__,
            len(token),
            token[:12],
        )
        return False
    if result is None:
        if _ws_companion_trusted(ws, handler.hass):
            _LOGGER.info(
                "[WS auth] admin_connect: ha_token did not resolve to a refresh "
                "token — accepting via Companion bypass"
            )
            return True
        _LOGGER.warning(
            "[WS auth] admin_connect rejected: HA auth manager returned None "
            "(len=%d, prefix=%s) — token is well-formed but no refresh_token in "
            "hass.auth matched it (HA restarted? user logged out? Companion "
            "token from a different HA install?)",
            len(token),
            token[:12],
        )
        return False
    return True


def _ws_companion_trusted(
    ws: web.WebSocketResponse | None, hass: HomeAssistant
) -> bool:
    """Check the request-meta stashed by ``BeatifyWebSocketHandler.handle``."""
    if ws is None:
        return False
    meta = getattr(ws, "beatify_request_meta", None)
    return is_companion_trusted_meta(meta, hass)


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
    # rc11 diagnostic (#1131 follow-up): log every join attempt so we can
    # see exactly which path the player-join takes when "Reconnecting"
    # surfaces on the client. Remove once #1131 lands stable.
    meta = getattr(ws, "beatify_request_meta", None)
    _LOGGER.info(
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
    _LOGGER.info(
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
            _LOGGER.info(
                "[WS-Debug] join is_admin=True _is_ha_authenticated=%s",
                authed,
            )
            if not authed:
                game_state.remove_player(name)
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


async def handle_admin_connect(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Handle admin spectator connection (Issue #477).

    #998: gated by Home Assistant login — the message must carry a valid HA
    access token (``ha_token``). The former per-game ``admin_token`` check is
    retired; that token was embedded into the admin page for any visitor.
    """
    if not _is_ha_authenticated(handler, data, ws):
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_UNAUTHORIZED,
                "message": "Home Assistant login required",
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
        "resume_game": admin_resume_game,
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

    # #1287: cold-start bridge. start_round() blocks for ~10-15s while Music
    # Assistant connects the speaker and round 1 is prepared, and only then is
    # the PLAYING state broadcast. Without an interim signal every client stays
    # on the lobby/"Starting…" view the whole time. Fire a lightweight transient
    # message FIRST so player phones + the TV/dashboard switch to the animated
    # vinyl-disc loader immediately; the PLAYING broadcast below replaces it.
    await handler.broadcast({"type": "game_starting"})

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
        # #949: start_round failing pauses the game (media_player_error etc.),
        # but without broadcasting that the admin and players never leave the
        # lobby / "Starting..." view for the PAUSED recovery banner. Mirror
        # what admin_next_round already does on its paused branch.
        await handler.broadcast_state()


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
        # #1180 Phase 4: finalize an open title/artist vote window (apply host
        # override + majority, rescore) before the round advances or the game
        # ends, so accepted near-misses count toward the leaderboard.
        await game_state.resolve_title_artist_if_pending()
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
            elif game_state.phase == GamePhase.PAUSED:
                # #805: start_round paused the game (MAX_SONG_RETRIES exhausted
                # or media-player unavailable). Don't force-end — let the
                # admin recover. The PAUSED-phase state will be broadcast so
                # the UI shows the paused indicator instead of the podium.
                _LOGGER.info(
                    "start_round paused the game (%s); leaving paused for recovery",
                    game_state.last_error_detail or "playback error",
                )
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
    # #805: PAUSED is allowed too — when start_round() pauses the game after
    # MAX_SONG_RETRIES, the admin's only escape (other than Resume) is to end
    # the game cleanly. Without PAUSED here, the End button in the control bar
    # silently rejects with ERR_INVALID_ACTION.
    if game_state.phase not in (GamePhase.PLAYING, GamePhase.REVEAL, GamePhase.PAUSED):
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


async def admin_resume_game(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Handle admin resume_game action — manual recovery from PAUSED (#805).

    Before this existed, the only resume path was via admin reconnect. After
    #805, when MA fails to play 3 songs in a row the game lands in PAUSED
    with no UI affordance to recover. This action lets the Resume button in
    the PAUSED view call back into `game_state.resume_game()` to restore the
    prior phase (typically REVEAL, where the admin can try the next round).
    """
    if game_state.phase != GamePhase.PAUSED:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Game is not paused",
            }
        )
        return

    success = await game_state.resume_game()
    if not success:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Resume failed — no previous phase to restore",
            }
        )
        return

    _LOGGER.info("Admin resumed game from PAUSED")
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
    # Issue #841 Phase 3: announce the rematch (use case 20). TTS survives
    # rematch_game() — only end_game() tears the service down.
    await game_state.announce_rematch()
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
        # Issue #842 Phase 4: announce the steal (use case 23).
        await game_state.announce_steal_used(player.name, result["target"])
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


async def handle_title_artist_guess(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Handle a title & artist guess submission (#1180).

    Mirrors handle_artist_guess: phase-gated to PLAYING, classifies the
    submitted title and artist independently via the challenge, acks the
    per-field status, marks the player done, and triggers early reveal once
    everyone has guessed. Empty fields are allowed — they classify as
    "skipped" (0 points for that field), so they are NOT rejected here.
    """
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

    if not game_state.title_artist_challenge:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_NO_TITLE_ARTIST_CHALLENGE,
                "message": "No title & artist challenge this round",
            }
        )
        return

    title = data.get("title", "")
    artist = data.get("artist", "")
    if not isinstance(title, str):
        title = ""
    if not isinstance(artist, str):
        artist = ""
    # Guess length is capped at the WS ingest boundary (#1581) before dispatch,
    # so title/artist already fit MAX_GUESS_LEN here. classify_field truncates
    # again defensively.

    guess_time = game_state.current_time()
    result = game_state.submit_title_artist_guess(
        player.name, title, artist, guess_time
    )
    player.has_title_artist_guess = True
    # Mark the player as submitted so the round behaves like a normal
    # submission (#1180): ScoringService.score_player_round gates the
    # title/artist points path on ``player.submitted``, and all_submitted() /
    # check_all_guesses_complete() rely on it for early reveal. There is no
    # year in this mode, so we set the submission state directly rather than
    # going through player.submit_guess (which expects a year).
    player.submitted = True
    player.submission_time = guess_time

    await ws.send_json(
        {
            "type": "title_artist_guess_ack",
            "title_status": result["title_status"],
            "artist_status": result["artist_status"],
        }
    )

    # Mirror handle_artist_guess / handle_submit: avoid a redundant broadcast
    # when the early-reveal path is about to broadcast via the round_end
    # callback. Only broadcast here when the round is NOT yet complete.
    if not game_state.check_all_guesses_complete():
        await handler.broadcast_state()

    await game_state.trigger_early_reveal_if_complete()

    _LOGGER.debug(
        "Title/artist guess from %s: title=%r (%s), artist=%r (%s)",
        player.name,
        title,
        result["title_status"],
        artist,
        result["artist_status"],
    )


async def handle_title_artist_vote(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Handle a community vote on a title/artist near-miss (#1180 Phase 4).

    REVEAL-only. A player may not vote on their own near-miss (the near-miss
    player is encoded as the prefix of nearmiss_id, "player:field").
    """
    if game_state.phase != GamePhase.REVEAL:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Can only vote during REVEAL phase",
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

    nearmiss_id = data.get("nearmiss_id")
    accept = data.get("accept")
    if not isinstance(nearmiss_id, str) or ":" not in nearmiss_id:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Invalid nearmiss_id",
            }
        )
        return
    if not isinstance(accept, bool):
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Invalid vote value",
            }
        )
        return

    # #1180: only accept votes for a real, vote-eligible near-miss. Without this
    # the votes dict would store an entry for ANY string, letting a player flood
    # it with fabricated ids during REVEAL and exhaust server memory.
    if nearmiss_id not in {nm["id"] for nm in game_state.get_near_misses()}:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Unknown nearmiss_id",
            }
        )
        return

    # Reject self-vote: the near-miss player is the part before the last ":".
    nearmiss_player = nearmiss_id.rsplit(":", 1)[0]
    if nearmiss_player == player.name:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Cannot vote on your own guess",
            }
        )
        return

    game_state.register_title_artist_vote(player.name, nearmiss_id, accept)
    _LOGGER.debug(
        "Title/artist vote by %s on %s -> %s", player.name, nearmiss_id, accept
    )
    await handler.broadcast_state()


async def handle_title_artist_override(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Handle a host override on a title/artist near-miss (#1180 Phase 4).

    REVEAL-only, admin-only. Override precedence is applied at resolve time
    (window expiry or host-advance) by resolve_title_artist.
    """
    if game_state.phase != GamePhase.REVEAL:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Can only override during REVEAL phase",
            }
        )
        return

    is_admin_ws = game_state._admin_ws is not None and game_state._admin_ws is ws
    sender = game_state.get_player_by_ws(ws)
    if not (is_admin_ws or (sender and sender.is_admin)):
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_NOT_ADMIN,
                "message": "Only admin can override",
            }
        )
        return

    nearmiss_id = data.get("nearmiss_id")
    accept = data.get("accept")
    if not isinstance(nearmiss_id, str) or ":" not in nearmiss_id:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Invalid nearmiss_id",
            }
        )
        return
    if not isinstance(accept, bool):
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Invalid override value",
            }
        )
        return

    # #1180: only accept overrides for a real, vote-eligible near-miss (mirrors
    # the vote handler) so the overrides dict can't be grown with fake ids.
    if nearmiss_id not in {nm["id"] for nm in game_state.get_near_misses()}:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Unknown nearmiss_id",
            }
        )
        return

    game_state.set_title_artist_override(nearmiss_id, accept)
    _LOGGER.info("Title/artist override on %s -> %s", nearmiss_id, accept)
    await handler.broadcast_state()


# ---------------------------------------------------------------------------
# Data quality report (Issue #911)
# ---------------------------------------------------------------------------


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
    reports_path.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8"
    )


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

    song = game_state.current_song or {}
    artist = song.get("artist", "Unknown")
    title = song.get("title", "Unknown")
    year = song.get("year")
    playlist_file = song.get("_playlist_source", "unknown")

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
