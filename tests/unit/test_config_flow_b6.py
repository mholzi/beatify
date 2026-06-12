"""Regression tests for B6 config-flow plumbing (#1402).

Covers:
* Fix 1 — the wizard's media-player check uses the same async_get_media_players
  discovery as setup (so the warning matches what setup finds), not the old
  registry-only scan.
* Fix 3 — the created entry stores empty data (the dead "has_media_players"
  flag is gone) and the flow no longer runs the unique-id dance (single-entry
  is enforced via manifest single_config_entry).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.unit import _ha_stubs

_ha_stubs.install()

from custom_components.beatify.config_flow import BeatifyConfigFlow  # noqa: E402

_MANIFEST = (
    Path(__file__).resolve().parents[2]
    / "custom_components"
    / "beatify"
    / "manifest.json"
)


def _flow() -> BeatifyConfigFlow:
    flow = BeatifyConfigFlow()
    flow.hass = MagicMock()
    return flow


@pytest.mark.asyncio
async def test_flow_uses_async_get_media_players_discovery():
    """Fix 1: the form check calls the shared async discovery, not the registry."""
    flow = _flow()
    players = [{"entity_id": "media_player.living", "friendly_name": "Living Room"}]
    with patch(
        "custom_components.beatify.config_flow.async_get_media_players",
        new=AsyncMock(return_value=players),
    ) as mocked:
        result = await flow.async_step_user(None)

    mocked.assert_awaited_once_with(flow.hass)
    assert result["type"] == "form"
    assert "Living Room" in result["description_placeholders"]["warning"]


@pytest.mark.asyncio
async def test_flow_warns_when_no_media_players():
    flow = _flow()
    with patch(
        "custom_components.beatify.config_flow.async_get_media_players",
        new=AsyncMock(return_value=[]),
    ):
        result = await flow.async_step_user(None)
    assert result["type"] == "form"
    assert "No media players found" in result["description_placeholders"]["warning"]


@pytest.mark.asyncio
async def test_flow_creates_entry_with_empty_data():
    """Fix 3: created entry stores empty data (dead has_media_players gone)."""
    flow = _flow()
    with patch(
        "custom_components.beatify.config_flow.async_get_media_players",
        new=AsyncMock(return_value=[]),
    ):
        result = await flow.async_step_user({})
    assert result["type"] == "create_entry"
    assert result["title"] == "Beatify"
    assert result["data"] == {}


@pytest.mark.asyncio
async def test_flow_no_unique_id_dance():
    """Fix 3: the flow no longer calls async_set_unique_id (single_config_entry)."""
    flow = _flow()
    flow.async_set_unique_id = AsyncMock()
    flow._abort_if_unique_id_configured = MagicMock()
    with patch(
        "custom_components.beatify.config_flow.async_get_media_players",
        new=AsyncMock(return_value=[]),
    ):
        await flow.async_step_user(None)
    flow.async_set_unique_id.assert_not_called()
    flow._abort_if_unique_id_configured.assert_not_called()


def test_manifest_declares_single_config_entry():
    """Fix 3: manifest opts into HA's single-entry enforcement."""
    manifest = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    assert manifest.get("single_config_entry") is True
