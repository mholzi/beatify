"""The wizard could rewrite the setup while the lobby kept the old one (#2769).

Found by a targeted live UI test of the v4.5.0-rc1 items on the real
installation on 2026-09-08. A lobby game exists — the normal state of
``/beatify/admin``, which creates one from ``saved_setup``. The host taps
**Back / Edit setup**, switches the play style from Chaos to Classic, raises the
rounds from 10 to 20, finishes the wizard and taps **Go to lobby**.

``saved_setup`` was rewritten correctly. The game was not touched at all: same
``game_id``, same flags, same round count. The host then started a game running
the settings they had just replaced — with Sabotage still on after choosing a
style whose card says "Not for the in-laws", and nothing on the home screen to
contradict them (the meta line shows speaker, playlist count, difficulty, round
duration and language — neither the style nor the round count).

Two pieces are tested here:

* ``GameOptions.patched`` — overlay by name, so the second view does not repeat
  the create view's seventeen-field parse. That duplication is exactly what
  #2635 removed and exactly how an option goes missing without an error.
* ``apply_lobby_options`` — LOBBY only, and it re-derives ``total_rounds``,
  because the round cap and ramp-up ordering only take effect through a rebuilt
  playlist manager.
"""

from __future__ import annotations

from typing import Any

import pytest

from custom_components.beatify.const import DIFFICULTY_HARD
from custom_components.beatify.game.config import GameOptions
from custom_components.beatify.game.state import GamePhase, GameState

from tests.conftest import make_game_state


def _songs(n: int = 20) -> list[dict[str, Any]]:
    return [
        {
            "year": 1980 + i,
            "title": f"Song {i}",
            "artist": f"Artist {i}",
            "uri": f"spotify:track:test{i:022d}",
            "uri_spotify": f"spotify:track:test{i:022d}",
        }
        for i in range(n)
    ]


@pytest.fixture
def lobby() -> GameState:
    """A game in LOBBY, created the way the admin page creates one."""
    state = make_game_state()
    state.create_game(
        playlists=["test.json"],
        songs=_songs(),
        media_player="media_player.party",
        base_url="http://localhost:8123",
        options=GameOptions(
            sabotage_enabled=True,
            comeback_token_enabled=True,
            rampup_order_enabled=True,
            intro_mode_enabled=True,
            max_rounds=10,
        ),
    )
    assert state.phase is GamePhase.LOBBY
    return state


class TestPatched:
    def test_only_the_named_options_move(self, lobby: GameState):
        # The measured wizard run: Chaos -> Classic switches four flags off and
        # the round count from 10 to 20. Everything unnamed keeps its value.
        patched, changed = GameOptions.patched(
            lobby,
            {
                "sabotage_enabled": False,
                "comeback_token_enabled": False,
                "rampup_order_enabled": False,
                "intro_mode_enabled": False,
                "max_rounds": 20,
            },
        )
        assert changed == [
            "comeback_token_enabled",
            "intro_mode_enabled",
            "max_rounds",
            "rampup_order_enabled",
            "sabotage_enabled",
        ]
        assert patched.sabotage_enabled is False
        assert patched.max_rounds == 20
        # Untouched by this body, so it must still be the game's own value.
        assert patched.difficulty == lobby.difficulty

    def test_an_absent_key_is_not_a_reset(self, lobby: GameState):
        # The distinction the whole overlay rests on: "not mentioned" means
        # leave it, never "back to the default". A body that only carries the
        # round count must not switch Sabotage off.
        patched, changed = GameOptions.patched(lobby, {"max_rounds": 20})
        assert changed == ["max_rounds"]
        assert patched.sabotage_enabled is True
        assert patched.comeback_token_enabled is True

    def test_an_unchanged_value_is_not_reported(self, lobby: GameState):
        # The frontend pushes the whole block on every wizard finish, so most
        # keys arrive equal to what the game already has. Reporting those would
        # make every push look like a change in the log and in the response.
        _, changed = GameOptions.patched(lobby, {"sabotage_enabled": True})
        assert changed == []

    def test_an_empty_body_changes_nothing(self, lobby: GameState):
        patched, changed = GameOptions.patched(lobby, {})
        assert changed == []
        assert patched == GameOptions.capture(lobby)

    def test_a_wrong_type_is_skipped_rather_than_coerced(self, lobby: GameState):
        # A client typo must not change how a game is played. "false" is a
        # non-empty string and would be truthy; 1 is not a round count anyone
        # chose.
        _, changed = GameOptions.patched(
            lobby, {"sabotage_enabled": "false", "max_rounds": "20"}
        )
        assert changed == []
        assert lobby.sabotage_enabled is True

    def test_a_bool_does_not_pass_for_an_int(self, lobby: GameState):
        # isinstance(True, int) is true in Python, so without the explicit bool
        # check a max_rounds of ``True`` would be accepted as the number 1 — a
        # one-round game nobody asked for.
        _, changed = GameOptions.patched(lobby, {"max_rounds": True})
        assert changed == []

    def test_an_unknown_key_is_ignored(self, lobby: GameState):
        _, changed = GameOptions.patched(lobby, {"not_an_option": True})
        assert changed == []

    def test_a_new_option_is_patchable_without_touching_this_code(
        self, lobby: GameState
    ):
        # Driven by field_names(), so the day an option is declared it can be
        # patched. This is the property that keeps the second view from growing
        # its own copy of the create parse.
        for name in GameOptions.field_names():
            current = getattr(lobby, name)
            if not isinstance(current, bool):
                continue
            _, changed = GameOptions.patched(lobby, {name: not current})
            assert changed == [name], name


