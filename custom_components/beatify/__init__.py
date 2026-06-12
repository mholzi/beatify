"""
Custom integration to integrate Beatify with Home Assistant.

Beatify is a party game integration that works with Music Assistant
to play music guessing games.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from homeassistant.components.frontend import (
    async_register_built_in_panel,
    async_remove_panel,
)

from .analytics import AnalyticsStorage
from .const import DOMAIN
from .game.playlist import (
    async_discover_playlists,
    async_ensure_playlist_directory,
)
from .game.service import GameService
from .game.state import GameState
from .server import async_register_static_paths
from .server.views import (
    AdminView,
    AlbumArtView,
    AnalyticsPageView,
    AnalyticsView,
    BeatifyAuthCallbackView,
    BeatifyAuthRefreshView,
    CapabilitiesView,
    DashboardView,
    EndGameView,
    ForceResetView,
    GameStatusView,
    LauncherView,
    LightsView,
    PreviewLightsView,
    TtsEntitiesView,
    TtsTestView,
    PlayerView,
    PlaylistRequestsView,
    SavePlaylistView,
    SwJsView,
    RematchGameView,
    SongStatsView,
    StartGameplayView,
    StartGameView,
    StatsView,
    StatusView,
    UsageView,
)
from .server.websocket import BeatifyWebSocketHandler
from .services.media_player import async_get_media_players
from .services.stats import StatsService

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

# hass.data key (outside DOMAIN, so it survives async_unload_entry popping
# hass.data[DOMAIN]) guarding one-time HTTP route registration. aiohttp routes
# cannot be unregistered, so views/WS/static paths must be registered exactly
# once per HA run — re-registering on a config-entry reload would shadow the
# new handlers with stale duplicates (#1364).
_ROUTES_REGISTERED = f"{DOMAIN}_routes_registered"


def _read_manifest_version() -> str:
    """Read the integration version from manifest.json (executor-safe).

    Single source of truth for the version label shown in the admin footer
    and reported via /beatify/api/status. Replaces the previously-hardcoded
    `_VERSION` constant in server/base.py that drifted out of sync whenever
    the version-bump.yml workflow failed to run (#784).
    """
    manifest_path = Path(__file__).parent / "manifest.json"
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8")).get(
            "version", "unknown"
        )
    except (OSError, ValueError):
        # Defensive: a malformed install shouldn't crash setup. The fallback
        # value is also what _get_version() returns when hass.data isn't yet
        # populated, so this stays consistent.
        return "unknown"


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Beatify from a config entry."""
    _LOGGER.debug("Setting up Beatify integration")

    # Initialize domain data storage
    hass.data.setdefault(DOMAIN, {})

    # Read version from manifest.json once at setup (#784). Done in executor
    # because HA 2026.2+ flags blocking I/O at module level — but doing it
    # here at setup time, off the event loop, keeps things clean.
    version = await hass.async_add_executor_job(_read_manifest_version)
    _LOGGER.debug("Beatify version: %s", version)

    # Ensure playlist directory exists
    playlist_dir = await async_ensure_playlist_directory(hass)

    # Discover media players and playlists
    media_players = await async_get_media_players(hass)
    playlists = await async_discover_playlists(hass)

    _LOGGER.info(
        "Found %d media players, %d playlists",
        len(media_players),
        len(playlists),
    )

    # Initialize game state
    game_state = GameState()
    game_state.set_hass(hass)

    # Initialize stats service (Story 14.4)
    stats_service = StatsService(hass)
    await stats_service.load()
    _LOGGER.debug(
        "Stats service initialized: %d games played", stats_service.games_played
    )

    # Initialize analytics storage (Story 19.1)
    analytics = AnalyticsStorage(hass)
    await analytics.load()
    _LOGGER.debug("Analytics initialized: %d games recorded", analytics.total_games)

    # Connect analytics to stats service for unified data collection
    stats_service.set_analytics(analytics)

    # Connect stats service to game state for performance tracking (Story 14.4)
    game_state.set_stats_service(stats_service)

    # Initialize WebSocket handler
    ws_handler = BeatifyWebSocketHandler(hass)

    # Set up round end callback for timer expiry (Story 4.5)
    game_state.set_round_end_callback(ws_handler.broadcast_state)

    # Set up metadata update callback for fast transitions (Issue #42)
    game_state.set_metadata_update_callback(ws_handler.broadcast_metadata_update)

    # Connect analytics to websocket handler for error recording (Story 19.1)
    ws_handler.set_analytics(analytics)

    # Issue #603/#609: Create GameService facade
    game_service = GameService(hass, game_state)

    # Store discovery results and game infrastructure
    hass.data[DOMAIN] = {
        "entry_id": entry.entry_id,
        "version": version,  # #784 — single source of truth from manifest.json
        "media_players": media_players,
        "playlists": playlists,
        "playlist_dir": str(playlist_dir),
        "game": game_state,
        "game_service": game_service,
        "ws_handler": ws_handler,
        "stats": stats_service,
        "analytics": analytics,
    }

    # Issue #441: Forward sensor and binary_sensor platforms
    await hass.config_entries.async_forward_entry_setups(
        entry, ["sensor", "binary_sensor"]
    )

    # Register HTTP views, the WebSocket route, and static paths exactly ONCE
    # per HA run (#1364). aiohttp's router cannot unregister resources, and its
    # dispatcher resolves to the FIRST matching resource — so re-registering on
    # a config-entry reload (unload + setup) would leave stale handlers serving
    # while the freshly-wired game state's callbacks point at the new, empty
    # handler. All views resolve their state from hass.data at request time, and
    # the WS route below dispatches to the *current* handler in hass.data, so a
    # single registration keeps working across reloads.
    if not hass.data.get(_ROUTES_REGISTERED):
        hass.http.register_view(AdminView(hass))
        hass.http.register_view(LauncherView(hass))
        # Safari 18 /auth/token workaround — server-side OAuth handling, the
        # frontend never POSTs to auth endpoints (rc15+).
        hass.http.register_view(BeatifyAuthCallbackView(hass))
        hass.http.register_view(BeatifyAuthRefreshView(hass))
        hass.http.register_view(StatusView(hass))
        hass.http.register_view(CapabilitiesView(hass))
        hass.http.register_view(LightsView(hass))  # Issue #331
        hass.http.register_view(AlbumArtView(hass))  # Issue #933 — remote album art
        hass.http.register_view(PreviewLightsView(hass))  # Issue #408
        hass.http.register_view(TtsEntitiesView(hass))  # Issue #1073
        hass.http.register_view(TtsTestView(hass))
        hass.http.register_view(StartGameView(hass))
        hass.http.register_view(StartGameplayView(hass))
        hass.http.register_view(EndGameView(hass))
        hass.http.register_view(
            ForceResetView(hass)
        )  # #777 follow-up — stuck-state escape hatch
        hass.http.register_view(RematchGameView(hass))  # Issue #108
        hass.http.register_view(PlayerView(hass))
        hass.http.register_view(
            SwJsView(hass)
        )  # #780 — SW at /beatify/sw.js for /beatify/ scope
        hass.http.register_view(GameStatusView(hass))
        hass.http.register_view(DashboardView(hass))
        hass.http.register_view(StatsView(hass))
        hass.http.register_view(AnalyticsView(hass))
        hass.http.register_view(AnalyticsPageView(hass))
        hass.http.register_view(SongStatsView(hass))  # Story 19.7
        hass.http.register_view(PlaylistRequestsView(hass))  # Story 44
        hass.http.register_view(SavePlaylistView(hass))  # #1057
        hass.http.register_view(UsageView(hass))  # v3.3 Playlist Hub local stats

        # Register WebSocket endpoint via a stable dispatch closure that
        # resolves the *current* handler from hass.data at call time (#1364).
        # Binding ws_handler.handle directly would pin the route to the handler
        # created in THIS setup; after a reload the new game state's callbacks
        # would target a new handler while clients kept landing in the old one's
        # (now empty) connection set, freezing round-end broadcasts.
        async def _ws_dispatch(request):
            handler = hass.data.get(DOMAIN, {}).get("ws_handler")
            if handler is None:
                from aiohttp import web  # noqa: PLC0415

                return web.Response(status=503, text="Beatify not ready")
            return await handler.handle(request)

        hass.http.app.router.add_get("/beatify/ws", _ws_dispatch)

        # Register static file paths
        await async_register_static_paths(hass)

        hass.data[_ROUTES_REGISTERED] = True
        _LOGGER.debug("Beatify HTTP routes registered (once per HA run)")
    else:
        _LOGGER.debug(
            "Beatify HTTP routes already registered this HA run — skipping "
            "re-registration on reload (#1364)"
        )

    # Register sidebar panel (Story 10.3)
    # Points to launcher page which opens game in a new tab (fullscreen, no HA chrome)
    async_register_built_in_panel(
        hass,
        component_name="iframe",
        sidebar_title="Beatify",
        sidebar_icon="mdi:music-circle",
        frontend_url_path="beatify",
        config={"url": "/beatify/launcher"},
        require_admin=False,
    )
    _LOGGER.debug("Beatify sidebar panel registered")

    _LOGGER.info("Beatify integration setup complete")
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading Beatify integration")

    # Issue #441: Unload sensor and binary_sensor platforms.
    # Issue #1392: gate cleanup on the platform-unload result and propagate it.
    # If a platform unload fails, leave the panel and hass.data[DOMAIN] in place
    # so HA does not treat the entry as fully unloaded while entities (and their
    # _game_state callbacks) still exist.
    unload_ok = await hass.config_entries.async_unload_platforms(
        entry, ["sensor", "binary_sensor"]
    )

    if unload_ok:
        # Remove sidebar panel (Story 10.3)
        try:
            async_remove_panel(hass, "beatify")
            _LOGGER.debug("Beatify sidebar panel removed")
        except KeyError:
            _LOGGER.debug("Beatify sidebar panel was not registered, skipping removal")

        # #1391: tear down the live game infrastructure BEFORE popping hass.data,
        # otherwise running game tasks/timers and open WebSockets keep operating on
        # an orphaned GameState/handler (and race a fresh GameState after reload —
        # two timers driving one media player). Best-effort so a teardown error here
        # never blocks the unload.
        domain_data = hass.data.get(DOMAIN, {})
        game_state = domain_data.get("game")
        if game_state is not None:
            try:
                game_state.async_shutdown()
            except Exception:  # noqa: BLE001
                _LOGGER.warning(
                    "Error shutting down game state on unload", exc_info=True
                )
        ws_handler = domain_data.get("ws_handler")
        if ws_handler is not None:
            try:
                await ws_handler.async_close_all()
            except Exception:  # noqa: BLE001
                _LOGGER.warning(
                    "Error closing WebSocket connections on unload", exc_info=True
                )

        # Clean up domain data
        if DOMAIN in hass.data:
            domain_data = hass.data.pop(DOMAIN)
            # Flush any pending debounced analytics error save before teardown (#1388)
            analytics = domain_data.get("analytics")
            if analytics is not None:
                await analytics.async_shutdown()

        _LOGGER.info("Beatify integration unloaded")
    else:
        _LOGGER.warning(
            "Beatify platform unload failed; leaving panel and domain data in place"
        )

    return unload_ok
