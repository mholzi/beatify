"""Round-advance / connection serialization regression tests.

Covers the concurrent round-advance + admin-connection bugs found via Fable
multi-agent review (2026-07-05):

* #1697 — ``start_round`` is serialized behind ``_round_start_lock`` so a manual
  ``next_round`` and the REVEAL auto-advance cannot double-advance the round.
* #1698 — ``admin_end_game`` resolves an open title/artist vote window before
  finalizing, so the last round's scores aren't lost.
* #1702 — two admin-capable sockets both driving ``next_round`` on the final
  round record the game exactly once (idempotent per ``game_id``).
* #1703 — a pending admin-disconnect pause task is cancelled before being
  overwritten and on rematch, so it can't pause a fresh lobby.
"""

from __future__ import annotations

import asyncio
import functools
from unittest.mock import AsyncMock, MagicMock

import pytest

import custom_components.beatify.game.state_auto_advance as auto_advance_mod
from custom_components.beatify.const import DOMAIN
from custom_components.beatify.game.state import GamePhase
from custom_components.beatify.server.ws_handlers import (
    admin_end_game,
    admin_next_round,
    admin_rematch_game,
)
from custom_components.beatify.server.ws_handlers.admin import _finalize_and_end
from tests.conftest import make_game_state
from tests.unit.test_websocket import _make_handler_and_game, _make_ws


# ---------------------------------------------------------------------------
# #1697 — start_round serialized behind _round_start_lock
# ---------------------------------------------------------------------------


class TestRoundStartLock:
    async def test_lock_prevents_double_start_round(self):
        """Two concurrent start_round() calls from REVEAL run the real
        orchestration once; the race loser no-ops (returns True) instead of
        pulling a second song / double-incrementing the round."""
        state = make_game_state()
        state.phase = GamePhase.REVEAL

        calls: list[int] = []

        async def fake_locked(retry_count: int = 0) -> bool:
            calls.append(retry_count)
            # Hold the lock long enough for the second caller to contend.
            await asyncio.sleep(0.02)
            state.phase = GamePhase.PLAYING
            return True

        state._start_round_locked = fake_locked

        results = await asyncio.gather(state.start_round(), state.start_round())

        # Only ONE real round-start ran.
        assert calls == [0]
        # Both callers report success (the loser is a benign no-op).
        assert results == [True, True]
        assert state.phase == GamePhase.PLAYING

    async def test_single_start_from_reveal_runs(self):
        """Guard is inert for a lone caller: the real orchestration runs."""
        state = make_game_state()
        state.phase = GamePhase.REVEAL

        calls: list[int] = []

        async def fake_locked(retry_count: int = 0) -> bool:
            calls.append(retry_count)
            state.phase = GamePhase.PLAYING
            return True

        state._start_round_locked = fake_locked

        assert await state.start_round() is True
        assert calls == [0]


# ---------------------------------------------------------------------------
# #1698 — admin_end_game resolves an open title/artist vote window
# ---------------------------------------------------------------------------


class TestEndGameResolvesVoteWindow:
    async def test_end_game_resolves_before_finalizing(self):
        handler, game_state, ws = _make_handler_and_game()
        game_state.phase = GamePhase.REVEAL

        order: list[str] = []

        async def _resolve() -> None:
            order.append("resolve")

        async def _advance() -> None:
            order.append("advance")

        game_state.stop_media = AsyncMock()
        game_state.resolve_title_artist_if_pending = AsyncMock(side_effect=_resolve)
        game_state.advance_to_end = AsyncMock(side_effect=_advance)
        game_state.finalize_game = MagicMock(return_value={})
        handler.broadcast_state = AsyncMock()

        await admin_end_game(handler, ws, {"action": "end_game"}, game_state)

        game_state.resolve_title_artist_if_pending.assert_awaited_once()
        game_state.advance_to_end.assert_awaited_once()
        # The vote window is resolved BEFORE the end ceremony snapshots totals.
        assert order == ["resolve", "advance"]


# ---------------------------------------------------------------------------
# #1702 — concurrent last-round next_round records the game once
# ---------------------------------------------------------------------------


