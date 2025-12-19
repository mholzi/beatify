"""
ATDD Tests: Stories 1.2, 1.3, 1.4 - Config Flow & Discovery

These tests verify the Home Assistant config flow works correctly:
- Story 1.2: HACS Installation & Integration Setup
- Story 1.3: Media Player Validation
- Story 1.4: Media Player & Playlist Discovery

Status: Updated for course correction (2025-12-19)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Attempt to import HA test utilities (may not exist yet)
try:
    from homeassistant.config_entries import ConfigFlow
    from homeassistant.core import HomeAssistant

    HA_AVAILABLE = True
except ImportError:
    HA_AVAILABLE = False
    HomeAssistant = MagicMock


# Project paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
PLAYLIST_DIR = PROJECT_ROOT / "beatify" / "playlists"


# =============================================================================
# STORY 1.2: HACS Installation & Integration Setup
# =============================================================================


@pytest.mark.integration
class TestHACSMetadata:
    """
    GIVEN Beatify files exist
    WHEN HACS scans the repository
    THEN valid hacs.json metadata is found
    """

    def test_hacs_json_exists(self):
        """AC: hacs.json exists in project root."""
        hacs_file = PROJECT_ROOT / "hacs.json"
        assert hacs_file.exists(), (
            f"Missing: {hacs_file}\n"
            "Create hacs.json with name, documentation URL, and domains"
        )

    def test_hacs_json_has_required_fields(self):
        """AC: hacs.json contains valid metadata."""
        import json

        hacs_file = PROJECT_ROOT / "hacs.json"
        if not hacs_file.exists():
            pytest.skip("hacs.json not found")

        hacs = json.loads(hacs_file.read_text())
        required = ["name"]
        missing = [f for f in required if f not in hacs]
        assert not missing, f"hacs.json missing required fields: {missing}"
        assert hacs.get("name") == "Beatify", f"Expected name='Beatify'"


@pytest.mark.integration
@pytest.mark.skipif(not HA_AVAILABLE, reason="Home Assistant not installed")
class TestConfigFlowSetup:
    """
    GIVEN Beatify is installed via HACS
    WHEN admin navigates to Settings -> Integrations -> Add Integration
    THEN Beatify appears and config flow can be initiated
    """

    @pytest.fixture
    def hass(self) -> MagicMock:
        """Mock Home Assistant instance."""
        hass = MagicMock(spec=HomeAssistant)
        hass.data = {}
        hass.config.path = lambda *p: "/config/" + "/".join(p)
        return hass

    def test_config_flow_can_be_imported(self):
        """AC: config_flow.py can be imported without errors."""
        try:
            from custom_components.beatify import config_flow

            assert hasattr(config_flow, "BeatifyConfigFlow"), (
                "config_flow.py must define BeatifyConfigFlow class"
            )
        except ImportError as e:
            pytest.fail(f"Cannot import config_flow: {e}")

    @pytest.mark.skip(reason="Config flow not implemented yet")
    async def test_config_flow_step_user(self, hass):
        """AC: Config flow user step completes successfully."""
        from custom_components.beatify.config_flow import BeatifyConfigFlow

        flow = BeatifyConfigFlow()
        flow.hass = hass

        result = await flow.async_step_user()
        assert result["type"] == "form" or result["type"] == "create_entry"


# =============================================================================
# STORY 1.3: Media Player Validation
# =============================================================================


@pytest.mark.integration
class TestMediaPlayerValidation:
    """
    GIVEN Beatify config flow runs
    WHEN checking for media players
    THEN media player availability is correctly detected
    """

    @pytest.fixture
    def mock_entity_registry_with_players(self) -> MagicMock:
        """Mock entity registry with media players."""
        mock_reg = MagicMock()
        # Create mock entities with all required attributes
        player1 = MagicMock()
        player1.entity_id = "media_player.living_room"
        player1.domain = "media_player"
        player1.name = "Living Room Speaker"
        player1.original_name = None

        player2 = MagicMock()
        player2.entity_id = "media_player.kitchen"
        player2.domain = "media_player"
        player2.name = None
        player2.original_name = "Kitchen Speaker"

        mock_reg.entities = MagicMock()
        mock_reg.entities.values.return_value = [player1, player2]
        return mock_reg

    @pytest.fixture
    def mock_entity_registry_no_players(self) -> MagicMock:
        """Mock entity registry with no media players."""
        mock_reg = MagicMock()
        mock_reg.entities = MagicMock()
        mock_reg.entities.values.return_value = []
        return mock_reg

    @pytest.fixture
    def mock_hass(self) -> MagicMock:
        """Mock Home Assistant instance for config flow."""
        hass = MagicMock()
        hass.data = {}
        return hass

    def test_media_player_detection_method_exists(self):
        """AC: Config flow has media player detection method."""
        config_flow_path = Path("custom_components/beatify/config_flow.py")
        content = config_flow_path.read_text()

        assert "_get_media_player_entities" in content, (
            "config_flow.py should have _get_media_player_entities method"
        )

    def test_uses_entity_registry(self):
        """AC: Config flow uses entity_registry for media player detection."""
        config_flow_path = Path("custom_components/beatify/config_flow.py")
        content = config_flow_path.read_text()

        assert "entity_registry" in content, (
            "config_flow.py should use entity_registry for media player detection"
        )

    def test_no_music_assistant_references(self):
        """AC: Config flow should not reference Music Assistant."""
        config_flow_path = Path("custom_components/beatify/config_flow.py")
        content = config_flow_path.read_text()

        # Should not have any Music Assistant references
        assert "music_assistant" not in content.lower(), (
            "config_flow.py should not reference Music Assistant"
        )
        assert "MA_SETUP_URL" not in content, (
            "config_flow.py should not use MA_SETUP_URL"
        )

    @pytest.mark.skipif(not HA_AVAILABLE, reason="Home Assistant not installed")
    def test_get_media_player_entities_with_players(
        self, mock_hass, mock_entity_registry_with_players
    ):
        """AC1: Media players detected - returns list with entity_id and friendly_name."""
        from custom_components.beatify.config_flow import BeatifyConfigFlow

        with patch(
            "custom_components.beatify.config_flow.er.async_get",
            return_value=mock_entity_registry_with_players,
        ):
            flow = BeatifyConfigFlow()
            flow.hass = mock_hass

            result = flow._get_media_player_entities()

            assert len(result) == 2
            assert result[0]["entity_id"] == "media_player.living_room"
            assert result[0]["friendly_name"] == "Living Room Speaker"
            assert result[1]["entity_id"] == "media_player.kitchen"
            assert result[1]["friendly_name"] == "Kitchen Speaker"

    @pytest.mark.skipif(not HA_AVAILABLE, reason="Home Assistant not installed")
    def test_get_media_player_entities_no_players(
        self, mock_hass, mock_entity_registry_no_players
    ):
        """AC2: No media players - returns empty list."""
        from custom_components.beatify.config_flow import BeatifyConfigFlow

        with patch(
            "custom_components.beatify.config_flow.er.async_get",
            return_value=mock_entity_registry_no_players,
        ):
            flow = BeatifyConfigFlow()
            flow.hass = mock_hass

            result = flow._get_media_player_entities()

            assert result == []

    @pytest.mark.skipif(not HA_AVAILABLE, reason="Home Assistant not installed")
    @pytest.mark.asyncio
    async def test_config_flow_shows_warning_no_players(
        self, mock_hass, mock_entity_registry_no_players
    ):
        """AC2: Config flow shows warning but allows proceeding when no media players."""
        from custom_components.beatify.config_flow import BeatifyConfigFlow

        with patch(
            "custom_components.beatify.config_flow.er.async_get",
            return_value=mock_entity_registry_no_players,
        ):
            flow = BeatifyConfigFlow()
            flow.hass = mock_hass
            # Mock async_set_unique_id to avoid issues
            flow.async_set_unique_id = AsyncMock()
            flow._abort_if_unique_id_configured = MagicMock()

            result = await flow.async_step_user(user_input=None)

            # Should show form (not abort/error)
            assert result["type"] == "form"
            assert result["step_id"] == "user"
            # Should have warning in description_placeholders
            assert "description_placeholders" in result
            assert "warning" in result["description_placeholders"]
            assert "No media players found" in result["description_placeholders"]["warning"]

    @pytest.mark.skipif(not HA_AVAILABLE, reason="Home Assistant not installed")
    @pytest.mark.asyncio
    async def test_config_flow_shows_players_found(
        self, mock_hass, mock_entity_registry_with_players
    ):
        """AC1/AC3: Config flow shows media players with friendly names when found."""
        from custom_components.beatify.config_flow import BeatifyConfigFlow

        with patch(
            "custom_components.beatify.config_flow.er.async_get",
            return_value=mock_entity_registry_with_players,
        ):
            flow = BeatifyConfigFlow()
            flow.hass = mock_hass
            flow.async_set_unique_id = AsyncMock()
            flow._abort_if_unique_id_configured = MagicMock()

            result = await flow.async_step_user(user_input=None)

            assert result["type"] == "form"
            assert "description_placeholders" in result
            assert "warning" in result["description_placeholders"]
            # Should show friendly names
            assert "Living Room Speaker" in result["description_placeholders"]["warning"]
            assert "Kitchen Speaker" in result["description_placeholders"]["warning"]

    @pytest.mark.skipif(not HA_AVAILABLE, reason="Home Assistant not installed")
    @pytest.mark.asyncio
    async def test_config_flow_creates_entry_with_players(
        self, mock_hass, mock_entity_registry_with_players
    ):
        """AC1: Config flow creates entry when media players exist."""
        from custom_components.beatify.config_flow import BeatifyConfigFlow

        with patch(
            "custom_components.beatify.config_flow.er.async_get",
            return_value=mock_entity_registry_with_players,
        ):
            flow = BeatifyConfigFlow()
            flow.hass = mock_hass
            flow.async_set_unique_id = AsyncMock()
            flow._abort_if_unique_id_configured = MagicMock()

            result = await flow.async_step_user(user_input={})

            assert result["type"] == "create_entry"
            assert result["title"] == "Beatify"
            assert result["data"]["has_media_players"] is True

    @pytest.mark.skipif(not HA_AVAILABLE, reason="Home Assistant not installed")
    @pytest.mark.asyncio
    async def test_config_flow_creates_entry_without_players(
        self, mock_hass, mock_entity_registry_no_players
    ):
        """AC2: Config flow allows creating entry even without media players (with warning)."""
        from custom_components.beatify.config_flow import BeatifyConfigFlow

        with patch(
            "custom_components.beatify.config_flow.er.async_get",
            return_value=mock_entity_registry_no_players,
        ):
            flow = BeatifyConfigFlow()
            flow.hass = mock_hass
            flow.async_set_unique_id = AsyncMock()
            flow._abort_if_unique_id_configured = MagicMock()

            result = await flow.async_step_user(user_input={})

            # Should still create entry (AC2: setup can proceed but warns)
            assert result["type"] == "create_entry"
            assert result["title"] == "Beatify"
            assert result["data"]["has_media_players"] is False


# =============================================================================
# STORY 1.4: Media Player & Playlist Discovery
# =============================================================================


@pytest.mark.integration
class TestMediaPlayerDiscovery:
    """
    GIVEN Beatify config flow is running
    WHEN Beatify scans for media players
    THEN all HA media_player entities are listed (FR4)
    """

    @pytest.fixture
    def mock_hass_with_players(self) -> MagicMock:
        """HA instance with media players."""
        hass = MagicMock()
        hass.states.async_all.return_value = [
            MagicMock(
                entity_id="media_player.living_room",
                state="idle",
                attributes={"friendly_name": "Living Room Speaker"},
            ),
            MagicMock(
                entity_id="media_player.kitchen",
                state="playing",
                attributes={"friendly_name": "Kitchen Speaker"},
            ),
        ]
        return hass

    @pytest.fixture
    def mock_hass_no_players(self) -> MagicMock:
        """HA instance with no media players."""
        hass = MagicMock()
        hass.states.async_all.return_value = []
        return hass

    @pytest.mark.skip(reason="Media player discovery not implemented yet")
    async def test_media_players_listed(self, mock_hass_with_players):
        """
        AC: All media_player entities listed with friendly names.
        GIVEN multiple media players exist in HA
        WHEN Beatify scans for media players
        THEN all are returned with friendly names and states
        """
        from custom_components.beatify.config_flow import discover_media_players

        players = await discover_media_players(mock_hass_with_players)
        assert len(players) == 2
        assert any(p["entity_id"] == "media_player.living_room" for p in players)
        assert any(p["friendly_name"] == "Kitchen Speaker" for p in players)

    @pytest.mark.skip(reason="Media player discovery not implemented yet")
    async def test_no_media_players_error(self, mock_hass_no_players):
        """
        AC: Error when no media players available (FR56).
        GIVEN no media players exist in HA
        WHEN Beatify scans for media players
        THEN appropriate error is returned
        """
        from custom_components.beatify.config_flow import discover_media_players

        players = await discover_media_players(mock_hass_no_players)
        assert players == [] or players is None


@pytest.mark.integration
class TestPlaylistDiscovery:
    """
    GIVEN Beatify scans for playlists
    WHEN the playlist directory is checked
    THEN valid playlists are listed (FR5)
    """

    @pytest.fixture
    def temp_playlist_dir(self, tmp_path) -> Path:
        """Create temporary playlist directory."""
        playlist_dir = tmp_path / "beatify" / "playlists"
        playlist_dir.mkdir(parents=True)
        return playlist_dir

    @pytest.fixture
    def valid_playlist(self, temp_playlist_dir) -> Path:
        """Create a valid playlist JSON file."""
        import json

        playlist = {
            "name": "80s Hits",
            "songs": [
                {"year": 1984, "uri": "spotify:track:123", "fun_fact": "Classic!"},
                {"year": 1985, "uri": "spotify:track:456", "fun_fact": "Another hit"},
            ],
        }
        playlist_file = temp_playlist_dir / "80s_hits.json"
        playlist_file.write_text(json.dumps(playlist))
        return playlist_file

    @pytest.fixture
    def invalid_playlist(self, temp_playlist_dir) -> Path:
        """Create an invalid playlist (missing required fields)."""
        import json

        playlist = {"name": "Bad Playlist", "songs": [{"title": "Missing year"}]}
        playlist_file = temp_playlist_dir / "bad.json"
        playlist_file.write_text(json.dumps(playlist))
        return playlist_file

    @pytest.mark.skip(reason="Playlist discovery not implemented yet")
    def test_playlist_directory_created_if_missing(self, tmp_path):
        """
        AC: Playlist directory created automatically if missing.
        GIVEN playlist directory does not exist
        WHEN Beatify scans for playlists
        THEN directory is created automatically
        """
        from custom_components.beatify.playlist import ensure_playlist_directory

        playlist_dir = tmp_path / "beatify" / "playlists"
        assert not playlist_dir.exists()

        ensure_playlist_directory(tmp_path)
        assert playlist_dir.exists()

    @pytest.mark.skip(reason="Playlist discovery not implemented yet")
    def test_valid_playlists_listed(self, temp_playlist_dir, valid_playlist):
        """
        AC: Valid playlist files listed with name and song count.
        GIVEN valid playlist JSON files exist
        WHEN Beatify scans for playlists
        THEN playlists are listed with name and song count
        """
        from custom_components.beatify.playlist import discover_playlists

        playlists = discover_playlists(temp_playlist_dir)
        assert len(playlists) == 1
        assert playlists[0]["name"] == "80s Hits"
        assert playlists[0]["song_count"] == 2

    @pytest.mark.skip(reason="Playlist validation not implemented yet")
    def test_invalid_playlist_flagged(self, temp_playlist_dir, invalid_playlist):
        """
        AC: Invalid playlists flagged with specific error messages.
        GIVEN playlist JSON is missing required fields
        WHEN Beatify validates playlists
        THEN specific error is returned
        """
        from custom_components.beatify.playlist import validate_playlist

        result = validate_playlist(invalid_playlist)
        assert result["valid"] is False
        assert "year" in result["error"].lower()

    @pytest.mark.skip(reason="Playlist validation not implemented yet")
    def test_playlist_requires_year_and_uri(self, temp_playlist_dir):
        """
        AC: Each song must have year (integer) and uri (string).
        GIVEN playlist with incomplete song data
        WHEN validation runs
        THEN validation fails with specific field errors
        """
        import json

        from custom_components.beatify.playlist import validate_playlist

        bad_playlist = temp_playlist_dir / "incomplete.json"
        bad_playlist.write_text(
            json.dumps({"name": "Test", "songs": [{"uri": "test"}]})  # Missing year
        )

        result = validate_playlist(bad_playlist)
        assert result["valid"] is False
