"""Shared state serialization helpers for views and WebSocket handler.

Both the HTTP views and the WebSocket handler need to build JSON-serializable
dicts from game state.  This module centralises that logic so changes only
need to be made in one place (#352).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from custom_components.beatify.const import (
    DOMAIN,
    MEDIA_PLAYER_DOCS_URL,
    PLAYLIST_DOCS_URL,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from custom_components.beatify.game.service import GameService
    from custom_components.beatify.game.state import GameState


def get_game_state(hass: HomeAssistant) -> GameState | None:
    """Look up the active GameState from hass.data.

    Returns None when no game has been created yet.
    """
    return hass.data.get(DOMAIN, {}).get("game")


def get_game_service(hass: HomeAssistant) -> GameService | None:
    """Look up the GameService facade from hass.data.

    Returns None when the integration has not been set up yet.
    """
    return hass.data.get(DOMAIN, {}).get("game_service")


def build_state_message(game_state: GameState) -> dict[str, Any] | None:
    """Build the WebSocket ``state`` message dict.

    Returns ``{"type": "state", ...}`` ready to broadcast, or *None* when the
    game has not been initialised.
    """
    state = game_state.get_state()
    if state is None:
        return None
    return {"type": "state", **state}


# Placeholder shown to players for an answer field that is hidden until REVEAL.
REDACTED_PLACEHOLDER = "???"


def redact_state_for_player(message: dict[str, Any]) -> dict[str, Any]:
    """Return a player-safe copy of a ``state`` / ``metadata_update`` message.

    The full broadcast payload built by :func:`build_state_message` (and the
    ``metadata_update`` payload) carries the round's answers so the spectator
    admin / TV can display them. Those frames are broadcast identically to
    every connection, so a player can read the answer straight off the
    WebSocket before guessing (#1366). This strips the answers for non-admin
    recipients:

    * ``admin_song`` (the year answer + fun facts) is removed entirely — it is
      never meant for players in any mode.
    * When ``title_artist_mode`` is active and the game is still ``PLAYING``,
      ``song.artist`` / ``song.title`` ARE the answers being guessed, so they
      are replaced with a placeholder. ``album_art`` is left intact (players
      need it to play along). The REVEAL payload is untouched — by then the
      answers are public.

    The input is not mutated; only the keys that need changing are shallow
    copied.
    """
    if not isinstance(message, dict):
        return message

    # Nothing to redact if neither answer-bearing key is present.
    has_admin_song = "admin_song" in message
    redact_song = (
        message.get("title_artist_mode")
        and message.get("phase") == "PLAYING"
        and isinstance(message.get("song"), dict)
    )
    if not has_admin_song and not redact_song:
        return message

    redacted = dict(message)
    redacted.pop("admin_song", None)
    if redact_song:
        song = dict(redacted["song"])
        song["artist"] = REDACTED_PLACEHOLDER
        song["title"] = REDACTED_PLACEHOLDER
        redacted["song"] = song
    return redacted


def build_status_response(
    hass: HomeAssistant,
    *,
    version: str,
    media_players: list[dict[str, Any]],
    playlists: list[dict[str, Any]],
    media_player_twin_remap: dict[str, str] | None = None,
    saved_setup: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the admin ``/api/status`` JSON payload.

    Centralises the status dict so the admin view and any future consumer
    assemble the same shape.

    ``media_player_twin_remap`` (#1627 follow-up) maps each native-platform
    media_player entity_id to the Music Assistant twin for the same physical
    speaker. The admin frontend uses it to heal a stale saved selection that
    points at a now-hidden native twin (see ``ensureMediaPlayerHydrated`` in
    ``mix.js``). Defaults to an empty map.

    ``saved_setup`` (#1663) is the host's persisted setup blob (speaker + game
    settings) or ``None``. It drives ``setup_complete`` — the server-side
    replacement for the localStorage-only "is configured?" check that made a
    configured instance look unconfigured on a new device.
    """
    data = hass.data.get(DOMAIN, {})
    game_state: GameState | None = data.get("game")

    active_game = None
    if game_state and game_state.game_id:
        active_game = game_state.get_state()

    has_music_assistant = any(
        entry.domain == "music_assistant"
        for entry in hass.config_entries.async_entries()
    )

    return {
        "version": version,
        "media_players": media_players,
        "media_player_twin_remap": media_player_twin_remap or {},
        "playlists": playlists,
        "playlist_dir": data.get("playlist_dir", ""),
        "playlist_docs_url": PLAYLIST_DOCS_URL,
        "media_player_docs_url": MEDIA_PLAYER_DOCS_URL,
        "active_game": active_game,
        "has_music_assistant": has_music_assistant,
        # #1663: server-side setup flag. "Configured" means a speaker was saved
        # AND at least one playlist was picked — mirrors the frontend
        # isConfigured() check, but survives a device/browser switch.
        "setup_complete": _is_setup_complete(saved_setup),
        "saved_setup": saved_setup,
    }


def _is_setup_complete(saved_setup: dict[str, Any] | None) -> bool:
    """True when the persisted setup blob has both a speaker and a playlist."""
    if not isinstance(saved_setup, dict):
        return False
    if not saved_setup.get("last_player"):
        return False
    settings = saved_setup.get("game_settings")
    if not isinstance(settings, dict):
        return False
    playlists = settings.get("selectedPlaylists")
    return isinstance(playlists, list) and len(playlists) > 0


def build_game_status_response(
    game_state: GameState | None,
    game_id: str | None,
) -> dict[str, Any]:
    """Build the ``/api/game-status`` JSON payload.

    Returns a dict with ``exists``, ``phase``, and ``can_join`` keys.
    """
    if not game_id or not game_state or game_state.game_id != game_id:
        return {
            "exists": False,
            "phase": None,
            "can_join": False,
        }

    phase = game_state.phase.value
    can_join = phase in ("LOBBY", "PLAYING", "REVEAL")

    return {
        "exists": True,
        "phase": phase,
        "can_join": can_join,
    }
