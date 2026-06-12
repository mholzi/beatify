"""HTTP views for Beatify admin interface.

This module serves as the main entry point for all Beatify views.
It contains HTML-serving views and shared infrastructure, and re-exports
views from sub-modules for backward compatibility.
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
from ipaddress import ip_address
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlencode, urlsplit

from aiohttp import ClientError, ClientTimeout, web
from homeassistant.components.http import HomeAssistantView
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.beatify.const import DOMAIN
from custom_components.beatify.game.state import GamePhase
from custom_components.beatify.game.playlist import async_discover_playlists
from custom_components.beatify.server.base import (
    RateLimitMixin,
    _apply_cache_tokens,
    _get_html,
    _get_version,
    _json_error,
    _read_file,
)
from custom_components.beatify.server.companion_auth import is_authorized_http
from custom_components.beatify.server.serializers import (
    build_status_response,
)
from custom_components.beatify.services.lights import PartyLightsService
from custom_components.beatify.services.media_player import (
    album_art_signature_is_valid,
    async_get_media_players,
)

# Re-export game views
from custom_components.beatify.server.game_views import (  # noqa: F401
    EndGameView,
    ForceResetView,
    GameStatusView,
    RematchGameView,
    StartGameplayView,
    StartGameView,
)

# Re-export playlist views
from custom_components.beatify.server.playlist_views import (  # noqa: F401
    PlaylistRequestsView,
    SavePlaylistView,
)

# Re-export stats views
from custom_components.beatify.server.stats_views import (  # noqa: F401
    AnalyticsPageView,
    AnalyticsView,
    DashboardView,
    SongStatsView,
    StatsView,
    UsageView,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HTML-serving views (kept here -- they are tightly coupled to static assets)
# ---------------------------------------------------------------------------

# Entry-point HTML must never be cached by the browser. Otherwise the `?v=rcN`
# cache-busters on the referenced JS/CSS never get read — the browser serves a
# months-old admin.html from its own cache and the new RC is invisible until
# the user opens a private window. no-cache + no-store + must-revalidate is
# the belt-and-suspenders version; we want revalidation on every navigation.
_NO_CACHE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _html_response(text: str) -> web.Response:
    """Return an HTML response that browsers will always revalidate."""
    return web.Response(text=text, content_type="text/html", headers=_NO_CACHE_HEADERS)


class AdminView(HomeAssistantView):
    """Serve the admin page."""

    url = "/beatify/admin"
    name = "beatify:admin"
    # Served unauthenticated on purpose: a browser navigation carries no HA
    # bearer token, so the page itself must load before its JS can run the
    # Home Assistant login flow. The shell embeds no secrets — every admin
    # action and the admin token are obtained over authenticated requests
    # (see ha-auth.js), so an unauthenticated visitor gets an inert page (#998).
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the admin view."""
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:  # noqa: ARG002
        """Serve the admin HTML page as a static, secret-free shell (#998)."""
        html_path = Path(__file__).parent.parent / "www" / "admin.html"
        html_content = await _get_html(self.hass, html_path)
        if html_content is None:
            _LOGGER.error("Admin page not found: %s", html_path)
            return web.Response(text="Admin page not found", status=500)
        return _html_response(_apply_cache_tokens(html_content, self.hass))


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
        return _html_response(_apply_cache_tokens(html_content, self.hass))


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
        return _html_response(_apply_cache_tokens(html_content, self.hass))


# ---------------------------------------------------------------------------
# Auth flow (rc15+) — server-side OAuth, no browser POSTs
# ---------------------------------------------------------------------------
#
# Safari 18 (macOS Sequoia / iOS 18) silently refuses certain same-origin
# POSTs from the OAuth-callback page state — fetch (FormData and
# urlencoded), XHR, both /auth/token and /beatify/auth/exchange. Three
# RCs of frontend transport workarounds (rc11–rc14) failed because the
# browser was never the right layer to fix this. Chrome and other
# engines are unaffected.
#
# Solution: the browser only does GETs and redirects. The OAuth code
# exchange and refresh both run server-side, with tokens delivered via
# cookies. ``BeatifyAuthCallbackView`` is the new ``redirect_uri`` for
# ``/auth/authorize``; it exchanges the code over loopback HTTP and sets
# two cookies (JS-readable ``beatify_access`` + HttpOnly
# ``beatify_refresh``) before redirecting back to /beatify/admin.
# ``BeatifyAuthRefreshView`` handles silent refreshes the same way, via
# fetch-GET, so the frontend never needs to POST.
#
# Cookies: Path=/beatify (so they only ride along on Beatify requests),
# SameSite=Lax (enough for the same-origin OAuth redirect + fetch GET
# flows; tighter Strict would break the post-login redirect), and
# Secure when the page was loaded over HTTPS (so Nabu Casa users get
# the cookie-security upgrade for free, and LAN HTTP users still work).


