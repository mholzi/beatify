"""
ATDD Tests: Story 1.5 - Admin Page Access

These tests verify the admin page loads correctly without authentication
and displays the required information.

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
# STORY 1.5: Admin Page Access
# =============================================================================


@pytest.mark.e2e
@pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason="Playwright not installed")
class TestAdminPageAccess:
    """
    GIVEN Beatify integration is configured
    WHEN admin navigates to /beatify/admin
    THEN the admin page loads without requiring HA login (FR6)
    """

    @pytest.mark.skip(reason="Admin page not implemented yet")
    def test_admin_page_loads_without_auth(self, page: Page):
        """
        AC: Admin page loads without requiring HA login.
        GIVEN Beatify is configured
        WHEN navigating to /beatify/admin
        THEN page loads successfully (no redirect to login)
        """
        page.goto(ADMIN_URL)

        # Should NOT be redirected to HA login
        assert "/auth/authorize" not in page.url, (
            "Admin page should not require authentication"
        )

        # Page should have loaded (check for some content)
        expect(page).to_have_title(title_pattern="Beatify")

    @pytest.mark.skip(reason="Admin page not implemented yet")
    def test_admin_page_loads_under_2_seconds(self, page: Page):
        """
        AC: Page load time < 2 seconds (NFR1).
        GIVEN admin navigates to /beatify/admin
        WHEN page loads
        THEN load completes within 2 seconds
        """
        import time

        start = time.time()
        page.goto(ADMIN_URL)
        page.wait_for_load_state("networkidle")
        load_time = time.time() - start

        assert load_time < 2.0, f"Page load took {load_time:.2f}s, expected <2s"


@pytest.mark.e2e
@pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason="Playwright not installed")
class TestAdminPageContent:
    """
    GIVEN admin page loads
    WHEN the page initializes
    THEN it displays media players, playlists, and MA status
    """

    @pytest.mark.skip(reason="Admin page not implemented yet")
    def test_displays_media_players(self, page: Page):
        """
        AC: Detected media players displayed.
        GIVEN media players exist in HA
        WHEN admin page loads
        THEN media player selector is visible
        """
        page.goto(ADMIN_URL)

        # Look for media player selection element
        media_player_selector = page.locator('[data-testid="media-player-select"]')
        expect(media_player_selector).to_be_visible()

    @pytest.mark.skip(reason="Admin page not implemented yet")
    def test_displays_playlists(self, page: Page):
        """
        AC: Detected playlists displayed.
        GIVEN playlists exist in the playlist directory
        WHEN admin page loads
        THEN playlist checkboxes are visible
        """
        page.goto(ADMIN_URL)

        # Look for playlist selection area
        playlist_area = page.locator('[data-testid="playlist-select"]')
        expect(playlist_area).to_be_visible()

    @pytest.mark.skip(reason="Admin page not implemented yet")
    def test_displays_ma_status(self, page: Page):
        """
        AC: Music Assistant status displayed.
        GIVEN admin page loads
        WHEN MA status is checked
        THEN status indicator is visible (connected/not found)
        """
        page.goto(ADMIN_URL)

        # Look for MA status indicator
        ma_status = page.locator('[data-testid="ma-status"]')
        expect(ma_status).to_be_visible()

    @pytest.mark.skip(reason="Admin page not implemented yet")
    def test_displays_ma_error_when_not_configured(self, page: Page):
        """
        AC: MA error with setup guide link shown when not configured (FR54).
        GIVEN Music Assistant is not configured
        WHEN admin page loads
        THEN error message with setup guide link is displayed
        """
        page.goto(ADMIN_URL)

        # If MA not configured, error should be visible
        ma_error = page.locator('[data-testid="ma-error"]')
        if ma_error.is_visible():
            expect(ma_error).to_contain_text("Music Assistant")
            # Should have a link to setup guide
            setup_link = ma_error.locator("a")
            expect(setup_link).to_be_visible()


@pytest.mark.e2e
@pytest.mark.skipif(not PLAYWRIGHT_AVAILABLE, reason="Playwright not installed")
class TestAdminPageMobileResponsive:
    """
    GIVEN admin accesses the page from a mobile device
    WHEN the page renders
    THEN all elements are touch-friendly and layout adapts
    """

    @pytest.mark.skip(reason="Admin page not implemented yet")
    def test_mobile_viewport_renders_correctly(self, page: Page):
        """
        AC: Layout adapts to mobile viewport.
        GIVEN admin on mobile device
        WHEN page renders
        THEN layout is mobile-optimized
        """
        # Set mobile viewport (iPhone 12 Pro dimensions)
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(ADMIN_URL)

        # Page should still render without horizontal scroll
        body = page.locator("body")
        expect(body).to_be_visible()

        # Check for no horizontal overflow
        overflow = page.evaluate(
            "() => document.documentElement.scrollWidth > document.documentElement.clientWidth"
        )
        assert not overflow, "Page has horizontal scroll on mobile"

    @pytest.mark.skip(reason="Admin page not implemented yet")
    def test_touch_targets_minimum_size(self, page: Page):
        """
        AC: All touch targets minimum 44x44px (NFR18).
        GIVEN admin on mobile device
        WHEN interactive elements are rendered
        THEN all buttons/inputs are at least 44x44px
        """
        page.set_viewport_size({"width": 390, "height": 844})
        page.goto(ADMIN_URL)

        # Find all buttons and check their size
        buttons = page.locator("button").all()
        for button in buttons:
            box = button.bounding_box()
            if box:
                assert box["width"] >= 44, f"Button too narrow: {box['width']}px"
                assert box["height"] >= 44, f"Button too short: {box['height']}px"


# =============================================================================
# REQUIRED DATA-TESTID ATTRIBUTES
# =============================================================================
"""
For these tests to pass, the admin page must include these data-testid attributes:

Admin Page (/beatify/admin):
- `media-player-select` - Media player dropdown/selector
- `playlist-select` - Playlist checkbox area
- `ma-status` - Music Assistant status indicator
- `ma-error` - Music Assistant error message (when not configured)
- `start-game-button` - Start game button (Epic 2)

These selectors follow the `data-testid` best practice for stable test automation.
"""
