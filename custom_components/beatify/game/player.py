"""Player session management for Beatify."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from custom_components.beatify.const import MIN_SUBMISSIONS_FOR_SPEED

if TYPE_CHECKING:
    from aiohttp import web


@dataclass
class PlayerSession:
    """Represents a connected player."""

    name: str
    ws: web.WebSocketResponse
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    score: int = 0
    streak: int = 0
    connected: bool = True
    is_admin: bool = False
    joined_late: bool = False
    # Player onboarding v2 — true once player has completed/skipped the tour
    onboarded: bool = False
    joined_at: float = field(default_factory=time.time)
    submitted: bool = False
    current_guess: int | None = None
    submission_time: float | None = None
    # Round results (for Story 4.6)
    round_score: int = 0
    years_off: int | None = None
    missed_round: bool = False

    # Speed bonus tracking (Story 5.1)
    speed_multiplier: float = 1.0
    base_score: int = 0

    # Streak bonus tracking (Story 5.2)
    streak_bonus: int = 0

    # Artist challenge bonus tracking (Story 20.4)
    artist_bonus: int = 0

    # Artist guess tracking (Story 20.9)
    has_artist_guess: bool = False

    # Title & Artist guess tracking (Issue #1180) — early-reveal trigger
    has_title_artist_guess: bool = False

    # Movie quiz bonus tracking (Issue #28)
    movie_bonus: int = 0
    has_movie_guess: bool = False
    movie_bonus_total: int = 0  # Cumulative across rounds for superlative

    # Intro mode bonus tracking (Issue #23)
    intro_bonus: int = 0  # Per-round intro speed bonus
    intro_speed_bonuses: int = 0  # Cumulative count for superlative

    # Round results tracking (Issue #120 — Shareable Result Cards)
    round_results: list[str] = field(default_factory=list)

    # Betting tracking (Story 5.3)
    bet: bool = False
    bet_outcome: str | None = None  # "won", "lost", or None

    # No-submission tracking (Story 5.4)
    previous_streak: int = 0  # Streak before reset (for "lost X-streak" display)

    # Leaderboard tracking (Story 5.5)
    previous_rank: int | None = None  # Rank before last update

    # Sudden Death tracking (Issue #827) - CUMULATIVE, NOT reset in reset_round()
    eliminated: bool = False  # True once eliminated; stays out for the rest of the game
    eliminated_round: int | None = None  # Round number the player was eliminated in
    # #1752: round number a late joiner entered the game in. None for LOBBY joins
    # (and after reset_for_new_game). Used to grant a mid-round joiner one grace
    # round — they are excluded from the Sudden Death elimination candidate pool
    # for the round they join, since they never played it.
    joined_round: int | None = None

    # Final stats tracking (Story 5.6) - CUMULATIVE, NOT reset in reset_round()
    best_streak: int = 0  # Highest streak achieved during game
    rounds_played: int = 0  # Rounds the player participated in
    bets_won: int = 0  # Successful bets

    # Superlative tracking (Story 15.2) - CUMULATIVE, NOT reset in reset_round()
    submission_times: list[float] = field(
        default_factory=list
    )  # Time-to-submit per round (seconds)
    bets_placed: int = 0  # Total bets placed (distinct from bets_won)
    close_calls: int = 0  # Number of +/-1 year guesses (not exact)
    round_scores: list[int] = field(
        default_factory=list
    )  # All round scores for final 3 calc

    # Title & Artist superlative tracking (#1180) - CUMULATIVE, NOT reset per round
    exact_titles: int = 0  # Rounds with an exact title match (Name Dropper)
    correct_artists: int = (
        0  # Rounds with the artist named correctly (Artist Whisperer)
    )
    perfect_pairs: int = 0  # Rounds with both title and artist correct (Perfect Pair)
    near_misses: int = 0  # Count of debated near-miss fields, title + artist (So Close)

    # Steal power-up tracking (Story 15.3)
    steal_available: bool = False  # True if steal unlocked and not yet used
    steal_used: bool = False  # True if steal was used this game (max 1 per game)
    # Comeback Token tracking (Issue #1724) - CUMULATIVE, NOT reset per round.
    # True once this player has been handed a catch-up steal after the halfway
    # round, so the grant fires at most once per player per game even if they
    # stay in the bottom third.
    comeback_token_granted: bool = False
    stole_from: str | None = None  # Per-round: who was stolen from
    was_stolen_by: list[str] = field(
        default_factory=list
    )  # Per-round: who stole this player's answer

    # Sabotage power-up tracking (Issue #1665) — mirrors the steal token.
    # The saboteur picks a target; the EFFECT is rolled server-side.
    sabotage_available: bool = False  # Token in hand, not yet spent
    sabotage_used: bool = False  # Token spent this game (max 1 per game)
    sabotaged: str | None = None  # Per-round: whom this player hit
    # Per-round victim state — set on the TARGET when a sabotage lands.
    sabotaged_by: str | None = None  # Who hit this player this round
    sabotage_effect: str | None = None  # Which effect was rolled (SABOTAGE_EFFECTS)
    # Timer-cut: milliseconds shaved off THIS player's effective round deadline.
    sabotage_deadline_cut_ms: int = 0
    # Freeze: this player may not submit until this timestamp (``_now`` units).
    sabotage_freeze_until: float | None = None
    # Forced bet: the server forces bet=True on this player's submission.
    sabotage_forced_bet: bool = False

    @property
    def player_id(self) -> str:
        """Stable identifier for this player (alias of ``session_id``).

        Read-only alias introduced for the name-identity refactor (#1664,
        PR-1). ``session_id`` is already a server-issued, stable UUID; this
        property simply exposes it under the ``player_id`` name that will
        become the primary key in later refactor steps. Purely additive — no
        behaviour change, no new state.
        """
        return self.session_id

    @property
    def is_active(self) -> bool:
        """True only if the player is genuinely still connected.

        ``connected`` alone is not enough: a dropped/closed WebSocket whose
        ``_handle_disconnect`` has not run yet leaves a stale ``connected =
        True`` ghost. Counting such a ghost as an active participant blocks
        all-submitted detection (early reveal) for the whole room — #928.
        """
        return self.connected and self.ws is not None and not self.ws.closed

    def submit_guess(self, year: int, timestamp: float) -> None:
        """Record a guess submission."""
        self.submitted = True
        self.current_guess = year
        self.submission_time = timestamp

    def reset_round(self) -> None:
        """Reset round-specific state for new round."""
        self.submitted = False
        self.current_guess = None
        self.submission_time = None
        self.round_score = 0
        self.years_off = None
        self.missed_round = False
        # Reset speed bonus fields (Story 5.1)
        self.speed_multiplier = 1.0
        self.base_score = 0
        # Reset streak bonus (Story 5.2)
        self.streak_bonus = 0
        # Reset artist bonus (Story 20.4)
        self.artist_bonus = 0
        # Reset artist guess tracking (Story 20.9)
        self.has_artist_guess = False
        # Reset title & artist guess tracking (Issue #1180)
        self.has_title_artist_guess = False
        # Reset movie quiz fields (Issue #28)
        self.movie_bonus = 0
        self.has_movie_guess = False
        # Reset intro mode fields (Issue #23)
        self.intro_bonus = 0
        # Reset bet fields (Story 5.3)
        self.bet = False
        self.bet_outcome = None
        # Reset previous streak (Story 5.4)
        self.previous_streak = 0
        # Reset per-round steal fields (Story 15.3)
        self.stole_from = None
        self.was_stolen_by = []
        # Reset per-round sabotage fields (Issue #1665). The token itself
        # (``sabotage_available`` / ``sabotage_used``) is game-level and
        # deliberately NOT reset here — one token per player per game.
        self.sabotaged = None
        self.sabotaged_by = None
        self.sabotage_effect = None
        self.sabotage_deadline_cut_ms = 0
        self.sabotage_freeze_until = None
        self.sabotage_forced_bet = False

    def unlock_steal(self) -> bool:
        """Unlock steal power-up if not already used. Returns True if newly unlocked."""
        if self.steal_used or self.steal_available:
            return False
        self.steal_available = True
        return True

    def consume_steal(self, target_name: str) -> None:
        """Use the steal power-up to copy target's answer."""
        self.steal_available = False
        self.steal_used = True
        self.stole_from = target_name

    def unlock_sabotage(self) -> bool:
        """Hand this player a sabotage token (#1665). True if newly unlocked."""
        if self.sabotage_used or self.sabotage_available:
            return False
        self.sabotage_available = True
        return True

    def consume_sabotage(self, target_name: str) -> None:
        """Spend the sabotage token against ``target_name`` (#1665)."""
        self.sabotage_available = False
        self.sabotage_used = True
        self.sabotaged = target_name

    def reset_for_new_game(self) -> None:
        """Reset all game-level stats for a new game (Story 15.2)."""
        # Reset join state
        self.joined_late = False

        # Reset score and streaks
        self.score = 0
        self.streak = 0
        self.best_streak = 0
        self.rounds_played = 0
        self.bets_won = 0

        # Reset round results (Issue #120)
        self.round_results = []

        # Reset superlative tracking
        self.submission_times = []
        self.bets_placed = 0
        self.close_calls = 0
        self.round_scores = []

        # Reset title & artist superlative tracking (#1180)
        self.exact_titles = 0
        self.correct_artists = 0
        self.perfect_pairs = 0
        self.near_misses = 0

        # Reset steal tracking
        self.steal_available = False
        self.steal_used = False
        # Reset comeback token tracking (Issue #1724)
        self.comeback_token_granted = False
        # Reset sabotage tracking (Issue #1665) — the token is per game.
        self.sabotage_available = False
        self.sabotage_used = False

        # Reset intro mode cumulative tracking (Issue #23)
        self.intro_speed_bonuses = 0

        # Reset Sudden Death state (Issue #827)
        self.eliminated = False
        self.eliminated_round = None
        # #1752: clear late-join grace tracking so a rematch/new game never
        # grants a carried-over player Sudden Death grace on a stale round number.
        self.joined_round = None

        # Reset movie bonus cumulative tracking (Issue #28)
        self.movie_bonus_total = 0

        # Also reset round-level state
        self.reset_round()

    @property
    def avg_submission_time(self) -> float | None:
        """Average submission time in seconds (Story 15.2)."""
        if len(self.submission_times) < MIN_SUBMISSIONS_FOR_SPEED:
            return None
        return sum(self.submission_times) / len(self.submission_times)

    @property
    def final_three_score(self) -> int:
        """Sum of last 3 round scores (Story 15.2)."""
        return sum(self.round_scores[-3:]) if len(self.round_scores) >= 3 else 0
