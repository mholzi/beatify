"""Fixed bot player profiles and profile mixes for the fun simulation.

The profiles are FIXED. They are part of the measuring instrument: changing
them between a baseline and a tuned run would move the goalposts. Phase 2
(tuning) must not edit this file; ``tests/unit/test_fun_sim.py`` pins the
numbers.

A profile only describes *behaviour* (what year the bot guesses, when it
submits, whether it bets). It never touches the point math, which always comes
from ``custom_components/beatify/game/scoring.py``.

Profiles
--------
Kenner       knows the song: year error ~ N(0, 2), submits fast (3-14 s of 45).
Gelegenheit  casual listener: year error ~ N(0, 8), submits mid-round (8-30 s).
Rater        guesses blindly: year error uniform in [-20, +20], 3-40 s.
Zoegerer     knows the song (~ N(0, 3)) but waits: submits 32-46 s, so about
             one round in fourteen runs past the 45 s deadline and is missed.
Zocker       ~ N(0, 6), bets on half of the rounds, submits 5-25 s.
"""

from __future__ import annotations

from dataclasses import dataclass
from random import Random

MIN_YEAR = 1900
MAX_YEAR = 2030


@dataclass(frozen=True)
class Profile:
    """Behaviour of one bot kind."""

    name: str
    #: "normal" -> N(0, spread); "uniform" -> U(-spread, +spread)
    error_kind: str
    error_spread: float
    #: submission time window as seconds from round start (uniform)
    submit_min: float
    submit_max: float
    #: probability of placing a bet in a round
    bet_prob: float

    def guess(self, rng: Random, actual_year: int) -> int:
        """Return the year this bot guesses for ``actual_year``."""
        if self.error_kind == "uniform":
            error = rng.randint(-int(self.error_spread), int(self.error_spread))
        else:
            error = round(rng.gauss(0.0, self.error_spread))
        return max(MIN_YEAR, min(MAX_YEAR, actual_year + error))

    def submit_time(self, rng: Random) -> float:
        """Return seconds after round start at which the bot submits."""
        return rng.uniform(self.submit_min, self.submit_max)

    def wants_bet(self, rng: Random) -> bool:
        """Return True if the bot places a bet this round."""
        return rng.random() < self.bet_prob


KENNER = Profile("Kenner", "normal", 2.0, 3.0, 14.0, 0.10)
GELEGENHEIT = Profile("Gelegenheit", "normal", 8.0, 8.0, 30.0, 0.05)
RATER = Profile("Rater", "uniform", 20.0, 3.0, 40.0, 0.05)
ZOEGERER = Profile("Zoegerer", "normal", 3.0, 32.0, 46.0, 0.05)
ZOCKER = Profile("Zocker", "normal", 6.0, 5.0, 25.0, 0.50)

PROFILES: dict[str, Profile] = {
    p.name: p for p in (KENNER, GELEGENHEIT, RATER, ZOEGERER, ZOCKER)
}

#: Profile mixes: weight per profile when a seat is filled. ``default`` is the
#: tuning mix; ``casual`` (party crowd, few experts) exists only to detect
#: overfitting to the default mix.
MIXES: dict[str, dict[str, float]] = {
    "default": {
        "Kenner": 1.0,
        "Gelegenheit": 1.0,
        "Rater": 1.0,
        "Zoegerer": 1.0,
        "Zocker": 1.0,
    },
    "casual": {
        "Kenner": 0.5,
        "Gelegenheit": 3.0,
        "Rater": 2.0,
        "Zoegerer": 0.5,
        "Zocker": 1.5,
    },
}

MIN_PLAYERS = 3
MAX_PLAYERS = 8


def draw_roster(rng: Random, mix: str) -> list[Profile]:
    """Draw 3-8 bot profiles for one game from the named mix."""
    weights = MIXES[mix]
    n_players = rng.randint(MIN_PLAYERS, MAX_PLAYERS)
    names = list(weights)
    picks = rng.choices(names, weights=[weights[n] for n in names], k=n_players)
    return [PROFILES[n] for n in picks]
