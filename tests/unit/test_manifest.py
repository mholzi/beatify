"""
ATDD Tests: Story 1.1 - Initialize Project from Starter Template

These tests verify the project structure matches the integration_blueprint
requirements for a Home Assistant custom integration.

Status: RED PHASE (Tests written before implementation)
Expected: All tests FAIL until implementation is complete
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

# Project root for file structure tests
PROJECT_ROOT = Path(__file__).parent.parent.parent
CUSTOM_COMPONENTS = PROJECT_ROOT / "custom_components" / "beatify"


# =============================================================================
# STORY 1.1: Initialize Project from Starter Template
# =============================================================================


@pytest.mark.unit
class TestProjectStructure:
    """
    GIVEN the integration_blueprint repository is available
    WHEN the project is initialized
    THEN a custom_components/beatify/ directory exists with required files
    """

    def test_custom_components_directory_exists(self):
        """AC: custom_components/beatify/ directory exists."""
        assert CUSTOM_COMPONENTS.exists(), (
            f"Directory not found: {CUSTOM_COMPONENTS}\n"
            "Run: Clone integration_blueprint and rename to beatify"
        )
        assert CUSTOM_COMPONENTS.is_dir()

    def test_init_file_exists(self):
        """AC: __init__.py with basic async_setup_entry exists."""
        init_file = CUSTOM_COMPONENTS / "__init__.py"
        assert init_file.exists(), f"Missing: {init_file}"

    def test_init_contains_async_setup_entry(self):
        """AC: __init__.py contains async_setup_entry function."""
        init_file = CUSTOM_COMPONENTS / "__init__.py"
        if not init_file.exists():
            pytest.skip("__init__.py not found")

        content = init_file.read_text()
        assert "async_setup_entry" in content, "__init__.py must contain async_setup_entry function"

    def test_manifest_file_exists(self):
        """AC: manifest.json exists."""
        manifest_file = CUSTOM_COMPONENTS / "manifest.json"
        assert manifest_file.exists(), f"Missing: {manifest_file}"

    def test_const_file_exists(self):
        """AC: const.py exists."""
        const_file = CUSTOM_COMPONENTS / "const.py"
        assert const_file.exists(), f"Missing: {const_file}"

    def test_config_flow_file_exists(self):
        """AC: config_flow.py skeleton exists."""
        config_flow_file = CUSTOM_COMPONENTS / "config_flow.py"
        assert config_flow_file.exists(), f"Missing: {config_flow_file}"


@pytest.mark.unit
class TestManifestContent:
    """
    GIVEN the manifest.json file exists
    WHEN the file is parsed
    THEN it contains correct domain and version
    """

    @pytest.fixture
    def manifest(self) -> dict:
        """Load manifest.json if it exists."""
        manifest_file = CUSTOM_COMPONENTS / "manifest.json"
        if not manifest_file.exists():
            pytest.skip("manifest.json not found")
        return json.loads(manifest_file.read_text())

    def test_manifest_domain_is_beatify(self, manifest):
        """AC: manifest.json has domain 'beatify'."""
        assert manifest.get("domain") == "beatify", (
            f"Expected domain='beatify', got domain='{manifest.get('domain')}'"
        )

    def test_manifest_version_exists(self, manifest):
        """AC: manifest.json has a valid semver version."""
        import re

        version = manifest.get("version")
        assert version is not None, "manifest.json must have a version field"
        # Validate semver format (major.minor.patch with optional pre-release)
        assert re.match(r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.]+)?$", version), (
            f"Version must be semver format (x.y.z or x.y.z-pre), got '{version}'"
        )

    def test_manifest_has_required_fields(self, manifest):
        """AC: manifest.json has all required fields."""
        required_fields = ["domain", "name", "version", "codeowners", "config_flow"]
        missing = [f for f in required_fields if f not in manifest]
        assert not missing, f"Missing required manifest fields: {missing}"

    def test_manifest_config_flow_enabled(self, manifest):
        """AC: config_flow is enabled for UI setup."""
        assert manifest.get("config_flow") is True, (
            "config_flow must be True for Settings → Integrations setup"
        )


@pytest.mark.unit
class TestConstContent:
    """
    GIVEN const.py exists
    WHEN the file is imported
    THEN DOMAIN equals 'beatify'
    """

    def test_const_domain_is_beatify(self):
        """AC: const.py has DOMAIN = 'beatify'."""
        const_file = CUSTOM_COMPONENTS / "const.py"
        if not const_file.exists():
            pytest.skip("const.py not found")

        content = const_file.read_text()
        assert 'DOMAIN = "beatify"' in content or "DOMAIN = 'beatify'" in content, (
            "const.py must contain DOMAIN = 'beatify'"
        )


@pytest.mark.unit
class TestCodeQuality:
    """
    GIVEN the project structure exists
    WHEN ruff linting is run
    THEN no errors are reported
    """

    @pytest.mark.slow
    def test_ruff_passes(self):
        """AC: Project passes ruff linting."""
        import subprocess

        if not CUSTOM_COMPONENTS.exists():
            pytest.skip("custom_components/beatify not found")

        import sys

        result = subprocess.run(
            [sys.executable, "-m", "ruff", "check", str(CUSTOM_COMPONENTS)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Ruff linting failed:\n{result.stdout}\n{result.stderr}"
