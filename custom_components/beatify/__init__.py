"""
Custom integration to integrate Beatify with Home Assistant.

Beatify is a party game integration that works with Music Assistant
to play music guessing games.
"""

from __future__ import annotations

import functools
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from homeassistant.components.frontend import (
    async_register_built_in_panel,
    async_remove_panel,
)
from homeassistant.helpers.event import async_track_time_interval

from .analytics import AnalyticsStorage
from .const import (
    CONF_ENABLE_COMPANION_AUTH_BYPASS,
    DEFAULT_ENABLE_COMPANION_AUTH_BYPASS,
    DOMAIN,
    ROUND_SUPERVISOR_INTERVAL_SECONDS,
)
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
    MixPlaylistView,
    SavePlaylistView,
    SwJsView,
    RematchGameView,
    SetSuddenDeathView,
    SongStatsView,
    StartGameplayView,
    StartGameView,
    StatsView,
    StatusView,
    SetupView,
    UsageView,
)
from .server.websocket import BeatifyWebSocketHandler
from .server.ws_handlers.admin import _finalize_and_end
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

    # hass.data[DOMAIN] is assigned wholesale below once discovery + game
    # infrastructure are built, so an early setdefault here is redundant (#1402
    # B6). The only reader before that assignment is _read_manifest_version,
    # which doesn't touch hass.data.

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

    # #1753: wire the terminal game-end one-shot so the unattended REVEAL
    # auto-advance final round records stats + runs the podium ceremony through
    # the same claim as the admin sockets (no double record / double podium TTS).
    game_state.set_game_end_callback(
        functools.partial(_finalize_and_end, ws_handler, game_state)
    )

    # Set up metadata update callback for fast transitions (Issue #42)
    game_state.set_metadata_update_callback(ws_handler.broadcast_metadata_update)

    # Connect analytics to websocket handler for error recording (Story 19.1)
    ws_handler.set_analytics(analytics)

    # Issue #603/#609: Create GameService facade
    game_service = GameService(hass, game_state)

    # #1357: Companion auth-bypass opt-in. Read once at setup; the auth helper
    # in server/companion_auth.py reads this live from hass.data per request,
    # so the options-update listener below can flip it without a full reload.
    companion_auth_bypass_enabled = entry.options.get(
        CONF_ENABLE_COMPANION_AUTH_BYPASS, DEFAULT_ENABLE_COMPANION_AUTH_BYPASS
    )

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
        "companion_auth_bypass_enabled": companion_auth_bypass_enabled,
    }

    # #1357: refresh the bypass flag in place when the options change. No full
    # reload is needed — companion_auth.py reads hass.data live per request.
    entry.async_on_unload(entry.add_update_listener(_async_update_options))

    # #1865: server-side round backstop. The round timer is a single asyncio
    # task owned by the round; if it is cancelled, raises, or blocks in the
    # time-up announcement, nothing on the server notices and the game sits on
    # PLAYING. The only rescue was a countdown running in a player's browser,
    # which a TV-only setup or a locked phone does not provide.
    #
    # This tick is deliberately owned by the config entry rather than by the
    # game: it must outlive whatever went wrong inside the round. It runs for
    # the life of the entry and costs a phase comparison when no round is in
    # flight, which is cheaper than starting and stopping it around games —
    # and the start/stop wiring would itself be something that can fail to run.
    entry.async_on_unload(
        async_track_time_interval(
            hass,
            functools.partial(_async_supervise_round, hass),
            timedelta(seconds=ROUND_SUPERVISOR_INTERVAL_SECONDS),
        )
    )

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
        hass.http.register_view(SetupView(hass))  # #1663 — server-side setup flag
        hass.http.register_view(LightsView(hass))  # Issue #331
        hass.http.register_view(AlbumArtView(hass))  # Issue #933 — remote album art
        hass.http.register_view(PreviewLightsView(hass))  # Issue #408
        hass.http.register_view(TtsEntitiesView(hass))  # Issue #1073
        hass.http.register_view(TtsTestView(hass))
        hass.http.register_view(StartGameView(hass))
        hass.http.register_view(StartGameplayView(hass))
        hass.http.register_view(SetSuddenDeathView(hass))  # Issue #827
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
        hass.http.register_view(MixPlaylistView(hass))  # #1538 — Smart Playlist Mixer
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


async def _async_supervise_round(
    hass: HomeAssistant, _now: datetime | None = None
) -> None:
    """Periodic tick: end a round whose own timer failed to end it (#1865).

    Resolves the game from ``hass.data`` on every tick rather than closing over
    it, so a config-entry reload that swaps in a fresh ``GameState`` cannot
    leave this driving the old one.

    Errors are swallowed with a log. ``async_track_time_interval`` keeps firing
    after a raising callback, but a round that is already stuck should not also
    be producing an unhandled-exception traceback every two seconds.
    """
    domain_data = hass.data.get(DOMAIN)
    if not isinstance(domain_data, dict):
        return
    game_state = domain_data.get("game")
    if game_state is None:
        return
    try:
        await game_state.force_end_round_if_overdue()
    except Exception:  # noqa: BLE001
        _LOGGER.warning("Round backstop failed to end an overdue round", exc_info=True)


async def _async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Refresh in-place state when the integration options change (#1357).

    Currently this only mirrors the ``enable_companion_auth_bypass`` toggle into
    ``hass.data[DOMAIN]``. The auth helper reads that value live per request, so
    flipping the option takes effect immediately without reloading the entry.
    """
    domain_data = hass.data.get(DOMAIN)
    if not isinstance(domain_data, dict):
        return
    domain_data["companion_auth_bypass_enabled"] = entry.options.get(
        CONF_ENABLE_COMPANION_AUTH_BYPASS, DEFAULT_ENABLE_COMPANION_AUTH_BYPASS
    )
    _LOGGER.debug(
        "Beatify options updated: companion_auth_bypass_enabled=%s",
        domain_data["companion_auth_bypass_enabled"],
    )


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
            # Flush any pending debounced per-round stats save before teardown (#1708)
            stats = domain_data.get("stats")
            if stats is not None:
                await stats.async_shutdown()

        _LOGGER.info("Beatify integration unloaded")
    else:
        _LOGGER.warning(
            "Beatify platform unload failed; leaving panel and domain data in place"
        )

    return unload_ok
