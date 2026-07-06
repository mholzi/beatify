"""Difficulty-aware bet scaling tests (Issue #1727).

Opt-in, default-off scoring tweak. A won (exact-year) bet normally pays a flat
``BET_WIN_MULTIPLIER`` (×3) on every difficulty, but the exact-year probability
is exactly what difficulty modulates — so on Hard a bet is strictly bad play and
the Risk Taker superlative / bet_tracking go dead. When
``difficulty_bet_scaling_enabled`` is on, the payout scales with difficulty
(easy ×2 / normal ×3 / hard ×5).

Guarantees under test:
  * off (default) → flat ×3 on every difficulty, byte-for-byte unchanged,
  * on → easy ×2 / normal ×3 / hard ×5, unknown difficulty falls back to ×3,
  * a missed bet still forfeits the round regardless of the multiplier,
  * the setting plumbs through create_game → GameState,
  * the serializer exposes the flag AND the active payout multiplier,
  * a rematch preserves the setting,
  * the setting reaches the real per-round scoring path (score_player_round).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.beatify.const import (
    DIFFICULTY_EASY,
    DIFFICULTY_HARD,
    DIFFICULTY_NORMAL,
)
from custom_components.beatify.game.scoring import ScoringService
from custom_components.beatify.game.player import PlayerSession
from custom_components.beatify.game.serializers import GameStateSerializer

from tests.conftest import make_game_state, make_songs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_game(*, difficulty=DIFFICULTY_NORMAL, enabled=False, songs=10):
    gs = make_game_state()
    gs.create_game(
        playlists=["t.json"],
        songs=make_songs(songs),
        media_player="media_player.x",
        base_url="http://h",
        difficulty=difficulty,
        difficulty_bet_scaling_enabled=enabled,
    )
    gs.platform = "music_assistant"
    return gs


def _betting_player(name: str, guess: int) -> PlayerSession:
    p = PlayerSession(name=name, ws=MagicMock())
    p.submitted = True
    p.current_guess = guess
    p.bet = True
    p.submission_time = None  # no speed bonus → base_score == accuracy score
    return p


def _score(player, correct_year, difficulty, *, scaling):
    ScoringService.score_player_round(
        player,
        correct_year=correct_year,
        round_start_time=None,
        round_duration=30.0,
        difficulty=difficulty,
        artist_challenge=None,
        movie_challenge=None,
        is_intro_round=False,
        intro_round_start_time=None,
        all_players=[player],
        streak_achievements={},
        bet_tracking={"total_bets": 0, "bets_won": 0},
        difficulty_bet_scaling_enabled=scaling,
    )


# ---------------------------------------------------------------------------
# End-to-end scoring through score_player_round
# ---------------------------------------------------------------------------


class TestScorePlayerRoundBetPayout:
    def test_off_is_flat_three_on_hard(self):
        # POINTS_EXACT (10) × flat 3 = 30, regardless of Hard difficulty.
        p = _betting_player("A", 2000)
        _score(p, 2000, DIFFICULTY_HARD, scaling=False)
        assert p.round_score == 30
        assert p.bet_outcome == "won"

    def test_on_hard_pays_five(self):
        p = _betting_player("A", 2000)
        _score(p, 2000, DIFFICULTY_HARD, scaling=True)
        assert p.round_score == 50  # 10 × 5
        assert p.bet_outcome == "won"

    def test_on_easy_pays_two(self):
        p = _betting_player("A", 2000)
        _score(p, 2000, DIFFICULTY_EASY, scaling=True)
        assert p.round_score == 20  # 10 × 2
        assert p.bet_outcome == "won"

    def test_on_normal_pays_three(self):
        p = _betting_player("A", 2000)
        _score(p, 2000, DIFFICULTY_NORMAL, scaling=True)
        assert p.round_score == 30  # 10 × 3 (unchanged from flat)
        assert p.bet_outcome == "won"

    def test_missed_bet_forfeits_on_hard_when_scaled(self):
        # A close-but-not-exact bet still forfeits the whole round, even with
        # the boosted Hard payout — that stake is what makes the bet a risk.
        p = _betting_player("A", 1998)  # 2 off
        _score(p, 2000, DIFFICULTY_HARD, scaling=True)
        assert p.round_score == 0
        assert p.bet_outcome == "lost"


# ---------------------------------------------------------------------------
# Plumbing: create_game → GameState → serializer → rematch
# ---------------------------------------------------------------------------


class TestPlumbing:
    def test_create_game_sets_flag(self):
        gs = _make_game(enabled=True)
        assert gs.difficulty_bet_scaling_enabled is True

    def test_default_is_off(self):
        gs = _make_game()
        assert gs.difficulty_bet_scaling_enabled is False

    def test_serializer_exposes_flag(self):
        gs = _make_game(enabled=True)
        state = GameStateSerializer.serialize(gs)
        assert state["difficulty_bet_scaling_enabled"] is True

    def test_serializer_exposes_flat_multiplier_when_off(self):
        gs = _make_game(difficulty=DIFFICULTY_HARD, enabled=False)
        state = GameStateSerializer.serialize(gs)
        assert state["bet_win_multiplier"] == 3

    def test_serializer_exposes_scaled_multiplier_when_on(self):
        gs = _make_game(difficulty=DIFFICULTY_HARD, enabled=True)
        state = GameStateSerializer.serialize(gs)
        assert state["bet_win_multiplier"] == 5

    def test_serializer_scaled_multiplier_easy(self):
        gs = _make_game(difficulty=DIFFICULTY_EASY, enabled=True)
        state = GameStateSerializer.serialize(gs)
        assert state["bet_win_multiplier"] == 2

    def test_rematch_preserves_setting(self):
        gs = _make_game(enabled=True)
        gs.rematch_game()
        assert gs.difficulty_bet_scaling_enabled is True
