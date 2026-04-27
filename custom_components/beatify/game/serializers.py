"""Game state serialization for Beatify (Issue #464).

Extracts ``get_state()`` and ``get_reveal_players_state()`` view logic
from GameState into a standalone serializer so the god object does not
own its own presentation layer.

GameState.get_state() becomes a thin wrapper calling
``GameStateSerializer.serialize(game_state)``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .state import GameState

_LOGGER = logging.getLogger(__name__)


class GameStateSerializer:
    """Builds broadcast-ready dicts from GameState.

    All methods are static — the serializer is stateless and receives
    the GameState instance as an explicit argument.
    """

    @staticmethod
    def serialize(gs: GameState) -> dict[str, Any] | None:
        """Build the phase-specific state dict for WebSocket broadcast.

        Returns:
            Game state dict or None if no active game.

        """
        if not gs.game_id:
            return None

        state: dict[str, Any] = {
            "game_id": gs.game_id,
            "phase": gs.phase.value,
            "player_count": len(gs.players),
            "players": gs.get_players_state(),
            "language": gs.language,
            "difficulty": gs.difficulty,
            # Issue #23: Intro mode (available in all phases)
            "intro_mode_enabled": gs.intro_mode_enabled,
            # Issue #442: Closest Wins mode
            "closest_wins_mode": gs.closest_wins_mode,
            "is_intro_round": gs.is_intro_round,
            "intro_stopped": gs.intro_stopped,
            "intro_splash_pending": gs.intro_splash_pending,
        }

        from .state import GamePhase  # noqa: PLC0415

        # Phase-specific data
        if gs.phase == GamePhase.LOBBY:
            state["join_url"] = gs.join_url

        elif gs.phase == GamePhase.PLAYING:
            GameStateSerializer._add_playing_state(gs, state)

        elif gs.phase == GamePhase.REVEAL:
            GameStateSerializer._add_reveal_state(gs, state)

        elif gs.phase == GamePhase.PAUSED:
            state["pause_reason"] = gs.pause_reason
            # #805: surface human-readable error detail so the admin sees
            # *why* the game paused instead of staring at a blank "⏸ Paused"
            # label. Empty string for non-error pauses (admin disconnect etc).
            state["last_error_detail"] = gs.last_error_detail or ""
            # #808 follow-up: surface the user's selected music provider so
            # the recovery banner can name it ("Re-authenticate Apple Music
            # in Music Assistant") instead of generic "your music provider".
            # The unauthenticated-MA-provider failure mode is the most
            # common cause of media_player_error pauses on MA setups.
            state["provider"] = gs.provider

        elif gs.phase == GamePhase.END:
            GameStateSerializer._add_end_state(gs, state)

        return state

    @staticmethod
    def _add_playing_state(gs: GameState, state: dict[str, Any]) -> None:
        """Populate PLAYING-phase fields."""
        state["join_url"] = gs.join_url
        state["round"] = gs.round
        state["total_rounds"] = gs.total_rounds
        state["deadline"] = gs.deadline
        state["last_round"] = gs.last_round
        state["songs_remaining"] = gs.songs_remaining
        # Submission tracking (Story 4.4)
        state["submitted_count"] = sum(1 for p in gs.players.values() if p.submitted)
        state["all_submitted"] = gs.all_submitted()
        # Song info WITHOUT year during PLAYING (hidden until reveal)
        if gs.current_song:
            state["song"] = {
                "artist": gs.current_song.get("artist", "Unknown"),
                "title": gs.current_song.get("title", "Unknown"),
                "album_art": gs.current_song.get(
                    "album_art", "/beatify/static/img/no-artwork.svg"
                ),
            }
            # #648: Admin-only song details (year, fun facts) — players ignore this
            state["admin_song"] = {
                "year": gs.current_song.get("year"),
                "fun_fact": gs.current_song.get("fun_fact", ""),
                "fun_fact_de": gs.current_song.get("fun_fact_de", ""),
                "fun_fact_es": gs.current_song.get("fun_fact_es", ""),
                "fun_fact_fr": gs.current_song.get("fun_fact_fr", ""),
                "fun_fact_nl": gs.current_song.get("fun_fact_nl", ""),
            }
        # Leaderboard (Story 5.5)
        state["leaderboard"] = gs.get_leaderboard()
        # Story 20.1: Artist challenge (hide answer during PLAYING)
        ac = gs.get_artist_challenge_dict(include_answer=False)
        if ac is not None:
            state["artist_challenge"] = ac
        # Issue #28: Movie quiz challenge (hide answer during PLAYING)
        mc = gs.get_movie_challenge_dict(include_answer=False)
        if mc is not None:
            state["movie_challenge"] = mc

    @staticmethod
    def _add_reveal_state(gs: GameState, state: dict[str, Any]) -> None:
        """Populate REVEAL-phase fields."""
        state["join_url"] = gs.join_url
        state["round"] = gs.round
        state["total_rounds"] = gs.total_rounds
        state["last_round"] = gs.last_round
        # Filtered song info during REVEAL — exclude URIs, alt_artists, internal fields
        if gs.current_song:
            state["song"] = {
                "artist": gs.current_song.get("artist", "Unknown"),
                "title": gs.current_song.get("title", "Unknown"),
                "year": gs.current_song.get("year"),
                "album_art": gs.current_song.get(
                    "album_art", "/beatify/static/img/no-artwork.svg"
                ),
                "fun_fact": gs.current_song.get("fun_fact", ""),
                "fun_fact_de": gs.current_song.get("fun_fact_de", ""),
                "fun_fact_es": gs.current_song.get("fun_fact_es", ""),
                "fun_fact_fr": gs.current_song.get("fun_fact_fr", ""),
                "fun_fact_nl": gs.current_song.get("fun_fact_nl", ""),
            }
        # Include reveal-specific player data (guesses, round_score, missed)
        state["players"] = GameStateSerializer.get_reveal_players_state(gs)
        # Leaderboard (Story 5.5)
        state["leaderboard"] = gs.get_leaderboard()
        # Round analytics (Story 13.3 AC4)
        if gs.round_analytics:
            state["round_analytics"] = gs.round_analytics.to_dict()
        # Game performance comparison (Story 14.4 AC2, AC3, AC4, AC6)
        game_performance = gs.get_game_performance()
        if game_performance:
            state["game_performance"] = game_performance
        # Song difficulty rating (Story 15.1 AC1, AC4)
        if gs.current_song:
            song_uri = gs.current_song.get("_resolved_uri") or gs.current_song.get(
                "uri"
            )
            if song_uri:
                difficulty = gs.get_song_difficulty(song_uri)
                if difficulty:
                    state["song_difficulty"] = difficulty
        # Story 20.1: Artist challenge (reveal answer during REVEAL)
        ac = gs.get_artist_challenge_dict(include_answer=True)
        if ac is not None:
            state["artist_challenge"] = ac
        # Issue #28: Movie quiz challenge (reveal answer + results during REVEAL)
        mc = gs.get_movie_challenge_dict(include_answer=True)
        if mc is not None:
            state["movie_challenge"] = mc
        # Story 20.9: Early reveal flag for client-side toast
        if gs.early_reveal:
            state["early_reveal"] = True

    @staticmethod
    def _add_end_state(gs: GameState, state: dict[str, Any]) -> None:
        """Populate END-phase fields."""
        # Final leaderboard with all player stats (Story 5.6)
        state["leaderboard"] = gs.get_final_leaderboard()
        state["game_stats"] = {
            "total_rounds": gs.round,
            "total_players": len(gs.players),
        }
        # Include winner info — detect ties
        if gs.players:
            top_score = max(p.score for p in gs.players.values())
            winners = [p for p in gs.players.values() if p.score == top_score]
            state["winner"] = {
                "name": ", ".join(w.name for w in winners),
                "score": top_score,
                "is_tie": len(winners) > 1,
            }
        # Game performance comparison for end screen (Story 14.4 AC5, AC6)
        game_performance = gs.get_game_performance()
        if game_performance:
            state["game_performance"] = game_performance
        # Superlatives - fun awards (Story 15.2)
        state["superlatives"] = gs.calculate_superlatives()
        # Issue #75: Game highlights reel
        state["highlights"] = gs.highlights_tracker.to_dict()
        # Issue #120: Shareable result cards
        from .share import build_share_data  # noqa: PLC0415

        state["share_data"] = build_share_data(gs)

    @staticmethod
    def get_reveal_players_state(gs: GameState) -> list[dict[str, Any]]:
        """Build player state with reveal info for REVEAL phase.

        Returns:
            List of player dicts including guess, round_score, years_off,
            speed bonus data, streak bonus, and artist/movie/intro bonuses,
            sorted by total score descending.

        """
        players = []
        for p in gs.players.values():
            player_data = {
                "name": p.name,
                "score": p.score,
                "streak": p.streak,
                "is_admin": p.is_admin,
                "connected": p.connected,
                "guess": p.current_guess,
                "round_score": p.round_score,
                "years_off": p.years_off,
                "missed_round": p.missed_round,
                # Speed bonus data (Story 5.1)
                "base_score": p.base_score,
                "speed_multiplier": round(p.speed_multiplier, 2),
                # Streak bonus data (Story 5.2)
                "streak_bonus": p.streak_bonus,
                # Bet data (Story 5.3)
                "bet": p.bet,
                "bet_outcome": p.bet_outcome,
                # Missed round data (Story 5.4)
                "previous_streak": p.previous_streak,
                # Steal data (Story 15.3 AC4)
                "stole_from": p.stole_from,
                "was_stolen_by": p.was_stolen_by.copy() if p.was_stolen_by else [],
                "steal_available": p.steal_available,
            }
            # Story 20.4: Add artist bonus if challenge is enabled
            if gs.artist_challenge_enabled:
                player_data["artist_bonus"] = p.artist_bonus
            # Issue #28: Add movie bonus if quiz is enabled
            if gs.movie_quiz_enabled:
                player_data["movie_bonus"] = p.movie_bonus
            # Issue #23: Add intro bonus if mode is enabled
            if gs.intro_mode_enabled:
                player_data["intro_bonus"] = p.intro_bonus
            players.append(player_data)
        # Sort by score descending for leaderboard preview
        players.sort(key=lambda p: p["score"], reverse=True)
        return players
