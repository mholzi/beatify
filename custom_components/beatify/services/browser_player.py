"""The game's media player and announcer when a browser is the speaker.

``MediaPlayerService`` is a conversation with one Home Assistant entity: it
reads its state, waits for its metadata, saves and restores its volume and
queue. A browser target has none of that — it is an open page on the TV or the
host's phone (``playback/browser.py``). So it gets its own small shell that
answers the same :class:`~..game.protocols.MediaPlayerProtocol`, and the game
code cannot tell the difference.

``BrowserTtsService`` does the same for announcements: ``tts.speak`` needs a
``media_player`` entity, so the announcement is rendered by Home Assistant
into an audio URL and that URL goes to the same page as the music.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from custom_components.beatify.const import (
    BROWSER_TARGET_PHONE,
    BROWSER_TARGET_ROLES,
    BROWSER_TARGET_TV,
)
from custom_components.beatify.game.playlist import get_playback_uri
from custom_components.beatify.providers import PLATFORM_BROWSER, supports_keys

from .media_player import NO_ARTWORK_PLACEHOLDER, proxy_album_art
from .playback import BrowserClientRegistry, BrowserStrategy, PlayerContext
from .tts import _match_language as match_tts_language
from .tts import supported_tts_languages

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from custom_components.beatify.analytics import AnalyticsStorage

_LOGGER = logging.getLogger(__name__)

#: The volume a page starts at. Browsers play at full level; the host lowers
#: it from the admin like any speaker (iPhones ignore it: Safari only obeys the
#: hardware buttons).
DEFAULT_BROWSER_VOLUME = 0.8


def is_browser_target(entity_id: str | None) -> bool:
    """True for the TV-screen and this-phone targets."""
    return entity_id in BROWSER_TARGET_ROLES


def browser_target_players(
    registry: BrowserClientRegistry | None,
) -> list[dict[str, Any]]:
    """The two browser targets, shaped like entries of the media-player list.

    The admin and the wizard render them in their own group ("without a
    speaker") and read ``browser_target`` / ``connected`` for it; every other
    key is the one a speaker carries, so selection, saving and the provider
    gate work on them unchanged. ``friendly_name`` is the English fallback —
    the pages show the translated name.
    """
    status = registry.status() if registry is not None else {}
    names = {"tv": "TV screen", "phone": "This phone"}
    players = []
    for entity_id in (BROWSER_TARGET_TV, BROWSER_TARGET_PHONE):
        role = BROWSER_TARGET_ROLES[entity_id]
        players.append(
            {
                "entity_id": entity_id,
                "friendly_name": names[role],
                # The phone is always there: it is the page doing the asking.
                # The TV is a speaker only while its page is open, but stays
                # selectable — the host may pick it before switching the TV on.
                "state": "idle",
                "platform": PLATFORM_BROWSER,
                **supports_keys(PLATFORM_BROWSER),
                "playback_method": BrowserStrategy.playback_method,
                "warning": None,
                "caveat": BrowserStrategy.setup_caveat,
                "browser_target": role,
                "connected": bool(status.get(role)) if role == "tv" else True,
            }
        )
    return players


class BrowserPlayerService:
    """``MediaPlayerProtocol`` for a browser target."""

    def __init__(
        self,
        hass: HomeAssistant,
        entity_id: str,
        *,
        clients: BrowserClientRegistry | None,
        provider: str = "deezer",
    ) -> None:
        self._hass = hass
        self._entity_id = entity_id
        self._context = PlayerContext(
            hass, entity_id, platform=PLATFORM_BROWSER, provider=provider
        )
        self._strategy = BrowserStrategy(self._context, clients=clients)
        self._volume = DEFAULT_BROWSER_VOLUME
        self._analytics: AnalyticsStorage | None = None

    # -- the attempt record the game reads (see MediaPlayerProtocol) --------

    @property
    def last_failure_reason(self) -> str | None:
        return self._context.last_failure_reason

    @last_failure_reason.setter
    def last_failure_reason(self, value: str | None) -> None:
        self._context.last_failure_reason = value

    @property
    def last_attempted_uri(self) -> str | None:
        return self._context.last_attempted_uri

    @last_attempted_uri.setter
    def last_attempted_uri(self, value: str | None) -> None:
        self._context.last_attempted_uri = value

    @property
    def _role(self) -> str:
        return BROWSER_TARGET_ROLES.get(self._entity_id, "tv")

    def _send(self, message: dict[str, Any]):
        clients = self._strategy.clients
        if clients is None:
            return None
        return clients.send(self._role, message)

    # -- MediaPlayerProtocol ------------------------------------------------

    def set_analytics(self, analytics: Any) -> None:
        self._analytics = analytics

    def is_available(self) -> bool:
        """Always True: a missing page is reported by :meth:`verify_responsive`.

        The round start asks both, in this order, and pauses on either. Only
        the second carries a reason, and "Media player beatify_browser.tv is
        unavailable" would tell the host nothing; "The TV screen is not open"
        tells them what to do.
        """
        return True

    def _connected(self) -> bool:
        clients = self._strategy.clients
        return clients is not None and clients.connected(self._role)

    async def verify_responsive(self) -> tuple[bool, str]:
        if self._connected():
            return True, ""
        if self._role == "tv":
            return False, "The TV screen is not open. Open Beatify's TV page on it."
        return False, "The host's phone is not connected."

    async def play_song(self, song: dict[str, Any]) -> bool:
        self.last_attempted_uri = get_playback_uri(song) or None
        self.last_failure_reason = None
        self._context.audio_wanted = True
        try:
            return await self._strategy.play(song)
        except Exception as err:  # noqa: BLE001 — a lookup must not end the round
            _LOGGER.error("Browser playback failed: %s", err)  # noqa: TRY400
            if self._analytics:
                self._analytics.record_error("PLAYBACK_FAILURE", str(err))
            self.last_failure_reason = "error"
            return False

    async def wait_for_metadata_update(self, uri: str) -> dict[str, Any]:
        """The cover from the preview lookup; no entity to wait for."""
        preview = self._strategy.last_preview
        art = preview.album_art if preview and preview.album_art else None
        return {"album_art": proxy_album_art(art) if art else NO_ARTWORK_PLACEHOLDER}

    async def stop(self) -> bool:
        self._context.audio_wanted = False
        sent = self._send({"type": "browser_audio", "action": "stop"})
        return bool(await sent) if sent is not None else False

    async def play(self) -> bool:
        self._context.audio_wanted = True
        sent = self._send({"type": "browser_audio", "action": "resume"})
        return bool(await sent) if sent is not None else False

    def get_volume(self) -> float:
        return self._volume

    async def set_volume(self, level: float) -> bool:
        self._volume = max(0.0, min(1.0, float(level)))
        sent = self._send(
            {"type": "browser_audio", "action": "volume", "level": self._volume}
        )
        return bool(await sent) if sent is not None else False

    def save_volume(self) -> None:
        """Nothing to remember: the page forgets its level when it closes."""

    async def restore_volume(self) -> bool:
        return True

    async def restore_queue(self) -> bool:
        """A browser has no queue that Beatify could have replaced."""
        return True

    def snapshot_saved_states(self) -> dict[str, dict[str, Any]]:
        return {}

    def get_playback_state(self) -> str | None:
        """``playing`` / ``idle`` in the speaker vocabulary the game reads."""
        clients = self._strategy.clients
        state = clients.playback_state(self._role) if clients else None
        if state is None:
            return None
        if state in ("ended", "error"):
            return "idle"
        if state == "paused":
            return "paused"
        # "blocked" counts as playing: the clip starts with "Sound on".
        return "playing"

    async def resume_after_announcement(
        self,
        *,
        lead_seconds: float,
        should_continue: Callable[[], bool],
    ) -> None:
        """Nothing to watch: the page ducks the music under an announcement
        and brings it back itself."""


class BrowserTtsService:
    """``TtsProtocol`` that speaks through the browser target's page."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        tts_entity_id: str,
        target_entity_id: str,
        clients: BrowserClientRegistry | None,
    ) -> None:
        self._hass = hass
        self._tts_entity_id = tts_entity_id
        self._role = BROWSER_TARGET_ROLES.get(target_entity_id, "tv")
        self._clients = clients

    async def speak(self, message: str, language: str | None = None) -> None:
        if not message or not self._tts_entity_id:
            return
        clients = self._clients
        if clients is None or not clients.connected(self._role):
            _LOGGER.debug("TTS skipped — no browser is playing for %s", self._role)
            return
        url = await self._audio_url(message, language)
        if not url:
            return
        await clients.send(
            self._role, {"type": "browser_audio", "action": "announce", "url": url}
        )

    async def _audio_url(self, message: str, language: str | None) -> str | None:
        """Have Home Assistant render ``message`` and return its proxy URL.

        Same route ``tts.speak`` takes internally before it hands the result
        to a media player: a media-source id for the engine, resolved to the
        ``/api/tts_proxy/…`` URL. That path is served by Home Assistant itself,
        so the page fetches it from the origin it was loaded from.
        """
        try:
            from homeassistant.components import media_source  # noqa: PLC0415
            from homeassistant.components.tts import (  # noqa: PLC0415
                generate_media_source_id,
            )

            resolved = (
                match_tts_language(
                    language,
                    supported_tts_languages(self._hass, self._tts_entity_id),
                )
                if language
                else None
            )
            media_id = generate_media_source_id(
                self._hass, message, engine=self._tts_entity_id, language=resolved
            )
            media = await media_source.async_resolve_media(self._hass, media_id, None)
        except Exception as err:  # noqa: BLE001 — an announcement is optional
            _LOGGER.warning("TTS for the browser failed: %s", err)
            return None
        url = getattr(media, "url", None)
        return url if isinstance(url, str) and url else None
