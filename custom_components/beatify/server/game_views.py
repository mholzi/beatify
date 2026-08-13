"""Game-action HTTP views for Beatify (start, end, pause, rematch, gameplay)."""

from __future__ import annotations

import contextlib
import functools
import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.helpers import entity_registry as er

from custom_components.beatify.const import (
    DEFAULT_ROUND_DURATION,
    DIFFICULTY_DEFAULT,
    DIFFICULTY_EASY,
    DIFFICULTY_HARD,
    DIFFICULTY_NORMAL,
    DOMAIN,
    PROVIDER_AMAZON_MUSIC,
    PROVIDER_APPLE_MUSIC,
    PROVIDER_DEEZER,
    PROVIDER_DEFAULT,
    PROVIDER_MA_LIBRARY,
    PROVIDER_SPOTIFY,
    PROVIDER_TIDAL,
    PROVIDER_YOUTUBE_MUSIC,
    ROUND_DURATION_MAX,
    ROUND_DURATION_MIN,
)
from custom_components.beatify.game.playlist import (
    async_discover_playlists_detailed,
)
from custom_components.beatify.game.state import GamePhase, GameState
from custom_components.beatify.server.base import (
    BeatifyAdminView,
    RateLimitMixin,
    _json_error,
    _read_file,
)
from custom_components.beatify.server.companion_auth import is_authorized_http
from custom_components.beatify.server.serializers import (
    build_state_message,
)
from custom_components.beatify.server.setup_state import clear_setup
from custom_components.beatify.server.ws_handlers.admin import _finalize_and_end
from custom_components.beatify.services.media_player import (
    async_get_native_twin_remap,
    get_platform_capabilities,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


def _validate_provider(provider: str) -> str:
    """Coerce unknown providers to PROVIDER_DEFAULT.

    Single source of truth for which providers the wizard may select. #808
    surfaced the cost of forgetting to update this list: PROVIDER_APPLE_MUSIC
    was missing, so wizard selections of "apple_music" silently became
    "spotify". Pre-#805 the cascade walked all six URI fields anyway so the
    wrong provider was a near-invisible bug. After #805 the cascade only
    walks the user-selected provider's fields — Apple-Music users were
    getting Spotify-only candidates, all of which fail on MA without a
    Spotify provider configured.
    """
    valid_providers = (
        PROVIDER_SPOTIFY,
        PROVIDER_APPLE_MUSIC,
        PROVIDER_YOUTUBE_MUSIC,
        PROVIDER_TIDAL,
        PROVIDER_DEEZER,
        PROVIDER_AMAZON_MUSIC,
        # Crate Digger. Omitting it here silently coerced the selection to
        # PROVIDER_DEFAULT, after which the "no playlists" guard fired and
        # create-game answered 400 with no log line — the same failure mode
        # this docstring records for Apple Music in #808.
        PROVIDER_MA_LIBRARY,
    )
    return provider if provider in valid_providers else PROVIDER_DEFAULT


class StartGameView(RateLimitMixin, HomeAssistantView):
    """Handle start game requests."""

    url = "/beatify/api/start-game"
    name = "beatify:api:start-game"
    requires_auth = False  # auth handled in-handler so Companion path works (#1131)

    RATE_LIMIT_REQUESTS = 5
    RATE_LIMIT_WINDOW = 60  # seconds

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass
        self._init_rate_limits()

    async def post(self, request: web.Request) -> web.Response:
        """Start a new game."""
        if not is_authorized_http(request, self.hass):
            return _json_error("Unauthorized", 401, code="UNAUTHORIZED")
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
            elif game_state.phase == GamePhase.LOBBY:
                # #935: a LOBBY game already exists — the caller should begin
                # gameplay, not create another. A distinct code lets the client
                # recover by routing to start-gameplay instead of dead-ending
                # the host on "End current game first" for a game that is
                # sitting right there in the lobby.
                return _json_error(
                    "A game is already in the lobby — start gameplay instead",
                    409,
                    code="GAME_IN_LOBBY",
                )
            else:
                return _json_error(
                    "End current game first", 409, code="GAME_ALREADY_STARTED"
                )

        try:
            body = await request.json()
        except (ValueError, UnicodeDecodeError):
            return _json_error("Invalid JSON", 400, code="INVALID_REQUEST")

        playlist_paths = body.get("playlists", [])
        media_player = body.get("media_player")
        language = body.get("language", "en")
        round_duration = body.get("round_duration")  # Story 13.1
        difficulty = body.get("difficulty", DIFFICULTY_DEFAULT)  # Story 14.1
        provider = body.get("provider", PROVIDER_DEFAULT)  # Story 17.2
        artist_challenge_enabled = body.get(
            "artist_challenge_enabled", True
        )  # Story 20.7
        movie_quiz_enabled = body.get("movie_quiz_enabled", True)  # Issue #28
        intro_mode_enabled = body.get("intro_mode_enabled", False)  # Issue #23
        closest_wins_mode = body.get("closest_wins_mode", False)  # Issue #442
        sudden_death_mode = bool(body.get("sudden_death_mode", False))  # Issue #827
        title_artist_mode = body.get("title_artist_mode", False)  # #1180
        rampup_order_enabled = bool(
            body.get("rampup_order_enabled", False)
        )  # Issue #1726
        # #1475: 0 or missing means "play every song" — the historic behaviour.
        # Negative or unparseable values fall back to 0 instead of raising: a
        # malformed payload must not block a party. The ten-round floor is
        # applied by PlaylistManager, not here.
        try:
            max_rounds = max(0, int(body.get("max_rounds", 0) or 0))
        except (TypeError, ValueError):
            max_rounds = 0
        finale_double_enabled = bool(
            body.get("finale_double_enabled", False)
        )  # Issue #1725
        finale_tiebreaker_enabled = bool(
            body.get("finale_tiebreaker_enabled", False)
        )  # Issue #1725
        comeback_token_enabled = bool(
            body.get("comeback_token_enabled", False)
        )  # Issue #1724
        difficulty_bet_scaling_enabled = bool(
            body.get("difficulty_bet_scaling_enabled", False)
        )  # Issue #1727
        sabotage_enabled = bool(body.get("sabotage_enabled", False))  # Issue #1665
        reveal_auto_advance = body.get("reveal_auto_advance", 0)  # #1012
        party_lights_config = body.get("party_lights")  # Issue #331
        tts_config = body.get("tts")  # Issue #447

        # #1012: REVEAL auto-advance — 0 (off, manual + song-end advance)
        # or 30/60/90 seconds. Default 0: host stays in control.
        try:
            reveal_auto_advance = int(reveal_auto_advance)
        except (ValueError, TypeError):
            reveal_auto_advance = 0
        if reveal_auto_advance not in (0, 30, 60, 90):
            reveal_auto_advance = 0

        # Validate difficulty (Story 14.1)
        valid_difficulties = (DIFFICULTY_EASY, DIFFICULTY_NORMAL, DIFFICULTY_HARD)
        if difficulty not in valid_difficulties:
            difficulty = DIFFICULTY_DEFAULT

        # Validate provider (Story 17.6 + #808). See _validate_provider for
        # the cost of forgetting to update this list.
        provider = _validate_provider(provider)
        # Crate Digger: the raw client block. The stored settings
        # are merged over it (server-authoritative) inside
        # _generate_library_songs — the client payload is only a fallback for
        # keys the Store doesn't have.
        library_config = body.get("library") or {}

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
                return _json_error(
                    "Invalid round duration value", 400, code="INVALID_REQUEST"
                )

        # Crate Digger GENERATES its playlist from the host's own library at
        # create time (see the library branch below), so it legitimately
        # arrives with no playlist paths. Every other provider must select at
        # least one — a game with no source cannot be played.
        if not playlist_paths and provider != PROVIDER_MA_LIBRARY:
            return _json_error("No playlists selected", 400, code="INVALID_REQUEST")

        if not media_player:
            return _json_error("No media player selected", 400, code="INVALID_REQUEST")

        # #1627 follow-up: heal a stale selection that points at the native twin
        # of a Music Assistant speaker. #1628 hides such twins from the picker,
        # but a saved selection (wizard localStorage, admin auto-restore, or a
        # direct API call) can still carry the native entity_id (e.g.
        # media_player.unnamed_room) — playing on it routes provider URIs to a
        # player that can't resolve them (UPnP Error 800), pausing the game with
        # media_player_error. Remap to the MA twin (same physical speaker) BEFORE
        # any validation/platform detection so every start path heals uniformly.
        twin_remap = await async_get_native_twin_remap(self.hass)
        if media_player in twin_remap:
            ma_twin = twin_remap[media_player]
            _LOGGER.info(
                "Remapped native-twin media player %s → MA twin %s (#1627)",
                media_player,
                ma_twin,
            )
            media_player = ma_twin

        # Validate media player entity exists
        media_player_state = self.hass.states.get(media_player)
        if not media_player_state:
            return _json_error("Media player not found", 400, code="INVALID_REQUEST")
        if media_player_state.state == "unavailable":
            return _json_error(
                "Media player is unavailable", 400, code="INVALID_REQUEST"
            )

        # Load and validate playlists -- or, for the library provider, sample a
        # fresh playlist from the enriched library pool (no files involved).
        songs: list[dict[str, Any]] = []
        if provider == PROVIDER_MA_LIBRARY and not playlist_paths:
            # No playlists picked -> fresh mix sampled from the library pool.
            # (Saved Crate Digger playlists, when selected, load through the
            # normal file path below -- their songs carry uri_ma_library.)
            _LOGGER.info(
                "Library game: no playlists selected -> generating fresh songs"
            )
            songs, err_resp = await _generate_library_songs(self.hass, library_config)
            if err_resp is not None:
                return err_resp
        if provider == PROVIDER_MA_LIBRARY and playlist_paths:
            import time as _time

            self.hass.data.setdefault(DOMAIN, {})["library_last_generate"] = {
                "ts": int(_time.time()),
                "skipped_playlists": len(playlist_paths),
            }
            _LOGGER.info(
                "Library game: %d saved playlist(s) selected -> playing those "
                "(popularity/genre settings do not apply to saved playlists)",
                len(playlist_paths),
            )
        warnings: list[str] = []
        playlist_dir = Path(self.hass.config.path("beatify/playlists"))

        # #1766: discovery already read+parsed every playlist file (memoised,
        # off-loop, and refreshed by the /api/status poll seconds before the
        # Start tap). Reuse that parse instead of re-reading + re-parsing each
        # ~600-song document on the event loop at this latency-sensitive moment.
        # ``songs_by_path`` is keyed by the same unresolved glob path the picker
        # sends, so a hit is a plain dict lookup; only a playlist added since the
        # last discovery walk (a cache miss) falls back to an executor read.
        _metas, songs_by_path = await async_discover_playlists_detailed(self.hass)

        for playlist_path in playlist_paths:
            try:
                full_path = playlist_dir / playlist_path
                # Security: Prevent path traversal attacks
                try:
                    if not full_path.resolve().is_relative_to(playlist_dir.resolve()):
                        warnings.append(f"Invalid playlist path: {playlist_path}")
                        continue
                except ValueError:
                    warnings.append(f"Invalid playlist path: {playlist_path}")
                    continue

                playlist_songs = songs_by_path.get(str(full_path))
                if playlist_songs is None:
                    # Cache miss (added since the last discovery walk) — fall back
                    # to the executor read + parse so the loop stays unblocked.
                    resolved = full_path.resolve()
                    if not resolved.exists():
                        warnings.append(f"Playlist not found: {playlist_path}")
                        continue
                    file_content = await self.hass.async_add_executor_job(
                        _read_file, resolved
                    )
                    playlist_songs = json.loads(file_content).get("songs", [])

                for song in playlist_songs:
                    has_uri = any(
                        song.get(k)
                        for k in (
                            "uri",
                            "uri_spotify",
                            "uri_youtube_music",
                            "uri_tidal",
                            "uri_deezer",
                            "uri_apple_music",
                        )
                    )
                    if "year" in song and has_uri:
                        tagged = dict(song)
                        tagged["_playlist_source"] = playlist_path
                        songs.append(tagged)
                    else:
                        warnings.append(
                            f"Invalid song in {playlist_path}: missing year or uri"
                        )

            except (OSError, ValueError) as err:
                warnings.append(f"Failed to load {playlist_path}: {err}")

        if not songs:
            return _json_error(
                "No valid songs found in selected playlists",
                400,
                code="INVALID_REQUEST",
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

        # #1663: the admin UI renders setup errors concretely ("Speaker X can't
        # play Apple Music") by interpolating {speaker}/{provider} from these
        # details. Fall back to the entity_id if the state carries no friendly
        # name. PROVIDER_LABELS gives each provider a human, translatable-free
        # display name.
        speaker_name = media_player_state.name if media_player_state else media_player

        # Validate platform is supported
        capabilities = get_platform_capabilities(platform)
        if not capabilities.get("supported"):
            return _json_error(
                capabilities.get("reason", "This player type is not supported"),
                400,
                code="UNSUPPORTED_PLAYER",
                details={"speaker": speaker_name},
            )

        # Validate provider is supported by platform
        if provider == "apple_music" and not capabilities.get("apple_music"):
            return _json_error(
                "Apple Music is not supported on this speaker. Use Music Assistant.",
                400,
                code="PROVIDER_NOT_SUPPORTED",
                details={"speaker": speaker_name, "provider": "Apple Music"},
            )

        if provider == PROVIDER_YOUTUBE_MUSIC and not capabilities.get("youtube_music"):
            return _json_error(
                "YouTube Music is not supported on this speaker. Use Music Assistant.",
                400,
                code="PROVIDER_NOT_SUPPORTED",
                details={"speaker": speaker_name, "provider": "YouTube Music"},
            )

        if provider == PROVIDER_TIDAL and not capabilities.get("tidal"):
            return _json_error(
                "Tidal is not supported on this speaker. Use Music Assistant.",
                400,
                code="PROVIDER_NOT_SUPPORTED",
                details={"speaker": speaker_name, "provider": "Tidal"},
            )

        if provider == PROVIDER_DEEZER and not capabilities.get("deezer"):
            return _json_error(
                "Deezer is not supported on this speaker. Use Music Assistant.",
                400,
                code="PROVIDER_NOT_SUPPORTED",
                details={"speaker": speaker_name, "provider": "Deezer"},
            )

        if provider == PROVIDER_AMAZON_MUSIC and not capabilities.get("amazon_music"):
            return _json_error(
                "Amazon Music is not supported on this speaker. Use an Amazon Echo (alexa_media).",
                400,
                code="PROVIDER_NOT_SUPPORTED",
                details={"speaker": speaker_name, "provider": "Amazon Music"},
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
            "sudden_death_mode": sudden_death_mode,  # Issue #827
            "title_artist_mode": title_artist_mode,  # #1180
            "rampup_order_enabled": rampup_order_enabled,  # Issue #1726
            "finale_double_enabled": finale_double_enabled,  # Issue #1725
            "finale_tiebreaker_enabled": finale_tiebreaker_enabled,  # Issue #1725
            "comeback_token_enabled": comeback_token_enabled,  # Issue #1724
            "difficulty_bet_scaling_enabled": difficulty_bet_scaling_enabled,  # Issue #1727
            "sabotage_enabled": sabotage_enabled,  # Issue #1665
            "reveal_auto_advance": reveal_auto_advance,  # #1012
            "max_rounds": max_rounds,  # #1475
        }
        if round_duration is not None:
            create_kwargs["round_duration"] = round_duration

        # #1867: state the round timer's provenance at the one moment it is
        # decided. The only prior trace was "Round N started (%.1fs timer)",
        # which shows the effective value but not whether the client asked for
        # it or the server fell back — the difference between "the host chose
        # this" and "nobody chose this". Settling #1867 needed the raw payload,
        # which no log had; one line here makes the next report a lookup.
        _LOGGER.info(
            "Game created with round_duration=%ss (client sent %r)",
            create_kwargs.get("round_duration", DEFAULT_ROUND_DURATION),
            body.get("round_duration"),
        )

        result = game_state.create_game(**create_kwargs)

        # Crate Digger: install the pre-start hook so the songs
        # are regenerated from the CURRENT settings on the LOBBY -> first
        # round transition, and the persisted output settings re-applied.
        # See game/state_lifecycle.py for why this must run from start_round.
        if provider == PROVIDER_MA_LIBRARY and not playlist_paths:

            async def _regen_library_songs(gs: Any) -> None:
                fresh_songs, regen_err = await _generate_library_songs(self.hass, {})
                if regen_err is None and fresh_songs and gs.replace_songs(fresh_songs):
                    _LOGGER.info(
                        "Library game: songs regenerated at gameplay start "
                        "(%d songs, current settings)",
                        len(fresh_songs),
                    )
                # Re-apply the persisted output settings SERVER-SIDE. The
                # client push proved unreliable on the force-reset path
                # (localStorage wipe + reload + token reset races); the Store
                # holds the last-known values and this hook runs on every
                # start path, so whatever was last saved always wins.
                from custom_components.beatify.server.library_views import (
                    async_load_game_output_settings,
                )

                out = await async_load_game_output_settings(self.hass)
                if out:
                    mp = out.get("media_player")
                    if isinstance(mp, str) and mp and self.hass.states.get(mp):
                        if gs.media_player != mp:
                            gs.media_player = mp
                            # #2143: same release-instead-of-null as the lobby
                            # switch below. This path runs pre-start, so there
                            # is usually nothing captured yet — but a force-
                            # reset can land here mid-game.
                            gs.release_media_player_service()
                            _cp = getattr(gs, "_cancel_prewarm", None)
                            if callable(_cp):
                                with contextlib.suppress(Exception):
                                    _cp()
                            _LOGGER.info("Pre-start: media_player -> %s", mp)
                    if "tts" in out:
                        with contextlib.suppress(Exception):
                            applied = await _apply_tts_config(gs, out["tts"])
                            _LOGGER.info(
                                "Pre-start: tts %s",
                                "configured" if applied else "disabled",
                            )
                    if "party_lights" in out:
                        with contextlib.suppress(Exception):
                            applied = await _apply_party_lights_config(
                                gs, out["party_lights"]
                            )
                            _LOGGER.info(
                                "Pre-start: party lights %s",
                                "configured" if applied else "disabled",
                            )

            game_state.pre_start_hook = _regen_library_songs

        result["warnings"] = warnings
        result["admin_token"] = (
            game_state.admin_token
        )  # Issue #386: for REST admin auth

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
        # Issue #471 Phase 1: Forward Game Flow toggles too.
        if tts_config and tts_config.get("enabled"):
            tts_entity_id = tts_config.get("entity_id", "")
            if tts_entity_id:
                await game_state.configure_tts(
                    tts_entity_id,
                    announce_game_start=tts_config.get("announce_game_start", True),
                    announce_winner=tts_config.get("announce_winner", True),
                    announce_round_start=tts_config.get("announce_round_start", True),
                    announce_countdown=tts_config.get("announce_countdown", False),
                    announce_time_up=tts_config.get("announce_time_up", True),
                    announce_correct_answer=tts_config.get(
                        "announce_correct_answer", True
                    ),
                    announce_nobody_correct=tts_config.get(
                        "announce_nobody_correct", True
                    ),
                    announce_exact_guess=tts_config.get("announce_exact_guess", True),
                    announce_closest_guess=tts_config.get(
                        "announce_closest_guess", True
                    ),
                    announce_streak_milestone=tts_config.get(
                        "announce_streak_milestone", True
                    ),
                    announce_streak_broken=tts_config.get(
                        "announce_streak_broken", False
                    ),
                    announce_leader_change=tts_config.get(
                        "announce_leader_change", True
                    ),
                    announce_tied_first=tts_config.get("announce_tied_first", True),
                    announce_bet_won=tts_config.get("announce_bet_won", True),
                    announce_bet_lost=tts_config.get("announce_bet_lost", True),
                    announce_player_join=tts_config.get("announce_player_join", True),
                    announce_player_reconnect=tts_config.get(
                        "announce_player_reconnect", False
                    ),
                    announce_last_round=tts_config.get("announce_last_round", True),
                    announce_podium=tts_config.get("announce_podium", True),
                    announce_rematch=tts_config.get("announce_rematch", True),
                    announce_intro_round=tts_config.get("announce_intro_round", True),
                    announce_steal_unlocked=tts_config.get(
                        "announce_steal_unlocked", True
                    ),
                    announce_steal_used=tts_config.get("announce_steal_used", True),
                    # Issue #1211: compensate for pre-round TTS overhead so the
                    # timer doesn't eat into actual music play time.
                    tts_pre_round_delay=float(tts_config.get("tts_pre_round_delay", 0)),
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
        return (
            f"{url.scheme}://{url.host}:{url.port}"
            if url.port
            else f"{url.scheme}://{url.host}"
        )


class EndGameView(BeatifyAdminView):
    """Handle end game requests."""

    url = "/beatify/api/end-game"
    name = "beatify:api:end-game"
    # rc15 (#1131): HA's middleware-enforced auth would block the request
    # before is_authorized_http() ever runs, so Companion bypass requests
    # land on a generic 401 HTML page from HA → admin.js fetches it and
    # response.json() throws → "Network error" alert. Match the pattern
    # StartGameView / ForceResetView / RematchView already use.
    requires_auth = False

    async def post(self, request: web.Request) -> web.Response:
        """End the current game."""
        if not is_authorized_http(request, self.hass):
            return _json_error("Unauthorized", 401, code="UNAUTHORIZED")
        data = self.hass.data.get(DOMAIN, {})
        game_state = data.get("game")

        if not game_state or not game_state.game_id:
            return _json_error("No active game", 404, code="GAME_NOT_STARTED")

        await game_state.end_game()

        # Broadcast game_ended to WebSocket clients so players clean up properly
        ws_handler = data.get("ws_handler")
        if ws_handler:
            await ws_handler.broadcast({"type": "game_ended"})
            await ws_handler.broadcast_state()

        return web.json_response({"success": True})


class ForceResetView(RateLimitMixin, HomeAssistantView):
    """Emergency escape hatch when state gets stuck (#777 follow-up).

    Requires a logged-in HA user (#998). Recovery is no longer tied to a
    per-game admin token — any household HA user can unwedge stuck state —
    so the old "you might not have a valid token" rationale no longer
    applies. Still rate-limited per IP to prevent DoS abuse.

    #2036: the reset also drops the persisted setup blob. The client half of
    the reset clears ``localStorage`` and reloads, but the server kept
    reporting ``setup_complete: true`` — and ``reconcileSavedSetup()`` wrote
    the saved speaker straight back into the emptied storage on that same
    load, so the wizard stayed shut and the host landed on the ready-to-host
    screen again. The reset therefore spans the whole installation, not just
    the device that pressed it; that follows from it already ending the
    running game for everyone, and the confirm dialog plus the 3/hour rate
    limit sit in front of it.
    """

    url = "/beatify/api/force-reset"
    name = "beatify:api:force-reset"
    requires_auth = False  # auth handled in-handler so Companion path works (#1131)

    # Tighter than EndGameView's defaults — this kills active games, so
    # 3 hits per hour per IP is plenty for legitimate "I got stuck" use.
    RATE_LIMIT_REQUESTS = 3
    RATE_LIMIT_WINDOW = 3600  # seconds

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass
        self._init_rate_limits()

    async def post(self, request: web.Request) -> web.Response:
        """Force-end any active game and report what was cleaned up."""
        if not is_authorized_http(request, self.hass):
            return _json_error("Unauthorized", 401, code="UNAUTHORIZED")
        client_ip = request.remote or "unknown"
        if not self._check_rate_limit(client_ip):
            return _json_error("Too many requests", 429, code="RATE_LIMITED")

        data = self.hass.data.get(DOMAIN, {})
        game_state = data.get("game")
        ended_game_id = None
        if game_state and game_state.game_id:
            ended_game_id = game_state.game_id
            try:
                await game_state.end_game()
            except Exception:
                # Even if end_game raises, the user is stuck and needs
                # the response — log and continue rather than 500.
                _LOGGER.exception("force-reset: end_game raised; continuing anyway")

            ws_handler = data.get("ws_handler")
            if ws_handler:
                try:
                    await ws_handler.broadcast({"type": "game_ended"})
                    await ws_handler.broadcast_state()
                except Exception:
                    _LOGGER.exception("force-reset: WS broadcast raised; continuing")

        # #2036: drop the persisted setup blob so the reloading client really
        # comes up unconfigured. Failures here must not swallow the rest of the
        # recovery — the caller is stuck and the game is already ended.
        cleared_setup = False
        try:
            cleared_setup = await self.hass.async_add_executor_job(
                clear_setup, self.hass
            )
        except OSError:
            _LOGGER.exception("force-reset: clearing the setup blob failed; continuing")

            # Reset must also drop OUR persisted output settings. Upstream 4.2.0
        # (#2036) made reset installation-wide — it clears the server-side
        # setup blob so "reset means reset". Our game_output_settings Store is
        # invisible to that cleanup, so without this the pre-start hook would
        # faithfully re-apply the PRE-reset device/TTS/lights to the next
        # game — silently contradicting the reset the user just performed.
        with contextlib.suppress(Exception):
            from custom_components.beatify.server.library_views import (
                async_clear_game_output_settings,
            )

            await async_clear_game_output_settings(self.hass)
            _LOGGER.info("Force reset: cleared persisted output settings")

        return web.json_response(
            {
                "success": True,
                "ended_game_id": ended_game_id,
                "cleared_setup": cleared_setup,
            }
        )


class RematchGameView(HomeAssistantView):
    """Handle rematch game requests (Issue #108)."""

    url = "/beatify/api/rematch-game"
    name = "beatify:api:rematch-game"
    requires_auth = False  # auth handled in-handler so Companion path works (#1131)

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass

    async def post(self, request: web.Request) -> web.Response:
        """Start a rematch with current players."""
        if not is_authorized_http(request, self.hass):
            return _json_error("Unauthorized", 401, code="UNAUTHORIZED")
        from custom_components.beatify.game.state import GamePhase

        data = self.hass.data.get(DOMAIN, {})
        game_state = data.get("game")

        if not game_state or not game_state.game_id:
            return _json_error("No active game", 404, code="GAME_NOT_FOUND")

        # Rematch is safe without token -- game is already in END phase,
        # and the action just resets for a new game with the same players.
        # Token auth was blocking rematch from the player page (#535).
        if game_state.phase != GamePhase.END:
            return _json_error(
                "Can only rematch from END phase", 400, code="INVALID_PHASE"
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


_LIBRARY_YEAR_GATES = {
    # UI value -> minimum YearConfidence tier (see library.year_resolver).
    "strict": 4,  # EXTERNAL_PRIMARY: verified MusicBrainz years only (default)
    "balanced": 3,  # + EXTERNAL_SECONDARY: Deezer release years
    "tags_ok": 2,  # + TAG_STUDIO: studio-album tag years (least strict)
}
_LIBRARY_SIZE_MIN = 5
_LIBRARY_SIZE_MAX = 100
_LIBRARY_SIZE_DEFAULT = 30


_RECENT_KEY = "library_recent_uris"
_RECENT_SONGS_KEY = "library_recent_songs"
_RECENT_SONGS_CAP = 60
_RECENT_CAP = 400


def _recent_played_uris(hass: HomeAssistant) -> set[str]:
    return set(hass.data.get(DOMAIN, {}).get(_RECENT_KEY, []))


def remember_played_songs(hass: HomeAssistant, songs: list[dict[str, Any]]) -> None:
    """Record what a game actually played, newest first, for the panel.

    The recency list already tracks URIs to avoid repeats; this keeps the
    display fields alongside them so the Crate Digger panel can offer "fix
    this song" for what was just heard, without re-reading the pool.
    """
    store = hass.data.setdefault(DOMAIN, {})
    prev = store.get(_RECENT_SONGS_KEY, [])
    fresh = [
        {
            "uri": s_.get("uri_ma_library"),
            "title": s_.get("title"),
            "artist": s_.get("artist"),
            "year": s_.get("year"),
        }
        for s_ in songs
        if s_.get("uri_ma_library")
    ]
    seen: set[str] = set()
    combined: list[dict[str, Any]] = []
    for item in fresh + prev:
        uri = item.get("uri")
        if uri and uri not in seen:
            seen.add(uri)
            combined.append(item)
    store[_RECENT_SONGS_KEY] = combined[:_RECENT_SONGS_CAP]


def _remember_played_uris(hass: HomeAssistant, uris: list[str | None]) -> None:
    store = hass.data.setdefault(DOMAIN, {})
    prev = store.get(_RECENT_KEY, [])
    fresh = [u for u in uris if u]
    combined = (prev + fresh)[-_RECENT_CAP:]
    store[_RECENT_KEY] = combined


def _parse_library_config(
    library_config: dict[str, Any],
) -> tuple[int, int, int, int | None, list[str]]:
    """Sanitize the library settings from the request body. Pure.

    Returns (size, difficulty_slider, min_confidence, popularity_percent, genres).
    popularity_percent is 1..100 ("draw from the most-popular P%") or None.
    """
    library_config = library_config or {}
    try:
        size = int(library_config.get("size", _LIBRARY_SIZE_DEFAULT))
    except (TypeError, ValueError):
        size = _LIBRARY_SIZE_DEFAULT
    size = max(_LIBRARY_SIZE_MIN, min(_LIBRARY_SIZE_MAX, size))

    try:
        slider = int(library_config.get("difficulty", 50))
    except (TypeError, ValueError):
        slider = 50
    slider = max(0, min(100, slider))

    gate = _LIBRARY_YEAR_GATES.get(
        str(library_config.get("year_gate", "strict")), _LIBRARY_YEAR_GATES["strict"]
    )

    pop_percent: int | None = None
    if library_config.get("popularity_percent") is not None:
        try:
            pop_percent = max(1, min(100, int(library_config["popularity_percent"])))
        except (TypeError, ValueError):
            pop_percent = None

    genres_raw = library_config.get("genres")
    genres: list[str] = []
    if isinstance(genres_raw, list):
        genres = [str(g).strip() for g in genres_raw if str(g).strip()][:20]

    return size, slider, gate, pop_percent, genres


async def _generate_library_songs(
    hass: HomeAssistant, library_config: dict[str, Any]
) -> tuple[list[dict[str, Any]], web.Response | None]:
    """Sample a game's songs from the library pool. Returns (songs, error)."""
    from custom_components.beatify.library import async_generate_library_playlist

    # SERVER-AUTHORITATIVE settings: the panel persists every change to the
    # HA Store immediately, so the Store is always current. The client payload
    # is only a fallback for keys the Store doesn't have — a stale browser, an
    # unhydrated lobby page, or cached JS can no longer start a game with
    # silent defaults (observed: a "Rock"-filtered setup generating with
    # genres=None because the lobby page never mounts the settings panel).
    from custom_components.beatify.server.library_views import (
        async_load_library_settings,
    )

    stored = await async_load_library_settings(hass)
    effective = dict(library_config or {})
    effective.update(stored)  # stored wins over client payload
    size, slider, min_confidence, pop_percent, genres = _parse_library_config(effective)
    recent = _recent_played_uris(hass)
    try:
        playlist = await async_generate_library_playlist(
            hass,
            size=size,
            difficulty_slider=slider,
            popularity_percent=pop_percent,
            genres=genres or None,
            min_confidence=min_confidence,
            exclude_uris=recent,
        )
    except Exception as err:
        _LOGGER.exception("Library playlist generation failed")
        return [], _json_error(
            f"Library playlist generation failed: {err}",
            500,
            code="LIBRARY_GENERATION_FAILED",
        )

    if playlist is None:
        return [], _json_error(
            "Your library hasn't been scanned yet. Open Settings and run "
            "'Scan library' first (this takes a while on the first run).",
            400,
            code="LIBRARY_POOL_MISSING",
        )
    songs = playlist.get("songs", [])
    if not songs:
        return [], _json_error(
            "No songs in your library have a verified release year yet at this "
            "strictness. Re-scan with MusicBrainz enabled, or relax the "
            "year-accuracy setting.",
            400,
            code="LIBRARY_POOL_EMPTY",
        )
    for song in songs:
        song["_playlist_source"] = "library"
    _remember_played_uris(hass, [s.get("uri_ma_library") for s in songs])
    remember_played_songs(hass, songs)
    return songs, None


# Recently-played URIs across games, so a new library game doesn't recycle the
# same songs. Small ring buffer in hass.data; capped so it can't grow forever.
_RECENT_KEY = "library_recent_uris"
_RECENT_CAP = 400


async def _apply_tts_config(game_state: Any, tts_config: Any) -> bool:
    """Apply a frontend TTS config dict correctly, or disable on falsy.

    configure_tts takes the ENTITY ID as its first positional argument plus
    unpacked announce_* keywords — passing the raw dict "worked" silently and
    then crashed speak() at hass.states.get(<dict>) (the tts.py:81 frames).
    Mirrors the create endpoint's unpacking; single source for update +
    pre-start paths.
    """
    if not (tts_config and isinstance(tts_config, dict) and tts_config.get("enabled")):
        await game_state.disable_tts()
        return False
    entity_id = tts_config.get("entity_id", "")
    if not entity_id or not isinstance(entity_id, str):
        await game_state.disable_tts()
        return False
    kwargs: dict[str, Any] = {
        k: v
        for k, v in tts_config.items()
        if isinstance(k, str) and k.startswith("announce_") and isinstance(v, bool)
    }
    delay = tts_config.get("tts_pre_round_delay")
    if isinstance(delay, (int, float)):
        kwargs["tts_pre_round_delay"] = float(delay)
    await game_state.configure_tts(entity_id, **kwargs)
    return True


async def _apply_party_lights_config(game_state: Any, cfg: Any) -> bool:
    """Apply a frontend party-lights config dict correctly, or disable.

    configure_party_lights takes (entity_ids, intensity, light_mode,
    wled_presets) — the raw dict as first arg made Python iterate its KEYS as
    entity ids ("Party Lights started: 4 lights" = four config keys), then
    every phase change failed against nonexistent entities.
    """
    if not (cfg and isinstance(cfg, dict) and cfg.get("enabled")):
        await game_state.disable_party_lights()
        return False
    entities = cfg.get("entity_ids") or []
    if not isinstance(entities, list) or not entities:
        await game_state.disable_party_lights()
        return False
    await game_state.configure_party_lights(
        entities,
        cfg.get("intensity", "medium"),
        cfg.get("light_mode", "dynamic"),
        cfg.get("wled_presets"),
    )
    return True


class UpdateLobbyView(BeatifyAdminView):
    """Apply setting changes to an EXISTING lobby (pre-game).

    Rooms freeze their parameters at creation; any control still changeable
    while a lobby exists therefore lagged one game (confirmed on hardware for
    the media player: switching output devices only took effect on the NEXT
    game). Songs are covered by the pre_start_hook; this endpoint covers the
    device (extensible for further lobby-mutable settings). No-ops with
    {"updated": false} when there is no lobby-phase game, so the frontend can
    fire-and-forget on every change without tracking game state.
    """

    url = "/beatify/api/game/update-lobby"
    name = "beatify:api:game:update-lobby"
    requires_auth = False  # auth handled in-handler (Companion bypass, #1131)

    async def post(self, request: web.Request) -> web.Response:
        if not is_authorized_http(request, self.hass):
            return _json_error("Unauthorized", 401, code="UNAUTHORIZED")
        from custom_components.beatify.game.state import GamePhase

        data = self.hass.data.get(DOMAIN, {})
        game_state = data.get("game")
        if (
            not game_state
            or not game_state.game_id
            or game_state.phase
            not in (GamePhase.LOBBY, GamePhase.PLAYING, GamePhase.REVEAL)
        ):
            return web.json_response({"updated": False})

        try:
            body = await request.json()
        except ValueError:
            return _json_error("Invalid JSON", 400, code="INVALID_REQUEST")

        updated: list[str] = []
        media_player = body.get("media_player")
        if isinstance(media_player, str) and media_player:
            if not self.hass.states.get(media_player):
                return _json_error(
                    "Media player not found", 400, code="INVALID_REQUEST"
                )
            ent_reg = er.async_get(self.hass)
            entity_entry = ent_reg.async_get(media_player)
            platform = entity_entry.platform if entity_entry else "unknown"
            capabilities = get_platform_capabilities(platform)
            if not capabilities.get("supported"):
                return _json_error(
                    "Media player platform not supported",
                    400,
                    code="INVALID_REQUEST",
                )
            game_state.media_player = media_player
            game_state.platform = platform
            # The lazily-built MediaPlayerService captures entity/platform at
            # construction and recycles itself (see create_game's identical
            # reset + its comment) — without nulling it, playback keeps
            # routing to the OLD device.
            #
            # #2143: released, not nulled. This view permits a switch during
            # PLAYING and REVEAL, so the outgoing service can already hold the
            # old speaker's pre-game volume (#1516) and pre-game queue. Nulling
            # threw both away and left that speaker at party volume with
            # Beatify's track on it.
            game_state.release_media_player_service()
            # Upstream 4.2.0 (#1540) pre-warms the MediaPlayerService during
            # LOBBY. That task was scheduled at create with the OLD entity; if
            # it completes AFTER the null above it can reinstate a service
            # bound to the previous speaker, silently undoing this switch.
            # Cancel it and re-schedule for the new device using upstream's own
            # helpers (absent on older bases -> getattr no-ops).
            cancel_prewarm = getattr(game_state, "_cancel_prewarm", None)
            if callable(cancel_prewarm):
                with contextlib.suppress(Exception):
                    cancel_prewarm()
            reschedule = getattr(game_state, "schedule_media_player_prewarm", None)
            if callable(reschedule):
                with contextlib.suppress(Exception):
                    reschedule()
            updated.append("media_player")
            _LOGGER.info(
                "Lobby updated: media_player -> %s (platform %s)",
                media_player,
                platform,
            )

        # TTS + party-light configs are also frozen at creation (same class);
        # apply changes through upstream's own configure_* methods so a
        # settings tweak affects the CURRENT game, not the next one.
        if "tts" in body:
            with contextlib.suppress(Exception):
                applied = await _apply_tts_config(game_state, body.get("tts"))
                updated.append("tts")
                _LOGGER.info(
                    "Lobby/game updated: tts %s",
                    "configured" if applied else "disabled",
                )
        if "party_lights" in body:
            with contextlib.suppress(Exception):
                applied = await _apply_party_lights_config(
                    game_state, body.get("party_lights")
                )
                updated.append("party_lights")
                _LOGGER.info(
                    "Lobby/game updated: party lights %s",
                    "configured" if applied else "disabled",
                )

        if updated:
            from custom_components.beatify.server.library_views import (
                async_save_game_output_settings,
            )

            patch: dict[str, Any] = {}
            if "media_player" in updated:
                patch["media_player"] = body.get("media_player")
            if "tts" in updated:
                patch["tts"] = body.get("tts")
            if "party_lights" in updated:
                patch["party_lights"] = body.get("party_lights")
            with contextlib.suppress(Exception):
                await async_save_game_output_settings(self.hass, patch)

        return web.json_response({"updated": bool(updated), "fields": updated})


class StartGameplayView(BeatifyAdminView):
    """Handle start gameplay requests (transition LOBBY -> PLAYING)."""

    url = "/beatify/api/start-gameplay"
    name = "beatify:api:start-gameplay"
    # rc15 (#1131): see EndGameView above — without this override,
    # Companion-bypass requests get a HA-middleware 401 and the JSON parse
    # fails on the admin client, surfacing as "Network error".
    requires_auth = False

    async def post(self, request: web.Request) -> web.Response:
        """Start gameplay from lobby."""
        if not is_authorized_http(request, self.hass):
            return _json_error("Unauthorized", 401, code="UNAUTHORIZED")
        from custom_components.beatify.game.state import GamePhase

        data = self.hass.data.get(DOMAIN, {})
        game_state = data.get("game")

        if not game_state or not game_state.game_id:
            return _json_error("No active game", 404, code="GAME_NOT_STARTED")

        if game_state.phase != GamePhase.LOBBY:
            return _json_error("Game already started", 409, code="INVALID_PHASE")

        # Issue #827: Sudden Death requires >=3 players. Players join the LOBBY
        # *after* create_game (which clears sessions), so the floor can only be
        # enforced here, at the LOBBY->PLAYING transition. The wizard also
        # disables the toggle client-side; this is the server-side backstop for
        # direct API callers. Auto-disable rather than block the start so the
        # host isn't stuck — surface a warning instead.
        sudden_death_warning = None
        if game_state.sudden_death_mode:
            connected_count = sum(1 for p in game_state.players.values() if p.connected)
            if connected_count < 3:
                game_state.set_sudden_death(False)
                sudden_death_warning = (
                    "Sudden Death needs at least 3 players — starting without it."
                )

        # Set round end callback for broadcasting
        ws_handler = data.get("ws_handler")
        if ws_handler:
            game_state.set_round_end_callback(ws_handler.broadcast_state)
            # #1753: wire the terminal game-end one-shot so the unattended REVEAL
            # auto-advance final round records stats + runs the podium ceremony
            # through the same claim as the admin sockets.
            game_state.set_game_end_callback(
                functools.partial(_finalize_and_end, ws_handler, game_state)
            )
            # Set metadata update callback for fast transitions (Issue #42)
            game_state.set_metadata_update_callback(
                ws_handler.broadcast_metadata_update
            )

        # Start the first round
        success = await game_state.start_round()
        if not success:
            return _json_error("Failed to start - no songs", 500, code="START_FAILED")

        # Broadcast state to all connected players
        if ws_handler:
            await ws_handler.broadcast_state()

        response: dict[str, Any] = {"success": True, "phase": game_state.phase.value}
        if sudden_death_warning:  # Issue #827
            response["warnings"] = [sudden_death_warning]
            response["sudden_death_disabled"] = True
        return web.json_response(response)


class SetSuddenDeathView(BeatifyAdminView):
    """Toggle Sudden Death mode live during a game (Issue #827).

    The host flips Sudden Death on/off from the reveal-screen control bar.
    Turning it ON arms eliminations from the next round; turning it OFF stops
    further cuts (already-eliminated players stay out).
    """

    url = "/beatify/api/sudden-death"
    name = "beatify:api:sudden-death"
    # Match the other control-bar actions: auth handled in-handler so the
    # Companion-bypass path works (#1131).
    requires_auth = False

    async def post(self, request: web.Request) -> web.Response:
        """Set the live Sudden Death flag and rebroadcast state."""
        if not is_authorized_http(request, self.hass):
            return _json_error("Unauthorized", 401, code="UNAUTHORIZED")

        try:
            body = await request.json()
        except (ValueError, UnicodeDecodeError):
            return _json_error("Invalid JSON", 400, code="INVALID_REQUEST")

        enabled = bool(body.get("enabled", False))

        data = self.hass.data.get(DOMAIN, {})
        game_state = data.get("game")
        if not game_state or not game_state.game_id:
            return _json_error("No active game", 404, code="GAME_NOT_FOUND")

        new_state = game_state.set_sudden_death(enabled)

        ws_handler = data.get("ws_handler")
        if ws_handler:
            await ws_handler.broadcast_state()

        return web.json_response({"success": True, "sudden_death_mode": new_state})


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
        from custom_components.beatify.server.serializers import (
            build_game_status_response,
            get_game_state,
        )

        game_id = request.query.get("game")
        game_state = get_game_state(self.hass)

        return web.json_response(build_game_status_response(game_state, game_id))
