"""Opt-in per-request / per-frame "wire" logging (#1866).

``custom_components.beatify: debug`` is the level we ask users for when we need
diagnostics. Two code paths emitted a DEBUG record for *every* HTTP request
(``[Companion-Debug]``) and *every* WebSocket frame (``[WS-Debug]``), and HA
writes log records synchronously on the event loop. Together with the
compatibility scan in :mod:`custom_components.beatify.services.media_player`
that made the documented diagnostics level slow Beatify's own HTTP path down by
50-500x and starved the server-side round timer (#1865) — i.e. turning on
logging changed the behaviour under investigation.

This module hands out a logger for that wire-level traffic which is **not**
enabled by ``custom_components.beatify: debug``. It carries an explicit level,
so it does not inherit the effective level of its ``custom_components.beatify``
ancestor; only naming it directly turns it on::

    logger:
      logs:
        custom_components.beatify.debug.wire: debug

Everything that is per-request or per-frame belongs here. Per-*game-event*
logging (a player joining, playback starting) stays on the normal module logger
— it is bounded by gameplay, not by poll frequency, and it is what users
actually need when they report a bug.
"""

from __future__ import annotations

import logging

#: Logger name users opt into for wire-level traffic.
WIRE_LOGGER_NAME = "custom_components.beatify.debug.wire"

#: Default level. Setting this explicitly is the whole point: a logger without
#: its own level inherits the nearest configured ancestor, so
#: ``custom_components.beatify: debug`` would switch the flood back on.
WIRE_DEFAULT_LEVEL = logging.INFO

_WIRE_LOGGER = logging.getLogger(WIRE_LOGGER_NAME)
_WIRE_LOGGER.setLevel(WIRE_DEFAULT_LEVEL)


def get_wire_logger() -> logging.Logger:
    """Return the shared wire-debug logger (see module docstring)."""
    return _WIRE_LOGGER
