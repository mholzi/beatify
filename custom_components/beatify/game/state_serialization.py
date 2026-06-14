"""State-serialization & game-summary subsystem for :class:`GameState`.

Issue #1271 next-increment extraction (stacked on the round-scoring cut
:class:`~custom_components.beatify.game.state_scoring.RoundScoringMixin`):
the **state-serialization + game-summary / performance dict-builder** cluster
is pulled out of the ``game/state.py`` God-Object into this
``StateSerializationMixin``.

The cluster is the read-only "turn GameState into a wire/summary dict for the
frontend and the :class:`StatsService`" half of the class. It is **behavior-
preserving**: it carries the exact same methods that previously lived on
``GameState``, so its public API and every caller / test are unchanged.

* ``get_state`` — broadcast snapshot for the frontend (#464); a thin wrapper
  that delegates the actual view assembly to
  :class:`~custom_components.beatify.game.serializers.GameStateSerializer`.
* ``get_reveal_players_state`` — REVEAL-phase per-player view rows (#464); also
  delegated to ``GameStateSerializer``.
* ``set_stats_service`` — wires the optional :class:`StatsService` reference
  used by the summary / performance / difficulty builders below.
* ``get_song_difficulty`` — difficulty lookup for a song URI; delegates to the
  wired ``StatsService`` (or ``None`` when unset).
* ``finalize_game`` — builds the end-of-game summary dict (Story 14.4): winner
  (incl. tie detection), totals, average-per-round, playlist name, and the
  streak / bet aggregates. Must run BEFORE ``end_game()`` so the totals are
  still present. Consumed by ``StatsService.record_game()``.
* ``_calculate_current_avg`` — helper for the live game's average score per
  round (Story 14.4), used by ``get_game_performance`` for the all-time
  comparison.
* ``get_game_performance`` — builds the motivational performance-comparison
  dict shown in REVEAL / END (Story 14.4); returns ``None`` when no
  ``StatsService`` is connected. Both ``GameStateSerializer`` REVEAL/END paths
  call this on ``self``.

Why the cut stops here: the heavy view-assembly logic already lives in
``game/serializers.py`` (:class:`GameStateSerializer`, #464); this mixin only
carries the GameState-side entry points + the summary/performance dict builders
that read live game state directly. The per-player leaderboard rows
(``get_players_state`` etc.) stay in
:class:`~custom_components.beatify.game.state_player.PlayerLifecycleMixin` and
the ranking in
:class:`~custom_components.beatify.game.state_leaderboard.LeaderboardMixin`;
this cut deliberately touches neither so the two cannot drift.

The mixin relies on attributes / methods the host class owns and that live on
``self`` at runtime:

* ``self.players`` — player map read for totals / winner / averages.
* ``self.round`` — rounds-played count for the summary + average.
* ``self.playlists`` — used to derive the playlist name for the summary.
* ``self.streak_achievements`` / ``self.bet_tracking`` — power-up aggregates
  folded into the summary dict (Story 19.11 / 19.12).
* ``self._stats_service`` — optional :class:`StatsService`; gates the
  difficulty / performance builders and is the summary's downstream consumer.

It carries no state of its own. ``GameStateSerializer`` is imported lazily
inside the two view delegators (``# noqa: PLC0415``) to avoid a top-level
import cycle (``serializers`` imports from this package), matching the lazy-
import discipline of the sibling state_*.py mixins.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

_LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from custom_components.beatify.game.player import PlayerSession
    from custom_components.beatify.services.stats import StatsService


class StateSerializationMixin:
    """State-serialization & game-summary behavior for :class:`GameState`.

    Carries the frontend/StatsService serialization entry points plus the
    end-of-game summary and live performance-comparison dict builders (#1271
    extraction). See the module docstring for the full attribute / method
    contract this mixin expects on ``self`` at runtime.
    """

    def get_state(self) -> dict[str, Any] | None:
        """Get current game state for broadcast.

        Delegates to GameStateSerializer (Issue #464).

        Returns:
            Game state dict or None if no active game

        """
        from .serializers import GameStateSerializer  # noqa: PLC0415

        return GameStateSerializer.serialize(self)

    def get_reveal_players_state(self) -> list[dict[str, Any]]:
        """Get player state with reveal info for REVEAL phase.

        Delegates to GameStateSerializer (Issue #464).

        Returns:
            List of player dicts including guess, round_score, years_off,
            speed bonus data (Story 5.1), streak bonus (Story 5.2),
            and artist bonus (Story 20.4), sorted by total score descending.

        """
        from .serializers import GameStateSerializer  # noqa: PLC0415

        return GameStateSerializer.get_reveal_players_state(self)

    def set_stats_service(self, stats_service: StatsService) -> None:
        """
        Set stats service reference (Story 14.4).

        Args:
            stats_service: StatsService instance for game performance tracking

        """
        self._stats_service = stats_service
        _LOGGER.info("Stats service connected to GameState")

    def get_song_difficulty(self, song_uri: str) -> dict[str, Any] | None:
        """Get song difficulty rating — delegated to StatsService."""
        if self._stats_service:
            return self._stats_service.get_song_difficulty(song_uri)
        return None

    def compute_winners(self) -> tuple[list[PlayerSession], int]:
        """Return the top-scoring player(s) and the top score (#1402 B2).

        Single source of truth for the "who won" computation that both
        ``finalize_game`` (the StatsService summary) and the END-state
        serializer (``GameStateSerializer._add_end_state``) need — previously
        the ``max`` + tie-detection loop was duplicated in both, so a change to
        one (e.g. a different tie rule) could silently diverge from the other.

        Returns:
            A ``(winners, top_score)`` tuple. ``winners`` is every player whose
            score equals the maximum (length > 1 means a tie); ``top_score`` is
            that maximum. With no players, returns ``([], 0)``.
        """
        if not self.players:
            return [], 0
        # Issue #827: in Sudden Death the winner is the last player standing,
        # regardless of cumulative score — provided the game actually ran to its
        # conclusion (at least one elimination and exactly one survivor). Falls
        # through to the score-based winner when Sudden Death is off or the game
        # ended without resolving (e.g. force-ended early).
        if self.sudden_death_mode:
            survivors = [p for p in self.players.values() if not p.eliminated]
            if len(survivors) == 1 and any(
                p.eliminated for p in self.players.values()
            ):
                return survivors, survivors[0].score
        top_score = max(p.score for p in self.players.values())
        winners = [p for p in self.players.values() if p.score == top_score]
        return winners, top_score

    def finalize_game(self) -> dict[str, Any]:
        """
        Calculate final stats before ending the game (Story 14.4).

        Must be called BEFORE end_game() to capture statistics.
        Returns summary dict for StatsService.record_game().

        Returns:
            Game summary dict with playlist, rounds, player_count,
            winner, winner_score, total_points, avg_score_per_round

        """
        # Calculate totals
        total_points = sum(p.score for p in self.players.values())
        player_count = len(self.players)
        rounds_played = self.round

        # Determine winner(s) — detect ties (#1402 B2: shared helper).
        winner_name = "Unknown"
        winners, winner_score = self.compute_winners()
        if winners:
            if len(winners) == 1:
                winner_name = winners[0].name
            else:
                winner_name = ", ".join(w.name for w in winners)

        # Calculate average score per round
        avg_score_per_round = 0.0
        if rounds_played > 0 and player_count > 0:
            avg_score_per_round = total_points / (rounds_played * player_count)

        # Determine playlist name (use first playlist or "mixed")
        playlist_name = "unknown"
        if self.playlists:
            # Extract playlist name from path
            playlist_path = self.playlists[0]
            if "/" in playlist_path:
                playlist_name = playlist_path.split("/")[-1].replace(".json", "")
            else:
                playlist_name = playlist_path.replace(".json", "")

        return {
            "playlist": playlist_name,
            "rounds": rounds_played,
            "player_count": player_count,
            "winner": winner_name,
            "winner_score": winner_score,
            "total_points": total_points,
            "avg_score_per_round": round(avg_score_per_round, 2),
            # Story 19.11: Include streak achievements
            "streak_3_count": self.streak_achievements.get("streak_3", 0),
            "streak_5_count": self.streak_achievements.get("streak_5", 0),
            "streak_10_count": self.streak_achievements.get("streak_10", 0),
            # Story 19.12: Include bet tracking
            "total_bets": self.bet_tracking.get("total_bets", 0),
            "bets_won": self.bet_tracking.get("bets_won", 0),
        }

    def _calculate_current_avg(self) -> float:
        """
        Calculate current game's average score per round (Story 14.4).

        Used for in-game comparison to all-time average.

        Returns:
            Current game average score per round, or 0.0 if no data

        """
        if self.round == 0 or not self.players:
            return 0.0

        total_points = sum(p.score for p in self.players.values())
        player_count = len(self.players)

        return total_points / (self.round * player_count)

    def get_game_performance(self) -> dict[str, Any] | None:
        """
        Get game performance comparison data (Story 14.4).

        Used during REVEAL and END phases to show motivational feedback.

        Returns:
            Performance dict with comparison data, or None if no stats service

        """
        if not self._stats_service:
            _LOGGER.debug("get_game_performance: No stats service connected")
            return None

        current_avg = self._calculate_current_avg()
        comparison = self._stats_service.get_game_comparison(current_avg)
        message_data = self._stats_service.get_motivational_message(comparison)

        return {
            "current_avg": round(current_avg, 2),
            "all_time_avg": comparison["all_time_avg"],
            "difference": comparison["difference"],
            "is_above_average": comparison["is_above_average"],
            "is_new_record": comparison["is_new_record"],
            "is_first_game": comparison["is_first_game"],
            "message": message_data,
        }
