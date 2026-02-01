"""HTTP views for Beatify admin interface."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView

from custom_components.beatify.const import (
    DIFFICULTY_DEFAULT,
    DIFFICULTY_EASY,
    DIFFICULTY_HARD,
    DIFFICULTY_NORMAL,
    DOMAIN,
    MEDIA_PLAYER_DOCS_URL,
    PLAYLIST_DOCS_URL,
    PROVIDER_DEFAULT,
    PROVIDER_SPOTIFY,
    PROVIDER_YOUTUBE_MUSIC,
    ROUND_DURATION_MAX,
    ROUND_DURATION_MIN,
)
from custom_components.beatify.game.state import GameState
from custom_components.beatify.services.media_player import (
    async_get_media_players,
    get_platform_capabilities,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Cache the version at module load time
_VERSION: str | None = None


def _get_version() -> str:
    """Get the version from manifest.json (cached)."""
    global _VERSION  # noqa: PLW0603
    if _VERSION is None:
        try:
            manifest_path = Path(__file__).parent.parent / "manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            _VERSION = manifest.get("version", "unknown")
        except Exception:  # noqa: BLE001
            _VERSION = "unknown"
    return _VERSION


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

        # Detect Music Assistant integration (not based on entity names)
        # Check if music_assistant integration is loaded via config entries
        has_music_assistant = any(
            entry.domain == "music_assistant" for entry in self.hass.config_entries.async_entries()
        )

        status = {
            "version": _get_version(),
            "media_players": media_players,
            "playlists": data.get("playlists", []),
            "playlist_dir": data.get("playlist_dir", ""),
            "playlist_docs_url": PLAYLIST_DOCS_URL,
            "media_player_docs_url": MEDIA_PLAYER_DOCS_URL,
            "active_game": active_game,
            "has_music_assistant": has_music_assistant,
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
        difficulty = body.get("difficulty", DIFFICULTY_DEFAULT)  # Story 14.1
        provider = body.get("provider", PROVIDER_DEFAULT)  # Story 17.2
        artist_challenge_enabled = body.get("artist_challenge_enabled", True)  # Story 20.7
        movie_quiz_enabled = body.get("movie_quiz_enabled", True)  # Issue #28

        # Validate difficulty (Story 14.1)
        valid_difficulties = (DIFFICULTY_EASY, DIFFICULTY_NORMAL, DIFFICULTY_HARD)
        if difficulty not in valid_difficulties:
            difficulty = DIFFICULTY_DEFAULT

        # Validate provider (Story 17.6: Spotify and YouTube Music supported)
        valid_providers = (PROVIDER_SPOTIFY, PROVIDER_YOUTUBE_MUSIC)
        if provider not in valid_providers:
            provider = PROVIDER_DEFAULT

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
                    {
                        "error": "INVALID_REQUEST",
                        "message": "Invalid round duration value",
                    },
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
                file_content = await self.hass.async_add_executor_job(_read_file, full_path)
                playlist_data = json.loads(file_content)

                for song in playlist_data.get("songs", []):
                    if "year" in song and "uri" in song:
                        songs.append(song)
                    else:
                        warnings.append(f"Invalid song in {playlist_path}: missing year or uri")

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

        # Get base URL for join URL construction (from request URL)
        base_url = self._get_base_url(request)

        # Initialize game state if needed
        if not game_state:
            game_state = GameState()
            self.hass.data[DOMAIN]["game"] = game_state
            # Connect stats service if available (Story 14.4)
            stats_service = self.hass.data.get(DOMAIN, {}).get("stats")
            if stats_service:
                game_state.set_stats_service(stats_service)

        # Detect platform and validate compatibility (resolves #38, #39)
        from homeassistant.helpers import entity_registry as er  # noqa: PLC0415

        ent_reg = er.async_get(self.hass)
        entity_entry = ent_reg.async_get(media_player)
        platform = entity_entry.platform if entity_entry else "unknown"

        # Validate platform is supported
        capabilities = get_platform_capabilities(platform)
        if not capabilities.get("supported"):
            return web.json_response(
                {
                    "error": "UNSUPPORTED_PLAYER",
                    "message": capabilities.get("reason", "This player type is not supported"),
                },
                status=400,
            )

        # Validate provider is supported by platform
        if provider == "apple_music" and not capabilities.get("apple_music"):
            return web.json_response(
                {
                    "error": "PROVIDER_NOT_SUPPORTED",
                    "message": "Apple Music is not supported on this speaker. Use Music Assistant.",
                },
                status=400,
            )

        if provider == PROVIDER_YOUTUBE_MUSIC and not capabilities.get("youtube_music"):
            return web.json_response(
                {
                    "error": "PROVIDER_NOT_SUPPORTED",
                    "message": "YouTube Music is not supported on this speaker. Use Music Assistant.",
                },
                status=400,
            )

        # Build create_game kwargs with optional round_duration (Story 13.1), difficulty (Story 14.1), provider (Story 17.2), platform, and artist_challenge_enabled (Story 20.7)
        create_kwargs: dict[str, Any] = {
            "playlists": playlist_paths,
            "songs": songs,
            "media_player": media_player,
            "base_url": base_url,
            "difficulty": difficulty,
            "provider": provider,
            "platform": platform,
            "artist_challenge_enabled": artist_challenge_enabled,  # Story 20.7
            "movie_quiz_enabled": movie_quiz_enabled,  # Issue #28
        }
        if round_duration is not None:
            create_kwargs["round_duration"] = round_duration

        result = game_state.create_game(**create_kwargs)
        result["warnings"] = warnings

        # Record game start time for analytics (Story 19.1)
        stats_service = data.get("stats")
        if stats_service:
            stats_service.record_game_start()

        # Set game language (Story 12.4, 16.3)
        if language in ("en", "de", "es"):
            game_state.language = language

        # Broadcast to WebSocket clients
        ws_handler = data.get("ws_handler")
        if ws_handler:
            state = game_state.get_state()
            if state:
                await ws_handler.broadcast({"type": "state", **state})

        return web.json_response(result)

    def _get_base_url(self, request: web.Request) -> str:
        """Get base URL for join URL construction from request."""
        # Use the request URL - this is what the user actually used to access the app
        url = request.url
        return f"{url.scheme}://{url.host}:{url.port}" if url.port else f"{url.scheme}://{url.host}"


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
            await ws_handler.broadcast({"type": "state", "phase": "END", "game_id": None})

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
            # Set metadata update callback for fast transitions (Issue #42)
            game_state.set_metadata_update_callback(ws_handler.broadcast_metadata_update)

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
            return web.json_response(
                {
                    "exists": False,
                    "phase": None,
                    "can_join": False,
                }
            )

        # Get game state with safe access
        game_state = self.hass.data.get(DOMAIN, {}).get("game")

        # No game state or different game ID
        if not game_state:
            return web.json_response(
                {
                    "exists": False,
                    "phase": None,
                    "can_join": False,
                }
            )

        if game_state.game_id != game_id:
            return web.json_response(
                {
                    "exists": False,
                    "phase": None,
                    "can_join": False,
                }
            )

        # Game exists - return status
        phase = game_state.phase.value
        # Late join supported during LOBBY, PLAYING, and REVEAL (Story 16.5)
        can_join = phase in ("LOBBY", "PLAYING", "REVEAL")

        return web.json_response(
            {
                "exists": True,
                "phase": phase,
                "can_join": can_join,
            }
        )


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


class StatsView(HomeAssistantView):
    """API endpoint for game statistics (Story 14.4)."""

    url = "/beatify/api/stats"
    name = "beatify:api:stats"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:  # noqa: ARG002
        """Get game statistics summary and history."""
        stats_service = self.hass.data.get(DOMAIN, {}).get("stats")

        if not stats_service:
            return web.json_response(
                {
                    "summary": {
                        "games_played": 0,
                        "highest_avg_score": 0.0,
                        "all_time_avg": 0.0,
                    },
                    "history": [],
                }
            )

        summary = await stats_service.get_summary()
        history = await stats_service.get_history(limit=10)

        return web.json_response(
            {
                "summary": summary,
                "history": history,
            }
        )


class AnalyticsView(HomeAssistantView):
    """API endpoint for analytics dashboard data (Story 19.2)."""

    url = "/beatify/api/analytics"
    name = "beatify:api:analytics"
    requires_auth = False

    # Valid period values
    VALID_PERIODS = ("7d", "30d", "90d", "all")
    # Rate limiting: max requests per IP per minute
    RATE_LIMIT_REQUESTS = 30
    RATE_LIMIT_WINDOW = 60  # seconds

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass
        self._cache: dict | None = None
        self._cache_time: float = 0
        self._cache_ttl: float = 60.0  # 60 second cache
        self._rate_limits: dict[str, list[float]] = {}  # IP -> list of request times

    def _check_rate_limit(self, ip: str) -> bool:
        """
        Check if IP is within rate limit.

        Args:
            ip: Client IP address

        Returns:
            True if allowed, False if rate limited

        """
        import time  # noqa: PLC0415

        now = time.time()
        cutoff = now - self.RATE_LIMIT_WINDOW

        # Get request times for this IP, filter old entries
        times = [t for t in self._rate_limits.get(ip, []) if t > cutoff]
        self._rate_limits[ip] = times

        if len(times) >= self.RATE_LIMIT_REQUESTS:
            return False

        times.append(now)
        return True

    async def get(self, request: web.Request) -> web.Response:
        """Get analytics metrics with caching and rate limiting."""
        import time  # noqa: PLC0415

        # Rate limiting check
        client_ip = request.remote or "unknown"
        if not self._check_rate_limit(client_ip):
            return web.json_response(
                {"error": "RATE_LIMITED", "message": "Too many requests"},
                status=429,
            )

        # Validate period parameter
        period = request.query.get("period", "30d")
        if period not in self.VALID_PERIODS:
            period = "30d"  # Fallback to default

        analytics = self.hass.data.get(DOMAIN, {}).get("analytics")

        if not analytics:
            return web.json_response(
                {
                    "period": period,
                    "total_games": 0,
                    "avg_players_per_game": 0,
                    "avg_score": 0,
                    "error_rate": 0,
                    "trends": {"games": 0, "players": 0, "score": 0, "errors": 0},
                    "generated_at": int(time.time()),
                }
            )

        # Check cache (invalidate if period changed or TTL expired)
        now = time.time()
        if (
            self._cache
            and self._cache.get("period") == period
            and (now - self._cache_time) < self._cache_ttl
        ):
            return web.json_response(self._cache)

        # Compute fresh metrics
        data = analytics.compute_metrics(period)
        self._cache = data
        self._cache_time = now

        return web.json_response(data)


class AnalyticsPageView(HomeAssistantView):
    """Serve the analytics dashboard page (Story 19.2)."""

    url = "/beatify/analytics"
    name = "beatify:analytics"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the view."""
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:  # noqa: ARG002
        """Serve analytics page."""
        www_path = Path(__file__).parent.parent / "www" / "analytics.html"
        if www_path.exists():
            content = await self.hass.async_add_executor_job(_read_file, www_path)
            return web.Response(text=content, content_type="text/html")
        return web.Response(text="Analytics page not found", status=404)