_ACCESS_COOKIE = "beatify_access"
_REFRESH_COOKIE = "beatify_refresh"

# Belt + suspenders: HA access tokens are short (~30 min by default), but
# refresh tokens are long-lived. 30 days lines up with HA's own refresh-
# token rotation window and means a user who hits the admin once a month
# never has to re-do the full OAuth dance.
_REFRESH_COOKIE_MAX_AGE = 30 * 24 * 60 * 60


def _ssl_kwargs(hass: HomeAssistant) -> dict:
    """Build aiohttp ssl kwargs for the loopback /auth/token call.

    HA on HTTPS still listens on localhost only with its own cert. We
    don't verify (the cert almost certainly doesn't SAN 127.0.0.1) —
    no security loss because the call never leaves the process.
    """
    if getattr(hass.http, "ssl_certificate", None):
        return {"ssl": False}
    return {}


def _loopback_url(hass: HomeAssistant) -> str:
    """Compose the loopback URL for HA's own /auth/token."""
    scheme = "https" if getattr(hass.http, "ssl_certificate", None) else "http"
    return f"{scheme}://127.0.0.1:{hass.http.server_port}/auth/token"


def _origin_from_request(request: web.Request) -> str:
    """Return the scheme+host the browser sees, for client_id/redirect_uri.

    The browser sent ``/auth/authorize`` with client_id and redirect_uri
    derived from ``window.location.origin``; the exchange request must
    use byte-identical values (per RFC 6749 §4.1.3). Reconstruct from
    Forwarded headers when present (Nabu Casa terminates TLS upstream
    and proxies plain HTTP to HA, so request.scheme alone says "http").
    """
    forwarded_proto = request.headers.get("X-Forwarded-Proto")
    forwarded_host = request.headers.get("X-Forwarded-Host") or request.headers.get(
        "Host"
    )
    scheme = forwarded_proto or request.scheme
    host = forwarded_host or request.host
    return f"{scheme}://{host}"


def _is_secure_origin(request: web.Request) -> bool:
    """True if the browser loaded the page over HTTPS — drives cookie Secure."""
    forwarded_proto = request.headers.get("X-Forwarded-Proto")
    if forwarded_proto:
        return forwarded_proto.lower() == "https"
    return request.scheme == "https"


def _set_session_cookies(
    response: web.Response,
    request: web.Request,
    *,
    refresh_token: str | None,
) -> None:
    """Set the HttpOnly refresh cookie onto an outgoing response.

    #1369: the HA access token is NEVER written to a cookie. A JS-readable
    ``beatify_access`` cookie would let any XSS on a /beatify page exfiltrate
    a token that authorizes the whole HA REST + WebSocket API. The access
    token is instead returned only in the refresh endpoint's JSON body, where
    the frontend (ha-auth.js) holds it in a module-scoped variable for the
    page's lifetime and re-bootstraps it from this HttpOnly refresh cookie on
    every page load. The callback view sets only the refresh cookie; the
    frontend's first ``GET /beatify/auth/refresh`` then mints the access token.
    """
    secure = _is_secure_origin(request)
    # Defensive: wipe any legacy JS-readable access cookie an upgraded client
    # still carries, so a real HA token can't linger in document.cookie.
    response.del_cookie(_ACCESS_COOKIE, path="/beatify")
    if refresh_token is not None:
        response.set_cookie(
            _REFRESH_COOKIE,
            refresh_token,
            path="/beatify",
            max_age=_REFRESH_COOKIE_MAX_AGE,
            samesite="Lax",
            secure=secure,
            httponly=True,  # JS cannot read; only ever sent to refresh view
        )


def _clear_session_cookies(response: web.Response) -> None:
    """Wipe both cookies — call on refresh failure or explicit logout."""
    response.del_cookie(_ACCESS_COOKIE, path="/beatify")
    response.del_cookie(_REFRESH_COOKIE, path="/beatify")


