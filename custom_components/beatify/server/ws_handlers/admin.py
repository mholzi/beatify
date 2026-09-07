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
    ERR_GAME_NOT_STARTED,
    ERR_INVALID_ACTION,
    ERR_MEDIA_PLAYER_UNAVAILABLE,
    ERR_NO_PLAYABLE_SONGS,
    ERR_NO_SONGS_REMAINING,
    ERR_NOT_ADMIN,
    ERR_UNAUTHORIZED,
    HOST_PAUSE_REASON,
    HOST_PAUSE_REASONS,
    MAX_REMATCH_PLAYLISTS,
    MIN_PLAYERS,
)
from custom_components.beatify.game.playlist import async_load_songs_from_paths
from custom_components.beatify.game.state import GamePhase, GameState
from custom_components.beatify.game.state_setup import NoPlayableSongsError
from custom_components.beatify.server.serializers import build_state_message
from custom_components.beatify.server.ws_handlers._helpers import (
    _is_ha_authenticated,
    finalize_and_end,
)

if TYPE_CHECKING:
    from custom_components.beatify.server.websocket import BeatifyWebSocketHandler

_LOGGER = logging.getLogger(__name__)


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

    handler.admin_ws = ws
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

    is_admin_ws = handler.admin_ws is not None and handler.admin_ws is ws

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
        "pause_game": admin_pause_game,
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

    # #2497: the minimum-player check used to live in a GameState.start_game()
    # that no production path called — so a game could be started with a single
    # player. It belongs here rather than inside start_round(): start_round runs
    # for every round of every game, while this is a property of *starting* one,
    # and only here is there a socket to tell the host why nothing happened.
    # #2717 deleted start_game(), so this and StartGameplayView are now the only
    # two copies of the floor, one per surface a host can start a game from.
    if len(game_state.players) < MIN_PLAYERS:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_GAME_NOT_STARTED,
                "message": f"Need at least {MIN_PLAYERS} players to start",
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
        # handler.admin_ws) may have advanced/ended the game while we awaited above.
        # Re-check before driving the round forward; if it already left REVEAL,
        # just re-broadcast the current state.
        if game_state.phase != GamePhase.REVEAL:
            await handler.broadcast_state()
            return
        if game_state.last_round:
            # #1702: finalize + record + advance run exactly once per game even
            # if both admin sockets reach here.
            await finalize_and_end(handler, game_state)
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
                await finalize_and_end(handler, game_state)
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
    """Handle admin stop_song action.

    #2645: also reachable *out of* a host pause. On the pause screen "Just the
    music off" sits as the fourth tile under the three pause reasons, each with
    its consequence spelled out — that juxtaposition is the whole point, since
    Stop and Pause were previously two buttons in two places and the host had
    to already know which one they meant. Picking the fourth tile out of a
    pause means the host did not want a pause at all: leave the pause and
    silence the song, so the round runs on.
    """
    if game_state.phase == GamePhase.PAUSED:
        # Only a pause the host set may be swapped for a plain stop. A pause
        # the server owns (dead speaker, empty playlist) is not a mislabelled
        # Stop, and resuming into it would just re-fail.
        if game_state.pause_reason not in HOST_PAUSE_REASONS:
            await ws.send_json(
                {
                    "type": "error",
                    "code": ERR_INVALID_ACTION,
                    "message": "No song playing",
                }
            )
            return
        if not await game_state.resume_game():
            await ws.send_json(
                {
                    "type": "error",
                    "code": ERR_INVALID_ACTION,
                    "message": "Resume failed — no previous phase to restore",
                }
            )
            return
        _LOGGER.info("Host swapped a pause for a plain stop")
        await handler.broadcast_state()
        if game_state.phase != GamePhase.PLAYING:
            # The round's deadline elapsed while the pause stood, so the resume
            # landed in REVEAL. The pause is lifted, which was the larger half
            # of the intent; there is no round left to silence.
            return

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
    #
    # #2689: allow_playoff=False, mirroring the REST EndGameView. End is the
    # host saying "stop now", not a game reaching its natural end, and this WS
    # path is the one the admin page actually uses. With the finale tiebreaker
    # armed and a tie for first during REVEAL, the default allow_playoff=True
    # made maybe_start_finale_playoff freeze every non-leader as a playoff
    # spectator and start another song — so End visibly continued the game and
    # only a second tap ended it, with the spectator flags on the end screen.
    # The finale tiebreaker still fires on the paths it was written for: the
    # last-round next_round branch and the REVEAL auto-advance.
    await finalize_and_end(handler, game_state, allow_playoff=False)
    _LOGGER.info(
        "Admin ended game early at round %d - players preserved for rematch",
        game_state.round,
    )
    await handler.broadcast_state()


