"""Sudden Death hardening regression tests (#1747/#1748/#1750/#1751/#1752/#1755).

These guard the six elimination-logic findings from the Fable re-review round 2:

* #1747 — deferred title/artist scoring must defer the SD cut too, so the
  RIGHT (lowest resolved) player is eliminated, not a stale-score victim.
* #1748 — an eliminated player is gated server-side (no submit / steal) and is
  never scored, a steal target, or a closest-wins participant.
* #1750 — round-delta ties break by accuracy first, not raw submission speed.
* #1751 — the elimination metric is the full round delta (incl. bonuses).
* #1752 — a mid-round joiner gets one grace round (not eliminable that round).
* #1755 — an unattended title/artist near-miss round re-arms the song-end
  auto-advance after the vote window expires (never-stall invariant #1012).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

from custom_components.beatify.const import DOMAIN, ERR_ELIMINATED
from custom_components.beatify.game.scoring import ScoringService
from custom_components.beatify.game.state import GamePhase
from tests.conftest import make_game_state, make_songs

from custom_components.beatify.server.websocket import (  # isort: skip
    BeatifyWebSocketHandler,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _ta_songs(n: int = 3) -> list[dict]:
    songs = make_songs(n)
    for i, s in enumerate(songs):
        s["title"] = f"Real Title {i}"
        s["artist"] = f"Real Artist {i}"
    return songs


def _stub_media_service() -> MagicMock:
    svc = MagicMock()
    svc.is_available.return_value = True
    svc.play_song = AsyncMock(return_value=True)
    svc.verify_responsive = AsyncMock(return_value=(True, None))
    svc.restore_volume = AsyncMock(return_value=True)
    return svc


def _add_live_player(gs, name: str) -> None:
    ws = MagicMock()
    ws.closed = False
    gs.add_player(name, ws)
    gs.get_player(name).connected = True


async def _start_ta_sd_game(gs, names, *, sudden_death=True):
    gs.create_game(
        playlists=["t.json"],
        songs=_ta_songs(3),
        media_player="media_player.x",
        base_url="http://h",
        title_artist_mode=True,
        sudden_death_mode=sudden_death,
    )
    gs._media_player_service = _stub_media_service()
    gs.platform = "music_assistant"
    for n in names:
        _add_live_player(gs, n)
    await gs.start_round()


# ---------------------------------------------------------------------------
# #1747 — deferred title/artist scoring must defer the elimination too
# ---------------------------------------------------------------------------


class TestDeferredEliminationTitleArtist:
    async def _drive_near_miss_round(self, gs):
        """Alice: rejected near-miss title + wrong artist (resolves to 0).

        Bob + Carol: exact/exact (15 each). Alice submitted FIRST (fastest),
        Carol submitted LAST (slowest) — so the pre-fix stale-score path (all
        round_score 0 at end_round) would wrongly eliminate the slowest
        *submitter* Carol, while the resolved scores make Alice the true lowest.
        """
        await _start_ta_sd_game(gs, ("Alice", "Bob", "Carol"))
        gs.round = 2  # SD only eliminates from round 2 on
        title = gs.current_song["title"]
        artist = gs.current_song["artist"]
        # Alice: near-miss title ("Real Mismatch" shares the stem) + wrong artist.
        gs._challenge_manager.submit_title_artist_guess(
            "Alice", "Real Mismatch", "Totally Different Band", 1.0
        )
        gs._challenge_manager.submit_title_artist_guess("Bob", title, artist, 2.0)
        gs._challenge_manager.submit_title_artist_guess("Carol", title, artist, 5.0)
        for name, t in (("Alice", 1.0), ("Bob", 2.0), ("Carol", 5.0)):
            p = gs.get_player(name)
            p.submitted = True
            p.submission_time = t

    async def test_no_elimination_while_window_open(self):
        """The cut must NOT happen at end_round while scoring is deferred."""
        gs = make_game_state()
        await self._drive_near_miss_round(gs)
        await gs.end_round()
        assert gs.is_title_artist_voting_open() is True
        # Deferred: nobody scored, nobody eliminated yet.
        assert all(not p.eliminated for p in gs.players.values())
        gs._cancel_auto_advance()

    async def test_deferred_path_eliminates_correct_player(self):
        """After the window resolves, the lowest *resolved* scorer is out."""
        gs = make_game_state()
        await self._drive_near_miss_round(gs)
        await gs.end_round()
        # Host advances -> finalize resolves near-misses, scores, then eliminates.
        await gs.resolve_title_artist_if_pending()

        alice = gs.get_player("Alice")
        assert alice.eliminated is True
        assert alice.eliminated_round == 2
        # The slowest *submitter* (pre-fix victim) survives — accuracy/score won.
        assert gs.get_player("Bob").eliminated is False
        assert gs.get_player("Carol").eliminated is False

    async def test_non_deferred_ta_still_eliminates_inline(self):
        """With no near-miss the immediate-resolve path eliminates at end_round."""
        gs = make_game_state()
        await _start_ta_sd_game(gs, ("Alice", "Bob", "Carol"))
        gs.round = 2
        title = gs.current_song["title"]
        artist = gs.current_song["artist"]
        gs._challenge_manager.submit_title_artist_guess("Alice", title, artist, 1.0)
        gs._challenge_manager.submit_title_artist_guess("Bob", title, artist, 1.0)
        for name in ("Alice", "Bob"):
            gs.get_player(name).submitted = True
            gs.get_player(name).submission_time = 1.0
        # Carol never submits -> lowest, no near-miss -> immediate resolve.
        await gs.end_round()
        assert gs.is_title_artist_voting_open() is False
        assert gs.get_player("Carol").eliminated is True
        assert gs.get_player("Carol").eliminated_round == 2
        assert gs.get_player("Alice").eliminated is False
        gs._cancel_auto_advance()


# ---------------------------------------------------------------------------
# #1748 — eliminated players gated server-side and never scored
# ---------------------------------------------------------------------------


def _make_year_handler_game(sudden_death=True):
    mock_hass = MagicMock()
    gs = make_game_state()
    gs.create_game(
        playlists=["t.json"],
        songs=make_songs(3),
        media_player="media_player.x",
        base_url="http://h",
        sudden_death_mode=sudden_death,
    )
    gs._media_player_service = _stub_media_service()
    gs.platform = "music_assistant"
    mock_hass.data = {DOMAIN: {"game": gs}}
    handler = BeatifyWebSocketHandler(mock_hass)
    handler.broadcast_state = AsyncMock()
    handler.broadcast = AsyncMock()
    handler.debounced_broadcast_state = AsyncMock()
    return handler, gs


def _ws() -> AsyncMock:
    ws = AsyncMock()
    ws.send_json = AsyncMock()
    ws.closed = False
    ws.close = AsyncMock()
    return ws


class TestEliminatedGatedServerSide:
    async def test_eliminated_submit_rejected(self):
        handler, gs = _make_year_handler_game()
        ws = _ws()
        gs.add_player("Alice", ws)
        gs.get_player("Alice").connected = True
        await gs.start_round()
        gs.get_player("Alice").eliminated = True

        await handler._handle_message(ws, {"type": "submit", "year": 1985})

        ws.send_json.assert_awaited()
        codes = [
            c.args[0].get("code")
            for c in ws.send_json.await_args_list
            if isinstance(c.args[0], dict)
        ]
        assert ERR_ELIMINATED in codes
        # The rejected guess must not have registered.
        assert gs.get_player("Alice").submitted is False

    async def test_eliminated_steal_rejected(self):
        handler, gs = _make_year_handler_game()
        ws = _ws()
        gs.add_player("Alice", ws)
        gs.get_player("Alice").connected = True
        await gs.start_round()
        gs.get_player("Alice").eliminated = True

        await handler._handle_message(ws, {"type": "steal", "target": "Someone"})

        codes = [
            c.args[0].get("code")
            for c in ws.send_json.await_args_list
            if isinstance(c.args[0], dict)
        ]
        assert ERR_ELIMINATED in codes

    def test_eliminated_not_scored(self):
        gs = make_game_state()
        gs.create_game(
            playlists=["t.json"],
            songs=make_songs(3),
            media_player="media_player.x",
            base_url="http://h",
            sudden_death_mode=True,
        )
        _add_live_player(gs, "Alice")
        _add_live_player(gs, "Bob")
        alice = gs.get_player("Alice")
        bob = gs.get_player("Bob")
        alice.eliminated = True
        alice.score = 42  # frozen at elimination
        # Both "submit" a perfect guess for year 1990.
        for p in (alice, bob):
            p.submitted = True
            p.current_guess = 1990
            p.submission_time = 1.0
        gs._score_all_players(1990, list(gs.players.values()))
        # Eliminated Alice's totals are frozen; Bob scored normally.
        assert alice.score == 42
        assert alice.round_score == 0
        assert bob.score > 0

    def test_eliminated_excluded_from_steal_targets(self):
        gs = make_game_state()
        gs.create_game(
            playlists=["t.json"],
            songs=make_songs(3),
            media_player="media_player.x",
            base_url="http://h",
            sudden_death_mode=True,
        )
        _add_live_player(gs, "Alice")
        _add_live_player(gs, "Bob")
        _add_live_player(gs, "Carol")
        for n in ("Bob", "Carol"):
            gs.get_player(n).submitted = True
            gs.get_player(n).current_guess = 1985
        gs.get_player("Carol").eliminated = True
        targets = gs.get_steal_targets("Alice")
        assert "Bob" in targets
        assert "Carol" not in targets

    def test_eliminated_excluded_from_closest_wins(self):
        gs = make_game_state()
        _add_live_player(gs, "Alice")
        _add_live_player(gs, "Bob")
        alice = gs.get_player("Alice")
        bob = gs.get_player("Bob")
        # Eliminated Alice sits exactly on the year; survivor Bob is 5 off.
        alice.submitted = True
        alice.current_guess = 1990
        alice.round_score = 10
        alice.eliminated = True
        bob.submitted = True
        bob.current_guess = 1995
        bob.round_score = 6
        ScoringService.apply_closest_wins(list(gs.players.values()), 1990)
        # Alice is OUT of the closest calc, so Bob (the only live submitter) is
        # "closest" and keeps his points instead of being zeroed by a ghost.
        assert bob.round_score == 6


# ---------------------------------------------------------------------------
# Unit-level elimination logic (#1750/#1751/#1752)
# ---------------------------------------------------------------------------


class TestEliminationLogic:
    def _fresh(self):
        gs = make_game_state()
        gs.create_game(
            playlists=["t.json"],
            songs=make_songs(5),
            media_player="media_player.x",
            base_url="http://h",
            sudden_death_mode=True,
        )
        for n in ("Alice", "Bob", "Carol", "Dave"):
            _add_live_player(gs, n)
        return gs

    def test_tie_break_prefers_accuracy_over_speed(self):
        """#1750: among a round-delta tie, the least accurate player is cut,
        even if they submitted fastest."""
        gs = self._fresh()
        gs.round = 2
        alice = gs.get_player("Alice")
        bob = gs.get_player("Bob")
        # Alice + Bob tie for last at round_score 0; Carol/Dave clearly ahead.
        for n, sc in (("Alice", 0), ("Bob", 0), ("Carol", 5), ("Dave", 5)):
            gs.get_player(n).round_score = sc
        # Alice: 1 year off (accurate), pondered 10s. Bob: 40 off, tapped at 1s.
        alice.years_off, alice.base_score, alice.submission_time = 1, 9, 10.0
        bob.years_off, bob.base_score, bob.submission_time = 40, 1, 1.0
        eliminated = gs._apply_sudden_death_elimination()
        assert eliminated == ["Bob"]  # accuracy beats raw speed
        assert alice.eliminated is False

    def test_round_bonus_counts_toward_metric(self):
        """#1751: a player who scored 0 on the year but won a bonus is safe."""
        gs = self._fresh()
        gs.round = 3
        for n, sc in (("Alice", 1), ("Bob", 0), ("Carol", 3), ("Dave", 4)):
            gs.get_player(n).round_score = sc
        # Bob's raw round_score is the lowest (0) — but a +5 movie bonus makes his
        # true round delta 5, so Alice (delta 1) is the real lowest.
        gs.get_player("Bob").movie_bonus = 5
        eliminated = gs._apply_sudden_death_elimination()
        assert eliminated == ["Alice"]
        assert gs.get_player("Bob").eliminated is False

    def test_late_joiner_gets_grace_round(self):
        """#1752: a player who joined THIS round is excluded from the cut."""
        gs = self._fresh()
        gs.round = 3
        alice = gs.get_player("Alice")
        alice.joined_round = 3  # joined mid-round 3
        alice.round_score = 0  # missed the round they never played
        alice.submission_time = None
        for n, sc in (("Bob", 5), ("Carol", 6), ("Dave", 7)):
            gs.get_player(n).round_score = sc
            gs.get_player(n).submission_time = 1.0
        eliminated = gs._apply_sudden_death_elimination()
        # Alice would be the lowest, but grace excludes her; Bob is the cut.
        assert eliminated == ["Bob"]
        assert alice.eliminated is False

    def test_late_joiner_eliminable_next_round(self):
        """#1752: grace lasts exactly one round — the joiner is fair game after."""
        gs = self._fresh()
        gs.round = 4
        alice = gs.get_player("Alice")
        alice.joined_round = 3  # joined last round, now fully played round 4
        alice.round_score = 0
        alice.submission_time = None
        for n, sc in (("Bob", 5), ("Carol", 6), ("Dave", 7)):
            gs.get_player(n).round_score = sc
            gs.get_player(n).submission_time = 1.0
        eliminated = gs._apply_sudden_death_elimination()
        assert eliminated == ["Alice"]

    def test_all_fresh_joiners_no_elimination(self):
        """#1752: if every survivor joined this round, nobody is eliminated."""
        gs = self._fresh()
        gs.round = 3
        for n in ("Alice", "Bob", "Carol", "Dave"):
            gs.get_player(n).joined_round = 3
            gs.get_player(n).round_score = 0
        eliminated = gs._apply_sudden_death_elimination()
        assert eliminated == []
        assert all(not p.eliminated for p in gs.players.values())


