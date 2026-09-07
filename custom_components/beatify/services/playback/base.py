"""The interface every platform answers to (#2636).

Before this, ``MediaPlayerService`` carried Music Assistant, Sonos and Alexa in
one class body, so a Sonos change was one indentation level away from the Music
Assistant path. A strategy is that platform and nothing else: it is handed a
:class:`~.context.PlayerContext`, it answers :meth:`play`, and it says on its
own behalf what it can remember of the host's queue.

Adding a platform (Plex, Jellyfin) is a new file plus one entry in
``_STRATEGIES`` — no existing method is cut open.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .context import PlayerContext

# Timeout for play_song service calls (seconds) - prevents long hangs (#179).
# Shared by the two strategies that make a single blocking play_media call;
# Music Assistant runs on its own, much longer budget (see MA_PLAYBACK_TIMEOUT).
PLAYBACK_TIMEOUT = 8.0


class PlaybackStrategy(ABC):
    """One platform's answer to "play this song on this speaker"."""

    #: platform identifiers from the entity registry that this strategy serves.
    #: The dispatch table in :mod:`..playback` is built from these, so a
    #: platform is claimed in exactly one place — the strategy that implements
    #: it — instead of in an ``if self._platform ==`` chain.
    platforms: ClassVar[tuple[str, ...]] = ()

    # -- What the admin needs to describe this platform (#2713) --------------
    # These used to live a second time in ``PLATFORM_CAPABILITIES``, which is
    # the duplication #2678 names: the capability table and this dispatch table
    # both answered "which platforms exist", and nothing kept them in step.
    # The table is now derived from the strategies, so a platform says these
    # things once, next to the code that plays on it.

    #: How this platform is asked to play — ``"uri"`` or ``"text_search"``.
    playback_method: ClassVar[str] = "uri"

    #: One-line setup requirement shown next to the speaker in the admin.
    setup_warning: ClassVar[str | None] = None

    #: A caveat about how well playback works, when there is one.
    setup_caveat: ClassVar[str | None] = None

    def __init__(self, context: PlayerContext) -> None:
        self.context = context

    # Convenience aliases. Properties rather than copies so a context that is
    # re-pointed (tests do this) stays authoritative.
    @property
    def _hass(self) -> HomeAssistant:
        return self.context.hass

    @property
    def _entity_id(self) -> str:
        return self.context.entity_id

    @property
    def _provider(self) -> str:
        return self.context.provider

    @property
    def last_attempted_uri(self) -> str | None:
        """The URI actually handed to the player for the most recent attempt."""
        return self.context.last_attempted_uri

    @last_attempted_uri.setter
    def last_attempted_uri(self, value: str | None) -> None:
        self.context.last_attempted_uri = value

    @property
    def last_failure_reason(self) -> str | None:
        """Why the most recent attempt failed — ``"unavailable"``, ``"error"``,
        ``"wrong_track"`` — or None when it succeeded. Read by
        ``game/state_lifecycle.py`` to decide whether a failure counts against
        ``MAX_SONG_RETRIES``."""
        return self.context.last_failure_reason

    @last_failure_reason.setter
    def last_failure_reason(self, value: str | None) -> None:
        self.context.last_failure_reason = value

    @abstractmethod
    async def play(self, song: dict[str, Any]) -> bool:
        """Play one song on this platform.

        Args:
            song: song dict with ``_resolved_uri``, ``artist``, ``title``.

        Returns:
            True if playback started, False otherwise. Timeouts and
            ``HomeAssistantError`` are allowed to escape — the service shell
            owns the analytics and the log line for those.
        """

    async def capture_queue(self) -> dict[str, Any] | None:
        """What the speaker was playing before Beatify claimed it (#2143).

        Returns:
            ``None`` when the platform cannot report it — the default, and the
            reason the shell then remembers nothing and hands nothing back.
            ``{}`` means "asked, and there was nothing playing". A dict is the
            track, its position, shuffle and repeat mode.
        """
        return None