class TestConcurrentLastRoundRecordsOnce:
    async def test_two_sockets_record_and_advance_once(self):
        handler, game_state, ws1 = _make_handler_and_game()
        ws2 = _make_ws()
        game_state.phase = GamePhase.REVEAL
        game_state.last_round = True
        game_state.resolve_title_artist_if_pending = AsyncMock()
        game_state.advance_to_end = AsyncMock()
        game_state.finalize_game = MagicMock(return_value={})

        record_game = AsyncMock()
        stats = MagicMock()
        stats.record_game = record_game
        handler.hass.data[DOMAIN]["stats"] = stats
        handler.broadcast_state = AsyncMock()

        # Participant-admin WS and spectator-admin WS both fire next_round on
        # the final round at the same time.
        await asyncio.gather(
            admin_next_round(handler, ws1, {"action": "next_round"}, game_state),
            admin_next_round(handler, ws2, {"action": "next_round"}, game_state),
        )

        record_game.assert_awaited_once()
        game_state.advance_to_end.assert_awaited_once()

    async def test_repeat_call_after_end_does_not_re_record(self):
        """Even sequentially, a second terminal call for the same game_id is a
        no-op (idempotent per game_id)."""
        handler, game_state, ws = _make_handler_and_game()
        game_state.phase = GamePhase.REVEAL
        game_state.last_round = True
        game_state.resolve_title_artist_if_pending = AsyncMock()
        game_state.advance_to_end = AsyncMock()
        game_state.finalize_game = MagicMock(return_value={})

        record_game = AsyncMock()
        stats = MagicMock()
        stats.record_game = record_game
        handler.hass.data[DOMAIN]["stats"] = stats
        handler.broadcast_state = AsyncMock()

        await admin_next_round(handler, ws, {"action": "next_round"}, game_state)
        # advance_to_end is mocked so phase stays REVEAL; a second tap must not
        # re-record the already-claimed game.
        await admin_next_round(handler, ws, {"action": "next_round"}, game_state)

        record_game.assert_awaited_once()
        game_state.advance_to_end.assert_awaited_once()


# ---------------------------------------------------------------------------
# #1703 — pending admin-disconnect pause task cancelled on re-arm + rematch
# ---------------------------------------------------------------------------


class TestAdminDisconnectTaskCleanup:
    async def test_disconnect_cancels_prior_pause_task(self):
        handler, game_state, admin_ws = _make_handler_and_game()
        game_state.add_player("Host", admin_ws)
        game_state.set_admin("Host")
        handler.broadcast_state = AsyncMock()

        async def _never() -> None:
            await asyncio.sleep(3600)

        old_task = asyncio.create_task(_never())
        handler._admin_disconnect_task = old_task

        await handler._handle_disconnect(admin_ws)

        # The superseded task is cancelled instead of leaking.
        with pytest.raises(asyncio.CancelledError):
            await old_task
        # A fresh grace task was armed in its place.
        assert handler._admin_disconnect_task is not None
        assert handler._admin_disconnect_task is not old_task

        # Cleanup: cancel the freshly-armed task so it doesn't dangle.
        handler._admin_disconnect_task.cancel()

    async def test_rematch_cleans_up_pending_tasks(self):
        handler, game_state, ws = _make_handler_and_game()
        game_state.phase = GamePhase.END
        handler.cleanup_game_tasks = AsyncMock()
        game_state.announce_rematch = AsyncMock()
        handler.broadcast = AsyncMock()
        handler.broadcast_state = AsyncMock()

        await admin_rematch_game(handler, ws, {"action": "rematch_game"}, game_state)

        # rematch must cancel any pending admin-disconnect pause task so the
        # grace timer can't pause the brand-new lobby.
        handler.cleanup_game_tasks.assert_awaited_once()


# ---------------------------------------------------------------------------
# #1753 — unattended REVEAL auto-advance final round shares the game-end gate
# ---------------------------------------------------------------------------


def _wire_game_end(handler, game_state) -> None:
    """Wire the terminal game-end callback exactly like setup does."""
    game_state.set_game_end_callback(
        functools.partial(_finalize_and_end, handler, game_state)
    )


def _stub_terminal_game(handler, game_state) -> AsyncMock:
    """Common stubs for the final-round terminal path; returns record_game mock."""
    game_state.resolve_title_artist_if_pending = AsyncMock()
    game_state.advance_to_end = AsyncMock()
    game_state.finalize_game = MagicMock(return_value={})
    record_game = AsyncMock()
    stats = MagicMock()
    stats.record_game = record_game
    handler.hass.data[DOMAIN]["stats"] = stats
    handler.broadcast_state = AsyncMock()
    return record_game


