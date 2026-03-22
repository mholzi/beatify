"""
Scoring calculation for Beatify.

MVP scoring (Epic 4) - accuracy-based scoring only.
Advanced scoring (Epic 5) adds speed bonus, streaks, and betting.
"""

from __future__ import annotations

from statistics import mean, median
from typing import TYPE_CHECKING, Any

from .types import RoundAnalytics, _get_decade_label

from custom_components.beatify.const import (
    ARTIST_BONUS_POINTS,
    DIFFICULTY_DEFAULT,
    DIFFICULTY_SCORING,
    INTRO_BONUS_TIERS,
    INTRO_DURATION_SECONDS,
    MAX_SUPERLATIVES,
    MIN_BETS_FOR_AWARD,
    MIN_CLOSE_CALLS,
    MIN_COMEBACK_IMPROVEMENT,
    MIN_INTRO_BONUSES_FOR_AWARD,
    MIN_MOVIE_WINS_FOR_AWARD,
    MIN_ROUNDS_FOR_CLUTCH,
    MIN_ROUNDS_FOR_COMEBACK,
    MIN_STREAK_FOR_AWARD,
    MIN_SUBMISSIONS_FOR_SPEED,
    STEAL_UNLOCK_STREAK,
    STREAK_MILESTONES,
)

# Points awarded
POINTS_EXACT = 10
POINTS_WRONG = 0

# Artist scoring constants (Story 10.1)
POINTS_ARTIST_EXACT = 10
POINTS_ARTIST_PARTIAL = 5


def calculate_accuracy_score(
    guess: int,
    actual: int,
    difficulty: str = DIFFICULTY_DEFAULT,
) -> int:
    """
    Calculate accuracy points based on guess vs actual year.

    Scoring rules vary by difficulty (Story 14.1):
    - Easy: exact=10, ±7 years=5, ±10 years=1
    - Normal: exact=10, ±3 years=5, ±5 years=1
    - Hard: exact=10, ±2 years=3, else=0

    Args:
        guess: Player's guessed year
        actual: Correct year from playlist
        difficulty: Difficulty level (easy/normal/hard)

    Returns:
        Points earned based on accuracy and difficulty

    """
    diff = abs(guess - actual)

    # Get config for current difficulty, fallback to default if unknown
    scoring = DIFFICULTY_SCORING.get(difficulty, DIFFICULTY_SCORING[DIFFICULTY_DEFAULT])
    close_range = scoring["close_range"]
    close_points = scoring["close_points"]
    near_range = scoring["near_range"]
    near_points = scoring["near_points"]

    if diff == 0:
        return POINTS_EXACT
    if close_range > 0 and diff <= close_range:
        return close_points
    if near_range > 0 and diff <= near_range:
        return near_points
    return POINTS_WRONG


def calculate_speed_multiplier(elapsed_time: float, round_duration: float) -> float:
    """
    Calculate speed bonus multiplier based on submission timing.

    Formula: speed_multiplier = 2.0 - (1.0 * submission_time_ratio)
    - Instant submission (0s): 2.0x multiplier (double points!)
    - At deadline (30s): 1.0x multiplier (no bonus)

    Args:
        elapsed_time: Seconds elapsed since round started when player submitted
        round_duration: Total round duration in seconds (default 30)

    Returns:
        Multiplier between 1.0 and 2.0

    """
    if round_duration <= 0:
        return 1.0

    # Calculate ratio (0.0 = instant, 1.0 = at deadline)
    submission_time_ratio = elapsed_time / round_duration

    # Clamp to valid range [0.0, 1.0]
    submission_time_ratio = max(0.0, min(1.0, submission_time_ratio))

    # Formula: 2.0x at instant, 1.0x at deadline (linear)
    return 2.0 - (1.0 * submission_time_ratio)


