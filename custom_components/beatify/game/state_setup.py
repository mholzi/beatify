"""Game-setup / create-reset-rematch subsystem for :class:`GameState`.

Issue #1271 next-increment extraction (off ``main``, **not** stacked): the
**game-setup lifecycle** cluster is pulled out of the ``game/state.py``
God-Object into this ``GameSetupMixin``.

The cluster is the "stand a game up, tear it down, and stand it up again"
group: ``create_game`` builds a fresh session from the admin's playlist /
provider / mode selection (token generation, PlaylistManager construction,
storefront detection, round-tracking + config reset, challenge / power-up
configuration), ``end_game`` tears the session back down to an empty LOBBY,
and ``rematch_game`` rebuilds a fresh session while preserving the connected
players and the admin-configured settings. ``_reset_game_internals`` is the
shared field-reset both teardown paths route through (so end and rematch can
never drift), and ``_detect_storefront`` resolves the Apple-Music storefront
the two builders attach to their PlaylistManager. It is **behavior-preserving**:
it carries the exact same methods that previously lived on ``GameState``, so its
public API and every caller / test are unchanged.

* ``create_game`` — the new-session builder. Validates the round duration,
  clears any leftover sessions, mints a fresh ``game_id`` / ``admin_token``,
  builds the join URL, constructs the :class:`PlaylistManager` (failing fast on
  a provider with zero playable songs, #709), resets round tracking + the
  config-managed fields, and configures the challenge / power-up / intro / mode
  state before flipping to ``LOBBY`` through the ``_set_phase`` chokepoint.
* ``_reset_game_internals`` — the shared field reset used by ``end_game`` and
  ``rematch_game`` (Issue #108, #464). Rebuilds the config-managed fields from
  ``_default_config`` via ``_apply_config`` and delegates round / power-up /
  challenge / highlights resets to the owned managers. Does **not** touch
  players, sessions, phase, ``game_id``, callbacks, service refs, or volume.
* ``end_game`` — tears the session down to an empty LOBBY: cancels the round
  timer + the #1012 REVEAL auto-advance task (synchronously, before the awaits),
  restores lights / disables TTS, runs ``_reset_game_internals``, clears
  ``game_id`` + players + sessions, and notifies the state callbacks.
* ``rematch_game`` — rebuilds a fresh session preserving the connected players
  (Issue #108) and the admin-configured settings (Issue #591): snapshots the
  settings, runs ``_reset_game_internals``, restores the snapshot, re-detects the
  storefront + re-creates the PlaylistManager, resets each player's per-game
  stats, mints a new ``game_id`` / ``admin_token`` and regenerates the join URL.
* ``_detect_storefront`` — resolves the Apple-Music storefront (#808 follow-up)
  from ``hass.config.country`` (lower-cased) or ``None``; used only by the two
  builders above.

Why the cut stops here: the ``_set_phase`` transition chokepoint (#1273) stays
on ``GameState`` — the builders only *call* it. ``_apply_config`` /
``_default_config``, ``cancel_timer``, ``_cancel_auto_advance``,
``clear_all_sessions``, ``disable_party_lights`` / ``disable_tts`` and the owned
managers (``_playlist_manager``, ``_powerup_manager``, ``_challenge_manager``,
``_round_manager``, ``highlights_tracker``) stay on ``GameState`` too; this mixin
references them via ``self`` and moves none of them.

The mixin relies on attributes / methods the host class owns and that live on
``self`` at runtime:

* ``self._set_phase`` — the single phase-transition chokepoint (#1273) the
  builders / teardown route their ``LOBBY`` writes through; stays on
  ``GameState``.
* ``self._apply_config`` / ``self._default_config`` — config-managed field reset
  (game/config.py); used by ``_reset_game_internals``.
* ``self.cancel_timer`` / ``self._cancel_auto_advance`` — round-timer + #1012
  REVEAL auto-advance cancellation on teardown; stay on ``GameState``.
* ``self.clear_all_sessions`` — leftover-session clear on create + teardown.
* ``self.disable_party_lights`` / ``self.disable_tts`` — output restore on
  ``end_game`` (MediaControlMixin / TtsAnnouncerMixin).
* ``self._playlist_manager`` / ``self._powerup_manager`` /
  ``self._challenge_manager`` / ``self._round_manager`` /
  ``self.highlights_tracker`` — the owned managers reset / (re)configured / (re)
  created across the cluster.
* ``self._hass`` — read by ``_detect_storefront`` for the configured country.
* ``self._notify_state_callbacks`` — fired at the end of ``end_game``.

It carries no state of its own. ``GamePhase`` is imported lazily inside the
methods that need it (``# noqa: PLC0415``) to avoid a top-level circular import
back into ``state.py``.
"""

