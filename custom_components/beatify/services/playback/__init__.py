"""Per-platform playback, and the one place that picks between them (#2636).

``MediaPlayerService`` used to answer "how do I play this?" with an
``if self._platform ==`` chain inside a 2300-line class, so Music Assistant,
Sonos and Alexa shared one class body, one test file and one blast radius.

Now each platform is a :class:`~.base.PlaybackStrategy` in its own module, and
the choice between them happens exactly once, in :func:`build_strategy`. A
strategy claims its platform identifiers itself (``platforms`` on the class),
so adding Plex or Jellyfin is a new module plus one entry in ``_STRATEGIES`` —
no existing method is cut open, and nothing about the other platforms is
touched.

The service shell keeps what is genuinely not per-platform: timeouts and
analytics, volume save/restore, the metadata wait, the pre-flight check and the
game-lifecycle bookkeeping around the queue snapshot.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .alexa import AlexaStrategy
from .base import PLAYBACK_TIMEOUT, PlaybackStrategy
from .context import PlayerContext
from .music_assistant import MusicAssistantStrategy
from .queue_restore import MaQueueRestorer
from .sonos import SonosStrategy
from .uris import convert_uri_for_ma, uri_match_tokens

if TYPE_CHECKING:
    pass

#: Every platform Beatify can play on. Order is irrelevant — a platform
#: identifier belongs to exactly one strategy, which the assertion below keeps
#: true at import time.
_STRATEGIES: tuple[type[PlaybackStrategy], ...] = (
    MusicAssistantStrategy,
    SonosStrategy,
    AlexaStrategy,
)

_BY_PLATFORM: dict[str, type[PlaybackStrategy]] = {}
for _strategy in _STRATEGIES:
    for _platform in _strategy.platforms:
        if _platform in _BY_PLATFORM:  # pragma: no cover - guards a typo
            raise RuntimeError(f"two strategies claim platform {_platform!r}")
        _BY_PLATFORM[_platform] = _strategy
del _strategy, _platform


def build_strategy(context: PlayerContext) -> PlaybackStrategy | None:
    """The dispatch point — the only place a platform name picks an implementation.

    Args:
        context: the speaker to play on, carrying its platform identifier.

    Returns:
        The strategy for that platform, or None when Beatify cannot play on it
        (Cast without Music Assistant, an unknown entity type). The caller logs
        that; deciding it is this function's whole job.
    """
    strategy = _BY_PLATFORM.get(context.platform)
    return strategy(context) if strategy else None


def supported_platforms() -> tuple[str, ...]:
    """Every platform identifier some strategy answers to."""
    return tuple(_BY_PLATFORM)


def strategy_for_platform(platform: str) -> type[PlaybackStrategy] | None:
    """The strategy class that claims ``platform``, or None (#2713/#2678).

    The class-level answer to :func:`build_strategy`'s per-speaker one, so the
    admin can describe a platform ("plays by URI", "needs Spotify linked in the
    Sonos app") without constructing a strategy for a speaker nobody picked.
    ``PLATFORM_CAPABILITIES`` used to answer that from a second, hand-kept
    table, and its ``cast: supported: False`` row said exactly what
    ``build_strategy`` returning None says.
    """
    return _BY_PLATFORM.get(platform)


__all__ = [
    "PLAYBACK_TIMEOUT",
    "AlexaStrategy",
    "MaQueueRestorer",
    "MusicAssistantStrategy",
    "PlaybackStrategy",
    "PlayerContext",
    "SonosStrategy",
    "build_strategy",
    "convert_uri_for_ma",
    "strategy_for_platform",
    "supported_platforms",
    "uri_match_tokens",
]
