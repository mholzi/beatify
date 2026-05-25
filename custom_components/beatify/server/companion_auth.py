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

Threat model: the bypass adds no new attack surface beyond "anyone on the
local network who can spoof an HA-Android-Companion User-Agent gains the
admin endpoints that #998 protects (lights inventory, TTS trigger, host a
game)". On a residential LAN this is roughly equivalent to "the network is
already trusted"; on a hostile LAN, leave ``enable_companion_auth_bypass``
off in the integration config.
"""

from __future__ import annotations

import ipaddress
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiohttp import web
    from homeassistant.core import HomeAssistant


# Companion UAs vary by build — order between "Android" and the app name
# isn't stable ("Home Assistant/2026 (Android 14)" puts the app first;
# "Mozilla/5.0 (Linux; Android 13) HACompanion/..." puts Android first).
# Match each token independently.
_ANDROID_RE = re.compile(r"Android", re.IGNORECASE)
_HA_APP_RE = re.compile(r"Home\s?Assistant|HACompanion|Hass", re.IGNORECASE)

_PRIVATE_NETS = [
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("::1/128"),
]


def is_local_remote(remote: str | None) -> bool:
    """Return True if ``remote`` is an RFC1918 / loopback / ULA address.

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


def is_companion_trusted_request(request: web.Request) -> bool:
    """Return True if an HTTP request comes from a trusted HA Android Companion.

    A request is "trusted" when ALL three hold:
      1. User-Agent matches the HA Android Companion regex.
      2. Source IP is private/loopback (request did not cross the public internet).
      3. (No header check — Companion's WebView does not reliably ship Bearer
         when ha-auth.js fails, and that's exactly the case we're bypassing.)
    """
    return is_companion_ua(request.headers.get("User-Agent")) and is_local_remote(
        request.remote
    )


def is_companion_trusted_meta(meta: dict | None) -> bool:
    """Same check as :func:`is_companion_trusted_request` but for WebSocket meta.

    The WebSocket layer collects ``{ua, remote}`` from the incoming HTTP upgrade
    request and stashes it on the connection so message handlers can re-use the
    same trust decision.
    """
    if not isinstance(meta, dict):
        return False
    return is_companion_ua(meta.get("ua")) and is_local_remote(meta.get("remote"))


async def is_authorized_http(request: web.Request, hass: HomeAssistant) -> bool:
    """Return True if ``request`` may invoke a #998-protected endpoint.

    Two paths are accepted:
      - Standard HA Bearer: ``Authorization: Bearer <token>`` that
        ``hass.auth.async_validate_access_token`` resolves to a refresh token.
      - Companion bypass: see :func:`is_companion_trusted_request`.

    Views that previously set ``requires_auth = True`` flip to ``False`` and
    call this helper at the top of their handler. HA's middleware no longer
    short-circuits the request, so the Bearer check moves into application
    code — equivalent behaviour for the happy path, plus the Companion fallback.
    """
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token:
            result = hass.auth.async_validate_access_token(token)
            if result is not None:
                return True
    return is_companion_trusted_request(request)


def extract_request_meta(request: web.Request) -> dict:
    """Pull the bits of an HTTP request the WS handler needs to re-evaluate trust."""
    return {
        "ua": request.headers.get("User-Agent"),
        "remote": request.remote,
    }
