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

from .playlist import get_playback_uri
from .scoring import bet_win_multiplier

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
            # #1867: the round timer the server is ACTUALLY counting. Every
            # other create-game setting was already echoed here; this one was
            # not, so `round_duration` was write-only from the client's side —
            # posted once at create, never readable again. A UI could only ever
            # show its own local intent, which is why a lobby advertising "45S"
            # over a server running 30.0s looked fine from every screen and
            # took log archaeology to spot. Emitted in all phases: the lobby
            # needs it before the first round exists.
            "round_duration": gs.round_duration,
            # Issue #23: Intro mode (available in all phases)
            "intro_mode_enabled": gs.intro_mode_enabled,
            # Issue #442: Closest Wins mode
            "closest_wins_mode": gs.closest_wins_mode,
            # Issue #1726: Ramp-up (difficulty-arc) ordering
            "rampup_order_enabled": gs.rampup_order_enabled,
            # Issue #1724: Comeback Token (catch-up steal for trailing players)
            "comeback_token_enabled": gs.comeback_token_enabled,
            "sabotage_enabled": gs.sabotage_enabled,  # #1665
            # Issue #1727: Difficulty-aware bet scaling. Expose the opt-in flag
            # plus the *active* won-bet payout multiplier so the player bet
            # toggle can show what a bet is worth (3x when off, 2/3/5x when on)
            # without duplicating the multiplier map in the frontend.
            "difficulty_bet_scaling_enabled": gs.difficulty_bet_scaling_enabled,
            "bet_win_multiplier": bet_win_multiplier(
                gs.difficulty,
                scaling_enabled=gs.difficulty_bet_scaling_enabled,
            ),
            # Issue #827: Sudden Death mode (drives wizard chip, player view,
            # leaderboard cut-line, admin live toggle)
            "sudden_death_mode": gs.sudden_death_mode,
            # Issue #1725: Finale ×2 + finale sudden-death tiebreaker opt-ins
            # (drive the wizard chip + the finish banner)
            "finale_double_enabled": gs.finale_double_enabled,
            "finale_tiebreaker_enabled": gs.finale_tiebreaker_enabled,
            # #1180: Title & Artist guessing mode (player UI renders inputs)
            "title_artist_mode": gs.title_artist_mode,
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
        # #1662: also expose the server-computed *relative* remaining seconds so
        # clients can anchor their countdown to their OWN clock instead of
        # subtracting a server wall-clock epoch (`deadline`) from a possibly
        # skewed client `Date.now()`. Mirrors the TA-vote timer's
        # ``vote_seconds_remaining``. The absolute ``deadline`` is kept for
        # back-compat and the client-side smooth-correct ease (#1273).
        if gs.deadline is not None:
            state["seconds_remaining"] = max(0, round(gs.deadline / 1000 - gs._now()))
        state["last_round"] = gs.last_round
        state["songs_remaining"] = gs.songs_remaining
        # Issue #1725: Finale ×2 is live this round (last round + opt-in) — drives
        # the "Finale ×2" finish banner. Playoff flag lets the client badge a
        # tiebreaker round.
        state["finale_double_active"] = gs.finale_double_enabled and gs.last_round
        state["finale_playoff_active"] = gs._finale_playoff_active
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
        # #1180: Title & Artist challenge (hide truth during PLAYING)
        tac = gs.get_title_artist_challenge_dict(include_answer=False)
        if tac is not None:
            state["title_artist_challenge"] = tac

    @staticmethod
    def _add_reveal_state(gs: GameState, state: dict[str, Any]) -> None:
        """Populate REVEAL-phase fields."""
        state["join_url"] = gs.join_url
        state["round"] = gs.round
        state["total_rounds"] = gs.total_rounds
        state["last_round"] = gs.last_round
        # Issue #1725: mirror the PLAYING-phase finale flags so the reveal card
        # can keep the "Finale ×2" / playoff badge visible.
        state["finale_double_active"] = gs.finale_double_enabled and gs.last_round
        state["finale_playoff_active"] = gs._finale_playoff_active
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
        # Issue #827: Sudden Death — names eliminated *this* round drive the
        # TV "OUT" takeover + the admin elimination highlight card.
        if gs.sudden_death_mode:
            state["eliminated_this_round"] = [
                p.name
                for p in gs.players.values()
                if p.eliminated and p.eliminated_round == gs.round
            ]
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
            song_uri = get_playback_uri(gs.current_song)
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
        # #1180: Title & Artist challenge (reveal truth + per-player results)
        tac = gs.get_title_artist_challenge_dict(include_answer=True)
        if tac is not None:
            state["title_artist_challenge"] = tac
        # Story 20.9: Early reveal flag for client-side toast
        if gs.early_reveal:
            state["early_reveal"] = True
        # #1012 follow-up: idle-halt — a round where no one submitted holds on
        # REVEAL with playback stopped instead of auto-advancing. Surface this
        # so the REVEAL screen can show a clear "Game idle — tap Next round"
        # banner instead of looking generically stuck.
        if not any(p.submitted for p in gs.players.values()):
            state["idle_halt"] = True
        # #1048: surface the auto-advance config + REVEAL entry timestamp so
        # the admin sticky-menu Next button can render a 1-Hz countdown
        # (deadline = reveal_started_at + reveal_auto_advance * 1000 ms).
        # Client falls back to the plain icon when these are missing or when
        # idle_halt is set.
        state["reveal_auto_advance"] = gs.reveal_auto_advance
        if gs.reveal_started_at is not None:
            state["reveal_started_at"] = gs.reveal_started_at

    @staticmethod
    def _add_end_state(gs: GameState, state: dict[str, Any]) -> None:
        """Populate END-phase fields."""
        # Final leaderboard with all player stats (Story 5.6)
        state["leaderboard"] = gs.get_final_leaderboard()
        state["game_stats"] = {
            "total_rounds": gs.round,
            "total_players": len(gs.players),
        }
        # Include winner info — detect ties (#1402 B2: shared helper, single
        # source of truth with GameState.finalize_game).
        winners, top_score = gs.compute_winners()
        if winners:
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
                # #1664 PR-1: stable id alias (== session_id), additive enabler
                "player_id": p.player_id,
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
                # #1666: Streak-Shield. `streak_shield` is the badge (an
                # unspent shield is held); `streak_shield_used` is the per-round
                # event that just absorbed a miss. Both are broadcast because a
                # shield nobody sees fire looks like a scoring bug — the player
                # answered wrong and their streak did not drop.
                "streak_shield": p.streak_shield,
                "streak_shield_used": p.streak_shield_used_this_round,
                # Issue #1724: True when this player's steal was handed to them
                # as a Comeback Token (catch-up grant), so the client can label
                # the reused steal UI as a comeback gift rather than a streak
                # unlock. Purely a cue — the steal itself is driven by
                # steal_available above.
                "comeback_token_granted": p.comeback_token_granted,
                # Issue #1665: Sabotage — who this player hit, and who hit them
                # with which rolled effect. Broadcast to everyone on purpose:
                # the "gotcha" only lands if the table can see it.
                "sabotage_available": p.sabotage_available,
                "sabotaged": p.sabotaged,
                "sabotaged_by": p.sabotaged_by,
                "sabotage_effect": p.sabotage_effect,
                # Issue #827: Sudden Death state
                "eliminated": p.eliminated,
                "eliminated_round": p.eliminated_round,
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
