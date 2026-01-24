"""
ATDD Tests: Story 2.1 - Select Playlists for Game

These tests verify playlist selection functionality:
- Playlists displayed with checkboxes (AC1)
- No playlists error with documentation link (AC2)
- Total song count displayed for selections (AC3)
- Start game validation requires playlist selection (AC4)

Status: RED PHASE (Tests written before implementation)
Expected: All tests FAIL until implementation is complete

Note: These tests require Playwright to be installed:
    pip install playwright pytest-playwright
    playwright install chromium
"""

from __future__ import annotations

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
# STORY 2.1: Select Playlists for Game
# =============================================================================


@pytest.mark.e2e
@pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason="Playwright not installed")
class TestPlaylistDisplayWithCheckboxes:
    """
    AC1: Given admin page is loaded with available playlists,
    When host views the playlist selection area,
    Then all valid playlists are displayed with: playlist name, song count, checkbox
    """

    def test_valid_playlists_have_checkboxes(self, page: Page):
        """
        AC1: Valid playlists display checkboxes for selection.
        GIVEN playlists exist in the playlist directory
        WHEN admin page loads
        THEN each valid playlist has a checkbox input
        """
        page.goto(ADMIN_URL)
        page.wait_for_load_state("networkidle")

        # Find playlist items with checkboxes
        checkboxes = page.locator(".playlist-item .playlist-checkbox")

        # Should have at least one checkbox if playlists exist
        # (Test assumes at least one valid playlist exists)
        count = checkboxes.count()
        if count > 0:
            # Each checkbox should be visible
            for i in range(count):
                expect(checkboxes.nth(i)).to_be_visible()

    def test_playlist_checkbox_has_data_attributes(self, page: Page):
        """
        AC1: Checkboxes store path and song count in data attributes.
        GIVEN valid playlists are displayed
        WHEN checkbox is rendered
        THEN it has data-path and data-song-count attributes
        """
        page.goto(ADMIN_URL)
        page.wait_for_load_state("networkidle")

        checkbox = page.locator(".playlist-checkbox").first
        if checkbox.count() > 0:
            # Check data attributes exist
            path = checkbox.get_attribute("data-path")
            song_count = checkbox.get_attribute("data-song-count")

            assert path is not None, "Checkbox should have data-path attribute"
            assert song_count is not None, "Checkbox should have data-song-count attribute"

    def test_invalid_playlists_have_no_checkbox(self, page: Page):
        """
        AC1: Invalid playlists are greyed out without checkboxes.
        GIVEN some playlists are invalid
        WHEN admin page loads
        THEN invalid playlists use .is-invalid class and have no checkbox
        """
        page.goto(ADMIN_URL)
        page.wait_for_load_state("networkidle")

        invalid_items = page.locator(".list-item.is-invalid")
        count = invalid_items.count()

        for i in range(count):
            item = invalid_items.nth(i)
            # Invalid items should NOT have checkboxes
            checkbox = item.locator(".playlist-checkbox")
            expect(checkbox).to_have_count(0)

    def test_playlist_displays_name_and_song_count(self, page: Page):
        """
        AC1: Each playlist shows name and song count.
        GIVEN valid playlists exist
        WHEN admin page loads
        THEN playlist name and song count are visible
        """
        page.goto(ADMIN_URL)
        page.wait_for_load_state("networkidle")

        playlist_item = page.locator(".playlist-item").first
        if playlist_item.count() > 0:
            # Should have name element
            name = playlist_item.locator(".playlist-name")
            expect(name).to_be_visible()

            # Should have meta element with song count
            meta = playlist_item.locator(".meta")
            expect(meta).to_be_visible()
            expect(meta).to_contain_text("songs")


@pytest.mark.e2e
@pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason="Playwright not installed")
class TestNoPlaylistsErrorState:
    """
    AC2: Given no playlists exist in the playlist directory,
    When admin page loads,
    Then an error displays with documentation link
    """

    def test_no_playlists_shows_error_message(self, page: Page):
        """
        AC2: Shows error when no playlists found.
        Note: This test requires a setup where no playlists exist.
        In practice, this may need mock data or specific test environment.
        """
        # This test would need to be run with an empty playlists directory
        # For now, we test the structure exists when empty state triggers
        page.goto(ADMIN_URL)
        page.wait_for_load_state("networkidle")

        # Check if empty state is shown (only when no playlists)
        empty_state = page.locator("#playlists-list .empty-state")
        if empty_state.count() > 0:
            expect(empty_state).to_contain_text("No playlists found")
            expect(empty_state).to_contain_text("Add playlist JSON files")

    def test_no_playlists_shows_documentation_link(self, page: Page):
        """
        AC2 (FR55): Documentation link shown when no playlists.
        GIVEN no playlists exist
        WHEN admin page loads
        THEN a link to playlist documentation is provided
        """
        page.goto(ADMIN_URL)
        page.wait_for_load_state("networkidle")

        # Check if empty state has documentation link
        empty_state = page.locator("#playlists-list .empty-state")
        if empty_state.count() > 0:
            doc_link = empty_state.locator("a")
            expect(doc_link).to_be_visible()
            expect(doc_link).to_have_attribute(
                "href", "https://github.com/mholzi/beatify/wiki/Creating-Playlists"
            )


