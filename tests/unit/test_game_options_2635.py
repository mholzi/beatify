"""GameOptions completeness tests (Issue #2635).

The bug this file exists to prevent: the same game option used to be written
out four times — as a parameter of ``create_game``, as a field of
``GameStateConfig``, as an entry in the hand-written ``preserved`` dict of
``rematch_game``, and as a key of ``create_kwargs`` in ``server/game_views.py``.
Miss one of them and the rematch broke *silently*: the option fell back to its
default with no error, no log line and no failing test.

``GameOptions`` collapses that to one list. The tests below are what keeps it
one list:

* ``test_every_option_survives_the_rematch`` sets EVERY option to a non-default
  value, creates a game, runs a rematch, and asserts every option is still
  there. It is driven by ``fields(GameOptions)``, so a newly added option is
  covered the moment it is declared — no test edit needed.
* ``test_completeness_test_fails_when_an_option_is_dropped`` is the counter-
  proof: it re-runs that same check against a deliberately broken
  ``GameOptions`` (one field omitted from the capture/apply loop, exactly the
  historic failure mode) and asserts it goes red.
* ``test_sentinel_covers_every_option`` fails loudly when someone adds a
  non-bool option without telling this file what a non-default value looks
  like — better a red test than a silently uncovered field.
* ``test_state_owned_options_are_config_managed`` keeps ``GameStateConfig`` in
  step, so ``end_game`` still resets what it used to reset.
"""

from __future__ import annotations

from dataclasses import fields, replace
from typing import Any

import pytest

from custom_components.beatify.const import (
    DIFFICULTY_HARD,
    PROVIDER_APPLE_MUSIC,
)
from custom_components.beatify.game.config import (
    REMATCH_CARRYOVER_ATTRS,
    GameOptions,
    GameStateConfig,
)
from custom_components.beatify.game.state import GamePhase, GameState

from tests.conftest import make_game_state

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

#: Non-default values for the options whose type does not tell us one. Bools
#: are flipped automatically; everything else has to be listed here, and
#: ``test_sentinel_covers_every_option`` fails if a new option is neither.
_NON_BOOL_SENTINELS: dict[str, Any] = {
    "round_duration": 30,  # != DEFAULT_ROUND_DURATION, inside 15..60
    "difficulty": DIFFICULTY_HARD,
    "provider": PROVIDER_APPLE_MUSIC,
    "platform": "music_assistant",
    "max_rounds": 12,
    "reveal_auto_advance": 60,
}


def _songs(n: int = 20) -> list[dict[str, Any]]:
    """Songs playable on both the default and the sentinel provider."""
    return [
        {
            "year": 1980 + i,
            "title": f"Song {i}",
            "artist": f"Artist {i}",
            "uri": f"spotify:track:test{i:022d}",
            "uri_spotify": f"spotify:track:test{i:022d}",
            "uri_apple_music": f"applemusic://track/{100 + i}",
        }
        for i in range(n)
    ]


def _sentinel_options() -> tuple[GameOptions, list[str]]:
    """Build a GameOptions in which every field differs from its default.

    Returns the options plus the list of option names with no sentinel rule, so
    the caller can turn that into a readable failure.
    """
    defaults = GameOptions()
    values: dict[str, Any] = {}
    uncovered: list[str] = []
    for f in fields(GameOptions):
        current = getattr(defaults, f.name)
        if isinstance(current, bool):
            values[f.name] = not current
        elif f.name in _NON_BOOL_SENTINELS:
            values[f.name] = _NON_BOOL_SENTINELS[f.name]
        else:
            uncovered.append(f.name)
    return replace(defaults, **values), uncovered


def _create(state: GameState, options: GameOptions) -> None:
    state.create_game(
        playlists=["test.json"],
        songs=_songs(),
        media_player="media_player.party",
        base_url="http://localhost:8123",
        options=options,
    )


