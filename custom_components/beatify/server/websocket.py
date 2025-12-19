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
                # Handle admin join
                if is_admin:
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

            else:
                _LOGGER.warning("Unknown admin action: %s", action)

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
        for name, player in game_state.players.items():
            if player.ws == ws:
                player_name = name
                player.connected = False
                break

        if not player_name:
            return

        _LOGGER.info("Player disconnected: %s", player_name)

        # Broadcast disconnect state
        await self.broadcast_state()

        # Schedule removal after grace period
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
