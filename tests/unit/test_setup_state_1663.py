"""Server-side setup flag tests (#1663).

Covers the pure ``_is_setup_complete`` predicate that drives the ``status``
payload's ``setup_complete`` field — the server-side replacement for the
localStorage-only "is configured?" check that made a configured instance look
unconfigured on a new device.
"""

from __future__ import annotations

from custom_components.beatify.server.serializers import _is_setup_complete


def test_none_blob_is_incomplete():
    assert _is_setup_complete(None) is False


def test_non_dict_blob_is_incomplete():
    assert _is_setup_complete("nope") is False  # type: ignore[arg-type]


def test_missing_player_is_incomplete():
    blob = {"game_settings": {"selectedPlaylists": [{"path": "a.json"}]}}
    assert _is_setup_complete(blob) is False


def test_missing_settings_is_incomplete():
    assert _is_setup_complete({"last_player": "media_player.kitchen"}) is False


def test_empty_playlists_is_incomplete():
    blob = {
        "last_player": "media_player.kitchen",
        "game_settings": {"selectedPlaylists": []},
    }
    assert _is_setup_complete(blob) is False


def test_player_and_playlist_is_complete():
    blob = {
        "last_player": "media_player.kitchen",
        "game_settings": {"selectedPlaylists": [{"path": "80s.json"}]},
    }
    assert _is_setup_complete(blob) is True