class TestAutoAdvanceFinalRoundRecordsOnce:
    async def test_unattended_final_round_records_stats_exactly_once(self, monkeypatch):
        """#1753(a): the auto-advance final round (admin walked away) must record
        stats + run the game-end ceremony — previously it called advance_to_end
        directly and never recorded."""
        handler, game_state, _ws = _make_handler_and_game()
        record_game = _stub_terminal_game(handler, game_state)
        _wire_game_end(handler, game_state)

        # Skip the poll delays; break out of the wait loop on the first poll.
        monkeypatch.setattr(auto_advance_mod.asyncio, "sleep", AsyncMock())
        game_state._song_finished = MagicMock(return_value=True)
        game_state._on_round_end = AsyncMock()

        async def _exhaust() -> bool:
            # Playlist exhausted: start_round flips to END and returns False.
            game_state.phase = GamePhase.END
            return False

        game_state.start_round = AsyncMock(side_effect=_exhaust)
        game_state.phase = GamePhase.REVEAL

        await game_state._reveal_auto_advance(0)

        record_game.assert_awaited_once()
        game_state.advance_to_end.assert_awaited_once()
        # The game-end was claimed by the auto-advance path.
        assert game_state.game_id in handler._recorded_game_ids

    async def test_auto_advance_and_parallel_next_round_end_once(self, monkeypatch):
        """#1753(b): a concurrently-parked admin_next_round and the auto-advance
        both reaching the final round record + advance exactly once."""
        handler, game_state, ws = _make_handler_and_game()
        record_game = _stub_terminal_game(handler, game_state)
        game_state.last_round = True
        _wire_game_end(handler, game_state)

        monkeypatch.setattr(auto_advance_mod.asyncio, "sleep", AsyncMock())
        game_state._song_finished = MagicMock(return_value=True)
        game_state._on_round_end = AsyncMock()

        async def _exhaust() -> bool:
            game_state.phase = GamePhase.END
            return False

        game_state.start_round = AsyncMock(side_effect=_exhaust)
        game_state.phase = GamePhase.REVEAL

        await asyncio.gather(
            game_state._reveal_auto_advance(0),
            admin_next_round(handler, ws, {"action": "next_round"}, game_state),
        )

        record_game.assert_awaited_once()
        game_state.advance_to_end.assert_awaited_once()


# ---------------------------------------------------------------------------
# #1754 — a record_game failure releases the claim so a retry ends the game
# ---------------------------------------------------------------------------


class TestGameEndClaimReleasedOnFailure:
    async def test_record_failure_releases_claim_then_retry_ends_game(self):
        """#1754: if record_game raises, the burned claim would strand the game
        in REVEAL forever. The claim is released so the next tap re-runs the
        terminal sequence and the game ends."""
        handler, game_state, ws = _make_handler_and_game()
        game_state.phase = GamePhase.REVEAL
        game_state.last_round = True
        game_state.resolve_title_artist_if_pending = AsyncMock()
        game_state.advance_to_end = AsyncMock()
        game_state.finalize_game = MagicMock(return_value={})
        handler.broadcast_state = AsyncMock()

        # First record_game raises (storage I/O), second succeeds.
        record_game = AsyncMock(side_effect=[RuntimeError("storage down"), None])
        stats = MagicMock()
        stats.record_game = record_game
        handler.hass.data[DOMAIN]["stats"] = stats

        # First tap: record_game raises → claim released, error propagates.
        with pytest.raises(RuntimeError):
            await admin_next_round(handler, ws, {"action": "next_round"}, game_state)

        # The claim was released — not left burned.
        assert game_state.game_id not in handler._recorded_game_ids
        game_state.advance_to_end.assert_not_awaited()

        # Retry: record_game succeeds → the game finally ends.
        await admin_next_round(handler, ws, {"action": "next_round"}, game_state)

        assert record_game.await_count == 2
        game_state.advance_to_end.assert_awaited_once()
        assert game_state.game_id in handler._recorded_game_ids

    async def test_claim_set_stays_bounded_across_games(self):
        """#1754 minor: the claim set never grows unbounded — a fresh game_id
        prunes the predecessor's entry."""
        handler, game_state, _ws = _make_handler_and_game()

        assert handler._claim_game_end("game-1") is True
        assert handler._claim_game_end("game-2") is True
        # Only the current claim is retained.
        assert handler._recorded_game_ids == {"game-2"}
        # The predecessor is claimable again (it's a different, later game).
        assert handler._claim_game_end("game-1") is True
        assert handler._recorded_game_ids == {"game-1"}
