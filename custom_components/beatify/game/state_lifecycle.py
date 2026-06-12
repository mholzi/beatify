"""Round-lifecycle / round-start subsystem for :class:`GameState`.

Issue #1271 next-increment extraction (stacked on the state-serialization cut
:class:`~custom_components.beatify.game.state_serialization.StateSerializationMixin`):
the **round-start / round-setup orchestration** cluster is pulled out of the
``game/state.py`` God-Object into this ``RoundLifecycleMixin``.

The cluster is the "kick off the game and set up each new round" half of the
class: the LOBBY→PLAYING start gate plus the full ``start_round`` orchestration
(song selection, playback dispatch, metadata build, round-state commit). It is
**behavior-preserving**: it carries the exact same methods that previously
lived on ``GameState``, so its public API and every caller / test are
unchanged.

* ``start_game`` — the LOBBY→PLAYING start gate: validates the phase and the
  minimum player count, then flips to PLAYING (#390 precursor). Called by the
  admin ``start_game`` WebSocket / view handlers.
* ``start_round`` — the round-start orchestrator (#390): pulls the next
  playable song from the :class:`PlaylistManager`, skips/retries songs with no
  provider URI (capped at ``MAX_SONG_RETRIES``), dispatches playback through
  the lazily-created :class:`MediaPlayerService` (classifying ``unavailable``
  storefront skips vs. systemic playback failures per #808 / #949), builds the
  round metadata, commits the round state, flips the lights and fires the
  round-start TTS announcements (#471 / #841 / #842). The single entry point
  every "advance to the next round" caller (``ws_handlers``, ``game_views``,
  ``GameService``) hits.
* ``_ensure_media_player_service`` — lazily constructs the
  :class:`MediaPlayerService` on the first round (and wires analytics for
  error recording, Story 19.1) so the service is only created once a media
  player is configured.
* ``_prepare_intro_round`` — thin pass-through to
  ``RoundManager.prepare_intro_round`` (intro-splash deferral decision).
* ``_build_round_metadata`` — thin pass-through to
  ``RoundManager.build_round_metadata`` (initial wire-metadata dict, wiring the
  async metadata fetch coroutine).
* ``_initialize_round`` — commits all round state via
  ``RoundManager.initialize_round`` (timer/deadline, challenge setup, per-player
  round reset), clears ``round_analytics`` and flips to PLAYING through the
  single ``_set_phase`` chokepoint.

Why the cut stops here: the round-*end* path stays on ``GameState``. The shared
``_score_all_players`` loop and ``_end_round_unlocked`` are bound to the
vote-window / scoring coupling and are deliberately NOT moved (see
:class:`~custom_components.beatify.game.state_scoring.RoundScoringMixin`). The
REVEAL transition / auto-advance / reveal-lights helpers
(``_transition_to_reveal``, ``_schedule_reveal_advance``,
``_apply_reveal_lights``) also stay on ``GameState`` — they couple to the TTS,
vote-window and party-lights subsystems. The pause/resume + early-reveal +
``advance_to_end`` terminal helpers stay too; this cut is strictly the forward
round-*start* path.

The mixin relies on attributes / methods the host class owns and that live on
``self`` at runtime:

* ``self.phase`` / ``self._set_phase`` — phase read + the single transition
  chokepoint used by ``start_game`` / ``start_round`` / ``_initialize_round``.
* ``self.players`` — minimum-player-count gate (``start_game``) and the
  per-player round reset list passed to ``RoundManager.initialize_round``.
* ``self._playlist_manager`` — next-song selection, remaining-count
  (``last_round``) and ``mark_played`` for skipped songs.
* ``self.provider`` / ``self.storefront`` / ``self.platform`` /
  ``self.media_player`` — URI resolution and media-player dispatch context.
* ``self._media_player_service`` / ``self._stats_service`` — lazily-built
  playback service + the analytics sink wired into it.
* ``self._round_manager`` — the :class:`RoundManager` the intro/metadata/commit
  helpers delegate to; also supplies ``_timer_countdown`` / ``_on_round_end``
  callbacks.
* ``self._timer_countdown`` / ``self._on_round_end`` / ``self._fetch_metadata_async``
  — round-end + metadata-fetch callbacks/coroutines wired into ``RoundManager``;
  all stay on ``GameState`` (REVEAL coupling) and are referenced via ``self``.
* ``self._tts_service`` / ``self._tts_pre_round_delay`` — the #1211 pre-round
  TTS deadline shift.
* ``self._cancel_auto_advance`` — supersedes a pending REVEAL auto-advance on a
  new round start (#1012); stays on ``GameState``.
* ``self._lights_set_phase`` — party-light phase sync (owned by
  :class:`~custom_components.beatify.game.state_media.MediaControlMixin`).
* ``self.announce_round_start`` / ``self.announce_countdown`` /
  ``self.announce_last_round`` / ``self.announce_intro_round`` — round-start TTS
  announcements (owned by
  :class:`~custom_components.beatify.game.state_tts.TtsAnnouncerMixin`).
* ``self.deadline`` / ``self.round`` / ``self.current_song`` /
  ``self.last_round`` / ``self.round_analytics`` / ``self.is_intro_round`` /
  ``self.total_rounds`` / ``self.last_error_detail`` / ``self._now`` — round
  state read/written across the orchestration.

It carries no state of its own. ``GamePhase`` is imported lazily inside the
methods that need it (``# noqa: PLC0415``) to avoid a top-level circular import
back into ``state.py``; ``MediaPlayerService`` is likewise imported lazily
inside ``_ensure_media_player_service`` (matching the original).
"""