def calculate_round_score(
    guess: int,
    actual: int,
    elapsed_time: float,
    round_duration: float,
    difficulty: str = DIFFICULTY_DEFAULT,
) -> tuple[int, int, float]:
    """
    Calculate total round score with speed bonus.

    Args:
        guess: Player's guessed year
        actual: Correct year from playlist
        elapsed_time: Seconds elapsed since round started
        round_duration: Total round duration in seconds
        difficulty: Difficulty level (easy/normal/hard)

    Returns:
        Tuple of (final_score, base_score, speed_multiplier)

    """
    base_score = calculate_accuracy_score(guess, actual, difficulty)
    speed_multiplier = calculate_speed_multiplier(elapsed_time, round_duration)
    final_score = int(base_score * speed_multiplier)
    return final_score, base_score, speed_multiplier


def apply_bet_multiplier(
    round_score: int,
    bet: bool,  # noqa: FBT001
) -> tuple[int, str | None]:
    """
    Apply bet multiplier to round score (Story 5.3).

    Betting is double-or-nothing:
    - If bet and scored points (>0): double the score, outcome="won"
    - If bet and 0 points: score stays 0, outcome="lost"
    - If no bet: score unchanged, outcome=None

    Args:
        round_score: Points earned before bet (accuracy x speed)
        bet: Whether player placed a bet

    Returns:
        Tuple of (final_score, bet_outcome)
        bet_outcome is "won", "lost", or None

    """
    if not bet:
        return round_score, None

    if round_score > 0:
        return round_score * 2, "won"
    return 0, "lost"


def calculate_streak_bonus(streak: int) -> int:
    """
    Calculate milestone bonus for streak.

    Bonuses awarded at exact milestones only (Story 5.2):
    - 3 consecutive: +20 points
    - 5 consecutive: +50 points
    - 10 consecutive: +100 points
    - 15 consecutive: +150 points
    - 20 consecutive: +250 points
    - 25 consecutive: +400 points

    Args:
        streak: Current streak count (after incrementing for this round)

    Returns:
        Bonus points (0 if not at milestone)

    """
    return STREAK_MILESTONES.get(streak, 0)


def calculate_years_off_text(diff: int) -> str:
    """
    Get human-readable text for years difference.

    Args:
        diff: Absolute difference between guess and actual

    Returns:
        Text like "Exact!", "2 years off", etc.

    """
    if diff == 0:
        return "Exact!"
    if diff == 1:
        return "1 year off"
    return f"{diff} years off"


def calculate_artist_score(guess: str | None, actual: str) -> tuple[int, str | None]:
    """
    Calculate artist guess score (Story 10.1).

    Matching rules (case-insensitive, whitespace-trimmed):
    - Exact match: 10 points
    - Partial match (substring): 5 points
    - No match: 0 points

    Args:
        guess: Player's guessed artist name (can be None or empty)
        actual: Correct artist name from song metadata

    Returns:
        Tuple of (points, match_type)
        match_type is "exact", "partial", or None

    """
    if not guess or not guess.strip():
        return 0, None

    guess_clean = guess.strip().lower()
    actual_clean = actual.strip().lower()

    # Exact match (case-insensitive)
    if guess_clean == actual_clean:
        return POINTS_ARTIST_EXACT, "exact"

    # Partial match (substring in either direction)
    if guess_clean in actual_clean or actual_clean in guess_clean:
        return POINTS_ARTIST_PARTIAL, "partial"

    return 0, None


if TYPE_CHECKING:
    from .player import PlayerSession


# ---------------------------------------------------------------------------
# Private helpers for score_player_round (#191)
# ---------------------------------------------------------------------------


def _apply_streak(
    player: PlayerSession,
    speed_score: int,
    streak_achievements: dict[str, int],
) -> None:
    """Update streak, streak bonus, and streak achievements. Mutates player."""
    if speed_score > 0:
        player.previous_streak = 0
        player.streak += 1
        # Track streak achievements (Issue #147)
        milestone_key = f"streak_{player.streak}"
        if milestone_key in streak_achievements:
            streak_achievements[milestone_key] += 1
        player.streak_bonus = calculate_streak_bonus(player.streak)
        if player.streak == STEAL_UNLOCK_STREAK:
            player.unlock_steal()
    else:
        player.previous_streak = player.streak
        player.streak = 0
        player.streak_bonus = 0


