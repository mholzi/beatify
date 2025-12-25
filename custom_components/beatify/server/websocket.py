"""WebSocket handler for Beatify game connections."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from aiohttp import WSMsgType, web

from custom_components.beatify.const import (
    DOMAIN,
    ERR_ADMIN_EXISTS,
    ERR_ALREADY_SUBMITTED,
    ERR_GAME_ENDED,
    ERR_GAME_FULL,
    ERR_GAME_NOT_STARTED,
    ERR_INVALID_ACTION,
    ERR_NAME_INVALID,
    ERR_NAME_TAKEN,
    ERR_NOT_ADMIN,
    ERR_NOT_IN_GAME,
    ERR_ROUND_EXPIRED,
    LOBBY_DISCONNECT_GRACE_PERIOD,
    YEAR_MAX,
    YEAR_MIN,
)
from custom_components.beatify.game.state import GamePhase, GameState

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class BeatifyWebSocketHandler:
    """Handle WebSocket connections for Beatify."""

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

    async def handle(self, request: web.Request) -> web.WebSocketResponse:
        """
        Handle WebSocket connection.

        Args:
            request: aiohttp request

        Returns:
            WebSocket response

        """
        ws = web.WebSocketResponse()
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
                    _LOGGER.error("WebSocket error: %s", ws.exception())

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
            await ws.send_json({
                "type": "error",
                "code": ERR_GAME_NOT_STARTED,
                "message": "No active game",
            })
            return

        if msg_type == "join":
            name = data.get("name", "").strip()
            is_admin = data.get("is_admin", False)

            success, error_code = game_state.add_player(name, ws)

            if success:
                # Handle admin join/reconnection (Story 7-2)
                if is_admin:
                    # Check if reconnecting as the disconnected admin
                    if game_state.disconnected_admin_name:
                        if name.lower() == game_state.disconnected_admin_name.lower():
                            # Same admin reconnecting - cancel disconnect task
                            if self._admin_disconnect_task:
                                self._admin_disconnect_task.cancel()
                                self._admin_disconnect_task = None
                                _LOGGER.info(
                                    "Admin reconnected, cancelled pause task: %s", name
                                )

                            # Cancel pending removal if any
                            self.cancel_pending_removal(name)

                            # Resume game if paused
                            if game_state.phase == GamePhase.PAUSED:
                                if await game_state.resume_game():
                                    _LOGGER.info("Game resumed by admin reconnection")
                        else:
                            # Different person trying to claim admin
                            game_state.remove_player(name)
                            await ws.send_json({
                                "type": "error",
                                "code": ERR_ADMIN_EXISTS,
                                "message": "Only the original host can reconnect",
                            })
                            return
                    else:
                        # No disconnected admin - check for existing admin
                        existing_admin = any(
                            p.is_admin for p in game_state.players.values()
                            if p.name != name
                        )
                        if existing_admin:
                            # Remove the just-added player and return error
                            game_state.remove_player(name)
                            await ws.send_json({
                                "type": "error",
                                "code": ERR_ADMIN_EXISTS,
                                "message": "Game already has an admin",
                            })
                            return
                        game_state.set_admin(name)
                else:
                    # Regular player - cancel pending removal on reconnect
                    self.cancel_pending_removal(name)

                # Send full state to newly joined player
                state_msg = {"type": "state", **game_state.get_state()}
                try:
                    await ws.send_json(state_msg)
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("Failed to send state to new player: %s", err)
                    return
                # Broadcast to OTHER players only (avoid double send to joiner)
                for other_ws in list(self.connections):
                    if other_ws != ws and not other_ws.closed:
                        try:
                            await other_ws.send_json(state_msg)
                        except Exception:  # noqa: BLE001
                            pass
            else:
                error_messages = {
                    ERR_NAME_TAKEN: "Name taken, choose another",
                    ERR_NAME_INVALID: "Please enter a name",
                    ERR_GAME_FULL: "Game is full",
                    ERR_GAME_ENDED: "This game has ended",
                }
                await ws.send_json({
                    "type": "error",
                    "code": error_code,
                    "message": error_messages.get(error_code, "Join failed"),
                })

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
                await ws.send_json({
                    "type": "error",
                    "code": ERR_NOT_ADMIN,
                    "message": "Only admin can perform this action",
                })
                return

            if action == "start_game":
                if game_state.phase != GamePhase.LOBBY:
                    await ws.send_json({
                        "type": "error",
                        "code": ERR_INVALID_ACTION,
                        "message": "Game already started",
                    })
                    return

                # Start the first round (plays song, sets timer)
                success = await game_state.start_round(self.hass)
                if success:
                    await self.broadcast_state()
                else:
                    await ws.send_json({
                        "type": "error",
                        "code": ERR_GAME_NOT_STARTED,
                        "message": "Failed to start game - no songs available",
                    })

            elif action == "next_round":
                if game_state.phase == GamePhase.PLAYING:
                    # Early advance - end current round first
                    await game_state.end_round()
                    # Broadcast handled by round_end_callback
                elif game_state.phase == GamePhase.REVEAL:
                    # Start next round or end game
                    if game_state.last_round:
                        # No more rounds, end game
                        game_state.phase = GamePhase.END
                        await self.broadcast_state()
                    else:
                        # Start next round
                        success = await game_state.start_round(self.hass)
                        if success:
                            await self.broadcast_state()
                        else:
                            # No more songs
                            game_state.phase = GamePhase.END
                            await self.broadcast_state()
                else:
                    await ws.send_json({
                        "type": "error",
                        "code": ERR_INVALID_ACTION,
                        "message": "Cannot advance round in current phase",
                    })

            elif action == "stop_song":
                if game_state.phase != GamePhase.PLAYING:
                    await ws.send_json({
                        "type": "error",
                        "code": ERR_INVALID_ACTION,
                        "message": "No song playing",
                    })
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
                    await ws.send_json({
                        "type": "error",
                        "code": ERR_INVALID_ACTION,
                        "message": "Invalid volume direction",
                    })
                    return

                # Calculate new volume
                new_level = game_state.adjust_volume(direction)

                # Apply to media player
                if game_state._media_player_service:
                    success = await game_state._media_player_service.set_volume(
                        new_level
                    )
                    if not success:
                        _LOGGER.warning(
                            "Failed to set volume to %.0f%%", new_level * 100
                        )

                _LOGGER.info(
                    "Volume adjusted %s to %.0f%%", direction, new_level * 100
                )

                # Send feedback to requester only (not broadcast)
                await ws.send_json({
                    "type": "volume_changed",
                    "level": new_level,
                })

            elif action == "end_game":
                if game_state.phase not in (GamePhase.PLAYING, GamePhase.REVEAL):
                    await ws.send_json({
                        "type": "error",
                        "code": ERR_INVALID_ACTION,
                        "message": "Cannot end game in current phase",
                    })
                    return

                # Cancel timer if running
                game_state.cancel_timer()

                # Stop media playback
                if game_state._media_player_service:
                    await game_state._media_player_service.stop()

                # Transition to END
                game_state.phase = GamePhase.END
                _LOGGER.info(
                    "Admin ended game early at round %d", game_state.round
                )

                # Broadcast final state to all players FIRST (Story 7-5)
                await self.broadcast_state()

                # Send game_ended notification (Story 7-5)
                await self.broadcast({"type": "game_ended"})

                # Cleanup pending tasks (Story 7-5)
                await self.cleanup_game_tasks()

            else:
                _LOGGER.warning("Unknown admin action: %s", action)

        elif msg_type == "get_state":
            # Dashboard/observer requesting current state (Story 10.4)
            state = game_state.get_state()
            if state:
                await ws.send_json({"type": "state", **state})

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
            await ws.send_json({
                "type": "error",
                "code": ERR_NOT_IN_GAME,
                "message": "Not in game",
            })
            return

        # Check phase
        if game_state.phase != GamePhase.PLAYING:
            await ws.send_json({
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Not in playing phase",
            })
            return

        # Check if already submitted
        if player.submitted:
            await ws.send_json({
                "type": "error",
                "code": ERR_ALREADY_SUBMITTED,
                "message": "Already submitted",
            })
            return

        # Check deadline (uses game_state's time function for testability)
        if game_state.is_deadline_passed():
            await ws.send_json({
                "type": "error",
                "code": ERR_ROUND_EXPIRED,
                "message": "Time's up!",
            })
            return

        # Validate year
        year = data.get("year")
        if not isinstance(year, int) or year < YEAR_MIN or year > YEAR_MAX:
            await ws.send_json({
                "type": "error",
                "code": ERR_INVALID_ACTION,
                "message": "Invalid year",
            })
            return

        # Parse bet flag (Story 5.3)
        bet = data.get("bet", False)
        player.bet = bool(bet)

        # Record submission
        submission_time = time.time()
        player.submit_guess(year, submission_time)

        # Send acknowledgment
        await ws.send_json({
            "type": "submit_ack",
            "year": year,
        })

        # Broadcast updated state (player.submitted now True)
        await self.broadcast_state()

        _LOGGER.info(
            "Player %s submitted guess: %d at %.2f",
            player.name, year, submission_time
        )

    async def broadcast(self, message: dict) -> None:
        """
        Broadcast message to all connected clients.

        Args:
            message: Message to broadcast

        """
        for ws in list(self.connections):
            if not ws.closed:
                try:
                    await ws.send_json(message)
                except Exception as err:  # noqa: BLE001
                    _LOGGER.warning("Failed to send to WebSocket: %s", err)

    async def broadcast_state(self) -> None:
        """Broadcast current game state to all connected players."""
        game_state = self.hass.data.get(DOMAIN, {}).get("game")
        if not game_state:
            return

        state = game_state.get_state()
        if state:
            state_msg = {"type": "state", **state}
            await self.broadcast(state_msg)

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

        _LOGGER.info(
            "Player disconnected: %s (is_admin: %s)", player_name, player.is_admin
        )

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
        else:
            # Regular player: remove after grace period (existing behavior)
            async def remove_after_timeout() -> None:
                await asyncio.sleep(LOBBY_DISCONNECT_GRACE_PERIOD)
                if player_name in game_state.players:
                    if not game_state.players[player_name].connected:
                        game_state.remove_player(player_name)
                        await self.broadcast_state()
                        _LOGGER.info("Player removed after timeout: %s", player_name)
                if player_name in self._pending_removals:
                    del self._pending_removals[player_name]

            task = asyncio.create_task(remove_after_timeout())
            self._pending_removals[player_name] = task

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
