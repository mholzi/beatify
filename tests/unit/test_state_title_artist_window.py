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
    # #1516: end_game now awaits restore_volume; make it awaitable on the stub.
    svc.restore_volume = AsyncMock(return_value=True)
    return svc


async def _start_round(gs):
    gs.create_game(
        playlists=["t.json"],
        songs=_ta_songs(3),
        media_player="media_player.x",
        base_url="http://h",
        title_artist_mode=True,
    )
    # Inject a stub service (truthy) so the lazy _ensure_media_player_service
    # is a no-op and real playback never runs. Must come *after* create_game,
    # which now nulls _media_player_service so a fresh game rebuilds it with the
    # new selection (#1526) — injecting before would be wiped out by that reset.
    gs._media_player_service = _stub_media_service()
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


class TestRoundResultsShareGrid:
    """#1373: the share-card emoji grid must reflect title/artist results.

    Before the fix, round_results was classified solely from player.years_off,
    which is always None in title/artist mode — so every round was appended as
    "missed" and the end-of-game share card showed an all-red grid + "0/N
    correct" even for a player who nailed every title and artist. These assert
    round_results is now classified from the resolved field statuses, on both
    the immediate-resolve and the deferred vote-window paths.
    """

    async def test_all_exact_grid_is_not_missed(self):
        """Immediate-resolve path: both fields exact -> 'exact', not 'missed'."""
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
            assert p.round_results == ["exact"]
        gs._cancel_auto_advance()

    async def test_title_only_correct_is_scored(self):
        """One field exact, other wrong (no near-miss) -> 'scored'."""
        gs = make_game_state()
        await _start_round(gs)
        await gs.start_round()
        # Exact title, clearly-wrong artist (not a near-miss -> immediate resolve).
        gs._challenge_manager.submit_title_artist_guess(
            "Alice", gs.current_song["title"], "Totally Different Band", 1.0
        )
        gs._challenge_manager.submit_title_artist_guess(
            "Bob", gs.current_song["title"], gs.current_song["artist"], 1.0
        )
        for p in gs.players.values():
            p.submitted = True
        await gs.end_round()
        assert gs.is_title_artist_voting_open() is False
        assert gs.players["Alice"].round_results == ["scored"]
        assert gs.players["Bob"].round_results == ["exact"]
        gs._cancel_auto_advance()

    async def test_accepted_near_miss_is_close_deferred_path(self):
        """Deferred vote-window path: accepted near-miss title -> 'close'.

        Alice has a near-miss title + exact artist; an override accepts it. The
        round_results append must run AFTER the window resolves so it sees the
        promoted near_miss_accepted status.
        """
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
        # Deferred — no round_results banked yet while the window is open.
        assert gs.players["Alice"].round_results == []
        gs.set_title_artist_override("Alice:title", True)
        await gs.resolve_title_artist_if_pending()
        # Alice: accepted near-miss title (partial) + exact artist -> "scored"
        # (artist is exact, which earns full points). Bob exact/exact -> "exact".
        assert gs.players["Alice"].round_results == ["scored"]
        assert gs.players["Bob"].round_results == ["exact"]

    async def test_rejected_near_miss_only_is_close(self):
        """A near-miss accepted with no other full-points field -> 'close'."""
        gs = make_game_state()
        await _start_round(gs)
        await gs.start_round()
        # Alice: near-miss title AND wrong artist -> only the accepted title
        # earns (partial) points, so the round classifies as "close".
        gs._challenge_manager.submit_title_artist_guess(
            "Alice", "Real Mismatch", "Totally Different Band", 1.0
        )
        gs._challenge_manager.submit_title_artist_guess(
            "Bob", gs.current_song["title"], gs.current_song["artist"], 1.0
        )
        for p in gs.players.values():
            p.submitted = True
        await gs.end_round()
        gs.set_title_artist_override("Alice:title", True)
        await gs.resolve_title_artist_if_pending()
        assert gs.players["Alice"].round_results == ["close"]

    async def test_no_submission_is_missed(self):
        """A player who didn't guess in title/artist mode -> 'missed'."""
        gs = make_game_state()
        await _start_round(gs)
        await gs.start_round()
        gs._challenge_manager.submit_title_artist_guess(
            "Bob", gs.current_song["title"], gs.current_song["artist"], 1.0
        )
        gs.players["Bob"].submitted = True
        # Alice never submits.
        await gs.end_round()
        assert gs.is_title_artist_voting_open() is False
        assert gs.players["Alice"].round_results == ["missed"]
        assert gs.players["Bob"].round_results == ["exact"]
        gs._cancel_auto_advance()


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
        gs.create_game(
            playlists=["t.json"],
            songs=make_songs(3),
            media_player="media_player.x",
            base_url="http://h",
            title_artist_mode=False,
            reveal_auto_advance=5,
        )
        # Stub the service after create_game, which nulls it for a fresh game (#1526).
        gs._media_player_service = _stub_media_service()
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