def _score_artist_challenge(
    player: PlayerSession,
    artist_challenge: Any | None,
) -> int:
    """Return artist bonus points and set player.artist_bonus. Mutates player."""
    player.artist_bonus = (
        ARTIST_BONUS_POINTS
        if artist_challenge and artist_challenge.winner == player.name
        else 0
    )
    return player.artist_bonus


def _score_movie_challenge(
    player: PlayerSession,
    movie_challenge: Any | None,
    *,
    add_to_score: bool = False,
) -> int:
    """Return movie bonus points and update player totals. Mutates player."""
    if not movie_challenge:
        player.movie_bonus = 0
        return 0
    player.movie_bonus = movie_challenge.get_player_bonus(player.name)
    if player.movie_bonus > 0:
        player.movie_bonus_total += player.movie_bonus
        if add_to_score:
            player.score += player.movie_bonus
    return player.movie_bonus


def _score_intro_round(
    player: PlayerSession,
    *,
    is_intro_round: bool,
    intro_round_start_time: float | None,
    all_players: list[PlayerSession],
) -> int:
    """Return intro bonus points. Mutates player.intro_bonus and player.intro_speed_bonuses."""
    player.intro_bonus = 0
    if not (is_intro_round and intro_round_start_time and player.submission_time):
        return 0
    cutoff = intro_round_start_time + INTRO_DURATION_SECONDS
    if player.submission_time >= cutoff:
        return 0
    player.intro_speed_bonuses += 1
    rank = sum(
        1
        for p in all_players
        if p.submission_time is not None
        and p.submission_time < cutoff
        and p.submission_time < player.submission_time
    )
    if rank < len(INTRO_BONUS_TIERS):
        player.intro_bonus = INTRO_BONUS_TIERS[rank]
    return player.intro_bonus


def _update_bet_tracking(
    player: PlayerSession,
    bet_tracking: dict[str, int],
) -> None:
    """Update bet counters on player and shared bet_tracking dict. Mutates both."""
    if not player.bet:
        return
    player.bets_placed += 1
    bet_tracking["total_bets"] += 1
    if player.bet_outcome == "won":
        bet_tracking["bets_won"] += 1


# ---------------------------------------------------------------------------
# Private helpers for calculate_superlatives (#191)
# ---------------------------------------------------------------------------


def _award(id_: str, emoji: str, player_name: str, value: Any, value_label: str) -> dict[str, Any]:
    """Build a superlative award dict."""
    return {"id": id_, "emoji": emoji, "title": id_, "player_name": player_name, "value": value, "value_label": value_label}


def _superlative_speed_demon(players: list[PlayerSession]) -> dict[str, Any] | None:
    candidates = [(p, p.avg_submission_time) for p in players if p.avg_submission_time is not None and len(p.submission_times) >= MIN_SUBMISSIONS_FOR_SPEED]
    if not candidates:
        return None
    fastest = min(candidates, key=lambda x: x[1])
    return _award("speed_demon", "⚡", fastest[0].name, round(fastest[1], 1), "avg_time")


def _superlative_lucky_streak(players: list[PlayerSession]) -> dict[str, Any] | None:
    candidates = [(p, p.best_streak) for p in players if p.best_streak >= MIN_STREAK_FOR_AWARD]
    if not candidates:
        return None
    best = max(candidates, key=lambda x: x[1])
    return _award("lucky_streak", "🔥", best[0].name, best[1], "streak")


def _superlative_risk_taker(players: list[PlayerSession]) -> dict[str, Any] | None:
    candidates = [(p, p.bets_placed) for p in players if p.bets_placed >= MIN_BETS_FOR_AWARD]
    if not candidates:
        return None
    most = max(candidates, key=lambda x: x[1])
    return _award("risk_taker", "🎲", most[0].name, most[1], "bets")


def _superlative_clutch_player(players: list[PlayerSession], rounds_played: int) -> dict[str, Any] | None:
    if rounds_played < MIN_ROUNDS_FOR_CLUTCH:
        return None
    candidates = [
        (p, p.final_three_score)
        for p in players
        if len(p.round_scores) >= MIN_ROUNDS_FOR_CLUTCH
    ]
    if not candidates:
        return None
    clutch = max(candidates, key=lambda x: x[1])
    if clutch[1] <= 0:
        return None
    return _award("clutch_player", "🌟", clutch[0].name, clutch[1], "points")


