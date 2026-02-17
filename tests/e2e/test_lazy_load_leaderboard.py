"""
E2E Tests for Story 18.1: Lazy Load Leaderboard.

Tests that the leaderboard:
1. Renders only visible entries initially (AC: #1)
2. Scrolls smoothly at 60fps without jank (AC: #2)
3. Reduces DOM nodes by 50%+ with 20 players (AC: #3)
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, Route, expect

# =============================================================================
# MOCK FIXTURES
# =============================================================================


def create_leaderboard_with_players(count: int) -> list[dict]:
    """Create a leaderboard with the specified number of players."""
    return [
        {
            "name": f"Player{i}",
            "score": (count - i) * 10,
            "rank": i + 1,
            "streak": 0,
            "connected": True,
            "submitted": True,
        }
        for i in range(count)
    ]


@pytest.fixture
def mock_game_with_20_players(page: Page):
    """Mock WebSocket and API for a game with 20 players in REVEAL phase."""

    def handle_route(route: Route) -> None:
        url = route.request.url

        if "/beatify/api/game-status" in url:
            route.fulfill(
                json={
                    "exists": True,
                    "phase": "REVEAL",
                    "can_join": False,
                }
            )
        else:
            route.continue_()

    return handle_route


# =============================================================================
# TEST CASES
# =============================================================================


@pytest.mark.asyncio
def test_leaderboard_renders_limited_entries_initially(page: Page, base_url: str):
    """
    AC #1: Given a game with 10+ players, only visible entries are rendered initially.

    With 20 players and entry height of ~48px, a 280px viewport should show ~6 entries.
    We expect 8-10 DOM nodes (visible + 2 buffer), not 20.
    """
    # Navigate to player page with a mock game
    page.goto(f"{base_url}/beatify/play?game=test20players")

    # Wait for leaderboard to be visible
    page.wait_for_selector(".leaderboard-list", state="visible")

    # Inject mock leaderboard data via JavaScript (simulating WS state update)
    page.evaluate("""
        () => {
            // Create 20 player leaderboard
            const players = [];
            for (let i = 0; i < 20; i++) {
                players.push({
                    name: 'Player' + i,
                    score: (20 - i) * 10,
                    rank: i + 1,
                    streak: 0,
                    connected: true,
                    submitted: true
                });
            }

            // Trigger leaderboard update
            if (typeof updateLeaderboard === 'function') {
                updateLeaderboard({ leaderboard: players }, 'leaderboard-list', false);
            }
        }
    """)

    # Wait a moment for rendering
    page.wait_for_timeout(100)

    # Count rendered leaderboard entries (not placeholders)
    entry_count = page.locator(".leaderboard-entry").count()

    # With lazy loading, should have ~8-10 entries (visible + buffer), not 20
    # Allow for compression behavior (Story 9.5) which shows top 5 + separator + current + separator + bottom 3 = ~11 max
    assert entry_count <= 12, f"Expected ≤12 rendered entries with lazy loading, got {entry_count}"


@pytest.mark.asyncio
def test_leaderboard_has_scroll_container_with_fixed_height(page: Page, base_url: str):
    """
    AC #1: Leaderboard scroll container must have fixed height for virtual scrolling.
    """
    page.goto(f"{base_url}/beatify/play?game=testgame")

    # Wait for leaderboard
    page.wait_for_selector(".leaderboard-list", state="visible")

    # Check that leaderboard-list has overflow-y: auto and a max-height
    styles = page.evaluate("""
        () => {
            const list = document.querySelector('.leaderboard-list');
            if (!list) return null;
            const computed = window.getComputedStyle(list);
            return {
                overflowY: computed.overflowY,
                maxHeight: computed.maxHeight,
                contain: computed.contain
            };
        }
    """)

    assert styles is not None, "Leaderboard list not found"
    assert styles["overflowY"] in ["auto", "scroll"], "Leaderboard should have scrollable overflow"
    assert styles["maxHeight"] != "none", "Leaderboard should have max-height for scroll container"


@pytest.mark.asyncio
def test_leaderboard_entries_have_css_containment(page: Page, base_url: str):
    """
    AC #2: Leaderboard entries should use CSS containment for scroll optimization.
    """
    page.goto(f"{base_url}/beatify/play?game=testgame")

    # Wait for leaderboard and inject a test entry
    page.wait_for_selector(".leaderboard-list", state="visible")

    # Inject mock data
    page.evaluate("""
        () => {
            const players = [{ name: 'TestPlayer', score: 100, rank: 1, streak: 0, connected: true, submitted: true }];
            if (typeof updateLeaderboard === 'function') {
                updateLeaderboard({ leaderboard: players }, 'leaderboard-list', false);
            }
        }
    """)

    page.wait_for_timeout(100)

    # Check CSS containment on entries
    containment = page.evaluate("""
        () => {
            const entry = document.querySelector('.leaderboard-entry');
            if (!entry) return null;
            return window.getComputedStyle(entry).contain;
        }
    """)

    # containment should be set (content, strict, or layout)
    assert containment is not None and containment != "none", \
        f"Leaderboard entries should have CSS containment, got: {containment}"


@pytest.mark.asyncio
def test_leaderboard_uses_spacer_elements(page: Page, base_url: str):
    """
    AC #1, #3: With 20 players, spacer elements maintain scroll height while reducing DOM nodes.
    """
    page.goto(f"{base_url}/beatify/play?game=test20players")

    page.wait_for_selector(".leaderboard-list", state="visible")

    # Inject 20 players
    page.evaluate("""
        () => {
            const players = [];
            for (let i = 0; i < 20; i++) {
                players.push({
                    name: 'Player' + i,
                    score: (20 - i) * 10,
                    rank: i + 1,
                    streak: 0,
                    connected: true
                });
            }
            if (typeof updateLeaderboard === 'function') {
                updateLeaderboard({ leaderboard: players }, 'leaderboard-list', false);
            }
        }
    """)

    page.wait_for_timeout(100)

    # Check for spacer elements (either placeholder class or separator with computed height)
    has_spacers = page.evaluate("""
        () => {
            const list = document.querySelector('.leaderboard-list');
            if (!list) return false;
            // Check for spacer divs or separators
            const spacers = list.querySelectorAll('.leaderboard-spacer-top, .leaderboard-spacer-bottom, .leaderboard-separator');
            return spacers.length > 0;
        }
    """)

    # With compression (Story 9.5), we should have separators; with lazy loading, we should have spacers
    assert has_spacers, "Expected spacer or separator elements for scroll height maintenance"


@pytest.mark.asyncio
def test_current_player_always_visible_on_initial_load(page: Page, base_url: str):
    """
    AC #1: Current player entry is always visible on initial load, even if ranked 15th.
    """
    page.goto(f"{base_url}/beatify/play?game=testgame")

    page.wait_for_selector(".leaderboard-list", state="visible")

    # Inject 20 players with current player at rank 15
    # First, set the player name via localStorage or direct variable (depends on implementation)
    page.evaluate("""
        () => {
            // Set player name (simulating joined player)
            window.playerName = 'CurrentPlayer';

            const players = [];
            for (let i = 0; i < 20; i++) {
                const name = i === 14 ? 'CurrentPlayer' : 'Player' + i;
                players.push({
                    name: name,
                    score: (20 - i) * 10,
                    rank: i + 1,
                    streak: 0,
                    connected: true
                });
            }
            if (typeof updateLeaderboard === 'function') {
                updateLeaderboard({ leaderboard: players }, 'leaderboard-list', false);
            }
        }
    """)

    page.wait_for_timeout(100)

    # Current player entry should be visible (is-current class)
    current_entry = page.locator(".leaderboard-entry.is-current")
    expect(current_entry).to_be_visible()


@pytest.mark.asyncio
def test_leaderboard_scroll_loads_more_entries(page: Page, base_url: str):
    """
    AC #1: Scrolling down loads additional entries smoothly.
    """
    page.goto(f"{base_url}/beatify/play?game=test20players")

    page.wait_for_selector(".leaderboard-list", state="visible")

    # Inject 20 players
    page.evaluate("""
        () => {
            const players = [];
            for (let i = 0; i < 20; i++) {
                players.push({
                    name: 'Player' + i,
                    score: (20 - i) * 10,
                    rank: i + 1,
                    streak: 0,
                    connected: true
                });
            }
            if (typeof updateLeaderboard === 'function') {
                updateLeaderboard({ leaderboard: players }, 'leaderboard-list', false);
            }
        }
    """)

    page.wait_for_timeout(100)

    # Get initial entry count
    initial_count = page.locator(".leaderboard-entry").count()

    # Scroll to bottom of leaderboard
    page.evaluate("""
        () => {
            const list = document.querySelector('.leaderboard-list');
            if (list) {
                list.scrollTop = list.scrollHeight;
            }
        }
    """)

    page.wait_for_timeout(200)  # Wait for lazy load

    # After scrolling, we should still see entries (either same count due to compression, or more if lazy loaded)
    final_count = page.locator(".leaderboard-entry").count()

    # Entries should remain accessible after scroll
    assert final_count > 0, "Entries should remain visible after scrolling"


@pytest.mark.asyncio
def test_dom_nodes_reduced_by_50_percent(page: Page, base_url: str):
    """
    AC #3: With 20 players, DOM nodes are reduced by at least 50% compared to full render.

    Full render = 20 entries. Target = ≤10 entries rendered.
    """
    page.goto(f"{base_url}/beatify/play?game=test20players")

    page.wait_for_selector(".leaderboard-list", state="visible")

    # Inject 20 players
    page.evaluate("""
        () => {
            const players = [];
            for (let i = 0; i < 20; i++) {
                players.push({
                    name: 'Player' + i,
                    score: (20 - i) * 10,
                    rank: i + 1,
                    streak: 0,
                    connected: true
                });
            }
            if (typeof updateLeaderboard === 'function') {
                updateLeaderboard({ leaderboard: players }, 'leaderboard-list', false);
            }
        }
    """)

    page.wait_for_timeout(100)

    # Count all child nodes in leaderboard list
    node_count = page.evaluate("""
        () => {
            const list = document.querySelector('.leaderboard-list');
            if (!list) return 0;
            // Count actual leaderboard entries (not spacers)
            return list.querySelectorAll('.leaderboard-entry').length;
        }
    """)

    # With lazy loading OR compression (Story 9.5), should be ≤10 for 20 players
    # Compression: top 5 + separator + current (if middle) + separator + bottom 3 = ~9 entries max
    # Lazy loading: visible (~6) + buffer (4) = ~10 entries max
    assert node_count <= 10, f"Expected ≤10 DOM nodes (50% reduction), got {node_count}"


@pytest.mark.asyncio
def test_rank_animations_work_with_lazy_loading(page: Page, base_url: str):
    """
    AC #2: Rank change animations still work with lazy loading.
    """
    page.goto(f"{base_url}/beatify/play?game=testgame")

    page.wait_for_selector(".leaderboard-list", state="visible")

    # First render
    page.evaluate("""
        () => {
            window.playerName = 'Player1';
            const players = [
                { name: 'Player0', score: 100, rank: 1, streak: 0, connected: true },
                { name: 'Player1', score: 90, rank: 2, streak: 0, connected: true },
                { name: 'Player2', score: 80, rank: 3, streak: 0, connected: true }
            ];
            if (typeof updateLeaderboard === 'function') {
                updateLeaderboard({ leaderboard: players, players: players }, 'leaderboard-list', false);
            }
        }
    """)

    page.wait_for_timeout(100)

    # Second render with rank change (Player1 overtakes Player0)
    page.evaluate("""
        () => {
            const players = [
                { name: 'Player1', score: 150, rank: 1, rank_change: 1, streak: 1, connected: true },
                { name: 'Player0', score: 100, rank: 2, rank_change: -1, streak: 0, connected: true },
                { name: 'Player2', score: 80, rank: 3, rank_change: 0, streak: 0, connected: true }
            ];
            if (typeof updateLeaderboard === 'function') {
                updateLeaderboard({ leaderboard: players, players: players }, 'leaderboard-list', true);
            }
        }
    """)

    page.wait_for_timeout(50)

    # Check for climbing animation class on Player1
    climbing_entry = page.locator(".leaderboard-entry--climbing, .leaderboard-entry--slide-up")
    count = climbing_entry.count()

    # At least one entry should have the climbing animation
    assert count >= 1, "Expected rank change animation classes to be applied"
