"""Sudden Death ghosts stay out of round analytics, song stats and highlights (#3028).

A ghost (#2559) keeps guessing after elimination. ``score_ghost_round`` fills
only ``ghost_score`` and never writes ``years_off``, so the ghost reaches the
reveal with ``submitted = True`` and ``years_off = None``. Every consumer that
coerced ``years_off or 0`` turned that into an exact answer: "Closest · Exact!"
on the reveal, a 0-years-off song result for the difficulty rating, and the
ghost's frozen streak re-recorded as a milestone highlight every round.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.beatify.game.config import GameOptions
from custom_components.beatify.game.scoring import ScoringService
from custom_components.beatify.game.state import GameState

from tests.conftest import make_game_state


def _songs(n: int = 5) -> list[dict[str, Any]]:
    return [
        {
            "year": 1980 + i,
            "title": f"Song {i}",
            "artist": f"Artist {i}",
            "uri": f"spotify:track:test{i:022d}",
            "uri_spotify": f"spotify:track:test{i:022d}",
        }
        for i in range(n)
    ]


@pytest.fixture
def game() -> GameState:
    state = make_game_state()
    state.create_game(
        playlists=["test.json"],
        songs=_songs(),
        media_player="media_player.party",
        base_url="http://localhost:8123",
        options=GameOptions(sudden_death_mode=True),
    )
    return state


def _seat(state: GameState, name: str):
    ok, _ = state.add_player(name, ws=None)
    assert ok, name
    return state.get_player(name)


def _living_and_ghost(game: GameState):
    """A survivor 5 years off and a ghost as the reveal sees them."""
    lebend = _seat(game, "Mara")
    lebend.submitted = True
    lebend.current_guess = 1990
    lebend.years_off = 5
    lebend.round_score = 2
    lebend.submission_time = 8.0

    ghost = _seat(game, "Tom")
    ghost.eliminated = True
    ghost.eliminated_round = 1
    ghost.submitted = True
    ghost.current_guess = 1970
    ghost.years_off = None  # score_ghost_round never writes it
    ghost.submission_time = 1.0  # faster than anyone alive
    ghost.streak = 3  # frozen at elimination, a milestone value
    return lebend, ghost


class TestRoundAnalytics:
    def test_a_ghost_is_not_closest_nor_exact(self, game: GameState):
        lebend, _ghost = _living_and_ghost(game)

        analytics = ScoringService.calculate_round_analytics(
            list(game.players.values()), correct_year=1985, round_start_time=0.0
        )

        assert [g["name"] for g in analytics.all_guesses] == ["Mara"]
        assert analytics.closest_players == ["Mara"]
        assert analytics.exact_match_players == []
        assert analytics.total_submitted == 1
        assert analytics.accuracy_percentage == 100
        assert analytics.speed_champion["names"] == ["Mara"]

    def test_only_ghosts_submitted_gives_empty_analytics(self, game: GameState):
        lebend, _ghost = _living_and_ghost(game)
        lebend.submitted = False

        analytics = ScoringService.calculate_round_analytics(
            list(game.players.values()), correct_year=1985, round_start_time=0.0
        )

        assert analytics.all_guesses == []
        assert analytics.total_submitted == 0


class TestSongStats:
    @pytest.mark.asyncio
    async def test_a_ghost_is_not_fed_to_the_song_difficulty(self, game: GameState):
        _living_and_ghost(game)
        game.current_song = _songs()[0]
        stats = MagicMock()
        stats.record_song_result = AsyncMock()
        game._stats_service = stats

        await game._record_round_stats(correct_year=1985)

        stats.record_song_result.assert_awaited_once()
        player_results = stats.record_song_result.await_args.args[1]
        assert player_results == [{"submitted": True, "years_off": 5}]


class TestHighlights:
    def test_a_ghost_gets_no_streak_or_speed_highlight(self, game: GameState):
        _living_and_ghost(game)
        game.round_start_time = 0.0

        game._record_round_highlights(correct_year=1985)

        players = {h.player for h in game.highlights_tracker._highlights}
        assert "Tom" not in players