from __future__ import annotations

import asyncio
import logging

from custom_components.beatify.const import (
    ERR_GAME_ALREADY_STARTED,
    ERR_GAME_NOT_STARTED,
    MIN_PLAYERS,
)

from .playlist import get_song_uri

_LOGGER = logging.getLogger(__name__)


class RoundLifecycleMixin:
    """Round-start / round-setup behavior for :class:`GameState`.

    Carries the LOBBY→PLAYING start gate plus the full ``start_round``
    orchestration and its round-setup helpers (#1271 extraction). See the
    module docstring for the full attribute / method contract this mixin
    expects on ``self`` at runtime.
    """

    def start_game(self) -> tuple[bool, str | None]:
        """
        Start the game, transitioning from LOBBY to PLAYING.

        Returns:
            (success, error_code) - error_code is None on success

        """
        from .state import GamePhase  # noqa: PLC0415 — avoid circular import

        if self.phase != GamePhase.LOBBY:
            return False, ERR_GAME_ALREADY_STARTED

        if len(self.players) < MIN_PLAYERS:
            return False, ERR_GAME_NOT_STARTED  # Need at least MIN_PLAYERS to play

        self._set_phase(GamePhase.PLAYING)
        # Round and song selection will be implemented in Epic 4
        _LOGGER.info("Game started: %d players", len(self.players))
        return True, None

    async def start_round(self, _retry_count: int = 0) -> bool:
        """Start a new round with song playback (#390).

        Args:
            _retry_count: Internal counter for failed song attempts (max 3)

        Returns:
            True if round started successfully, False otherwise

        """
        from .state import GamePhase  # noqa: PLC0415 — avoid circular import

        MAX_SONG_RETRIES = 3

        # #1358: snapshot the game-identity epoch at entry. start_round parks in
        # long awaits (verify_responsive, play_song — play_song waits a full
        # Music Assistant timeout). If end_game / rematch_game / create_game runs
        # while we're parked, the epoch advances and we must abort instead of
        # resuming onto a torn-down or replaced game (game_id=None, no players,
        # phase LOBBY) — see _round_start_aborted.
        start_epoch = self._game_epoch

        # #1012: a (manual or auto) round start supersedes any pending
        # REVEAL auto-advance.
        if _retry_count == 0:
            self._cancel_auto_advance()

        if not self._playlist_manager:
            _LOGGER.error("No playlist manager configured")
            return False

        # Get next playable song (skip songs without URI for selected provider)
        song = self._playlist_manager.get_next_song()
        if not song:
            _LOGGER.info("All songs exhausted, ending game")
            self._set_phase(GamePhase.END)
            return False

        resolved_uri = song.get("_resolved_uri")
        if not resolved_uri:
            _LOGGER.warning(
                "Skipping song (year %s) - no URI for provider", song.get("year", "?")
            )
            self._playlist_manager.mark_played(
                get_song_uri(song, self.provider, self.storefront) or song.get("uri")
            )
            if _retry_count >= MAX_SONG_RETRIES:
                _LOGGER.error(
                    "No playable songs found after %d attempts, pausing game",
                    MAX_SONG_RETRIES,
                )
                await self.pause_game("no_songs_available")
                return False
            return await self.start_round(_retry_count + 1)

        self.last_round = self._playlist_manager.get_remaining_count() <= 1
        self._ensure_media_player_service()
        will_defer_for_splash = self._prepare_intro_round(song)

        # Play song via media player (skip if deferred for intro splash)
        if self._media_player_service and not will_defer_for_splash:
            if not self._media_player_service.is_available():
                self.last_error_detail = (
                    f"Media player {self.media_player} is unavailable"
                )
                _LOGGER.error(
                    "Media player %s is not available, pausing game", self.media_player
                )
                await self.pause_game("media_player_error")
                return False

            # Additional responsiveness check for non-MA players
            if self.platform != "music_assistant":
                (
                    responsive,
                    error_detail,
                ) = await self._media_player_service.verify_responsive()
                # #1358: the game may have been torn down / replaced while we
                # waited on verify_responsive — bail before play_song so we
                # don't start music on a dead game.
                if await self._round_start_aborted(start_epoch):
                    return False
                if not responsive:
                    self.last_error_detail = error_detail
                    _LOGGER.error(
                        "Media player not responsive: %s, pausing game", error_detail
                    )
                    await self.pause_game("media_player_error")
                    return False

            success = await self._media_player_service.play_song(song)
            if not success:
                # #808 follow-up: classify the failure. "unavailable" means
                # MA accepted the URI but the speaker stayed on the prior
                # track — typically a region/storefront mismatch (the track
                # ID isn't in the user's catalog). Skip silently and try the
                # next song without counting against MAX_SONG_RETRIES; the
                # user can't fix individual track availability and the game
                # should keep playing the subset that IS available.
                #
                # "error" / unset → systemic failure (speaker offline, MA
                # provider broken). Count toward MAX_SONG_RETRIES so the
                # recovery banner kicks in for real problems.
                failure_reason = getattr(
                    self._media_player_service, "last_failure_reason", None
                )
                self._playlist_manager.mark_played(
                    song.get("_resolved_uri") or song.get("uri")
                )

                if failure_reason == "unavailable":
                    _LOGGER.info(
                        "Skipping unavailable song silently: %s (likely not in "
                        "your provider's storefront/catalog) — trying next song",
                        song.get("title") or song.get("uri"),
                    )
                    await asyncio.sleep(0.2)
                    return await self.start_round(_retry_count)

                # #949: a systemic playback failure — the speaker stayed idle,
                # or the Music Assistant provider is unauthenticated — does not
                # fix itself by retrying. play_song already waited a full MA
                # timeout. Retrying it ~3x more meant ~2 minutes of a silent
                # "Starting..." button before the admin saw anything. Pause
                # now so the recovery banner (which names the provider to
                # re-authenticate) appears within seconds; its Resume button
                # is the manual retry if it really was a transient blip.
                _LOGGER.error(
                    "Playback failed for %s — speaker unreachable, pausing game",
                    song.get("uri"),
                )
                await self.pause_game("media_player_error")
                return False

            # #1358: play_song just succeeded, but it parks for a full Music
            # Assistant timeout — long enough for the admin to end the game
            # (or a rematch / new game) in the meantime. If the game we started
            # for is gone, stop the playback we just kicked off and bail BEFORE
            # _initialize_round stamps PLAYING onto the torn-down game.
            if await self._round_start_aborted(start_epoch, stop_playback=True):
                return False

        metadata = self._build_round_metadata(song, resolved_uri, will_defer_for_splash)
        # Issue #1211: when TTS pre-round announcements are active, shift the
        # deadline forward so the timer doesn't count down during the TTS
        # overhead (e.g. Google Home chime → announcement → chime before music
        # resumes). Default is 0 ms (no change); users configure this via the
        # TTS settings "Timer delay" field.
        extra_ms = 0
        if self._tts_service and self._tts_pre_round_delay > 0:
            extra_ms = int(self._tts_pre_round_delay * 1000)
        self._initialize_round(
            song,
            metadata,
            resolved_uri,
            will_defer_for_splash,
            extra_deadline_ms=extra_ms,
        )

        delay_seconds = (self.deadline - int(self._now() * 1000)) / 1000.0
        await self._lights_set_phase(GamePhase.PLAYING)
        _LOGGER.info(
            "Round %d started: %s - %s (%.1fs timer)",
            self.round,
            self.current_song.get("artist"),
            self.current_song.get("title"),
            delay_seconds,
        )

        # Issue #471 Phase 1: Game Flow announcements at round start.
        # Fired AFTER lights/log so the audio aligns with the user-visible
        # transition. countdown is opt-in (default off) — chained after
        # round_start when both are enabled.
        await self.announce_round_start()
        await self.announce_countdown()
        # Issue #841 Phase 3: flag the final round (use case 17).
        if self.total_rounds > 1 and self.round >= self.total_rounds:
            await self.announce_last_round()
        # Issue #842 Phase 4: flag an intro-mode round (use case 21).
        if self.is_intro_round:
            await self.announce_intro_round()

        return True

    async def _round_start_aborted(
        self, start_epoch: int, *, stop_playback: bool = False
    ) -> bool:
        """Decide whether an in-flight ``start_round`` must bail (#1358).

        Re-validates, after a long await, that the game ``start_round`` was
        launched for is still the live, playable game. Returns ``True`` (abort)
        when either:

        * the game-identity epoch has advanced — ``create_game`` / ``end_game``
          / ``rematch_game`` ran while we were parked (the original game is gone
          or has been replaced; ``end_game``/``rematch`` flip the phase to
          ``LOBBY`` without bumping it back), or
        * the phase has moved to ``PAUSED`` or ``END`` — a concurrent
          ``pause_game`` (which does NOT bump the epoch) or a game-end that
          ``_initialize_round``'s unconditional ``_set_phase(PLAYING)`` would
          otherwise silently undo.

        ``LOBBY`` is deliberately NOT a stand-alone abort trigger: the very
        first round of a game is started straight from ``LOBBY`` (no epoch
        change), so checking ``LOBBY`` directly would abort every legitimate
        first round. An ``end_game``/``rematch`` that lands on ``LOBBY`` is
        instead caught by the epoch bump.

        When ``stop_playback`` is set and we abort, the playback this round
        already started is stopped so the speaker doesn't keep playing on a
        torn-down game.
        """
        from .state import GamePhase  # noqa: PLC0415 — avoid circular import

        if self._game_epoch == start_epoch and self.phase not in (
            GamePhase.END,
            GamePhase.PAUSED,
        ):
            return False

        _LOGGER.info(
            "Aborting start_round: game changed during await (epoch %s→%s, phase %s)",
            start_epoch,
            self._game_epoch,
            self.phase.value,
        )
        if stop_playback and self._media_player_service:
            try:
                await self._media_player_service.stop()
            except Exception as err:  # noqa: BLE001 — a stop error must not raise
                _LOGGER.warning("start_round abort: stop playback failed: %s", err)
        return True

    def _ensure_media_player_service(self) -> None:
        """Create MediaPlayerService lazily on first round."""
        # Lazy import: only the concrete class for instantiation; type hints
        # use MediaPlayerProtocol (module-level) to keep the import graph acyclic.
        from custom_components.beatify.services.media_player import (  # noqa: PLC0415
            MediaPlayerService,
        )

        if self.media_player and not self._media_player_service:
            self._media_player_service = MediaPlayerService(
                self._hass,
                self.media_player,
                platform=self.platform,
                provider=self.provider,
            )
            # Connect analytics for error recording (Story 19.1 AC: #2)
            if self._stats_service and hasattr(self._stats_service, "_analytics"):
                self._media_player_service.set_analytics(self._stats_service._analytics)

    def _prepare_intro_round(self, song: dict) -> bool:
        """Determine if this is an intro round. Delegates to RoundManager."""
        return self._round_manager.prepare_intro_round(song, self._hass)

    def _build_round_metadata(
        self, song: dict, resolved_uri: str, will_defer_for_splash: bool
    ) -> dict:
        """Build initial metadata dict. Delegates to RoundManager."""
        return self._round_manager.build_round_metadata(
            song,
            resolved_uri,
            will_defer_for_splash,
            self._media_player_service,
            # #1402 B2: pass a factory, NOT an eagerly-created coroutine.
            # On intro-splash-deferred rounds (or when no media player is
            # configured) build_round_metadata sets metadata_coro=None — an
            # eagerly-created coroutine would then be dropped un-awaited,
            # leaking it (RuntimeWarning: coroutine never awaited). The factory
            # is only invoked when the fetch is actually needed.
            lambda: self._fetch_metadata_async(resolved_uri),
        )

    def _initialize_round(
        self,
        song: dict,
        metadata: dict,
        resolved_uri: str,
        will_defer_for_splash: bool,
        extra_deadline_ms: int = 0,
    ) -> None:
        """Commit all round state. Delegates to RoundManager."""
        from .state import GamePhase  # noqa: PLC0415 — avoid circular import

        self._round_manager.initialize_round(
            song,
            metadata,
            resolved_uri,
            will_defer_for_splash,
            self._playlist_manager,
            self._challenge_manager,
            self.players,
            self._timer_countdown,
            self._on_round_end,
            extra_deadline_ms=extra_deadline_ms,
        )
        self.round_analytics = None
        # #1273: transition clears reveal_started_at (#1048) + notifies (#441).
        self._set_phase(GamePhase.PLAYING)
