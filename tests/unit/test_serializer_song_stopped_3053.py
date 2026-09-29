"""#3053: the PLAYING payload carries the host's per-round ``song_stopped``."""

from __future__ import annotations

from custom_components.beatify.game.serializers import GameStateSerializer
from custom_components.beatify.game.state import GamePhase
from tests.conftest import make_game_state, make_songs


def _playing_game():
    gs = make_game_state()
    gs.create_game(
        playlists=["test.json"],
        songs=make_songs(3),
        media_player="media_player.test",
        base_url="http://localhost:8123",
    )
    gs.phase = GamePhase.PLAYING
    gs.current_song = {"title": "Hey Jude", "artist": "The Beatles"}
    return gs


def test_playing_payload_song_stopped_false_by_default():
    gs = _playing_game()
    assert GameStateSerializer.serialize(gs)["song_stopped"] is False


def test_playing_payload_song_stopped_true_after_stop():
    gs = _playing_game()
    gs.song_stopped = True
    assert GameStateSerializer.serialize(gs)["song_stopped"] is True
