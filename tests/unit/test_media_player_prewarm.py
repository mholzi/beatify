"""Tests for the #1540 LOBBY media-player pre-warm.

Follow-up to #803: ``create_game`` should kick off construction (and a cheap
availability probe) of the ``MediaPlayerService`` during LOBBY so Round 1 does
not pay the cold-start construction + first-call latency. The pre-warm must be
best-effort and non-blocking, and ``_ensure_media_player_service`` must stay the
idempotent fallback for the round path.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.conftest import make_game_state, make_songs


def _closing_background_task(coro, *_args, **_kwargs):
    """async_create_background_task stub that closes the coro (no event loop)."""
    coro.close()
    return MagicMock()


def _create_game(state, **kwargs) -> dict:
    return state.create_game(
        playlists=["test.json"],
        songs=make_songs(5),
        media_player="media_player.test",
        base_url="http://localhost:8123",
        **kwargs,
    )


def test_create_game_schedules_prewarm_when_hass_set() -> None:
    """create_game schedules the pre-warm via hass when a player is selected."""
    state = make_game_state()
    hass = MagicMock()
    hass.async_create_background_task = MagicMock()
    state.set_hass(hass)

    _create_game(state)

    hass.async_create_background_task.assert_called_once()
    # The scheduled coroutine is named for the integration lifecycle.
    _args, kwargs = hass.async_create_background_task.call_args
    assert kwargs.get("name") == "beatify_media_player_prewarm"
    # Drain the scheduled coroutine so pytest doesn't warn about it never awaited.
    coro = hass.async_create_background_task.call_args.args[0]
    coro.close()


def test_create_game_does_not_schedule_without_hass() -> None:
    """No hass -> no pre-warm scheduled (silent no-op, lazy path remains)."""
    state = make_game_state()  # _hass is None
    # Must not raise even though there is no event loop / hass available.
    result = _create_game(state)
    assert result["game_id"]
    assert state._media_player_service is None


@pytest.mark.asyncio
async def test_prewarm_constructs_service_and_probes() -> None:
    """prewarm_media_player_service builds the service and runs verify_responsive."""
    state = make_game_state()
    hass = MagicMock()
    hass.async_create_background_task = MagicMock(side_effect=_closing_background_task)
    state.set_hass(hass)
    _create_game(state)
    assert state._media_player_service is None  # not yet built

    fake_service = MagicMock()
    fake_service.verify_responsive = AsyncMock(return_value=(True, ""))

    def _build() -> None:
        state._media_player_service = fake_service

    state._ensure_media_player_service = MagicMock(side_effect=_build)

    await state.prewarm_media_player_service()

    state._ensure_media_player_service.assert_called_once()
    fake_service.verify_responsive.assert_awaited_once()


@pytest.mark.asyncio
async def test_prewarm_is_idempotent_with_ensure() -> None:
    """A real round-path _ensure_media_player_service reuses the pre-warmed service."""
    state = make_game_state()
    hass = MagicMock()
    hass.states.get.return_value = None  # verify_responsive bails gracefully
    hass.async_create_background_task = MagicMock(side_effect=_closing_background_task)
    state.set_hass(hass)
    _create_game(state)

    await state.prewarm_media_player_service()
    warmed = state._media_player_service
    assert warmed is not None

    # The round path's lazy fallback must NOT rebuild — same instance is kept.
    state._ensure_media_player_service()
    assert state._media_player_service is warmed


@pytest.mark.asyncio
async def test_prewarm_runner_swallows_probe_errors_with_warning(caplog) -> None:
    """#1540 review (Fix 3): a failing probe is caught + warned in the runner.

    The inner best-effort catch was removed; the probe error now propagates out
    of ``prewarm_media_player_service`` and is swallowed (and logged at WARNING)
    by the ``_runner`` wrapper in ``schedule_media_player_prewarm``.
    """
    state = make_game_state()
    fake_service = MagicMock()
    fake_service.verify_responsive = AsyncMock(side_effect=RuntimeError("boom"))
    state._media_player_service = fake_service
    state.platform = "sonos"  # non-MA -> probe runs

    # The method itself now propagates (no inner swallow).
    with pytest.raises(RuntimeError, match="boom"):
        await state.prewarm_media_player_service()

    # The runner wrapper must swallow it (best-effort) and warn so a permanently
    # offline speaker is visible.
    hass = MagicMock(spec=[])  # no async_create_background_task -> bare task path
    state.set_hass(hass)
    state.media_player = "media_player.test"

    async def _run() -> None:
        with caplog.at_level("WARNING"):
            state.schedule_media_player_prewarm()
            await asyncio.sleep(0)  # let the fire-and-forget runner execute

    await _run()
    assert any("pre-warm failed" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_prewarm_music_assistant_skips_probe() -> None:
    """#1540 review (Fix 1): MA players must NOT get the blocking probe.

    verify_responsive is a blocking speaker service call; the round path only
    issues it for non-MA players. The pre-warm must mirror that so it doesn't
    fire a speaker service call in the LOBBY for Music Assistant.
    """
    state = make_game_state()
    hass = MagicMock()
    hass.async_create_background_task = MagicMock(side_effect=_closing_background_task)
    state.set_hass(hass)
    _create_game(state, platform="music_assistant")

    fake_service = MagicMock()
    fake_service.verify_responsive = AsyncMock(return_value=(True, ""))
    state._media_player_service = fake_service

    await state.prewarm_media_player_service()

    fake_service.verify_responsive.assert_not_awaited()


@pytest.mark.asyncio
async def test_prewarm_non_ma_runs_probe() -> None:
    """#1540 review (Fix 1): non-MA players still get the probe (counterpart)."""
    state = make_game_state()
    hass = MagicMock()
    hass.async_create_background_task = MagicMock(side_effect=_closing_background_task)
    state.set_hass(hass)
    _create_game(state, platform="sonos")

    fake_service = MagicMock()
    fake_service.verify_responsive = AsyncMock(return_value=(True, ""))
    state._media_player_service = fake_service

    await state.prewarm_media_player_service()

    fake_service.verify_responsive.assert_awaited_once()


