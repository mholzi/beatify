"""Game-action HTTP views for Beatify (start, end, pause, rematch, gameplay)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.helpers import entity_registry as er

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
from custom_components.beatify.game.state import GamePhase, GameState
from custom_components.beatify.server.base import (
    BeatifyAdminView,
    RateLimitMixin,
    _json_error,
    _read_file,
    _verify_admin_token,
)
from custom_components.beatify.server.serializers import (
    build_state_message,
)
from custom_components.beatify.services.media_player import get_platform_capabilities

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class StartGameView(RateLimitMixin, HomeAssistantView):
    """Handle start game requests."""

    url = "/beatify/api/start-game"
    name = "beatify:api:start-game"
    requires_auth = False

    RATE_LIMIT_REQUESTS = 5
    RATE_LIMIT_WINDOW = 60  # seconds

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass
        self._init_rate_limits()

    async def post(self, request: web.Request) -> web.Response:  # noqa: PLR0911, PLR0912
        """Start a new game."""
        client_ip = request.remote or "unknown"
        if not self._check_rate_limit(client_ip):
            return _json_error("Too many requests", 429, code="RATE_LIMITED")

        data = self.hass.data.get(DOMAIN, {})
        game_state = data.get("game")

        # Check for existing game
        if game_state and game_state.game_id:

            if game_state.phase == GamePhase.END:
                # Game is already finished -- auto-clean state so a new game can start
                # without requiring the user to explicitly dismiss the end screen (#206)
                await game_state.end_game()
            else:
                return _json_error("End current game first", 409, code="GAME_ALREADY_STARTED")

        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            return _json_error("Invalid JSON", 400, code="INVALID_REQUEST")

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
                    return _json_error(
                        f"Round duration must be between {ROUND_DURATION_MIN} and {ROUND_DURATION_MAX} seconds",
                        400,
                        code="INVALID_REQUEST",
                    )
            except (ValueError, TypeError):
                return _json_error("Invalid round duration value", 400, code="INVALID_REQUEST")

        if not playlist_paths:
            return _json_error("No playlists selected", 400, code="INVALID_REQUEST")

        if not media_player:
            return _json_error("No media player selected", 400, code="INVALID_REQUEST")

        # Validate media player entity exists
        media_player_state = self.hass.states.get(media_player)
        if not media_player_state:
            return _json_error("Media player not found", 400, code="INVALID_REQUEST")
        if media_player_state.state == "unavailable":
            return _json_error("Media player is unavailable", 400, code="INVALID_REQUEST")

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
            return _json_error("No valid songs found in selected playlists", 400, code="INVALID_REQUEST")

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
            return _json_error(
                capabilities.get("reason", "This player type is not supported"),
                400,
                code="UNSUPPORTED_PLAYER",
            )

        # Validate provider is supported by platform
        if provider == "apple_music" and not capabilities.get("apple_music"):
            return _json_error(
                "Apple Music is not supported on this speaker. Use Music Assistant.",
                400,
                code="PROVIDER_NOT_SUPPORTED",
            )

        if provider == PROVIDER_YOUTUBE_MUSIC and not capabilities.get("youtube_music"):
            return _json_error(
                "YouTube Music is not supported on this speaker. Use Music Assistant.",
                400,
                code="PROVIDER_NOT_SUPPORTED",
            )

        if provider == PROVIDER_TIDAL and not capabilities.get("tidal"):
            return _json_error(
                "Tidal is not supported on this speaker. Use Music Assistant.",
                400,
                code="PROVIDER_NOT_SUPPORTED",
            )

        if provider == PROVIDER_DEEZER and not capabilities.get("deezer"):
            return _json_error(
                "Deezer is not supported on this speaker. Use Music Assistant.",
                400,
                code="PROVIDER_NOT_SUPPORTED",
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


class EndGameView(BeatifyAdminView):
    """Handle end game requests."""

    url = "/beatify/api/end-game"
    name = "beatify:api:end-game"

    async def post(self, request: web.Request) -> web.Response:
        """End the current game."""
        data = self.hass.data.get(DOMAIN, {})
        game_state = data.get("game")

        if not game_state or not game_state.game_id:
            return _json_error("No active game", 404, code="GAME_NOT_STARTED")

        err = self._verify_admin(request)
        if err:
            return err

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
            return _json_error("No active game", 404, code="GAME_NOT_FOUND")

        # Rematch is safe without token -- game is already in END phase,
        # and the action just resets for a new game with the same players.
        # Token auth was blocking rematch from the player page (#535).
        if game_state.phase != GamePhase.END:
            return _json_error("Can only rematch from END phase", 400, code="INVALID_PHASE")

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


class StartGameplayView(BeatifyAdminView):
    """Handle start gameplay requests (transition LOBBY -> PLAYING)."""

    url = "/beatify/api/start-gameplay"
    name = "beatify:api:start-gameplay"

    async def post(self, request: web.Request) -> web.Response:
        """Start gameplay from lobby."""
        from custom_components.beatify.game.state import GamePhase  # noqa: PLC0415

        data = self.hass.data.get(DOMAIN, {})
        game_state = data.get("game")

        if not game_state or not game_state.game_id:
            return _json_error("No active game", 404, code="GAME_NOT_STARTED")

        err = self._verify_admin(request)
        if err:
            return err

        if game_state.phase != GamePhase.LOBBY:
            return _json_error("Game already started", 409, code="INVALID_PHASE")

        # Set round end callback for broadcasting
        ws_handler = data.get("ws_handler")
        if ws_handler:
            game_state.set_round_end_callback(ws_handler.broadcast_state)
            # Set metadata update callback for fast transitions (Issue #42)
            game_state.set_metadata_update_callback(ws_handler.broadcast_metadata_update)

        # Start the first round
        success = await game_state.start_round()
        if not success:
            return _json_error("Failed to start - no songs", 500, code="START_FAILED")

        # Broadcast state to all connected players
        if ws_handler:
            await ws_handler.broadcast_state()

        return web.json_response({"success": True, "phase": game_state.phase.value})


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
        from custom_components.beatify.server.serializers import (  # noqa: PLC0415
            build_game_status_response,
            get_game_state,
        )

        game_id = request.query.get("game")
        game_state = get_game_state(self.hass)

        return web.json_response(
            build_game_status_response(game_state, game_id)
        )