def _assert_options_on_state(state: GameState, expected: GameOptions) -> None:
    """Assert every GameOptions field reads back off the state."""
    mismatches = {
        f.name: (getattr(expected, f.name), getattr(state, f.name))
        for f in fields(GameOptions)
        if getattr(state, f.name) != getattr(expected, f.name)
    }
    assert not mismatches, (
        "Game option(s) did not survive: "
        + ", ".join(
            f"{name} expected {want!r}, got {got!r}"
            for name, (want, got) in sorted(mismatches.items())
        )
        + ". A new option has to be a GameOptions field — nothing else."
    )


# ---------------------------------------------------------------------------
# The completeness test
# ---------------------------------------------------------------------------


class TestRematchCompleteness:
    """Every configured option must survive the rematch (#2635)."""

    def test_sentinel_covers_every_option(self):
        """A new non-bool option must get a sentinel here, or this fails."""
        options, uncovered = _sentinel_options()
        assert not uncovered, (
            "New GameOptions field(s) with no test sentinel: "
            f"{', '.join(uncovered)}. Add a non-default value to "
            "_NON_BOOL_SENTINELS in this file so the rematch completeness "
            "test actually covers them."
        )
        # And every sentinel really is non-default — otherwise the round-trip
        # below would pass on an option that was silently reset.
        defaults = GameOptions()
        same = [
            f.name
            for f in fields(GameOptions)
            if getattr(options, f.name) == getattr(defaults, f.name)
        ]
        assert not same, f"Sentinel equals the default for: {', '.join(same)}"

    def test_every_option_survives_the_rematch(self):
        """Set every option, rematch, and find all of them still set."""
        options, _ = _sentinel_options()
        state = make_game_state()

        _create(state, options)
        # Sanity: create_game itself applied them.
        _assert_options_on_state(state, options)

        state.rematch_game()

        assert state.phase == GamePhase.LOBBY
        _assert_options_on_state(state, options)

    def test_completeness_test_fails_when_an_option_is_dropped(self, monkeypatch):
        """The counter-proof: the check above goes red on the historic bug.

        ``sabotage_enabled`` (#1665) is dropped from the capture/apply loop —
        precisely what happened when an option was added to ``create_game`` but
        forgotten in the ``preserved`` dict. The option then falls back to its
        default on the rematch, and the assertion must catch it.
        """
        dropped = "sabotage_enabled"
        full = GameOptions.field_names()
        assert dropped in full

        monkeypatch.setattr(
            GameOptions,
            "field_names",
            classmethod(lambda cls: [n for n in full if n != dropped]),
        )

        options, _ = _sentinel_options()
        state = make_game_state()
        _create(state, options)
        state.rematch_game()

        # The option is a GameStateConfig field, so _reset_game_internals put it
        # back to its default and nothing carried it over again.
        assert getattr(state, dropped) is not getattr(options, dropped)
        with pytest.raises(AssertionError, match=dropped):
            _assert_options_on_state(state, options)

    def test_carryover_attrs_survive_the_rematch(self):
        """Content / join URL / language are kept too (#591)."""
        state = make_game_state()
        songs = _songs()
        state.create_game(
            playlists=["party.json"],
            songs=songs,
            media_player="media_player.party",
            base_url="http://ha.local:8123",
        )
        state.language = "de"
        before = {name: getattr(state, name) for name in REMATCH_CARRYOVER_ATTRS}
        game_id_before = state.game_id

        state.rematch_game()

        assert state.playlists == before["playlists"]
        assert state.songs == before["songs"]
        assert state.media_player == before["media_player"]
        assert state.language == "de"
        # join_url keeps its base but carries the NEW game id.
        assert state.game_id != game_id_before
        assert (
            state.join_url == f"http://ha.local:8123/beatify/play?game={state.game_id}"
        )

    def test_rematch_works_on_its_own_song_copy(self):
        """The rematch must not hand back the caller's list object."""
        state = make_game_state()
        songs = _songs()
        state.create_game(
            playlists=["test.json"],
            songs=songs,
            media_player="media_player.party",
            base_url="http://localhost:8123",
        )
        state.rematch_game()
        assert state.songs == songs
        assert state.songs is not songs


# ---------------------------------------------------------------------------
# The two dataclasses must not drift apart
# ---------------------------------------------------------------------------