async def _exchange_with_ha(
    hass: HomeAssistant, body: str
) -> tuple[int, dict | None, str]:
    """POST the urlencoded body to HA's loopback /auth/token.

    Returns ``(status, parsed_json_or_None, raw_text)``. ``parsed_json``
    is None when HA returned non-JSON (HTTP error pages, mostly), which
    callers should treat as an exchange failure.
    """
    session = async_get_clientsession(hass)
    try:
        async with session.post(
            _loopback_url(hass),
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=ClientTimeout(total=10),
            **_ssl_kwargs(hass),
        ) as resp:
            text = await resp.text()
            try:
                parsed = json.loads(text)
            except ValueError:
                parsed = None
            return resp.status, parsed, text
    except (ClientError, asyncio.TimeoutError) as err:
        _LOGGER.error("Loopback /auth/token call failed: %s", err)
        return 502, None, str(err)


class BeatifyAuthCallbackView(HomeAssistantView):
    """OAuth ``redirect_uri`` target — server-side code exchange.

    Replaces the rc11–rc14 frontend POST exchange path. The browser
    arrives here via ``/auth/authorize``'s redirect, hands us ``?code=``
    and ``?state=``; we exchange the code over loopback HTTP and set
    the two session cookies before redirecting to /beatify/admin (with
    state echoed so the frontend can CSRF-validate against its
    sessionStorage entry on the next load).

    Failures redirect to /beatify/admin?auth_error=<reason> so the
    frontend can surface a clean message instead of a silent loop.
    """

    url = "/beatify/auth/callback"
    name = "beatify:auth_callback"
    requires_auth = False  # this *is* the auth entry point

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the callback view."""
        self.hass = hass

    def _redirect_to_admin(
        self,
        request: web.Request,
        *,
        state: str | None = None,
        error: str | None = None,
    ) -> web.Response:
        """Build the post-exchange redirect back to the admin page."""
        params: list[tuple[str, str]] = []
        if state:
            params.append(("auth_state", state))
        if error:
            params.append(("auth_error", error))
        suffix = ("?" + urlencode(params)) if params else ""
        return web.HTTPFound(f"/beatify/admin{suffix}")

    async def get(self, request: web.Request) -> web.Response:
        """Handle the OAuth code redirect from HA."""
        code = request.query.get("code")
        state = request.query.get("state", "")
        if not code:
            return self._redirect_to_admin(request, error="missing_code")

        origin = _origin_from_request(request)
        # rc18: ha-auth.js's redirect_uri is /beatify/auth/callback again
        # (rc15 architecture restored — the rc16 detour was unnecessary
        # once the rc17 launcher started opening Beatify in external
        # Safari via target="_blank", so HA Companion's interception of
        # /auth/authorize is no longer a concern). client_id and
        # redirect_uri MUST match what ha-auth.js sent to /auth/authorize
        # per RFC 6749 §4.1.3.
        body = urlencode(
            {
                "grant_type": "authorization_code",
                "code": code,
                "client_id": f"{origin}/beatify/",
                "redirect_uri": f"{origin}/beatify/auth/callback",
            }
        )

        status, parsed, raw = await _exchange_with_ha(self.hass, body)
        if status != 200 or not parsed or not parsed.get("access_token"):
            _LOGGER.warning(
                "OAuth code exchange failed (status=%s body=%s)", status, raw[:200]
            )
            return self._redirect_to_admin(request, error="exchange_failed")

        response = self._redirect_to_admin(request, state=state)
        # #1369: only the HttpOnly refresh cookie is set here. The frontend
        # mints its in-memory access token via GET /beatify/auth/refresh on
        # the post-callback page load.
        _set_session_cookies(
            response,
            request,
            refresh_token=parsed.get("refresh_token"),
        )
        return response


class BeatifyAuthRefreshView(HomeAssistantView):
    """Silent refresh endpoint — keeps the frontend off ``/auth/token``.

    Reads the HttpOnly ``beatify_refresh`` cookie, posts the refresh
    grant to HA over loopback, and returns JSON with the fresh access
    token so ha-auth.js can populate its in-memory cache (#1369: the
    access token is never written to a cookie). On refresh failure both
    cookies are wiped — the
    frontend then redirects to ``/auth/authorize`` for a full re-login.
    """

    url = "/beatify/auth/refresh"
    name = "beatify:auth_refresh"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the refresh view."""
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:
        """Refresh the access token using the HttpOnly refresh cookie."""
        refresh_token = request.cookies.get(_REFRESH_COOKIE)
        if not refresh_token:
            response = web.json_response({"error": "no_refresh_token"}, status=401)
            _clear_session_cookies(response)
            return response

        origin = _origin_from_request(request)
        body = urlencode(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": f"{origin}/beatify/",
            }
        )
        status, parsed, raw = await _exchange_with_ha(self.hass, body)
        if status != 200 or not parsed or not parsed.get("access_token"):
            _LOGGER.info("Refresh failed (status=%s) — clearing session", status)
            response = web.json_response(
                {"error": "refresh_failed", "ha_status": status}, status=401
            )
            _clear_session_cookies(response)
            return response

        # #1369: the fresh access token is returned ONLY in the JSON body —
        # the frontend caches it in memory, never in a cookie. HA's
        # refresh-token grant does NOT return a new refresh_token (the
        # long-lived one stays in the HttpOnly cookie), so no Set-Cookie is
        # needed here beyond wiping any legacy JS-readable access cookie.
        response = web.json_response(
            {
                "access_token": parsed["access_token"],
                "expires_in": parsed.get("expires_in", 1800),
            },
            headers={"Cache-Control": "no-store"},
        )
        _set_session_cookies(
            response,
            request,
            # Don't overwrite the long-lived refresh cookie.
            refresh_token=None,
        )
        return response


