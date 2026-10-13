"""#3157 — the phone's points breakdown must show what the server awarded.

``player-reveal.js`` used to recompute the speed bonus as
``Math.floor(base * speed_multiplier) - base`` while the scorer has used
``round()`` since #1722, and it hard-coded a won bet as "x2" although the
payout is 3 by default (2/3/5 with difficulty scaling). The server now sends
the pre-bet ``speed_bonus`` per player and the state already carries
``bet_win_multiplier``; the client renders both and recomputes neither.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from custom_components.beatify.game.scoring import calculate_round_score
from tests.conftest import make_game_state, make_songs

REVEAL_JS = (
    Path(__file__).resolve().parents[2]
    / "custom_components"
    / "beatify"
    / "www"
    / "js"
    / "player-reveal.js"
)


def _state_with_player():
    state = make_game_state()
    state.create_game(
        playlists=["test.json"],
        songs=make_songs(5),
        media_player="media_player.test",
        base_url="http://localhost:8123",
    )
    state.add_player("Alice", MagicMock())
    return state


@pytest.mark.parametrize(
    ("guess", "elapsed"),
    [(1990, 0.0), (1989, 20.0), (1985, 25.0), (1980, 15.0), (1975, 27.5)],
)
def test_speed_bonus_matches_the_scorer(guess: int, elapsed: float) -> None:
    """speed_bonus == awarded pre-bet score minus base, rounding included."""
    points, base, multiplier = calculate_round_score(guess, 1990, elapsed, 30.0)
    state = _state_with_player()
    player = state.get_player("Alice")
    player.base_score = base
    player.speed_multiplier = multiplier

    row = next(r for r in state.get_reveal_players_state() if r["name"] == "Alice")

    assert row["speed_bonus"] == points - base


def test_speed_bonus_rounds_up_for_the_one_point_tier() -> None:
    """base 1 x 1.9 is 2 on the server: the row the floor version dropped."""
    state = _state_with_player()
    player = state.get_player("Alice")
    player.base_score = 1
    player.speed_multiplier = 1.9

    row = state.get_reveal_players_state()[0]

    assert row["speed_bonus"] == 1


def test_client_recomputes_neither_speed_bonus_nor_bet_multiplier() -> None:
    """Source guard: no floor() recomputation, no fixed bet multiplier."""
    src = REVEAL_JS.read_text(encoding="utf-8")
    assert "Math.floor(base * speedMultiplier)" not in src
    assert "value: '×2'" not in src
    assert "player.speed_bonus" in src
    assert "betWinMultiplier" in src
