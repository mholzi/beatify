"""The player payload is an allowlist, and the allowlist is complete (#2634).

``redact_state_for_player`` used to be a denylist of two keys over a payload of
~59. Every key the serializer grew therefore reached the player sockets by
default, and twice that default was the bug: #1366 (``admin_song``) and #2550
(``artist_challenge``), each closed afterwards by widening the denylist.

The direction is reversed now. These tests hold the reversal in place:

* :class:`TestAllowlistCompleteness` walks **every** key the serializer can
  produce and fails when one is in neither ``PLAYER_VISIBLE_KEYS`` nor
  ``ADMIN_ONLY_KEYS``. A future answer field is a red build here, not a line in
  a guest's network tab.
* :class:`TestHistoricLeaks` keeps the two leaks that actually happened closed.
"""

from __future__ import annotations

import re
from pathlib import Path

import custom_components.beatify.game.serializers as game_serializers
from custom_components.beatify.game.state import GamePhase
from custom_components.beatify.server.serializers import (
    ADMIN_ONLY_KEYS,
    PLAYER_VISIBLE_KEYS,
    PLAYING_SONG_PLAYER_KEYS,
    REDACTED_PLACEHOLDER,
    build_state_message,
    redact_state_for_player,
)
from tests.conftest import make_game_state, make_songs

_SERIALIZER_SOURCE = Path(game_serializers.__file__)

# `state["<key>"] = ...` — the form every phase-specific key is written in.
_ASSIGNED_KEY = re.compile(r'state\[\s*"([A-Za-z_][A-Za-z0-9_]*)"\s*\]\s*=')

# The static scan is the part of this test that sees keys no fixture happens to
# trigger. If a refactor ever changes how the serializer writes its keys the
# regex would quietly match nothing and the whole test would pass vacuously, so
# pin a floor well below today's count (37) and well above zero.
_MIN_EXPECTED_ASSIGNED_KEYS = 30


def _statically_assigned_keys() -> set[str]:
    """Every ``state["x"] = ...`` key in the serializer, condition or not.

    Read off the source rather than off a fixture on purpose: half the payload
    is conditional (``early_reveal`` needs an early reveal, ``song_difficulty``
    needs a wired StatsService, ``eliminated_this_round`` needs Sudden Death),
    and a test that only sees what it managed to trigger is exactly the gap
    #2634 is about.
    """
    keys = set(_ASSIGNED_KEY.findall(_SERIALIZER_SOURCE.read_text()))
    assert len(keys) >= _MIN_EXPECTED_ASSIGNED_KEYS, (
        f"Only {len(keys)} keys matched {_ASSIGNED_KEY.pattern!r} in "
        f"{_SERIALIZER_SOURCE.name}. The serializer probably changed how it "
        "writes state keys — update this scan, or the allowlist stops being "
        "checked at all."
    )
    return keys


def _make_game(*, title_artist_mode: bool = False):
    gs = make_game_state()
    gs.create_game(
        playlists=["test.json"],
        songs=make_songs(3),
        media_player="media_player.test",
        base_url="http://localhost:8123",
        title_artist_mode=title_artist_mode,
    )
    gs.current_song = {
        "title": "Hey Jude",
        "artist": "The Beatles",
        "year": 1968,
        "album_art": "/art.png",
        "fun_fact": "Written for Julian Lennon.",
    }
    if title_artist_mode:
        gs._challenge_manager.init_round(gs.current_song)
    return gs


def _keys_seen_at_runtime() -> set[str]:
    """Union of the top-level keys an actual broadcast carries, per phase.

    Complements the static scan: it catches the base dict literal in
    ``GameStateSerializer.serialize`` (which uses no ``state["x"] =`` form) and
    the ``type`` envelope that ``build_state_message`` adds.
    """
    seen: set[str] = set()
    for phase in (
        GamePhase.LOBBY,
        GamePhase.PLAYING,
        GamePhase.REVEAL,
        GamePhase.PAUSED,
        GamePhase.END,
    ):
        gs = _make_game()
        gs.phase = phase
        message = build_state_message(gs)
        assert message is not None
        seen |= set(message)
    return seen


