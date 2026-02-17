"""
E2E Tests: QR Code & Player Flow (Story 2.4)

Tests the complete QR code and player page workflow:
- QR code display in lobby
- Print button functionality
- Player page game validation
- Error states for invalid/ended games
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect


@pytest.mark.e2e
class TestQRCodeDisplay:
    """Tests for QR code display in lobby."""

    def test_qr_code_visible_in_lobby(
        self, page: Page, admin_page_url: str, mock_start_game: dict
    ) -> None:
        """QR code should be visible in lobby view."""
        page.goto(admin_page_url)
        page.wait_for_load_state("networkidle")

        # Start a game
        page.locator(".playlist-checkbox").first.click()
        page.locator(".media-player-radio").first.click()
        page.locator("#start-game").click()

        # QR code should be visible
        qr_code = page.locator("#qr-code")
        expect(qr_code).to_be_visible()

    def test_qr_code_has_content(
        self, page: Page, admin_page_url: str, mock_start_game: dict
    ) -> None:
        """QR code container should have generated content."""
        page.goto(admin_page_url)
        page.wait_for_load_state("networkidle")

        # Start a game
        page.locator(".playlist-checkbox").first.click()
        page.locator(".media-player-radio").first.click()
        page.locator("#start-game").click()

        # QR code should contain canvas or img element
        qr_code = page.locator("#qr-code")
        expect(qr_code.locator("canvas, img")).to_be_attached()

    def test_join_url_displayed(
        self, page: Page, admin_page_url: str, mock_start_game: dict
    ) -> None:
        """Join URL should be displayed below QR code."""
        page.goto(admin_page_url)
        page.wait_for_load_state("networkidle")

        # Start a game
        page.locator(".playlist-checkbox").first.click()
        page.locator(".media-player-radio").first.click()
        page.locator("#start-game").click()

        # Join URL should contain the game path
        join_url = page.locator("#join-url")
        expect(join_url).to_be_visible()
        expect(join_url).to_contain_text("/beatify/play?game=")

    def test_qr_code_has_aria_label(
        self, page: Page, admin_page_url: str, mock_start_game: dict
    ) -> None:
        """QR code should have accessibility label."""
        page.goto(admin_page_url)
        page.wait_for_load_state("networkidle")

        # Start a game
        page.locator(".playlist-checkbox").first.click()
        page.locator(".media-player-radio").first.click()
        page.locator("#start-game").click()

        # Check aria-label
        qr_code = page.locator("#qr-code")
        aria_label = qr_code.get_attribute("aria-label")
        assert aria_label is not None
        assert "QR" in aria_label or "qr" in aria_label.lower()


@pytest.mark.e2e
class TestPrintQRCode:
    """Tests for print QR code functionality."""

    def test_print_button_visible(
        self, page: Page, admin_page_url: str, mock_start_game: dict
    ) -> None:
        """Print button should be visible in lobby."""
        page.goto(admin_page_url)
        page.wait_for_load_state("networkidle")

        # Start a game
        page.locator(".playlist-checkbox").first.click()
        page.locator(".media-player-radio").first.click()
        page.locator("#start-game").click()

        # Print button should be visible
        print_btn = page.locator("#print-qr")
        expect(print_btn).to_be_visible()

    def test_print_button_enabled(
        self, page: Page, admin_page_url: str, mock_start_game: dict
    ) -> None:
        """Print button should be enabled."""
        page.goto(admin_page_url)
        page.wait_for_load_state("networkidle")

        # Start a game
        page.locator(".playlist-checkbox").first.click()
        page.locator(".media-player-radio").first.click()
        page.locator("#start-game").click()

        # Print button should be enabled
        print_btn = page.locator("#print-qr")
        expect(print_btn).to_be_enabled()


@pytest.mark.e2e
class TestPlayerPage:
    """Tests for player page game validation."""

    def test_player_page_loads(
        self, page: Page, player_page_url: str
    ) -> None:
        """Player page should load."""
        page.goto(player_page_url)
        page.wait_for_load_state("networkidle")

        # Main container should be present
        container = page.locator(".player-container")
        expect(container).to_be_visible()

    def test_invalid_game_id_shows_not_found(
        self, page: Page, player_page_url_invalid: str
    ) -> None:
        """Invalid game ID should show not found view."""
        page.goto(player_page_url_invalid)
        page.wait_for_load_state("networkidle")

        # Not found view should be visible
        not_found = page.locator("#not-found-view")
        expect(not_found).to_be_visible()

    def test_no_game_id_shows_not_found(
        self, page: Page, player_page_url_no_game: str
    ) -> None:
        """No game ID in URL should show not found view."""
        page.goto(player_page_url_no_game)
        page.wait_for_load_state("networkidle")

        # Not found view should be visible
        not_found = page.locator("#not-found-view")
        expect(not_found).to_be_visible()

    def test_valid_game_shows_join_view(
        self, page: Page, player_page_url_valid: str, mock_game_status_valid: dict
    ) -> None:
        """Valid game ID should show join view."""
        page.goto(player_page_url_valid)
        page.wait_for_load_state("networkidle")

        # Join view should be visible
        join_view = page.locator("#join-view")
        expect(join_view).to_be_visible()

    def test_ended_game_shows_ended_view(
        self, page: Page, player_page_url_ended: str, mock_game_status_ended: dict
    ) -> None:
        """Ended game should show ended view."""
        page.goto(player_page_url_ended)
        page.wait_for_load_state("networkidle")

        # Ended view should be visible
        ended_view = page.locator("#ended-view")
        expect(ended_view).to_be_visible()

    def test_refresh_button_exists(
        self, page: Page, player_page_url_invalid: str
    ) -> None:
        """Refresh button should exist on not found view."""
        page.goto(player_page_url_invalid)
        page.wait_for_load_state("networkidle")

        # Refresh button should be present
        refresh_btn = page.locator("#refresh-btn")
        expect(refresh_btn).to_be_visible()

    def test_refresh_button_clickable(
        self, page: Page, player_page_url_invalid: str
    ) -> None:
        """Refresh button should be clickable."""
        page.goto(player_page_url_invalid)
        page.wait_for_load_state("networkidle")

        # Refresh button should be enabled and clickable
        refresh_btn = page.locator("#refresh-btn")
        expect(refresh_btn).to_be_enabled()


@pytest.mark.e2e
class TestResponsiveQRCode:
    """Tests for responsive QR code sizing."""

    def test_qr_visible_on_mobile(
        self, page: Page, admin_page_url: str, mock_start_game: dict
    ) -> None:
        """QR code should be visible on mobile viewport."""
        # Set mobile viewport
        page.set_viewport_size({"width": 375, "height": 667})

        page.goto(admin_page_url)
        page.wait_for_load_state("networkidle")

        # Start a game
        page.locator(".playlist-checkbox").first.click()
        page.locator(".media-player-radio").first.click()
        page.locator("#start-game").click()

        # QR code should still be visible
        qr_code = page.locator("#qr-code")
        expect(qr_code).to_be_visible()

    def test_qr_visible_on_tablet(
        self, page: Page, admin_page_url: str, mock_start_game: dict
    ) -> None:
        """QR code should be visible on tablet viewport."""
        # Set tablet viewport
        page.set_viewport_size({"width": 768, "height": 1024})

        page.goto(admin_page_url)
        page.wait_for_load_state("networkidle")

        # Start a game
        page.locator(".playlist-checkbox").first.click()
        page.locator(".media-player-radio").first.click()
        page.locator("#start-game").click()

        # QR code should be visible
        qr_code = page.locator("#qr-code")
        expect(qr_code).to_be_visible()

    def test_qr_visible_on_desktop(
        self, page: Page, admin_page_url: str, mock_start_game: dict
    ) -> None:
        """QR code should be visible on desktop viewport."""
        # Set desktop viewport
        page.set_viewport_size({"width": 1920, "height": 1080})

        page.goto(admin_page_url)
        page.wait_for_load_state("networkidle")

        # Start a game
        page.locator(".playlist-checkbox").first.click()
        page.locator(".media-player-radio").first.click()
        page.locator("#start-game").click()

        # QR code should be visible
        qr_code = page.locator("#qr-code")
        expect(qr_code).to_be_visible()


@pytest.mark.e2e
class TestNameEntryForm:
    """Tests for name entry form (Story 3.1)."""

    def test_name_input_visible_and_focusable(
        self, page: Page, player_page_url_valid: str, mock_game_status_valid: dict
    ) -> None:
        """Name input should be visible and focusable when join view shows."""
        page.goto(player_page_url_valid)
        page.wait_for_load_state("networkidle")

        # Name input should be visible
        name_input = page.locator("#name-input")
        expect(name_input).to_be_visible()

        # Should be focusable
        name_input.focus()
        expect(name_input).to_be_focused()

    def test_join_button_disabled_with_empty_name(
        self, page: Page, player_page_url_valid: str, mock_game_status_valid: dict
    ) -> None:
        """Join button should be disabled when name is empty."""
        page.goto(player_page_url_valid)
        page.wait_for_load_state("networkidle")

        # Join button should be disabled initially
        join_btn = page.locator("#join-btn")
        expect(join_btn).to_be_disabled()

    def test_join_button_enabled_with_valid_name(
        self, page: Page, player_page_url_valid: str, mock_game_status_valid: dict
    ) -> None:
        """Join button should be enabled when valid name is entered."""
        page.goto(player_page_url_valid)
        page.wait_for_load_state("networkidle")

        # Enter a valid name
        name_input = page.locator("#name-input")
        name_input.fill("TestPlayer")

        # Join button should now be enabled
        join_btn = page.locator("#join-btn")
        expect(join_btn).to_be_enabled()

    def test_error_message_matches_ac3_text(
        self, page: Page, player_page_url_invalid: str
    ) -> None:
        """Error hint should match AC3: 'Ask the host for a new QR code.'"""
        page.goto(player_page_url_invalid)
        page.wait_for_load_state("networkidle")

        # Check the hint text matches AC3 exactly
        hint = page.locator("#not-found-view .hint")
        expect(hint).to_have_text("Ask the host for a new QR code.")

    def test_touch_targets_minimum_size(
        self, page: Page, player_page_url_valid: str, mock_game_status_valid: dict
    ) -> None:
        """Touch targets (input and button) should be at least 44px tall."""
        page.goto(player_page_url_valid)
        page.wait_for_load_state("networkidle")

        # Check name input height
        name_input = page.locator("#name-input")
        input_box = name_input.bounding_box()
        assert input_box is not None
        assert input_box["height"] >= 44, f"Name input height {input_box['height']}px is less than 44px"

        # Check join button height
        join_btn = page.locator("#join-btn")
        btn_box = join_btn.bounding_box()
        assert btn_box is not None
        assert btn_box["height"] >= 44, f"Join button height {btn_box['height']}px is less than 44px"

    def test_name_input_placeholder(
        self, page: Page, player_page_url_valid: str, mock_game_status_valid: dict
    ) -> None:
        """Name input should have 'Your name' placeholder."""
        page.goto(player_page_url_valid)
        page.wait_for_load_state("networkidle")

        name_input = page.locator("#name-input")
        placeholder = name_input.get_attribute("placeholder")
        assert placeholder == "Your name"

    def test_name_input_maxlength(
        self, page: Page, player_page_url_valid: str, mock_game_status_valid: dict
    ) -> None:
        """Name input should have maxlength of 20."""
        page.goto(player_page_url_valid)
        page.wait_for_load_state("networkidle")

        name_input = page.locator("#name-input")
        maxlength = name_input.get_attribute("maxlength")
        assert maxlength == "20"

    def test_validation_message_hidden_initially(
        self, page: Page, player_page_url_valid: str, mock_game_status_valid: dict
    ) -> None:
        """Validation message should be hidden initially."""
        page.goto(player_page_url_valid)
        page.wait_for_load_state("networkidle")

        validation_msg = page.locator("#name-validation-msg")
        expect(validation_msg).to_have_class(re.compile(r"hidden"))

    def test_mobile_viewport_form_visible(
        self, page: Page, player_page_url_valid: str, mock_game_status_valid: dict
    ) -> None:
        """Form should be visible and usable on 320px mobile viewport."""
        # Set narrow mobile viewport (320px width per Task 4.4)
        page.set_viewport_size({"width": 320, "height": 568})

        page.goto(player_page_url_valid)
        page.wait_for_load_state("networkidle")

        # Form elements should be visible
        name_input = page.locator("#name-input")
        join_btn = page.locator("#join-btn")

        expect(name_input).to_be_visible()
        expect(join_btn).to_be_visible()

        # Input should be usable
        name_input.fill("Player")
        expect(join_btn).to_be_enabled()


@pytest.mark.e2e
class TestWebSocketJoin:
    """Tests for WebSocket join functionality (Story 3.2)."""

    def test_join_button_shows_joining_state(
        self, page: Page, player_page_url_valid: str, mock_game_status_valid: dict
    ) -> None:
        """Join button should show 'Joining...' when clicked."""
        page.goto(player_page_url_valid)
        page.wait_for_load_state("networkidle")

        # Enter a valid name
        name_input = page.locator("#name-input")
        name_input.fill("TestPlayer")

        # Click join
        join_btn = page.locator("#join-btn")
        join_btn.click()

        # Button should show joining state
        expect(join_btn).to_have_text("Joining...")
        expect(join_btn).to_be_disabled()

    def test_lobby_view_exists(
        self, page: Page, player_page_url_valid: str, mock_game_status_valid: dict
    ) -> None:
        """Lobby view element should exist in the DOM."""
        page.goto(player_page_url_valid)
        page.wait_for_load_state("networkidle")

        # Lobby view should be present but hidden
        lobby_view = page.locator("#lobby-view")
        expect(lobby_view).to_be_hidden()

    def test_lobby_placeholder_content(
        self, page: Page, player_page_url_valid: str, mock_game_status_valid: dict
    ) -> None:
        """Lobby placeholder should have expected content."""
        page.goto(player_page_url_valid)
        page.wait_for_load_state("networkidle")

        # Check lobby placeholder elements exist
        lobby_view = page.locator("#lobby-view")

        # Even though hidden, elements should exist
        h1 = lobby_view.locator(".lobby-placeholder h1")
        expect(h1).to_have_text("Welcome to the Lobby!")

    def test_validation_msg_shows_on_error(
        self, page: Page, player_page_url_valid: str, mock_game_status_valid: dict
    ) -> None:
        """Validation message container should be available for error display."""
        page.goto(player_page_url_valid)
        page.wait_for_load_state("networkidle")

        # Validation message element should exist
        validation_msg = page.locator("#name-validation-msg")
        expect(validation_msg).to_be_attached()
