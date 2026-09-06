"""#2626 — the auto-advance delays a host can pick, and what happens to the rest.

`server/game_views.py` rejected anything outside a literal ``(0, 30, 60, 90)``
and replaced it with 0. The UI kept two more lists of its own — the wizard's
``AUTO_ADVANCE_OPTIONS`` and four hand-written chips in ``admin.html`` — with
nothing tying the three together. A chip added to either UI list looked selected
while the game ran with auto-advance off, and the host found out at the first
reveal, with no error message anywhere.

The list now lives in ``const.py`` and is the only one: the handler validates
against it, and both chip groups are rendered from the JS mirror
(``www/js/game-constants.js``, guarded by ``game-constants-mirror.test.js``).

These tests pin the server half — what the game will actually run for a given
payload — and the rejection log that used to be silent.
"""

from __future__ import annotations

import logging

import pytest

from custom_components.beatify.const import REVEAL_AUTO_ADVANCE_OPTIONS
from custom_components.beatify.server.game_views import normalize_reveal_auto_advance


def test_every_offered_delay_survives_untouched() -> None:
    """The whole point: a delay the UI offers is the delay the game runs."""
    for seconds in REVEAL_AUTO_ADVANCE_OPTIONS:
        assert normalize_reveal_auto_advance(seconds) == seconds


def test_the_json_string_form_survives_too() -> None:
    """The value arrives from JSON, where a client may send it as a string."""
    for seconds in REVEAL_AUTO_ADVANCE_OPTIONS:
        assert normalize_reveal_auto_advance(str(seconds)) == seconds


def test_off_is_one_of_the_choices() -> None:
    """0 is a real setting (manual / song-end advance), not just the fallback."""
    assert 0 in REVEAL_AUTO_ADVANCE_OPTIONS


@pytest.mark.parametrize("value", [15, 120, 45, -30, 1, 10_000])
def test_a_delay_nobody_supports_becomes_off(value: int) -> None:
    assert value not in REVEAL_AUTO_ADVANCE_OPTIONS  # guard the fixture itself
    assert normalize_reveal_auto_advance(value) == 0


@pytest.mark.parametrize("value", [None, "", "soon", "30s", [], {}, 45.5])
def test_a_malformed_value_becomes_off_rather_than_failing_the_start(value) -> None:
    """A bad payload must not stop a party from starting."""
    assert normalize_reveal_auto_advance(value) == 0


def test_a_rejected_delay_leaves_a_trace(caplog: pytest.LogCaptureFixture) -> None:
    """The silence was half the bug — the host had nothing to look at.

    WARNING rather than INFO on purpose: Home Assistant's ``system_log``, the
    list behind Settings > System > Logs, only collects WARNING and above.
    """
    with caplog.at_level(logging.WARNING):
        assert normalize_reveal_auto_advance(120) == 0
    assert any(
        record.levelno == logging.WARNING and "120" in record.getMessage()
        for record in caplog.records
    ), caplog.text


def test_choosing_off_is_not_reported_as_a_rejection(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """0 is the default for every game; logging it would bury the real ones."""
    with caplog.at_level(logging.WARNING):
        assert normalize_reveal_auto_advance(0) == 0
        assert normalize_reveal_auto_advance(None) == 0
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING], caplog.text