class TestAllowlistCompleteness:
    """Every key the serializer can emit is classified — or the build fails."""

    def test_every_serializer_key_is_classified(self):
        produced = _statically_assigned_keys() | _keys_seen_at_runtime()
        classified = PLAYER_VISIBLE_KEYS | ADMIN_ONLY_KEYS

        unclassified = produced - classified

        assert not unclassified, (
            "New state key(s) reach the broadcast without a decision: "
            f"{sorted(unclassified)}.\n"
            "Ask whether a guest holding their phone may see this BEFORE they "
            "guess, then add it to PLAYER_VISIBLE_KEYS or to ADMIN_ONLY_KEYS in "
            "custom_components/beatify/server/serializers.py. Until then it is "
            "withheld from every player socket, which will look like a missing "
            "feature rather than a leak (#2634)."
        )

    def test_no_stale_entries_in_the_lists(self):
        produced = _statically_assigned_keys() | _keys_seen_at_runtime()

        stale = (PLAYER_VISIBLE_KEYS | ADMIN_ONLY_KEYS) - produced

        assert not stale, (
            f"Classified key(s) the serializer no longer produces: {sorted(stale)}. "
            "Drop them, otherwise the lists slowly stop describing the payload."
        )

    def test_a_key_cannot_be_both_visible_and_admin_only(self):
        assert PLAYER_VISIBLE_KEYS.isdisjoint(ADMIN_ONLY_KEYS)

    def test_admin_only_keys_are_actually_withheld(self):
        gs = _make_game()
        gs.phase = GamePhase.PLAYING
        message = build_state_message(gs)

        player_view = redact_state_for_player(message)

        for key in ADMIN_ONLY_KEYS:
            assert key not in player_view, f"{key} is admin-only but reached a player"

    def test_playing_song_card_is_allowlisted_too(self):
        """The song card is where the answer lives, so it gets the same default.

        A ``year`` added to the PLAYING payload would be the answer, printed,
        before anyone guessed.
        """
        gs = _make_game()
        gs.phase = GamePhase.PLAYING
        message = build_state_message(gs)
        assert set(message["song"]) <= PLAYING_SONG_PLAYER_KEYS, (
            "The PLAYING song card grew a field. Decide whether players may see "
            "it and update PLAYING_SONG_PLAYER_KEYS."
        )

        player_view = redact_state_for_player(message)

        assert set(player_view["song"]) <= PLAYING_SONG_PLAYER_KEYS

    def test_an_unclassified_key_is_dropped_at_runtime(self):
        """Default-deny: the CI failure above is the loud half, this is the quiet
        half that holds even when someone ships without running the tests."""
        message = {
            "type": "state",
            "phase": "PLAYING",
            "song": {"artist": "Queen", "title": "Bohemian Rhapsody"},
            "tomorrows_answer": 1975,
        }

        player_view = redact_state_for_player(message)

        assert "tomorrows_answer" not in player_view
        assert message["tomorrows_answer"] == 1975, "input must not be mutated"

    def test_nothing_to_strip_returns_the_same_object(self):
        """The broadcast path serializes once when the two variants are identical
        (#1711) — that shortcut depends on identity, not equality."""
        gs = _make_game()
        message = build_state_message(gs)  # LOBBY: no song, no admin_song

        assert redact_state_for_player(message) is message


class TestHistoricLeaks:
    """The two leaks that actually happened stay closed."""

    def test_1366_admin_song_never_reaches_a_player(self):
        gs = _make_game()
        gs.phase = GamePhase.PLAYING
        message = build_state_message(gs)
        assert message["admin_song"]["year"] == 1968, "the spectator gets the answer"

        player_view = redact_state_for_player(message)

        assert "admin_song" not in player_view
        assert "admin_song" in message, "input must not be mutated"

    def test_1366_title_artist_mode_masks_both_answers(self):
        gs = _make_game(title_artist_mode=True)
        gs.phase = GamePhase.PLAYING
        message = build_state_message(gs)

        player_view = redact_state_for_player(message)

        assert player_view["song"]["artist"] == REDACTED_PLACEHOLDER
        assert player_view["song"]["title"] == REDACTED_PLACEHOLDER
        # Album art must survive — players need it to play along.
        assert player_view["song"]["album_art"] == "/art.png"
        assert message["song"]["artist"] == "The Beatles", "input must not be mutated"

    def test_2550_artist_challenge_masks_the_artist_only(self):
        message = {
            "type": "state",
            "phase": "PLAYING",
            "artist_challenge": {"options": ["Queen", "Abba"]},
            "song": {"artist": "Queen", "title": "Bohemian Rhapsody", "album_art": "x"},
        }

        player_view = redact_state_for_player(message)

        assert player_view["song"]["artist"] == REDACTED_PLACEHOLDER
        # The title is not part of that challenge and stays visible.
        assert player_view["song"]["title"] == "Bohemian Rhapsody"
        assert player_view["song"]["album_art"] == "x"
        assert message["song"]["artist"] == "Queen", "input must not be mutated"

    def test_reveal_is_the_moment_the_answers_go_public(self):
        gs = _make_game(title_artist_mode=True)
        gs.phase = GamePhase.REVEAL
        message = build_state_message(gs)

        player_view = redact_state_for_player(message)

        assert player_view["song"]["artist"] == "The Beatles"
        assert player_view["song"]["title"] == "Hey Jude"
        assert player_view["song"]["year"] == 1968
        assert player_view["song"]["fun_fact"] == "Written for Julian Lennon."