async def admin_pause_game(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
    game_state: GameState,
) -> None:
    """Handle admin pause_game action — the host's own pause (#2645).

    ``GameState.pause_game(reason)`` has existed for a long time, but every
    caller was server-side; the host's only "pause" was locking their phone,
    which trips ``admin_disconnected``, or Stop, which leaves the clock running
    and marks the room as missing the round.

    The tap pauses **immediately**. ``reason`` only names the announcement the
    room reads, and a host who tapped Pause without picking one has still
    paused — the screens then simply say "Pause". The same action arriving
    while already paused re-labels the announcement without leaving the pause,
    which is why the pizza can turn into "back in a minute" halfway through.
    """
    reason = data.get("reason") or HOST_PAUSE_REASON
    if reason not in HOST_PAUSE_REASONS:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": f"Unknown pause reason: {reason}",
            }
        )
        return

    if game_state.phase == GamePhase.PAUSED:
        # Re-labelling an existing host pause. A pause the server owns keeps
        # its reason: "Pizza is here" must never be able to cover a speaker
        # that stopped answering — the room would wait for a host who is
        # waiting for a speaker.
        if game_state.pause_reason not in HOST_PAUSE_REASONS:
            await ws.send_json(
                {
                    "type": "error",
                    "code": ERR_INVALID_ACTION,
                    "message": "This pause was not set by the host",
                }
            )
            return
        if game_state.pause_reason == reason:
            return
        game_state.pause_reason = reason
        _LOGGER.info("Host pause re-labelled: %s", reason)
        await handler.broadcast_state()
        return

    if game_state.phase not in (GamePhase.PLAYING, GamePhase.REVEAL):
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "No round to pause",
            }
        )
        return

    if not await game_state.pause_game(reason):
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Could not pause the game",
            }
        )
        return

    _LOGGER.info("Host paused the game: %s", reason)
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


async def _resolve_rematch_playlists(
    handler: BeatifyWebSocketHandler,
    ws: web.WebSocketResponse,
    data: dict,
) -> tuple[list[dict] | None, list[str] | None]:
    """Turn a rematch's ``playlists`` field into songs (#2648).

    Returns ``(songs, paths)``. ``(None, None)`` means the caller asked for the
    historic same-playlist rematch and nothing should change. ``(None, paths)``
    means the request named playlists that produced no usable song — the error
    has already been sent on ``ws`` and the caller must return.
    """
    raw = data.get("playlists")
    if raw is None:
        return None, None
    if not isinstance(raw, list) or not all(isinstance(p, str) for p in raw) or not raw:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "playlists must be a non-empty list of paths",
            }
        )
        return None, []

    paths = [p for p in raw][:MAX_REMATCH_PLAYLISTS]
    songs, warnings = await async_load_songs_from_paths(handler.hass, paths)
    if warnings:
        _LOGGER.debug("Rematch playlist swap warnings: %s", warnings[:5])
    if not songs:
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_NO_PLAYABLE_SONGS,
                "message": "No valid songs found in the selected playlist(s)",
            }
        )
        return None, paths
    return songs, paths


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

    # #2648: the end screen sends the playlist the room just shouted for. No
    # `playlists` key at all is the historic rematch — same music, untouched.
    # Everything below this block runs identically either way, which is the
    # point: swapping the songs must not become a second lifecycle.
    swap_songs, swap_paths = await _resolve_rematch_playlists(handler, ws, data)
    if swap_paths is not None and swap_songs is None:
        return  # the error was already sent; the finished game stands

    player_count = len(game_state.players)
    # #2706: remember the spectator socket before rematch_game() runs — its
    # reset callback (clear_admin_socket) nulls handler.admin_ws.
    previous_admin_ws = handler.admin_ws
    # #2706: decide on the socket identity BEFORE the rebuild, while the player
    # records are guaranteed intact.
    sender_is_participant = game_state.get_player_by_ws(ws) is not None
    try:
        game_state.rematch_game(songs=swap_songs, playlists=swap_paths)
    except NoPlayableSongsError as err:
        # rematch_game validates before it mutates, so the finished game is
        # still intact here — the host keeps the end screen and can pick again.
        await ws.send_json(
            {
                "type": "error",
                "code": ERR_NO_PLAYABLE_SONGS,
                "message": str(err),
            }
        )
        return

    # #1703: cancel any pending admin-disconnect pause task for the rematch.
    # rematch_game() preserves player records (admin may still be marked
    # disconnected), so a leftover grace timer would otherwise fire and pause
    # the brand-new LOBBY. cleanup_game_tasks previously ran only on dismiss.
    # #2648: it sits after the rebuild rather than before it now. rematch_game
    # is synchronous, so no timer can fire between the two lines — but a
    # rejected playlist swap returns above, and that path must not leave the
    # still-running game with its grace timer cancelled.
    await handler.cleanup_game_tasks()

    # Issue #841 Phase 3: announce the rematch (use case 20). TTS survives
    # rematch_game() — only end_game() tears the service down.
    await game_state.announce_rematch()
    _LOGGER.info("Rematch started with %d players", player_count)

    # #2706: this action is reachable from EITHER admin-capable socket, and
    # www/js/player-end.js sends it over the host's PARTICIPANT socket. Handing
    # that phone the admin slot gave it the unredacted broadcast (answers,
    # admin_song) for the whole rematch — exactly what _send_state_to forbids —
    # while the admin page, which only sends admin_connect once on open, was
    # left with the redacted copy and blank reveal fields. Only a genuine
    # spectator socket may claim the slot; a phone-initiated rematch restores
    # the spectator socket rematch_game() just cleared, if it is still open.
    if not sender_is_participant:
        handler.admin_ws = ws
    elif previous_admin_ws is not None and not previous_admin_ws.closed:
        handler.admin_ws = previous_admin_ws

    # The new admin_token belongs to whoever holds the admin slot; the
    # requesting socket gets it too, since it asked for the rematch.
    token_msg = {
        "type": "admin_token_update",
        "admin_token": game_state.admin_token,
        "game_id": game_state.game_id,
    }
    await ws.send_json(token_msg)
    if handler.admin_ws is not None and handler.admin_ws is not ws:
        await handler.admin_ws.send_json(token_msg)
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
    if language not in ("en", "de", "es", "fr", "nl", "it"):
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
