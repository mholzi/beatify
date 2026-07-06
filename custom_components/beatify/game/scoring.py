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
    DIFFICULTY_DEFAULT,
    DIFFICULTY_EASY,
    DIFFICULTY_HARD,
    DIFFICULTY_NORMAL,
    DIFFICULTY_SCORING,
    INTRO_BONUS_TIERS,
    INTRO_DURATION_SECONDS,
    MAX_SUPERLATIVES,
    MIN_BETS_FOR_AWARD,
    MIN_CLOSE_CALLS,
    MIN_COMEBACK_IMPROVEMENT,
    MIN_CORRECT_ARTISTS_FOR_AWARD,
    MIN_EXACT_TITLES_FOR_AWARD,
    MIN_INTRO_BONUSES_FOR_AWARD,
    MIN_MOVIE_WINS_FOR_AWARD,
    MIN_NEAR_MISSES_FOR_AWARD,
    MIN_PERFECT_PAIRS_FOR_AWARD,
    MIN_ROUNDS_FOR_CLUTCH,
    MIN_ROUNDS_FOR_COMEBACK,
    MIN_STREAK_FOR_AWARD,
    MIN_SUBMISSIONS_FOR_SPEED,
    STEAL_UNLOCK_STREAK,
    STREAK_MILESTONES,
)

from custom_components.beatify.game.challenges import STATUS_NEAR_MISS_ACCEPTED
from custom_components.beatify.game.text_match import (
    STATUS_EXACT,
    STATUS_FUZZY,
    STATUS_NEAR_MISS,
)

# Points awarded
POINTS_EXACT = 10
POINTS_WRONG = 0

# #1722: the speed bonus holds at its maximum for an initial grace window so a
# player isn't punished for actually listening to the song before committing to
# a year. After the grace it decays linearly to 1.0x at the deadline.
SPEED_MULTIPLIER_MAX = 2.0
SPEED_GRACE_FRACTION = 1.0 / 3.0

# A won bet (exact year) multiplies the round score by this (#1004).
# This is the flat, difficulty-agnostic payout — the default that applies when
# difficulty-aware bet scaling is OFF (byte-for-byte the pre-#1727 behaviour).
BET_WIN_MULTIPLIER = 3

# #1727: difficulty-aware bet payout. The exact-year probability is exactly what
# difficulty modulates, so a flat 3x makes betting strictly bad play on Hard
# (rare exact guess, whole round forfeited on a miss) — Risk Taker + bet_tracking
# go dead. When the opt-in ``difficulty_bet_scaling_enabled`` setting is on, the
# payout scales with how hard an exact guess is: easy 2x / normal 3x / hard 5x.
# Unknown difficulties fall back to the flat BET_WIN_MULTIPLIER.
BET_WIN_MULTIPLIER_BY_DIFFICULTY: dict[str, int] = {
    DIFFICULTY_EASY: 2,
    DIFFICULTY_NORMAL: 3,
    DIFFICULTY_HARD: 5,
}


