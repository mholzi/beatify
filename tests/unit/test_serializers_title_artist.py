"""Serializer tests for Title & Artist mode (#1180, Phase 3)."""

from __future__ import annotations

from custom_components.beatify.game.serializers import GameStateSerializer
from custom_components.beatify.game.state import GamePhase
from tests.conftest import make_game_state, make_songs


def _game(*, title_artist_mode: bool):
    gs = make_game_state()
    gs.create_game(
        playlists=["test.json"],
        songs=make_songs(3),
        media_player="media_player.test",
        base_url="http://localhost:8123",
        title_artist_mode=title_artist_mode,
    )
    return gs


def test_top_level_flag_present_when_on():
    gs = _game(title_artist_mode=True)
    state = GameStateSerializer.serialize(gs)
    assert state["title_artist_mode"] is True


def test_top_level_flag_false_when_off():
    gs = _game(title_artist_mode=False)
    state = GameStateSerializer.serialize(gs)
    assert state["title_artist_mode"] is False


def test_playing_hides_truth():
    gs = _game(title_artist_mode=True)
    gs.phase = GamePhase.PLAYING
    gs.current_song = {"title": "Hey Jude", "artist": "The Beatles"}
    gs._challenge_manager.init_round(gs.current_song)
    state = GameStateSerializer.serialize(gs)
    assert state["title_artist_challenge"] == {"active": True}
    assert "correct_title" not in state["title_artist_challenge"]


def test_reveal_shows_results_and_truth():
    gs = _game(title_artist_mode=True)
    gs.phase = GamePhase.PLAYING
    gs.current_song = {"title": "Hey Jude", "artist": "The Beatles"}
    gs._challenge_manager.init_round(gs.current_song)
    gs.submit_title_artist_guess("Alice", "Hey Jude", "Beatles", 1.0)
    gs.phase = GamePhase.REVEAL
    state = GameStateSerializer.serialize(gs)
    tac = state["title_artist_challenge"]
    assert tac["correct_title"] == "Hey Jude"
    assert tac["correct_artist"] == "The Beatles"
    assert tac["voting_open"] is False
    assert tac["near_misses"] == []
    assert {r["player"] for r in tac["results"]} == {"Alice"}


def test_no_challenge_key_when_mode_off():
    gs = _game(title_artist_mode=False)
    gs.phase = GamePhase.PLAYING
    gs.current_song = {"title": "Hey Jude", "artist": "The Beatles"}
    gs._challenge_manager.init_round(gs.current_song)
    state = GameStateSerializer.serialize(gs)
    assert "title_artist_challenge" not in state
