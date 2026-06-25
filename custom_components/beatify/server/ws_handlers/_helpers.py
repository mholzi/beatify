"""Shared helpers for the WebSocket message handlers (#1588 split).

State-redaction and admin-authentication helpers used across the handler
submodules. Extracted verbatim from the former monolithic ``ws_handlers``
module — behavior is unchanged.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiohttp import web

from custom_components.beatify.game.state import GameState
from custom_components.beatify.server.companion_auth import is_companion_trusted_meta
from custom_components.beatify.server.serializers import redact_state_for_player

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from custom_components.beatify.server.websocket import BeatifyWebSocketHandler

_LOGGER = logging.getLogger(__name__)


async def _send_state_to(
    ws: web.WebSocketResponse, state_msg: dict, game_state: GameState
) -> None:
    """Send a ``state`` message to a single recipient, redacted for players.

    #1366: ``state`` frames carry the round's answers (admin_song year;
    song.artist/title in title_artist_mode). Only the spectator admin WS
    (``game_state._admin_ws``) may receive them unfiltered; every other
    connection — including an admin who joined as a *participant* — gets a
    redacted copy, matching the per-recipient filtering in
    ``BeatifyWebSocketHandler.broadcast``.
    """
    payload = state_msg
    if ws is not game_state._admin_ws:
        payload = redact_state_for_player(state_msg)
    await ws.send_json(payload)


# ---------------------------------------------------------------------------
# Authentication helper (#998)
# ---------------------------------------------------------------------------


def _is_ha_authenticated(
    handler: BeatifyWebSocketHandler,
    data: dict,
    ws: web.WebSocketResponse | None = None,
) -> bool:
    """Return True if the message is authorized to claim admin role.

    Two paths are accepted (#1131):

    1. **Bearer token via ``ha_token`` field.** The standard #998 path:
       client obtains an HA access token via OAuth (desktop) or the
       Companion ``externalAppV2`` bridge (rc5+ Android) and sends it.
       Validated against ``hass.auth.async_validate_access_token``.

    2. **HA Android Companion trust on local network.** When the OAuth and
       Companion-bridge paths both fail (the #1120/#1131 saga), this
       fallback inspects the *original HTTP upgrade request* stashed on
       ``ws.beatify_request_meta`` for the UA + RFC1918 signature of an HA
       Android Companion WebView. Same trust model as the HTTP helper in
       ``companion_auth.py``.

    rc6 (#1120 diagnostics): logs *why* path 1 was rejected at warning
    level. We log only the first 12 chars of the token (HA tokens are JWT
    so the header prefix is deterministic and not secret) plus the length
    and exception class.
    """
    token = data.get("ha_token")
    if not token or not isinstance(token, str):
        if _ws_companion_trusted(ws, handler.hass):
            _LOGGER.info(
                "[WS auth] admin_connect: ha_token missing — accepting via "
                "Companion bypass (UA+RFC1918 match on upgrade request)"
            )
            return True
        _LOGGER.warning(
            "[WS auth] admin_connect rejected: ha_token field missing or non-string "
            "(type=%s)",
            type(data.get("ha_token")).__name__,
        )
        return False
    try:
        result = handler.hass.auth.async_validate_access_token(token)
    except Exception as err:  # noqa: BLE001 — any decode/validation error means "no"
        if _ws_companion_trusted(ws, handler.hass):
            _LOGGER.info(
                "[WS auth] admin_connect: ha_token unparseable (%s) — accepting "
                "via Companion bypass",
                type(err).__name__,
            )
            return True
        _LOGGER.warning(
            "[WS auth] admin_connect rejected: validator raised %s (len=%d, prefix=%s)",
            type(err).__name__,
            len(token),
            token[:12],
        )
        return False
    if result is None:
        if _ws_companion_trusted(ws, handler.hass):
            _LOGGER.info(
                "[WS auth] admin_connect: ha_token did not resolve to a refresh "
                "token — accepting via Companion bypass"
            )
            return True
        _LOGGER.warning(
            "[WS auth] admin_connect rejected: HA auth manager returned None "
            "(len=%d, prefix=%s) — token is well-formed but no refresh_token in "
            "hass.auth matched it (HA restarted? user logged out? Companion "
            "token from a different HA install?)",
            len(token),
            token[:12],
        )
        return False
    return True


def _ws_companion_trusted(
    ws: web.WebSocketResponse | None, hass: HomeAssistant
) -> bool:
    """Check the request-meta stashed by ``BeatifyWebSocketHandler.handle``."""
    if ws is None:
        return False
    meta = getattr(ws, "beatify_request_meta", None)
    return is_companion_trusted_meta(meta, hass)
