"""Tests for Beatify constants.

These tests verify the const.py module has correct values.
Tests are skipped if Home Assistant is not installed since importing
the custom_components package triggers HA imports.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Check if Home Assistant is available
try:
    from homeassistant.core import HomeAssistant

    HA_AVAILABLE = True
except ImportError:
    HA_AVAILABLE = False
    HomeAssistant = MagicMock


def test_const_file_has_domain():
    """Test const.py file defines DOMAIN constant."""
    const_path = Path("custom_components/beatify/const.py")
    content = const_path.read_text()
    assert 'DOMAIN = "beatify"' in content


def test_const_file_has_game_configuration():
    """Test const.py file has game configuration constants."""
    const_path = Path("custom_components/beatify/const.py")
    content = const_path.read_text()

    assert "MAX_PLAYERS = 20" in content
    assert "MIN_PLAYERS = 2" in content
    assert "RECONNECT_TIMEOUT = 60" in content
    assert "DEFAULT_ROUND_DURATION = 30" in content
    assert "MAX_NAME_LENGTH = 20" in content
    assert "MIN_NAME_LENGTH = 1" in content


def test_const_file_has_round_timer_constants():
    """Test const.py file has round timer configuration constants (Story 13.1)."""
    const_path = Path("custom_components/beatify/const.py")
    content = const_path.read_text()

    # Timer range constants
    assert "ROUND_DURATION_MIN = 10" in content
    assert "ROUND_DURATION_MAX = 60" in content

    # Timer presets
    assert "ROUND_DURATION_PRESETS" in content
    assert '"quick": 15' in content
    assert '"normal": 30' in content
    assert '"relaxed": 45' in content


def test_const_file_has_error_codes():
    """Test const.py file has error code constants."""
    const_path = Path("custom_components/beatify/const.py")
    content = const_path.read_text()

    assert 'ERR_NAME_TAKEN = "NAME_TAKEN"' in content
    assert 'ERR_NAME_INVALID = "NAME_INVALID"' in content
    assert 'ERR_GAME_NOT_STARTED = "GAME_NOT_STARTED"' in content
    assert 'ERR_GAME_ALREADY_STARTED = "GAME_ALREADY_STARTED"' in content
    assert 'ERR_NOT_ADMIN = "NOT_ADMIN"' in content
    assert 'ERR_ROUND_EXPIRED = "ROUND_EXPIRED"' in content
    assert 'ERR_MEDIA_PLAYER_UNAVAILABLE = "MEDIA_PLAYER_UNAVAILABLE"' in content
    assert 'ERR_INVALID_ACTION = "INVALID_ACTION"' in content


def test_const_file_has_external_urls():
    """Test const.py file has external URL constants."""
    const_path = Path("custom_components/beatify/const.py")
    content = const_path.read_text()

    assert "PLAYLIST_DOCS_URL" in content
    assert "MEDIA_PLAYER_DOCS_URL" in content
    assert "github.com" in content
    assert "home-assistant.io" in content


@pytest.mark.skipif(not HA_AVAILABLE, reason="Home Assistant not installed")
def test_domain_constant_import():
    """Test DOMAIN constant can be imported and has correct value."""
    from custom_components.beatify.const import DOMAIN

    assert DOMAIN == "beatify"


@pytest.mark.skipif(not HA_AVAILABLE, reason="Home Assistant not installed")
def test_error_code_constants_import():
    """Test error code constants can be imported."""
    from custom_components.beatify.const import (
        ERR_GAME_ALREADY_STARTED,
        ERR_GAME_NOT_STARTED,
        ERR_INVALID_ACTION,
        ERR_MEDIA_PLAYER_UNAVAILABLE,
        ERR_NAME_INVALID,
        ERR_NAME_TAKEN,
        ERR_NOT_ADMIN,
        ERR_ROUND_EXPIRED,
    )

    assert ERR_NAME_TAKEN == "NAME_TAKEN"
    assert ERR_MEDIA_PLAYER_UNAVAILABLE == "MEDIA_PLAYER_UNAVAILABLE"
