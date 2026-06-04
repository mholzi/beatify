"""Tests for the conditional title/artist vote window in REVEAL (P4, #1180)."""

from __future__ import annotations

import asyncio


from custom_components.beatify.game.state import GamePhase
from tests.conftest import make_game_state, make_songs


def _ta_songs(n: int = 3) -> list[dict]:
    songs = make_songs(n)
    for i, s in enumerate(songs):
        s["title"] = f"Real Title {i}"
        s["artist"] = f"Real Artist {i}"
    return songs


async def _start_round(gs):
    gs._media_player_service = None  # skip real playback
    gs.create_game(
        playlists=["t.json"],
        songs=_ta_songs(3),
        media_player="media_player.x",
        base_url="http://h",
        title_artist_mode=True,
    )
    gs.add_player(
        "Alice", __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock()
    )
    gs.add_player(
        "Bob", __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock()
    )
    for p in gs.players.values():
        p.connected = True


class TestDelegation:
    def test_delegation_methods_present(self):
        gs = make_game_state()
        assert hasattr(gs, "register_title_artist_vote")
        assert hasattr(gs, "set_title_artist_override")
        assert hasattr(gs, "get_near_misses")
        assert hasattr(gs, "has_near_misses")

    def test_register_vote_delegates(self):
        gs = make_game_state()
        gs._challenge_manager.configure(
            artist_challenge_enabled=False,
            movie_quiz_enabled=False,
            title_artist_mode=True,
        )
        gs._challenge_manager.init_round({"title": "T Word", "artist": "A Word"})
        gs._challenge_manager.submit_title_artist_guess(
            "Alice", "Wrong Wrong Title", "A Word", 1.0
        )
        gs.register_title_artist_vote("Bob", "Alice:title", True)
        assert gs.has_near_misses() is True
        assert gs.get_near_misses()[0]["votes_yes"] == 1


class TestConditionalWindow:
    async def test_no_near_miss_resolves_immediately(self):
        gs = make_game_state()
        await _start_round(gs)
        await gs.start_round()
        # Both guess exactly -> no near-misses.
        gs._challenge_manager.submit_title_artist_guess(
            "Alice", gs.current_song["title"], gs.current_song["artist"], 1.0
        )
        gs._challenge_manager.submit_title_artist_guess(
            "Bob", gs.current_song["title"], gs.current_song["artist"], 1.0
        )
        for p in gs.players.values():
            p.submitted = True
        await gs.end_round()
        assert gs.phase == GamePhase.REVEAL
        # Resolved synchronously; no open voting window task.
        assert gs._challenge_manager.title_artist_challenge.resolved is True
        assert gs.is_title_artist_voting_open() is False

    async def test_near_miss_opens_window(self):
        gs = make_game_state()
        await _start_round(gs)
        await gs.start_round()
        gs._challenge_manager.submit_title_artist_guess(
            "Alice", "Completely Different", gs.current_song["artist"], 1.0
        )
        gs._challenge_manager.submit_title_artist_guess(
            "Bob", gs.current_song["title"], gs.current_song["artist"], 1.0
        )
        for p in gs.players.values():
            p.submitted = True
        await gs.end_round()
        assert gs.phase == GamePhase.REVEAL
        assert gs.is_title_artist_voting_open() is True
        assert gs._challenge_manager.title_artist_challenge.resolved is False
        # cleanup the pending window task
        gs._cancel_auto_advance()

    async def test_host_advance_resolves_first(self):
        gs = make_game_state()
        await _start_round(gs)
        await gs.start_round()
        gs._challenge_manager.submit_title_artist_guess(
            "Alice", "Completely Different", gs.current_song["artist"], 1.0
        )
        gs._challenge_manager.submit_title_artist_guess(
            "Bob", gs.current_song["title"], gs.current_song["artist"], 1.0
        )
        for p in gs.players.values():
            p.submitted = True
        await gs.end_round()
        gs.set_title_artist_override("Alice:title", True)
        # Host advancing finalizes votes before the next round.
        await gs.resolve_title_artist_if_pending()
        assert gs._challenge_manager.title_artist_challenge.resolved is True
        assert (
            gs._challenge_manager.title_artist_challenge.guesses["Alice"][
                "title_status"
            ]
            == "near_miss_accepted"
        )
        assert gs.is_title_artist_voting_open() is False

    async def test_window_resolves_after_timeout(self):
        gs = make_game_state()
        await _start_round(gs)
        await gs.start_round()
        gs._challenge_manager.submit_title_artist_guess(
            "Alice", "Completely Different", gs.current_song["artist"], 1.0
        )
        gs._challenge_manager.submit_title_artist_guess(
            "Bob", gs.current_song["title"], gs.current_song["artist"], 1.0
        )
        for p in gs.players.values():
            p.submitted = True
        # Patch the window length to ~0 so the test does not wait 15s.
        import custom_components.beatify.game.state as state_mod

        orig = state_mod.TITLE_ARTIST_VOTE_WINDOW_SECONDS
        state_mod.TITLE_ARTIST_VOTE_WINDOW_SECONDS = 0
        try:
            await gs.end_round()
            assert gs.is_title_artist_voting_open() is True
            # Let the 0s window task run.
            await asyncio.sleep(0.05)
            assert gs._challenge_manager.title_artist_challenge.resolved is True
            assert gs.is_title_artist_voting_open() is False
        finally:
            state_mod.TITLE_ARTIST_VOTE_WINDOW_SECONDS = orig
