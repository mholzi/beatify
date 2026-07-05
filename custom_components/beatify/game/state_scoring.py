"""Round-scoring & round-stats subsystem for :class:`GameState`.

Issue #1271 next-increment extraction (stacked on the vote-window cut
:class:`~custom_components.beatify.game.state_vote_window.VoteWindowMixin`):
the **round-end scoring pass + round-stats/highlights recording** cluster is
pulled out of the ``game/state.py`` God-Object into this
``RoundScoringMixin``.

The cluster is the synchronous + persisted bookkeeping half of the round-end
orchestration (``_end_round_unlocked`` phases 2 & 3). It is **behavior-
preserving**: it carries the exact same methods that previously lived on
``GameState``, so its public API and every caller / test are unchanged.

* ``_score_round`` — the round's scoring pass: runs the shared per-player
  scoring loop (``_score_all_players``, except deferred title/artist
  near-misses), applies Closest-Wins zeroing (#442), and classifies the
  per-player ``round_results`` (#120).
* ``_record_round_stats`` — records highlights (#75), computes round analytics
  (Story 13.3), and persists per-song results for difficulty tracking
  (Story 15.1 / 19.7). Each block keeps its own defensive wrap so a stats
  hiccup never blocks the REVEAL transition.
* ``_record_round_highlights`` — detects and records the round's highlight
  events (exact match, heartbreaker, streak, bet win, comeback, speed record,
  photo finish) into the :class:`HighlightsTracker` (#75/#414).

Why the cut stops here: the deliberately-excluded
``_score_all_players`` per-player scoring loop **stays on** ``GameState`` —
the vote-window path (``_finalize_title_artist_window``) reuses it via
``self._score_all_players`` so the round-end and deferred-rescore paths cannot
drift; moving it would split a single source of truth across two mixins. The
REVEAL announcement / phase-flip / auto-advance / party-light helpers
(``_transition_to_reveal``, ``_schedule_reveal_advance``, ``_apply_reveal_lights``)
also stay on ``GameState`` — they couple to the TTS, vote-window and
party-lights subsystems and are out of scope for this scoring-only cut.

The mixin relies on attributes / methods the host class owns and that live on
``self`` at runtime:

* ``self._score_all_players`` — the shared per-player scoring loop (owned by
  ``GameState``); the deferred title/artist near-miss path is skipped here.
* ``self.players`` / ``self.current_song`` / ``self.round`` /
  ``self.round_start_time`` — round state read while scoring.
* ``self.title_artist_mode`` / ``self.has_near_misses`` — gate the deferred
  title/artist scoring path (#1180 Phase 4).
* ``self._challenge_manager`` — :class:`ChallengeManager`; its
  ``title_artist_round_result`` classifies ``round_results`` from the resolved
  field statuses in title/artist mode (#1373).
* ``self.closest_wins_mode`` / ``self.difficulty`` — Closest-Wins + scoring
  config selection.
* ``self.calculate_round_analytics`` — Story 13.3 analytics (delegates to
  ``ScoringService``); the result is stored on ``self.round_analytics``.
* ``self._stats_service`` — optional persisted song-result stats sink.
* ``self.playlists`` — used to derive the playlist name for stats.
* ``self.highlights_tracker`` — the :class:`HighlightsTracker` sink for the
  round's highlight events.
* ``self._lights_flash`` / ``self._bg_tasks`` — fire-and-forget party-light
  flash on streak milestones (#75).

It carries no state of its own. ``Counter`` is imported lazily inside
``_record_round_highlights`` (matching the original inline import) to keep the
module top-level import surface minimal.
"""

from __future__ import annotations

import asyncio
import logging

from custom_components.beatify.const import (
    DIFFICULTY_DEFAULT,
    DIFFICULTY_SCORING,
    STREAK_MILESTONES,
)

from .playlist import get_playback_uri
from .scoring import ScoringService

_LOGGER = logging.getLogger(__name__)


