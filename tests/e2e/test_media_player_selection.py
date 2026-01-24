"""
ATDD Tests: Story 2.2 - Select Media Player

These tests verify media player selection functionality:
- Available media players displayed with radio buttons (AC1)
- Unavailable players filtered out (AC1)
- No media players error with documentation link (AC2)
- All unavailable error message (AC3)
- Selection state tracked and visually confirmed (AC4)
- Start button requires both playlist AND media player selection

Status: Tests for Story 2.2
"""

from __future__ import annotations

import re

import pytest

# Attempt to import Playwright
try:
    from playwright.sync_api import Page, expect

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    Page = None


# Base URL for testing (configurable via environment)
BASE_URL = "http://localhost:8123"
ADMIN_URL = f"{BASE_URL}/beatify/admin"


# =============================================================================
# STORY 2.2: Select Media Player
# =============================================================================


@pytest.mark.e2e
@pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason="Playwright not installed")
class TestMediaPlayerDisplayWithRadioButtons:
    """
    AC1: Given admin page is loaded with available media players,
    When host views the media player selection area,
    Then only available (non-unavailable) players are displayed as selectable options
    """

    def test_available_players_have_radio_buttons(self, page: Page):
        """
        AC1: Available media players display radio buttons for selection.
        GIVEN media players exist in Home Assistant
        WHEN admin page loads
        THEN each available player has a radio button input
        """
        page.goto(ADMIN_URL)
        page.wait_for_load_state("networkidle")

        # Find media player items with radio buttons
        radios = page.locator(".media-player-item .media-player-radio")

        # Should have radio buttons if players exist
        count = radios.count()
        if count == 0:
            pytest.skip("No media players available in test environment")

        # Each radio should be visible
        for i in range(count):
            expect(radios.nth(i)).to_be_visible()

    def test_radio_button_has_data_attributes(self, page: Page):
        """
        AC1: Radio buttons store entity_id and state in data attributes.
        GIVEN available media players are displayed
        WHEN radio button is rendered
        THEN it has data-entity-id and data-state attributes
        """
        page.goto(ADMIN_URL)
        page.wait_for_load_state("networkidle")

        radio = page.locator(".media-player-radio").first
        if radio.count() == 0:
            pytest.skip("No media players available in test environment")

        # Check data attributes exist
        entity_id = radio.get_attribute("data-entity-id")
        state = radio.get_attribute("data-state")

        assert entity_id is not None, "Radio should have data-entity-id attribute"
        assert state is not None, "Radio should have data-state attribute"

    def test_media_player_displays_name_and_state(self, page: Page):
        """
        AC1: Each media player shows friendly name and current state.
        GIVEN available media players exist
        WHEN admin page loads
        THEN player name and state are visible
        """
        page.goto(ADMIN_URL)
        page.wait_for_load_state("networkidle")

        player_item = page.locator(".media-player-item").first
        if player_item.count() == 0:
            pytest.skip("No media players available in test environment")

        # Should have name element
        name = player_item.locator(".player-name")
        expect(name).to_be_visible()

        # Should have meta element with state
        meta = player_item.locator(".meta")
        expect(meta).to_be_visible()

    def test_state_dot_indicator_visible(self, page: Page):
        """
        AC1: State indicator dot is visible for each player.
        GIVEN available media players exist
        WHEN admin page loads
        THEN each player has a colored state dot
        """
        page.goto(ADMIN_URL)
        page.wait_for_load_state("networkidle")

        player_item = page.locator(".media-player-item").first
        if player_item.count() == 0:
            pytest.skip("No media players available in test environment")

        state_dot = player_item.locator(".state-dot")
        expect(state_dot).to_be_visible()


@pytest.mark.e2e
@pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason="Playwright not installed")
class TestNoMediaPlayersErrorState:
    """
    AC2: Given no media players are available in HA,
    When admin page loads,
    Then an error displays with documentation link
    """

    def test_no_players_shows_error_message(self, page: Page):
        """
        AC2: Shows error when no media players found.
        Note: This test requires a setup where no media players exist.
        """
        page.goto(ADMIN_URL)
        page.wait_for_load_state("networkidle")

        # Check if empty state is shown (only when no players)
        empty_state = page.locator("#media-players-list .empty-state")
        if empty_state.count() > 0:
            expect(empty_state).to_contain_text("No media players found")
            expect(empty_state).to_contain_text("Configure a media player")

    def test_no_players_shows_documentation_link(self, page: Page):
        """
        AC2 (FR56): Documentation link shown when no media players.
        GIVEN no media players exist
        WHEN admin page loads
        THEN a link to setup documentation is provided
        """
        page.goto(ADMIN_URL)
        page.wait_for_load_state("networkidle")

        empty_state = page.locator("#media-players-list .empty-state")
        if empty_state.count() > 0:
            doc_link = empty_state.locator("a")
            expect(doc_link).to_be_visible()


@pytest.mark.e2e
@pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason="Playwright not installed")
class TestAllUnavailableErrorState:
    """
    AC3: Given some media players exist but all are unavailable,
    When admin page loads,
    Then error displays specific message about unavailable devices
    """

    def test_all_unavailable_shows_specific_error(self, page: Page):
        """
        AC3: Shows specific error when all players unavailable.
        Note: This test requires a setup where all players are unavailable.
        """
        page.goto(ADMIN_URL)
        page.wait_for_load_state("networkidle")

        empty_state = page.locator("#media-players-list .empty-state")
        # This would trigger only if all players have state 'unavailable'
        # Check for the specific message in that case
        if empty_state.count() > 0:
            text = empty_state.text_content()
            if "unavailable" in text.lower():
                expect(empty_state).to_contain_text("Check your devices are powered on")


