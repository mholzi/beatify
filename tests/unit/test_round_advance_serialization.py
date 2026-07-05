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
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.beatify.const import DOMAIN
from custom_components.beatify.game.state import GamePhase
from custom_components.beatify.server.ws_handlers import (
    admin_end_game,
    admin_next_round,
    admin_rematch_game,
)
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
