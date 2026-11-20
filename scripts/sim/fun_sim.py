"""Beatify game simulation harness: bot players against the REAL scoring code.

Usage::

    python scripts/sim/fun_sim.py --games 1000 --seed 1 --json out.json
    python scripts/sim/fun_sim.py --baseline --games 1000 --json baseline.json

This changes no gameplay and is not shipped (the file lives under scripts/).

How a round is scored (nothing is re-implemented here):

1. Every bot gets a real ``PlayerSession`` (``reset_round`` + ``submit_guess``,
   the same calls the websocket handler makes).
2. ``ScoringService.score_player_round`` scores each player - this is the very
   function ``GameState._score_all_players`` calls. It in turn uses
   ``calculate_round_score`` (accuracy + speed), ``apply_bet_multiplier``,
   ``_apply_streak`` (milestones, shield, steal unlock) and so on.
3. With ``--closest-wins``, ``ScoringService.apply_closest_wins`` runs after it,
   exactly as ``RoundScoringMixin._score_round`` does.
4. At the end ``ScoringService.calculate_superlatives`` produces the awards.

What the sim does not cover: steal/sabotage power-ups (bots never use them),
artist/movie/intro/title-artist bonus modes, Sudden Death and ghosts, the real
timer and reveal pacing, music and mood. See the PR text.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from random import Random

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parents[1]
for _p in (str(_ROOT), str(_HERE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

try:  # real Home Assistant is only present inside an HA venv
    import homeassistant  # noqa: F401
except ModuleNotFoundError:  # reuse the repo's own stubs (root conftest.py)
    import conftest  # noqa: F401
    from types import ModuleType
    from unittest.mock import MagicMock

    # Same extra stub tests/conftest.py installs before importing beatify.
    _er = ModuleType("homeassistant.helpers.entity_registry")
    _er.async_get = MagicMock()  # type: ignore[attr-defined]
    sys.modules.setdefault("homeassistant.helpers.entity_registry", _er)

import metrics  # noqa: E402
import profiles  # noqa: E402

from custom_components.beatify.const import (  # noqa: E402
    DEFAULT_ROUND_DURATION,
    DIFFICULTY_DEFAULT,
    STREAK_MILESTONES,
)
from custom_components.beatify.game.player import PlayerSession  # noqa: E402
from custom_components.beatify.game.scoring import ScoringService  # noqa: E402

PLAYLIST_DIR = _ROOT / "custom_components" / "beatify" / "playlists"

#: Rounds per simulated game. The real default is "play the whole playlist"
#: (max_rounds = 0), which is too long to be a party evening; 20 is the middle
#: preset chip of the setup wizard (10/20/30).
DEFAULT_ROUNDS = 20

#: Clock origin for the simulated round, so elapsed time is a real difference.
ROUND_START = 1000.0


@dataclass(frozen=True)
class Decision:
    """What one bot does in one round. ``guess=None`` = did not submit."""

    guess: int | None
    elapsed: float
    bet: bool = False


def load_song_years(directory: Path = PLAYLIST_DIR) -> list[int]:
    """Read the year of every song from the real playlist JSONs (read only)."""
    years: list[int] = []
    for path in sorted(glob.glob(str(directory / "*.json"))):
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        years.extend(
            s["year"] for s in data.get("songs", []) if isinstance(s.get("year"), int)
        )
    return years


def make_players(names: list[str]) -> list[PlayerSession]:
    """Real ``PlayerSession`` objects without a websocket."""
    return [PlayerSession(name=n, ws=None) for n in names]  # type: ignore[arg-type]


def new_trackers() -> tuple[dict[str, int], dict[str, int]]:
    """Fresh (streak_achievements, bet_tracking) dicts as GameState keeps them."""
    streaks = {f"streak_{n}": 0 for n in STREAK_MILESTONES}
    bets = {"total_bets": 0, "bets_won": 0}
    return streaks, bets


def play_round(
    players: list[PlayerSession],
    decisions: list[Decision],
    correct_year: int,
    *,
    streak_achievements: dict[str, int],
    bet_tracking: dict[str, int],
    round_duration: float = DEFAULT_ROUND_DURATION,
    difficulty: str = DIFFICULTY_DEFAULT,
    closest_wins: bool = False,
) -> list[int]:
    """Play one round through the real scoring code. Returns points gained per seat."""
    before = [p.score for p in players]
    for player, decision in zip(players, decisions, strict=True):
        player.reset_round()
        if decision.guess is not None and decision.elapsed < round_duration:
            player.submit_guess(decision.guess, ROUND_START + decision.elapsed)
            player.bet = decision.bet
    for player in players:
        ScoringService.score_player_round(
            player,
            correct_year=correct_year,
            round_start_time=ROUND_START,
            round_duration=round_duration,
            difficulty=difficulty,
            artist_challenge=None,
            movie_challenge=None,
            is_intro_round=False,
            intro_round_start_time=None,
            all_players=players,
            streak_achievements=streak_achievements,
            bet_tracking=bet_tracking,
        )
    if closest_wins:
        ScoringService.apply_closest_wins(players, correct_year, streak_achievements)
    return [p.score - b for p, b in zip(players, before, strict=True)]


def play_game(
    rng: Random,
    song_years: list[int],
    *,
    mix: str = "default",
    rounds: int = DEFAULT_ROUNDS,
    difficulty: str = DIFFICULTY_DEFAULT,
    closest_wins: bool = False,
    round_duration: float = DEFAULT_ROUND_DURATION,
) -> metrics.GameRecord:
    """Simulate one whole game and return its record."""
    roster = profiles.draw_roster(rng, mix)
    players = make_players([f"{p.name}{i}" for i, p in enumerate(roster)])
    streaks, bets = new_trackers()
    years = rng.sample(song_years, min(rounds, len(song_years)))

    history: list[list[int]] = []
    deltas: list[list[int]] = []
    for year in years:
        decisions = []
        for profile in roster:
            elapsed = profile.submit_time(rng)
            decisions.append(
                Decision(profile.guess(rng, year), elapsed, profile.wants_bet(rng))
            )
        deltas.append(
            play_round(
                players,
                decisions,
                year,
                streak_achievements=streaks,
                bet_tracking=bets,
                round_duration=round_duration,
                difficulty=difficulty,
                closest_wins=closest_wins,
            )
        )
        history.append([p.score for p in players])

    awards = ScoringService.calculate_superlatives(players, rounds_played=len(years))
    names = {p.name: i for i, p in enumerate(players)}
    return metrics.GameRecord(
        profiles=[p.name for p in roster],
        final_scores=[p.score for p in players],
        score_history=history,
        round_deltas=deltas,
        award_winner_seats={names[a["player_name"]] for a in awards},
    )


def run_batch(
    games: int,
    seed: int,
    *,
    mix: str = "default",
    rounds: int = DEFAULT_ROUNDS,
    difficulty: str = DIFFICULTY_DEFAULT,
    closest_wins: bool = False,
    song_years: list[int] | None = None,
) -> dict[str, object]:
    """Run ``games`` seeded games and aggregate the fun metrics."""
    years = song_years if song_years is not None else load_song_years()
    rng = Random(seed)  # noqa: S311 - simulation, not security
    stats = [
        metrics.game_stats(
            play_game(
                rng,
                years,
                mix=mix,
                rounds=rounds,
                difficulty=difficulty,
                closest_wins=closest_wins,
            )
        )
        for _ in range(games)
    ]
    result = metrics.aggregate(stats)
    result.update(
        {"seed": seed, "mix": mix, "rounds": rounds, "difficulty": difficulty}
    )
    return result


def format_table(results: list[dict[str, object]]) -> str:
    """Short plain-text table, one column per batch."""

    def med(r: dict[str, object], key: str, fmt: str) -> str:
        block = r[key]
        assert isinstance(block, dict)  # noqa: S101
        return fmt.format(block["median"], block["q1"], block["q3"])

    cols = [f"{r['mix']}/seed{r['seed']}" for r in results]
    rows: list[tuple[str, list[str]]] = [
        (
            "podium gap 1-3 (% of winner)",
            [med(r, "podium_gap_pct", "{:.1f} [{:.1f}-{:.1f}]") for r in results],
        ),
        (
            "lead changes / game",
            [med(r, "lead_changes", "{:.0f} [{:.0f}-{:.0f}]") for r in results],
        ),
        (
            "zero-point player-rounds",
            [med(r, "zero_round_share", "{:.0%} [{:.0%}-{:.0%}]") for r in results],
        ),
        (
            "settled from round",
            [med(r, "settled_round", "{:.0f} [{:.0f}-{:.0f}]") for r in results],
        ),
        (
            "open until last round",
            [f"{r['open_to_last']['share']:.0%}" for r in results],
        ),  # type: ignore[index]
        (
            "Gelegenheit on podium (>=4p)",
            [
                f"{r['gelegenheit_podium']['share']:.0%} (chance {r['gelegenheit_podium']['chance_level']:.0%})"
                for r in results
            ],
        ),  # type: ignore[index]
        (
            "players with an award",
            [med(r, "award_coverage", "{:.0%} [{:.0%}-{:.0%}]") for r in results],
        ),
        ("OBJECTIVE (0-100)", [f"{r['objective']['score']:.1f}" for r in results]),  # type: ignore[index]
    ]
    width = max(len(label) for label, _ in rows)
    colw = max(len(v) for _, vals in rows for v in vals + cols)
    lines = [" " * width + "  " + "  ".join(c.rjust(colw) for c in cols)]
    lines.extend(
        label.ljust(width) + "  " + "  ".join(v.rjust(colw) for v in vals)
        for label, vals in rows
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--games", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--mix", choices=sorted(profiles.MIXES), default="default")
    ap.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS)
    ap.add_argument("--difficulty", default=DIFFICULTY_DEFAULT)
    ap.add_argument("--closest-wins", action="store_true")
    ap.add_argument("--json", metavar="PATH", help="write the result as JSON")
    ap.add_argument(
        "--baseline",
        action="store_true",
        help="run default+casual mixes with seeds 1 and 2 (ignores --seed/--mix)",
    )
    args = ap.parse_args(argv)

    years = load_song_years()
    started = time.perf_counter()
    plan = (
        [("default", 1), ("default", 2), ("casual", 1), ("casual", 2)]
        if args.baseline
        else [(args.mix, args.seed)]
    )
    results = [
        run_batch(
            args.games,
            seed,
            mix=mix,
            rounds=args.rounds,
            difficulty=args.difficulty,
            closest_wins=args.closest_wins,
            song_years=years,
        )
        for mix, seed in plan
    ]
    elapsed = time.perf_counter() - started
    print(format_table(results))
    print(f"\n{len(results)} batch(es) x {args.games} games in {elapsed:.1f}s")
    if args.json:
        payload = {
            "games_per_batch": args.games,
            "objective_terms": {
                k: {"weight": w, "bad": b, "good": g}
                for k, (w, b, g) in metrics.OBJECTIVE_TERMS.items()
            },
            "batches": results,
        }
        Path(args.json).write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
