"""WebSocket handler for Beatify game connections."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from aiohttp import WSCloseCode, WSMsgType, web

from custom_components.beatify.const import (
    ERR_GAME_NOT_STARTED,
    LOBBY_DISCONNECT_GRACE_PERIOD,
    MAX_GUESS_LEN,
)
from custom_components.beatify.server.serializers import (
    REDACTED_PLACEHOLDER,
    build_state_message,
    get_game_state,
    redact_state_for_player,
)
from custom_components.beatify.server.ws_handlers import (
    handle_admin,
    handle_admin_connect,
    handle_artist_guess,
    handle_get_state,
    handle_get_steal_targets,
    handle_join,
    handle_leave,
    handle_movie_guess,
    handle_ping,
    handle_player_onboarded,
    handle_reaction,
    handle_reconnect,
    handle_report_data,
    handle_round_timeout,
    handle_steal,
    handle_submit,
    handle_title_artist_guess,
    handle_title_artist_override,
    handle_title_artist_vote,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from custom_components.beatify.analytics import AnalyticsStorage

_LOGGER = logging.getLogger(__name__)

# Free-text guess fields that must be length-capped at the ingest boundary
# (#1581). aiohttp accepts WS frames up to 4 MB; an unbounded guess would feed a
# multi-megabyte string into the O(n*m) Levenshtein DP and freeze the HA event
# loop. Truncating here — before the message is dispatched, classified, stored,
# or re-broadcast — keeps any oversized payload from flowing through the backend.
_GUESS_TEXT_FIELDS = ("title", "artist", "movie")


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
            "title_artist_vote": handle_title_artist_vote,
            "title_artist_override": handle_title_artist_override,
            "title_artist_guess": handle_title_artist_guess,
            "player_onboarded": handle_player_onboarded,
            "report_data": handle_report_data,
            "round_timeout": handle_round_timeout,
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
        # Stash the request's UA + remote so ws_handlers._is_ha_authenticated
        # can re-evaluate the HA Android Companion trust signature on the
        # admin_connect message. Scoped per-connection (#1131).
        ua_at_upgrade = request.headers.get("User-Agent")
        ws.beatify_request_meta = {
            "ua": ua_at_upgrade,
            "remote": request.remote,
        }
        await ws.prepare(request)

        self.connections.add(ws)
        # rc11 diagnostic (#1131 follow-up, player-join "Reconnecting" issue):
        # the HTTP bypass works (admin loads) but the WS player-join fails.
        # Log every WS upgrade with the *exact* UA + remote the server saw at
        # upgrade time so we can confirm whether the WS path sees the same
        # Companion signature the HTTP path does, or whether the upgrade
        # arrives with a different UA / through a different proxy hop.
        _LOGGER.info(
            "[WS-Debug] upgrade path=%s remote=%s ua=%r total=%d",
            request.path,
            request.remote,
            (ua_at_upgrade[:200] if isinstance(ua_at_upgrade, str) else ua_at_upgrade),
            len(self.connections),
        )

        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        parsed = msg.json()
                        _LOGGER.info(
                            "[WS-Debug] recv type=%s keys=%s",
                            parsed.get("type") if isinstance(parsed, dict) else "?",
                            list(parsed.keys()) if isinstance(parsed, dict) else None,
                        )
                        await self._handle_message(ws, parsed)
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
                else:
                    _LOGGER.info(
                        "[WS-Debug] non-text msg type=%s",
                        msg.type,
                    )

        finally:
            self.connections.discard(ws)
            await self._handle_disconnect(ws)
            _LOGGER.info(
                "[WS-Debug] disconnect path=%s remote=%s total=%d ws_closed=%s close_code=%s",
                request.path,
                request.remote,
                len(self.connections),
                ws.closed,
                ws.close_code,
            )

        return ws

    # ------------------------------------------------------------------
    # Message dispatch
    # ------------------------------------------------------------------

    async def _handle_message(self, ws: web.WebSocketResponse, data: dict) -> None:
        """
        Handle incoming WebSocket message.

        Args:
            ws: WebSocket connection
            data: Parsed message data

        """
        msg_type = data.get("type")

        # Truncate free-text guesses at the ingest boundary (#1581), before the
        # message is dispatched to a handler, classified, stored, or rebroadcast.
        for field in _GUESS_TEXT_FIELDS:
            value = data.get(field)
            if isinstance(value, str) and len(value) > MAX_GUESS_LEN:
                data[field] = value[:MAX_GUESS_LEN]

        game_state = get_game_state(self.hass)

        # Heartbeat ping: answer before the active-game guard so the client
        # heartbeat keeps working between games and on the end screen (#967).
        if msg_type == "ping":
            await handle_ping(self, ws, data, game_state)
            return

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

        # #1366: the broadcast payload carries the round's answers (admin_song
        # year; song.artist/title in title_artist_mode) for the spectator admin
        # / TV. Sent unfiltered, any player could read them off the WebSocket
        # before guessing. Redact per-recipient: only the spectator admin WS
        # gets the answers; every player connection gets a redacted copy.
        player_message = self._redact_for_player(message, game_state)

        admin_ws = game_state._admin_ws if game_state else None

        # Build list of send tasks for all open connections
        tasks = []
        for ws in list(targets):
            if not ws.closed:
                payload = message if ws is admin_ws else player_message
                tasks.append(self._safe_send(ws, payload))

        # Execute all sends in parallel
        if tasks:
            await asyncio.gather(*tasks)

    @staticmethod
    def _redact_for_player(message: dict, game_state) -> dict:  # noqa: ANN001
        """Return the player-safe variant of an answer-bearing broadcast (#1366).

        Returns ``message`` unchanged for payloads that carry no answers.
        ``metadata_update`` frames (sent mid-PLAYING when song metadata lands)
        have no ``phase`` / ``title_artist_mode`` of their own, so the
        title_artist context is taken from ``game_state``.
        """
        msg_type = message.get("type")
        if msg_type == "state":
            return redact_state_for_player(message)
        if msg_type == "metadata_update" and game_state is not None:
            from custom_components.beatify.game.state import (  # noqa: PLC0415
                GamePhase,
            )

            if (
                game_state.title_artist_mode
                and game_state.phase == GamePhase.PLAYING
                and isinstance(message.get("song"), dict)
            ):
                song = dict(message["song"])
                song["artist"] = REDACTED_PLACEHOLDER
                song["title"] = REDACTED_PLACEHOLDER
                return {**message, "song": song}
        return message

    async def _safe_send(self, ws: web.WebSocketResponse, message: dict) -> None:
        """
        Send message to a single WebSocket, catching errors.

        Args:
            ws: WebSocket connection
            message: Message to send

        """
        try:
            await ws.send_json(message)
        except (ConnectionError, RuntimeError) as err:
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

        # #928: a mid-round disconnect can itself complete the round. If
        # everyone still active has already submitted, the departing player
        # was the last thing the room was waiting on — advance to REVEAL now
        # instead of stalling on "Waiting for others" until the timer.
        try:
            await game_state.trigger_early_reveal_if_complete()
        except Exception:  # noqa: BLE001
            _LOGGER.warning("Early-reveal check after disconnect failed")

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
        # Cancel admin disconnect task
        if self._admin_disconnect_task and not self._admin_disconnect_task.done():
            self._admin_disconnect_task.cancel()
        self._admin_disconnect_task = None

        _LOGGER.debug("Cleaned up all pending game tasks")

    async def async_close_all(self) -> None:
        """Cancel pending tasks and close every open WebSocket on unload (#1391).

        ``async_unload_entry`` previously left this handler's tasks
        (``_admin_disconnect_task``, ``_broadcast_debounce_task``) running and
        every player/admin WebSocket open, pinning the orphaned handler +
        GameState after the integration was torn down. This cancels all of them
        and sends each client a going-away close so they reconnect cleanly to a
        fresh handler after reload.
        """
        # Reuse the existing pending-task cleanup (_admin_disconnect_task),
        # then additionally cancel the debounce task that cleanup_game_tasks
        # does not cover.
        await self.cleanup_game_tasks()
        if self._broadcast_debounce_task and not self._broadcast_debounce_task.done():
            self._broadcast_debounce_task.cancel()
        self._broadcast_debounce_task = None

        # Close every open connection with a going-away code. Snapshot the set
        # first: ws.close() resolves the handle() finally-block which discards
        # from self.connections, mutating it mid-iteration otherwise.
        for ws in list(self.connections):
            if not ws.closed:
                try:
                    await ws.close(
                        code=WSCloseCode.GOING_AWAY, message=b"beatify-unload"
                    )
                except Exception:  # noqa: BLE001 — best-effort teardown
                    _LOGGER.debug(
                        "Error closing WebSocket during unload", exc_info=True
                    )
        self.connections.clear()

        _LOGGER.debug("Closed all WebSocket connections on unload")
