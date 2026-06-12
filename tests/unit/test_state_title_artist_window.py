"""Tests for the conditional title/artist vote window in REVEAL (P4, #1180)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from custom_components.beatify.game.state import GamePhase
from tests.conftest import make_game_state, make_songs


def _ta_songs(n: int = 3) -> list[dict]:
    songs = make_songs(n)
    for i, s in enumerate(songs):
        s["title"] = f"Real Title {i}"
        s["artist"] = f"Real Artist {i}"
    return songs


def _stub_media_service() -> MagicMock:
    """A fake MediaPlayerService that reports a healthy, playing speaker.

    Injected so _ensure_media_player_service skips constructing a real
    (hass-less) service — tests stub the dependency instead of branching
    production code on a None hass.
    """
    svc = MagicMock()
    svc.is_available.return_value = True
    svc.play_song = AsyncMock(return_value=True)
    svc.verify_responsive = AsyncMock(return_value=(True, None))
    return svc


async def _start_round(gs):
    # Inject a stub service (truthy) so the lazy _ensure_media_player_service
    # is a no-op and real playback never runs.
    gs._media_player_service = _stub_media_service()
    gs.create_game(
        playlists=["t.json"],
        songs=_ta_songs(3),
        media_player="media_player.x",
        base_url="http://h",
        title_artist_mode=True,
    )
    gs.platform = "music_assistant"  # skip the verify_responsive branch
    gs.add_player("Alice", MagicMock())
    gs.add_player("Bob", MagicMock())
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
        gs._challenge_manager.init_round({"title": "Word Up Now", "artist": "A Word"})
        gs._challenge_manager.submit_title_artist_guess(
            "Alice", "Word Up Later", "A Word", 1.0
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
            "Alice", "Real Mismatch", gs.current_song["artist"], 1.0
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
            "Alice", "Real Mismatch", gs.current_song["artist"], 1.0
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
            "Alice", "Real Mismatch", gs.current_song["artist"], 1.0
        )
        gs._challenge_manager.submit_title_artist_guess(
            "Bob", gs.current_song["title"], gs.current_song["artist"], 1.0
        )
        for p in gs.players.values():
            p.submitted = True
        # Patch the window length to ~0 so the test does not wait 15s.
        import custom_components.beatify.game.state_vote_window as state_mod

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


class TestVoteWindowScoring:
    """The window's reason to exist: accepted near-misses change the score.

    These assert real leaderboard bookkeeping (player.score, round_score,
    round_scores, rounds_played) — not just the resolved/voting_open flags —
    so the load-bearing behavior of finalize/score is verified (#1180 P4).
    """

    async def _setup_near_miss(self, gs):
        """Alice: near-miss title + exact artist; Bob: exact title + artist."""
        await _start_round(gs)
        await gs.start_round()
        gs._challenge_manager.submit_title_artist_guess(
            "Alice", "Real Mismatch", gs.current_song["artist"], 1.0
        )
        gs._challenge_manager.submit_title_artist_guess(
            "Bob", gs.current_song["title"], gs.current_song["artist"], 1.0
        )
        for p in gs.players.values():
            p.submitted = True

    async def test_scoring_deferred_while_window_open(self):
        """With a near-miss pending, scoring is held until the window closes."""
        gs = make_game_state()
        await self._setup_near_miss(gs)
        await gs.end_round()
        assert gs.is_title_artist_voting_open() is True
        # Scoring deferred — nobody has banked points yet, no round recorded.
        for p in gs.players.values():
            assert p.score == 0
            assert p.rounds_played == 0
            assert p.round_scores == []
        gs._cancel_auto_advance()

    async def test_override_accept_increases_leaderboard(self):
        gs = make_game_state()
        await self._setup_near_miss(gs)
        await gs.end_round()
        gs.set_title_artist_override("Alice:title", True)
        await gs.resolve_title_artist_if_pending()

        alice = gs.players["Alice"]
        bob = gs.players["Bob"]
        # Alice: accepted near-miss title (partial 5) + exact artist (5) = 10.
        assert alice.score == 10
        assert alice.round_score == 10
        assert alice.round_scores == [10]
        assert alice.rounds_played == 1
        # Bob: exact title (10) + exact artist (5) = 15.
        assert bob.score == 15
        assert bob.round_scores == [15]
        assert bob.rounds_played == 1

    async def test_rejected_near_miss_scores_without_partial(self):
        gs = make_game_state()
        await self._setup_near_miss(gs)
        await gs.end_round()
        # No vote and no override -> default reject on resolve.
        await gs.resolve_title_artist_if_pending()

        alice = gs.players["Alice"]
        # Rejected title (0) + exact artist (5) = 5.
        assert alice.score == 5
        assert alice.round_scores == [5]
        assert alice.rounds_played == 1

    async def test_vote_accept_increases_leaderboard(self):
        gs = make_game_state()
        await self._setup_near_miss(gs)
        await gs.end_round()
        # Bob votes 👍 on Alice's title near-miss (majority of one).
        gs.register_title_artist_vote("Bob", "Alice:title", True)
        await gs.resolve_title_artist_if_pending()

        alice = gs.players["Alice"]
        assert alice.score == 10
        assert alice.round_scores == [10]
        assert alice.rounds_played == 1

    async def test_timeout_applies_accepted_points(self):
        gs = make_game_state()
        await self._setup_near_miss(gs)
        gs.set_title_artist_override("Alice:title", True)
        import custom_components.beatify.game.state_vote_window as state_mod

        orig = state_mod.TITLE_ARTIST_VOTE_WINDOW_SECONDS
        state_mod.TITLE_ARTIST_VOTE_WINDOW_SECONDS = 0
        try:
            await gs.end_round()
            await asyncio.sleep(0.05)
        finally:
            state_mod.TITLE_ARTIST_VOTE_WINDOW_SECONDS = orig

        alice = gs.players["Alice"]
        assert alice.score == 10
        assert alice.round_scores == [10]
        assert alice.rounds_played == 1

    async def test_no_near_miss_scores_in_main_loop(self):
        """Immediate-resolve path scores during end_round (no window)."""
        gs = make_game_state()
        await _start_round(gs)
        await gs.start_round()
        gs._challenge_manager.submit_title_artist_guess(
            "Alice", gs.current_song["title"], gs.current_song["artist"], 1.0
        )
        gs._challenge_manager.submit_title_artist_guess(
            "Bob", gs.current_song["title"], gs.current_song["artist"], 1.0
        )
        for p in gs.players.values():
            p.submitted = True
        await gs.end_round()
        assert gs.is_title_artist_voting_open() is False
        for p in gs.players.values():
            # Exact title (10) + exact artist (5) = 15, scored once.
            assert p.score == 15
            assert p.round_scores == [15]
            assert p.rounds_played == 1
        gs._cancel_auto_advance()

    async def test_resolve_is_idempotent(self):
        """A double finalize (host-advance + late timer) must not double-count."""
        gs = make_game_state()
        await self._setup_near_miss(gs)
        await gs.end_round()
        gs.set_title_artist_override("Alice:title", True)
        await gs.resolve_title_artist_if_pending()
        # Second call is a guarded no-op — scores must not change.
        await gs.resolve_title_artist_if_pending()
        await gs._finalize_title_artist_window()

        alice = gs.players["Alice"]
        assert alice.score == 10
        assert alice.round_scores == [10]
        assert alice.rounds_played == 1


class TestVoteWindowFlagReset:
    """#1359: the vote-window flags must not leak past a game's lifecycle.

    These flags live on GameState (not in GameStateConfig), so a force-end
    while the 30s window is open used to leak _title_artist_voting_open=True
    into the next game — which then lost REVEAL auto-advance and double-scored
    a round on host-advance. end_game / create_game / rematch must reset them.
    """

    async def _open_window(self, gs):
        """Drive a title/artist game into an OPEN vote window in REVEAL."""
        await _start_round(gs)
        await gs.start_round()
        gs._challenge_manager.submit_title_artist_guess(
            "Alice", "Real Mismatch", gs.current_song["artist"], 1.0
        )
        gs._challenge_manager.submit_title_artist_guess(
            "Bob", gs.current_song["title"], gs.current_song["artist"], 1.0
        )
        for p in gs.players.values():
            p.submitted = True
        await gs.end_round()
        assert gs.is_title_artist_voting_open() is True

    async def test_end_game_clears_open_vote_flag(self):
        """Force-ending while the window is open must reset the flag."""
        gs = make_game_state()
        await self._open_window(gs)
        # Admin force-ends the game mid vote-window.
        await gs.end_game()
        assert gs._title_artist_voting_open is False
        assert gs._title_artist_vote_deadline is None

    async def test_create_game_clears_leaked_vote_flag(self):
        """A leaked flag from a prior game must be cleared by create_game.

        Simulates the pre-fix leak directly (flag stuck True with no reset)
        and asserts the next create_game scrubs it, so the new game keeps its
        REVEAL auto-advance and never double-scores.
        """
        gs = make_game_state()
        # Pretend a prior game leaked the flag.
        gs._title_artist_voting_open = True
        gs._title_artist_vote_deadline = 123.0
        gs.create_game(
            playlists=["t.json"],
            songs=_ta_songs(3),
            media_player="media_player.x",
            base_url="http://h",
            title_artist_mode=False,  # plain year mode — must NOT inherit the flag
        )
        assert gs._title_artist_voting_open is False
        assert gs._title_artist_vote_deadline is None

    async def test_cancelled_window_task_clears_flag(self):
        """Cancelling the window task (defense in depth) clears the flag."""
        gs = make_game_state()
        await self._open_window(gs)
        # Let the freshly-created window task actually enter its try-block so
        # the cancellation lands inside the except handler (not before start).
        await asyncio.sleep(0)
        # Cancel the pending window task exactly as end_game/next_round do.
        task = gs._auto_advance_task
        gs._cancel_auto_advance()
        if task is not None:
            try:
                await task
            except asyncio.CancelledError:
                pass
        assert gs._title_artist_voting_open is False
        assert gs._title_artist_vote_deadline is None

    async def test_next_year_game_keeps_reveal_auto_advance(self):
        """End-to-end: after a force-end mid-window, a plain year game still
        schedules REVEAL auto-advance (the leak previously disabled it)."""
        gs = make_game_state()
        await self._open_window(gs)
        await gs.end_game()
        # Start a fresh plain year-mode game.
        gs._media_player_service = _stub_media_service()
        gs.create_game(
            playlists=["t.json"],
            songs=make_songs(3),
            media_player="media_player.x",
            base_url="http://h",
            title_artist_mode=False,
            reveal_auto_advance=5,
        )
        gs.platform = "music_assistant"
        gs.add_player("Alice", MagicMock())
        for p in gs.players.values():
            p.connected = True
        # The reveal-advance scheduler short-circuits when voting_open is True;
        # with the flag cleared it must run and arm an auto-advance task.
        assert gs._title_artist_voting_open is False
        await gs.start_round()
        for p in gs.players.values():
            p.submitted = True
        await gs.end_round()
        assert gs.phase == GamePhase.REVEAL
        assert gs._auto_advance_task is not None
        gs._cancel_auto_advance()
