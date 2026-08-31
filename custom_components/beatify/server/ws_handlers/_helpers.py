"""Shared helpers for the WebSocket message handlers (#1588 split).

State-redaction and admin-authentication helpers used across the handler
submodules. Extracted verbatim from the former monolithic ``ws_handlers``
module — behavior is unchanged.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aiohttp import web

from custom_components.beatify.const import DOMAIN
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


async def finalize_and_end(
    handler: BeatifyWebSocketHandler,
    game_state: GameState,
    *,
    allow_playoff: bool = True,
) -> None:
    """Record game stats + run the game-end ceremony exactly once (#1702/#1753).

    The final-round terminal path is reachable from THREE places at the same
    time: the two admin-capable sockets (participant WS + spectator
    ``_admin_ws``) driving ``next_round``/``end_game``, and the unattended
    REVEAL auto-advance carrying the final round (#1753, wired via
    ``GameState.set_game_end_callback``). Gating on the handler's one-shot claim
    keyed by ``game_id`` makes ``finalize_game`` / ``record_game`` (double
    stats) and ``advance_to_end`` (double podium TTS) fire at most once per
    game. The loser skips straight to the broadcast its caller performs.

    #1754: the claim is taken BEFORE the side effects (``record_game`` storage
    I/O + ``advance_to_end``). If either raises, the claim is released so a
    retry can re-run the terminal sequence instead of stranding the game in
    REVEAL/PAUSED — then the error propagates to the caller.

    #1725: before claiming/finalizing, offer a finale sudden-death tiebreaker.
    When the host opted in and the game would end on a tie for first with
    unplayed songs left, ``maybe_start_finale_playoff`` eliminates the non-tied
    players and starts one more playoff round; the game stays in PLAYING and we
    return WITHOUT finalizing, so the caller re-broadcasts the live round. On a
    clear winner / 0 songs left / cap reached it's a no-op and the normal
    finalize path runs.
    """
    if allow_playoff and await game_state.maybe_start_finale_playoff():
        _LOGGER.info("Finale tiebreaker armed — playoff round started, not ending")
        return

    if not handler._claim_game_end(game_state.game_id):
        _LOGGER.debug("Game-end already claimed for %s — skipping", game_state.game_id)
        return

    try:
        stats_service = handler.hass.data.get(DOMAIN, {}).get("stats")
        if stats_service:
            game_summary = game_state.finalize_game()
            await stats_service.record_game(
                game_summary, difficulty=game_state.difficulty
            )
            _LOGGER.debug("Game stats recorded")

        await game_state.advance_to_end()
    except Exception:
        # #1754: release the claim so a retry re-runs the end sequence rather
        # than hitting "already claimed" and stranding the game in REVEAL.
        handler._release_game_end(game_state.game_id)
        raise