def _superlative_close_calls(players: list[PlayerSession]) -> dict[str, Any] | None:
    candidates = [(p, p.close_calls) for p in players if p.close_calls >= MIN_CLOSE_CALLS]
    if not candidates:
        return None
    closest = max(candidates, key=lambda x: x[1])
    return _award("close_calls", "🎯", closest[0].name, closest[1], "close_guesses")


def _superlative_film_buff(players: list[PlayerSession]) -> dict[str, Any] | None:
    candidates = [
        (p, p.movie_bonus_total)
        for p in players
        if p.movie_bonus_total >= MIN_MOVIE_WINS_FOR_AWARD
    ]
    if not candidates:
        return None
    film_buff = max(candidates, key=lambda x: x[1])
    return _award("film_buff", "🎬", film_buff[0].name, film_buff[1], "movie_bonus")


def _superlative_intro_master(players: list[PlayerSession]) -> dict[str, Any] | None:
    candidates = [
        (p, p.intro_speed_bonuses)
        for p in players
        if p.intro_speed_bonuses >= MIN_INTRO_BONUSES_FOR_AWARD
    ]
    if not candidates:
        return None
    intro_master = max(candidates, key=lambda x: x[1])
    return _award("intro_master", "🎧", intro_master[0].name, intro_master[1], "intro_bonuses")


def _superlative_comeback_king(players: list[PlayerSession], rounds_played: int) -> dict[str, Any] | None:
    if rounds_played < MIN_ROUNDS_FOR_COMEBACK:
        return None
    candidates = []
    for p in players:
        if len(p.round_scores) >= MIN_ROUNDS_FOR_COMEBACK:
            mid = len(p.round_scores) // 2
            first_half = sum(p.round_scores[:mid]) / mid
            second_half = sum(p.round_scores[mid:]) / (len(p.round_scores) - mid)
            improvement = second_half - first_half
            if improvement > MIN_COMEBACK_IMPROVEMENT:
                candidates.append((p, round(improvement, 1)))
    if not candidates:
        return None
    comeback = max(candidates, key=lambda x: x[1])
    return _award("comeback_king", "👑", comeback[0].name, comeback[1], "improvement")


# ---------------------------------------------------------------------------
# ScoringService — extracted from GameState (Issue #139)
# ---------------------------------------------------------------------------


