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
from playwright.async_api import Page, expect


@pytest.mark.e2e
class TestStartGameButton:
    """Tests for start game button state."""

    async def test_start_button_disabled_without_selections(
        self, page: Page, admin_page_url: str
    ) -> None:
        """Start button should be disabled when no playlist or media player selected."""
        await page.goto(admin_page_url)
        await page.wait_for_load_state("networkidle")

        start_button = page.locator("#start-game")
        await expect(start_button).to_be_disabled()

    async def test_start_button_disabled_with_only_playlist(
        self, page: Page, admin_page_url: str, mock_status_with_playlists: dict
    ) -> None:
        """Start button should be disabled when only playlist is selected."""
        await page.goto(admin_page_url)
        await page.wait_for_load_state("networkidle")

        # Select first playlist
        await page.locator(".playlist-checkbox").first.click()

        start_button = page.locator("#start-game")
        await expect(start_button).to_be_disabled()

    async def test_start_button_disabled_with_only_media_player(
        self, page: Page, admin_page_url: str, mock_status_with_media_players: dict
    ) -> None:
        """Start button should be disabled when only media player is selected."""
        await page.goto(admin_page_url)
        await page.wait_for_load_state("networkidle")

        # Select first media player
        await page.locator(".media-player-radio").first.click()

        start_button = page.locator("#start-game")
        await expect(start_button).to_be_disabled()

    async def test_start_button_enabled_with_both_selections(
        self, page: Page, admin_page_url: str, mock_status_full: dict
    ) -> None:
        """Start button should be enabled when both playlist and media player selected."""
        await page.goto(admin_page_url)
        await page.wait_for_load_state("networkidle")

        # Select playlist and media player
        await page.locator(".playlist-checkbox").first.click()
        await page.locator(".media-player-radio").first.click()

        start_button = page.locator("#start-game")
        await expect(start_button).to_be_enabled()


@pytest.mark.e2e
class TestStartGameTransition:
    """Tests for game start and lobby transition."""

    async def test_start_game_shows_lobby_view(
        self, page: Page, admin_page_url: str, mock_start_game: dict
    ) -> None:
        """Clicking start game should transition to lobby view."""
        await page.goto(admin_page_url)
        await page.wait_for_load_state("networkidle")

        # Make selections
        await page.locator(".playlist-checkbox").first.click()
        await page.locator(".media-player-radio").first.click()

        # Click start game
        await page.locator("#start-game").click()

        # Wait for lobby section to be visible
        await expect(page.locator("#lobby-section")).to_be_visible()
        await expect(page.locator("#ma-status")).to_be_hidden()

    async def test_start_game_shows_qr_code(
        self, page: Page, admin_page_url: str, mock_start_game: dict
    ) -> None:
        """Lobby view should display QR code."""
        await page.goto(admin_page_url)
        await page.wait_for_load_state("networkidle")

        # Make selections and start game
        await page.locator(".playlist-checkbox").first.click()
        await page.locator(".media-player-radio").first.click()
        await page.locator("#start-game").click()

        # QR code container should have content
        qr_code = page.locator("#qr-code")
        await expect(qr_code).to_be_visible()
        # QRCode library generates either canvas or img element
        await expect(qr_code.locator("canvas, img")).to_be_attached()

    async def test_start_game_shows_join_url(
        self, page: Page, admin_page_url: str, mock_start_game: dict
    ) -> None:
        """Lobby view should display join URL."""
        await page.goto(admin_page_url)
        await page.wait_for_load_state("networkidle")

        # Make selections and start game
        await page.locator(".playlist-checkbox").first.click()
        await page.locator(".media-player-radio").first.click()
        await page.locator("#start-game").click()

        # Join URL should be displayed
        join_url = page.locator("#join-url")
        await expect(join_url).to_be_visible()
        await expect(join_url).to_contain_text("/beatify/play?game=")


@pytest.mark.e2e
class TestExistingGame:
    """Tests for existing game detection and handling."""

    async def test_page_reload_shows_existing_game(
        self, page: Page, admin_page_url: str, mock_status_with_active_game: dict
    ) -> None:
        """Page reload with active game should show existing game options."""
        await page.goto(admin_page_url)
        await page.wait_for_load_state("networkidle")

        # Should show existing game section
        await expect(page.locator("#existing-game-section")).to_be_visible()
        await expect(page.locator("#ma-status")).to_be_hidden()

    async def test_existing_game_shows_game_info(
        self, page: Page, admin_page_url: str, mock_status_with_active_game: dict
    ) -> None:
        """Existing game view should show game info."""
        await page.goto(admin_page_url)
        await page.wait_for_load_state("networkidle")

        # Game info should be displayed
        await expect(page.locator("#existing-game-id")).to_be_visible()
        await expect(page.locator("#existing-game-phase")).to_contain_text("LOBBY")

    async def test_rejoin_game_shows_lobby(
        self, page: Page, admin_page_url: str, mock_status_with_active_game: dict
    ) -> None:
        """Clicking rejoin should show lobby view."""
        await page.goto(admin_page_url)
        await page.wait_for_load_state("networkidle")

        # Click rejoin
        await page.locator("#rejoin-game").click()

        # Should show lobby
        await expect(page.locator("#lobby-section")).to_be_visible()


@pytest.mark.e2e
class TestEndGame:
    """Tests for ending a game."""

    async def test_end_game_returns_to_setup(
        self, page: Page, admin_page_url: str, mock_end_game: dict
    ) -> None:
        """Ending game should return to setup view."""
        await page.goto(admin_page_url)
        await page.wait_for_load_state("networkidle")

        # Make selections and start game first
        await page.locator(".playlist-checkbox").first.click()
        await page.locator(".media-player-radio").first.click()
        await page.locator("#start-game").click()
        await expect(page.locator("#lobby-section")).to_be_visible()

        # Accept confirmation dialog
        page.on("dialog", lambda dialog: dialog.accept())

        # End game from lobby
        await page.locator("#end-game-lobby").click()

        # Should return to setup view
        await expect(page.locator("#ma-status")).to_be_visible()
        await expect(page.locator("#lobby-section")).to_be_hidden()


@pytest.mark.e2e
class TestPrintQRCode:
    """Tests for print QR code functionality."""

    async def test_print_button_exists(
        self, page: Page, admin_page_url: str, mock_start_game: dict
    ) -> None:
        """Print button should be visible in lobby view."""
        await page.goto(admin_page_url)
        await page.wait_for_load_state("networkidle")

        # Start game
        await page.locator(".playlist-checkbox").first.click()
        await page.locator(".media-player-radio").first.click()
        await page.locator("#start-game").click()

        # Print button should be visible
        await expect(page.locator("#print-qr")).to_be_visible()

    async def test_print_button_clickable(
        self, page: Page, admin_page_url: str, mock_start_game: dict
    ) -> None:
        """Print button should be clickable."""
        await page.goto(admin_page_url)
        await page.wait_for_load_state("networkidle")

        # Start game
        await page.locator(".playlist-checkbox").first.click()
        await page.locator(".media-player-radio").first.click()
        await page.locator("#start-game").click()

        # Print button should be enabled
        print_button = page.locator("#print-qr")
        await expect(print_button).to_be_enabled()
