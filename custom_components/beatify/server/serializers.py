"""Shared state serialization helpers for views and WebSocket handler.

Both the HTTP views and the WebSocket handler need to build JSON-serializable
dicts from game state.  This module centralises that logic so changes only
need to be made in one place (#352).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from custom_components.beatify.const import (
    DOMAIN,
    MEDIA_PLAYER_DOCS_URL,
    PLAYLIST_DOCS_URL,
    PROVIDER_MA_LIBRARY,
)

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from custom_components.beatify.game.state import GameState

_LOGGER = logging.getLogger(__name__)


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


# Placeholder shown to players for an answer field that is hidden until REVEAL.
REDACTED_PLACEHOLDER = "???"


# ---------------------------------------------------------------------------
# Player-visible state — an allowlist, not a denylist (#2634)
# ---------------------------------------------------------------------------
#
# The ``state`` broadcast carries ~59 top-level keys. Until #2634 the filtering
# was a denylist of two (``admin_song``, ``song.artist``/``song.title``), so
# every key added to the serializer reached the player sockets by default. That
# default produced two leaks — #1366 (``admin_song``) and #2550
# (``artist_challenge``) — each closed afterwards by widening the denylist.
#
# The direction is now reversed: a key reaches a player only if it is listed
# here, and ``tests/unit/test_player_state_allowlist_2634.py`` fails the build
# when the serializer grows a key that is in neither set. A new answer field is
# therefore a red CI run, not a line in someone's network tab.
#
# Adding a key here is a deliberate act: ask whether a guest holding the phone
# may see it *before* they guess.

#: Base keys, present in every phase (``GameStateSerializer.serialize``).
_PLAYER_VISIBLE_BASE = frozenset(
    {
        # ``type`` is the envelope from build_state_message; the HTTP
        # ``active_game`` payload has no envelope and simply never carries it.
        "type",
        "game_id",
        "phase",
        "player_count",
        "players",
        "language",
        "difficulty",
        "round_duration",
        "intro_mode_enabled",
        "closest_wins_mode",
        "rampup_order_enabled",
        "comeback_token_enabled",
        "sabotage_enabled",
        "difficulty_bet_scaling_enabled",
        "bet_win_multiplier",
        "sudden_death_mode",
        "finale_double_enabled",
        "finale_tiebreaker_enabled",
        "title_artist_mode",
        "is_intro_round",
        "intro_stopped",
        "intro_splash_pending",
        "year_range",
    }
)

#: LOBBY / PLAYING / REVEAL round context.
_PLAYER_VISIBLE_ROUND = frozenset(
    {
        "join_url",
        "round",
        "total_rounds",
        "last_round",
        "songs_remaining",
        "deadline",
        "server_now_ms",
        "seconds_remaining",
        "finale_double_active",
        "finale_playoff_active",
        "submitted_count",
        "all_submitted",
        # The song card. Its *contents* are filtered separately during PLAYING —
        # see PLAYING_SONG_PLAYER_KEYS below.
        "song",
        "leaderboard",
        # The three challenge blocks are built with ``include_answer=False``
        # during PLAYING and ``include_answer=True`` at REVEAL, so the answer
        # gating lives in the challenge managers, not here.
        "artist_challenge",
        "movie_challenge",
        "title_artist_challenge",
        # #2557: the host renders the volume, but the frame goes to everyone.
        "volume_level",
    }
)

#: PAUSED-phase recovery banner.
_PLAYER_VISIBLE_PAUSED = frozenset(
    {
        "pause_reason",
        "last_error_detail",
        "provider",
        "media_player",
    }
)

#: REVEAL-phase result surface. Everything here is public by the time it is
#: sent — REVEAL is the moment the answer becomes common knowledge.
_PLAYER_VISIBLE_REVEAL = frozenset(
    {
        "eliminated_this_round",
        "round_analytics",
        "game_performance",
        "song_difficulty",
        "early_reveal",
        "idle_halt",
        "reveal_auto_advance",
        "reveal_started_at",
    }
)

#: END-phase podium.
_PLAYER_VISIBLE_END = frozenset(
    {
        "game_stats",
        "winner",
        "superlatives",
        "highlights",
        "share_data",
    }
)

#: Every top-level key a non-admin socket may receive.
PLAYER_VISIBLE_KEYS: frozenset[str] = (
    _PLAYER_VISIBLE_BASE
    | _PLAYER_VISIBLE_ROUND
    | _PLAYER_VISIBLE_PAUSED
    | _PLAYER_VISIBLE_REVEAL
    | _PLAYER_VISIBLE_END
)

#: Top-level keys that stay on the spectator-admin socket. Listing a key here
#: rather than simply leaving it out of the allowlist is what makes the
#: completeness test meaningful: an unlisted key is an oversight, a listed one
#: is a decision.
ADMIN_ONLY_KEYS: frozenset[str] = frozenset(
    {
        # #648/#1366: the year answer, the fun facts and the library URI.
        "admin_song",
    }
)

#: Keys of the PLAYING-phase ``song`` sub-dict a player may receive. The song
#: card is where the answer lives, so it gets the same default-deny treatment
#: one level down: a ``year`` accidentally added to the PLAYING payload would
#: otherwise be the answer, printed, before anyone guesses.
#:
#: The REVEAL ``song`` is deliberately NOT filtered — by then the year, the fun
#: facts and the cover hint are the point of the screen.
PLAYING_SONG_PLAYER_KEYS: frozenset[str] = frozenset(
    {
        "artist",
        "title",
        "album_art",
    }
)

# Keys already reported as unclassified, so the warning below fires once per
# key per process instead of once per broadcast.
_UNCLASSIFIED_SEEN: set[str] = set()


def redact_state_for_player(message: dict[str, Any]) -> dict[str, Any]:
    """Return a player-safe copy of a ``state`` / ``metadata_update`` message.

    The full broadcast payload built by :func:`build_state_message` carries the
    round's answers so the spectator admin / TV can display them. Those frames
    are broadcast identically to every connection, so a player could read the
    answer straight off the WebSocket before guessing (#1366).

    Three things happen here:

    * **Top-level allowlist (#2634).** Only :data:`PLAYER_VISIBLE_KEYS` survive.
      Anything else is dropped — including, by name, :data:`ADMIN_ONLY_KEYS`
      (``admin_song``: the year answer, the fun facts, the library URI). A key
      in neither set is dropped *and* logged, and fails the build in
      ``tests/unit/test_player_state_allowlist_2634.py``.
    * **Song allowlist during PLAYING.** The ``song`` card is reduced to
      :data:`PLAYING_SONG_PLAYER_KEYS`. The REVEAL card is untouched.
    * **Answer masking.** When ``title_artist_mode`` is active and the game is
      still ``PLAYING``, ``song.artist`` / ``song.title`` ARE the answers being
      guessed, so they become :data:`REDACTED_PLACEHOLDER`. ``album_art`` stays
      — players need it to play along. An artist challenge (#2550) masks
      ``song.artist`` alone; the title is not part of that challenge.

    The input is never mutated. When nothing needs changing the *same object* is
    returned, which the broadcast path relies on to serialize a payload once
    instead of twice (#1711).
    """
    if not isinstance(message, dict):
        return message

    playing_with_song = message.get("phase") == "PLAYING" and isinstance(
        message.get("song"), dict
    )
    redact_song = bool(message.get("title_artist_mode")) and playing_with_song
    # #2550: an artist challenge asks players to name the artist, so during
    # PLAYING `song.artist` is the answer just as much as in title_artist_mode.
    # No client renders it, but the frame is on every player socket and the
    # network tab is enough to read it.
    redact_artist_only = (
        not redact_song
        and playing_with_song
        and isinstance(message.get("artist_challenge"), dict)
    )

    stripped = [key for key in message if key not in PLAYER_VISIBLE_KEYS]
    song_stripped = (
        [key for key in message["song"] if key not in PLAYING_SONG_PLAYER_KEYS]
        if playing_with_song
        else []
    )
    if (
        not stripped
        and not song_stripped
        and not redact_song
        and not redact_artist_only
    ):
        return message

    for key in stripped:
        if key in ADMIN_ONLY_KEYS or key in _UNCLASSIFIED_SEEN:
            continue
        _UNCLASSIFIED_SEEN.add(key)
        _LOGGER.warning(
            "State key %r is in neither PLAYER_VISIBLE_KEYS nor ADMIN_ONLY_KEYS "
            "(server/serializers.py) — it is being withheld from players. If it "
            "belongs on a player screen, add it to the allowlist (#2634).",
            key,
        )

    redacted = {
        key: value for key, value in message.items() if key in PLAYER_VISIBLE_KEYS
    }
    if playing_with_song:
        song = {
            key: value
            for key, value in message["song"].items()
            if key in PLAYING_SONG_PLAYER_KEYS
        }
        if redact_song:
            song["artist"] = REDACTED_PLACEHOLDER
            song["title"] = REDACTED_PLACEHOLDER
        elif redact_artist_only:
            song["artist"] = REDACTED_PLACEHOLDER
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
    redact_answers: bool = False,
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

    ``redact_answers`` (#2332) strips the round's answers out of
    ``active_game`` for a caller who has not proved they are the host. The
    #1366 redaction existed but was wired only into the WebSocket path, so an
    unauthenticated HTTP GET returned ``admin_song.year`` — the answer — to
    anyone who could reach the port. Players are unauthenticated by design and
    on the same network, so that is one browser tab, silently, with nothing in
    the log.
    """
    data = hass.data.get(DOMAIN, {})
    game_state: GameState | None = data.get("game")

    active_game = None
    if game_state and game_state.game_id:
        active_game = game_state.get_state()
        # #2332: same treatment the WebSocket broadcast already gets. The
        # endpoint stays open — the wizard (``wizard.js``) and the playlist
        # hub fetch it without a token and would break under a hard auth
        # gate, which is why ``requires_auth`` is False in the first place.
        # Only the answers come out.
        if redact_answers and isinstance(active_game, dict):
            active_game = redact_state_for_player(active_game)

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
    """True when the persisted setup can actually start a game.

    That normally means a speaker plus at least one playlist. Crate Digger
    (``ma_library``) GENERATES its playlist from the host's own library at
    game start, so it never selects one — requiring a playlist there reported
    "You haven't set up yet" to hosts who had completed the wizard.
    """
    if not isinstance(saved_setup, dict):
        return False
    if not saved_setup.get("last_player"):
        return False
    settings = saved_setup.get("game_settings")
    if not isinstance(settings, dict):
        return False
    # The persisted blob writes `provider` (the wizard) — `selectedProvider`
    # is only the in-memory name on the admin page. Accept either.
    if PROVIDER_MA_LIBRARY in (
        settings.get("provider"),
        settings.get("selectedProvider"),
    ):
        return True
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
    # #2549: PAUSED accepts joins too — add_player only rejects END, and an
    # admin phone whose screen locked pauses the game after a 5s grace period
    # (#841), which is a common window for a guest to be scanning the QR code.
    # Without PAUSED here they were told "game in progress, try again in a
    # moment" and had to keep retrying by hand against a server that would have
    # let them straight in.
    can_join = phase in ("LOBBY", "PLAYING", "REVEAL", "PAUSED")

    return {
        "exists": True,
        "phase": phase,
        "can_join": can_join,
    }