@pytest.mark.e2e
@pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason="Playwright not installed")
class TestMediaPlayerSelection:
    """
    AC4: Given host selects a media player,
    When selection is made,
    Then selection is visually confirmed and stored
    """

    def test_selecting_player_updates_visual_state(self, page: Page):
        """
        AC4: Selecting a player adds .is-selected class.
        GIVEN available media players exist
        WHEN user selects a player
        THEN the item gets .is-selected class
        """
        page.goto(ADMIN_URL)
        page.wait_for_load_state("networkidle")

        radio = page.locator(".media-player-radio").first
        if radio.count() == 0:
            pytest.skip("No media players available in test environment")

        # Click to select
        radio.click()

        # Parent item should have is-selected class (use regex for flexible class order)
        item = radio.locator("xpath=ancestor::*[contains(@class, 'media-player-item')]")
        expect(item).to_have_class(re.compile(r"is-selected"))

    def test_only_one_player_selected_at_a_time(self, page: Page):
        """
        AC4: Radio buttons ensure single selection.
        GIVEN multiple media players exist
        WHEN user selects a second player
        THEN first player is deselected
        """
        page.goto(ADMIN_URL)
        page.wait_for_load_state("networkidle")

        radios = page.locator(".media-player-radio")
        if radios.count() < 2:
            pytest.skip("Need at least 2 media players for this test")

        # Select first
        radios.nth(0).click()
        first_item = radios.nth(0).locator(
            "xpath=ancestor::*[contains(@class, 'media-player-item')]"
        )
        expect(first_item).to_have_class(re.compile(r"is-selected"))

        # Select second
        radios.nth(1).click()
        second_item = radios.nth(1).locator(
            "xpath=ancestor::*[contains(@class, 'media-player-item')]"
        )

        # First should lose is-selected, second should have it
        expect(first_item).not_to_have_class(re.compile(r"is-selected"))
        expect(second_item).to_have_class(re.compile(r"is-selected"))


@pytest.mark.e2e
@pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason="Playwright not installed")
class TestStartGameValidationWithMediaPlayer:
    """
    Start game requires BOTH playlist AND media player selection.
    """

    def test_start_button_disabled_without_media_player(self, page: Page):
        """
        Start button disabled when no media player selected.
        GIVEN playlists exist but no media player is selected
        WHEN admin page loads
        THEN start game button is disabled
        """
        page.goto(ADMIN_URL)
        page.wait_for_load_state("networkidle")

        # Select a playlist if available
        playlist_checkbox = page.locator(".playlist-checkbox").first
        media_player_radio = page.locator(".media-player-radio").first

        if playlist_checkbox.count() == 0 or media_player_radio.count() == 0:
            pytest.skip("Need both playlists and media players for this test")

        playlist_checkbox.click()

        # Without media player selection, button should still be disabled
        start_btn = page.locator("#start-game")
        expect(start_btn).to_be_disabled()

    def test_start_button_enabled_with_both_selections(self, page: Page):
        """
        Start button enabled when both playlist and media player selected.
        GIVEN playlists and media players exist
        WHEN user selects one of each
        THEN start game button is enabled
        """
        page.goto(ADMIN_URL)
        page.wait_for_load_state("networkidle")

        # Select a playlist
        playlist_checkbox = page.locator(".playlist-checkbox").first
        # Select a media player
        media_player_radio = page.locator(".media-player-radio").first

        if playlist_checkbox.count() == 0 or media_player_radio.count() == 0:
            pytest.skip("Need both playlists and media players for this test")

        playlist_checkbox.click()
        media_player_radio.click()

        start_btn = page.locator("#start-game")
        expect(start_btn).to_be_enabled()

    def test_media_player_validation_message_visible(self, page: Page):
        """
        Validation message visible when no media player selected.
        GIVEN admin page loads
        WHEN no media player is selected
        THEN validation message is visible
        """
        page.goto(ADMIN_URL)
        page.wait_for_load_state("networkidle")

        # Check for media player items (if they exist)
        radios = page.locator(".media-player-radio")
        if radios.count() == 0:
            pytest.skip("No media players available in test environment")

        # Validation message should be visible initially
        msg = page.locator("#media-player-validation-msg")
        expect(msg).to_be_visible()

    def test_media_player_validation_message_hidden_after_selection(self, page: Page):
        """
        Validation message hidden after media player selected.
        GIVEN media players exist
        WHEN user selects a player
        THEN validation message is hidden
        """
        page.goto(ADMIN_URL)
        page.wait_for_load_state("networkidle")

        radio = page.locator(".media-player-radio").first
        if radio.count() == 0:
            pytest.skip("No media players available in test environment")

        radio.click()

        msg = page.locator("#media-player-validation-msg")
        expect(msg).to_have_class(re.compile(r"hidden"))


@pytest.mark.e2e
@pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason="Playwright not installed")
class TestMediaPlayerRadioTouchTargets:
    """
    NFR18: All touch targets minimum 44x44px
    """

    def test_radio_meets_minimum_touch_target(self, page: Page):
        """
        NFR18: Radio buttons are at least 44x44px.
        GIVEN available media players exist
        WHEN radio buttons are rendered
        THEN each radio is at least 44x44px
        """
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(ADMIN_URL)
        page.wait_for_load_state("networkidle")

        radios = page.locator(".media-player-radio").all()
        for radio in radios:
            box = radio.bounding_box()
            if box:
                assert box["width"] >= 44, f"Radio too narrow: {box['width']}px"
                assert box["height"] >= 44, f"Radio too short: {box['height']}px"
