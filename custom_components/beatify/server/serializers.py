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

    from custom_components.beatify.game.state import GameState


def get_game_state(hass: HomeAssistant) -> GameState | None:
    """Look up the active GameState from hass.data.

    Returns None when no game has been created yet.
    """
    return hass.data.get(DOMAIN, {}).get("game")


def build_state_message(game_state: GameState) -> dict[str, Any] | None:
    """Build the WebSocket ``state`` message dict.

    Returns ``{"type": "state", ...}`` ready to broadcast, or *None* when the
    game has not been initialised.
    """
    state = game_state.get_state()
    if state is None:
        return None
    return {"type": "state", **state}


def build_status_response(
    hass: HomeAssistant,
    *,
    version: str,
    media_players: list[dict[str, Any]],
    playlists: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the admin ``/api/status`` JSON payload.

    Centralises the status dict so the admin view and any future consumer
    assemble the same shape.
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
        "playlists": playlists,
        "playlist_dir": data.get("playlist_dir", ""),
        "playlist_docs_url": PLAYLIST_DOCS_URL,
        "media_player_docs_url": MEDIA_PLAYER_DOCS_URL,
        "active_game": active_game,
        "has_music_assistant": has_music_assistant,
    }


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