class RoundScoringMixin:
    """Round-scoring & round-stats behavior for :class:`GameState`.

    Carries the round-end scoring pass plus highlights / analytics / song-result
    recording (#1271 extraction). See the module docstring for the full
    attribute / method contract this mixin expects on ``self`` at runtime.
    """

    def _score_round(self, correct_year: int | None) -> None:
        """Run the round's scoring pass (#1272 — extracted from end_round).

        Sync; caller holds _score_lock (matches the prior inline behaviour —
        no lock is acquired here). Mutates player scores / round_results in
        place. Covers: ScoringService scoring, Closest-Wins zeroing, and the
        per-player round_results classification.
        """
        # Calculate scores for all players — delegates to ScoringService (#139).
        # #816: wrap in try/except so an unexpected state shape in ONE player
        # doesn't abort the whole round-end transition. Without this, a
        # ScoringService exception bubbles up before line 1573 (where phase
        # gets set to REVEAL) and broadcast_state never fires — the UI
        # stays frozen on the PLAYING screen with the timer at 0. Per-player
        # isolation: if one player's scoring fails, the rest still score and
        # the round still ends.
        all_players = list(self.players.values())
        # #1180 Phase 4: in title/artist mode with vote-eligible near-misses,
        # the per-player score depends on the final near-miss resolution, which
        # only happens after the REVEAL vote window closes. Defer scoring those
        # players to _finalize_title_artist_window (scored exactly once, after
        # resolve) so the leaderboard reflects accepted near-misses without the
        # main loop and the rescore double-counting. With no near-misses the
        # challenge resolves immediately, so scoring here is already final.
        # #1747: shared predicate with the Sudden Death elimination gate in
        # _end_round_unlocked so the two paths never disagree on whether scores
        # are final yet.
        defer_title_artist = self._title_artist_scoring_deferred()
        if not defer_title_artist:
            self._score_all_players(correct_year, all_players)

        # Issue #442: Closest Wins — zero out non-closest players' scores.
        # #816: same defensive wrap as above.
        if self.closest_wins_mode and correct_year is not None:
            try:
                ScoringService.apply_closest_wins(
                    all_players, correct_year, self.streak_achievements
                )
            except (KeyError, AttributeError, TypeError, ValueError) as err:
                _LOGGER.error(
                    "apply_closest_wins failed in round %d: %s — round still ends",
                    self.round,
                    err,
                )

        # Issue #120: Track round results for shareable result cards.
        # #1373: in title/artist mode with deferred near-miss scoring, the field
        # statuses aren't final until _finalize_title_artist_window — defer the
        # round_results append to that path too, so it classifies the resolved
        # statuses instead of marking the round "missed".
        if correct_year is not None and not defer_title_artist:
            self._append_round_results()

    def _append_round_results(self) -> None:
        """Append one round_results entry per player (#120, #1373).

        Year mode classifies from player.years_off; title/artist mode classifies
        from the resolved field statuses (years_off is always None there, which
        would otherwise mark every round "missed" — #1373). Called from the main
        scoring pass for year / non-deferred rounds, and from
        _finalize_title_artist_window once deferred near-misses are resolved.

        #816: each player is wrapped so a corrupt player state doesn't block the
        round-end transition.
        """
        title_artist_mode = self.title_artist_mode
        manager = self._challenge_manager if title_artist_mode else None
        scoring_cfg = DIFFICULTY_SCORING.get(
            self.difficulty, DIFFICULTY_SCORING[DIFFICULTY_DEFAULT]
        )
        close_range = scoring_cfg["close_range"]
        near_range = scoring_cfg["near_range"]
        for player in self.players.values():
            try:
                if title_artist_mode and manager is not None:
                    player.round_results.append(
                        manager.title_artist_round_result(player.name)
                    )
                elif player.submitted and player.years_off is not None:
                    if player.years_off == 0:
                        player.round_results.append("exact")
                    elif close_range > 0 and player.years_off <= close_range:
                        player.round_results.append("scored")
                    elif near_range > 0 and player.years_off <= near_range:
                        player.round_results.append("close")
                    else:
                        player.round_results.append("missed")
                else:
                    player.round_results.append("missed")
            except (AttributeError, TypeError) as err:
                _LOGGER.error(
                    "round_results append failed for player %s: %s",
                    getattr(player, "name", "?"),
                    err,
                )

    async def _record_round_stats(self, correct_year: int | None) -> None:
        """Record highlights, round analytics and song-result stats (#1272).

        Extracted from end_round; runs after scoring, before REVEAL. Each block
        keeps its own defensive wrap so a stats hiccup never blocks the REVEAL
        transition. No lock is acquired (caller holds _score_lock).
        """
        # Issue #75: Record highlights after scoring
        try:
            self._record_round_highlights(correct_year)
        except (KeyError, AttributeError, TypeError, ValueError) as err:
            _LOGGER.error("Failed to record round highlights: %s", err)

        # Issue #23: Music continues playing through reveal for intro rounds.
        # No resume needed — _intro_auto_stop no longer pauses playback.

        # Calculate round analytics after scoring (Story 13.3)
        try:
            self.round_analytics = self.calculate_round_analytics()
        except (
            KeyError,
            AttributeError,
            TypeError,
            ValueError,
            ZeroDivisionError,
        ) as err:
            _LOGGER.error("Failed to calculate round analytics: %s", err)
            self.round_analytics = None

        # Record song results for difficulty tracking (Story 15.1 AC3)
        # Extended for song statistics (Story 19.7)
        # Wrapped in try/catch to ensure round transition completes even if stats fail
        if self._stats_service and self.current_song:
            song_uri = get_playback_uri(self.current_song)
            if song_uri:
                try:
                    # Build player results list for song difficulty calculation
                    player_results = [
                        {
                            "submitted": p.submitted,
                            "years_off": p.years_off if p.years_off is not None else 0,
                        }
                        for p in self.players.values()
                    ]
                    # Story 19.7: Pass song metadata and playlist info
                    song_metadata = {
                        "title": self.current_song.get("title", "Unknown"),
                        "artist": self.current_song.get("artist", "Unknown"),
                        "year": self.current_song.get("year", 0),
                    }
                    # Extract playlist name from path (e.g., "greatest-hits.json" -> "Greatest Hits")
                    playlist_name = None
                    if self.playlists:
                        playlist_path = self.playlists[0]
                        playlist_name = (
                            playlist_path.replace(".json", "").replace("-", " ").title()
                        )
                    await self._stats_service.record_song_result(
                        song_uri,
                        player_results,
                        song_metadata=song_metadata,
                        playlist_name=playlist_name,
                        difficulty=self.difficulty,
                    )
                except (OSError, KeyError, TypeError, ValueError) as err:
                    _LOGGER.error("Failed to record song results: %s", err)

    def _record_round_highlights(self, correct_year: int | None) -> None:
        """Detect and record highlights for the current round (Issue #75)."""
        if correct_year is None:
            return

        song_title = ""
        if self.current_song:
            song_title = self.current_song.get("title", "Unknown")

        submitted_players = [
            p
            for p in self.players.values()
            if p.submitted and p.current_guess is not None
        ]

        sorted_players = sorted(self.players.values(), key=lambda p: (-p.score, p.name))
        rank_map = {p.name: i + 1 for i, p in enumerate(sorted_players)}

        for player in submitted_players:
            # Exact match
            if player.years_off == 0:
                self.highlights_tracker.record_exact_match(
                    player.name, song_title, correct_year, self.round
                )

            # Heartbreaker (off by 1)
            if player.years_off == 1:
                self.highlights_tracker.record_heartbreaker(
                    player.name, song_title, 1, self.round
                )

            # Streak milestones
            if player.streak in STREAK_MILESTONES:
                self.highlights_tracker.record_streak(
                    player.name, player.streak, self.round
                )
                # Fire-and-forget flash (sync context — cannot await)
                task = asyncio.create_task(self._lights_flash("orange"))
                self._bg_tasks.add(task)
                task.add_done_callback(self._bg_tasks.discard)

            # Bet win
            if player.bet_outcome == "won" and player.round_score >= 10:
                self.highlights_tracker.record_bet_win(
                    player.name, player.round_score, self.round
                )

            # Comeback (gained 2+ positions)
            if player.previous_rank is not None:
                current_rank = rank_map.get(player.name)
                if current_rank is not None:
                    positions_gained = player.previous_rank - current_rank
                    if positions_gained >= 2:
                        self.highlights_tracker.record_comeback(
                            player.name, positions_gained, self.round
                        )

        # Speed record (fastest submission this round)
        timed = [
            (p, p.submission_time - self.round_start_time)
            for p in submitted_players
            if p.submission_time is not None and self.round_start_time is not None
        ]
        if timed:
            fastest_player, fastest_time = min(timed, key=lambda x: x[1])
            if fastest_time < 5.0:  # Only highlight very fast answers
                self.highlights_tracker.record_speed_record(
                    fastest_player.name, fastest_time, self.round
                )

        # Photo finish (tied round scores among top players) — Issue #414
        scores = [p.round_score for p in self.players.values()]
        if len(scores) >= 2:
            from collections import Counter

            score_counts = Counter(scores)
            for score, count in score_counts.items():
                if count >= 2 and score > 0:
                    tied_names = [
                        p.name for p in self.players.values() if p.round_score == score
                    ]
                    # Only record if it's among the top scores
                    top_score = max(scores)
                    if score >= top_score * 0.8:
                        self.highlights_tracker.record_photo_finish(
                            tied_names, self.round
                        )
                        break  # Only one photo finish per round
