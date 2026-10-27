"""Home Assistant actions that drive a running game (#3306).

``beatify.pause_game`` / ``resume_game`` / ``next_round`` / ``end_game``.

**Same handlers as the host's phone.** Each action calls the admin websocket's
own sub-handler (``admin_pause_game`` and friends) rather than re-implementing
the game logic. Those handlers already carry every guard the host's buttons
rely on — a server-owned pause cannot be relabelled as "door", ``end_game``
resolves an open title/artist vote first, the final ``next_round`` runs the
podium exactly once — and they finish with the same ``broadcast_state``, so a
pause from an automation shows the reason chip on the TV, the players' phones
and the admin page alike. The handlers report a refusal by sending an
``error`` frame to the socket they were given; here they are given a
collector instead, and the first error becomes a ``ServiceValidationError``
with a translated message.

**Who may call them.** These actions control the game for the whole room, so
they follow the admin websocket's rule: the caller must be a Home Assistant
administrator. In Home Assistant terms (the same rule as
``homeassistant.helpers.service.async_register_admin_service``):

* ``call.context.user_id`` is set and the user is an admin → allowed.
* ``call.context.user_id`` is set and the user is not an admin → ``Unauthorized``.
* ``call.context.user_id`` is set but no such user exists → ``UnknownUser``.
* ``call.context.user_id`` is None → allowed. That is a call Home Assistant
  itself makes: an automation, a script run by a trigger, the doorbell. Only
  an administrator can create or edit an automation, so the admin decision was
  made when the automation was written. Refusing these would make the
  doorbell use case — the reason the actions exist — impossible.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, cast

import voluptuous as vol
from homeassistant.exceptions import (
    ServiceValidationError,
    Unauthorized,
    UnknownUser,
)

from .const import (
    ATTR_REASON,
    DOMAIN,
    SERVICE_END_GAME,
    SERVICE_NEXT_ROUND,
    SERVICE_PAUSE_GAME,
    SERVICE_PAUSE_REASONS,
    SERVICE_RESUME_GAME,
    SERVICES,
)
from .server.ws_handlers.admin import (
    admin_end_game,
    admin_next_round,
    admin_pause_game,
    admin_resume_game,
)

if TYPE_CHECKING:
    from aiohttp import web
    from homeassistant.core import HomeAssistant, ServiceCall

    from .game.state import GameState
    from .server.websocket import BeatifyWebSocketHandler

_LOGGER = logging.getLogger(__name__)

AdminHandler = Callable[
    ["BeatifyWebSocketHandler", "web.WebSocketResponse", dict, "GameState"],
    Awaitable[None],
]

#: Refusals the admin handlers can send, by ``message_key``, mapped to the
#: translation keys under ``exceptions`` in translations/*.json.
_REFUSAL_TRANSLATION_KEYS: dict[str, str] = {
    "UNKNOWN_PAUSE_REASON": "unknown_pause_reason",
    "PAUSE_NOT_HOST": "pause_not_host",
    "NO_ROUND_TO_PAUSE": "no_round_to_pause",
    "PAUSE_FAILED": "pause_failed",
    "NOT_PAUSED": "not_paused",
    "RESUME_FAILED": "resume_failed",
    "CANNOT_ADVANCE": "cannot_advance",
    "CANNOT_END_NOW": "cannot_end_now",
}

PAUSE_GAME_SCHEMA = vol.Schema(
    {vol.Optional(ATTR_REASON): vol.In(list(SERVICE_PAUSE_REASONS))}
)
EMPTY_SCHEMA = vol.Schema({})


class _RefusalCollector:
    """Stands in for the admin socket and keeps the handler's error frames."""

    def __init__(self) -> None:
        self.errors: list[dict[str, Any]] = []

    async def send_json(self, data: Any, **_kwargs: Any) -> None:
        if isinstance(data, dict) and data.get("type") == "error":
            self.errors.append(data)


async def async_require_admin(hass: HomeAssistant, call: ServiceCall) -> None:
    """Refuse a call made by a Home Assistant user who is not an admin.

    A call without a user (``context.user_id is None``) is Home Assistant
    acting on its own — an automation or a triggered script — and is allowed.
    See the module docstring for why.
    """
    user_id = call.context.user_id
    if user_id is None:
        return
    user = await hass.auth.async_get_user(user_id)
    if user is None:
        raise UnknownUser(context=call.context, user_id=user_id)
    if not user.is_admin:
        raise Unauthorized(context=call.context, user_id=user_id)


def _translated(key: str, **placeholders: str) -> ServiceValidationError:
    return ServiceValidationError(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders=placeholders or None,
    )


async def _async_run_admin_action(
    hass: HomeAssistant,
    call: ServiceCall,
    sub_handler: AdminHandler,
    data: dict[str, Any],
) -> None:
    """Authorize, then run one admin sub-handler and surface its refusal."""
    await async_require_admin(hass, call)

    domain_data = hass.data.get(DOMAIN)
    game_state = domain_data.get("game") if isinstance(domain_data, dict) else None
    ws_handler = (
        domain_data.get("ws_handler") if isinstance(domain_data, dict) else None
    )
    if game_state is None or ws_handler is None or not game_state.game_id:
        raise _translated("no_active_game")

    collector = _RefusalCollector()
    await sub_handler(
        ws_handler, cast("web.WebSocketResponse", collector), data, game_state
    )
    if collector.errors:
        error = collector.errors[0]
        message_key = str(error.get("message_key") or "")
        translation_key = _REFUSAL_TRANSLATION_KEYS.get(message_key)
        if translation_key is None:
            raise _translated(
                "action_refused", message=str(error.get("message") or message_key)
            )
        raise _translated(translation_key)
    _LOGGER.info(
        "Beatify action %s.%s ran (user=%s)",
        call.domain,
        call.service,
        call.context.user_id or "automation",
    )


def async_register_services(hass: HomeAssistant) -> None:
    """Register the four game-control actions."""

    async def _pause(call: ServiceCall) -> None:
        short = call.data.get(ATTR_REASON)
        data: dict[str, Any] = {}
        if short is not None:
            reason = SERVICE_PAUSE_REASONS.get(short)
            if reason is None:
                raise _translated("unknown_pause_reason")
            data["reason"] = reason
        await _async_run_admin_action(hass, call, admin_pause_game, data)

    async def _resume(call: ServiceCall) -> None:
        await _async_run_admin_action(hass, call, admin_resume_game, {})

    async def _next(call: ServiceCall) -> None:
        await _async_run_admin_action(hass, call, admin_next_round, {})

    async def _end(call: ServiceCall) -> None:
        await _async_run_admin_action(hass, call, admin_end_game, {})

    hass.services.async_register(
        DOMAIN, SERVICE_PAUSE_GAME, _pause, schema=PAUSE_GAME_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_RESUME_GAME, _resume, schema=EMPTY_SCHEMA
    )
    hass.services.async_register(DOMAIN, SERVICE_NEXT_ROUND, _next, schema=EMPTY_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_END_GAME, _end, schema=EMPTY_SCHEMA)


def async_unregister_services(hass: HomeAssistant) -> None:
    """Remove the actions again when the config entry unloads."""
    for service in SERVICES:
        hass.services.async_remove(DOMAIN, service)
