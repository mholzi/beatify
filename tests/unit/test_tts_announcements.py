"""Tests for the combined REVEAL TTS announcement (_announce_reveal).

The #471 TTS roadmap shipped 23 per-event announcements with no automated
coverage. _announce_reveal is the consolidation that collects the per-round
REVEAL events into a single utterance — this exercises its fragment logic,
toggle gating, and the leader / steal-unlock state it carries.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.beatify.game.player import PlayerSession
from tests.conftest import make_game_state


def _state(**overrides):
    """A GameState with a live (mock) TTS service and a captured _tts_announce."""
    state = make_game_state()
    state._tts_service = MagicMock()  # truthy → announcements run
    state._tts_announce = AsyncMock()
    for key, value in overrides.items():
        setattr(state, key, value)
    return state


def _player(name, **fields):
    player = PlayerSession(name=name, ws=None)
    for key, value in fields.items():
        setattr(player, key, value)
    return player


def _spoken(state):
    """The single combined message passed to _tts_announce, or None."""
    if not state._tts_announce.await_args_list:
        return None
    return state._tts_announce.await_args.args[0]


@pytest.mark.asyncio
async def test_no_tts_service_is_silent():
    state = _state()
    state._tts_service = None
    state.players = {"Marco": _player("Marco", submitted=True, years_off=0, score=5)}
    await state._announce_reveal(1987)
    state._tts_announce.assert_not_awaited()


@pytest.mark.asyncio
async def test_answer_with_nobody_correct():
    state = _state()
    # A submitter who was not exact and not in closest-wins mode → the
    # "nobody got it" line accompanies the answer.
    state.players = {"Marco": _player("Marco", submitted=True, years_off=4)}
    await state._announce_reveal(1987)
    assert _spoken(state) == "The answer was 1987. Nobody got it this round."


@pytest.mark.asyncio
async def test_single_exact_guess():
    state = _state()
    state.players = {"Marco": _player("Marco", submitted=True, years_off=0, score=10)}
    await state._announce_reveal(1991)
    assert "Marco got it exactly right." in _spoken(state)
    assert "Nobody got it" not in _spoken(state)


@pytest.mark.asyncio
async def test_multiple_exact_guesses_joined():
    state = _state()
    state.players = {
        "Marco": _player("Marco", submitted=True, years_off=0, score=10),
        "Anna": _player("Anna", submitted=True, years_off=0, score=10),
    }
    await state._announce_reveal(1991)
    assert "Marco and Anna got it exactly right." in _spoken(state)


@pytest.mark.asyncio
async def test_streak_milestone_fragment():
    state = _state()
    state.players = {
        "Marco": _player("Marco", submitted=True, years_off=0, score=10,
                          streak=5, streak_bonus=3),
    }
    await state._announce_reveal(1991)
    assert "Marco is on a 5-song streak." in _spoken(state)


@pytest.mark.asyncio
async def test_bet_won_and_lost_fragments():
    state = _state()
    state.players = {
        "Marco": _player("Marco", submitted=True, years_off=0, score=10,
                          bet=True, bet_outcome="won"),
        "Anna": _player("Anna", submitted=True, years_off=8, score=2,
                        bet=True, bet_outcome="lost"),
    }
    await state._announce_reveal(1991)
    spoken = _spoken(state)
    assert "Marco doubled their points." in spoken
    assert "Anna loses the bet." in spoken


@pytest.mark.asyncio
async def test_closest_wins_winner_fragment():
    state = _state(closest_wins_mode=True)
    state.players = {
        "Marco": _player("Marco", submitted=True, years_off=2, round_score=5,
                         score=5),
        "Anna": _player("Anna", submitted=True, years_off=9, round_score=0,
                        score=0),
    }
    await state._announce_reveal(1991)
    assert "Marco was closest." in _spoken(state)


@pytest.mark.asyncio
async def test_leader_change_announced_after_first_round():
    state = _state(_tts_previous_leader="Anna")
    state.players = {"Marco": _player("Marco", submitted=True, years_off=0, score=20)}
    await state._announce_reveal(1991)
    assert "Marco just took the lead." in _spoken(state)
    assert state._tts_previous_leader == "Marco"


@pytest.mark.asyncio
async def test_first_leader_is_suppressed_but_tracked():
    # _tts_previous_leader starts None — the round-1 "leader" must not be
    # announced, but the name is still recorded for next round's diff.
    state = _state()
    state.players = {"Marco": _player("Marco", submitted=True, years_off=0, score=10)}
    await state._announce_reveal(1991)
    assert "took the lead" not in (_spoken(state) or "")
    assert state._tts_previous_leader == "Marco"


@pytest.mark.asyncio
async def test_tie_at_top_resets_previous_leader():
    state = _state(_tts_previous_leader="Marco")
    state.players = {
        "Marco": _player("Marco", submitted=True, years_off=0, score=10),
        "Anna": _player("Anna", submitted=True, years_off=0, score=10),
    }
    await state._announce_reveal(1991)
    assert "It's a tie at the top." in _spoken(state)
    assert state._tts_previous_leader is None


@pytest.mark.asyncio
async def test_steal_unlock_announced_once_per_game():
    state = _state()
    marco = _player("Marco", submitted=True, years_off=0, score=10,
                    steal_available=True)
    state.players = {"Marco": marco}

    await state._announce_reveal(1991)
    assert "Marco unlocked steal." in _spoken(state)

    # Second reveal — steal still available, but must not be re-announced.
    state._tts_announce.reset_mock()
    await state._announce_reveal(1992)
    assert "unlocked steal" not in (_spoken(state) or "")


@pytest.mark.asyncio
async def test_toggle_gating_drops_fragment():
    state = _state()
    state._tts_announce_correct_answer = False
    state.players = {"Marco": _player("Marco", submitted=True, years_off=0, score=10)}
    await state._announce_reveal(1991)
    spoken = _spoken(state)
    assert "The answer was" not in spoken
    assert "Marco got it exactly right." in spoken


@pytest.mark.asyncio
async def test_all_toggles_off_is_silent():
    state = _state()
    for attr in vars(state):
        if attr.startswith("_tts_announce_"):
            setattr(state, attr, False)
    state.players = {"Marco": _player("Marco", submitted=True, years_off=0, score=10)}
    await state._announce_reveal(1991)
    state._tts_announce.assert_not_awaited()


@pytest.mark.asyncio
async def test_fragments_combine_into_one_utterance():
    state = _state(_tts_previous_leader="Anna")
    state.players = {
        "Marco": _player("Marco", submitted=True, years_off=0, score=20,
                         streak=5, streak_bonus=3, bet=True, bet_outcome="won"),
    }
    await state._announce_reveal(1987)
    # One call, one combined sentence carrying every enabled fragment.
    state._tts_announce.assert_awaited_once()
    spoken = _spoken(state)
    assert spoken == (
        "The answer was 1987. Marco got it exactly right. "
        "Marco is on a 5-song streak. Marco doubled their points. "
        "Marco just took the lead."
    )
