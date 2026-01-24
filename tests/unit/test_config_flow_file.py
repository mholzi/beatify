"""Tests for Beatify config flow.

Note: These tests verify the config_flow.py file structure and content
without importing it directly (to avoid homeassistant dependency).
"""

from pathlib import Path


def test_config_flow_file_exists():
    """Test that config_flow.py exists."""
    config_flow_path = Path("custom_components/beatify/config_flow.py")
    assert config_flow_path.exists(), "config_flow.py should exist"


def test_config_flow_has_beatify_class():
    """Test that config_flow.py defines BeatifyConfigFlow class."""
    config_flow_path = Path("custom_components/beatify/config_flow.py")
    content = config_flow_path.read_text()

    assert "class BeatifyConfigFlow" in content, "Should define BeatifyConfigFlow class"
    assert "ConfigFlow" in content, "Should inherit from ConfigFlow"


def test_config_flow_uses_domain():
    """Test that config_flow.py uses DOMAIN from const."""
    config_flow_path = Path("custom_components/beatify/config_flow.py")
    content = config_flow_path.read_text()

    assert "from .const import DOMAIN" in content, "Should import DOMAIN from const"
    assert "domain=DOMAIN" in content, "Should use DOMAIN in class definition"


def test_config_flow_has_user_step():
    """Test that config_flow.py has async_step_user method."""
    config_flow_path = Path("custom_components/beatify/config_flow.py")
    content = config_flow_path.read_text()

    assert "async def async_step_user" in content, "Should have async_step_user method"


def test_config_flow_has_version():
    """Test that config_flow.py defines VERSION."""
    config_flow_path = Path("custom_components/beatify/config_flow.py")
    content = config_flow_path.read_text()

    assert "VERSION = 1" in content, "Should define VERSION = 1"


def test_config_flow_sets_unique_id():
    """Test that config_flow.py sets unique_id to prevent duplicates."""
    config_flow_path = Path("custom_components/beatify/config_flow.py")
    content = config_flow_path.read_text()

    assert "async_set_unique_id" in content, "Should call async_set_unique_id"
    assert "_abort_if_unique_id_configured" in content, "Should check for duplicate config"


def test_config_flow_creates_entry():
    """Test that config_flow.py creates config entry."""
    config_flow_path = Path("custom_components/beatify/config_flow.py")
    content = config_flow_path.read_text()

    assert "async_create_entry" in content, "Should call async_create_entry"
    assert 'title="Beatify"' in content, "Should use 'Beatify' as entry title"


def test_config_flow_shows_form():
    """Test that config_flow.py shows form."""
    config_flow_path = Path("custom_components/beatify/config_flow.py")
    content = config_flow_path.read_text()

    assert "async_show_form" in content, "Should call async_show_form"
    assert 'step_id="user"' in content, "Should use 'user' as step_id"
