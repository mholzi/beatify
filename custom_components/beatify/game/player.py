"""Player session management for Beatify."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiohttp import web


@dataclass
class PlayerSession:
    """Represents a connected player."""

    name: str
    ws: web.WebSocketResponse
    score: int = 0
    streak: int = 0
    connected: bool = True
    is_admin: bool = False
    joined_late: bool = False
    joined_at: float = field(default_factory=time.time)
