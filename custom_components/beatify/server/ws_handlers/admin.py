"""Admin / host control WebSocket handlers (#1588 split).

Admin spectator connect, the admin action dispatch table, and every admin
sub-handler (start/next/stop/volume/seek/end/resume/dismiss/rematch/language/
intro-splash/party-lights/kick). Extracted verbatim from the former monolithic
``ws_handlers`` module — behavior is unchanged.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiohttp import web

from custom_components.beatify.const import (
    DOMAIN,
    ERR_GAME_NOT_STARTED,
    ERR_INVALID_ACTION,
    ERR_MEDIA_PLAYER_UNAVAILABLE,
    ERR_NO_SONGS_REMAINING,
    ERR_NOT_ADMIN,
    ERR_UNAUTHORIZED,
)
from custom_components.beatify.game.state import GamePhase, GameState
from custom_components.beatify.server.serializers import build_state_message
from custom_components.beatify.server.ws_handlers._helpers import _is_ha_authenticated

if TYPE_CHECKING:
    from custom_components.beatify.server.websocket import BeatifyWebSocketHandler

_LOGGER = logging.getLogger(__name__)


async def _finalize_and_end(
    handler: BeatifyWebSocketHandler, game_state: GameState
) -> None:
    """Record game stats + run the game-end ceremony exactly once (#1702/#1753).

    The final-round terminal path is reachable from THREE places at the same
    time: the two admin-capable sockets (participant WS + spectator
    ``_admin_ws``) driving ``next_round``/``end_game``, and the unattended
    REVEAL auto-advance carrying the final round (#1753, wired via
    ``GameState.set_game_end_callback``). Gating on the handler's one-shot claim
    keyed by ``game_id`` makes ``finalize_game`` / ``record_game`` (double
    stats) and ``advance_to_end`` (double podium TTS) fire at most once per
    game. The loser skips straight to the broadcast its caller performs.

    #1754: the claim is taken BEFORE the side effects (``record_game`` storage
    I/O + ``advance_to_end``). If either raises, the claim is released so a
    retry can re-run the terminal sequence instead of stranding the game in
    REVEAL/PAUSED — then the error propagates to the caller.

    #1725: before claiming/finalizing, offer a finale sudden-death tiebreaker.
    When the host opted in and the game would end on a tie for first with
    unplayed songs left, ``maybe_start_finale_playoff`` eliminates the non-tied
    players and starts one more playoff round; the game stays in PLAYING and we
    return WITHOUT finalizing, so the caller re-broadcasts the live round. On a
    clear winner / 0 songs left / cap reached it's a no-op and the normal
    finalize path runs.
    """
    if await game_state.maybe_start_finale_playoff():
        _LOGGER.info("Finale tiebreaker armed — playoff round started, not ending")
        return

    if not handler._claim_game_end(game_state.game_id):
        _LOGGER.debug("Game-end already claimed for %s — skipping", game_state.game_id)
        return

    try:
        stats_service = handler.hass.data.get(DOMAIN, {}).get("stats")
        if stats_service:
            game_summary = game_state.finalize_game()
            await stats_service.record_game(
                game_summary, difficulty=game_state.difficulty
            )
            _LOGGER.debug("Game stats recorded")

        await game_state.advance_to_end()
    except Exception:
        # #1754: release the claim so a retry re-runs the end sequence rather
        # than hitting "already claimed" and stranding the game in REVEAL.
        handler._release_game_end(game_state.game_id)
        raise


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
        # #1702: a second admin-capable socket (participant WS + spectator
        # _admin_ws) may have advanced/ended the game while we awaited above.
        # Re-check before driving the round forward; if it already left REVEAL,
        # just re-broadcast the current state.
        if game_state.phase != GamePhase.REVEAL:
            await handler.broadcast_state()
            return
        if game_state.last_round:
            # #1702: finalize + record + advance run exactly once per game even
            # if both admin sockets reach here.
            await _finalize_and_end(handler, game_state)
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
                await _finalize_and_end(handler, game_state)
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

    # #1698: in title/artist mode, scoring for the current round is deferred
    # until the vote window is finalized. admin_next_round resolves it first;
    # admin_end_game must too, otherwise ending during REVEAL with the window
    # open snapshots totals that miss the entire last round (wrong podium /
    # winner). No-op outside title/artist mode or when nothing is pending.
    await game_state.resolve_title_artist_if_pending()

    # #1702: record + end ceremony run once per game (shared claim with the
    # next_round terminal path).
    await _finalize_and_end(handler, game_state)
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

    # #1703: cancel any pending admin-disconnect pause task before the rematch.
    # rematch_game() preserves player records (admin may still be marked
    # disconnected), so a leftover grace timer would otherwise fire and pause
    # the brand-new LOBBY. cleanup_game_tasks previously ran only on dismiss.
    await handler.cleanup_game_tasks()

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
