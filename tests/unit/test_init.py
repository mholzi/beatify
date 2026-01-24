"""Tests for Beatify integration initialization."""

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_config_entry():
    """Create a mock config entry."""
    entry = MagicMock()
    entry.entry_id = "test_entry_123"
    entry.data = {}
    return entry


@pytest.mark.asyncio
async def test_async_setup_entry_initializes_domain_data(mock_hass, mock_config_entry):
    """Test that async_setup_entry initializes hass.data[DOMAIN]."""
    from custom_components.beatify import async_setup_entry
    from custom_components.beatify.const import DOMAIN

    result = await async_setup_entry(mock_hass, mock_config_entry)

    assert result is True
    assert DOMAIN in mock_hass.data
    assert mock_config_entry.entry_id in mock_hass.data[DOMAIN]


@pytest.mark.asyncio
async def test_async_setup_entry_returns_true(mock_hass, mock_config_entry):
    """Test that async_setup_entry returns True on success."""
    from custom_components.beatify import async_setup_entry

    result = await async_setup_entry(mock_hass, mock_config_entry)

    assert result is True


@pytest.mark.asyncio
async def test_async_unload_entry_cleans_up_data(mock_hass, mock_config_entry):
    """Test that async_unload_entry removes entry data."""
    from custom_components.beatify import async_setup_entry, async_unload_entry
    from custom_components.beatify.const import DOMAIN

    # Setup first
    await async_setup_entry(mock_hass, mock_config_entry)
    assert mock_config_entry.entry_id in mock_hass.data[DOMAIN]

    # Unload
    result = await async_unload_entry(mock_hass, mock_config_entry)

    assert result is True
    assert mock_config_entry.entry_id not in mock_hass.data.get(DOMAIN, {})


@pytest.mark.asyncio
async def test_async_unload_entry_removes_empty_domain(mock_hass, mock_config_entry):
    """Test that domain is removed when empty after unload."""
    from custom_components.beatify import async_setup_entry, async_unload_entry
    from custom_components.beatify.const import DOMAIN

    # Setup and unload
    await async_setup_entry(mock_hass, mock_config_entry)
    await async_unload_entry(mock_hass, mock_config_entry)

    # Domain should be removed when empty
    assert DOMAIN not in mock_hass.data or not mock_hass.data[DOMAIN]


@pytest.mark.asyncio
async def test_async_unload_entry_handles_missing_data(mock_hass, mock_config_entry):
    """Test that unload handles case where data doesn't exist."""
    from custom_components.beatify import async_unload_entry

    # Don't setup, just try to unload
    result = await async_unload_entry(mock_hass, mock_config_entry)

    # Should still return True and not raise
    assert result is True
