"""#2721 — the Comeback Token stops being handed out silently.

The grant itself (#1724) already worked: after the halfway round the trailing
third gets a steal. What was missing was any trace of *why*. The server sent
``comeback_token_granted`` per player and no client read it, so on the phone the
gifted steal looked exactly like a streak unlock, and the announcer said
"{name} unlocked steal" about a player who had just got nothing right. To the
room that reads as a broken streak counter, not as a catch-up mechanic.

Three things are guarded here, and each one fails differently:

1. **The grant is published as a one-round event.** Without
   ``comeback_granted_this_round`` neither screen can build a halftime moment.

2. **It does not linger.** The field is only recomputed at the *end* of a round,
   so a naive implementation leaves the halfway names in place for the whole
   second half — and the takeover replays in rounds 6, 7, 8 and so on. This is
   the regression most likely to be introduced by a later refactor, because
   nothing about the field's name says "one round only".

3. **The announcement is one group sentence, not N streak lines.** The old
   per-player loop is exactly the wrong sentence for these players, and the
   dedup set has to swallow their names so it never fires for them later.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.beatify.game import tts_phrases
from custom_components.beatify.game.player import PlayerSession
from custom_components.beatify.game.state import GameState
from tests.conftest import make_game_state

LANGUAGES = ["en", "de", "es", "fr", "it", "nl"]


def _game(names: list[str], *, total_rounds: int = 10) -> GameState:
    """A started game with `names` joined, Comeback Token on."""
    gs = make_game_state()
    gs.game_id = "test"
    gs.total_rounds = total_rounds
    gs.comeback_token_enabled = True
    gs.players = {name: _player(name) for name in names}
    return gs


def _player(name: str, **fields) -> PlayerSession:
    player = PlayerSession(name=name, ws=None)
    for key, value in fields.items():
        setattr(player, key, value)
    return player


def _score(gs: GameState, points: dict[str, int]) -> None:
    for name, value in points.items():
        gs.players[name].score = value


class TestGrantIsPublished:
    """The event has to reach the payload, or no screen can say anything."""

    def test_halfway_round_records_the_names(self):
        gs = _game(["Ben", "Chris", "Dana", "Anna"])
        _score(gs, {"Ben": 412, "Chris": 388, "Dana": 201, "Anna": 96})
        gs.round = gs._halfway_round(gs.total_rounds)

        granted = gs._maybe_grant_comeback_tokens()

        # floor(4 / 3) == 1 → the single lowest-ranked active player.
        assert granted == ["Anna"]
        assert gs.comeback_granted_this_round == ["Anna"]

    def test_the_recorded_list_is_a_copy_not_the_return_value(self):
        # A shared list would let a caller mutate the broadcast payload.
        gs = _game(["Ben", "Chris", "Dana", "Anna"])
        _score(gs, {"Ben": 412, "Chris": 388, "Dana": 201, "Anna": 96})
        gs.round = gs._halfway_round(gs.total_rounds)

        granted = gs._maybe_grant_comeback_tokens()
        granted.append("Mallory")

        assert gs.comeback_granted_this_round == ["Anna"]

    def test_starts_empty(self):
        assert _game(["Ben"]).comeback_granted_this_round == []


class TestItDoesNotLinger:
    """The takeover is a beat. A field that survives replays it every round."""

    def test_cleared_on_the_round_after_the_grant(self):
        gs = _game(["Ben", "Chris", "Dana", "Anna"])
        _score(gs, {"Ben": 412, "Chris": 388, "Dana": 201, "Anna": 96})
        gs.round = gs._halfway_round(gs.total_rounds)
        gs._maybe_grant_comeback_tokens()
        assert gs.comeback_granted_this_round == ["Anna"]

        # Round 6 ends. Nothing is granted — and nothing may be left over.
        gs.round += 1
        gs._maybe_grant_comeback_tokens()

        assert gs.comeback_granted_this_round == []

    def test_cleared_even_when_the_feature_is_off(self):
        # The early return for a disabled feature is the easiest one to forget.
        gs = _game(["Ben", "Chris", "Dana", "Anna"])
        gs.comeback_granted_this_round = ["Anna"]
        gs.comeback_token_enabled = False

        gs._maybe_grant_comeback_tokens()

        assert gs.comeback_granted_this_round == []

    def test_cleared_when_the_field_is_too_small_for_a_bottom_third(self):
        gs = _game(["Ben", "Chris"])
        gs.comeback_granted_this_round = ["Anna"]
        gs.round = gs._halfway_round(gs.total_rounds)

        gs._maybe_grant_comeback_tokens()

        # floor(2 / 3) == 0 → nobody is granted anything.
        assert gs.comeback_granted_this_round == []


class TestSerialisation:
    """REVEAL only — the field outlives the reveal it belongs to."""

    def test_reveal_payload_carries_the_names(self):
        from custom_components.beatify.game.serializers import GameStateSerializer

        gs = _game(["Ben", "Chris", "Dana", "Anna"])
        _score(gs, {"Ben": 412, "Chris": 388, "Dana": 201, "Anna": 96})
        gs.round = gs._halfway_round(gs.total_rounds)
        gs._maybe_grant_comeback_tokens()

        state: dict = {}
        GameStateSerializer._add_reveal_state(gs, state)

        assert state["comeback_granted_this_round"] == ["Anna"]

    def test_reveal_payload_omits_it_when_nothing_was_granted(self):
        from custom_components.beatify.game.serializers import GameStateSerializer

        gs = _game(["Ben", "Chris", "Dana", "Anna"])
        state: dict = {}
        GameStateSerializer._add_reveal_state(gs, state)

        assert "comeback_granted_this_round" not in state

    def test_players_are_allowed_to_see_it(self):
        # The whole point is that the *room* hears a reason. A field filtered
        # out of the player payload would leave the phones as silent as before.
        from custom_components.beatify.server.serializers import (
            _PLAYER_VISIBLE_REVEAL,
        )

        assert "comeback_granted_this_round" in _PLAYER_VISIBLE_REVEAL


class TestAnnouncement:
    """One halftime sentence, not N streak lines."""

    @pytest.mark.parametrize("lang", LANGUAGES)
    def test_every_language_has_the_phrase(self, lang):
        rendered = tts_phrases.phrase(lang, "comeback_tokens", names="Anna and Dana")
        assert "Anna and Dana" in rendered
        assert "{names}" not in rendered

    @pytest.mark.parametrize("lang", [c for c in LANGUAGES if c != "en"])
    def test_it_was_actually_translated(self, lang):
        # A copied English fallback would announce the reason in the wrong
        # language to five rooms out of six.
        assert tts_phrases.phrase(lang, "comeback_tokens", names="X") != (
            tts_phrases.phrase("en", "comeback_tokens", names="X")
        )

    @pytest.mark.asyncio
    async def test_recipients_get_the_halftime_line_not_a_streak_line(self):
        """The sentence that #2721 is about.

        Before this change the room heard "Anna unlocked steal" about the
        player in last place. The assertion that matters is the negative one.
        """
        state = make_game_state()
        state._tts_service = MagicMock()  # truthy → announcements run
        state._tts_announce = AsyncMock()
        state.players = {
            "Ben": _player("Ben", submitted=True, years_off=0, score=412),
            "Anna": _player("Anna", submitted=True, years_off=9, score=96),
        }
        # Anna holds a steal, and it came from the halftime grant.
        state.players["Anna"].steal_available = True
        state.comeback_granted_this_round = ["Anna"]

        await state._announce_reveal(1987)

        spoken = state._tts_announce.await_args.args[0]
        assert "unlocked steal" not in spoken
        assert "Halfway" in spoken and "Anna" in spoken
        # And the dedup set swallowed her, so the per-player line can never
        # fire for her in a later round either.
        assert "Anna" in state._tts_steal_unlocked_announced

    @pytest.mark.asyncio
    async def test_a_streak_unlock_still_gets_its_own_line(self):
        """The group sentence must not swallow the ordinary case."""
        state = make_game_state()
        state._tts_service = MagicMock()
        state._tts_announce = AsyncMock()
        state.players = {
            "Ben": _player("Ben", submitted=True, years_off=0, score=412),
        }
        state.players["Ben"].steal_available = True
        state.comeback_granted_this_round = []

        await state._announce_reveal(1987)

        assert "unlocked steal" in state._tts_announce.await_args.args[0]
