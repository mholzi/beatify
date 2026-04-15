"""HTTP views for Beatify admin interface."""

from __future__ import annotations

import hmac
import json
import logging
import time
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
    PROVIDER_DEFAULT,
    PROVIDER_DEEZER,
    PROVIDER_SPOTIFY,
    PROVIDER_TIDAL,
    PROVIDER_YOUTUBE_MUSIC,
    ROUND_DURATION_MAX,
    ROUND_DURATION_MIN,
)
from homeassistant.helpers import entity_registry as er

from custom_components.beatify.game.playlist import async_discover_playlists
from custom_components.beatify.game.state import GamePhase, GameState
from custom_components.beatify.server.serializers import (
    build_game_status_response,
    build_state_message,
    build_status_response,
    get_game_state,
)
from custom_components.beatify.services.lights import PartyLightsService
from custom_components.beatify.services.media_player import (
    async_get_media_players,
    get_platform_capabilities,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# Version is set here and bumped alongside manifest.json in release commits.
# We avoid reading manifest.json at runtime because HA imports custom components
# inside the event loop, and any file I/O (even at module level) triggers
# blocking call warnings in HA 2026.2+.
_VERSION = "3.0.3"


def _get_version() -> str:
    """Get the integration version."""
    return _VERSION


def _read_file(path: Path) -> str:
    """Read file contents (runs in executor)."""
    return path.read_text(encoding="utf-8")


_html_cache: dict[str, str] = {}


async def _get_html(hass: HomeAssistant, path: Path) -> str | None:
    """Read HTML file with in-memory caching."""
    key = str(path)
    if key in _html_cache:
        return _html_cache[key]
    if not path.exists():
        return None
    content = await hass.async_add_executor_job(_read_file, path)
    _html_cache[key] = content
    return content


def _verify_admin_token(request: web.Request, game_state: Any) -> bool:
    """Verify admin token from Authorization header or query param (#386).

    Accepts:
    - Header: Authorization: Bearer <token>
    - Query: ?admin_token=<token>
    """
    if not game_state or not game_state.admin_token:
        return False
    token = None
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
    if not token:
        token = request.query.get("admin_token")
    if not token:
        return False
    return hmac.compare_digest(token, game_state.admin_token)


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
        html_content = await _get_html(self.hass, html_path)
        if html_content is None:
            _LOGGER.error("Admin page not found: %s", html_path)
            return web.Response(text="Admin page not found", status=500)
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
        html_content = await _get_html(self.hass, html_path)
        if html_content is None:
            _LOGGER.error("Launcher page not found: %s", html_path)
            return web.Response(text="Launcher page not found", status=500)
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
        # Fetch media players fresh (not cached) - Story 8-2
        media_players = await async_get_media_players(self.hass)

        # Fetch playlists fresh (not cached) - Issue #135
        playlists = await async_discover_playlists(self.hass)
        self.hass.data.setdefault(DOMAIN, {})["playlists"] = playlists

        status = build_status_response(
            self.hass,
            version=_get_version(),
            media_players=media_players,
            playlists=playlists,
        )

        return web.json_response(status)


class LightsView(HomeAssistantView):
    """API endpoint for available light entities (#331)."""

    url = "/beatify/api/lights"
    name = "beatify:api:lights"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the lights view."""
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:  # noqa: ARG002
        """Return available light entities with capabilities."""
        lights = []
        for state in self.hass.states.async_all("light"):
            color_modes = state.attributes.get("supported_color_modes", [])
            if any(m in color_modes for m in ("rgb", "rgbw", "rgbww", "hs", "xy")):
                capability = "rgb"
            elif "color_temp" in color_modes:
                capability = "ct"
            elif "brightness" in color_modes:
                capability = "dim"
            else:
                capability = "onoff"

            lights.append(
                {
                    "entity_id": state.entity_id,
                    "friendly_name": state.attributes.get(
                        "friendly_name", state.entity_id
                    ),
                    "state": state.state,
                    "capability": capability,
                    "supported_color_modes": color_modes,
                }
            )

        return web.json_response({"lights": lights})


class PreviewLightsView(HomeAssistantView):
    """Trigger a party lights preview for selected entities (#408)."""

    url = "/beatify/api/preview-lights"
    name = "beatify:api:preview-lights"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass

    async def post(self, request: web.Request) -> web.Response:
        """Run a ~5s party lights preview on the given entity_ids."""
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return web.json_response({"error": "Invalid JSON"}, status=400)

        entity_ids = body.get("entity_ids", [])
        if not entity_ids:
            return web.json_response({"error": "No entity_ids provided"}, status=400)

        game_state = self.hass.data.get(DOMAIN, {}).get("game")
        if game_state and game_state.game_id:
            return web.json_response(
                {"error": "Cannot preview during active game"}, status=409
            )

        intensity = body.get("intensity", "party")

        try:
            preview = PartyLightsService(self.hass)
            await preview.start(entity_ids, intensity)
            await preview.celebrate()
            await preview.stop()
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Party lights preview failed")
            return web.json_response({"error": "Preview failed"}, status=500)

        return web.json_response({"ok": True})


class TtsTestView(HomeAssistantView):
    """Send a test TTS announcement to verify setup."""

    url = "/beatify/api/tts-test"
    name = "beatify:api:tts-test"
    requires_auth = False

    MAX_TTS_MESSAGE_LENGTH = 500

    RATE_LIMIT_REQUESTS = 5
    RATE_LIMIT_WINDOW = 60  # seconds

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass
        self._rate_limits: dict[str, list[float]] = {}
        self._last_sweep: float = 0.0

    def _check_rate_limit(self, ip: str) -> bool:
        """Check if IP is within rate limit."""
        now = time.time()
        cutoff = now - self.RATE_LIMIT_WINDOW
        if now - self._last_sweep > 300:
            self._rate_limits = {
                k: [t for t in v if t > cutoff]
                for k, v in self._rate_limits.items()
                if any(t > cutoff for t in v)
            }
            self._last_sweep = now
        times = [t for t in self._rate_limits.get(ip, []) if t > cutoff]
        self._rate_limits[ip] = times
        if len(times) >= self.RATE_LIMIT_REQUESTS:
            return False
        times.append(now)
        return True

    async def post(self, request: web.Request) -> web.Response:
        """Speak a test message via TTS."""
        client_ip = request.remote or "unknown"
        if not self._check_rate_limit(client_ip):
            return web.json_response(
                {"error": "RATE_LIMITED", "message": "Too many requests"},
                status=429,
            )
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return web.json_response({"error": "Invalid JSON"}, status=400)

        entity_id = body.get("entity_id", "")
        message = body.get("message", "")[:self.MAX_TTS_MESSAGE_LENGTH]
        if not entity_id or not message:
            return web.json_response(
                {"error": "entity_id and message required"}, status=400
            )

        state = self.hass.states.get(entity_id)
        if not state or state.domain not in ("media_player", "tts"):
            return web.json_response(
                {"error": "Invalid or unsupported entity_id"}, status=400
            )

        try:
            await self.hass.services.async_call(
                "tts",
                "speak",
                {"entity_id": entity_id, "message": message},
                blocking=False,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception("TTS test failed for entity: %s", entity_id)
            return web.json_response({"error": "TTS call failed"}, status=500)

        return web.json_response({"ok": True})


class StartGameView(HomeAssistantView):
    """Handle start game requests."""

    url = "/beatify/api/start-game"
    name = "beatify:api:start-game"
    requires_auth = False

    RATE_LIMIT_REQUESTS = 5
    RATE_LIMIT_WINDOW = 60  # seconds

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass
        self._rate_limits: dict[str, list[float]] = {}
        self._last_sweep: float = 0.0

    def _check_rate_limit(self, ip: str) -> bool:
        """Check if IP is within rate limit."""
        now = time.time()
        cutoff = now - self.RATE_LIMIT_WINDOW
        if now - self._last_sweep > 300:
            self._rate_limits = {
                k: [t for t in v if t > cutoff]
                for k, v in self._rate_limits.items()
                if any(t > cutoff for t in v)
            }
            self._last_sweep = now
        times = [t for t in self._rate_limits.get(ip, []) if t > cutoff]
        self._rate_limits[ip] = times
        if len(times) >= self.RATE_LIMIT_REQUESTS:
            return False
        times.append(now)
        return True

    async def post(self, request: web.Request) -> web.Response:  # noqa: PLR0911, PLR0912
        """Start a new game."""
        client_ip = request.remote or "unknown"
        if not self._check_rate_limit(client_ip):
            return web.json_response(
                {"error": "RATE_LIMITED", "message": "Too many requests"},
                status=429,
            )

        data = self.hass.data.get(DOMAIN, {})
        game_state = data.get("game")

        # Check for existing game
        if game_state and game_state.game_id:

            if game_state.phase == GamePhase.END:
                # Game is already finished — auto-clean state so a new game can start
                # without requiring the user to explicitly dismiss the end screen (#206)
                await game_state.end_game()
            else:
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
        intro_mode_enabled = body.get("intro_mode_enabled", False)  # Issue #23
        closest_wins_mode = body.get("closest_wins_mode", False)  # Issue #442
        party_lights_config = body.get("party_lights")  # Issue #331
        tts_config = body.get("tts")  # Issue #447

        # Validate difficulty (Story 14.1)
        valid_difficulties = (DIFFICULTY_EASY, DIFFICULTY_NORMAL, DIFFICULTY_HARD)
        if difficulty not in valid_difficulties:
            difficulty = DIFFICULTY_DEFAULT

        # Validate provider (Story 17.6: Spotify, YouTube Music, Tidal supported)
        valid_providers = (PROVIDER_SPOTIFY, PROVIDER_YOUTUBE_MUSIC, PROVIDER_TIDAL, PROVIDER_DEEZER)
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
                            "message": (
                                f"Round duration must be between "
                                f"{ROUND_DURATION_MIN} and {ROUND_DURATION_MAX} seconds"
                            ),
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
                    has_uri = any(
                        song.get(k)
                        for k in ("uri", "uri_spotify", "uri_youtube_music", "uri_tidal", "uri_deezer", "uri_apple_music")
                    )
                    if "year" in song and has_uri:
                        tagged = dict(song)
                        tagged["_playlist_source"] = playlist_path
                        songs.append(tagged)
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

        if provider == PROVIDER_TIDAL and not capabilities.get("tidal"):
            return web.json_response(
                {
                    "error": "PROVIDER_NOT_SUPPORTED",
                    "message": "Tidal is not supported on this speaker. Use Music Assistant.",
                },
                status=400,
            )

        if provider == PROVIDER_DEEZER and not capabilities.get("deezer"):
            return web.json_response(
                {
                    "error": "PROVIDER_NOT_SUPPORTED",
                    "message": "Deezer is not supported on this speaker. Use Music Assistant.",
                },
                status=400,
            )

        # Build create_game kwargs with optional round_duration (Story 13.1),
        # difficulty (Story 14.1), provider (Story 17.2), platform,
        # and artist_challenge_enabled (Story 20.7)
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
            "intro_mode_enabled": intro_mode_enabled,  # Issue #23
            "closest_wins_mode": closest_wins_mode,  # Issue #442
        }
        if round_duration is not None:
            create_kwargs["round_duration"] = round_duration

        result = game_state.create_game(**create_kwargs)
        result["warnings"] = warnings
        result["admin_token"] = game_state.admin_token  # Issue #386: for REST admin auth

        # Record game start time for analytics (Story 19.1)
        stats_service = data.get("stats")
        if stats_service:
            stats_service.record_game_start()

        # Set game language (Story 12.4, 16.3)
        if language in ("en", "de", "es", "fr", "nl"):
            game_state.language = language

        # Issue #331/#517: Configure Party Lights if enabled
        if party_lights_config and party_lights_config.get("enabled"):
            pl_entities = party_lights_config.get("entity_ids", [])
            pl_intensity = party_lights_config.get("intensity", "medium")
            pl_light_mode = party_lights_config.get("light_mode", "dynamic")
            pl_wled_presets = party_lights_config.get("wled_presets")
            if pl_entities:
                await game_state.configure_party_lights(
                    pl_entities, pl_intensity, pl_light_mode, pl_wled_presets
                )

        # Issue #447: Configure TTS if enabled
        if tts_config and tts_config.get("enabled"):
            tts_entity_id = tts_config.get("entity_id", "")
            if tts_entity_id:
                tts_announce_game_start = tts_config.get(
                    "announce_game_start", True
                )
                tts_announce_winner = tts_config.get("announce_winner", True)
                await game_state.configure_tts(
                    tts_entity_id,
                    announce_game_start=tts_announce_game_start,
                    announce_winner=tts_announce_winner,
                )
                await game_state.announce_game_start()

        # Broadcast to WebSocket clients
        ws_handler = data.get("ws_handler")
        if ws_handler:
            state_msg = build_state_message(game_state)
            if state_msg:
                await ws_handler.broadcast(state_msg)

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

    async def post(self, request: web.Request) -> web.Response:
        """End the current game."""
        data = self.hass.data.get(DOMAIN, {})
        game_state = data.get("game")

        if not game_state or not game_state.game_id:
            return web.json_response(
                {"error": "GAME_NOT_STARTED", "message": "No active game"},
                status=404,
            )

        if not _verify_admin_token(request, game_state):
            return web.json_response(
                {"error": "UNAUTHORIZED", "message": "Admin token required"},
                status=403,
            )

        await game_state.end_game()

        # Broadcast game_ended to WebSocket clients so players clean up properly
        ws_handler = data.get("ws_handler")
        if ws_handler:
            await ws_handler.broadcast({"type": "game_ended"})
            await ws_handler.broadcast_state()

        return web.json_response({"success": True})


class RematchGameView(HomeAssistantView):
    """Handle rematch game requests (Issue #108)."""

    url = "/beatify/api/rematch-game"
    name = "beatify:api:rematch-game"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass

    async def post(self, request: web.Request) -> web.Response:
        """Start a rematch with current players."""
        from custom_components.beatify.game.state import GamePhase  # noqa: PLC0415

        data = self.hass.data.get(DOMAIN, {})
        game_state = data.get("game")

        if not game_state or not game_state.game_id:
            return web.json_response(
                {"error": "GAME_NOT_FOUND", "message": "No active game"},
                status=404,
            )

        # Rematch is safe without token — game is already in END phase,
        # and the action just resets for a new game with the same players.
        # Token auth was blocking rematch from the player page (#535).
        if game_state.phase != GamePhase.END:
            return web.json_response(
                {"error": "INVALID_PHASE", "message": "Can only rematch from END phase"},
                status=400,
            )

        player_count = len(game_state.players)
        game_state.rematch_game()

        # Broadcast to WebSocket clients
        ws_handler = data.get("ws_handler")
        if ws_handler:
            await ws_handler.broadcast({"type": "rematch_started"})
            await ws_handler.broadcast_state()

        return web.json_response(
            {
                "success": True,
                "player_count": player_count,
                "new_game_id": game_state.game_id,
            }
        )


class StartGameplayView(HomeAssistantView):
    """Handle start gameplay requests (transition LOBBY -> PLAYING)."""

    url = "/beatify/api/start-gameplay"
    name = "beatify:api:start-gameplay"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass

    async def post(self, request: web.Request) -> web.Response:
        """Start gameplay from lobby."""
        from custom_components.beatify.game.state import GamePhase  # noqa: PLC0415

        data = self.hass.data.get(DOMAIN, {})
        game_state = data.get("game")

        if not game_state or not game_state.game_id:
            return web.json_response(
                {"error": "GAME_NOT_STARTED", "message": "No active game"},
                status=404,
            )

        if not _verify_admin_token(request, game_state):
            return web.json_response(
                {"error": "UNAUTHORIZED", "message": "Admin token required"},
                status=403,
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
        success = await game_state.start_round()
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
        html_content = await _get_html(self.hass, html_path)
        if html_content is None:
            _LOGGER.error("Player page not found: %s", html_path)
            return web.Response(text="Player page not found", status=500)
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
        game_state = get_game_state(self.hass)

        return web.json_response(
            build_game_status_response(game_state, game_id)
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
        html_content = await _get_html(self.hass, html_path)
        if html_content is None:
            _LOGGER.error("Dashboard page not found: %s", html_path)
            return web.Response(text="Dashboard page not found", status=500)
        return web.Response(text=html_content, content_type="text/html")


class StatsView(HomeAssistantView):
    """API endpoint for game statistics (Story 14.4)."""

    url = "/beatify/api/stats"
    name = "beatify:api:stats"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:
        """Get game statistics summary and history."""
        # Issue #386: Admin token required when game is active
        game_state = self.hass.data.get(DOMAIN, {}).get("game")
        if game_state and game_state.game_id and not _verify_admin_token(request, game_state):
            return web.json_response(
                {"error": "UNAUTHORIZED", "message": "Admin token required"},
                status=403,
            )

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
        self._last_sweep: float = 0.0  # Last time we did a full sweep

    def _check_rate_limit(self, ip: str) -> bool:
        """
        Check if IP is within rate limit.

        Args:
            ip: Client IP address

        Returns:
            True if allowed, False if rate limited

        """

        now = time.time()
        cutoff = now - self.RATE_LIMIT_WINDOW

        # Periodic full sweep every 5 minutes to evict stale IP entries
        if now - self._last_sweep > 300:
            self._rate_limits = {
                k: [t for t in v if t > cutoff]
                for k, v in self._rate_limits.items()
                if any(t > cutoff for t in v)
            }
            self._last_sweep = now

        # Get request times for this IP, filter old entries
        times = [t for t in self._rate_limits.get(ip, []) if t > cutoff]
        self._rate_limits[ip] = times

        if len(times) >= self.RATE_LIMIT_REQUESTS:
            return False

        times.append(now)
        return True

    async def get(self, request: web.Request) -> web.Response:
        """Get analytics metrics with caching and rate limiting."""

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
        content = await _get_html(self.hass, www_path)
        if content is None:
            return web.Response(text="Analytics page not found", status=404)
        return web.Response(text=content, content_type="text/html")


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

    MAX_REQUESTS = 100
    MAX_FIELD_LENGTH = 500
    RATE_LIMIT_REQUESTS = 10
    RATE_LIMIT_WINDOW = 60  # seconds

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass
        self._storage_path = Path(hass.config.path("beatify/playlist_requests.json"))
        self._rate_limits: dict[str, list[float]] = {}
        self._last_sweep: float = 0.0

    def _check_rate_limit(self, ip: str) -> bool:
        """Check if IP is within rate limit."""

        now = time.time()
        cutoff = now - self.RATE_LIMIT_WINDOW

        # Periodic full sweep every 5 minutes to evict stale IP entries
        if now - self._last_sweep > 300:
            self._rate_limits = {
                k: [t for t in v if t > cutoff]
                for k, v in self._rate_limits.items()
                if any(t > cutoff for t in v)
            }
            self._last_sweep = now

        times = [t for t in self._rate_limits.get(ip, []) if t > cutoff]
        self._rate_limits[ip] = times
        if len(times) >= self.RATE_LIMIT_REQUESTS:
            return False
        times.append(now)
        return True

    def _sanitize_item(self, item: object) -> dict | None:
        """Validate and sanitize a single playlist request item."""
        if not isinstance(item, dict):
            return None
        sanitized = {}
        for key, value in item.items():
            if not isinstance(key, str) or len(key) > 50:
                continue
            if isinstance(value, str):
                sanitized[key] = value[: self.MAX_FIELD_LENGTH]
            elif isinstance(value, (int, float, bool)):
                sanitized[key] = value
        return sanitized if sanitized else None

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
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
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
        # Rate limiting
        client_ip = request.remote or "unknown"
        if not self._check_rate_limit(client_ip):
            return web.json_response(
                {"error": "RATE_LIMITED", "message": "Too many requests"},
                status=429,
            )

        try:
            body = await request.json(content_type=None)
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

        raw_requests = body["requests"][: self.MAX_REQUESTS]

        # Sanitize each item
        sanitized = []
        for item in raw_requests:
            clean = self._sanitize_item(item)
            if clean is not None:
                sanitized.append(clean)

        # Build storage object
        data = {
            "requests": sanitized,
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


class SpotifyCredentialsView(HomeAssistantView):
    """Save/validate Spotify API credentials (#165)."""

    url = "/beatify/api/spotify-credentials"
    name = "beatify:api:spotify-credentials"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass

    async def post(self, request: web.Request) -> web.Response:
        """Save and validate Spotify credentials."""
        from custom_components.beatify.services.spotify_import import (  # noqa: PLC0415
            async_fetch_spotify_token,
            async_save_credentials,
        )

        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return web.json_response({"error": "Invalid JSON"}, status=400)

        client_id = body.get("client_id", "").strip()
        client_secret = body.get("client_secret", "").strip()
        if not client_id or not client_secret:
            return web.json_response(
                {"error": "client_id and client_secret required"}, status=400
            )

        # Validate by attempting to fetch a token
        import aiohttp  # noqa: PLC0415

        try:
            async with aiohttp.ClientSession() as session:
                token = await async_fetch_spotify_token(session, client_id, client_secret)
                if not token:
                    return web.json_response(
                        {"error": "Invalid credentials — Spotify rejected the token request"},
                        status=401,
                    )
        except Exception as err:  # noqa: BLE001
            return web.json_response(
                {"error": f"Failed to validate credentials: {err}"},
                status=500,
            )

        await async_save_credentials(self.hass, client_id, client_secret)
        return web.json_response({"success": True})

    async def get(self, request: web.Request) -> web.Response:  # noqa: ARG002
        """Check if credentials are configured."""
        from custom_components.beatify.services.spotify_import import (  # noqa: PLC0415
            async_load_credentials,
        )

        creds = await async_load_credentials(self.hass)
        return web.json_response({"configured": creds is not None})


class ImportPlaylistView(HomeAssistantView):
    """Import a Spotify playlist (#165)."""

    url = "/beatify/api/import-playlist"
    name = "beatify:api:import-playlist"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass

    async def post(self, request: web.Request) -> web.Response:
        """Import a Spotify playlist and save as Beatify JSON."""
        from custom_components.beatify.services.spotify_import import (  # noqa: PLC0415
            async_import_playlist,
        )

        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return web.json_response({"error": "Invalid JSON"}, status=400)

        spotify_url = body.get("spotify_url", "").strip()
        playlist_name = body.get("name", "").strip() or None
        if not spotify_url:
            return web.json_response(
                {"error": "spotify_url required"}, status=400
            )

        try:
            result = await async_import_playlist(
                self.hass, spotify_url, name=playlist_name
            )
            return web.json_response(result)
        except ValueError as err:
            return web.json_response({"error": str(err)}, status=400)
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Playlist import failed")
            return web.json_response(
                {"error": f"Import failed: {err}"}, status=500
            )


class EditPlaylistView(HomeAssistantView):
    """Edit an imported playlist (PR #549)."""

    url = "/beatify/api/edit-playlist"
    name = "beatify:api:edit-playlist"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:
        """Return playlist JSON for the given filename."""
        filename = request.query.get("file", "").strip()
        if not filename:
            return web.json_response({"error": "file parameter required"}, status=400)

        playlist_dir = Path(self.hass.config.path("beatify/playlists"))
        file_path = playlist_dir / filename

        # Prevent path traversal
        try:
            file_path = file_path.resolve()
            playlist_dir_resolved = playlist_dir.resolve()
            if not file_path.is_relative_to(playlist_dir_resolved):
                return web.json_response({"error": "Invalid file path"}, status=400)
        except Exception:  # noqa: BLE001
            return web.json_response({"error": "Invalid file path"}, status=400)

        def _read() -> dict | None:
            if not file_path.exists():
                return None
            return json.loads(file_path.read_text(encoding="utf-8"))

        data = await self.hass.async_add_executor_job(_read)
        if data is None:
            return web.json_response({"error": "Playlist not found"}, status=404)

        return web.json_response({
            "file": filename,
            "name": data.get("name", ""),
            "tags": data.get("tags", []),
            "songs": data.get("songs", []),
        })

    async def post(self, request: web.Request) -> web.Response:
        """Save updated playlist data."""
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return web.json_response({"error": "Invalid JSON"}, status=400)

        filename = body.get("file", "").strip()
        if not filename:
            return web.json_response({"error": "file required"}, status=400)

        playlist_dir = Path(self.hass.config.path("beatify/playlists"))
        file_path = playlist_dir / filename

        # Prevent path traversal
        try:
            file_path = file_path.resolve()
            playlist_dir_resolved = playlist_dir.resolve()
            if not file_path.is_relative_to(playlist_dir_resolved):
                return web.json_response({"error": "Invalid file path"}, status=400)
        except Exception:  # noqa: BLE001
            return web.json_response({"error": "Invalid file path"}, status=400)

        # Read existing data to preserve version and other fields
        def _read_existing() -> dict:
            if file_path.exists():
                return json.loads(file_path.read_text(encoding="utf-8"))
            return {}

        existing = await self.hass.async_add_executor_job(_read_existing)

        # Update fields
        existing["name"] = body.get("name", existing.get("name", ""))
        existing["tags"] = body.get("tags", existing.get("tags", []))
        existing["songs"] = body.get("songs", existing.get("songs", []))

        def _save() -> None:
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(
                json.dumps(existing, indent=2, ensure_ascii=False), encoding="utf-8"
            )

        await self.hass.async_add_executor_job(_save)

        # Refresh playlist discovery so changes appear immediately
        await async_discover_playlists(self.hass)

        return web.json_response({"success": True})

    async def delete(self, request: web.Request) -> web.Response:
        """Remove a song by index from a playlist."""
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return web.json_response({"error": "Invalid JSON"}, status=400)

        filename = body.get("file", "").strip()
        remove_index = body.get("remove_index")
        if not filename or remove_index is None:
            return web.json_response(
                {"error": "file and remove_index required"}, status=400
            )

        playlist_dir = Path(self.hass.config.path("beatify/playlists"))
        file_path = playlist_dir / filename

        # Prevent path traversal
        try:
            file_path = file_path.resolve()
            playlist_dir_resolved = playlist_dir.resolve()
            if not file_path.is_relative_to(playlist_dir_resolved):
                return web.json_response({"error": "Invalid file path"}, status=400)
        except Exception:  # noqa: BLE001
            return web.json_response({"error": "Invalid file path"}, status=400)

        def _read() -> dict | None:
            if not file_path.exists():
                return None
            return json.loads(file_path.read_text(encoding="utf-8"))

        data = await self.hass.async_add_executor_job(_read)
        if data is None:
            return web.json_response({"error": "Playlist not found"}, status=404)

        songs = data.get("songs", [])
        try:
            idx = int(remove_index)
        except (ValueError, TypeError):
            return web.json_response({"error": "Invalid remove_index"}, status=400)
        if idx < 0 or idx >= len(songs):
            return web.json_response({"error": "Index out of range"}, status=400)

        songs.pop(idx)
        data["songs"] = songs

        def _save() -> None:
            file_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
            )

        await self.hass.async_add_executor_job(_save)

        return web.json_response({
            "success": True,
            "song_count": len(songs),
        })


class SpotifySearchView(HomeAssistantView):
    """Search Spotify for tracks (PR #549)."""

    url = "/beatify/api/spotify-search"
    name = "beatify:api:spotify-search"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:
        """Search Spotify for tracks matching query."""
        from custom_components.beatify.services.spotify_import import (  # noqa: PLC0415
            async_fetch_spotify_token,
            async_load_credentials,
        )

        query = request.query.get("q", "").strip()
        if not query:
            return web.json_response({"error": "q parameter required"}, status=400)

        credentials = await async_load_credentials(self.hass)
        if not credentials:
            return web.json_response(
                {"error": "Spotify credentials not configured"}, status=400
            )

        import aiohttp  # noqa: PLC0415

        try:
            async with aiohttp.ClientSession() as session:
                token = await async_fetch_spotify_token(
                    session,
                    credentials["client_id"],
                    credentials["client_secret"],
                )

                from urllib.parse import quote  # noqa: PLC0415

                encoded_q = quote(query)
                url = (
                    f"https://api.spotify.com/v1/search"
                    f"?q={encoded_q}&type=track&limit=5"
                )
                headers = {"Authorization": f"Bearer {token}"}

                async with session.get(url, headers=headers) as resp:
                    if resp.status != 200:
                        return web.json_response(
                            {"error": "Spotify search failed"}, status=502
                        )
                    data = await resp.json()

            results = []
            for item in data.get("tracks", {}).get("items", []):
                artists = ", ".join(a["name"] for a in item.get("artists", []))
                album = item.get("album", {})
                release_date = album.get("release_date", "")
                year = (
                    int(release_date[:4])
                    if release_date and len(release_date) >= 4
                    else 0
                )
                results.append({
                    "title": item["name"],
                    "artist": artists,
                    "year": year,
                    "uri": item.get("uri", ""),
                })

            return web.json_response({"results": results})
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Spotify search failed")
            return web.json_response(
                {"error": f"Search failed: {err}"}, status=500
            )