@pytest.mark.asyncio
async def test_end_game_cancels_running_prewarm() -> None:
    """#1540 review (Fix 2): end_game cancels a still-running pre-warm task."""
    state = make_game_state()
    hass = MagicMock()
    hass.async_create_background_task = MagicMock(side_effect=_closing_background_task)
    state.set_hass(hass)
    _create_game(state)

    fake_task = MagicMock()
    state._prewarm_task = fake_task

    await state.end_game()

    fake_task.cancel.assert_called_once()
    assert state._prewarm_task is None


def test_create_game_cancels_prior_prewarm() -> None:
    """#1540 review (Fix 2): a new create_game cancels the prior pre-warm task."""
    state = make_game_state()
    hass = MagicMock()
    hass.async_create_background_task = MagicMock(side_effect=_closing_background_task)
    state.set_hass(hass)
    _create_game(state)

    stale_task = MagicMock()
    state._prewarm_task = stale_task

    # A second create_game (e.g. host starts a fresh game) must supersede it.
    _create_game(state)

    stale_task.cancel.assert_called_once()


def test_schedule_falls_back_to_create_task_without_helper() -> None:
    """When hass lacks async_create_background_task, a bare task is used."""
    state = make_game_state()
    hass = MagicMock(spec=[])  # no async_create_background_task attr
    state.set_hass(hass)
    state.media_player = "media_player.test"
    state.prewarm_media_player_service = AsyncMock()

    async def _run() -> None:
        state.schedule_media_player_prewarm()
        # Let the fire-and-forget task run.
        await asyncio.sleep(0)

    asyncio.run(_run())
    state.prewarm_media_player_service.assert_awaited_once()
