"""HA Android Companion auth-bypass helpers (#1131, #1120, #1114).

The HA Android Companion App ships a WebView that intercepts OAuth redirects
to ``/auth/authorize``, so the standard ha-auth.js token bootstrap dies on
"Invalid redirect URI" before any beatify endpoint sees a Bearer token. The
``externalAppV2`` bridge (rc5+) is the documented escape hatch, but several
Companion builds either don't expose it or expose it intermittently.

This module provides a narrowly-scoped bypass: when a request bears all
three indicators of an HA Android Companion WebView on the local network,
beatify treats it as authenticated even without a Bearer token. The bypass
is intentionally conservative — desktop browsers, iOS Companion, and any
internet-origin request fall through to the unchanged OAuth path.

#1357 hardening — the bypass is now **opt-in and OFF by default**, gated on
the ``enable_companion_auth_bypass`` integration option (stored live in
``hass.data[DOMAIN]["companion_auth_bypass_enabled"]``). Two further defenses
close the "internet-reachable bypass" hole:

  * **No loopback in the trusted set.** ``127.0.0.0/8`` / ``::1/128`` are
    deliberately excluded — a Companion WebView never connects from loopback,
    only reverse proxies and Nabu Casa's snitun tunnel terminator do (snitun
    hands requests to HA from 127.0.0.1). Removing loopback is the primary
    structural defense for the Nabu Casa setup.
  * **Cloud-connection refusal.** On the HTTP path we additionally consult
    HA's ``is_cloud_connection(hass)`` helper and refuse the bypass for
    cloud-tunnelled requests (defense-in-depth).

#3202 hardening — reverse proxies. A reverse proxy on a private address
(nginx add-on, Traefik, Caddy on the LAN) makes every forwarded internet
request look like it came from the LAN. The bypass is therefore refused when

  * the request carries a forwarding header (``X-Forwarded-For``,
    ``Forwarded``, ``X-Real-IP``, ``X-Forwarded-Host``), or
  * ``request.remote`` is one of HA's configured ``http.trusted_proxies``, or
  * the request is a Home Assistant Cloud connection.

This "via a proxy or tunnel" verdict is taken once, while the aiohttp request
(and HA's request contextvar) still exists: per request on the HTTP path, and
at the WebSocket upgrade for the WS path, where it is stored in the
connection's request meta. Both paths share :func:`is_proxied_request`.

Threat model: with the bypass enabled, the only added attack surface is
"anyone on the local network who can spoof an HA-Android-Companion
User-Agent gains the admin endpoints that #998 protects (lights inventory,
TTS trigger, host a game)". On a residential LAN this is roughly equivalent
to "the network is already trusted"; on a hostile LAN, leave
``enable_companion_auth_bypass`` off (the default).
"""

from __future__ import annotations

import ipaddress
import logging
import re
from typing import TYPE_CHECKING

from ..const import DOMAIN
from ..wire_debug import get_wire_logger

if TYPE_CHECKING:
    from aiohttp import web
    from homeassistant.core import HomeAssistant


_LOGGER = logging.getLogger(__name__)
# #1866: per-request / per-frame traffic goes to the opt-in wire logger so
# `custom_components.beatify: debug` stays usable (it used to cost 50-500x on
# the HTTP path). See custom_components/beatify/wire_debug.py.
_WIRE_LOGGER = get_wire_logger()


# Companion UAs vary by build — order between "Android" and the app name
# isn't stable ("Home Assistant/2026 (Android 14)" puts the app first;
# "Mozilla/5.0 (Linux; Android 13) HACompanion/..." puts Android first).
# Match each token independently.
_ANDROID_RE = re.compile(r"Android", re.IGNORECASE)
_HA_APP_RE = re.compile(r"Home\s?Assistant|HACompanion|Hass", re.IGNORECASE)

# #1357: loopback (127.0.0.0/8, ::1/128) is intentionally NOT in this set.
# A real HA Android Companion WebView never connects from loopback — only
# reverse proxies and Nabu Casa's snitun tunnel terminator hand requests to
# HA from 127.0.0.1. Trusting loopback was the core internet-reachable hole.
_PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("fc00::/7"),
]


def is_local_remote(remote: str | None) -> bool:
    """Return True if ``remote`` is an RFC1918 / ULA private address.

    Loopback is deliberately excluded (#1357) — see ``_PRIVATE_NETS``.

    aiohttp sometimes hands us an IPv6-mapped IPv4 ("::ffff:192.168.1.5") —
    ``ipaddress`` parses that as IPv6 but its ``.ipv4_mapped`` attribute
    exposes the underlying v4 address for range-checking.
    """
    if not isinstance(remote, str) or not remote:
        return False
    try:
        ip = ipaddress.ip_address(remote)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return any(ip in net for net in _PRIVATE_NETS)