class ScoringService:
    """Centralised scoring, analytics, and superlative calculations.

    Extracted from GameState (Issue #139) so that scoring logic is
    independently testable and doesn't bloat the game-lifecycle class.
    """

    @staticmethod
    def calculate_superlatives(
        players: list[PlayerSession],
        *,
        rounds_played: int,
        movie_quiz_enabled: bool = False,
        intro_mode_enabled: bool = False,
    ) -> list[dict[str, Any]]:
        """Calculate fun awards based on game performance (Story 15.2)."""
        if not players:
            return []

        builders = [
            _superlative_speed_demon(players),
            _superlative_lucky_streak(players),
            _superlative_risk_taker(players),
            _superlative_clutch_player(players, rounds_played),
            _superlative_close_calls(players),
            _superlative_film_buff(players) if movie_quiz_enabled else None,
            _superlative_intro_master(players) if intro_mode_enabled else None,
            _superlative_comeback_king(players, rounds_played),
        ]

        return [a for a in builders if a is not None][:MAX_SUPERLATIVES]

    @staticmethod
    def calculate_round_analytics(
        players: list[PlayerSession],
        correct_year: int | None,
        round_start_time: float | None,
    ) -> Any:
        """Calculate analytics for current round reveal (Story 13.3)."""
        if correct_year is None:
            return RoundAnalytics()

        submitted = [p for p in players if p.submitted and p.current_guess is not None]
        if not submitted:
            return RoundAnalytics(correct_decade=_get_decade_label(correct_year))

        all_guesses = sorted(
            [
                {"name": p.name, "guess": p.current_guess, "years_off": p.years_off or 0}
                for p in submitted
            ],
            key=lambda x: x["years_off"],
        )
        guesses = [p.current_guess for p in submitted]
        avg_guess = mean(guesses)
        med_guess = int(median(guesses))
        min_off = min(p.years_off or 0 for p in submitted)
        closest = [p.name for p in submitted if (p.years_off or 0) == min_off]
        max_off = max(p.years_off or 0 for p in submitted)
        furthest = [p.name for p in submitted if (p.years_off or 0) == max_off]
        exact = [p.name for p in submitted if p.years_off == 0]
        scored = sum(1 for p in submitted if p.round_score > 0)
        accuracy_pct = int((scored / len(submitted)) * 100)

        speed_champion = None
        timed = [
            p for p in submitted if p.submission_time is not None and round_start_time is not None
        ]
        if timed:
            elapsed = [(p, p.submission_time - round_start_time) for p in timed]
            fastest_time = min(t for _, t in elapsed)
            speed_champion = {
                "names": [p.name for p, t in elapsed if t == fastest_time],
                "time": round(fastest_time, 1),
            }

        decade_dist: dict[str, int] = {}
        for g in guesses:
            d = _get_decade_label(g)
            decade_dist[d] = decade_dist.get(d, 0) + 1

        return RoundAnalytics(
            all_guesses=all_guesses,
            average_guess=avg_guess,
            median_guess=med_guess,
            closest_players=closest,
            furthest_players=furthest,
            exact_match_players=exact,
            exact_match_count=len(exact),
            scored_count=scored,
            total_submitted=len(submitted),
            accuracy_percentage=accuracy_pct,
            speed_champion=speed_champion,
            decade_distribution=decade_dist,
            correct_decade=_get_decade_label(correct_year),
        )

    @staticmethod
    def score_player_round(
        player: PlayerSession,
        *,
        correct_year: int,
        round_start_time: float | None,
        round_duration: float,
        difficulty: str,
        artist_challenge: Any | None,
        movie_challenge: Any | None,
        is_intro_round: bool,
        intro_round_start_time: float | None,
        all_players: list[PlayerSession],
        streak_achievements: dict[str, int],
        bet_tracking: dict[str, int],
    ) -> None:
        """Score a single player for the current round. Mutates player in-place."""
        if player.submitted and correct_year is not None:
            elapsed = (
                player.submission_time - round_start_time
                if player.submission_time is not None and round_start_time is not None
                else round_duration
            )
            speed_score, player.base_score, player.speed_multiplier = calculate_round_score(
                player.current_guess, correct_year, elapsed, round_duration, difficulty
            )
            player.years_off = abs(player.current_guess - correct_year)
            player.missed_round = False
            player.round_score, player.bet_outcome = apply_bet_multiplier(speed_score, player.bet)

            _apply_streak(player, speed_score, streak_achievements)
            _score_artist_challenge(player, artist_challenge)
            _score_movie_challenge(player, movie_challenge)
            _score_intro_round(
                player,
                is_intro_round=is_intro_round,
                intro_round_start_time=intro_round_start_time,
                all_players=all_players,
            )

            player.score += (
                player.round_score
                + player.streak_bonus
                + player.artist_bonus
                + player.movie_bonus
                + player.intro_bonus
            )
            player.rounds_played += 1
            player.best_streak = max(player.best_streak, player.streak)
            if player.bet_outcome == "won":
                player.bets_won += 1
            if player.submission_time is not None and round_start_time is not None:
                player.submission_times.append(player.submission_time - round_start_time)
            _update_bet_tracking(player, bet_tracking)
            if player.years_off == 1:
                player.close_calls += 1
            player.round_scores.append(player.round_score)
        else:
            player.previous_streak = player.streak
            player.round_score = 0
            player.base_score = 0
            player.speed_multiplier = 1.0
            player.years_off = None
            player.missed_round = True
            player.streak = 0
            player.streak_bonus = 0
            player.bet_outcome = None
            _score_artist_challenge(player, artist_challenge)
            if player.artist_bonus:
                player.score += player.artist_bonus
            _score_movie_challenge(player, movie_challenge, add_to_score=True)
            player.intro_bonus = 0
