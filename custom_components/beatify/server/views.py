"""HTTP views for Beatify admin interface."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from custom_components.beatify.const import (
    DOMAIN,
    MEDIA_PLAYER_DOCS_URL,
    PLAYLIST_DOCS_URL,
    ROUND_DURATION_MAX,
    ROUND_DURATION_MIN,
)
from custom_components.beatify.game.state import GameState
from custom_components.beatify.services.media_player import async_get_media_players

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


def _read_file(path: Path) -> str:
    """Read file contents (runs in executor)."""
    return path.read_text(encoding="utf-8")


class AdminView(HomeAssistantView):
    """Serve the admin page."""

    url = "/beatify/admin"
    name = "beatify:admin"
    requires_auth = False  # Frictionless access per PRD

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the admin view."""
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:  # noqa: ARG002
        """Serve the admin HTML page."""
        html_path = Path(__file__).parent.parent / "www" / "admin.html"

        if not html_path.exists():
            _LOGGER.error("Admin page not found: %s", html_path)
            return web.Response(text="Admin page not found", status=500)

        html_content = await self.hass.async_add_executor_job(_read_file, html_path)
        return web.Response(text=html_content, content_type="text/html")


class LauncherView(HomeAssistantView):
    """Serve the launcher page for HA sidebar (opens admin in new tab)."""

    url = "/beatify/launcher"
    name = "beatify:launcher"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the launcher view."""
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:  # noqa: ARG002
        """Serve the launcher HTML page."""
        html_path = Path(__file__).parent.parent / "www" / "launcher.html"

        if not html_path.exists():
            _LOGGER.error("Launcher page not found: %s", html_path)
            return web.Response(text="Launcher page not found", status=500)

        html_content = await self.hass.async_add_executor_job(_read_file, html_path)
        return web.Response(text=html_content, content_type="text/html")


class StatusView(HomeAssistantView):
    """API endpoint for admin page status."""

    url = "/beatify/api/status"
    name = "beatify:api:status"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the status view."""
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:  # noqa: ARG002
        """Return current status as JSON."""
        data = self.hass.data.get(DOMAIN, {})

        # Check for active game
        game_state = data.get("game")
        active_game = None
        if game_state and game_state.game_id:
            active_game = game_state.get_state()

        # Fetch media players fresh (not cached) - Story 8-2
        media_players = await async_get_media_players(self.hass)

        status = {
            "media_players": media_players,
            "playlists": data.get("playlists", []),
            "playlist_dir": data.get("playlist_dir", ""),
            "playlist_docs_url": PLAYLIST_DOCS_URL,
            "media_player_docs_url": MEDIA_PLAYER_DOCS_URL,
            "active_game": active_game,
        }

        return web.json_response(status)


