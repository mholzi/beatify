"""Force-reset must also drop the persisted setup blob (#2036).

Pressing Reset on the host screen cleared the browser's ``localStorage`` and
reloaded — but the server kept its setup blob, so ``/beatify/api/status`` still
reported ``setup_complete: true`` and ``reconcileSavedSetup()`` wrote the saved
speaker straight back into the emptied storage on the very same load. The
wizard's ``shouldTrigger()`` then saw a configured host, stayed shut, and
``BeatifyHome`` opened a fresh lobby — the screen the reset was meant to leave.

These tests pin the server half of the fix: after a force-reset there is no
blob left for the reload to re-seed from.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest import mock
from unittest.mock import AsyncMock, MagicMock

import pytest

from aiohttp.test_utils import make_mocked_request

from custom_components.beatify.const import DOMAIN
from custom_components.beatify.server.game_views import ForceResetView
from custom_components.beatify.server.setup_state import (
    clear_setup,
    read_setup,
    write_setup,
)


CONFIGURED_BLOB = {
    "last_player": "media_player.esszimmer",
    "game_settings": {"selectedPlaylists": [{"path": "80s.json"}]},
}


def _hass(tmp_path: Path) -> MagicMock:
    """A hass double whose config dir is `tmp_path` and whose executor is inline."""
    hass = MagicMock()
    # _setup_path() resolves to hass.config.path("beatify") / "setup.json".
    hass.config.path = MagicMock(return_value=str(tmp_path / "beatify"))
    hass.async_add_executor_job = AsyncMock(side_effect=lambda fn, *args: fn(*args))
    # No active game — the interesting half of this view is the blob, and a
    # stuck instance often has no game left to end anyway.
    hass.data = {DOMAIN: {}}
    return hass


def _authorized():
    return mock.patch(
        "custom_components.beatify.server.game_views.is_authorized_http",
        new=MagicMock(return_value=True),
    )


def _request():
    return make_mocked_request("POST", "/beatify/api/force-reset")


def _post(view: ForceResetView):
    """Drive the async handler from a sync test."""
    return asyncio.run(view.post(_request()))


# ---------------------------------------------------------------- clear_setup


def test_clear_setup_removes_the_blob(tmp_path: Path) -> None:
    hass = _hass(tmp_path)
    write_setup(hass, CONFIGURED_BLOB)
    assert read_setup(hass) == CONFIGURED_BLOB

    assert clear_setup(hass) is True
    # read_setup already means "nothing saved" by returning None for a missing
    # file — no second empty shape for callers to special-case.
    assert read_setup(hass) is None


def test_clear_setup_on_pristine_install_is_a_no_op(tmp_path: Path) -> None:
    """Never configured, or reset twice — neither may raise."""
    hass = _hass(tmp_path)
    assert clear_setup(hass) is False
    assert read_setup(hass) is None


def test_clear_setup_is_idempotent(tmp_path: Path) -> None:
    hass = _hass(tmp_path)
    write_setup(hass, CONFIGURED_BLOB)

    assert clear_setup(hass) is True
    assert clear_setup(hass) is False


# ------------------------------------------------------------ ForceResetView


def test_force_reset_clears_a_configured_setup(tmp_path: Path) -> None:
    """The regression: after the POST the instance reports unconfigured."""
    hass = _hass(tmp_path)
    write_setup(hass, CONFIGURED_BLOB)
    view = ForceResetView(hass)

    with _authorized():
        response = _post(view)

    assert response.status == 200
    assert read_setup(hass) is None


def test_force_reset_reports_what_it_cleared(tmp_path: Path) -> None:
    hass = _hass(tmp_path)
    write_setup(hass, CONFIGURED_BLOB)
    view = ForceResetView(hass)

    with _authorized():
        response = _post(view)

    assert b'"cleared_setup": true' in response.body


def test_force_reset_succeeds_without_a_saved_setup(tmp_path: Path) -> None:
    """Nothing saved is a normal state, not an error."""
    hass = _hass(tmp_path)
    view = ForceResetView(hass)

    with _authorized():
        response = _post(view)

    assert response.status == 200
    assert b'"success": true' in response.body
    assert b'"cleared_setup": false' in response.body


def test_force_reset_survives_an_unwritable_config_dir(tmp_path: Path) -> None:
    """A failed delete must not 500 — the caller is stuck and needs the reload.

    The blob then survives, so this reset degrades to its pre-#2036 behaviour
    instead of leaving the host with no working escape hatch at all.
    """
    hass = _hass(tmp_path)
    write_setup(hass, CONFIGURED_BLOB)
    view = ForceResetView(hass)

    with (
        _authorized(),
        mock.patch(
            "custom_components.beatify.server.game_views.clear_setup",
            side_effect=OSError("read-only file system"),
        ),
    ):
        response = _post(view)

    assert response.status == 200
    assert b'"success": true' in response.body
    assert b'"cleared_setup": false' in response.body


def test_force_reset_still_ends_a_running_game(tmp_path: Path) -> None:
    """The #777 job stays intact — the blob is an addition, not a replacement."""
    hass = _hass(tmp_path)
    write_setup(hass, CONFIGURED_BLOB)

    game_state = MagicMock()
    game_state.game_id = "GAME-42"
    game_state.end_game = AsyncMock()
    ws_handler = MagicMock()
    ws_handler.broadcast = AsyncMock()
    ws_handler.broadcast_state = AsyncMock()
    hass.data = {DOMAIN: {"game": game_state, "ws_handler": ws_handler}}

    view = ForceResetView(hass)
    with _authorized():
        response = _post(view)

    game_state.end_game.assert_awaited_once()
    assert b'"ended_game_id": "GAME-42"' in response.body
    assert read_setup(hass) is None


def test_force_reset_requires_authorization(tmp_path: Path) -> None:
    """An unauthorized caller must not be able to wipe the household setup."""
    hass = _hass(tmp_path)
    write_setup(hass, CONFIGURED_BLOB)
    view = ForceResetView(hass)

    with mock.patch(
        "custom_components.beatify.server.game_views.is_authorized_http",
        new=MagicMock(return_value=False),
    ):
        response = _post(view)

    assert response.status == 401
    assert read_setup(hass) == CONFIGURED_BLOB


def test_force_reset_rate_limit_does_not_clear_setup(tmp_path: Path) -> None:
    """The 4th call in an hour is refused — and must leave the blob alone."""
    hass = _hass(tmp_path)
    view = ForceResetView(hass)

    with _authorized():
        for _ in range(ForceResetView.RATE_LIMIT_REQUESTS):
            _post(view)

        write_setup(hass, CONFIGURED_BLOB)
        response = _post(view)

    assert response.status == 429
    assert read_setup(hass) == CONFIGURED_BLOB


@pytest.mark.parametrize("blob", [CONFIGURED_BLOB, {"last_player": None}])
def test_status_would_report_unconfigured_after_reset(
    tmp_path: Path, blob: dict
) -> None:
    """End-to-end of the actual bug — the reload has nothing to re-seed from.

    ``reconcileSavedSetup()`` only writes back what ``saved_setup`` carries, so
    a ``None`` blob is exactly what keeps the wizard open on step 1.
    """
    hass = _hass(tmp_path)
    write_setup(hass, blob)
    view = ForceResetView(hass)

    with _authorized():
        _post(view)

    assert read_setup(hass) is None
