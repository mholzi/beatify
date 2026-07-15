"""Sabotage power-up tests (Issue #1665).

Opt-in, default-off gameplay power-up. Each player is handed exactly one
sabotage token at game start; it is spent on an opponent who is still guessing.
The saboteur picks only the *target* — the *effect* is rolled server-side
(timer-cut / forced bet / freeze) so a tampered client cannot pick the mildest
one. Mirrors the steal token (see ``TestUseSteal`` in test_state.py) but for the
opposite side of a guess: steal needs a *submitted* target, sabotage needs an
*un-submitted* one.

Guarantees under test:
  * token is handed out at game start only when the setting is on,
  * ``use_sabotage`` consumes the token and records the target,
  * validations: no-token, self-target, wrong-phase, unknown saboteur,
    already-submitted target, double-sabotage, eliminated target,
  * each of the 3 effects, when rolled, lands the right per-victim state,
  * ``get_sabotage_targets`` filters self / submitted / eliminated / already-hit,
  * the setting plumbs through create_game → GameState → serializer,
  * per-round victim fields reset while the game-level token does not.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.beatify.const import (
    ERR_CANNOT_SABOTAGE_SELF,
    ERR_ELIMINATED,
    ERR_INVALID_ACTION,
    ERR_NO_SABOTAGE_AVAILABLE,
    ERR_NOT_IN_GAME,
    ERR_TARGET_ALREADY_SABOTAGED,
    ERR_TARGET_ALREADY_SUBMITTED,
    SABOTAGE_FORCED_BET,
    SABOTAGE_FREEZE,
    SABOTAGE_FREEZE_SECONDS,
    SABOTAGE_TIMER_CUT,
    SABOTAGE_TIMER_CUT_SECONDS,
)
from custom_components.beatify.game.serializers import GameStateSerializer
from custom_components.beatify.game.state import GamePhase

from tests.conftest import make_game_state, make_songs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_fresh_game(state, songs=None, **kwargs):
    songs = songs or make_songs(5)
    return state.create_game(
        playlists=["test.json"],
        songs=songs,
        media_player="media_player.test",
        base_url="http://localhost:8123",
        **kwargs,
    )


def _make_game(names, **create_kwargs):
    """Build a PLAYING game with the named players already joined."""
    state = make_game_state()
    _create_fresh_game(state, **create_kwargs)
    for name in names:
        ws = MagicMock()
        ws.closed = False
        state.add_player(name, ws)
    state.phase = GamePhase.PLAYING
    return state


def _roll(effect):
    """An ``effect_roll`` chooser that always returns ``effect`` (test injection)."""
    return lambda _effects: effect


# ---------------------------------------------------------------------------
# Token handout at game start
# ---------------------------------------------------------------------------


class TestTokenHandout:
    def test_token_handed_out_when_enabled(self):
        state = make_game_state()
        _create_fresh_game(state, sabotage_enabled=True)
        state.add_player("Alice", MagicMock())
        state.add_player("Bob", MagicMock())
        ok, err = state.start_game()
        assert ok is True and err is None
        assert state.get_player("Alice").sabotage_available is True
        assert state.get_player("Bob").sabotage_available is True

    def test_no_token_when_disabled(self):
        state = make_game_state()
        _create_fresh_game(state, sabotage_enabled=False)
        state.add_player("Alice", MagicMock())
        state.add_player("Bob", MagicMock())
        state.start_game()
        assert state.get_player("Alice").sabotage_available is False
        assert state.get_player("Bob").sabotage_available is False


# ---------------------------------------------------------------------------
# GameState.use_sabotage — validations + consumption
# ---------------------------------------------------------------------------


class TestUseSabotage:
    def setup_method(self):
        self.state = _make_game(["Alice", "Bob"])

    def test_no_sabotage_available(self):
        result = self.state.use_sabotage("Alice", "Bob")
        assert result["success"] is False
        assert result["error"] == ERR_NO_SABOTAGE_AVAILABLE

    def test_cannot_sabotage_self(self):
        self.state.get_player("Alice").sabotage_available = True
        result = self.state.use_sabotage("Alice", "Alice")
        assert result["success"] is False
        assert result["error"] == ERR_CANNOT_SABOTAGE_SELF

    def test_wrong_phase(self):
        self.state.phase = GamePhase.REVEAL
        self.state.get_player("Alice").sabotage_available = True
        result = self.state.use_sabotage("Alice", "Bob")
        assert result["success"] is False
        assert result["error"] == ERR_INVALID_ACTION

    def test_unknown_saboteur(self):
        result = self.state.use_sabotage("Ghost", "Bob")
        assert result["success"] is False
        assert result["error"] == ERR_NOT_IN_GAME

    def test_target_already_submitted(self):
        self.state.get_player("Alice").sabotage_available = True
        self.state.get_player("Bob").submitted = True
        result = self.state.use_sabotage("Alice", "Bob")
        assert result["success"] is False
        assert result["error"] == ERR_TARGET_ALREADY_SUBMITTED

    def test_target_eliminated(self):
        self.state.get_player("Alice").sabotage_available = True
        self.state.get_player("Bob").eliminated = True
        result = self.state.use_sabotage("Alice", "Bob")
        assert result["success"] is False
        assert result["error"] == ERR_ELIMINATED

    def test_target_already_sabotaged(self):
        self.state.get_player("Alice").sabotage_available = True
        self.state.get_player("Bob").sabotaged_by = "Someone"
        result = self.state.use_sabotage("Alice", "Bob")
        assert result["success"] is False
        assert result["error"] == ERR_TARGET_ALREADY_SABOTAGED

    def test_token_consumed_on_success(self):
        self.state.get_player("Alice").sabotage_available = True
        result = self.state.use_sabotage("Alice", "Bob")
        assert result["success"] is True
        assert result["target"] == "Bob"
        assert result["effect"] in (
            SABOTAGE_TIMER_CUT,
            SABOTAGE_FORCED_BET,
            SABOTAGE_FREEZE,
        )
        alice = self.state.get_player("Alice")
        assert alice.sabotage_available is False
        assert alice.sabotage_used is True
        assert alice.sabotaged == "Bob"
        assert self.state.get_player("Bob").sabotaged_by == "Alice"


# ---------------------------------------------------------------------------
# Effect rolling — inject effect_roll to land each one deterministically
# ---------------------------------------------------------------------------


class TestSabotageEffects:
    def setup_method(self):
        self.state = _make_game(["Alice", "Bob"])
        self.state.get_player("Alice").sabotage_available = True
        self.pm = self.state._powerup_manager

    def _use(self, effect):
        return self.pm.use_sabotage(
            "Alice",
            "Bob",
            self.state.players,
            self.state.phase,
            self.state._now(),
            effect_roll=_roll(effect),
        )

    def test_timer_cut_applies_deadline_cut(self):
        result = self._use(SABOTAGE_TIMER_CUT)
        assert result["success"] is True
        assert result["effect"] == SABOTAGE_TIMER_CUT
        bob = self.state.get_player("Bob")
        assert bob.sabotage_effect == SABOTAGE_TIMER_CUT
        assert bob.sabotage_deadline_cut_ms == SABOTAGE_TIMER_CUT_SECONDS * 1000
        assert bob.sabotage_freeze_until is None
        assert bob.sabotage_forced_bet is False

    def test_forced_bet_sets_flag(self):
        result = self._use(SABOTAGE_FORCED_BET)
        assert result["effect"] == SABOTAGE_FORCED_BET
        bob = self.state.get_player("Bob")
        assert bob.sabotage_effect == SABOTAGE_FORCED_BET
        assert bob.sabotage_forced_bet is True
        assert bob.sabotage_deadline_cut_ms == 0
        assert bob.sabotage_freeze_until is None

    def test_freeze_sets_deadline(self):
        now = self.state._now()
        result = self.pm.use_sabotage(
            "Alice",
            "Bob",
            self.state.players,
            self.state.phase,
            now,
            effect_roll=_roll(SABOTAGE_FREEZE),
        )
        assert result["effect"] == SABOTAGE_FREEZE
        bob = self.state.get_player("Bob")
        assert bob.sabotage_effect == SABOTAGE_FREEZE
        assert bob.sabotage_freeze_until == now + SABOTAGE_FREEZE_SECONDS
        assert bob.sabotage_deadline_cut_ms == 0
        assert bob.sabotage_forced_bet is False


# ---------------------------------------------------------------------------
# get_sabotage_targets — filtering
# ---------------------------------------------------------------------------


class TestGetSabotageTargets:
    def setup_method(self):
        self.state = _make_game(["Alice", "Bob", "Carol", "Dave"])
        self.state.get_player("Alice").sabotage_available = True

    def test_excludes_self(self):
        targets = self.state.get_sabotage_targets("Alice")
        assert "Alice" not in targets

    def test_excludes_submitted(self):
        self.state.get_player("Bob").submitted = True
        targets = self.state.get_sabotage_targets("Alice")
        assert "Bob" not in targets
        assert "Carol" in targets and "Dave" in targets

    def test_excludes_eliminated(self):
        self.state.get_player("Carol").eliminated = True
        targets = self.state.get_sabotage_targets("Alice")
        assert "Carol" not in targets

    def test_excludes_already_sabotaged(self):
        self.state.get_player("Dave").sabotaged_by = "Bob"
        targets = self.state.get_sabotage_targets("Alice")
        assert "Dave" not in targets

    def test_lists_valid_opponents(self):
        targets = self.state.get_sabotage_targets("Alice")
        assert set(targets) == {"Bob", "Carol", "Dave"}


# ---------------------------------------------------------------------------
# Config plumbing + serializer
# ---------------------------------------------------------------------------


class TestConfigPlumbing:
    def test_create_game_sets_flag(self):
        state = make_game_state()
        _create_fresh_game(state, sabotage_enabled=True)
        assert state.sabotage_enabled is True

    def test_default_is_off(self):
        state = make_game_state()
        _create_fresh_game(state)
        assert state.sabotage_enabled is False

    def test_serializer_exposes_flag(self):
        state = _make_game(["Alice", "Bob"], sabotage_enabled=True)
        serialized = GameStateSerializer.serialize(state)
        assert serialized["sabotage_enabled"] is True


# ---------------------------------------------------------------------------
# Per-round reset semantics
# ---------------------------------------------------------------------------


class TestResetSemantics:
    def test_reset_for_new_round_clears_victim_state_not_token(self):
        state = _make_game(["Alice", "Bob"])
        bob = state.get_player("Bob")
        bob.sabotage_available = True
        bob.sabotaged_by = "Alice"
        bob.sabotage_effect = SABOTAGE_TIMER_CUT
        bob.sabotage_deadline_cut_ms = 5000
        bob.sabotage_forced_bet = True
        bob.reset_round()
        # Per-round victim state cleared...
        assert bob.sabotaged_by is None
        assert bob.sabotage_effect is None
        assert bob.sabotage_deadline_cut_ms == 0
        assert bob.sabotage_forced_bet is False
        # ...but the game-level token is untouched.
        assert bob.sabotage_available is True

    def test_reset_for_new_game_clears_token(self):
        state = _make_game(["Alice", "Bob"])
        alice = state.get_player("Alice")
        alice.sabotage_available = True
        alice.sabotage_used = True
        alice.reset_for_new_game()
        assert alice.sabotage_available is False
        assert alice.sabotage_used is False
