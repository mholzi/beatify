"""
E2E Tests: Start Game Flow (Story 2.3)

Tests the complete start game workflow:
- Start button state management
- Transition to lobby view
- QR code generation and display
- Existing game detection
- End game functionality
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect


@pytest.mark.e2e
class TestStartGameButton:
    """Tests for start game button state."""

    def test_start_button_disabled_without_selections(
        self, page: Page, admin_page_url: str
    ) -> None:
        """Start button should be disabled when no playlist or media player selected."""
        page.goto(admin_page_url)
        page.wait_for_load_state("networkidle")

        start_button = page.locator("#start-game")
        expect(start_button).to_be_disabled()

    def test_start_button_disabled_with_only_playlist(
        self, page: Page, admin_page_url: str, mock_status_with_playlists: dict
    ) -> None:
        """Start button should be disabled when only playlist is selected."""
        page.goto(admin_page_url)
        page.wait_for_load_state("networkidle")

        # Select first playlist
        page.locator(".playlist-checkbox").first.click()

        start_button = page.locator("#start-game")
        expect(start_button).to_be_disabled()

    def test_start_button_disabled_with_only_media_player(
        self, page: Page, admin_page_url: str, mock_status_with_media_players: dict
    ) -> None:
        """Start button should be disabled when only media player is selected."""
        page.goto(admin_page_url)
        page.wait_for_load_state("networkidle")

        # Select first media player
        page.locator(".media-player-radio").first.click()

        start_button = page.locator("#start-game")
        expect(start_button).to_be_disabled()

    def test_start_button_enabled_with_both_selections(
        self, page: Page, admin_page_url: str, mock_status_full: dict
    ) -> None:
        """Start button should be enabled when both playlist and media player selected."""
        page.goto(admin_page_url)
        page.wait_for_load_state("networkidle")

        # Select playlist and media player
        page.locator(".playlist-checkbox").first.click()
        page.locator(".media-player-radio").first.click()

        start_button = page.locator("#start-game")
        expect(start_button).to_be_enabled()


@pytest.mark.e2e
class TestStartGameTransition:
    """Tests for game start and lobby transition."""

    def test_start_game_shows_lobby_view(
        self, page: Page, admin_page_url: str, mock_start_game: dict
    ) -> None:
        """Clicking start game should transition to lobby view."""
        page.goto(admin_page_url)
        page.wait_for_load_state("networkidle")

        # Make selections
        page.locator(".playlist-checkbox").first.click()
        page.locator(".media-player-radio").first.click()

        # Click start game
        page.locator("#start-game").click()

        # Wait for lobby section to be visible
        expect(page.locator("#lobby-section")).to_be_visible()
        expect(page.locator("#ma-status")).to_be_hidden()

    def test_start_game_shows_qr_code(
        self, page: Page, admin_page_url: str, mock_start_game: dict
    ) -> None:
        """Lobby view should display QR code."""
        page.goto(admin_page_url)
        page.wait_for_load_state("networkidle")

        # Make selections and start game
        page.locator(".playlist-checkbox").first.click()
        page.locator(".media-player-radio").first.click()
        page.locator("#start-game").click()

        # QR code container should have content
        qr_code = page.locator("#qr-code")
        expect(qr_code).to_be_visible()
        # QRCode library generates either canvas or img element
        expect(qr_code.locator("canvas, img")).to_be_attached()

    def test_start_game_shows_join_url(
        self, page: Page, admin_page_url: str, mock_start_game: dict
    ) -> None:
        """Lobby view should display join URL."""
        page.goto(admin_page_url)
        page.wait_for_load_state("networkidle")

        # Make selections and start game
        page.locator(".playlist-checkbox").first.click()
        page.locator(".media-player-radio").first.click()
        page.locator("#start-game").click()

        # Join URL should be displayed
        join_url = page.locator("#join-url")
        expect(join_url).to_be_visible()
        expect(join_url).to_contain_text("/beatify/play?game=")


@pytest.mark.e2e
class TestExistingGame:
    """Tests for existing game detection and handling."""

    def test_page_reload_shows_existing_game(
        self, page: Page, admin_page_url: str, mock_status_with_active_game: dict
    ) -> None:
        """Page reload with active game should show existing game options."""
        page.goto(admin_page_url)
        page.wait_for_load_state("networkidle")

        # Should show existing game section
        expect(page.locator("#existing-game-section")).to_be_visible()
        expect(page.locator("#ma-status")).to_be_hidden()

    def test_existing_game_shows_game_info(
        self, page: Page, admin_page_url: str, mock_status_with_active_game: dict
    ) -> None:
        """Existing game view should show game info."""
        page.goto(admin_page_url)
        page.wait_for_load_state("networkidle")

        # Game info should be displayed
        expect(page.locator("#existing-game-id")).to_be_visible()
        expect(page.locator("#existing-game-phase")).to_contain_text("LOBBY")

    def test_rejoin_game_shows_lobby(
        self, page: Page, admin_page_url: str, mock_status_with_active_game: dict
    ) -> None:
        """Clicking rejoin should show lobby view."""
        page.goto(admin_page_url)
        page.wait_for_load_state("networkidle")

        # Click rejoin
        page.locator("#rejoin-game").click()

        # Should show lobby
        expect(page.locator("#lobby-section")).to_be_visible()


@pytest.mark.e2e
class TestEndGame:
    """Tests for ending a game."""

    def test_end_game_returns_to_setup(
        self, page: Page, admin_page_url: str, mock_end_game: dict
    ) -> None:
        """Ending game should return to setup view."""
        page.goto(admin_page_url)
        page.wait_for_load_state("networkidle")

        # Make selections and start game first
        page.locator(".playlist-checkbox").first.click()
        page.locator(".media-player-radio").first.click()
        page.locator("#start-game").click()
        expect(page.locator("#lobby-section")).to_be_visible()

        # Accept confirmation dialog
        page.on("dialog", lambda dialog: dialog.accept())

        # End game from lobby
        page.locator("#end-game-lobby").click()

        # Should return to setup view
        expect(page.locator("#ma-status")).to_be_visible()
        expect(page.locator("#lobby-section")).to_be_hidden()


@pytest.mark.e2e
class TestPrintQRCode:
    """Tests for print QR code functionality."""

    def test_print_button_exists(
        self, page: Page, admin_page_url: str, mock_start_game: dict
    ) -> None:
        """Print button should be visible in lobby view."""
        page.goto(admin_page_url)
        page.wait_for_load_state("networkidle")

        # Start game
        page.locator(".playlist-checkbox").first.click()
        page.locator(".media-player-radio").first.click()
        page.locator("#start-game").click()

        # Print button should be visible
        expect(page.locator("#print-qr")).to_be_visible()

    def test_print_button_clickable(
        self, page: Page, admin_page_url: str, mock_start_game: dict
    ) -> None:
        """Print button should be clickable."""
        page.goto(admin_page_url)
        page.wait_for_load_state("networkidle")

        # Start game
        page.locator(".playlist-checkbox").first.click()
        page.locator(".media-player-radio").first.click()
        page.locator("#start-game").click()

        # Print button should be enabled
        print_button = page.locator("#print-qr")
        expect(print_button).to_be_enabled()
