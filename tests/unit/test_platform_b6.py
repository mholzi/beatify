"""Regression tests for B6 HA-platform plumbing (#1402).

Covers:
* Fix 2 — BeatifyCurrentSongSensor.native_value is a pure read; the cache is
  refreshed in the _on_state_changed callback, not as a property side effect.
* Fix 4 — every sensor / binary_sensor entity carries a shared Beatify
  DeviceInfo (identifiers, name, manufacturer, sw_version from manifest).
* Fix 5 — BeatifyGameActiveSensor reuses GameState.leader instead of
  recomputing the leaderboard max().
"""

from __future__ import annotations

from unittest.mock import MagicMock

from tests.conftest import make_game_state, make_player
from tests.unit import _ha_stubs

_ha_stubs.install()

from custom_components.beatify.binary_sensor import (  # noqa: E402
    BeatifyGameActiveSensor,
)
from custom_components.beatify.const import DOMAIN  # noqa: E402
from custom_components.beatify.device import build_device_info  # noqa: E402
from custom_components.beatify.game.state import GamePhase  # noqa: E402
from custom_components.beatify.sensor import (  # noqa: E402
    BeatifyCurrentSongSensor,
    BeatifyLeaderSensor,
)


def _device_info(version: str = "4.0.0"):
    hass = MagicMock()
    hass.data = {DOMAIN: {"version": version}}
    return build_device_info(hass, "entry123")


# ---------------------------------------------------------------------------
# Fix 4 — DeviceInfo
# ---------------------------------------------------------------------------


def test_build_device_info_fields():
    info = _device_info("4.2.1")
    assert info["identifiers"] == {(DOMAIN, "entry123")}
    assert info["name"] == "Beatify"
    assert info["manufacturer"] == "Beatify"
    assert info["sw_version"] == "4.2.1"


def test_build_device_info_falls_back_when_version_missing():
    hass = MagicMock()
    hass.data = {}  # version not yet populated
    info = build_device_info(hass, "e1")
    assert info["sw_version"] == "unknown"


def test_entities_share_same_device_identifiers():
    game = make_game_state()
    info = _device_info()
    leader_sensor = BeatifyLeaderSensor(game, "entry123", info)
    binary = BeatifyGameActiveSensor(game, "entry123", info)
    # Both platforms attach to the SAME device (same identifiers).
    assert leader_sensor._attr_device_info["identifiers"] == {(DOMAIN, "entry123")}
    assert (
        binary._attr_device_info["identifiers"]
        == leader_sensor._attr_device_info["identifiers"]
    )


# ---------------------------------------------------------------------------
# Fix 2 — current-song cache is updated in the callback, not in native_value
# ---------------------------------------------------------------------------


def test_current_song_native_value_is_pure_read():
    game = make_game_state()
    sensor = BeatifyCurrentSongSensor(game, "e", _device_info())

    # Song available during a non-PLAYING phase, but the callback hasn't fired.
    game.phase = GamePhase.REVEAL
    game.current_song = {"title": "Africa", "artist": "Toto", "year": 1982}

    # Pure read: native_value must NOT populate the cache as a side effect.
    assert sensor.native_value is None
    assert sensor._last_title is None

    # The callback is what refreshes the cache.
    sensor._on_state_changed()
    assert sensor._last_title == "Africa"
    assert sensor._last_artist == "Toto"
    assert sensor._last_year == 1982
    assert sensor.native_value == "Africa"


def test_current_song_hidden_during_playing_and_cache_untouched():
    game = make_game_state()
    sensor = BeatifyCurrentSongSensor(game, "e", _device_info())

    # Seed the cache via a REVEAL callback.
    game.phase = GamePhase.REVEAL
    game.current_song = {"title": "Africa", "artist": "Toto", "year": 1982}
    sensor._on_state_changed()

    # Now PLAYING — value hidden, and a PLAYING callback must NOT overwrite the
    # cached last song (so it reappears at the next REVEAL).
    game.phase = GamePhase.PLAYING
    game.current_song = {"title": "Secret", "artist": "X", "year": 2000}
    sensor._on_state_changed()
    assert sensor.native_value is None
    assert sensor._last_title == "Africa"

    game.phase = GamePhase.REVEAL
    sensor._on_state_changed()
    assert sensor.native_value == "Secret"  # cache refreshed once back in REVEAL


def test_current_song_extra_attributes_pure_read():
    game = make_game_state()
    sensor = BeatifyCurrentSongSensor(game, "e", _device_info())
    game.phase = GamePhase.PLAYING
    assert sensor.extra_state_attributes == {"artist": None, "year": None}


# ---------------------------------------------------------------------------
# Fix 5 — binary sensor reuses GameState.leader
# ---------------------------------------------------------------------------


def test_game_active_leader_attribute_reuses_game_state_leader():
    game = make_game_state()
    game.players = {
        "a": make_player("Alice", score=10),
        "b": make_player("Bob", score=42),
        "c": make_player("Cara", score=7),
    }
    sensor = BeatifyGameActiveSensor(game, "e", _device_info())
    attrs = sensor.extra_state_attributes
    assert attrs["leader"] == "Bob"
    assert attrs["leader"] == game.leader.name


def test_game_active_leader_none_when_no_players():
    game = make_game_state()
    game.players = {}
    sensor = BeatifyGameActiveSensor(game, "e", _device_info())
    assert sensor.extra_state_attributes["leader"] is None