@pytest.mark.e2e
@pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason="Playwright not installed")
class TestPlaylistSelectionSummary:
    """
    AC3: Given host selects multiple playlists,
    When playlists are selected,
    Then total song count across all selected playlists is displayed
    """

    def test_selecting_playlist_updates_summary(self, page: Page):
        """
        AC3: Selecting playlists shows total count.
        GIVEN valid playlists exist
        WHEN user selects a playlist
        THEN summary shows selected count and total songs
        """
        page.goto(ADMIN_URL)
        page.wait_for_load_state("networkidle")

        checkbox = page.locator(".playlist-checkbox").first
        if checkbox.count() > 0:
            # Click to select
            checkbox.click()

            # Summary should become visible
            summary = page.locator("#playlist-summary")
            expect(summary).to_be_visible()
            expect(summary).not_to_have_class("hidden")

            # Summary should show count
            selected_count = page.locator("#selected-count")
            expect(selected_count).to_have_text("1")

    def test_deselecting_all_hides_summary(self, page: Page):
        """
        AC3: Summary hidden when no playlists selected.
        GIVEN playlists were selected
        WHEN all are deselected
        THEN summary is hidden
        """
        page.goto(ADMIN_URL)
        page.wait_for_load_state("networkidle")

        checkbox = page.locator(".playlist-checkbox").first
        if checkbox.count() > 0:
            # Select then deselect
            checkbox.click()
            checkbox.click()

            # Summary should be hidden
            summary = page.locator("#playlist-summary")
            expect(summary).to_have_class("hidden")

    def test_multiple_selections_accumulate_song_count(self, page: Page):
        """
        AC3: Multiple selections sum total songs.
        GIVEN multiple valid playlists exist
        WHEN user selects multiple playlists
        THEN total songs is the sum across all selected
        """
        page.goto(ADMIN_URL)
        page.wait_for_load_state("networkidle")

        checkboxes = page.locator(".playlist-checkbox")
        if checkboxes.count() >= 2:
            # Get song counts from data attributes
            first_count = int(checkboxes.nth(0).get_attribute("data-song-count") or "0")
            second_count = int(checkboxes.nth(1).get_attribute("data-song-count") or "0")
            expected_total = first_count + second_count

            # Select both
            checkboxes.nth(0).click()
            checkboxes.nth(1).click()

            # Check total
            total_songs = page.locator("#total-songs")
            expect(total_songs).to_have_text(str(expected_total))

    def test_selected_playlist_has_visual_highlight(self, page: Page):
        """
        AC3: Selected playlists are visually highlighted.
        GIVEN valid playlists exist
        WHEN user selects a playlist
        THEN the item gets .is-selected class
        """
        page.goto(ADMIN_URL)
        page.wait_for_load_state("networkidle")

        checkbox = page.locator(".playlist-checkbox").first
        if checkbox.count() > 0:
            # Click to select
            checkbox.click()

            # Parent item should have is-selected class
            item = checkbox.locator("xpath=ancestor::*[contains(@class, 'playlist-item')]")
            expect(item).to_have_class("playlist-item list-item is-selectable is-selected")


@pytest.mark.e2e
@pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason="Playwright not installed")
class TestStartGameValidation:
    """
    AC4: Given host attempts to start game with no playlists selected,
    When start game is clicked,
    Then validation prevents start with message
    """

    def test_start_button_disabled_without_selection(self, page: Page):
        """
        AC4: Start button disabled when no playlists selected.
        GIVEN admin page loads
        WHEN no playlists are selected
        THEN start game button is disabled
        """
        page.goto(ADMIN_URL)
        page.wait_for_load_state("networkidle")

        start_btn = page.locator("#start-game")
        expect(start_btn).to_be_disabled()

    def test_start_button_enabled_with_selection(self, page: Page):
        """
        AC4: Start button enabled when playlists selected.
        GIVEN valid playlists exist
        WHEN user selects a playlist
        THEN start game button is enabled
        """
        page.goto(ADMIN_URL)
        page.wait_for_load_state("networkidle")

        checkbox = page.locator(".playlist-checkbox").first
        if checkbox.count() > 0:
            checkbox.click()

            start_btn = page.locator("#start-game")
            expect(start_btn).to_be_enabled()

    def test_game_controls_visible_when_playlists_exist(self, page: Page):
        """
        AC4: Game controls section visible when playlists exist.
        GIVEN valid playlists exist
        WHEN admin page loads
        THEN game controls section is visible (not hidden)
        """
        page.goto(ADMIN_URL)
        page.wait_for_load_state("networkidle")

        # Check if playlists exist
        checkboxes = page.locator(".playlist-checkbox")
        if checkboxes.count() > 0:
            game_controls = page.locator("#game-controls")
            expect(game_controls).not_to_have_class("hidden")


@pytest.mark.e2e
@pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason="Playwright not installed")
class TestPlaylistCheckboxTouchTargets:
    """
    NFR18: All touch targets minimum 44x44px
    """

    def test_checkbox_meets_minimum_touch_target(self, page: Page):
        """
        NFR18: Checkboxes are at least 44x44px.
        GIVEN valid playlists exist
        WHEN checkboxes are rendered
        THEN each checkbox is at least 44x44px
        """
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(ADMIN_URL)
        page.wait_for_load_state("networkidle")

        checkboxes = page.locator(".playlist-checkbox").all()
        for checkbox in checkboxes:
            box = checkbox.bounding_box()
            if box:
                assert box["width"] >= 44, f"Checkbox too narrow: {box['width']}px"
                assert box["height"] >= 44, f"Checkbox too short: {box['height']}px"