class StartGameView(HomeAssistantView):
    """Handle start game requests."""

    url = "/beatify/api/start-game"
    name = "beatify:api:start-game"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass

    async def post(self, request: web.Request) -> web.Response:  # noqa: PLR0911, PLR0912
        """Start a new game."""
        data = self.hass.data.get(DOMAIN, {})
        game_state = data.get("game")

        # Check for existing game
        if game_state and game_state.game_id:
            return web.json_response(
                {"error": "GAME_ALREADY_STARTED", "message": "End current game first"},
                status=409,
            )

        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return web.json_response(
                {"error": "INVALID_REQUEST", "message": "Invalid JSON"},
                status=400,
            )

        playlist_paths = body.get("playlists", [])
        media_player = body.get("media_player")
        language = body.get("language", "en")
        round_duration = body.get("round_duration")  # Story 13.1

        # Validate round_duration if provided (Story 13.1)
        if round_duration is not None:
            try:
                round_duration = int(round_duration)
                if not (ROUND_DURATION_MIN <= round_duration <= ROUND_DURATION_MAX):
                    return web.json_response(
                        {
                            "error": "INVALID_REQUEST",
                            "message": f"Round duration must be between {ROUND_DURATION_MIN} and {ROUND_DURATION_MAX} seconds",
                        },
                        status=400,
                    )
            except (ValueError, TypeError):
                return web.json_response(
                    {"error": "INVALID_REQUEST", "message": "Invalid round duration value"},
                    status=400,
                )

        if not playlist_paths:
            return web.json_response(
                {"error": "INVALID_REQUEST", "message": "No playlists selected"},
                status=400,
            )

        if not media_player:
            return web.json_response(
                {"error": "INVALID_REQUEST", "message": "No media player selected"},
                status=400,
            )

        # Validate media player entity exists
        media_player_state = self.hass.states.get(media_player)
        if not media_player_state:
            return web.json_response(
                {"error": "INVALID_REQUEST", "message": "Media player not found"},
                status=400,
            )
        if media_player_state.state == "unavailable":
            return web.json_response(
                {"error": "INVALID_REQUEST", "message": "Media player is unavailable"},
                status=400,
            )

        # Load and validate playlists
        songs: list[dict[str, Any]] = []
        warnings: list[str] = []
        playlist_dir = Path(self.hass.config.path("beatify/playlists"))

        for playlist_path in playlist_paths:
            try:
                full_path = playlist_dir / playlist_path
                # Security: Prevent path traversal attacks
                try:
                    full_path = full_path.resolve()
                    if not full_path.is_relative_to(playlist_dir.resolve()):
                        warnings.append(f"Invalid playlist path: {playlist_path}")
                        continue
                except ValueError:
                    warnings.append(f"Invalid playlist path: {playlist_path}")
                    continue

                if not full_path.exists():
                    warnings.append(f"Playlist not found: {playlist_path}")
                    continue

                # Read file in executor to avoid blocking event loop
                file_content = await self.hass.async_add_executor_job(
                    _read_file, full_path
                )
                playlist_data = json.loads(file_content)

                for song in playlist_data.get("songs", []):
                    if "year" in song and "uri" in song:
                        songs.append(song)
                    else:
                        warnings.append(
                            f"Invalid song in {playlist_path}: missing year or uri"
                        )

            except Exception as err:  # noqa: BLE001
                warnings.append(f"Failed to load {playlist_path}: {err}")

        if not songs:
            return web.json_response(
                {
                    "error": "INVALID_REQUEST",
                    "message": "No valid songs found in selected playlists",
                },
                status=400,
            )

        # Get base URL for join URL construction
        base_url = self._get_base_url()

        # Initialize game state if needed
        if not game_state:
            game_state = GameState()
            self.hass.data[DOMAIN]["game"] = game_state

        # Build create_game kwargs with optional round_duration (Story 13.1)
        create_kwargs: dict[str, Any] = {
            "playlists": playlist_paths,
            "songs": songs,
            "media_player": media_player,
            "base_url": base_url,
        }
        if round_duration is not None:
            create_kwargs["round_duration"] = round_duration

        result = game_state.create_game(**create_kwargs)
        result["warnings"] = warnings

        # Set game language (Story 12.4)
        if language in ("en", "de"):
            game_state.language = language

        # Broadcast to WebSocket clients
        ws_handler = data.get("ws_handler")
        if ws_handler:
            state = game_state.get_state()
            if state:
                await ws_handler.broadcast({"type": "state", **state})

        return web.json_response(result)

    def _get_base_url(self) -> str:
        """Get HA base URL for join URL construction."""
        if self.hass.config.internal_url:
            return self.hass.config.internal_url.rstrip("/")
        if self.hass.config.external_url:
            return self.hass.config.external_url.rstrip("/")
        return "http://homeassistant.local:8123"


class EndGameView(HomeAssistantView):
    """Handle end game requests."""

    url = "/beatify/api/end-game"
    name = "beatify:api:end-game"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass

    async def post(self, request: web.Request) -> web.Response:  # noqa: ARG002
        """End the current game."""
        data = self.hass.data.get(DOMAIN, {})
        game_state = data.get("game")

        if not game_state or not game_state.game_id:
            return web.json_response(
                {"error": "GAME_NOT_STARTED", "message": "No active game"},
                status=404,
            )

        game_state.end_game()

        # Broadcast game ended to WebSocket clients
        ws_handler = data.get("ws_handler")
        if ws_handler:
            await ws_handler.broadcast(
                {"type": "state", "phase": "END", "game_id": None}
            )

        return web.json_response({"success": True})


