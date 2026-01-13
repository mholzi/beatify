"""
Scoring calculation for Beatify.

MVP scoring (Epic 4) - accuracy-based scoring only.
Advanced scoring (Epic 5) adds speed bonus, streaks, and betting.
"""

from __future__ import annotations

from custom_components.beatify.const import STREAK_MILESTONES

# Scoring thresholds (FR32)
THRESHOLD_CLOSE = 3  # Within ±3 years = 5 points
THRESHOLD_NEAR = 5  # Within ±5 years = 1 point

# Points awarded
POINTS_EXACT = 10
POINTS_CLOSE = 5
POINTS_NEAR = 1
POINTS_WRONG = 0

# Artist scoring constants (Story 10.1)
POINTS_ARTIST_EXACT = 10
POINTS_ARTIST_PARTIAL = 5


def calculate_accuracy_score(guess: int, actual: int) -> int:
    """
    Calculate accuracy points based on guess vs actual year.

    Scoring rules (FR32):
    - Exact match: 10 points
    - Within ±3 years: 5 points
    - Within ±5 years: 1 point
    - More than 5 years off: 0 points

    Args:
        guess: Player's guessed year
        actual: Correct year from playlist

    Returns:
        Points earned (0, 1, 5, or 10)

    """
    diff = abs(guess - actual)

    if diff == 0:
        return POINTS_EXACT
    if diff <= THRESHOLD_CLOSE:
        return POINTS_CLOSE
    if diff <= THRESHOLD_NEAR:
        return POINTS_NEAR
    return POINTS_WRONG


def calculate_artist_score(guess: str | None, actual: str) -> tuple[int, str | None]:
    """
    Calculate artist scoring based on guess vs actual (Story 10.1).

    Scoring rules:
    - Exact match (case-insensitive): 10 points
    - Partial match (guess in actual OR actual in guess): 5 points
    - No match: 0 points

    Args:
        guess: Player's guessed artist (may be None or empty)
        actual: Correct artist from playlist

    Returns:
        Tuple of (points, match_type) where match_type is "exact", "partial", or None

    """
    if not guess or not guess.strip():
        return 0, None

    guess_normalized = guess.strip().lower()
    actual_normalized = actual.strip().lower()

    # Exact match
    if guess_normalized == actual_normalized:
        return POINTS_ARTIST_EXACT, "exact"

    # Partial match (bidirectional - either direction)
    if guess_normalized in actual_normalized or actual_normalized in guess_normalized:
        return POINTS_ARTIST_PARTIAL, "partial"

    return 0, None


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
) -> tuple[int, int, float]:
    """
    Calculate total round score with speed bonus.

    Args:
        guess: Player's guessed year
        actual: Correct year from playlist
        elapsed_time: Seconds elapsed since round started
        round_duration: Total round duration in seconds

    Returns:
        Tuple of (final_score, base_score, speed_multiplier)

    """
    base_score = calculate_accuracy_score(guess, actual)
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
