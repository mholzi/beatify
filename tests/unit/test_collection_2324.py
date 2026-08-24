"""Collected row — issue #2324, shape E.

The mode discussion on #2324 offered five shapes; this is E: the year guess is
unchanged, the currency stays points, and a guess that lands inside the
difficulty's ``close_range`` pins the song to a row the player keeps. The row
grows *beside* the score, which is the whole reason E costs what it costs —
nothing in the scorer, the superlatives or the power-ups had to move.

What these tests pin down:

* the threshold is the one already used to classify ``round_results`` — one
  rule for "close enough", not a second one that can drift from it;
* title/artist mode never collects, even though its classifier returns the same
  ``exact``/``scored`` strings (the guard is ``years_off``, not a mode flag);
* the row is game-level: a new round must not clear it, a new game must.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.beatify.game.share import build_emoji_grid
from custom_components.beatify.game.state import GamePhase
from tests.conftest import make_game_state, make_player, make_songs


def _started_game(*names: str, difficulty: str = "normal"):
    """Start a game with ``names`` plus a silent extra player.

    ``MIN_PLAYERS`` is 2, so a one-player test still needs a body in the room.
    "Nobody" never submits, so it never collects and never affects a threshold
    assertion — it exists only to clear the start gate.
    """
    state = make_game_state()
    state.create_game(
        playlists=["test.json"],
        songs=make_songs(5),
        media_player="media_player.test",
        base_url="http://localhost:8123",
    )
    state.difficulty = difficulty
    for name in (*names, "Nobody"):
        state.add_player(name, MagicMock())
    started, _ = state.start_game()
    assert started is True
    return state


def _begin_round(state, *, year: int, title: str = "Test Song") -> None:
    state.current_song = {"title": title, "artist": "Test Artist", "year": year}
    state.round_start_time = state._now()
    state.phase = GamePhase.PLAYING


class TestThreshold:
    @pytest.mark.asyncio
    async def test_exact_and_close_range_edge_collect(self):
        """Exact and a guess exactly ``close_range`` off both keep the song.

        Normal difficulty's ``close_range`` is 3, so 1987 against 1990 is the
        last guess that still counts — the boundary itself, not one inside it.
        """
        state = _started_game("Alice", "Bob")
        _begin_round(state, year=1990)
        state.get_player("Alice").submit_guess(1990, state._now())
        state.get_player("Bob").submit_guess(1987, state._now())

        await state.end_round()

        assert len(state.get_player("Alice").collection) == 1
        assert len(state.get_player("Bob").collection) == 1

    @pytest.mark.asyncio
    async def test_one_year_past_close_range_does_not_collect(self):
        """4 years off on normal difficulty still scores, but keeps nothing.

        This is the line the feature lives on: ``close`` (near_range) earns a
        point and is NOT a keeper. If this test ever flips, the row silently
        becomes "everyone keeps everything".
        """
        state = _started_game("Alice")
        _begin_round(state, year=1990)
        state.get_player("Alice").submit_guess(1986, state._now())

        await state.end_round()

        alice = state.get_player("Alice")
        assert alice.round_results == ["close"]
        assert alice.collection == []

    @pytest.mark.asyncio
    async def test_miss_and_no_submission_collect_nothing(self):
        state = _started_game("Alice", "Bob")
        _begin_round(state, year=1990)
        state.get_player("Alice").submit_guess(2015, state._now())
        # Bob stays silent.

        await state.end_round()

        assert state.get_player("Alice").collection == []
        assert state.get_player("Bob").collection == []

    @pytest.mark.asyncio
    async def test_hard_difficulty_uses_its_own_narrower_range(self):
        """The threshold follows the difficulty, it is not a constant.

        Hard's ``close_range`` is 2, so the same 3-year guess that keeps the
        song on normal must not keep it here.
        """
        state = _started_game("Alice", difficulty="hard")
        _begin_round(state, year=1990)
        state.get_player("Alice").submit_guess(1987, state._now())

        await state.end_round()

        assert state.get_player("Alice").collection == []


class TestEntryContent:
    @pytest.mark.asyncio
    async def test_entry_carries_song_and_round(self):
        state = _started_game("Alice")
        _begin_round(state, year=1990, title="Nothing Compares 2 U")
        state.get_player("Alice").submit_guess(1990, state._now())

        await state.end_round()

        entry = state.get_player("Alice").collection[0]
        assert entry["title"] == "Nothing Compares 2 U"
        assert entry["artist"] == "Test Artist"
        assert entry["year"] == 1990
        assert entry["round"] == state.round

    @pytest.mark.asyncio
    async def test_row_grows_across_rounds(self):
        state = _started_game("Alice")
        for year in (1975, 1990, 2004):
            _begin_round(state, year=year, title=f"Song {year}")
            state.get_player("Alice").submit_guess(year, state._now())
            await state.end_round()
            state.round += 1
            for player in state.players.values():
                player.reset_round()

        collected = state.get_player("Alice").collection
        assert [entry["year"] for entry in collected] == [1975, 1990, 2004]

    @pytest.mark.asyncio
    async def test_song_without_a_year_is_not_collected(self):
        """A catalogue entry missing its year cannot go on a timeline.

        The guess path can still score (``correct_year`` comes from the round,
        not from this dict), so the row needs its own guard — an entry with
        ``year: None`` would render as a blank card in the middle of the row.
        """
        state = _started_game("Alice")
        _begin_round(state, year=1990)
        state.get_player("Alice").submit_guess(1990, state._now())
        state.current_song = {"title": "No Year", "artist": "Someone", "year": None}

        await state.end_round()

        assert state.get_player("Alice").collection == []


class TestTitleArtistModeNeverCollects:
    @pytest.mark.asyncio
    async def test_title_artist_round_keeps_nothing(self):
        """#1180's classifier returns "exact"/"scored" too — and must not collect.

        Its rounds have no year guess at all, so a row built from them would be
        a timeline of songs nobody placed. The guard that separates the two is
        ``years_off``, which only the year path sets.
        """
        state = _started_game("Alice")
        state.title_artist_mode = True
        _begin_round(state, year=1990)
        alice = state.get_player("Alice")
        alice.submitted = True
        alice.years_off = None

        await state.end_round()

        assert alice.collection == []


class TestRowLifetime:
    def test_reset_round_keeps_the_row_reset_for_new_game_clears_it(self):
        """The row is game-level, like ``round_results`` and ``best_streak``.

        Clearing it in ``reset_round`` would empty it before every round — the
        row would never be longer than one song and the feature would look
        broken rather than absent.
        """
        player = make_player("Alice")
        player.collection.append(
            {"title": "T", "artist": "A", "year": 1990, "round": 1}
        )

        player.reset_round()
        assert len(player.collection) == 1

        player.reset_for_new_game()
        assert player.collection == []


class TestSerialization:
    @pytest.mark.asyncio
    async def test_reveal_payload_carries_the_row(self):
        state = _started_game("Alice")
        _begin_round(state, year=1990)
        state.get_player("Alice").submit_guess(1990, state._now())

        await state.end_round()

        rows = state.get_reveal_players_state()
        alice_row = next(row for row in rows if row["name"] == "Alice")
        assert len(alice_row["collection"]) == 1
        assert alice_row["collection"][0]["year"] == 1990

    @pytest.mark.asyncio
    async def test_reveal_payload_copies_entries(self):
        """A client payload must not alias live player state.

        Same rule ``was_stolen_by`` follows: a serializer that hands out the
        live list lets a later mutation appear in an already-sent frame.
        """
        state = _started_game("Alice")
        _begin_round(state, year=1990)
        state.get_player("Alice").submit_guess(1990, state._now())

        await state.end_round()

        rows = state.get_reveal_players_state()
        alice_row = next(row for row in rows if row["name"] == "Alice")
        alice_row["collection"][0]["year"] = 1234
        assert state.get_player("Alice").collection[0]["year"] == 1990

    @pytest.mark.asyncio
    async def test_final_leaderboard_carries_the_row(self):
        state = _started_game("Alice")
        _begin_round(state, year=1990)
        state.get_player("Alice").submit_guess(1990, state._now())

        await state.end_round()

        entry = next(
            row for row in state.get_final_leaderboard() if row["name"] == "Alice"
        )
        assert len(entry["collection"]) == 1


class TestShareCard:
    def test_share_card_shows_count_and_span(self):
        player = make_player("Alice", score=42)
        player.round_results = ["exact", "scored"]
        player.collection = [
            {"title": "A", "artist": "X", "year": 2004, "round": 1},
            {"title": "B", "artist": "Y", "year": 1968, "round": 2},
        ]

        card = build_emoji_grid(player, "90s Hits", 2)

        assert "2 collected | 1968–2004" in card
        assert card.strip().endswith("beatify.fun")

    def test_share_card_omits_the_line_when_nothing_was_collected(self):
        player = make_player("Alice", score=0)
        player.round_results = ["missed"]

        card = build_emoji_grid(player, "90s Hits", 1)

        assert "collected" not in card