class SongStatsView(HomeAssistantView):
    """API endpoint for song statistics (Story 19.7)."""

    url = "/beatify/api/analytics/songs"
    name = "beatify:api:analytics:songs"
    requires_auth = False

    # Cache settings
    CACHE_TTL = 60.0  # 60 second cache

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass
        self._cache: dict | None = None
        self._cache_time: float = 0
        self._cache_playlist: str | None = None

    async def get(self, request: web.Request) -> web.Response:
        """Get song statistics with optional playlist filter (Story 19.7 AC3)."""
        import time  # noqa: PLC0415

        # Get optional playlist filter
        playlist_filter = request.query.get("playlist")

        stats_service = self.hass.data.get(DOMAIN, {}).get("stats")

        if not stats_service:
            return web.json_response(
                {
                    "most_played": None,
                    "hardest": None,
                    "easiest": None,
                    "by_playlist": [],
                }
            )

        # Check cache (invalidate if playlist changed or TTL expired)
        now = time.time()
        if (
            self._cache
            and self._cache_playlist == playlist_filter
            and (now - self._cache_time) < self.CACHE_TTL
        ):
            return web.json_response(self._cache)

        # Compute fresh stats
        data = stats_service.compute_song_stats(playlist_filter)
        self._cache = data
        self._cache_time = now
        self._cache_playlist = playlist_filter

        return web.json_response(data)