# ---------------------------------------------------------------------------
# #1755 — unattended title/artist near-miss round re-arms auto-advance
# ---------------------------------------------------------------------------


class TestUnattendedTitleArtistAdvance:
    async def test_natural_expiry_rearms_auto_advance(self):
        """After the vote window expires unattended, the song-end auto-advance
        must be re-armed so the round doesn't park on REVEAL forever."""
        gs = make_game_state()
        await _start_ta_sd_game(gs, ("Alice", "Bob"), sudden_death=False)
        title = gs.current_song["title"]
        artist = gs.current_song["artist"]
        gs._challenge_manager.submit_title_artist_guess(
            "Alice", "Real Mismatch", artist, 1.0
        )
        gs._challenge_manager.submit_title_artist_guess("Bob", title, artist, 1.0)
        for p in gs.players.values():
            p.submitted = True
            p.submission_time = 1.0

        # Spy on the re-arm so the assertion doesn't depend on the real
        # song-end poll task's timing.
        calls: list[bool] = []
        gs._schedule_song_end_auto_advance = lambda: calls.append(True)  # type: ignore[method-assign]

        import custom_components.beatify.game.state_vote_window as vw_mod

        orig = vw_mod.TITLE_ARTIST_VOTE_WINDOW_SECONDS
        vw_mod.TITLE_ARTIST_VOTE_WINDOW_SECONDS = 0
        try:
            await gs.end_round()
            assert gs.is_title_artist_voting_open() is True
            await asyncio.sleep(0.05)  # let the 0s window task expire
        finally:
            vw_mod.TITLE_ARTIST_VOTE_WINDOW_SECONDS = orig

        assert gs.phase == GamePhase.REVEAL
        assert calls, "song-end auto-advance was not re-armed after vote expiry"
