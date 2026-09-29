"""#3062: the REVEAL announcement in Title & Artist mode.

In Title & Artist mode nobody guesses the year, so the old announcement —
"The answer was 1985. Nobody got it this round." — was wrong twice: it named
the year instead of the song, and ``years_off`` is always None in this mode, so
the "nobody got it" line fired every round regardless of who got the song.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.beatify.game.challenges import TitleArtistChallenge
from custom_components.beatify.game.player import PlayerSession
from tests.conftest import make_game_state


def _state(guesses, **overrides):
    state = make_game_state()
    state._tts_service = MagicMock()
    state._tts_announce = AsyncMock()
    state.title_artist_mode = True
    state.title_artist_challenge = TitleArtistChallenge(
        correct_title="Take On Me",
        correct_artist="a-ha",
        guesses=guesses,
    )
    state.players = {
        name: PlayerSession(name=name, ws=None) for name in guesses or {"Marco": 0}
    }
    for player in state.players.values():
        player.submitted = True
        player.years_off = None
    for key, value in overrides.items():
        setattr(state, key, value)
    return state


def _guess(title_status, artist_status):
    return {
        "title": "x",
        "artist": "y",
        "title_status": title_status,
        "artist_status": artist_status,
        "ts": 0.0,
    }


def _spoken(state):
    if not state._tts_announce.await_args_list:
        return None
    return state._tts_announce.await_args.args[0]


@pytest.mark.asyncio
async def test_answer_names_title_and_artist_not_year():
    state = _state({"Marco": _guess("skipped", "skipped")})
    await state._announce_reveal(1985)
    spoken = _spoken(state)
    assert spoken.startswith("The answer was Take On Me by a-ha.")
    assert "1985" not in spoken


@pytest.mark.asyncio
async def test_nobody_line_when_no_field_right():
    state = _state({"Marco": _guess("skipped", "skipped")})
    await state._announce_reveal(1985)
    assert _spoken(state) == (
        "The answer was Take On Me by a-ha. Nobody got it this round."
    )


@pytest.mark.asyncio
async def test_no_nobody_line_when_someone_got_the_title():
    state = _state({"Marco": _guess("exact", "skipped")})
    await state._announce_reveal(1985)
    assert "Nobody got it" not in _spoken(state)


@pytest.mark.asyncio
async def test_no_nobody_line_when_someone_got_the_artist_fuzzy():
    state = _state({"Marco": _guess("skipped", "fuzzy")})
    await state._announce_reveal(1985)
    assert "Nobody got it" not in _spoken(state)


@pytest.mark.asyncio
async def test_no_nobody_line_while_a_near_miss_awaits_the_vote():
    state = _state({"Marco": _guess("near_miss", "skipped")})
    await state._announce_reveal(1985)
    assert _spoken(state) == "The answer was Take On Me by a-ha."


@pytest.mark.asyncio
async def test_players_with_both_fields_are_named():
    state = _state(
        {
            "Marco": _guess("exact", "fuzzy"),
            "Anna": _guess("exact", "skipped"),
        }
    )
    await state._announce_reveal(1985)
    # Only Marco got BOTH fields; Anna's title alone doesn't earn the line,
    # but it does keep "nobody got it" away.
    assert _spoken(state) == (
        "The answer was Take On Me by a-ha. Marco got it exactly right."
    )


@pytest.mark.asyncio
async def test_localized_german():
    state = _state({"Marco": _guess("skipped", "skipped")}, language="de")
    await state._announce_reveal(1985)
    assert _spoken(state) == (
        "Die Antwort war Take On Me von a-ha. Diese Runde hatte niemand richtig."
    )


@pytest.mark.asyncio
async def test_year_mode_unchanged():
    state = make_game_state()
    state._tts_service = MagicMock()
    state._tts_announce = AsyncMock()
    player = PlayerSession(name="Marco", ws=None)
    player.submitted = True
    player.years_off = 4
    state.players = {"Marco": player}
    await state._announce_reveal(1987)
    assert _spoken(state) == "The answer was 1987. Nobody got it this round."
