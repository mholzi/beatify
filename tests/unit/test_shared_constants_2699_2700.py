"""#2699 / #2700 — two numbers the server owns, no longer copied into JS.

Both issues are the same defect twice: a value defined by the server, restated
somewhere in ``www/js/``, with nothing holding the two together. Changing the
server's copy silently desynchronised the phone.

* **#2699** ``SUDDEN_DEATH_MIN_PLAYERS`` lived in four places and in none of them
  authoritatively — the wizard card, the ``connected_count < 3`` backstop, the
  warning beside it, and the digit spelled out in six locale files. Raising it
  left the host a card enabled for a game the server then started *without*
  Sudden Death, with no error on any surface.
* **#2700** the server already computed a sabotage-freeze countdown and put it in
  every player-state broadcast, and no client read it. The phone worked from
  ``var SABOTAGE_FREEZE_MS = 3000`` instead, so tuning
  ``SABOTAGE_FREEZE_SECONDS`` unlocked the submit button while the server was
  still answering ERR_FROZEN.

The JS halves are guarded in ``www/js/__tests__/`` (``game-constants-mirror``,
``sudden-death-min-players-2699``, ``sabotage-freeze-payload-2700``). This file
guards the Python halves: the rendered warning, the countdown's rounding, and
the field on the private hit.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.beatify.const import (
    DOMAIN,
    SABOTAGE_FREEZE,
    SABOTAGE_FREEZE_SECONDS,
    SUDDEN_DEATH_MIN_PLAYERS,
)
from custom_components.beatify.game.state import GamePhase
from custom_components.beatify.server.game_views import StartGameplayView

from tests.conftest import make_game_state, make_songs

BEATIFY = Path(__file__).resolve().parents[2] / "custom_components" / "beatify"


def _create_fresh_game(state, **kwargs):
    return state.create_game(
        playlists=["test.json"],
        songs=make_songs(5),
        media_player="media_player.test",
        base_url="http://localhost:8123",
        **kwargs,
    )


def _add_live_player(state, name: str) -> None:
    ws = AsyncMock()
    ws.closed = False
    state.add_player(name, ws)
    state.get_player(name).connected = True


def _hass(state) -> MagicMock:
    hass = MagicMock()
    hass.data = {DOMAIN: {"game": state}}  # no ws_handler
    return hass


# ---------------------------------------------------------------------------
# #2699 — the Sudden Death floor
# ---------------------------------------------------------------------------


class TestSuddenDeathFloorIsTheConstant:
    """The start-gameplay backstop and its warning both read const.py."""

    @patch(
        "custom_components.beatify.server.game_views.is_authorized_http",
        return_value=True,
    )
    async def test_warning_names_the_constant_and_no_other_number(self, _auth):
        """One short of the floor: the mode drops and the host is told why.

        The assertion that earns its keep is the negative one — the warning may
        contain the const.py number and no other digit. A sentence that kept
        saying "at least 3" after the floor moved would fail here instead of on
        the host's screen, which is exactly what #2699 reported.
        """
        state = make_game_state()
        _create_fresh_game(state, sudden_death_mode=True)
        for i in range(SUDDEN_DEATH_MIN_PLAYERS - 1):
            _add_live_player(state, f"P{i}")
        state.start_round = AsyncMock(return_value=True)

        view = StartGameplayView(_hass(state))
        resp = await view.post(MagicMock())
        body = json.loads(resp.body)

        assert resp.status == 200
        assert state.sudden_death_mode is False
        assert body["sudden_death_disabled"] is True

        (warning,) = body["warnings"]
        assert str(SUDDEN_DEATH_MIN_PLAYERS) in warning
        leftover = warning.replace(str(SUDDEN_DEATH_MIN_PLAYERS), "")
        assert not re.search(r"\d", leftover), (
            f"warning carries a second number: {warning!r}"
        )

    @patch(
        "custom_components.beatify.server.game_views.is_authorized_http",
        return_value=True,
    )
    async def test_at_the_floor_the_mode_survives(self, _auth):
        """Exactly at the floor, Sudden Death starts and nothing is warned."""
        state = make_game_state()
        _create_fresh_game(state, sudden_death_mode=True)
        for i in range(SUDDEN_DEATH_MIN_PLAYERS):
            _add_live_player(state, f"P{i}")
        state.start_round = AsyncMock(return_value=True)

        view = StartGameplayView(_hass(state))
        resp = await view.post(MagicMock())
        body = json.loads(resp.body)

        assert resp.status == 200
        assert state.sudden_death_mode is True
        assert "sudden_death_disabled" not in body
        assert "warnings" not in body


class TestSuddenDeathFloorHasOneHome:
    """No surface may restate the floor as a literal."""

    def test_game_views_uses_the_constant(self):
        src = (BEATIFY / "server" / "game_views.py").read_text(encoding="utf-8")
        assert "connected_count < SUDDEN_DEATH_MIN_PLAYERS" in src
        assert not re.search(r"connected_count < \d", src)

    def test_locales_carry_a_placeholder_not_a_digit(self):
        """All six locales phrase the floor as ``{min}``.

        The JS side proves the substitution actually happens (see
        ``sudden-death-min-players-2699.test.js``); this keeps a translator's
        well-meant "3" from creeping back into a file the JS tests would then
        fail on.
        """
        keys = ("suddenDeathDisabledTooltip", "suddenDeathDisabledGate")
        for locale in ("en", "de", "es", "fr", "it", "nl"):
            payload = json.loads(
                (BEATIFY / "www" / "i18n" / f"{locale}.json").read_text(
                    encoding="utf-8"
                )
            )
            for key in keys:
                value = payload["admin"][key]
                assert "{min}" in value, f"{locale}.{key} lost its placeholder"
                assert not re.search(r"\d", value.replace("{min}", "")), (
                    f"{locale}.{key} spells out a number: {value!r}"
                )


# ---------------------------------------------------------------------------
# #2700 — the sabotage freeze countdown
# ---------------------------------------------------------------------------


class TestSabotageFreezeRemaining:
    """The countdown the phone now works from."""

    def setup_method(self):
        self.state = make_game_state()
        _create_fresh_game(self.state, sabotage_enabled=True)
        for name in ("Alice", "Bob"):
            ws = MagicMock()
            ws.closed = False
            self.state.add_player(name, ws)
        self.state.phase = GamePhase.PLAYING

    def _freeze(self, bob, seconds_ago: float = 0.0) -> None:
        bob.sabotage_effect = SABOTAGE_FREEZE
        bob.sabotage_freeze_until = (
            self.state._now() + SABOTAGE_FREEZE_SECONDS - seconds_ago
        )

    def _bob_state(self) -> dict:
        return next(p for p in self.state.get_players_state() if p["name"] == "Bob")

    def test_fresh_freeze_broadcasts_the_full_duration(self):
        self._freeze(self.state.get_player("Bob"))
        assert self._bob_state()["sabotage_freeze_remaining"] == (
            SABOTAGE_FREEZE_SECONDS
        )

    def test_no_freeze_broadcasts_zero(self):
        assert self._bob_state()["sabotage_freeze_remaining"] == 0

    def test_a_lapsed_freeze_broadcasts_zero(self):
        self._freeze(self.state.get_player("Bob"), seconds_ago=99)
        assert self._bob_state()["sabotage_freeze_remaining"] == 0

    def test_a_part_second_remainder_rounds_up(self):
        """0.4s left must broadcast as 1, never 0.

        Enforcement in ``ws_handlers/guessing.py`` is a strict
        ``now < freeze_until``, so rounding to nearest would hand the phone a 0
        while the server still rejects — the button looks live and answers
        ERR_FROZEN. Late by under a second is harmless; early is #2700.
        """
        bob = self.state.get_player("Bob")
        bob.sabotage_freeze_until = self.state._now() + 0.4
        assert self._bob_state()["sabotage_freeze_remaining"] == 1


class TestSabotageFreezeHasOneHome:
    """The duration reaches the client, and the client keeps no copy."""

    def test_the_private_hit_carries_the_countdown(self):
        src = (BEATIFY / "server" / "ws_handlers" / "guessing.py").read_text(
            encoding="utf-8"
        )
        assert '"freeze_remaining": game_state.sabotage_freeze_remaining(target)' in src

    def test_player_game_js_has_no_mirrored_duration(self):
        src = (BEATIFY / "www" / "js" / "player-game.js").read_text(encoding="utf-8")
        # The name may appear in the comment explaining why it is gone; what
        # must not come back is an assignment.
        assert not re.search(r"SABOTAGE_FREEZE_MS\s*=", src)
        assert "sabotage_freeze_remaining" in src
