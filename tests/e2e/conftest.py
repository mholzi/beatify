"""
E2E Test Fixtures for Playwright Browser Tests.

Uses Playwright SYNC API (provided by pytest-playwright).
All fixtures and tests use synchronous page interactions.
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, Route

# =============================================================================
# URL FIXTURES
# =============================================================================


@pytest.fixture(scope="session")
def base_url() -> str:
    """Base URL for the test server."""
    return "http://localhost:8123"


@pytest.fixture
def admin_page_url(base_url: str) -> str:
    """Admin page URL."""
    return f"{base_url}/beatify/admin"


@pytest.fixture
def player_page_url(base_url: str) -> str:
    """Player page URL with a test game ID."""
    return f"{base_url}/beatify/play?game=test123abc"


@pytest.fixture
def player_page_url_invalid(base_url: str) -> str:
    """Player page URL with invalid game ID."""
    return f"{base_url}/beatify/play?game=invalid123"


@pytest.fixture
def player_page_url_no_game(base_url: str) -> str:
    """Player page URL without game parameter."""
    return f"{base_url}/beatify/play"


@pytest.fixture
def player_page_url_valid(base_url: str) -> str:
    """Player page URL with a valid game ID."""
    return f"{base_url}/beatify/play?game=validgame1"


@pytest.fixture
def player_page_url_ended(base_url: str) -> str:
    """Player page URL with ended game ID."""
    return f"{base_url}/beatify/play?game=endedgame1"


# =============================================================================
# MOCK STATUS RESPONSES
# =============================================================================


def create_base_status() -> dict:
    """Create base status response."""
    return {
        "ma_configured": True,
        "ma_setup_url": "https://docs.example.com/ma-setup",
        "playlist_docs_url": "https://docs.example.com/playlists",
        "media_player_docs_url": "https://docs.example.com/media-players",
        "playlist_dir": "/config/beatify/playlists",
        "media_players": [],
        "playlists": [],
        "active_game": None,
    }


@pytest.fixture
def mock_status_with_playlists():
    """Mock status API with playlists available."""

    def handle_route(route: Route) -> None:
        if "/beatify/api/status" in route.request.url:
            status = create_base_status()
            status["playlists"] = [
                {"path": "80s-hits.json", "name": "80s Hits", "song_count": 20, "is_valid": True, "errors": []},
                {"path": "90s-pop.json", "name": "90s Pop", "song_count": 15, "is_valid": True, "errors": []},
            ]
            route.fulfill(json=status)
        else:
            route.continue_()

    return handle_route


@pytest.fixture
def mock_status_with_media_players():
    """Mock status API with media players available."""

    def handle_route(route: Route) -> None:
        if "/beatify/api/status" in route.request.url:
            status = create_base_status()
            status["media_players"] = [
                {"entity_id": "media_player.living_room", "friendly_name": "Living Room Speaker", "state": "idle"},
                {"entity_id": "media_player.kitchen", "friendly_name": "Kitchen Speaker", "state": "playing"},
            ]
            route.fulfill(json=status)
        else:
            route.continue_()

    return handle_route


@pytest.fixture
def mock_status_full():
    """Mock status API with both playlists and media players."""

    def handle_route(route: Route) -> None:
        if "/beatify/api/status" in route.request.url:
            status = create_base_status()
            status["playlists"] = [
                {"path": "80s-hits.json", "name": "80s Hits", "song_count": 20, "is_valid": True, "errors": []},
            ]
            status["media_players"] = [
                {"entity_id": "media_player.living_room", "friendly_name": "Living Room Speaker", "state": "idle"},
            ]
            route.fulfill(json=status)
        else:
            route.continue_()

    return handle_route


@pytest.fixture
def mock_status_with_active_game():
    """Mock status API with an active game."""

    def handle_route(route: Route) -> None:
        if "/beatify/api/status" in route.request.url:
            status = create_base_status()
            status["playlists"] = [
                {"path": "80s-hits.json", "name": "80s Hits", "song_count": 20, "is_valid": True, "errors": []},
            ]
            status["media_players"] = [
                {"entity_id": "media_player.living_room", "friendly_name": "Living Room Speaker", "state": "idle"},
            ]
            status["active_game"] = {
                "game_id": "test123abc",
                "phase": "LOBBY",
                "player_count": 0,
                "join_url": "http://localhost:8123/beatify/play?game=test123abc",
            }
            route.fulfill(json=status)
        else:
            route.continue_()

    return handle_route


# =============================================================================
# MOCK GAME API RESPONSES
# =============================================================================


@pytest.fixture
def mock_start_game():
    """Mock start game API and status API."""

    def handle_route(route: Route) -> None:
        url = route.request.url

        if "/beatify/api/start-game" in url:
            route.fulfill(
                json={
                    "game_id": "newgame123",
                    "join_url": "http://localhost:8123/beatify/play?game=newgame123",
                    "phase": "LOBBY",
                    "song_count": 20,
                    "warnings": [],
                }
            )
        elif "/beatify/api/status" in url:
            status = create_base_status()
            status["playlists"] = [
                {"path": "80s-hits.json", "name": "80s Hits", "song_count": 20, "is_valid": True, "errors": []},
            ]
            status["media_players"] = [
                {"entity_id": "media_player.living_room", "friendly_name": "Living Room Speaker", "state": "idle"},
            ]
            route.fulfill(json=status)
        else:
            route.continue_()

    return handle_route


@pytest.fixture
def mock_end_game():
    """Mock end game API and related APIs."""

    def handle_route(route: Route) -> None:
        url = route.request.url

        if "/beatify/api/end-game" in url:
            route.fulfill(json={"success": True})
        elif "/beatify/api/start-game" in url:
            route.fulfill(
                json={
                    "game_id": "newgame123",
                    "join_url": "http://localhost:8123/beatify/play?game=newgame123",
                    "phase": "LOBBY",
                    "song_count": 20,
                    "warnings": [],
                }
            )
        elif "/beatify/api/status" in url:
            status = create_base_status()
            status["playlists"] = [
                {"path": "80s-hits.json", "name": "80s Hits", "song_count": 20, "is_valid": True, "errors": []},
            ]
            status["media_players"] = [
                {"entity_id": "media_player.living_room", "friendly_name": "Living Room Speaker", "state": "idle"},
            ]
            route.fulfill(json=status)
        else:
            route.continue_()

    return handle_route


# =============================================================================
# MOCK GAME STATUS API (for player page)
# =============================================================================


@pytest.fixture
def mock_game_status_valid():
    """Mock game status API returning valid game."""

    def handle_route(route: Route) -> None:
        if "/beatify/api/game-status" in route.request.url:
            route.fulfill(
                json={
                    "exists": True,
                    "phase": "LOBBY",
                    "can_join": True,
                }
            )
        else:
            route.continue_()

    return handle_route


@pytest.fixture
def mock_game_status_ended():
    """Mock game status API returning ended game."""

    def handle_route(route: Route) -> None:
        if "/beatify/api/game-status" in route.request.url:
            route.fulfill(
                json={
                    "exists": True,
                    "phase": "END",
                    "can_join": False,
                }
            )
        else:
            route.continue_()

    return handle_route


# =============================================================================
# ROUTE SETUP FIXTURE
# =============================================================================


@pytest.fixture(autouse=True)
def setup_routes(page: Page, request):
    """
    Auto-setup routes based on test fixtures.

    Checks if the test uses any mock_* fixtures and automatically
    sets up the Playwright route handlers.
    """
    fixture_names = request.fixturenames

    mock_fixtures = [
        "mock_status_with_playlists",
        "mock_status_with_media_players",
        "mock_status_full",
        "mock_status_with_active_game",
        "mock_start_game",
        "mock_end_game",
        "mock_game_status_valid",
        "mock_game_status_ended",
    ]

    for fixture_name in fixture_names:
        if fixture_name in mock_fixtures:
            handler = request.getfixturevalue(fixture_name)
            page.route("**/*", handler)
            break

    yield

    page.unroute("**/*")