class SwJsView(HomeAssistantView):
    """Serve sw.js from /beatify/sw.js so the SW can claim /beatify/ scope (#780).

    The file on disk lives under www/ and is also reachable via /beatify/static/sw.js,
    but browsers limit a service worker's max scope to its own path. Registering
    /beatify/static/sw.js can only control /beatify/static/..., which defeats the
    purpose. Serving the same bytes at /beatify/sw.js lets the wider /beatify/
    scope register cleanly without needing a Service-Worker-Allowed header dance.
    """

    url = "/beatify/sw.js"
    name = "beatify:sw"
    requires_auth = False  # Must load unauthenticated on first admin/player visit

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the sw.js view."""
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:  # noqa: ARG002
        """Serve the service worker script."""
        sw_path = Path(__file__).parent.parent / "www" / "sw.js"
        try:
            content = await self.hass.async_add_executor_job(_read_file, sw_path)
        except OSError:
            _LOGGER.error("Service worker script not found: %s", sw_path)
            return web.Response(text="Service worker not found", status=500)
        # Must be served as JS. No-cache so CACHE_VERSION bumps propagate without
        # waiting for HTTP cache to expire on the SW bootstrap itself. Tokens
        # ({{ASSET_VER}}) are substituted at serve time (#1266).
        return web.Response(
            text=_apply_cache_tokens(content, self.hass),
            content_type="application/javascript",
            headers=_NO_CACHE_HEADERS,
        )


# ---------------------------------------------------------------------------
# API views (kept here -- lightweight and closely tied to core status)
# ---------------------------------------------------------------------------


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
            version=_get_version(self.hass),
            media_players=media_players,
            playlists=playlists,
        )

        return web.json_response(status)


class CapabilitiesView(HomeAssistantView):
    """Advertise which HA capabilities Beatify can light up in the wizard."""

    url = "/beatify/api/capabilities"
    name = "beatify:api:capabilities"
    # requires_auth=False + in-handler check so HA Android Companion (which
    # can't reliably attach a Bearer token, see companion_auth.py) is still
    # served while desktop browsers without a valid token are still rejected.
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the capabilities view."""
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:
        """Return flags the wizard's Step 4 uses to gate toggles."""
        if not is_authorized_http(request, self.hass):
            return _json_error("Unauthorized", 401, code="UNAUTHORIZED")
        light_count = len(self.hass.states.async_all("light"))
        tts_services = self.hass.services.async_services().get("tts", {})
        return web.json_response(
            {
                "has_lights": light_count > 0,
                "light_count": light_count,
                "has_tts": bool(tts_services),
                "tts_service_count": len(tts_services),
            }
        )


