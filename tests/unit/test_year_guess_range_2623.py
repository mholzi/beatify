"""The guess validator must accept the range the slider offered (#2623).

#2337 widened the slider so it always covers the playlist: a song from 1937
gets a slider that reaches 1937. The validator in ``handle_submit`` was not
part of that change and kept comparing against ``YEAR_MIN``/``YEAR_MAX``
(1950/2026). Ten bundled playlists hold **27 songs dated 1937-1949**, so for
those rounds a player could set the correct year, submit it, and get
``ERR_INVALID_ACTION "Invalid year"`` back — the guess simply vanished.

The same split bites at the top end on a calendar boundary: the slider maximum
follows the clock, ``YEAR_MAX`` is a literal, so from January 2027 the current
year would be offered and rejected.

The fix is not a wider constant. Both sides now ask the same function, so the
two answers cannot drift apart again — which is the actual defect. A wider
constant would have fixed today's 27 songs and left the next widening to
rediscover the bug.

#2701: the handler used to be covered by reading ``guessing.py`` and asserting
``"year_range(game_state)" in src`` with ``"YEAR_MIN" not in src``. That was
red on renaming a local to ``gs`` and green on a validator that returned a
hardcoded 1950. ``handle_submit`` is driven for real below — a pre-1950 guess
goes in and has to come back as ``submit_ack``.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.beatify.const import (
    DOMAIN,
    ERR_INVALID_ACTION,
    YEAR_MAX,
    YEAR_MIN,
)
from custom_components.beatify.game.serializers import (
    GameStateSerializer,
    year_range,
)
from custom_components.beatify.game.state import GamePhase
from custom_components.beatify.server.ws_handlers.guessing import handle_submit
from tests.conftest import make_game_state

from custom_components.beatify.server.websocket import (  # isort: skip
    BeatifyWebSocketHandler,
)


class _FakeManager:
    def __init__(self, span):
        self._span = span

    def get_year_span(self):
        return self._span


class _FakeState:
    def __init__(self, span=None):
        self._playlist_manager = _FakeManager(span) if span else None


def _this_year() -> int:
    return datetime.now(timezone.utc).year


class TestOneSourceForBothSides:
    def test_serializer_delegates_to_the_shared_function(self):
        """The slider bounds and the validator bounds are the same object."""
        gs = _FakeState((1937, 2001))
        assert GameStateSerializer._year_range(gs) == year_range(gs)

    def test_a_pre_1950_playlist_widens_the_accepted_range(self):
        """The 1937-1949 songs are inside the range, not below it."""
        rng = year_range(_FakeState((1937, 2001)))
        assert rng["min"] == 1937
        assert rng["min"] < YEAR_MIN, "otherwise this test proves nothing"

    def test_the_upper_bound_follows_the_clock_not_the_constant(self):
        """From January 2027 a literal 2026 ceiling would reject the year."""
        rng = year_range(_FakeState(None))
        assert rng["max"] == _this_year()
        assert rng["max"] >= YEAR_MAX


# ---------------------------------------------------------------------------
# The validator itself, driven through the websocket handler.
# ---------------------------------------------------------------------------


def _songs(*years: int) -> list[dict]:
    return [
        {
            "year": year,
            "title": f"Song {year}",
            "artist": f"Artist {year}",
            "uri": f"spotify:track:{i:022d}",
            "_resolved_uri": f"spotify:track:{i:022d}",
        }
        for i, year in enumerate(years)
    ]


def _stub_media_service() -> MagicMock:
    svc = MagicMock()
    svc.is_available.return_value = True
    svc.play_song = AsyncMock(return_value=True)
    svc.verify_responsive = AsyncMock(return_value=(True, None))
    return svc


def _ws() -> AsyncMock:
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    ws.closed = False
    ws.close = AsyncMock()
    return ws


async def _playing_game(*years: int):
    """A game in PLAYING phase, its playlist spanning ``years``."""
    hass = MagicMock()
    gs = make_game_state()
    gs.create_game(
        playlists=["t.json"],
        songs=_songs(*years),
        media_player="media_player.x",
        base_url="http://h",
    )
    gs._media_player_service = _stub_media_service()
    gs.platform = "music_assistant"
    hass.data = {DOMAIN: {"game": gs}}

    handler = BeatifyWebSocketHandler(hass)
    handler.broadcast_state = AsyncMock()
    handler.broadcast = AsyncMock()
    handler.debounced_broadcast_state = AsyncMock()

    ws = _ws()
    gs.add_player("Alice", ws)
    gs.get_player("Alice").connected = True
    await gs.start_round()
    assert gs.phase == GamePhase.PLAYING
    return handler, gs, ws


def _replies(ws: AsyncMock) -> list[dict]:
    return [c.args[0] for c in ws.send_json.call_args_list if c.args]


async def _submit(year, *, span_years):
    """Submit ``year`` into a game whose playlist spans ``span_years``."""
    handler, gs, ws = await _playing_game(*span_years)
    await handle_submit(handler, ws, {"year": year}, gs)
    return gs, ws, _replies(ws)


class TestValidatorAcceptsWhatTheSliderOffers:
    """The handler and the slider answer to the same bounds."""

    async def test_the_slider_and_the_handler_agree_on_this_playlist(self):
        # The premise: the slider really does reach below YEAR_MIN here.
        _, gs, _ = await _playing_game(1937, 2001)
        assert year_range(gs)["min"] == 1937 < YEAR_MIN

    @pytest.mark.parametrize("year", [1937, 1945, 1949])
    async def test_a_pre_1950_guess_is_banked_not_rejected(self, year):
        # #2623 in one call: 27 catalogue songs sit in this window, and every
        # correct answer for them used to come back as "Invalid year".
        gs, ws, replies = await _submit(year, span_years=(1937, 2001))
        assert [r["type"] for r in replies] == ["submit_ack"]
        assert replies[0]["year"] == year
        assert gs.get_player("Alice").current_guess == year

    async def test_the_current_year_is_accepted_whatever_the_constant_says(self):
        # The January failure mode: the slider maximum follows the clock, so a
        # literal ceiling starts rejecting the current year at some new year.
        gs, ws, replies = await _submit(_this_year(), span_years=(1990, 2001))
        assert [r["type"] for r in replies] == ["submit_ack"]
        assert gs.get_player("Alice").current_guess == _this_year()

    @pytest.mark.parametrize("year", [1900, 1936])
    async def test_a_year_below_the_slider_is_still_rejected(self, year):
        # Widening is not the same as accepting anything: the range still has a
        # floor, it is just the playlist's floor rather than a constant.
        gs, ws, replies = await _submit(year, span_years=(1937, 2001))
        assert replies[0]["code"] == ERR_INVALID_ACTION
        assert gs.get_player("Alice").current_guess is None

    async def test_a_year_beyond_the_clock_is_still_rejected(self):
        gs, ws, replies = await _submit(_this_year() + 1, span_years=(1990, 2001))
        assert replies[0]["code"] == ERR_INVALID_ACTION
        assert gs.get_player("Alice").current_guess is None

    @pytest.mark.parametrize("year", ["1970", None, 1970.5])
    async def test_a_non_integer_year_is_rejected(self, year):
        gs, ws, replies = await _submit(year, span_years=(1937, 2001))
        assert replies[0]["code"] == ERR_INVALID_ACTION
        assert gs.get_player("Alice").current_guess is None

    async def test_the_bounds_the_player_was_shown_are_the_bounds_applied(self):
        """The two sides are checked against each other, not against literals.

        This is the shape of the defect rather than one instance of it: whatever
        the slider offers, the extremes of that offer must be accepted. A
        validator that hardcoded any bound fails here on some playlist.
        """
        handler, gs, ws = await _playing_game(1937, 2001)
        offered = json.loads(json.dumps(year_range(gs)))  # the payload's copy

        for year in (offered["min"], offered["max"]):
            player_ws = _ws()
            gs.add_player(f"P{year}", player_ws)
            gs.get_player(f"P{year}").connected = True
            await handle_submit(handler, player_ws, {"year": year}, gs)
            assert [r["type"] for r in _replies(player_ws)] == ["submit_ack"], (
                f"the slider offered {year} and the handler refused it"
            )
