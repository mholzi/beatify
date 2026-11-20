"""Fun metrics and the combined objective for the Beatify simulation.

Everything here is pure arithmetic on the per-game records produced by
``fun_sim.play_game``. No point math lives here (that is scoring.py's job).

Per-game metrics are aggregated over a batch as median + IQR (q1/q3). Yes/no
metrics (decided only in the last round, Gelegenheit on the podium) are batch
proportions.

OBJECTIVE (fixed before any tuning run, must NOT be changed by phase 2)
----------------------------------------------------------------------
Each metric is mapped linearly onto 0..1 between a "bad" and a "good" anchor
(clamped), then combined with the weights below into a 0..100 score. Higher is
better. The anchors are judgement calls, written down here once so a tuning run
cannot move them after seeing results. They were widened once in phase 1,
after the first baseline showed two terms pinned at 0 (no gradient to tune
against); that was before any tuning and they are frozen from here on.

  metric                         weight  bad -> good anchor   why
  podium_gap_pct (median)         0.20   100 -> 10            a tight podium is
        the strongest single driver of "anyone can still win" tension
  lead_changes (median)           0.20   0 -> 4               the lead should
        change hands a few times per game, not never, not every round
  zero_round_share (median)       0.15   0.65 -> 0.15         a blank round is
        frustration; too many means guessers feel shut out
  open_to_last (proportion)       0.15   0.0 -> 0.5            about half of the
        games should still be open going into the last round
  gelegenheit_podium (prop.)      0.15   0.20 -> 0.60          it is a party
        game: a casual player must have a real shot at the podium (only games
        with >= 4 players count, otherwise everybody is on the podium)
  award_coverage (median)         0.15   0.20 -> 0.80          most players
        should hear their name at least once in the awards

The weights sum to 1.0 (checked at import time). They are guesses about what
makes a party game feel good, not measurements; the live test with real people
is the only judge of the final result.

Bounds, not objective terms: round duration is not simulated (the sim has no
clock), so it is only a limit in phase 2, never scored here.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median

#: name -> (weight, bad anchor, good anchor). FIXED, see module docstring.
OBJECTIVE_TERMS: dict[str, tuple[float, float, float]] = {
    "podium_gap_pct": (0.20, 100.0, 10.0),
    "lead_changes": (0.20, 0.0, 4.0),
    "zero_round_share": (0.15, 0.65, 0.15),
    "open_to_last": (0.15, 0.0, 0.5),
    "gelegenheit_podium": (0.15, 0.20, 0.60),
    "award_coverage": (0.15, 0.20, 0.80),
}

assert abs(sum(w for w, _, _ in OBJECTIVE_TERMS.values()) - 1.0) < 1e-9  # noqa: S101


@dataclass
class GameRecord:
    """What one simulated game leaves behind for the metrics."""

    profiles: list[str]  # profile name per seat
    final_scores: list[int]  # final score per seat
    score_history: list[list[int]]  # [round][seat] cumulative score
    round_deltas: list[list[int]]  # [round][seat] points gained that round
    award_winner_seats: set[int]  # seats holding >= 1 superlative


def ranking(scores: list[int]) -> list[int]:
    """Seat indices best-first. Ties break by seat order (stable, deterministic)."""
    return sorted(range(len(scores)), key=lambda i: (-scores[i], i))


def _leader_after_round(scores: list[int], previous: int | None) -> int:
    """Leader by score; on a tie at the top the previous leader keeps the lead."""
    top = max(scores)
    tied = [i for i, s in enumerate(scores) if s == top]
    if previous is not None and previous in tied:
        return previous
    return tied[0]


def game_stats(rec: GameRecord) -> dict[str, float | bool | None]:
    """Fun numbers for one game."""
    order = ranking(rec.final_scores)
    winner = order[0]
    n_players = len(rec.final_scores)
    n_rounds = len(rec.score_history)

    first = rec.final_scores[order[0]]
    third = rec.final_scores[order[2]]
    gap = (first - third) / first * 100.0 if first > 0 else None

    leaders: list[int] = []
    prev: int | None = None
    for scores in rec.score_history:
        prev = _leader_after_round(scores, prev)
        leaders.append(prev)
    lead_changes = sum(1 for a, b in zip(leaders, leaders[1:], strict=False) if a != b)

    # Settled round: first round from which the final winner leads in every
    # later round (1-based). Lead stays with the winner from there on.
    settled = n_rounds
    for r in range(n_rounds - 1, -1, -1):
        if leaders[r] == winner:
            settled = r + 1
        else:
            break
    open_to_last = n_rounds >= 2 and leaders[n_rounds - 2] != winner

    flat = [d for rnd in rec.round_deltas for d in rnd]
    zero_share = sum(1 for d in flat if d == 0) / len(flat) if flat else 0.0

    podium = set(order[:3])
    gele_seats = [i for i, p in enumerate(rec.profiles) if p == "Gelegenheit"]
    counts = n_players >= 4
    return {
        "podium_gap_pct": gap,
        "lead_changes": float(lead_changes),
        "zero_round_share": zero_share,
        "settled_round": float(settled),
        "open_to_last": open_to_last,
        "gelegenheit_seats": len(gele_seats) if counts else 0,
        "gelegenheit_on_podium": (
            sum(1 for i in gele_seats if i in podium) if counts else 0
        ),
        "gelegenheit_chance": (3.0 / n_players * len(gele_seats)) if counts else 0.0,
        "award_coverage": len(rec.award_winner_seats) / n_players,
    }


def _quartiles(values: list[float]) -> tuple[float, float, float]:
    ordered = sorted(values)
    n = len(ordered)
    if n == 0:
        return (0.0, 0.0, 0.0)
    if n == 1:
        return (ordered[0], ordered[0], ordered[0])
    mid = median(ordered)
    lower = ordered[: n // 2]
    upper = ordered[(n + 1) // 2 :]
    return (median(lower), mid, median(upper))


def _dist(values: list[float]) -> dict[str, float]:
    q1, med, q3 = _quartiles(values)
    return {"median": round(med, 4), "q1": round(q1, 4), "q3": round(q3, 4)}


def aggregate(stats: list[dict[str, float | bool | None]]) -> dict[str, object]:
    """Batch summary: median + IQR for continuous metrics, proportions for flags."""
    gaps = [
        float(s["podium_gap_pct"]) for s in stats if s["podium_gap_pct"] is not None
    ]
    seats = sum(int(s["gelegenheit_seats"]) for s in stats)
    on_podium = sum(int(s["gelegenheit_on_podium"]) for s in stats)
    chance = sum(float(s["gelegenheit_chance"]) for s in stats)
    out: dict[str, object] = {
        "games": len(stats),
        "podium_gap_pct": _dist(gaps),
        "lead_changes": _dist([float(s["lead_changes"]) for s in stats]),
        "zero_round_share": _dist([float(s["zero_round_share"]) for s in stats]),
        "settled_round": _dist([float(s["settled_round"]) for s in stats]),
        "open_to_last": {
            "share": round(sum(1 for s in stats if s["open_to_last"]) / len(stats), 4)
        },
        "gelegenheit_podium": {
            "share": round(on_podium / seats, 4) if seats else 0.0,
            "chance_level": round(chance / seats, 4) if seats else 0.0,
            "seats": seats,
        },
        "award_coverage": _dist([float(s["award_coverage"]) for s in stats]),
    }
    out["objective"] = objective(out)
    return out


def _headline(summary: dict[str, object], name: str) -> float:
    block = summary[name]
    assert isinstance(block, dict)  # noqa: S101
    return float(block["share"] if "share" in block else block["median"])


def objective(summary: dict[str, object]) -> dict[str, object]:
    """Combine the headline numbers into the fixed 0..100 objective."""
    parts: dict[str, float] = {}
    total = 0.0
    for name, (weight, bad, good) in OBJECTIVE_TERMS.items():
        value = _headline(summary, name)
        goodness = (value - bad) / (good - bad)
        goodness = max(0.0, min(1.0, goodness))
        parts[name] = round(goodness, 4)
        total += weight * goodness
    return {"score": round(total * 100.0, 2), "term_goodness": parts}