class LightsView(HomeAssistantView):
    """API endpoint for available light entities (#331)."""

    url = "/beatify/api/lights"
    name = "beatify:api:lights"
    requires_auth = False  # auth handled in-handler so Companion path works (#1131)

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the lights view."""
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:
        """Return available light entities with capabilities."""
        if not is_authorized_http(request, self.hass):
            return _json_error("Unauthorized", 401, code="UNAUTHORIZED")
        lights = []
        for state in self.hass.states.async_all("light"):
            # Hide unreachable lights — an "unavailable" entity can't be
            # controlled by anyone, so listing it only invites dead selections
            # that silently do nothing during the game.
            if state.state == "unavailable":
                continue
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


class TtsEntitiesView(HomeAssistantView):
    """API endpoint for available TTS entities (#1073).

    Backs the dropdown picker that replaced the legacy free-text
    ``tts.*`` entity_id field in the admin TTS panel and the setup
    wizard's voice-announcements card. Listing real entities removes
    the typo class that was the most common TTS setup failure.
    """

    url = "/beatify/api/tts-entities"
    name = "beatify:api:tts-entities"
    requires_auth = False  # auth handled in-handler so Companion path works (#1131)

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the TTS entities view."""
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:
        """Return registered TTS entities sorted by friendly name."""
        if not is_authorized_http(request, self.hass):
            return _json_error("Unauthorized", 401, code="UNAUTHORIZED")
        entities = [
            {
                "entity_id": state.entity_id,
                "friendly_name": state.attributes.get("friendly_name", state.entity_id),
            }
            for state in self.hass.states.async_all("tts")
        ]
        entities.sort(key=lambda e: e["friendly_name"].lower())
        return web.json_response({"entities": entities})


class AlbumArtView(HomeAssistantView):
    """Same-origin proxy for media-player album art (#933).

    Music Assistant exposes ``entity_picture`` as an absolute URL on the MA
    server's LAN address (e.g. ``http://192.168.x.x:8095/imageproxy?...``). A
    player who joined via the nabu.casa remote URL is on a public origin, so
    the browser's Private Network Access policy blocks the LAN request and
    album art never loads. This view re-fetches the image server-side — HA can
    reach the LAN — and re-serves it same-origin under ``/beatify/api/albumart``.
    """

    url = "/beatify/api/albumart"
    name = "beatify:api:albumart"
    requires_auth = False  # player browsers are unauthenticated

    # Cap the re-served image so a hostile/huge upstream can't exhaust memory.
    _MAX_BYTES = 5 * 1024 * 1024

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the album-art proxy view."""
        self.hass = hass

    async def get(self, request: web.Request) -> web.Response:
        """Fetch the upstream image and re-serve it same-origin (#933, hardened #1356).

        The endpoint is unauthenticated (player browsers have no token), so it
        must not be usable as a server-side request forge. Defences:

        * **HMAC signature** — only URLs the integration itself produced (via
          ``proxy_album_art``) carry a valid ``sig``; everything else is 403.
          This is the primary SSRF guard.
        * **Host allow-list** — loopback, link-local (incl. the
          ``169.254.169.254`` cloud-metadata endpoint), multicast and reserved
          ranges are refused. RFC1918 private addresses stay allowed because
          that is exactly where the Music Assistant LAN server lives (#933).
        * **No redirects**, a **read-size cap** and an **``image/*``
          content-type check** so the proxy can only ever return a bounded image.
        """
        raw_url = request.query.get("url", "")
        signature = request.query.get("sig", "")
        if not raw_url.startswith(("http://", "https://")):
            return web.Response(status=400, text="invalid url")
        if not album_art_signature_is_valid(raw_url, signature):
            _LOGGER.warning("Album-art proxy rejected an unsigned/forged URL")
            return web.Response(status=403, text="forbidden")

        host = urlsplit(raw_url).hostname
        if not host or not await self._host_is_allowed(host):
            _LOGGER.warning("Album-art proxy refused a disallowed host")
            return web.Response(status=403, text="forbidden")

        session = async_get_clientsession(self.hass)
        try:
            async with session.get(
                raw_url,
                timeout=ClientTimeout(total=10),
                allow_redirects=False,
            ) as resp:
                if resp.status != 200:
                    return web.Response(status=502, text="upstream fetch failed")
                content_type = resp.headers.get("Content-Type", "")
                if not content_type.startswith("image/"):
                    return web.Response(status=415, text="not an image")
                declared = resp.headers.get("Content-Length")
                if declared is not None and declared.isdigit():
                    if int(declared) > self._MAX_BYTES:
                        return web.Response(status=413, text="image too large")
                body = bytearray()
                async for chunk in resp.content.iter_chunked(65536):
                    body += chunk
                    if len(body) > self._MAX_BYTES:
                        return web.Response(status=413, text="image too large")
        except (ClientError, asyncio.TimeoutError):
            _LOGGER.warning("Album-art proxy fetch failed")
            return web.Response(status=502, text="upstream fetch failed")

        return web.Response(
            body=bytes(body),
            content_type=content_type,
            headers={"Cache-Control": "public, max-age=86400"},
        )

    async def _host_is_allowed(self, host: str) -> bool:
        """Reject hosts that resolve to loopback/link-local/reserved ranges (#1356)."""
        try:
            infos = await self.hass.async_add_executor_job(
                socket.getaddrinfo, host, None
            )
        except OSError:
            return False
        for info in infos:
            addr = info[4][0]
            try:
                ip = ip_address(addr.split("%")[0])
            except ValueError:
                return False
            if (
                ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_unspecified
                or ip.is_reserved
            ):
                return False
        return True


class PreviewLightsView(HomeAssistantView):
    """Trigger a party lights preview for selected entities (#408)."""

    url = "/beatify/api/preview-lights"
    name = "beatify:api:preview-lights"
    requires_auth = False  # auth handled in-handler so Companion path works (#1131)

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass

    async def post(self, request: web.Request) -> web.Response:
        """Run a ~5s party lights preview on the given entity_ids."""
        if not is_authorized_http(request, self.hass):
            return _json_error("Unauthorized", 401, code="UNAUTHORIZED")
        try:
            body = await request.json()
        except (ValueError, UnicodeDecodeError):
            return web.json_response({"error": "Invalid JSON"}, status=400)

        entity_ids = body.get("entity_ids", [])
        if not entity_ids:
            return web.json_response({"error": "No entity_ids provided"}, status=400)

        game_state = self.hass.data.get(DOMAIN, {}).get("game")
        if game_state and game_state.phase in (GamePhase.PLAYING, GamePhase.REVEAL):
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


class TtsTestView(RateLimitMixin, HomeAssistantView):
    """Send a test TTS announcement to verify setup."""

    url = "/beatify/api/tts-test"
    name = "beatify:api:tts-test"
    requires_auth = False  # auth handled in-handler so Companion path works (#1131)

    MAX_TTS_MESSAGE_LENGTH = 500

    RATE_LIMIT_REQUESTS = 5
    RATE_LIMIT_WINDOW = 60  # seconds

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize view."""
        self.hass = hass
        self._init_rate_limits()

    async def post(self, request: web.Request) -> web.Response:
        """Speak a test message via TTS.

        Modern HA ``tts.speak`` requires both a TTS provider entity and a
        media player to route through (#793). Caller passes both:
        ``entity_id`` (the TTS entity) and ``media_player_entity_id``.
        """
        if not is_authorized_http(request, self.hass):
            return _json_error("Unauthorized", 401, code="UNAUTHORIZED")
        client_ip = request.remote or "unknown"
        if not self._check_rate_limit(client_ip):
            return _json_error("Too many requests", 429, code="RATE_LIMITED")
        try:
            body = await request.json()
        except (ValueError, UnicodeDecodeError):
            return web.json_response({"error": "Invalid JSON"}, status=400)

        entity_id = body.get("entity_id", "")
        media_player_entity_id = body.get("media_player_entity_id", "")
        message = body.get("message", "")[: self.MAX_TTS_MESSAGE_LENGTH]
        if not entity_id or not message:
            return web.json_response(
                {"error": "entity_id and message required"}, status=400
            )
        if not media_player_entity_id:
            return web.json_response(
                {
                    "error": (
                        "media_player_entity_id required — TTS needs a speaker "
                        "to route through. Pick a media player in the wizard "
                        "first, then test TTS."
                    )
                },
                status=400,
            )

        tts_state = self.hass.states.get(entity_id)
        if not tts_state or tts_state.domain != "tts":
            return web.json_response(
                {
                    "error": (
                        f"{entity_id!r} is not a TTS entity. Expected "
                        "something like 'tts.google_translate_say' or "
                        "'tts.google_gemini_tts'."
                    )
                },
                status=400,
            )
        mp_state = self.hass.states.get(media_player_entity_id)
        if not mp_state or mp_state.domain != "media_player":
            return web.json_response(
                {"error": f"{media_player_entity_id!r} is not a media player"},
                status=400,
            )

        try:
            await self.hass.services.async_call(
                "tts",
                "speak",
                {
                    "entity_id": entity_id,
                    "media_player_entity_id": media_player_entity_id,
                    "message": message,
                },
                blocking=False,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.exception(
                "TTS test failed (tts=%s, media_player=%s)",
                entity_id,
                media_player_entity_id,
            )
            return web.json_response({"error": "TTS call failed"}, status=500)

        return web.json_response({"ok": True})