class StartGameplayView(HomeAssistantView):
    """Handle start gameplay requests (transition LOBBY -> PLAYING)."""

    url = "/beatify/api/start-gameplay"
    name = "beatify:api:start-gameplay"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass

    async def post(self, request: web.Request) -> web.Response:  # noqa: ARG002
        """Start gameplay from lobby."""
        from custom_components.beatify.game.state import GamePhase  # noqa: PLC0415

        data = self.hass.data.get(DOMAIN, {})
        game_state = data.get("game")

        if not game_state or not game_state.game_id:
            return web.json_response(
                {"error": "GAME_NOT_STARTED", "message": "No active game"},
                status=404,
            )

        if game_state.phase != GamePhase.LOBBY:
            return web.json_response(
                {"error": "INVALID_PHASE", "message": "Game already started"},
                status=409,
            )

        # Set round end callback for broadcasting
        ws_handler = data.get("ws_handler")
        if ws_handler:
            game_state.set_round_end_callback(ws_handler.broadcast_state)

        # Start the first round
        success = await game_state.start_round(self.hass)
        if not success:
            return web.json_response(
                {"error": "START_FAILED", "message": "Failed to start - no songs"},
                status=500,
            )

        # Broadcast state to all connected players
        if ws_handler:
            await ws_handler.broadcast_state()

        return web.json_response({"success": True, "phase": game_state.phase.value})


class PlayerView(HomeAssistantView):
    """Serve the player page."""

    url = "/beatify/play"
    name = "beatify:play"
    requires_auth = False  # Frictionless access per PRD

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the player view."""
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:  # noqa: ARG002
        """Serve the player HTML page."""
        html_path = Path(__file__).parent.parent / "www" / "player.html"

        if not html_path.exists():
            _LOGGER.error("Player page not found: %s", html_path)
            return web.Response(text="Player page not found", status=500)

        html_content = await self.hass.async_add_executor_job(_read_file, html_path)
        return web.Response(text=html_content, content_type="text/html")


class GameStatusView(HomeAssistantView):
    """Check game status for player page."""

    url = "/beatify/api/game-status"
    name = "beatify:api:game-status"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:
        """Get game status."""
        game_id = request.query.get("game")

        # No game ID provided
        if not game_id:
            return web.json_response({
                "exists": False,
                "phase": None,
                "can_join": False,
            })

        # Get game state with safe access
        game_state = self.hass.data.get(DOMAIN, {}).get("game")

        # No game state or different game ID
        if not game_state:
            return web.json_response({
                "exists": False,
                "phase": None,
                "can_join": False,
            })

        if game_state.game_id != game_id:
            return web.json_response({
                "exists": False,
                "phase": None,
                "can_join": False,
            })

        # Game exists - return status
        phase = game_state.phase.value
        can_join = phase in ("LOBBY", "PLAYING")  # Late join supported

        return web.json_response({
            "exists": True,
            "phase": phase,
            "can_join": can_join,
        })


class DashboardView(HomeAssistantView):
    """Serve the spectator dashboard page."""

    url = "/beatify/dashboard"
    name = "beatify:dashboard"
    requires_auth = False  # Frictionless access per PRD

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the dashboard view."""
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:  # noqa: ARG002
        """Serve the dashboard HTML page."""
        html_path = Path(__file__).parent.parent / "www" / "dashboard.html"

        if not html_path.exists():
            _LOGGER.error("Dashboard page not found: %s", html_path)
            return web.Response(text="Dashboard page not found", status=500)

        html_content = await self.hass.async_add_executor_job(_read_file, html_path)
        return web.Response(text=html_content, content_type="text/html")
