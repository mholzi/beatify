"""Removal cleanup for the config entry (#2263).

@proffalken removed and re-added the integration after deleting some speakers
from Home Assistant. Beatify still had the old entity ids: `setup.json` had
survived the removal, the fresh install re-hydrated it, and the game refused to
start because the assigned speakers no longer existed. Nothing in the UI could
clear that state — the in-app reset is the only caller of `clear_setup`, and it
is unreachable when the game will not start.

Home Assistant deletes the config entry itself; anything written elsewhere is
the integration's own job, and `async_remove_entry` did not exist at all.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.beatify import _remove_persisted_files, async_remove_entry


class _Config:
    def __init__(self, root: Path) -> None:
        self._root = root

    def path(self, *parts: str) -> str:
        return str(self._root.joinpath(*parts))


class _Hass:
    def __init__(self, root: Path) -> None:
        self.config = _Config(root)

    async def async_add_executor_job(self, func, *args):
        return func(*args)


def _write_both(root: Path) -> Path:
    d = root / "beatify"
    d.mkdir(parents=True, exist_ok=True)
    (d / "setup.json").write_text(
        json.dumps({"last_player": "Markus"}), encoding="utf-8"
    )
    (d / "data_quality_reports.json").write_text("[]", encoding="utf-8")
    return d


def test_removes_both_files(tmp_path: Path) -> None:
    d = _write_both(tmp_path)
    removed = _remove_persisted_files(_Hass(tmp_path))

    assert sorted(removed) == ["data_quality_reports.json", "setup.json"]
    assert not (d / "setup.json").exists()
    assert not (d / "data_quality_reports.json").exists()


def test_missing_files_are_not_an_error(tmp_path: Path) -> None:
    # A host who never finished the wizard has neither file. Removal must still
    # succeed rather than raise into HA's entry-removal path.
    assert _remove_persisted_files(_Hass(tmp_path)) == []


@pytest.mark.asyncio
async def test_removes_both_library_stores(tmp_path: Path) -> None:
    _write_both(tmp_path)
    hass = _Hass(tmp_path)
    created: list[str] = []

    class _FakeStore:
        def __init__(self, _hass, _version, key):
            created.append(key)
            self.async_remove = AsyncMock()

    with patch("custom_components.beatify.Store", _FakeStore):
        await async_remove_entry(hass, MagicMock())

    assert created == [
        "beatify.library_settings",
        "beatify.game_output_settings",
    ]


@pytest.mark.asyncio
async def test_a_failing_step_does_not_abort_the_removal(tmp_path: Path) -> None:
    """Best-effort by design: HA must not be left with a half-removed entry."""
    hass = _Hass(tmp_path)
    seen: list[str] = []

    class _FakeStore:
        def __init__(self, _hass, _version, key):
            self._key = key

        async def async_remove(self):
            seen.append(self._key)
            if self._key.endswith("library_settings"):
                raise OSError("disk full")

    with (
        patch("custom_components.beatify.Store", _FakeStore),
        patch(
            "custom_components.beatify._remove_persisted_files",
            side_effect=OSError("permission denied"),
        ),
    ):
        await async_remove_entry(hass, MagicMock())

    # The second Store is still attempted after the first one raised.
    assert seen == ["beatify.library_settings", "beatify.game_output_settings"]
