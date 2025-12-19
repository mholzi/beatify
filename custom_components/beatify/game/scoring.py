"""
Scoring calculation for Beatify.

MVP scoring (Epic 4) - accuracy-based scoring only.
Advanced scoring (Epic 5) adds speed bonus, streaks, and betting.
"""

from __future__ import annotations

# Scoring thresholds (FR32)
THRESHOLD_CLOSE = 3  # Within ±3 years = 5 points
THRESHOLD_NEAR = 5  # Within ±5 years = 1 point

# Points awarded
POINTS_EXACT = 10
POINTS_CLOSE = 5
POINTS_NEAR = 1
POINTS_WRONG = 0


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