class PlaylistRequestsView(HomeAssistantView):
    """API for managing playlist requests (Story 44).

    Stores requests in a JSON file on the HA server so they persist
    across browser sessions and devices.
    """

    url = "/beatify/api/playlist-requests"
    name = "beatify:api:playlist-requests"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass
        self._storage_path = Path(hass.config.path("beatify/playlist_requests.json"))

    def _load_requests(self) -> dict:
        """Load requests from storage file."""
        if self._storage_path.exists():
            try:
                return json.loads(self._storage_path.read_text(encoding="utf-8"))
            except Exception as e:  # noqa: BLE001
                _LOGGER.error("Failed to load playlist requests: %s", e)
        return {"requests": [], "last_poll": None}

    def _save_requests(self, data: dict) -> bool:
        """Save requests to storage file."""
        try:
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)
            self._storage_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
            return True
        except Exception as e:  # noqa: BLE001
            _LOGGER.error("Failed to save playlist requests: %s", e)
            return False

    async def get(self, request: web.Request) -> web.Response:  # noqa: ARG002
        """Get all playlist requests."""
        data = await self.hass.async_add_executor_job(self._load_requests)
        return web.json_response(data)

    async def post(self, request: web.Request) -> web.Response:
        """Save playlist requests (replaces all data)."""
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return web.json_response(
                {"error": "INVALID_REQUEST", "message": "Invalid JSON"},
                status=400,
            )

        # Validate data structure
        if not isinstance(body.get("requests"), list):
            return web.json_response(
                {"error": "INVALID_REQUEST", "message": "Missing or invalid requests array"},
                status=400,
            )

        # Build storage object
        data = {
            "requests": body.get("requests", []),
            "last_poll": body.get("last_poll"),
        }

        # Save to file
        success = await self.hass.async_add_executor_job(self._save_requests, data)
        if not success:
            return web.json_response(
                {"error": "SAVE_FAILED", "message": "Failed to save request"},
                status=500,
            )

        return web.json_response({"success": True, "requests": data["requests"]})