def bet_win_multiplier(
    difficulty: str = DIFFICULTY_DEFAULT,
    *,
    scaling_enabled: bool = False,
) -> int:
    """Return the active bet-win payout multiplier (#1727).

    When ``scaling_enabled`` is False the flat ``BET_WIN_MULTIPLIER`` (3x)
    applies on every difficulty — identical to the pre-#1727 behaviour. When
    True the payout is read from ``BET_WIN_MULTIPLIER_BY_DIFFICULTY`` (easy 2x /
    normal 3x / hard 5x), falling back to the flat value for an unknown
    difficulty.

    Args:
        difficulty: Difficulty level (easy/normal/hard).
        scaling_enabled: Whether difficulty-aware bet scaling is opted in.

    Returns:
        The multiplier a won (exact-year) bet applies to the round score.

    """
    if not scaling_enabled:
        return BET_WIN_MULTIPLIER
    return BET_WIN_MULTIPLIER_BY_DIFFICULTY.get(difficulty, BET_WIN_MULTIPLIER)


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

    #1722: a grace window keeps the multiplier at its maximum for the first
    third of the round, so listening to recognise the song isn't penalised.
    - Instant .. grace edge (round_duration / 3): 2.0x (double points!)
    - Grace edge .. deadline: linear decay 2.0x → 1.0x
    - At / past the deadline: 1.0x (no bonus)

    Args:
        elapsed_time: Seconds elapsed since round started when player submitted
        round_duration: Total round duration in seconds

    Returns:
        Multiplier between 1.0 and 2.0

    """
    if round_duration <= 0:
        return 1.0

    grace = round_duration * SPEED_GRACE_FRACTION

    # Full multiplier during the grace window (and for any early / negative time).
    if elapsed_time <= grace:
        return SPEED_MULTIPLIER_MAX

    # Linear decay from the max at the grace edge to 1.0x at the deadline.
    decay_ratio = (elapsed_time - grace) / (round_duration - grace)
    decay_ratio = max(0.0, min(1.0, decay_ratio))
    return SPEED_MULTIPLIER_MAX - ((SPEED_MULTIPLIER_MAX - 1.0) * decay_ratio)


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
    # #1722: round rather than truncate — int() dropped the speed bonus entirely
    # for the 1-point accuracy tier (int(1 * 1.9) == 1) and shaved fractional
    # bonuses off every other tier.
    final_score = round(base_score * speed_multiplier)
    return final_score, base_score, speed_multiplier


def apply_bet_multiplier(
    round_score: int,
    bet: bool,  # noqa: FBT001
    is_exact: bool,  # noqa: FBT001
    multiplier: int = BET_WIN_MULTIPLIER,
) -> tuple[int, str | None]:
    """
    Apply bet multiplier to round score (Story 5.3, redesigned #1004).

    Betting is a real "exact or nothing" gamble:
    - If bet and the guess is the EXACT year: round_score x multiplier,
      outcome="won".
    - If bet and the guess is not exact: score becomes 0, outcome="lost" —
      the player forfeits the points a close guess would otherwise have
      earned. That forfeit is the stake that makes the bet a real risk.
    - If no bet: score unchanged, outcome=None.

    Args:
        round_score: Points earned before bet (accuracy x speed)
        bet: Whether player placed a bet
        is_exact: Whether the guess matched the correct year exactly
        multiplier: Payout multiplier for a won bet. Defaults to the flat
            ``BET_WIN_MULTIPLIER`` (3x). #1727: the caller passes a
            difficulty-scaled value via :func:`bet_win_multiplier` when the
            opt-in ``difficulty_bet_scaling_enabled`` setting is on.

    Returns:
        Tuple of (final_score, bet_outcome)
        bet_outcome is "won", "lost", or None

    """
    if not bet:
        return round_score, None

    if is_exact:
        return round_score * multiplier, "won"
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
    """Return artist bonus points and set player.artist_bonus. Mutates player.

    Winner-takes-all (Issue #1723): delegates to the challenge's shared
    ``get_player_bonus`` so the artist and movie challenges award identically.
    """
    player.artist_bonus = (
        artist_challenge.get_player_bonus(player.name) if artist_challenge else 0
    )
    return player.artist_bonus


# Title statuses that count as a "correct" round for streak purposes (#1180).
_TITLE_CORRECT_STATUSES = (STATUS_EXACT, STATUS_FUZZY, STATUS_NEAR_MISS_ACCEPTED)


def _score_title_artist_round(
    player: PlayerSession,
    title_artist_manager: Any,
    streak_achievements: dict[str, int],
) -> None:
    """Score a player in title/artist mode (#1180). Mutates player in-place.

    Round score = title points + artist points (replacing the year score).
    Speed/bet/intro do not apply. Streak counts the round as correct when the
    title status is exact/fuzzy/near_miss_accepted. Cumulative score, streak
    milestone bonus, and round_scores are all updated here.
    """
    title_pts, artist_pts = title_artist_manager.title_artist_points(player.name)
    round_score = title_pts + artist_pts

    player.round_score = round_score
    player.base_score = round_score
    player.speed_multiplier = 1.0
    player.years_off = None
    player.missed_round = False
    player.bet_outcome = None
    player.artist_bonus = 0
    player.movie_bonus = 0
    player.intro_bonus = 0

    title_status = title_artist_manager.title_artist_status(player.name)
    artist_status = title_artist_manager.title_artist_status(player.name, "artist")
    title_correct = title_status in _TITLE_CORRECT_STATUSES
    artist_correct = artist_status in _TITLE_CORRECT_STATUSES

    # Cumulative per-field counters drive the Title & Artist superlatives
    # (#1180): Name Dropper, Artist Whisperer, Perfect Pair, So Close.
    if title_status == STATUS_EXACT:
        player.exact_titles += 1
    if artist_correct:
        player.correct_artists += 1
    if title_correct and artist_correct:
        player.perfect_pairs += 1
    player.near_misses += (title_status == STATUS_NEAR_MISS) + (
        artist_status == STATUS_NEAR_MISS
    )

    # Reuse the shared streak machinery, keyed on title correctness rather
    # than a positive year score (which doesn't exist in this mode).
    _apply_streak(player, 1 if title_correct else 0, streak_achievements)

    player.score += player.round_score + player.streak_bonus
    player.rounds_played += 1
    player.best_streak = max(player.best_streak, player.streak)
    player.round_scores.append(player.round_score)


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


def _intro_qualified(
    player: PlayerSession,
    *,
    cutoff: float,
    correct_year: int | None,
    difficulty: str,
    title_artist_manager: Any | None,
) -> bool:
    """Whether ``player`` qualifies for the intro speed bonus (#1720).

    A submission must be both *in time* (before the 15s cutoff) and
    *accuracy-positive*. Accuracy is recomputed from stable submit-time inputs
    (``current_guess`` / the title-artist manager) rather than read off
    ``player.base_score``: the per-player scoring loop runs sequentially, so a
    not-yet-scored player's ``base_score`` may still hold a previous round's
    value. Recomputing keeps the speed ranking order-independent.

    Year mode: accuracy score (== ``base_score``) must be > 0.
    Title/artist mode: title + artist points (== ``base_score``) must be > 0.
    """
    if player.submission_time is None or player.submission_time >= cutoff:
        return False
    if title_artist_manager is not None:
        title_pts, artist_pts = title_artist_manager.title_artist_points(player.name)
        return (title_pts + artist_pts) > 0
    if correct_year is None or player.current_guess is None:
        return False
    return calculate_accuracy_score(player.current_guess, correct_year, difficulty) > 0


def _score_intro_round(
    player: PlayerSession,
    *,
    is_intro_round: bool,
    intro_round_start_time: float | None,
    all_players: list[PlayerSession],
    correct_year: int | None,
    difficulty: str,
    title_artist_manager: Any | None,
) -> int:
    """Return intro bonus points. Mutates player.intro_bonus and player.intro_speed_bonuses.

    #1720: only accuracy-qualified submitters compete for (and receive) the
    tiered 5/3/1 intro bonus. A fast-but-wrong tap no longer farms guaranteed
    points nor displaces a slower-but-correct recognizer in the speed ranking.
    """
    player.intro_bonus = 0
    if not (is_intro_round and intro_round_start_time and player.submission_time):
        return 0
    cutoff = intro_round_start_time + INTRO_DURATION_SECONDS
    if not _intro_qualified(
        player,
        cutoff=cutoff,
        correct_year=correct_year,
        difficulty=difficulty,
        title_artist_manager=title_artist_manager,
    ):
        return 0
    player.intro_speed_bonuses += 1
    rank = sum(
        1
        for p in all_players
        if p is not player
        # #1748: an eliminated player (Sudden Death) is out of the game and must
        # not occupy a slot in the intro speed ranking that survivors compete for.
        and not p.eliminated
        and _intro_qualified(
            p,
            cutoff=cutoff,
            correct_year=correct_year,
            difficulty=difficulty,
            title_artist_manager=title_artist_manager,
        )
        and p.submission_time is not None
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


def _award(
    id_: str, emoji: str, player_name: str, value: Any, value_label: str
) -> dict[str, Any]:
    """Build a superlative award dict."""
    return {
        "id": id_,
        "emoji": emoji,
        "title": id_,
        "player_name": player_name,
        "value": value,
        "value_label": value_label,
    }


def _superlative_speed_demon(players: list[PlayerSession]) -> dict[str, Any] | None:
    candidates = [
        (p, p.avg_submission_time)
        for p in players
        if p.avg_submission_time is not None
        and len(p.submission_times) >= MIN_SUBMISSIONS_FOR_SPEED
    ]
    if not candidates:
        return None
    fastest = min(candidates, key=lambda x: x[1])
    return _award(
        "speed_demon", "⚡", fastest[0].name, round(fastest[1], 1), "avg_time"
    )


def _superlative_lucky_streak(players: list[PlayerSession]) -> dict[str, Any] | None:
    candidates = [
        (p, p.best_streak) for p in players if p.best_streak >= MIN_STREAK_FOR_AWARD
    ]
    if not candidates:
        return None
    best = max(candidates, key=lambda x: x[1])
    return _award("lucky_streak", "🔥", best[0].name, best[1], "streak")


def _superlative_risk_taker(players: list[PlayerSession]) -> dict[str, Any] | None:
    candidates = [
        (p, p.bets_placed) for p in players if p.bets_placed >= MIN_BETS_FOR_AWARD
    ]
    if not candidates:
        return None
    most = max(candidates, key=lambda x: x[1])
    return _award("risk_taker", "🎲", most[0].name, most[1], "bets")


def _superlative_last_one_standing(
    players: list[PlayerSession],
) -> dict[str, Any] | None:
    """Issue #827: the sole survivor of a Sudden Death game.

    Awarded only when exactly one player was never eliminated while at least
    one other player was — i.e. a Sudden Death game that actually ran to its
    1v1 conclusion.
    """
    survivors = [p for p in players if not p.eliminated]
    eliminated = [p for p in players if p.eliminated]
    if len(survivors) != 1 or not eliminated:
        return None
    return _award(
        "last_one_standing", "💀", survivors[0].name, len(eliminated), "eliminated"
    )


def _superlative_clutch_player(
    players: list[PlayerSession], rounds_played: int
) -> dict[str, Any] | None:
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
    candidates = [
        (p, p.close_calls) for p in players if p.close_calls >= MIN_CLOSE_CALLS
    ]
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
    return _award(
        "intro_master", "🎧", intro_master[0].name, intro_master[1], "intro_bonuses"
    )


def _superlative_comeback_king(
    players: list[PlayerSession], rounds_played: int
) -> dict[str, Any] | None:
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
# Title & Artist mode superlatives (#1180). Computed only when title_artist_mode
# is on; their counters stay 0 in year mode so they self-gate regardless.
# ---------------------------------------------------------------------------


def _superlative_perfect_pair(players: list[PlayerSession]) -> dict[str, Any] | None:
    candidates = [
        (p, p.perfect_pairs)
        for p in players
        if p.perfect_pairs >= MIN_PERFECT_PAIRS_FOR_AWARD
    ]
    if not candidates:
        return None
    best = max(candidates, key=lambda x: x[1])
    return _award("perfect_pair", "💯", best[0].name, best[1], "perfect_rounds")


def _superlative_name_dropper(players: list[PlayerSession]) -> dict[str, Any] | None:
    candidates = [
        (p, p.exact_titles)
        for p in players
        if p.exact_titles >= MIN_EXACT_TITLES_FOR_AWARD
    ]
    if not candidates:
        return None
    best = max(candidates, key=lambda x: x[1])
    return _award("name_dropper", "🧠", best[0].name, best[1], "exact_titles")


def _superlative_artist_whisperer(
    players: list[PlayerSession],
) -> dict[str, Any] | None:
    candidates = [
        (p, p.correct_artists)
        for p in players
        if p.correct_artists >= MIN_CORRECT_ARTISTS_FOR_AWARD
    ]
    if not candidates:
        return None
    best = max(candidates, key=lambda x: x[1])
    return _award("artist_whisperer", "🎤", best[0].name, best[1], "artists")


def _superlative_so_close(players: list[PlayerSession]) -> dict[str, Any] | None:
    candidates = [
        (p, p.near_misses)
        for p in players
        if p.near_misses >= MIN_NEAR_MISSES_FOR_AWARD
    ]
    if not candidates:
        return None
    best = max(candidates, key=lambda x: x[1])
    return _award("so_close", "🤏", best[0].name, best[1], "near_misses")


# ---------------------------------------------------------------------------
# ScoringService — extracted from GameState (Issue #139)
# ---------------------------------------------------------------------------


class ScoringService:
    """Centralised scoring, analytics, and superlative calculations.

    Extracted from GameState (Issue #139) so that scoring logic is
    independently testable and doesn't bloat the game-lifecycle class.
    """

    @staticmethod
    def apply_closest_wins(
        players: list[PlayerSession],
        correct_year: int,
        streak_achievements: dict[str, int] | None = None,
    ) -> None:
        """Zero out round_score for players who are not closest to the correct year.

        Ties (equal distance) all keep their points. Players who didn't submit
        are already scored 0 by score_player_round and are excluded from the
        closest-distance calculation.

        Must be called *after* score_player_round has run for every player, and
        *before* the round scores are appended to cumulative totals (they are
        already added in score_player_round, so we need to undo the difference).

        ``streak_achievements`` is the same shared milestone-counter dict passed
        to score_player_round. It is needed to roll back a milestone increment
        for a streak round that closest-wins voids (#1375). When omitted the
        milestone counter cannot be decremented (callers that don't track
        achievements may pass ``None``).
        """
        # #1748: an eliminated player (Sudden Death) must not enter the
        # closest-distance calculation — a stale-client submission from someone
        # already OUT could otherwise become "closest" and zero every survivor.
        submitted = [
            p
            for p in players
            if p.submitted and p.current_guess is not None and not p.eliminated
        ]
        if not submitted:
            return

        best_diff = min(abs(p.current_guess - correct_year) for p in submitted)
        for p in submitted:
            if abs(p.current_guess - correct_year) != best_diff:
                lost = p.round_score
                p.round_score = 0
                p.score -= lost
                # Keep round_scores list in sync so superlatives
                # (clutch/comeback) and hot-streak display use the
                # actual zeroed score, not the pre-zeroed value.
                if p.round_scores:
                    p.round_scores[-1] = 0
                # Design decision: artist_bonus and movie_bonus are
                # skill-based and independent of year proximity, so they
                # are kept.  Streak bonus, however, tracks *consecutive
                # scoring rounds*; a zeroed round must break the streak
                # and undo the milestone bonus that was already added.
                p.score -= p.streak_bonus
                p.streak_bonus = 0
                p.score -= p.intro_bonus
                p.intro_bonus = 0
                # #1375: only roll back / break the streak when this player
                # actually SCORED this round (lost > 0). _apply_streak already
                # set streak=0 and saved the real previous_streak for players
                # who scored 0 — overwriting previous_streak with the now-0
                # streak here would wipe their "lost X-streak" reveal display.
                # #1721: additionally keep the streak (and its steal/milestone/
                # best_streak side-effects) alive when the player was ACCURATE
                # this round (base_score > 0). Closest-Wins still voids their
                # round POINTS above, but an accurate guess must not break a
                # streak just because someone else landed closer — otherwise
                # streaks, the Steal unlock, milestone bonuses and the 🔥
                # highlight become dead content in this mode.
                if lost > 0 and p.base_score <= 0:
                    # _apply_streak incremented streak for this scoring round,
                    # so the pre-round streak is (streak - 1). Roll back the
                    # side-effects that the now-voided round produced:
                    pre_round_streak = p.streak - 1
                    # (a) milestone achievement counter (#147) — decrement the
                    #     bucket this round's streak ticked, if any.
                    if streak_achievements is not None:
                        milestone_key = f"streak_{p.streak}"
                        if streak_achievements.get(milestone_key, 0) > 0:
                            streak_achievements[milestone_key] -= 1
                    # (b) steal unlock — revoke only if THIS round newly unlocked
                    #     it (streak hit the threshold) and it hasn't been used.
                    if (
                        p.streak == STEAL_UNLOCK_STREAK
                        and p.steal_available
                        and not p.steal_used
                    ):
                        p.steal_available = False
                    # (c) best_streak — roll back to the pre-round value only
                    #     when THIS round set the record (best_streak == the
                    #     streak we're voiding). If an earlier round already
                    #     peaked higher, best_streak stays untouched. (A rare
                    #     identical earlier peak would dip by 1 — acceptable vs.
                    #     the inflated value the bug left, per #1375.)
                    if p.best_streak == p.streak:
                        p.best_streak = pre_round_streak
                    p.previous_streak = pre_round_streak
                    p.streak = 0

    @staticmethod
    def calculate_superlatives(
        players: list[PlayerSession],
        *,
        rounds_played: int,
        movie_quiz_enabled: bool = False,
        intro_mode_enabled: bool = False,
        title_artist_mode_enabled: bool = False,
        sudden_death_mode_enabled: bool = False,
    ) -> list[dict[str, Any]]:
        """Calculate fun awards based on game performance (Story 15.2)."""
        if not players:
            return []

        # In Title & Artist mode (#1180) the speed/bet/close-call awards can
        # never qualify (their counters aren't tracked), so the TA-native
        # awards take their slots near the top of the priority order.
        builders = [
            # Issue #827: the marquee award for a Sudden Death game leads the reel.
            (
                _superlative_last_one_standing(players)
                if sudden_death_mode_enabled
                else None
            ),
            _superlative_speed_demon(players),
            _superlative_lucky_streak(players),
            _superlative_perfect_pair(players) if title_artist_mode_enabled else None,
            _superlative_name_dropper(players) if title_artist_mode_enabled else None,
            (
                _superlative_artist_whisperer(players)
                if title_artist_mode_enabled
                else None
            ),
            _superlative_so_close(players) if title_artist_mode_enabled else None,
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
                {
                    "name": p.name,
                    "guess": p.current_guess,
                    "years_off": p.years_off or 0,
                    "round_score": p.round_score,
                }
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
            p
            for p in submitted
            if p.submission_time is not None and round_start_time is not None
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
        title_artist_manager: Any | None = None,
        difficulty_bet_scaling_enabled: bool = False,
    ) -> None:
        """Score a single player for the current round. Mutates player in-place.

        When ``title_artist_manager`` is provided (title/artist mode, #1180),
        the round score is title points + artist points and the year-based
        scoring path is bypassed entirely.

        #1727: when ``difficulty_bet_scaling_enabled`` is True the won-bet payout
        scales with difficulty (easy 2x / normal 3x / hard 5x); when False the
        flat 3x applies on every difficulty (unchanged).
        """
        if title_artist_manager is not None:
            if player.submitted:
                _score_title_artist_round(
                    player, title_artist_manager, streak_achievements
                )
                # #1180: movie quiz + intro mode are compatible bonuses that
                # stack on top of the title/artist score (both are independent
                # of the year). The _score_*_round helpers overwrite the zeros
                # _score_title_artist_round set, then we add them to the score.
                _score_movie_challenge(player, movie_challenge)
                _score_intro_round(
                    player,
                    is_intro_round=is_intro_round,
                    intro_round_start_time=intro_round_start_time,
                    all_players=all_players,
                    correct_year=correct_year,
                    difficulty=difficulty,
                    title_artist_manager=title_artist_manager,
                )
                player.score += player.movie_bonus + player.intro_bonus
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
                player.artist_bonus = 0
                # #1376: the movie quiz is an independent guess that stacks on
                # top of the year/title-artist score. A player who skipped the
                # title/artist guess but answered the movie quiz correctly must
                # still earn its points and the movie_bonus_total increment
                # (Film Buff superlative) — mirroring the year-mode missed
                # branch below. Previously this was hard-zeroed, silently
                # dropping the earned bonus.
                _score_movie_challenge(player, movie_challenge, add_to_score=True)
                player.intro_bonus = 0
                player.rounds_played += 1
                player.round_scores.append(0)
            return

        if player.submitted and correct_year is not None:
            elapsed = (
                player.submission_time - round_start_time
                if player.submission_time is not None and round_start_time is not None
                else round_duration
            )
            speed_score, player.base_score, player.speed_multiplier = (
                calculate_round_score(
                    player.current_guess,
                    correct_year,
                    elapsed,
                    round_duration,
                    difficulty,
                )
            )
            player.years_off = abs(player.current_guess - correct_year)
            player.missed_round = False
            player.round_score, player.bet_outcome = apply_bet_multiplier(
                speed_score,
                player.bet,
                player.years_off == 0,
                bet_win_multiplier(
                    difficulty, scaling_enabled=difficulty_bet_scaling_enabled
                ),
            )

            _apply_streak(player, speed_score, streak_achievements)
            _score_artist_challenge(player, artist_challenge)
            _score_movie_challenge(player, movie_challenge)
            _score_intro_round(
                player,
                is_intro_round=is_intro_round,
                intro_round_start_time=intro_round_start_time,
                all_players=all_players,
                correct_year=correct_year,
                difficulty=difficulty,
                title_artist_manager=None,
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
                player.submission_times.append(
                    player.submission_time - round_start_time
                )
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
            player.rounds_played += 1
            player.round_scores.append(0)
