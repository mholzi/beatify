"""#3494 - a solo near-miss accepted at once must be scored and recorded."""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.beatify.game.state import GamePhase

from tests.conftest import make_game_state, make_songs


async def _game(names, rounds=2):
    songs = make_songs(rounds + 1)
    for i, song in enumerate(songs):
        song["title"] = f"Real Title {i}"
        song["artist"] = f"Real Artist {i}"
    state = make_game_state()
    state.create_game(
        playlists=["t.json"],
        songs=songs,
        media_player="media_player.x",
        base_url="http://h",
        title_artist_mode=True,
    )
    state.platform = "music_assistant"
    for name in names:
        state.add_player(name, MagicMock())
        state.get_player(name).connected = True
    return state


async def _play_round(state, first_title_wrong: bool):
    await state.start_round()
    song = state.current_song
    for i, name in enumerate(p.name for p in state.players.values()):
        title = "Real Mismatch" if (first_title_wrong and i == 0) else song["title"]
        state._challenge_manager.submit_title_artist_guess(
            name, title, song["artist"], 1.0
        )
    for p in state.players.values():
        p.submitted = True
    await state.end_round()


class TestSoloNearMissScored:
    async def test_score_and_round_results_at_reveal(self):
        state = await _game(["Alice"])
        await _play_round(state, first_title_wrong=True)
        assert state.phase == GamePhase.REVEAL
        guess = state.title_artist_challenge.guesses["Alice"]
        assert guess["title_status"] == "near_miss_accepted"
        player = state.get_player("Alice")
        assert player.score > 0
        assert player.round_score == player.score
        assert len(player.round_scores) == 1

    async def test_round_scores_match_rounds_played(self):
        state = await _game(["Alice"], rounds=2)
        await _play_round(state, first_title_wrong=True)
        await _play_round(state, first_title_wrong=False)
        player = state.get_player("Alice")
        assert len(player.round_scores) == 2
        assert player.round_scores[0] > 0
        assert player.score == sum(player.round_scores)

    async def test_multiplayer_vote_window_unchanged(self):
        state = await _game(["Alice", "Bob"])
        await _play_round(state, first_title_wrong=True)
        assert state.is_title_artist_voting_open() is True
        # Scoring stays deferred until the window resolves.
        assert state.get_player("Alice").round_scores == []
        await state.resolve_title_artist_if_pending()
        assert len(state.get_player("Alice").round_scores) == 1
        assert len(state.get_player("Bob").round_scores) == 1
