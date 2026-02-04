"""WebSocket handler for Beatify game connections."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from aiohttp import WSMsgType, web

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
    LOBBY_DISCONNECT_GRACE_PERIOD,
    YEAR_MAX,
    YEAR_MIN,
)
from custom_components.beatify.game.state import GamePhase, GameState

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from custom_components.beatify.analytics import AnalyticsStorage

_LOGGER = logging.getLogger(__name__)


class BeatifyWebSocketHandler:
    """Handle WebSocket connections for Beatify."""

    # Ping interval in seconds (must be less than proxy timeout, typically 60s)
    # aiohttp's heartbeat sends ping frames automatically
    HEARTBEAT_INTERVAL = 30

    def __init__(self, hass: HomeAssistant) -> None:
        """
        Initialize handler.

        Args:
            hass: Home Assistant instance

        """
        self.hass = hass
        self.connections: set[web.WebSocketResponse] = set()
        self._pending_removals: dict[str, asyncio.Task] = {}
        self._admin_disconnect_task: asyncio.Task | None = None
        self._analytics: AnalyticsStorage | None = None
        # Debouncing for concurrent player joins (Issue #41)
        self._broadcast_debounce_task: asyncio.Task | None = None
        self._broadcast_debounce_delay = 0.05  # 50ms

    def set_analytics(self, analytics: AnalyticsStorage) -> None:
        """
        Set analytics storage for error recording (Story 19.1).

        Args:
            analytics: AnalyticsStorage instance

        """
        self._analytics = analytics

    def _record_error(self, error_type: str, message: str) -> None:
        """
        Record error event to analytics (Story 19.1 AC: #2).

        Args:
            error_type: Error type constant
            message: Human-readable error message

        """
        if self._analytics:
            self._analytics.record_error(error_type, message)

    async def handle(self, request: web.Request) -> web.WebSocketResponse:
        """
        Handle WebSocket connection.

        Args:
            request: aiohttp request

        Returns:
            WebSocket response

        """
        # heartbeat parameter enables automatic ping/pong to prevent proxy timeouts
        ws = web.WebSocketResponse(heartbeat=self.HEARTBEAT_INTERVAL)
        await ws.prepare(request)

        self.connections.add(ws)
        _LOGGER.debug("WebSocket connected, total: %d", len(self.connections))

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        await self._handle_message(ws, msg.json())
                    except Exception as err:  # noqa: BLE001
                        _LOGGER.warning("Failed to parse WebSocket message: %s", err)
                elif msg.type == WSMsgType.ERROR:
                    err_msg = str(ws.exception())
                    _LOGGER.error("WebSocket error: %s", err_msg)
                    # Record WebSocket error to analytics (Story 19.1 AC: #2)
                    from custom_components.beatify.analytics import (  # noqa: PLC0415
                        ERROR_WEBSOCKET_DISCONNECT,
                    )

                    self._record_error(ERROR_WEBSOCKET_DISCONNECT, err_msg)

        finally:
            self.connections.discard(ws)
            await self._handle_disconnect(ws)
            _LOGGER.debug("WebSocket disconnected, total: %d", len(self.connections))

        return ws

    async def _handle_message(  # noqa: PLR0912, PLR0915
        self, ws: web.WebSocketResponse, data: dict
    ) -> None:
        """
        Handle incoming WebSocket message.

        Args:
            ws: WebSocket connection
            data: Parsed message data

        """
        msg_type = data.get("type")
        game_state = self.hass.data.get(DOMAIN, {}).get("game")

        if not game_state or not game_state.game_id:
            await ws.send_json(
                {
                    "type": "error",
                    "code": ERR_GAME_NOT_STARTED,
                    "message": "No active game",
                }
            )
            return

        if msg_type == "join":
            name = data.get("name", "").strip()
            is_admin = data.get("is_admin", False)

            success, error_code = game_state.add_player(name, ws)

            if success:
                # Get the player session for session_id (Story 11.1)
                player = game_state.get_player(name)

                # Handle admin join/reconnection (Story 7-2)
                if is_admin:
                    # Check if reconnecting as the disconnected admin
                    if game_state.disconnected_admin_name:
                        if name.lower() == game_state.disconnected_admin_name.lower():
                            # Same admin reconnecting - cancel disconnect task
                            if self._admin_disconnect_task:
                                self._admin_disconnect_task.cancel()
                                self._admin_disconnect_task = None
                                _LOGGER.info("Admin reconnected, cancelled pause task: %s", name)

                            # Cancel pending removal if any
                            self.cancel_pending_removal(name)

                            # Resume game if paused
                            if game_state.phase == GamePhase.PAUSED:
                                if await game_state.resume_game():
                                    _LOGGER.info("Game resumed by admin reconnection")
                        else:
                            # Different person trying to claim admin
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
                        # No disconnected admin - check for existing admin
                        existing_admin = any(
                            p.is_admin for p in game_state.players.values() if p.name != name
                        )
                        if existing_admin:
                            # Remove the just-added player and return error
                            game_state.remove_player(name)
                            await ws.send_json(
                                {
                                    "type": "error",
                                    "code": ERR_ADMIN_EXISTS,
                                    "message": "Game already has an admin",
                                }
                            )
                            return
                        game_state.set_admin(name)
                else:
                    # Regular player - cancel pending removal on reconnect
                    self.cancel_pending_removal(name)

                # Send join acknowledgment with session_id (Story 11.1)
                # Only the joining player receives their session_id (security)
                if player:
                    await ws.send_json(
                        {
                            "type": "join_ack",
                            "session_id": player.session_id,
                            "game_id": game_state.game_id,
                        }
                    )

                # Send full state to newly joined player
                state_msg = {"type": "state", **game_state.get_state()}
                try:
                    await ws.send_json(state_msg)
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("Failed to send state to new player: %s", err)
                    return
                # Debounced broadcast to others (Issue #41 - batches concurrent joins)
                # Joiner already got state above; this notifies other players
                await self.debounced_broadcast_state()
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

        elif msg_type == "submit":
            await self._handle_submit(ws, data, game_state)

        elif msg_type == "admin":
            action = data.get("action")

            # Find sender's player session
            sender = None
            for player in game_state.players.values():
                if player.ws == ws:
                    sender = player
                    break

            if not sender or not sender.is_admin:
                await ws.send_json(
                    {
                        "type": "error",
                        "code": ERR_NOT_ADMIN,
                        "message": "Only admin can perform this action",
                    }
                )
                return

            if action == "start_game":
                if game_state.phase != GamePhase.LOBBY:
                    await ws.send_json(
                        {
                            "type": "error",
                            "code": ERR_INVALID_ACTION,
                            "message": "Game already started",
                        }
                    )
                    return

                # Start the first round (plays song, sets timer)
                success = await game_state.start_round(self.hass)
                if success:
                    await self.broadcast_state()
                else:
                    # Determine specific error based on game state
                    error_code = ERR_GAME_NOT_STARTED
                    error_message = "Failed to start game"

                    if game_state.phase == GamePhase.PAUSED:
                        # Game paused due to specific error
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

            elif action == "next_round":
                if game_state.phase == GamePhase.PLAYING:
                    # Early advance - end current round first
                    await game_state.end_round()
                    # Broadcast handled by round_end_callback
                elif game_state.phase == GamePhase.REVEAL:
                    # Start next round or end game
                    if game_state.last_round:
                        # Record game stats before ending (Story 14.4, 19.1)
                        stats_service = self.hass.data.get(DOMAIN, {}).get("stats")
                        if stats_service:
                            game_summary = game_state.finalize_game()
                            await stats_service.record_game(
                                game_summary, difficulty=game_state.difficulty
                            )
                            _LOGGER.debug("Game stats recorded for natural end")

                        # No more rounds, end game
                        game_state.phase = GamePhase.END
                        await self.broadcast_state()
                    else:
                        # Start next round
                        success = await game_state.start_round(self.hass)
                        if success:
                            await self.broadcast_state()
                        else:
                            # Record stats before ending due to no songs (Story 14.4, 19.1)
                            stats_service = self.hass.data.get(DOMAIN, {}).get("stats")
                            if stats_service:
                                game_summary = game_state.finalize_game()
                                await stats_service.record_game(
                                    game_summary, difficulty=game_state.difficulty
                                )
                                _LOGGER.debug("Game stats recorded (no songs remaining)")

                            # No more songs
                            game_state.phase = GamePhase.END
                            await self.broadcast_state()
                else:
                    await ws.send_json(
                        {
                            "type": "error",
                            "code": ERR_INVALID_ACTION,
                            "message": "Cannot advance round in current phase",
                        }
                    )

            elif action == "stop_song":
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
                    # Already stopped, no-op
                    return

                # Stop playback
                if game_state._media_player_service:
                    await game_state._media_player_service.stop()

                game_state.song_stopped = True
                _LOGGER.info("Admin stopped song in round %d", game_state.round)

                # Notify all clients
                await self.broadcast({"type": "song_stopped"})

            elif action == "set_volume":
                direction = data.get("direction")  # "up" or "down"
                if direction not in ("up", "down"):
                    await ws.send_json(
                        {
                            "type": "error",
                            "code": ERR_INVALID_ACTION,
                            "message": "Invalid volume direction",
                        }
                    )
                    return

                # Calculate new volume
                new_level = game_state.adjust_volume(direction)

                # Apply to media player
                if game_state._media_player_service:
                    success = await game_state._media_player_service.set_volume(new_level)
                    if not success:
                        _LOGGER.warning("Failed to set volume to %.0f%%", new_level * 100)

                _LOGGER.info("Volume adjusted %s to %.0f%%", direction, new_level * 100)

                # Send feedback to requester only (not broadcast)
                await ws.send_json(
                    {
                        "type": "volume_changed",
                        "level": new_level,
                    }
                )

            elif action == "end_game":
                # Issue #108: Modified to stay in END phase without wiping players
                if game_state.phase not in (GamePhase.PLAYING, GamePhase.REVEAL):
                    await ws.send_json(
                        {
                            "type": "error",
                            "code": ERR_INVALID_ACTION,
                            "message": "Cannot end game in current phase",
                        }
                    )
                    return

                # Cancel timer if running
                game_state.cancel_timer()

                # Stop media playback
                if game_state._media_player_service:
                    await game_state._media_player_service.stop()

                # Record game stats BEFORE transitioning to END (Story 14.4, 19.1)
                stats_service = self.hass.data.get(DOMAIN, {}).get("stats")
                if stats_service:
                    game_summary = game_state.finalize_game()
                    await stats_service.record_game(game_summary, difficulty=game_state.difficulty)
                    _LOGGER.debug("Game stats recorded for early end")

                # Transition to END - players stay connected for rematch option
                game_state.phase = GamePhase.END
                _LOGGER.info(
                    "Admin ended game early at round %d - players preserved for rematch",
                    game_state.round,
                )

                # Broadcast final state to all players
                await self.broadcast_state()
                # NOTE: game_state.end_game() NOT called - admin can now Rematch or Dismiss
                # NOTE: game_ended NOT sent here - only sent on dismiss_game

            elif action == "dismiss_game":
                # Issue #108: Full teardown - only allowed from END phase
                if game_state.phase != GamePhase.END:
                    await ws.send_json(
                        {
                            "type": "error",
                            "code": ERR_INVALID_ACTION,
                            "message": "Can only dismiss from END phase",
                        }
                    )
                    return

                # Fully reset game state - wipes all players
                game_state.end_game()
                _LOGGER.info("Game dismissed - all players cleared")

                # Send game_ended notification to kick all players
                await self.broadcast({"type": "game_ended"})

                # Broadcast cleared state
                await self.broadcast_state()

                # Cleanup pending tasks
                await self.cleanup_game_tasks()

            elif action == "rematch_game":
                # Issue #108: Soft reset for rematch - preserves players
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

                # Broadcast rematch event so clients transition to lobby
                await self.broadcast({"type": "rematch_started"})
                await self.broadcast_state()

            elif action == "set_language":
                # Language selection (Story 12.4) - only in LOBBY phase
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
                if language not in ("en", "de", "es"):
                    language = "en"  # Default to English for invalid codes

                game_state.language = language
                _LOGGER.info("Game language set to: %s", language)

                # Broadcast state with updated language
                await self.broadcast_state()

            else:
                _LOGGER.warning("Unknown admin action: %s", action)

        elif msg_type == "reconnect":
            # Session-based reconnection (Story 11.2)
            await self._handle_reconnect(ws, data, game_state)

        elif msg_type == "leave":
            # Intentional leave game (Story 11.5)
            await self._handle_leave(ws, game_state)

        elif msg_type == "get_state":
            # Dashboard/observer requesting current state (Story 10.4)
            state = game_state.get_state()
            if state:
                await ws.send_json({"type": "state", **state})

        elif msg_type == "get_steal_targets":
            # Request available steal targets (Story 15.3 AC2, AC5)
            await self._handle_get_steal_targets(ws, game_state)

        elif msg_type == "steal":
            # Execute steal power-up (Story 15.3 AC2, AC3)
            await self._handle_steal(ws, data, game_state)

        elif msg_type == "reaction":
            # Live reactions during reveal (Story 18.9)
            player = game_state.get_player_by_ws(ws)
            if not player:
                return

            if game_state.phase != GamePhase.REVEAL:
                return  # Silent ignore - only during REVEAL

            emoji = data.get("emoji", "")
            if emoji not in ["🔥", "😂", "😱", "👏", "🤔"]:
                return  # Invalid emoji

            if game_state.record_reaction(player.name, emoji):
                await self.broadcast(
                    {
                        "type": "player_reaction",
                        "player_name": player.name,
                        "emoji": emoji,
                    }
                )

        elif msg_type == "artist_guess":
            # Artist challenge guess submission (Story 20.3)
            await self._handle_artist_guess(ws, data, game_state)

        elif msg_type == "movie_guess":
            # Movie quiz guess submission (Issue #28)
            await self._handle_movie_guess(ws, data, game_state)

        else:
            _LOGGER.warning("Unknown message type: %s", msg_type)

    async def _handle_submit(
        self, ws: web.WebSocketResponse, data: dict, game_state: GameState
    ) -> None:
        """
        Handle guess submission from player.

        Args:
            ws: WebSocket connection
            data: Message data containing year guess
            game_state: Current game state

        """
        # Find player by WebSocket
        player = None
        for p in game_state.players.values():
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

        # Check phase
        if game_state.phase != GamePhase.PLAYING:
            await ws.send_json(
                {
                    "type": "error",
                    "code": ERR_INVALID_ACTION,
                    "message": "Not in playing phase",
                }
            )
            return

        # Check if already submitted
        if player.submitted:
            await ws.send_json(
                {
                    "type": "error",
                    "code": ERR_ALREADY_SUBMITTED,
                    "message": "Already submitted",
                }
            )
            return

        # Check deadline (uses game_state's time function for testability)
        if game_state.is_deadline_passed():
            await ws.send_json(
                {
                    "type": "error",
                    "code": ERR_ROUND_EXPIRED,
                    "message": "Time's up!",
                }
            )
            return

        # Validate year
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

        # Parse bet flag (Story 5.3)
        bet = data.get("bet", False)
        player.bet = bool(bet)

        # Record submission
        submission_time = time.time()
        player.submit_guess(year, submission_time)

        # Send acknowledgment
        await ws.send_json(
            {
                "type": "submit_ack",
                "year": year,
            }
        )

        # Broadcast updated state (player.submitted now True)
        await self.broadcast_state()

        # Story 20.9: Check for early reveal when all guesses are complete
        # Note: _trigger_early_reveal() calls end_round() which broadcasts via callback
        all_complete = game_state.check_all_guesses_complete()
        _LOGGER.debug(
            "Early reveal check: phase=%s, all_complete=%s, artist_challenge=%s",
            game_state.phase.value,
            all_complete,
            game_state.artist_challenge_enabled,
        )
        if game_state.phase == GamePhase.PLAYING and all_complete:
            await game_state._trigger_early_reveal()

        _LOGGER.info("Player %s submitted guess: %d at %.2f", player.name, year, submission_time)

    async def _handle_reconnect(
        self, ws: web.WebSocketResponse, data: dict, game_state: GameState
    ) -> None:
        """
        Handle session-based reconnection (Story 11.2).

        Args:
            ws: WebSocket connection
            data: Message data containing session_id
            game_state: Current game state

        """
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

        # Find player by session ID
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

        # Check game phase - cannot reconnect to ended game
        if game_state.phase == GamePhase.END:
            await ws.send_json(
                {
                    "type": "error",
                    "code": ERR_GAME_ENDED,
                    "message": "Game has ended",
                }
            )
            return

        # Handle dual-tab scenario: close old connection if still active
        if player.connected and player.ws and not player.ws.closed:
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
                pass  # Old connection may already be dead
            _LOGGER.info("Session takeover: %s (old tab disconnected)", player.name)

        # Update connection
        player.ws = ws
        player.connected = True

        # Cancel any pending removal for this player
        self.cancel_pending_removal(player.name)

        # If admin, handle reconnect logic
        if player.is_admin:
            if self._admin_disconnect_task:
                self._admin_disconnect_task.cancel()
                self._admin_disconnect_task = None
                _LOGGER.info("Admin reconnected via session, cancelled pause task")

            # Resume game if paused
            if game_state.phase == GamePhase.PAUSED:
                if await game_state.resume_game():
                    _LOGGER.info("Game resumed by admin session reconnection")

        # Send reconnect acknowledgment
        await ws.send_json(
            {
                "type": "reconnect_ack",
                "name": player.name,
                "success": True,
            }
        )

        # Send current state to reconnected player
        state_msg = {"type": "state", **game_state.get_state()}
        await ws.send_json(state_msg)

        # Broadcast updated state to all players (connected status changed)
        await self.broadcast_state()

        _LOGGER.info("Player reconnected via session: %s (score: %d)", player.name, player.score)

    async def _handle_leave(self, ws: web.WebSocketResponse, game_state: GameState) -> None:
        """
        Handle intentional leave game (Story 11.5).

        Args:
            ws: WebSocket connection
            game_state: Current game state

        """
        # Find player by WebSocket
        player = None
        player_name = None
        for name, p in game_state.players.items():
            if p.ws == ws:
                player = p
                player_name = name
                break

        if not player:
            return

        # Block admin leave
        if player.is_admin:
            await ws.send_json(
                {
                    "type": "error",
                    "code": ERR_ADMIN_CANNOT_LEAVE,
                    "message": "Host cannot leave. End the game instead.",
                }
            )
            return

        # Remove player completely (also clears session mapping via Story 11.1)
        game_state.remove_player(player_name)

        # Confirm to leaving player
        await ws.send_json({"type": "left"})

        # Close WebSocket from server side (prevents client auto-reconnect)
        await ws.close()

        # Broadcast state update to remaining players
        await self.broadcast_state()

        _LOGGER.info("Player left game intentionally: %s", player_name)

    async def _handle_get_steal_targets(
        self, ws: web.WebSocketResponse, game_state: GameState
    ) -> None:
        """
        Handle request for available steal targets (Story 15.3 AC2, AC5).

        Args:
            ws: WebSocket connection
            game_state: Current game state

        """
        # Find player by WebSocket
        player = None
        for p in game_state.players.values():
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

        # Check if player has steal available
        if not player.steal_available:
            await ws.send_json(
                {
                    "type": "error",
                    "code": ERR_INVALID_ACTION,
                    "message": "No steal available",
                }
            )
            return

        # Get available targets (privacy: only requesting player sees this)
        targets = game_state.get_steal_targets(player.name)

        await ws.send_json(
            {
                "type": "steal_targets",
                "targets": targets,
            }
        )

    async def _handle_steal(
        self, ws: web.WebSocketResponse, data: dict, game_state: GameState
    ) -> None:
        """
        Handle steal execution (Story 15.3 AC2, AC3).

        Args:
            ws: WebSocket connection
            data: Message data containing target name
            game_state: Current game state

        """
        # Find player by WebSocket
        player = None
        for p in game_state.players.values():
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

        # Execute steal via GameState
        result = game_state.use_steal(player.name, target_name)

        if result["success"]:
            # Send acknowledgment to stealer
            await ws.send_json(
                {
                    "type": "steal_ack",
                    "success": True,
                    "target": result["target"],
                    "year": result["year"],
                }
            )

            # Broadcast updated state (stealer now has submitted)
            await self.broadcast_state()
        else:
            # Send error to stealer
            await ws.send_json(
                {
                    "type": "error",
                    "code": result["error"],
                    "message": self._get_steal_error_message(result["error"]),
                }
            )

    def _get_steal_error_message(self, error_code: str) -> str:
        """Get human-readable message for steal error codes."""
        messages = {
            ERR_NOT_IN_GAME: "Not in game",
            ERR_INVALID_ACTION: "Cannot steal now",
            "NO_STEAL_AVAILABLE": "No steal available",
            "TARGET_NOT_SUBMITTED": "Target has not submitted yet",
            "CANNOT_STEAL_SELF": "Cannot steal from yourself",
        }
        return messages.get(error_code, "Steal failed")

    async def _handle_artist_guess(
        self, ws: web.WebSocketResponse, data: dict, game_state: GameState
    ) -> None:
        """
        Handle artist guess submission (Story 20.3).

        Args:
            ws: WebSocket connection
            data: Message data containing artist guess
            game_state: Current game state

        """
        # Validate phase
        if game_state.phase != GamePhase.PLAYING:
            await ws.send_json(
                {
                    "type": "error",
                    "code": ERR_INVALID_ACTION,
                    "message": "Can only guess during PLAYING phase",
                }
            )
            return

        # Get player from connection
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

        # Validate artist challenge exists
        if not game_state.artist_challenge:
            await ws.send_json(
                {
                    "type": "error",
                    "code": ERR_NO_ARTIST_CHALLENGE,
                    "message": "No artist challenge this round",
                }
            )
            return

        # Get and validate artist guess
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

        # Submit guess
        guess_time = time.time()
        result = game_state.submit_artist_guess(player.name, artist, guess_time)

        # Story 20.9: Track that player has made an artist guess
        player.has_artist_guess = True

        # Send acknowledgment
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

        # Broadcast state if winner changed (so all players see winner)
        if result.get("first"):
            await self.broadcast_state()

        # Story 20.9: Check for early reveal when all guesses are complete
        # Note: _trigger_early_reveal() calls end_round() which broadcasts via callback
        if game_state.phase == GamePhase.PLAYING and game_state.check_all_guesses_complete():
            await game_state._trigger_early_reveal()

        _LOGGER.debug(
            "Artist guess from %s: '%s' -> correct=%s, first=%s",
            player.name,
            artist,
            result["correct"],
            result.get("first", False),
        )

    async def _handle_movie_guess(
        self, ws: web.WebSocketResponse, data: dict, game_state: GameState
    ) -> None:
        """
        Handle movie quiz guess submission (Issue #28).

        Args:
            ws: WebSocket connection
            data: Message data containing movie guess
            game_state: Current game state

        """
        # Validate phase
        if game_state.phase != GamePhase.PLAYING:
            await ws.send_json(
                {
                    "type": "error",
                    "code": ERR_INVALID_ACTION,
                    "message": "Can only guess during PLAYING phase",
                }
            )
            return

        # Get player from connection
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

        # Validate movie challenge exists
        if not game_state.movie_challenge:
            await ws.send_json(
                {
                    "type": "error",
                    "code": ERR_NO_MOVIE_CHALLENGE,
                    "message": "No movie quiz this round",
                }
            )
            return

        # Get and validate movie guess
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

        # Submit guess with server-side timing
        guess_time = time.time()
        result = game_state.submit_movie_guess(player.name, movie, guess_time)

        # Issue #28: Track that player has made a movie guess
        player.has_movie_guess = True

        # Send acknowledgment
        response: dict = {
            "type": "movie_guess_ack",
            "correct": result["correct"],
            "already_guessed": result["already_guessed"],
        }

        if result["correct"] and not result["already_guessed"]:
            response["rank"] = result["rank"]
            response["bonus"] = result["bonus"]

        await ws.send_json(response)

        # Issue #28: Check for early reveal when all guesses are complete
        # Note: _trigger_early_reveal() calls end_round() which broadcasts via callback
        if game_state.phase == GamePhase.PLAYING and game_state.check_all_guesses_complete():
            await game_state._trigger_early_reveal()

        _LOGGER.debug(
            "Movie guess from %s: '%s' -> correct=%s, rank=%s",
            player.name,
            movie,
            result["correct"],
            result.get("rank"),
        )

    async def broadcast(self, message: dict) -> None:
        """
        Broadcast message to all connected clients in parallel (Issue #41).

        Uses asyncio.gather() for parallel sends instead of sequential awaits.

        Args:
            message: Message to broadcast

        """
        if not self.connections:
            return

        # Build list of send tasks for all open connections
        tasks = []
        for ws in list(self.connections):
            if not ws.closed:
                tasks.append(self._safe_send(ws, message))

        # Execute all sends in parallel
        if tasks:
            await asyncio.gather(*tasks)

    async def _safe_send(self, ws: web.WebSocketResponse, message: dict) -> None:
        """
        Send message to a single WebSocket, catching errors.

        Args:
            ws: WebSocket connection
            message: Message to send

        """
        try:
            await ws.send_json(message)
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Failed to send to WebSocket: %s", err)

    async def debounced_broadcast_state(self) -> None:
        """
        Broadcast state with debouncing for concurrent events (Issue #41).

        Batches rapid state changes (like multiple players joining)
        into a single broadcast after a short delay. This prevents
        N broadcasts when N players join within the debounce window.

        """
        # Cancel any pending broadcast
        if self._broadcast_debounce_task and not self._broadcast_debounce_task.done():
            self._broadcast_debounce_task.cancel()
            try:
                await self._broadcast_debounce_task
            except asyncio.CancelledError:
                pass

        async def delayed_broadcast() -> None:
            await asyncio.sleep(self._broadcast_debounce_delay)
            await self.broadcast_state()

        self._broadcast_debounce_task = asyncio.create_task(delayed_broadcast())

    async def broadcast_state(self) -> None:
        """Broadcast current game state to all connected players."""
        game_state = self.hass.data.get(DOMAIN, {}).get("game")
        if not game_state:
            _LOGGER.warning("broadcast_state: No game state found in hass.data")
            return

        state = game_state.get_state()
        if state:
            _LOGGER.debug(
                "broadcast_state: phase=%s, connections=%d",
                state.get("phase"),
                len(self.connections),
            )
            state_msg = {"type": "state", **state}
            await self.broadcast(state_msg)
        else:
            _LOGGER.warning("broadcast_state: get_state() returned None")

    async def broadcast_metadata_update(self, metadata: dict) -> None:
        """
        Broadcast song metadata update to all connected players (Issue #42).

        This is called when metadata becomes available after round start,
        allowing clients to update album art/artist/title with animation.

        Args:
            metadata: Dict with artist, title, album_art

        """
        _LOGGER.debug(
            "broadcast_metadata_update: %s - %s",
            metadata.get("artist"),
            metadata.get("title"),
        )
        await self.broadcast({"type": "metadata_update", "song": metadata})

    async def _handle_disconnect(self, ws: web.WebSocketResponse) -> None:
        """
        Handle WebSocket disconnection with grace period.

        Args:
            ws: Disconnected WebSocket

        """
        game_state = self.hass.data.get(DOMAIN, {}).get("game")
        if not game_state:
            return

        # Find player by WebSocket
        player_name = None
        player = None
        for name, p in game_state.players.items():
            if p.ws == ws:
                player_name = name
                player = p
                player.connected = False
                break

        if not player_name or not player:
            return

        _LOGGER.info("Player disconnected: %s (is_admin: %s)", player_name, player.is_admin)

        # Broadcast disconnect state immediately
        await self.broadcast_state()

        # Admin disconnect: pause game after grace period (Story 7-1)
        if player.is_admin:

            async def pause_after_timeout() -> None:
                await asyncio.sleep(LOBBY_DISCONNECT_GRACE_PERIOD)
                # Check if admin still disconnected
                if player_name in game_state.players:
                    admin = game_state.players[player_name]
                    if not admin.connected:
                        # pause_game() is async and handles media stop internally
                        if await game_state.pause_game("admin_disconnected"):
                            await self.broadcast_state()
                            _LOGGER.info("Game paused due to admin disconnect")

            # Store task for cancellation on reconnect
            self._admin_disconnect_task = asyncio.create_task(pause_after_timeout())
        # Story 11.3: Regular players persist indefinitely - no removal timeout
        # Player stays in game with connected=false, session allows reconnect
        # Score and stats preserved, counts toward MAX_PLAYERS (intentional)

    async def cleanup_game_tasks(self) -> None:
        """
        Cancel all pending tasks related to the game (Story 7-5).

        Called when game ends to prevent dangling async tasks.

        """
        # Cancel all pending player removals
        for task in list(self._pending_removals.values()):
            if not task.done():
                task.cancel()
        self._pending_removals.clear()

        # Cancel admin disconnect task
        if self._admin_disconnect_task and not self._admin_disconnect_task.done():
            self._admin_disconnect_task.cancel()
        self._admin_disconnect_task = None

        _LOGGER.debug("Cleaned up all pending game tasks")

    def cancel_pending_removal(self, player_name: str) -> None:
        """
        Cancel a pending player removal (on reconnect).

        Args:
            player_name: Name of reconnecting player

        """
        if player_name in self._pending_removals:
            self._pending_removals[player_name].cancel()
            del self._pending_removals[player_name]
            _LOGGER.info("Cancelled removal for reconnecting player: %s", player_name)
