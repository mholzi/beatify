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

if TYPE_CHECKING:
    from aiohttp import web
    from homeassistant.core import HomeAssistant


_LOGGER = logging.getLogger(__name__)


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


def is_companion_trusted_request(request: web.Request, hass: HomeAssistant) -> bool:
    """Return True if an HTTP request comes from a trusted HA Android Companion.

    A request is "trusted" when ALL of these hold (#1357):
      0. The ``enable_companion_auth_bypass`` option is ON (default OFF). If the
         bypass is disabled, this returns False immediately — no UA/IP is ever
         trusted.
      1. The request is NOT a Home Assistant Cloud (Nabu Casa) tunnelled
         request. snitun terminates locally and would otherwise reach us from
         127.0.0.1; loopback removal (see ``_PRIVATE_NETS``) is the primary
         structural defense, this ``is_cloud_connection`` check is
         defense-in-depth for the HTTP path.
      2. User-Agent matches the HA Android Companion regex.
      3. Source IP is private (RFC1918 / ULA; loopback excluded — request did
         not cross the public internet and did not arrive via a local tunnel).
      4. (No header check — Companion's WebView does not reliably ship Bearer
         when ha-auth.js fails, and that's exactly the case we're bypassing.)
    """
    # #1357 gate: the whole bypass is opt-in and OFF by default.
    if not hass.data.get(DOMAIN, {}).get("companion_auth_bypass_enabled", False):
        return False

    # #1357 defense-in-depth: refuse the bypass for Nabu Casa cloud-tunnelled
    # requests. snitun terminates the tunnel locally, so request.remote would
    # be 127.0.0.1 — loopback removal already blocks that, but the cloud helper
    # also catches reverse-proxy/forwarded cases where remote was rewritten to
    # a private IP. Lazily imported because the cloud component may be absent.
    try:
        from homeassistant.components.cloud import is_cloud_connection

        if is_cloud_connection(hass):
            return False
    except Exception:  # noqa: BLE001 — cloud component unavailable / not a cloud context
        pass

    ua = request.headers.get("User-Agent")
    remote = request.remote
    ua_match = is_companion_ua(ua)
    ip_match = is_local_remote(remote)
    trusted = ua_match and ip_match
    # rc9 diagnostic: log every HTTP trust check so #1131 / #1120 reports can
    # be correlated with the actual UA + remote that reaches the server.
    # Remove once Companion auth lands stable.
    _LOGGER.debug(
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
    Unlike the HTTP path, we do NOT call ``is_cloud_connection`` here: that
    helper reads a request-scoped contextvar that is unreliable from a WS
    message handler (the message arrives long after the HTTP upgrade, off the
    original request context). We therefore rely on the enabled-gate plus the
    loopback removal in ``_PRIVATE_NETS`` (snitun/proxy requests arrive from
    127.0.0.1, which is no longer trusted) as the defense for the WS path.
    """
    # #1357 gate: the whole bypass is opt-in and OFF by default.
    if not hass.data.get(DOMAIN, {}).get("companion_auth_bypass_enabled", False):
        return False

    if not isinstance(meta, dict):
        _LOGGER.debug("[Companion-Debug] WS meta=None (no signature collected)")
        return False
    ua = meta.get("ua")
    remote = meta.get("remote")
    ua_match = is_companion_ua(ua)
    ip_match = is_local_remote(remote)
    trusted = ua_match and ip_match
    _LOGGER.debug(
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
                _LOGGER.debug(
                    "[Companion-Debug] HTTP path=%s bearer_valid=True (bypass not consulted)",
                    request.path,
                )
                return True
    if bearer_present:
        _LOGGER.debug(
            "[Companion-Debug] HTTP path=%s bearer_present=True bearer_valid=False (falling back to bypass)",
            request.path,
        )
    return is_companion_trusted_request(request, hass)


def extract_request_meta(request: web.Request) -> dict:
    """Pull the bits of an HTTP request the WS handler needs to re-evaluate trust."""
    return {
        "ua": request.headers.get("User-Agent"),
        "remote": request.remote,
    }
