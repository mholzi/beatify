"""#2734: the finale playoff finally says something out loud.

#2722 built the TV banner and the finalists' phone screens for a playoff round
and deliberately left the voice unbuilt — the trigger inside
``maybe_start_finale_playoff`` was under repair at the time (#2689, #2692).
The reasoning in that issue is the reason this test exists:

    a wrong banner is read once; a wrong voice interrupts the room and cannot
    be unheard.

So the announcement fires **after** ``start_round()`` confirms, never before.
The last test here is the one that matters: when the round fails to launch, the
room stays silent, exactly as it did before this feature existed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from custom_components.beatify.game import tts_phrases
from custom_components.beatify.game.state import GamePhase
from tests.conftest import make_game_state


def _tied_game(monkeypatch, *, start_succeeds: bool):
    """A REVEAL-phase game with two players tied for first."""
    state = make_game_state()
    state.phase = GamePhase.REVEAL
    state.finale_tiebreaker_enabled = True
    state._finale_playoff_rounds = 0

    winners = [MagicMock(name="w1"), MagicMock(name="w2")]
    winners[0].name = "Ada"
    winners[1].name = "Bo"
    state.compute_winners = MagicMock(return_value=(winners, 42))
    state._release_playoff_song = MagicMock(return_value=True)
    state.start_round = AsyncMock(return_value=start_succeeds)
    state.announce_finale_playoff = AsyncMock()
    return state


class TestFinalePlayoffVoice:
    async def test_speaks_once_the_round_has_started(self, monkeypatch):
        state = _tied_game(monkeypatch, start_succeeds=True)

        started = await state.maybe_start_finale_playoff()

        assert started is True
        state.announce_finale_playoff.assert_awaited_once_with(["Ada", "Bo"])

    async def test_stays_silent_when_the_round_never_starts(self, monkeypatch):
        """The whole point of waiting for the trigger to be trustworthy."""
        state = _tied_game(monkeypatch, start_succeeds=False)

        started = await state.maybe_start_finale_playoff()

        assert started is False
        assert state._finale_playoff_active is False
        state.announce_finale_playoff.assert_not_awaited()

    async def test_no_playoff_means_no_announcement(self, monkeypatch):
        """A single leader is not a tie — nothing to say."""
        state = _tied_game(monkeypatch, start_succeeds=True)
        only_one = [MagicMock()]
        only_one[0].name = "Ada"
        state.compute_winners = MagicMock(return_value=(only_one, 42))

        assert await state.maybe_start_finale_playoff() is False
        state.announce_finale_playoff.assert_not_awaited()


class TestFinalePlayoffPhrase:
    def test_every_language_has_the_line(self):
        for lang in tts_phrases.SUPPORTED_LANGUAGES:
            text = tts_phrases.phrase(lang, "finale_playoff", names="Ada und Bo")
            assert "Ada und Bo" in text, f"{lang} drops the names"
            assert text.strip(), f"{lang} is empty"

    def test_it_is_one_sentence_long(self):
        """It plays over a room that thinks the game is over — keep it short."""
        for lang in tts_phrases.SUPPORTED_LANGUAGES:
            text = tts_phrases.phrase(lang, "finale_playoff", names="Ada")
            assert len(text) <= 80, f"{lang} is {len(text)} chars: {text}"


class TestFinalePlayoffToggle:
    async def test_the_toggle_silences_it(self):
        state = make_game_state()
        state._tts_service = MagicMock()
        state._tts_announce = AsyncMock()
        state._tts_announce_finale_playoff = False

        await state.announce_finale_playoff(["Ada", "Bo"])

        state._tts_announce.assert_not_awaited()

    async def test_no_names_says_nothing(self):
        """A phrase built around names is not worth speaking without them."""
        state = make_game_state()
        state._tts_service = MagicMock()
        state._tts_announce = AsyncMock()
        state._tts_announce_finale_playoff = True

        await state.announce_finale_playoff([])

        state._tts_announce.assert_not_awaited()

    async def test_it_speaks_with_the_names_joined(self):
        state = make_game_state()
        state._tts_service = MagicMock()
        state._tts_announce = AsyncMock()
        state._tts_announce_finale_playoff = True

        await state.announce_finale_playoff(["Ada", "Bo"])

        state._tts_announce.assert_awaited_once()
        spoken = state._tts_announce.await_args.args[0]
        assert "Ada" in spoken and "Bo" in spoken
