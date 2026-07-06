"""Finale mechanic tests (Issue #1725).

Two opt-in, default-off mechanics layered onto the existing round flow:

* **Finale ×2** (``finale_double_enabled``) — on the last round each player's
  round score is doubled before it is committed. Off / non-last-round scoring
  must stay byte-for-byte unchanged.
* **Finale sudden-death tiebreaker** (``finale_tiebreaker_enabled``) — when the
  game would end on a tie for first with unplayed songs left, a one-round
  playoff runs among ONLY the tied leaders (reusing the #1472 ``eliminated``
  machinery) instead of declaring a shared winner.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from custom_components.beatify.game.serializers import GameStateSerializer
from custom_components.beatify.game.state import (
    FINALE_PLAYOFF_MAX_ROUNDS,
    GamePhase,
)
from tests.conftest import make_game_state, make_songs


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _stub_media_service() -> MagicMock:
    svc = MagicMock()
    svc.is_available.return_value = True
    svc.play_song = AsyncMock(return_value=True)
    svc.verify_responsive = AsyncMock(return_value=(True, None))
    svc.restore_volume = AsyncMock(return_value=True)
    svc.stop = AsyncMock(return_value=True)
    return svc


def _add_live_player(gs, name: str) -> None:
    ws = MagicMock()
    ws.closed = False
    gs.add_player(name, ws)
    gs.get_player(name).connected = True


def _make_game(names, *, songs=5, **create_kwargs):
    gs = make_game_state()
    gs.create_game(
        playlists=["t.json"],
        songs=make_songs(songs),
        media_player="media_player.x",
        base_url="http://h",
        **create_kwargs,
    )
    gs._media_player_service = _stub_media_service()
    gs.platform = "music_assistant"
    for n in names:
        _add_live_player(gs, n)
    return gs


def _score_one(*, finale_double, last_round, guess=1980, correct=1980):
    """Score a single submitted player and return their (round_score, score)."""
    gs = _make_game(["Alice"])
    gs.finale_double_enabled = finale_double
    gs.last_round = last_round
    gs.round_start_time = None  # use round_duration fallback (no speed skew)
    p = gs.get_player("Alice")
    p.current_guess = guess
    p.submitted = True
    p.submission_time = None
    gs._score_all_players(correct, list(gs.players.values()))
    return p.round_score, p.score


# ---------------------------------------------------------------------------
# Part 1 — Finale ×2
# ---------------------------------------------------------------------------


class TestFinaleDouble:
    def test_doubles_on_last_round_when_enabled(self):
        base_rs, base_score = _score_one(finale_double=False, last_round=True)
        rs, score = _score_one(finale_double=True, last_round=True)
        assert base_rs > 0  # sanity: an exact guess scores
        assert rs == 2 * base_rs
        # The extra half lands on the cumulative score too.
        assert score == base_score + base_rs

    def test_not_doubled_when_disabled(self):
        base_rs, base_score = _score_one(finale_double=False, last_round=True)
        rs, score = _score_one(finale_double=False, last_round=True)
        assert rs == base_rs
        assert score == base_score

    def test_not_doubled_off_last_round(self):
        base_rs, base_score = _score_one(finale_double=False, last_round=False)
        rs, score = _score_one(finale_double=True, last_round=False)
        # Enabled but NOT the last round → identical to normal scoring.
        assert rs == base_rs
        assert score == base_score

    def test_missed_round_no_change(self):
        # A player who did not submit has round_score 0 → doubling is a no-op
        # (no negative, no phantom points).
        gs = _make_game(["Alice"])
        gs.finale_double_enabled = True
        gs.last_round = True
        p = gs.get_player("Alice")
        p.submitted = False
        gs._score_all_players(1980, list(gs.players.values()))
        assert p.round_score == 0
        assert p.score == 0

    def test_round_scores_history_reflects_double(self):
        gs = _make_game(["Alice"])
        gs.finale_double_enabled = True
        gs.last_round = True
        gs.round_start_time = None
        p = gs.get_player("Alice")
        p.current_guess = 1980
        p.submitted = True
        gs._score_all_players(1980, list(gs.players.values()))
        assert p.round_scores[-1] == p.round_score

    def test_serializer_flag_only_on_enabled_last_round(self):
        gs = _make_game(["Alice", "Bob"], finale_double_enabled=True)
        gs._set_phase(GamePhase.PLAYING)
        gs.last_round = True
        state = GameStateSerializer.serialize(gs)
        assert state["finale_double_active"] is True
        assert state["finale_double_enabled"] is True

        gs.last_round = False
        state = GameStateSerializer.serialize(gs)
        assert state["finale_double_active"] is False

    def test_serializer_flag_off_when_disabled(self):
        gs = _make_game(["Alice", "Bob"], finale_double_enabled=False)
        gs._set_phase(GamePhase.PLAYING)
        gs.last_round = True
        state = GameStateSerializer.serialize(gs)
        assert state["finale_double_active"] is False

    def test_closest_wins_interaction(self):
        # Finale ×2 runs before Closest-Wins zeroing: the closest player keeps
        # the doubled score, the non-closest is zeroed back out cleanly.
        gs = _make_game(["Alice", "Bob"], closest_wins_mode=True)
        gs.finale_double_enabled = True
        gs.last_round = True
        gs.round_start_time = None
        alice = gs.get_player("Alice")
        bob = gs.get_player("Bob")
        alice.current_guess = 1980  # exact → closest
        bob.current_guess = 1990  # far off → zeroed by closest-wins
        for p in (alice, bob):
            p.submitted = True
        gs._score_round(1980)
        assert alice.round_score > 0  # closest keeps doubled points
        assert bob.round_score == 0  # non-closest zeroed
        assert bob.round_scores[-1] == 0


# ---------------------------------------------------------------------------
# Part 2 — Finale sudden-death tiebreaker
# ---------------------------------------------------------------------------


def _reveal_with_scores(gs, scores: dict[str, int]) -> None:
    """Drive a game into REVEAL with the given cumulative scores."""
    for name, sc in scores.items():
        gs.get_player(name).score = sc
    if gs.phase != GamePhase.PLAYING:
        gs._set_phase(GamePhase.PLAYING)
    gs._set_phase(GamePhase.REVEAL)


class TestFinaleTiebreaker:
    async def test_triggers_on_tie_with_songs_remaining(self):
        gs = _make_game(
            ["Alice", "Bob", "Carol"], songs=5, finale_tiebreaker_enabled=True
        )
        await gs.start_round()  # round 1, 4 songs left
        _reveal_with_scores(gs, {"Alice": 10, "Bob": 10, "Carol": 4})

        started = await gs.maybe_start_finale_playoff()

        assert started is True
        assert gs.phase == GamePhase.PLAYING  # playoff round is live
        assert gs._finale_playoff_active is True
        assert gs._finale_playoff_rounds == 1
        # Only the non-tied player is frozen out.
        assert gs.get_player("Carol").eliminated is True
        assert gs.get_player("Alice").eliminated is False
        assert gs.get_player("Bob").eliminated is False
        # Not mislabelled as a Sudden-Death cut.
        assert gs.get_player("Carol").eliminated_round is None

    async def test_no_trigger_on_clear_winner(self):
        gs = _make_game(["Alice", "Bob"], songs=5, finale_tiebreaker_enabled=True)
        await gs.start_round()
        _reveal_with_scores(gs, {"Alice": 12, "Bob": 5})
        assert await gs.maybe_start_finale_playoff() is False
        assert gs.get_player("Bob").eliminated is False

    async def test_no_trigger_when_disabled(self):
        gs = _make_game(["Alice", "Bob"], songs=5, finale_tiebreaker_enabled=False)
        await gs.start_round()
        _reveal_with_scores(gs, {"Alice": 10, "Bob": 10})
        assert await gs.maybe_start_finale_playoff() is False

    async def test_no_trigger_when_no_songs_remain(self):
        # One-song game: after round 1 the playlist is exhausted (0 remaining).
        gs = _make_game(["Alice", "Bob"], songs=1, finale_tiebreaker_enabled=True)
        await gs.start_round()
        assert gs.songs_remaining == 0
        _reveal_with_scores(gs, {"Alice": 10, "Bob": 10})
        assert await gs.maybe_start_finale_playoff() is False
        assert gs.get_player("Alice").eliminated is False

    async def test_no_trigger_outside_reveal(self):
        gs = _make_game(["Alice", "Bob"], songs=5, finale_tiebreaker_enabled=True)
        await gs.start_round()  # phase PLAYING
        gs.get_player("Alice").score = 10
        gs.get_player("Bob").score = 10
        assert gs.phase == GamePhase.PLAYING
        assert await gs.maybe_start_finale_playoff() is False

    async def test_recursion_cap_falls_back_to_shared_winner(self):
        gs = _make_game(["Alice", "Bob"], songs=10, finale_tiebreaker_enabled=True)
        await gs.start_round()
        _reveal_with_scores(gs, {"Alice": 10, "Bob": 10})
        gs._finale_playoff_rounds = FINALE_PLAYOFF_MAX_ROUNDS  # cap already hit
        assert await gs.maybe_start_finale_playoff() is False
        # No further elimination once capped.
        assert gs.get_player("Alice").eliminated is False
        assert gs.get_player("Bob").eliminated is False

    async def test_resolved_tie_ends_normally(self):
        gs = _make_game(
            ["Alice", "Bob", "Carol"], songs=8, finale_tiebreaker_enabled=True
        )
        await gs.start_round()
        _reveal_with_scores(gs, {"Alice": 10, "Bob": 10, "Carol": 3})
        assert await gs.maybe_start_finale_playoff() is True  # playoff 1

        # Playoff round diverges the tie → a single leader.
        gs.get_player("Alice").score = 15
        gs.get_player("Bob").score = 10
        _reveal_with_scores(gs, {"Alice": 15, "Bob": 10, "Carol": 3})
        # Now a clear winner → no further playoff.
        assert await gs.maybe_start_finale_playoff() is False

    async def test_sudden_death_survivors_drive_the_tie(self):
        # With Sudden Death also on, compute_winners ranks survivors first, so
        # the playoff runs among tied *survivors*, ignoring a higher-scoring but
        # already-eliminated player.
        gs = _make_game(
            ["Alice", "Bob", "Carol"],
            songs=6,
            sudden_death_mode=True,
            finale_tiebreaker_enabled=True,
        )
        await gs.start_round()
        # Carol was cut earlier despite a high raw score.
        carol = gs.get_player("Carol")
        carol.eliminated = True
        carol.eliminated_round = 1
        carol.score = 99
        _reveal_with_scores(gs, {"Alice": 10, "Bob": 10, "Carol": 99})

        started = await gs.maybe_start_finale_playoff()
        assert started is True
        assert gs.get_player("Alice").eliminated is False
        assert gs.get_player("Bob").eliminated is False
        assert carol.eliminated is True  # stays out


# ---------------------------------------------------------------------------
# Plumbing — create_game / rematch thread both opt-in flags
# ---------------------------------------------------------------------------


class TestFinalePlumbing:
    def test_create_game_defaults_off(self):
        gs = _make_game(["Alice"])
        assert gs.finale_double_enabled is False
        assert gs.finale_tiebreaker_enabled is False
        assert gs._finale_playoff_rounds == 0
        assert gs._finale_playoff_active is False

    def test_create_game_sets_flags(self):
        gs = _make_game(
            ["Alice"],
            finale_double_enabled=True,
            finale_tiebreaker_enabled=True,
        )
        assert gs.finale_double_enabled is True
        assert gs.finale_tiebreaker_enabled is True

    def test_rematch_preserves_flags_and_resets_counters(self):
        gs = _make_game(
            ["Alice", "Bob"],
            finale_double_enabled=True,
            finale_tiebreaker_enabled=True,
        )
        gs._finale_playoff_rounds = 3
        gs._finale_playoff_active = True
        gs.rematch_game()
        assert gs.finale_double_enabled is True
        assert gs.finale_tiebreaker_enabled is True
        assert gs._finale_playoff_rounds == 0
        assert gs._finale_playoff_active is False