def is_companion_ua(user_agent: str | None) -> bool:
    """Return True if ``user_agent`` looks like HA's Android Companion App."""
    if not isinstance(user_agent, str) or not user_agent:
        return False
    return bool(_ANDROID_RE.search(user_agent)) and bool(_HA_APP_RE.search(user_agent))


# #3202: headers a reverse proxy adds when it forwards a request. A real
# Companion WebView talking straight to HA never sends any of them.
_FORWARDING_HEADERS = (
    "X-Forwarded-For",
    "Forwarded",
    "X-Real-IP",
    "X-Forwarded-Host",
)


def _has_forwarding_headers(request: web.Request) -> bool:
    """Return True if ``request`` carries any reverse-proxy forwarding header."""
    headers = request.headers
    return any(name in headers for name in _FORWARDING_HEADERS)


def _trusted_proxy_networks(
    hass: HomeAssistant,
) -> list[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """Return HA's configured ``http.trusted_proxies`` as networks.

    The http integration keeps the parsed list on ``hass.http.trusted_proxies``.
    A missing integration, attribute or unparsable entry is skipped — an
    install without ``trusted_proxies`` simply has none.
    """
    http = getattr(hass, "http", None)
    raw = getattr(http, "trusted_proxies", None)
    if not isinstance(raw, (list, tuple, set, frozenset)):
        return []
    networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
    for entry in raw:
        if isinstance(entry, (ipaddress.IPv4Network, ipaddress.IPv6Network)):
            networks.append(entry)
            continue
        try:
            networks.append(ipaddress.ip_network(str(entry), strict=False))
        except ValueError:
            continue
    return networks


def _is_trusted_proxy(remote: str | None, hass: HomeAssistant) -> bool:
    """Return True if ``remote`` falls inside HA's ``trusted_proxies``."""
    if not isinstance(remote, str) or not remote:
        return False
    try:
        ip = ipaddress.ip_address(remote)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return any(
        ip.version == net.version and ip in net for net in _trusted_proxy_networks(hass)
    )


def _is_cloud_connection(hass: HomeAssistant) -> bool:
    """Return True if the current request is a Home Assistant Cloud connection.

    ``is_cloud_connection`` reads HA's request contextvar, so this is only
    meaningful while the aiohttp request is being handled. Lazily imported
    because the cloud component may be absent.
    """
    try:
        from homeassistant.components.cloud import is_cloud_connection

        return bool(is_cloud_connection(hass))
    except Exception:  # noqa: BLE001 — cloud component unavailable / not a cloud context
        return False


def is_proxied_request(request: web.Request, hass: HomeAssistant) -> bool:
    """Return True if ``request`` reached HA through a proxy or tunnel (#3202).

    True when any forwarding header is present, when ``request.remote`` is one
    of HA's ``trusted_proxies``, or when the request is a Home Assistant Cloud
    connection. Any of these means ``request.remote`` does not tell us where
    the client really is, so the Companion bypass must not apply.
    """
    return (
        _has_forwarding_headers(request)
        or _is_trusted_proxy(request.remote, hass)
        or _is_cloud_connection(hass)
    )


def is_companion_trusted_request(request: web.Request, hass: HomeAssistant) -> bool:
    """Return True if an HTTP request comes from a trusted HA Android Companion.

    A request is "trusted" when ALL of these hold (#1357):
      0. The ``enable_companion_auth_bypass`` option is ON (default OFF). If the
         bypass is disabled, this returns False immediately — no UA/IP is ever
         trusted.
      1. The request did NOT come through a proxy or tunnel (#3202, see
         :func:`is_proxied_request`): no forwarding headers, ``remote`` is not
         one of HA's ``trusted_proxies``, and it is not a Home Assistant Cloud
         (Nabu Casa) connection.
      2. User-Agent matches the HA Android Companion regex.
      3. Source IP is private (RFC1918 / ULA; loopback excluded — request did
         not cross the public internet and did not arrive via a local tunnel).
      4. (No header check — Companion's WebView does not reliably ship Bearer
         when ha-auth.js fails, and that's exactly the case we're bypassing.)
    """
    # #1357 gate: the whole bypass is opt-in and OFF by default.
    if not hass.data.get(DOMAIN, {}).get("companion_auth_bypass_enabled", False):
        return False

    # #1357 / #3202: refuse the bypass for anything that came through a proxy
    # or tunnel (forwarding headers, HA trusted_proxies, Nabu Casa). Behind a
    # reverse proxy on a private IP, request.remote is the proxy's LAN address
    # and says nothing about the real client.
    if is_proxied_request(request, hass):
        _WIRE_LOGGER.debug(
            "[Companion-Debug] HTTP path=%s proxied=True (bypass refused)",
            request.path,
        )
        return False

    ua = request.headers.get("User-Agent")
    remote = request.remote
    ua_match = is_companion_ua(ua)
    ip_match = is_local_remote(remote)
    trusted = ua_match and ip_match
    # #1662: demoted to DEBUG — these fire on every auth check and flood INFO logs.
    _WIRE_LOGGER.debug(
        "[Companion-Debug] HTTP path=%s ua=%r remote=%s ua_match=%s ip_match=%s trusted=%s",
        request.path,
        (ua[:200] if isinstance(ua, str) else ua),
        remote,
        ua_match,
        ip_match,
        trusted,
    )
    return trusted


def is_companion_trusted_meta(meta: dict | None, hass: HomeAssistant) -> bool:
    """Same check as :func:`is_companion_trusted_request` but for WebSocket meta.

    The WebSocket layer collects ``{ua, remote}`` from the incoming HTTP upgrade
    request and stashes it on the connection so message handlers can re-use the
    same trust decision.

    #1357: same opt-in gate first — if the bypass is disabled, never trust.

    #3202: the proxy/cloud verdict cannot be taken here — HA's request
    contextvar is gone by the time WS messages arrive. It is taken once at the
    HTTP upgrade by :func:`extract_request_meta` (the same
    :func:`is_proxied_request` as the HTTP path) and carried as
    ``meta["proxied"]``. Meta without that key counts as proxied, so the WS
    path fails closed.
    """
    # #1357 gate: the whole bypass is opt-in and OFF by default.
    if not hass.data.get(DOMAIN, {}).get("companion_auth_bypass_enabled", False):
        return False

    if not isinstance(meta, dict):
        _WIRE_LOGGER.debug("[Companion-Debug] WS meta=None (no signature collected)")
        return False
    if meta.get("proxied", True) is not False:
        _WIRE_LOGGER.debug(
            "[Companion-Debug] WS proxied=%r (bypass refused)", meta.get("proxied")
        )
        return False
    ua = meta.get("ua")
    remote = meta.get("remote")
    ua_match = is_companion_ua(ua)
    ip_match = is_local_remote(remote)
    trusted = ua_match and ip_match
    _WIRE_LOGGER.debug(
        "[Companion-Debug] WS ua=%r remote=%s ua_match=%s ip_match=%s trusted=%s",
        (ua[:200] if isinstance(ua, str) else ua),
        remote,
        ua_match,
        ip_match,
        trusted,
    )
    return trusted


def is_authorized_http(request: web.Request, hass: HomeAssistant) -> bool:
    """Return True if ``request`` may invoke a #998-protected endpoint.

    Two paths are accepted:
      - Standard HA Bearer: ``Authorization: Bearer <token>`` that
        ``hass.auth.async_validate_access_token`` resolves to a refresh token.
      - Companion bypass: see :func:`is_companion_trusted_request`.

    Views that previously set ``requires_auth = True`` flip to ``False`` and
    call this helper at the top of their handler. HA's middleware no longer
    short-circuits the request, so the Bearer check moves into application
    code — equivalent behaviour for the happy path, plus the Companion fallback.

    Synchronous: ``async_validate_access_token`` and ``is_companion_trusted_request``
    are both sync, so this helper does no awaiting and is a plain function.
    """
    auth = request.headers.get("Authorization", "")
    bearer_present = False
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token:
            bearer_present = True
            result = hass.auth.async_validate_access_token(token)
            if result is not None:
                _WIRE_LOGGER.debug(
                    "[Companion-Debug] HTTP path=%s bearer_valid=True (bypass not consulted)",
                    request.path,
                )
                return True
    if bearer_present:
        _WIRE_LOGGER.debug(
            "[Companion-Debug] HTTP path=%s bearer_present=True bearer_valid=False (falling back to bypass)",
            request.path,
        )
    return is_companion_trusted_request(request, hass)


def extract_request_meta(request: web.Request, hass: HomeAssistant) -> dict:
    """Pull the bits of an HTTP request the WS handler needs to re-evaluate trust.

    Called at the WebSocket upgrade, while the aiohttp request and HA's request
    contextvar still exist. ``proxied`` carries the #3202 proxy/cloud verdict
    so :func:`is_companion_trusted_meta` uses the same decision as the HTTP
    path. The opt-in gate is still checked per message, so toggling the
    option takes effect without a reconnect.
    """
    return {
        "ua": request.headers.get("User-Agent"),
        "remote": request.remote,
        "proxied": is_proxied_request(request, hass),
    }
