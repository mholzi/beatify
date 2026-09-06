"""Per-platform playback, and the one place that picks between them (#2636).

``MediaPlayerService`` answers "how do I play this?" with an
``if self._platform ==`` chain inside a 2300-line class, so Music Assistant,
Sonos and Alexa share one class body, one test file and one blast radius.

This package is where each platform is getting its own module behind one
interface. It starts with what they have in common: the speaker
(:class:`~.context.PlayerContext`) and the contract
(:class:`~.base.PlaybackStrategy`).
"""

from __future__ import annotations

from .base import PLAYBACK_TIMEOUT, PlaybackStrategy
from .context import PlayerContext
from .uris import convert_uri_for_ma, uri_match_tokens

__all__ = [
    "PLAYBACK_TIMEOUT",
    "PlaybackStrategy",
    "PlayerContext",
    "convert_uri_for_ma",
    "uri_match_tokens",
]