class TestConfigAgreement:
    """GameOptions and GameStateConfig overlap — keep the overlap honest."""

    #: Options that are NOT reset by ``_reset_game_internals`` today and are
    #: not manager-owned either. Documented, not fixed: adding them to
    #: ``GameStateConfig`` would make ``end_game`` clear them, which is a
    #: behaviour change and belongs in its own change (#2635 follow-up).
    NOT_RESET_TODAY = frozenset({"platform", "reveal_auto_advance", "max_rounds"})

    def test_state_owned_options_are_config_managed(self):
        """Options GameState owns itself must be in GameStateConfig.

        Options owned by a manager (ChallengeManager / RoundManager) reach
        GameState through a delegation property and are reset by that manager's
        own ``reset()``; they are detected here by being a ``property`` on the
        class rather than a plain instance attribute.
        """
        config_fields = set(GameStateConfig.field_names())
        missing = []
        for name in GameOptions.field_names():
            if isinstance(getattr(GameState, name, None), property):
                continue  # manager-owned, reset by that manager
            if name in self.NOT_RESET_TODAY:
                continue
            if name not in config_fields:
                missing.append(name)
        assert not missing, (
            "Option(s) that GameState owns but GameStateConfig does not reset: "
            f"{', '.join(missing)}. Add the field to GameStateConfig too, or "
            "list it in NOT_RESET_TODAY with a reason."
        )

    def test_shared_defaults_agree(self):
        """A field in both dataclasses must default to the same value."""
        options = GameOptions()
        config = GameStateConfig()
        shared = set(GameOptions.field_names()) & {
            f.name for f in fields(GameStateConfig)
        }
        assert shared, "expected some overlap between the two dataclasses"
        drift = {
            name: (getattr(options, name), getattr(config, name))
            for name in shared
            if getattr(options, name) != getattr(config, name)
        }
        assert not drift, f"default drift between GameOptions/GameStateConfig: {drift}"


# ---------------------------------------------------------------------------
# create_game's new signature
# ---------------------------------------------------------------------------


class TestCreateGameSignature:
    """The dataclass replaced 18 parameters — the call styles still work."""

    def test_keyword_overrides_still_work(self):
        """The historic create_game(..., sabotage_enabled=True) call style."""
        state = make_game_state()
        state.create_game(
            playlists=["test.json"],
            songs=_songs(),
            media_player="media_player.party",
            base_url="http://localhost:8123",
            sabotage_enabled=True,
            sudden_death_mode=True,
        )
        assert state.sabotage_enabled is True
        assert state.sudden_death_mode is True
        assert state.closest_wins_mode is False

    def test_overrides_win_over_the_options_object(self):
        state = make_game_state()
        state.create_game(
            playlists=["test.json"],
            songs=_songs(),
            media_player="media_player.party",
            base_url="http://localhost:8123",
            options=GameOptions(sabotage_enabled=True, closest_wins_mode=True),
            sabotage_enabled=False,
        )
        assert state.sabotage_enabled is False
        assert state.closest_wins_mode is True

    def test_unknown_option_is_a_type_error(self):
        """A typo must still be loud, as it was with an explicit signature."""
        state = make_game_state()
        with pytest.raises(TypeError):
            state.create_game(
                playlists=["test.json"],
                songs=_songs(),
                media_player="media_player.party",
                base_url="http://localhost:8123",
                sabotage_enable=True,  # typo
            )

    def test_title_artist_mode_still_disables_the_artist_challenge(self):
        """#1180's exclusion is applied by configure(), not by apply_to."""
        state = make_game_state()
        state.create_game(
            playlists=["test.json"],
            songs=_songs(),
            media_player="media_player.party",
            base_url="http://localhost:8123",
            artist_challenge_enabled=True,
            title_artist_mode=True,
        )
        assert state.title_artist_mode is True
        assert state.artist_challenge_enabled is False
        # ...and the rematch keeps the resolved value, not the requested one.
        state.rematch_game()
        assert state.artist_challenge_enabled is False