class TestApplyLobbyOptions:
    def test_the_measured_wizard_run_lands_on_the_game(self, lobby: GameState):
        game_id = lobby.game_id
        patched, _ = GameOptions.patched(
            lobby,
            {
                "sabotage_enabled": False,
                "comeback_token_enabled": False,
                "rampup_order_enabled": False,
                "intro_mode_enabled": False,
                "max_rounds": 20,
            },
        )
        assert lobby.apply_lobby_options(patched) is True
        assert lobby.sabotage_enabled is False
        assert lobby.comeback_token_enabled is False
        assert lobby.rampup_order_enabled is False
        assert lobby.intro_mode_enabled is False
        # Patched, not replaced: a new game_id would drop every guest who had
        # already joined by QR code while the host was in the wizard.
        assert lobby.game_id == game_id

    def test_the_round_count_is_re_derived_not_just_stored(self, lobby: GameState):
        # total_rounds comes from the playlist manager, not from max_rounds
        # directly. Writing the option without rebuilding the manager would
        # leave the lobby claiming ten rounds while the host chose twenty.
        assert lobby.total_rounds == 10
        patched, _ = GameOptions.patched(lobby, {"max_rounds": 20})
        assert lobby.apply_lobby_options(patched) is True
        assert lobby.total_rounds == 20

    def test_a_count_below_the_floor_is_raised_not_honoured(self, lobby: GameState):
        # #1475 puts a floor of MIN_ROUNDS = 10 under the round cap, and the
        # playlist manager enforces it. A wizard that offers a smaller number
        # would be lying, so the lobby says ten rather than five — the same
        # answer a freshly created game gives for the same pick.
        patched, _ = GameOptions.patched(lobby, {"max_rounds": 5})
        assert lobby.apply_lobby_options(patched) is True
        assert lobby.max_rounds == 5
        assert lobby.total_rounds == 10

    def test_zero_means_every_playable_song(self, lobby: GameState):
        # #1475's historic behaviour, and the fallback the frontend sends for a
        # missing or malformed setting.
        patched, _ = GameOptions.patched(lobby, {"max_rounds": 0})
        assert lobby.apply_lobby_options(patched) is True
        assert lobby.total_rounds == 20

    def test_a_running_game_is_refused(self, lobby: GameState):
        # update-lobby also serves PLAYING and REVEAL so the host can move the
        # music to another speaker. A round count or a mode flag changing there
        # would rewrite the rules under the players mid-game.
        lobby._set_phase(GamePhase.PLAYING)
        patched, _ = GameOptions.patched(lobby, {"max_rounds": 20})
        assert lobby.apply_lobby_options(patched) is False
        assert lobby.total_rounds == 10

    def test_a_game_that_does_not_exist_is_refused(self):
        state = make_game_state()
        assert state.apply_lobby_options(GameOptions()) is False

    def test_title_artist_exclusion_is_enforced_on_the_way_in(self, lobby: GameState):
        # create_game runs _challenge_manager.configure right after apply_to;
        # skipping it here would leave a lobby switched INTO Title & Artist
        # carrying the artist challenge alongside it.
        patched, _ = GameOptions.patched(
            lobby, {"title_artist_mode": True, "artist_challenge_enabled": False}
        )
        assert lobby.apply_lobby_options(patched) is True
        assert lobby.title_artist_mode is True
        assert lobby.artist_challenge_enabled is False

    def test_difficulty_travels_too(self, lobby: GameState):
        patched, _ = GameOptions.patched(lobby, {"difficulty": DIFFICULTY_HARD})
        assert lobby.apply_lobby_options(patched) is True
        assert lobby.difficulty == DIFFICULTY_HARD
