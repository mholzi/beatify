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
"""

from __future__ import annotations

from datetime import datetime, timezone

from custom_components.beatify.const import YEAR_MAX, YEAR_MIN
from custom_components.beatify.game.serializers import (
    GameStateSerializer,
    year_range,
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


class TestValidatorUsesIt:
    def test_handler_no_longer_reads_the_constants(self):
        """A source guard: the drift came from two literals, so neither may
        return to the submit path.

        Asserting on behaviour would need the full websocket handler with a
        game, a player and a live round; the defect, however, is entirely in
        *which bounds the check reads*. That is what this pins.
        """
        from pathlib import Path

        src = Path(
            "custom_components/beatify/server/ws_handlers/guessing.py"
        ).read_text(encoding="utf-8")
        assert "year_range(game_state)" in src
        assert "YEAR_MIN" not in src
        assert "YEAR_MAX" not in src
