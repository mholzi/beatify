"""WebSocket handler for Beatify game connections."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from aiohttp import WSMsgType, web

from custom_components.beatify.const import (
    DOMAIN,
    ERR_GAME_NOT_STARTED,
    LOBBY_DISCONNECT_GRACE_PERIOD,
)
from custom_components.beatify.game.state import GamePhase
from custom_components.beatify.server.serializers import build_state_message, get_game_state
from custom_components.beatify.server.ws_handlers import (
    handle_admin,
    handle_admin_connect,
    handle_artist_guess,
    handle_get_state,
    handle_get_steal_targets,
    handle_join,
    handle_leave,
    handle_movie_guess,
    handle_reaction,
    handle_reconnect,
    handle_steal,
    handle_submit,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from custom_components.beatify.analytics import AnalyticsStorage

_LOGGER = logging.getLogger(__name__)


class BeatifyWebSocketHandler:
    """Handle WebSocket connections for Beatify."""

    # Ping interval in seconds (must be less than proxy timeout, typically 60s)
    # aiohttp's heartbeat sends ping frames automatically
    HEARTBEAT_INTERVAL = 30
    RATE_LIMIT_CONNECTIONS = 10
    RATE_LIMIT_WINDOW = 60  # seconds

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
        self._connection_rate_limits: dict[str, list[float]] = {}
        self._last_rate_sweep: float = 0.0
        self._message_handlers = {
            "join": handle_join,
            "submit": handle_submit,
            "admin": handle_admin,
            "admin_connect": handle_admin_connect,
            "reconnect": handle_reconnect,
            "leave": handle_leave,
            "get_state": handle_get_state,
            "get_steal_targets": handle_get_steal_targets,
            "steal": handle_steal,
            "reaction": handle_reaction,
            "artist_guess": handle_artist_guess,
            "movie_guess": handle_movie_guess,
        }

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

    # ------------------------------------------------------------------
    # Rate limiting
    # ------------------------------------------------------------------

    def _check_connection_rate_limit(self, ip: str) -> bool:
        """Check if IP is within WebSocket connection rate limit."""
        now = time.time()
        cutoff = now - self.RATE_LIMIT_WINDOW
        if now - self._last_rate_sweep > 300:
            self._connection_rate_limits = {
                k: [t for t in v if t > cutoff]
                for k, v in self._connection_rate_limits.items()
                if any(t > cutoff for t in v)
            }
            self._last_rate_sweep = now
        times = [t for t in self._connection_rate_limits.get(ip, []) if t > cutoff]
        self._connection_rate_limits[ip] = times
        if len(times) >= self.RATE_LIMIT_CONNECTIONS:
            return False
        times.append(now)
        return True

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def handle(self, request: web.Request) -> web.StreamResponse:
        """
        Handle WebSocket connection.

        Args:
            request: aiohttp request

        Returns:
            WebSocket response

        """
        client_ip = request.remote or "unknown"
        if not self._check_connection_rate_limit(client_ip):
            return web.Response(status=429, text="Too many connections")

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

    # ------------------------------------------------------------------
    # Message dispatch
    # ------------------------------------------------------------------

    async def _handle_message(
        self, ws: web.WebSocketResponse, data: dict
    ) -> None:
        """
        Handle incoming WebSocket message.

        Args:
            ws: WebSocket connection
            data: Parsed message data

        """
        msg_type = data.get("type")
        game_state = get_game_state(self.hass)

        if not game_state or not game_state.game_id:
            await ws.send_json(
                {
                    "type": "error",
                    "code": ERR_GAME_NOT_STARTED,
                    "message": "No active game",
                }
            )
            return

        handler = self._message_handlers.get(msg_type)
        if handler:
            await handler(self, ws, data, game_state)
        else:
            _LOGGER.warning("Unknown message type: %s", msg_type)

    # ------------------------------------------------------------------
    # Broadcasting
    # ------------------------------------------------------------------

    async def broadcast(self, message: dict) -> None:
        """
        Broadcast message to all connected clients in parallel (Issue #41).

        Uses asyncio.gather() for parallel sends instead of sequential awaits.
        Issue #550: Also ensures admin spectator WS receives the broadcast
        even if it somehow dropped out of self.connections.

        Args:
            message: Message to broadcast

        """
        # Collect all target WebSockets
        targets = set(self.connections)

        # Issue #550: Ensure admin spectator WS is included
        game_state = get_game_state(self.hass)
        if game_state and game_state._admin_ws is not None:
            targets.add(game_state._admin_ws)

        if not targets:
            return

        # Build list of send tasks for all open connections
        tasks = []
        for ws in list(targets):
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
        # Cancel any pending broadcast — Issue #421: don't await cancelled task
        if self._broadcast_debounce_task and not self._broadcast_debounce_task.done():
            self._broadcast_debounce_task.cancel()

        async def delayed_broadcast() -> None:
            await asyncio.sleep(self._broadcast_debounce_delay)
            await self.broadcast_state()

        self._broadcast_debounce_task = asyncio.create_task(delayed_broadcast())

    async def broadcast_state(self) -> None:
        """Broadcast current game state to all connected players."""
        game_state = get_game_state(self.hass)
        if not game_state:
            _LOGGER.warning("broadcast_state: No game state found in hass.data")
            return

        state_msg = build_state_message(game_state)
        if state_msg:
            _LOGGER.debug(
                "broadcast_state: phase=%s, connections=%d",
                state_msg.get("phase"),
                len(self.connections),
            )
            await self.broadcast(state_msg)
        else:
            _LOGGER.debug(
                "broadcast_state: get_state() returned None (game not initialized yet)"
            )

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

    # ------------------------------------------------------------------
    # Disconnect handling
    # ------------------------------------------------------------------

    async def _handle_disconnect(self, ws: web.WebSocketResponse) -> None:
        """
        Handle WebSocket disconnection with grace period.

        Args:
            ws: Disconnected WebSocket

        """
        game_state = get_game_state(self.hass)
        if not game_state:
            return

        # Find player by WebSocket
        player_name = None
        player = None
        for name, p in list(game_state.players.items()):
            if p.ws == ws:
                player_name = name
                player = p
                player.connected = False
                break

        # Issue #477: Clear admin spectator WS if it disconnected
        if game_state._admin_ws is ws:
            game_state._admin_ws = None
            _LOGGER.info("Admin spectator WebSocket disconnected")

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
        # Story 11.3: Regular players persist indefinitely - no removal timeout
        # Player stays in game with connected=false, session allows reconnect
        # Score and stats preserved, counts toward MAX_PLAYERS (intentional)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

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
