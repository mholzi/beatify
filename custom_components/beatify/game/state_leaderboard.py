"""Leaderboard subsystem for :class:`GameState`.

Issue #1271 next-increment extraction: the leaderboard / ranking cluster
(``get_leaderboard``, ``_store_previous_ranks``, ``get_final_leaderboard`` —
originally Stories 5.5 / 5.6) is pulled out of the ``game/state.py``
God-Object into this ``LeaderboardMixin``.

The mixin is **behavior-preserving**: it carries the exact same methods that
previously lived on ``GameState``. ``GameState`` inherits them, so its public
API and every caller / test are unchanged.

The mixin relies on a single attribute the host class owns and that lives on
``self`` at runtime:

* ``self.players`` — mapping of player name → ``PlayerSession``. Each session
  exposes ``score``, ``name``, ``streak``, ``is_admin``, ``connected``,
  ``previous_rank``, ``best_streak``, ``rounds_played`` and ``bets_won``.

It carries no state of its own and imports nothing from ``state.py``, so the
extraction introduces no cyclic imports.
"""

from __future__ import annotations

from typing import Any


class LeaderboardMixin:
    """Leaderboard / ranking behavior for :class:`GameState`.

    See module docstring for the host-class attributes this mixin reads.
    """

    def get_leaderboard(self) -> list[dict[str, Any]]:
        """
        Get the in-round leaderboard sorted by score (Story 5.5).

        #1765: entries carry ONLY ``{rank, name, rank_change}``. Every other
        per-player field (score, streak, is_admin, connected, eliminated,
        eliminated_round) is already present in the ``players`` array of the
        same broadcast frame, so duplicating it here shipped ~30-40% redundant
        bytes on every PLAYING/REVEAL frame (and serialized it twice). Clients
        re-attach those fields from ``players`` by name on receipt
        (``BeatifyUtils.hydrateLeaderboard``). ``get_final_leaderboard`` (END
        phase, sent once) keeps the full stat block.

        Returns:
            List of ``{rank, name, rank_change}`` sorted by score, then name.
            Note: is_current is set client-side based on playerName.

        """
        # Sort by score descending, then by name for tie-breaking display order
        sorted_players = sorted(
            self.players.values(),
            key=lambda p: (-p.score, p.name),
        )

        leaderboard = []
        current_rank = 0
        previous_score = None

        for i, player in enumerate(sorted_players):
            # Handle ties (same score = same rank)
            # Example: scores [100, 80, 80, 50] -> ranks [1, 2, 2, 4]
            if player.score != previous_score:
                current_rank = i + 1  # Rank jumps to position (skips tied ranks)
            previous_score = player.score

            # Calculate rank change (positive = moved up)
            rank_change = 0
            if player.previous_rank is not None:
                rank_change = player.previous_rank - current_rank

            leaderboard.append(
                {
                    "rank": current_rank,
                    "name": player.name,
                    "rank_change": rank_change,
                }
            )

        return leaderboard

    def _store_previous_ranks(self) -> None:
        """Store current ranks before scoring for rank change detection."""
        sorted_players = sorted(
            self.players.values(),
            key=lambda p: (-p.score, p.name),
        )

        current_rank = 0
        previous_score = None

        for i, player in enumerate(sorted_players):
            if player.score != previous_score:
                current_rank = i + 1
            previous_score = player.score
            player.previous_rank = current_rank

    def get_final_leaderboard(self) -> list[dict[str, Any]]:
        """
        Get final leaderboard with full player stats (Story 5.6).

        Returns:
            List of player data with rank and final stats.
            Note: is_current is set client-side based on playerName.

        """
        # Issue #827: in a Sudden Death game the finish order IS the survival
        # order — the last one standing is 1st, then players in reverse
        # elimination order (eliminated latest = higher), score breaking ties.
        # Ranks are sequential (no score-tie grouping) because survival is a
        # total order. Falls back to the score sort for normal games.
        sudden_death = self.sudden_death_mode and any(
            p.eliminated for p in self.players.values()
        )
        if sudden_death:
            sorted_players = sorted(
                self.players.values(),
                key=lambda p: (
                    p.eliminated,
                    -(p.eliminated_round or 0),
                    -p.score,
                    p.name,
                ),
            )
        else:
            # Sort by score descending, then by name for tie-breaking display order
            sorted_players = sorted(
                self.players.values(),
                key=lambda p: (-p.score, p.name),
            )

        leaderboard = []
        current_rank = 0
        previous_score = None

        for i, player in enumerate(sorted_players):
            if sudden_death:
                current_rank = i + 1
            elif player.score != previous_score:
                current_rank = i + 1
            previous_score = player.score

            entry = {
                "rank": current_rank,
                "name": player.name,
                "score": player.score,
                "is_admin": player.is_admin,
                "connected": player.connected,
                # Final stats (Story 5.6)
                "best_streak": player.best_streak,
                "rounds_played": player.rounds_played,
                "bets_won": player.bets_won,
                # Issue #827: Sudden Death
                "eliminated": player.eliminated,
                "eliminated_round": player.eliminated_round,
            }
            leaderboard.append(entry)

        return leaderboard
