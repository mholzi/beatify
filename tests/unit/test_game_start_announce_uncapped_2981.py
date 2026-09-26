"""#2981: the game-start announcement leaves the round count out without a cap.

With ``max_rounds == 0`` ("all songs") ``total_rounds`` is just the size of the
song pool, e.g. 266. Since #2958 the TV and phones no longer show that number,
so the spoken announcement must not read it out either — in every language.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.beatify.game import tts_phrases as tp
from tests.conftest import make_game_state


def _state(language: str, max_rounds: int, total_rounds: int):
    state = make_game_state()
    state._tts_service = MagicMock()
    state._tts_announce = AsyncMock()
    state.language = language
    state.difficulty = "normal"
    state.max_rounds = max_rounds
    state.total_rounds = total_rounds
    return state


@pytest.mark.asyncio
async def test_uncapped_english_has_no_round_count():
    state = _state("en", max_rounds=0, total_rounds=266)
    await state.announce_game_start()
    state._tts_announce.assert_awaited_once_with(
        "Let's play Beatify — normal difficulty."
    )


@pytest.mark.asyncio
async def test_capped_english_keeps_round_count():
    state = _state("en", max_rounds=10, total_rounds=10)
    await state.announce_game_start()
    state._tts_announce.assert_awaited_once_with(
        "Let's play Beatify! 10 rounds, normal difficulty."
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("lang", tp.SUPPORTED_LANGUAGES)
async def test_uncapped_every_language_omits_pool_size(lang):
    state = _state(lang, max_rounds=0, total_rounds=266)
    await state.announce_game_start()
    spoken = state._tts_announce.await_args.args[0]
    assert spoken == tp.phrase(
        lang, "game_start_open", difficulty=tp.difficulty_label(lang, "normal")
    )
    assert "266" not in spoken
    assert tp.spoken_number(lang, 266) not in spoken
    # No round word from the capped template leaks into the open one.
    capped = tp._PHRASES[lang]["game_start"]
    round_word = capped.split("{rounds}")[1].split(",")[0].strip()
    assert round_word not in spoken


@pytest.mark.asyncio
@pytest.mark.parametrize("lang", tp.SUPPORTED_LANGUAGES)
async def test_capped_every_language_reads_round_count(lang):
    state = _state(lang, max_rounds=15, total_rounds=15)
    await state.announce_game_start()
    spoken = state._tts_announce.await_args.args[0]
    assert tp.spoken_number(lang, 15) in spoken