from __future__ import annotations

import logging
import secrets
from typing import Any

from custom_components.beatify.const import (
    DEFAULT_ROUND_DURATION,
    DIFFICULTY_DEFAULT,
    PROVIDER_DEFAULT,
    ROUND_DURATION_MAX,
    ROUND_DURATION_MIN,
)

from .playlist import PlaylistManager

_LOGGER = logging.getLogger(__name__)


class GameSetupMixin:
    """Game-setup (create / reset / end / rematch) behavior for :class:`GameState`.

    Carries the new-session builder plus the teardown / rematch rebuild and
    their shared field-reset + storefront-detection helpers (#1271 extraction).
    See the module docstring for the full attribute / method contract this mixin
    expects on ``self`` at runtime.
    """

    def create_game(  # noqa: PLR0913
        self,
        playlists: list[str],
        songs: list[dict[str, Any]],
        media_player: str,
        base_url: str,
        round_duration: int = DEFAULT_ROUND_DURATION,
        difficulty: str = DIFFICULTY_DEFAULT,
        provider: str = PROVIDER_DEFAULT,
        platform: str = "unknown",
        artist_challenge_enabled: bool = True,
        movie_quiz_enabled: bool = True,
        intro_mode_enabled: bool = False,
        closest_wins_mode: bool = False,
        sudden_death_mode: bool = False,
        title_artist_mode: bool = False,
        reveal_auto_advance: int = 0,
    ) -> dict[str, Any]:
        """
        Create a new game session.

        Args:
            playlists: List of playlist file paths
            songs: List of song dicts loaded from playlists
            media_player: Entity ID of media player
            base_url: HA base URL for join URL construction
            round_duration: Round timer duration in seconds (10-60, default 30)
            difficulty: Difficulty level (easy/normal/hard, default normal)
            provider: Music provider (spotify/apple_music, default spotify)
            platform: Platform identifier for playback routing (music_assistant, sonos, alexa_media)
            artist_challenge_enabled: Whether to enable artist guessing (default True)
            movie_quiz_enabled: Whether to enable movie quiz bonus (default True)
            intro_mode_enabled: Whether to enable intro mode (~20% random rounds)
            closest_wins_mode: Whether only the closest guess(es) earn points
            title_artist_mode: Whether title/artist guessing replaces the year guess

        Returns:
            dict with game_id, join_url, song_count, phase

        Raises:
            ValueError: If round_duration is outside valid range (10-60)

        """
        from .state import GamePhase  # noqa: PLC0415

        # Validate round duration (Story 13.1)
        if not (ROUND_DURATION_MIN <= round_duration <= ROUND_DURATION_MAX):
            raise ValueError(
                f"Round duration must be between {ROUND_DURATION_MIN} "
                f"and {ROUND_DURATION_MAX} seconds"
            )

        # #1378: validate BEFORE mutating any state. Building the
        # PlaylistManager and running the #709 no-playable-songs check first —
        # into locals, touching nothing on self — means a validation failure
        # leaves GameState completely untouched (game_id stays None, phase
        # unchanged, players intact). Otherwise the host hits a zombie
        # zero-song LOBBY that the create-handler's existing-game guard
        # (#935) then rejects with 409 on every retry.
        #
        # #808 follow-up: detect the user's Apple Music storefront from
        # HA's configured country. Beatify's playlists carry per-region
        # Apple Music URIs; PlaylistManager uses this to pick the right
        # one and to filter out songs explicitly unavailable in this
        # region. Lower-case to match the storefront codes used by
        # Apple's API ("us", "de", "gb", ...). None when HA doesn't have
        # a country configured → falls back to the legacy single URI.
        # _detect_storefront is read-only, so it is safe to run pre-mutation.
        storefront = self._detect_storefront()

        # Initialize PlaylistManager for song selection (Epic 4, Story 17.2: with provider)
        playlist_manager = PlaylistManager(songs, provider, storefront=storefront)

        # #709: if the chosen provider has zero playable songs, fail fast with
        # a clear error rather than silently starting a game that will stall.
        if not playlist_manager.has_playable_songs():
            raise ValueError(
                f"No playable songs for provider '{provider}' in the selected "
                f"playlist(s). Pick a different playlist or provider."
            )

        # Validation passed — now it is safe to mutate game state.
        # Clear any leftover sessions from previous/crashed game (Story 11.6)
        self.clear_all_sessions()

        # #1358: a new game invalidates any start_round still parked in an
        # await from a prior game/session.
        self._game_epoch += 1
        self.game_id = secrets.token_urlsafe(8)
        self.admin_token = secrets.token_urlsafe(16)  # Issue #386: REST admin auth
        self._set_phase(GamePhase.LOBBY)
        self.playlists = playlists
        self.songs = songs
        self.media_player = media_player
        # A new game brings fresh media_player/platform/provider from the wizard.
        # The lazily-built MediaPlayerService captures these at construction time
        # (services/media_player.py __init__) — without nulling it here, the next
        # _ensure_media_player_service() call recycles the previous game's service
        # because of its `not self._media_player_service` guard. Result: playback
        # ignores the new selection and routes via the old entity_id/platform/
        # provider until HA itself restarts. rematch_game() intentionally preserves
        # these values, so this reset stays scoped to create_game.
        self._media_player_service = None
        self.join_url = f"{base_url}/beatify/play?game={self.game_id}"
        self.players = {}

        # Store provider setting (Story 17.2)
        self.provider = provider

        # Store platform for playback routing
        self.platform = platform

        self.storefront = storefront

        # Reset error detail
        self.last_error_detail = ""

        self._playlist_manager = playlist_manager

        # Reset round tracking for new game
        self.round = 0
        self.total_rounds = self._playlist_manager.get_total_count()
        self.deadline = None
        self.current_song = None
        self.last_round = False
        self.pause_reason = None
        self._previous_phase = None

        # Reset timing for speed bonus (Story 5.1) and configurable duration (Story 13.1)
        self.round_start_time = None
        self.round_duration = round_duration

        # Set difficulty (Story 14.1). Explicit annotation so mypy has a
        # declared type at the assignment point — without it the gated
        # game/service.py read (self._game_state.difficulty) hit a mypy
        # has-type deferral once GameState grew to 9 mixins (#1271).
        self.difficulty: str = difficulty

        # Reset song stopped flag (Story 6.2)
        self.song_stopped = False

        # #1012: REVEAL auto-advance — seconds to wait in REVEAL before
        # starting the next round automatically (0 = off / manual only).
        self.reveal_auto_advance = reveal_auto_advance
        # #1359: cancel any leftover auto-advance / vote-window task from a
        # prior game instead of just dropping the handle — a bare
        # ``self._auto_advance_task = None`` would orphan a still-running
        # vote-window task that could mutate the new game's state.
        self._cancel_auto_advance()
        self.reveal_started_at = None  # #1048

        # #1359: the title/artist vote-window flags live on GameState and are
        # NOT managed by GameStateConfig, so _apply_config()/_reset_game_internals
        # don't touch them. A force-ended title/artist game can leak
        # _title_artist_voting_open=True into the next game, which then loses
        # REVEAL auto-advance and double-scores a round. Reset them explicitly.
        self._title_artist_voting_open = False
        self._title_artist_vote_deadline = None
        # #1371: clear the pause snapshot of the vote window too.
        self._paused_vote_open = False
        self._paused_vote_deadline = None

        # Reset round analytics (Story 13.3)
        self.round_analytics = None

        # Issue #351: Reset power-up state for new game
        self._powerup_manager.reset()

        # Story 20.1 / Issue #28 / Issue #1180: Set challenge configuration
        self._challenge_manager.configure(
            artist_challenge_enabled=artist_challenge_enabled,
            movie_quiz_enabled=movie_quiz_enabled,
            title_artist_mode=title_artist_mode,
        )

        # Issue #23: Set intro mode configuration
        self.intro_mode_enabled = intro_mode_enabled

        # Issue #442: Set closest wins mode
        self.closest_wins_mode = closest_wins_mode
        # Issue #827: Set sudden death mode
        self.sudden_death_mode = sudden_death_mode
        self.is_intro_round = False
        self.intro_stopped = False
        self._round_manager._intro_round_start_time = None
        self._round_manager._rounds_since_intro = 0
        self._round_manager._cancel_intro_timer()

        # Reset timer task for new game
        self.cancel_timer()

        _LOGGER.info("Game created: %s with %d songs", self.game_id, len(songs))

        # #1540: pre-warm the MediaPlayerService during LOBBY so Round 1 doesn't
        # pay the construction + cold first-call (preflight) latency that #803
        # tracked. Fire-and-forget / best-effort — must NOT block create_game.
        # _ensure_media_player_service() stays the idempotent fallback if this
        # didn't run (or hasn't finished) by the time the first round starts.
        self.schedule_media_player_prewarm()

        return {
            "game_id": self.game_id,
            "join_url": self.join_url,
            "phase": self.phase.value,
            "song_count": len(songs),
        }

    def _reset_game_internals(self) -> None:
        """Reset internal game state (Issue #108, #464).

        Shared by end_game() and rematch_game() to prevent field drift.
        Uses GameStateConfig to rebuild config-managed fields from defaults,
        and delegates round state reset to RoundManager.reset().

        Does NOT reset: players, sessions, phase, game_id, callbacks,
        service refs (_stats_service, _on_round_end, _on_metadata_update),
        or volume_level (caller's responsibility).
        """
        # Issue #477: Clear admin spectator WS (connection stays open, just de-ref)
        self._admin_ws = None

        # Issue #464: Reset round lifecycle (timers, metadata, intro state)
        self._round_manager.reset()
        self.cancel_timer()

        # Issue #464: Rebuild config-managed fields from defaults
        self._apply_config(self._default_config)

        # #1359: the title/artist vote-window flags are NOT config-managed, so
        # _apply_config above does not touch them. Without this, a force-ended
        # title/artist game (end_game) or a rematch leaks
        # _title_artist_voting_open=True into the next game — disabling REVEAL
        # auto-advance and double-scoring the round on host-advance.
        self._title_artist_voting_open = False
        self._title_artist_vote_deadline = None

        # Issue #351: Reset power-up state
        self._powerup_manager.reset()

        # Story 20.1 / Issue #28: Reset challenges
        self._challenge_manager.reset()

        # Issue #75: Reset highlights tracker
        self.highlights_tracker.reset()

    async def end_game(self) -> None:
        """End the current game and reset state."""
        from .state import GamePhase  # noqa: PLC0415

        _LOGGER.info("Game ended: %s", self.game_id)
        self.cancel_timer()
        # #1012: cancel the REVEAL auto-advance task synchronously, BEFORE the
        # awaits below. Otherwise a countdown expiring at the same instant could
        # fire start_round() during disable_party_lights()/disable_tts() (phase
        # is still REVEAL there) and trigger the next song after the game ended.
        # advance_to_end() already does this; the HTTP/force-end path lands here.
        self._cancel_auto_advance()
        # #1540 review: cancel a still-running LOBBY media-player pre-warm so it
        # can't keep probing the speaker after the game ended (analogous to the
        # auto-advance cancel above).
        self._cancel_prewarm()
        # #1358: bump the game-identity epoch synchronously, BEFORE the awaits
        # below (same rationale as the _cancel_auto_advance above). A start_round
        # that's parked in play_song and resumes anytime during this teardown —
        # even during disable_party_lights()/disable_tts(), while phase is still
        # REVEAL/PLAYING — then sees the changed epoch and bails instead of
        # stamping PLAYING onto the now-empty game.
        self._game_epoch += 1
        # #1402 B2: serialize the teardown with any in-flight round-end. The
        # synchronous guards above (cancel_timer / _cancel_auto_advance / the
        # epoch bump) deliberately run BEFORE this acquire so a start_round
        # parked in an await sees the new epoch immediately. But _end_round_
        # unlocked runs its whole body under _score_lock and has no per-await
        # epoch re-check — without taking the lock here, an end_round() parked
        # mid-reveal could resume AFTER this teardown and flip the torn-down
        # game back into REVEAL (an illegal LOBBY->REVEAL edge) while scheduling
        # stray auto-advance tasks. Holding _score_lock around the teardown
        # makes end_game and _end_round_unlocked mutually exclusive: either the
        # round-end fully completes first, or it never starts on the dead game.
        async with self._score_lock:
            # Issue #331: Restore lights before resetting
            await self.disable_party_lights()
            # #1516: restore the speaker volume to its pre-game level (the host
            # had to manually reset it after every game otherwise). No-op if
            # Beatify never changed the volume this game.
            await self.restore_player_volume()
            # Issue #447: Disable TTS
            await self.disable_tts()
            self._reset_game_internals()
            self.game_id = None
            self._set_phase(GamePhase.LOBBY, notify=False)
            self.players = {}
            self.clear_all_sessions()
            self._notify_state_callbacks()

    def rematch_game(self) -> None:
        """Reset game for rematch, preserving connected players (Issue #108)."""
        from .state import GamePhase  # noqa: PLC0415

        _LOGGER.info("Rematch initiated from game: %s", self.game_id)
        self.cancel_timer()

        # Preserve game settings that the admin configured (Issue #591)
        preserved = {
            "playlists": self.playlists,
            "songs": list(self.songs),
            "media_player": self.media_player,
            "join_url": self.join_url,
            "provider": self.provider,
            "platform": self.platform,
            "difficulty": self.difficulty,
            "language": self.language,
            "round_duration": self.round_duration,
            "artist_challenge_enabled": self.artist_challenge_enabled,
            "movie_quiz_enabled": self.movie_quiz_enabled,
            "intro_mode_enabled": self.intro_mode_enabled,
            "closest_wins_mode": self.closest_wins_mode,
            "sudden_death_mode": self.sudden_death_mode,
            "title_artist_mode": self.title_artist_mode,
        }

        self._reset_game_internals()

        # Restore preserved settings for seamless rematch
        for attr, value in preserved.items():
            setattr(self, attr, value)

        # Re-create PlaylistManager with fresh song list
        # #808 follow-up: re-detect storefront for the rematch (in case
        # HA's country config changed) and re-attach it.
        self.storefront = self._detect_storefront()
        self._playlist_manager = PlaylistManager(
            preserved["songs"],
            preserved["provider"],
            storefront=self.storefront,
        )
        # #1377: derive total_rounds from the filtered/deduped playable pool
        # (exactly like create_game, state_setup.py), not the raw song list.
        # Using len(preserved["songs"]) inflated total_rounds whenever the
        # PlaylistManager dropped songs (no provider URI, duplicate URI, or
        # storefront-unavailable), breaking 'Round X of Y' and the last-round
        # TTS gate.
        self.total_rounds = self._playlist_manager.get_total_count()

        self._set_phase(GamePhase.LOBBY)
        # #1358: a rematch replaces the game identity — invalidate any
        # start_round still parked in an await from the finished game.
        self._game_epoch += 1
        # Reset each player's game stats but keep them connected
        for player in self.players.values():
            player.reset_for_new_game()
        # Generate new game ID and admin token for the rematch
        self.game_id = secrets.token_urlsafe(8)
        self.admin_token = secrets.token_urlsafe(16)  # Issue #386

        # Regenerate join_url with new game_id
        if preserved["join_url"]:
            base_url = preserved["join_url"].split("/beatify/play")[0]
            self.join_url = f"{base_url}/beatify/play?game={self.game_id}"

        _LOGGER.info(
            "Rematch ready with %d players, %d songs, new game_id: %s",
            len(self.players),
            self.total_rounds,
            self.game_id,
        )

    def _detect_storefront(self) -> str | None:
        """Determine the user's Apple Music storefront for URI resolution.

        Sources, in order:
          1. ``hass.config.country`` — HA's configured country code, set
             during initial HA setup. This is what most users will have.
             Returned lower-cased to match Apple's storefront codes.
          2. None — fall back to the legacy single Apple Music URI in
             ``uri_apple_music`` (typically a US track ID).

        Future: query Music Assistant's WebSocket API for the actual
        Apple Music provider's configured storefront, which may differ
        from HA's country (e.g. an expat using a US Apple Music account
        from a German HA install). For now HA's country covers ~80%+ of
        users without any extra round-trip.
        """
        hass = getattr(self, "_hass", None)
        if hass is None:
            return None
        country = getattr(hass.config, "country", None) if hass.config else None
        if not country:
            return None
        return str(country).strip().lower() or None
