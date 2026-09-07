"""Protocols for game service dependencies — avoids circular imports (#465).

#2638: the domain package no longer builds its own Home Assistant services.
``GameState`` receives a :class:`GameOutputFactories` bundle at construction
time; the composition root (``custom_components/beatify/__init__.py``, and the
defensive fallback in ``server/game_views.py``) fills it via
``services.factories.ha_service_factories``, which is the only place that knows
the concrete ``services.*`` classes exist.

A caller that passes no bundle — every game-logic unit test — gets a
``GameState`` with no output backends at all: the media player, party lights and
TTS announcements are simply absent, which is exactly what those code paths
already guard for (``if self._media_player_service``, ``if self._party_lights``,
``if not self._tts_service``). Tests that DO want an output pass a fake factory
instead of mocking Home Assistant.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class MediaPlayerProtocol(Protocol):
    """Interface that GameState expects from a media-player service.

    #2711: this list is the whole contract, so it has to name everything the
    domain actually calls. It did not: ``seek_forward``,
    ``get_playback_state`` and the two failure-report attributes were called
    without being declared, and a fake written against the Protocol therefore
    raised on them. The reveal auto-advance swallows that exception as "still
    playing" (``state_auto_advance.py``), so song-end auto-advance was
    silently dead in every test that used such a fake. Anything the domain
    reaches for belongs here.
    """

    def set_analytics(self, analytics: Any) -> None: ...
    def is_available(self) -> bool: ...
    async def verify_responsive(self) -> tuple[bool, str]: ...
    async def play_song(self, song: dict[str, Any]) -> bool: ...
    async def wait_for_metadata_update(self, uri: str) -> dict[str, Any]: ...
    async def stop(self) -> bool: ...
    async def play(self) -> bool: ...
    def get_volume(self) -> float: ...
    async def set_volume(self, level: float) -> bool: ...
    def save_volume(self) -> None: ...
    async def restore_volume(self) -> bool: ...
    async def restore_queue(self) -> bool: ...
    def snapshot_saved_states(self) -> dict[str, dict[str, Any]]: ...
    async def seek_forward(self, seconds: int) -> bool: ...
    def get_playback_state(self) -> str | None: ...
    async def resume_after_announcement(
        self,
        *,
        lead_seconds: float,
        should_continue: Callable[[], bool],
    ) -> None: ...

    # Why the last attempt failed, and which URI it used. Read by
    # ``state_lifecycle`` to tell a storefront gap (#808: skip the song) from
    # a systemic failure (#949/#1936: pause the game), and to name the URI
    # that was really tried in the pause banner (#1927). Both are ``None``
    # until the first attempt.
    last_failure_reason: str | None
    last_attempted_uri: str | None


@runtime_checkable
class PartyLightsProtocol(Protocol):
    """Interface that GameState expects from a party-lights service."""

    async def start(
        self,
        entity_ids: list[str],
        intensity: str = "medium",
        light_mode: str = "dynamic",
        wled_presets: dict[str, int] | None = None,
        inherited_states: dict[str, dict[str, Any]] | None = None,
    ) -> None: ...
    async def set_phase(self, phase: Any) -> None: ...
    async def flash(self, color_name: str) -> None: ...
    async def celebrate(self) -> None: ...
    async def stop(self) -> None: ...
    def snapshot_saved_states(self) -> dict[str, dict[str, Any]]: ...


@runtime_checkable
class TtsProtocol(Protocol):
    """Interface that GameState expects from a TTS announcement service (#2638).

    ``TtsAnnouncerMixin`` only ever calls ``speak``; everything else about an
    announcement (phrasing, language, staleness, the busy-window reservation)
    is game logic and stays in the domain package.
    """

    async def speak(self, message: str, language: str | None = None) -> None: ...


# ---------------------------------------------------------------------------
# Factory ports (#2638)
# ---------------------------------------------------------------------------
#
# The domain never names a concrete service class. It asks for one through
# these call signatures, which carry only game-level values (an entity id, the
# platform, the provider). Whatever a factory needs from Home Assistant it
# closes over at the composition root.


class MediaPlayerFactory(Protocol):
    """Builds the media-player service for one speaker."""

    def __call__(
        self,
        entity_id: str,
        *,
        platform: str = "unknown",
        provider: str = "spotify",
        inherited_states: dict[str, dict[str, Any]] | None = None,
    ) -> MediaPlayerProtocol: ...


class PartyLightsFactory(Protocol):
    """Builds a fresh party-lights service (one per ``configure_party_lights``)."""

    def __call__(self) -> PartyLightsProtocol: ...


class TtsFactory(Protocol):
    """Builds the TTS announcement service for a (provider, speaker) pair."""

    def __call__(
        self,
        *,
        tts_entity_id: str,
        media_player_entity_id: str,
    ) -> TtsProtocol: ...


@dataclass(frozen=True)
class GameOutputFactories:
    """Where ``GameState`` gets its output services from (#2638).

    "Outputs" = the three things the game does to the room it is played in:
    play music, drive the lights, speak. Nothing to do with the retired
    ``GameService`` transport facade removed in #2670.

    Every field defaults to ``None`` = "this output is not wired". That is the
    default a bare ``GameState()`` gets, which is what makes the game logic
    constructible — and testable — without Home Assistant.
    """

    media_player: MediaPlayerFactory | None = None
    party_lights: PartyLightsFactory | None = None
    tts: TtsFactory | None = None
