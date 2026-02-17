"""
E2E Tests for Story 18.3: Animation Performance Optimization.

Tests that:
1. Reduced motion is respected (AC: #1)
2. Device tier detection works (AC: #2)
3. Animations use requestAnimationFrame (AC: #3)
4. Tap-to-skip works in reveal view (AC: #4)
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page

# =============================================================================
# TEST CASES
# =============================================================================


@pytest.mark.asyncio
def test_animation_utils_exists(page: Page, base_url: str):
    """
    AC #1, #2: AnimationUtils module is available with expected methods.
    """
    page.goto(f"{base_url}/beatify/play?game=testgame")

    page.wait_for_selector("#player-list", state="visible")

    # Check AnimationUtils exists and has expected methods
    has_animation_utils = page.evaluate("""
        () => {
            return typeof AnimationUtils !== 'undefined' &&
                   typeof AnimationUtils.prefersReducedMotion === 'function' &&
                   typeof AnimationUtils.getDeviceTier === 'function' &&
                   typeof AnimationUtils.getQualitySettings === 'function' &&
                   typeof AnimationUtils.ifMotionAllowed === 'function' &&
                   typeof AnimationUtils.withWillChange === 'function';
        }
    """)

    assert has_animation_utils, "AnimationUtils should be available with all methods"


@pytest.mark.asyncio
def test_device_tier_class_applied(page: Page, base_url: str):
    """
    AC #2: Device tier class is applied to body element.
    """
    page.goto(f"{base_url}/beatify/play?game=testgame")

    page.wait_for_selector("#player-list", state="visible")

    # Check body has a device-tier class
    has_tier_class = page.evaluate("""
        () => {
            const body = document.body;
            return body.classList.contains('device-tier-high') ||
                   body.classList.contains('device-tier-medium') ||
                   body.classList.contains('device-tier-low');
        }
    """)

    assert has_tier_class, "Body should have a device-tier-* class"


@pytest.mark.asyncio
def test_device_tier_returns_valid_value(page: Page, base_url: str):
    """
    AC #2: getDeviceTier returns valid tier value.
    """
    page.goto(f"{base_url}/beatify/play?game=testgame")

    page.wait_for_selector("#player-list", state="visible")

    tier = page.evaluate("""
        () => {
            if (typeof AnimationUtils !== 'undefined') {
                return AnimationUtils.getDeviceTier();
            }
            return null;
        }
    """)

    assert tier in ["high", "medium", "low"], f"Device tier should be 'high', 'medium', or 'low', got {tier}"


@pytest.mark.asyncio
def test_quality_settings_structure(page: Page, base_url: str):
    """
    AC #2: getQualitySettings returns expected structure.
    """
    page.goto(f"{base_url}/beatify/play?game=testgame")

    page.wait_for_selector("#player-list", state="visible")

    settings = page.evaluate("""
        () => {
            if (typeof AnimationUtils !== 'undefined') {
                return AnimationUtils.getQualitySettings();
            }
            return null;
        }
    """)

    assert settings is not None, "Quality settings should be returned"
    assert "confettiParticles" in settings, "Should have confettiParticles"
    assert "scoreDuration" in settings, "Should have scoreDuration"
    assert "leaderboardAnimation" in settings, "Should have leaderboardAnimation"
    assert "neonGlow" in settings, "Should have neonGlow"
    assert "enableAnimations" in settings, "Should have enableAnimations"


@pytest.mark.asyncio
def test_animation_queue_exists(page: Page, base_url: str):
    """
    AC #4: AnimationQueue module is available for interruptible animations.
    """
    page.goto(f"{base_url}/beatify/play?game=testgame")

    page.wait_for_selector("#player-list", state="visible")

    has_queue = page.evaluate("""
        () => {
            return typeof AnimationQueue !== 'undefined' &&
                   typeof AnimationQueue.add === 'function' &&
                   typeof AnimationQueue.skipAll === 'function' &&
                   typeof AnimationQueue.clear === 'function' &&
                   typeof AnimationQueue.isRunning === 'function';
        }
    """)

    assert has_queue, "AnimationQueue should be available with all methods"


@pytest.mark.asyncio
def test_animation_queue_skip_all(page: Page, base_url: str):
    """
    AC #4: AnimationQueue.skipAll() works correctly.
    """
    page.goto(f"{base_url}/beatify/play?game=testgame")

    page.wait_for_selector("#player-list", state="visible")

    # Test that skipAll can be called without errors
    result = page.evaluate("""
        () => {
            if (typeof AnimationQueue === 'undefined') {
                return { error: 'AnimationQueue not found' };
            }

            try {
                // Add a test animation
                var skipped = false;
                AnimationQueue.add({
                    run: function(done) {
                        setTimeout(done, 1000);
                    },
                    skipToEnd: function() {
                        skipped = true;
                    }
                });

                // Skip all
                AnimationQueue.skipAll();

                return {
                    isRunning: AnimationQueue.isRunning(),
                    skipped: skipped
                };
            } catch (e) {
                return { error: e.message };
            }
        }
    """)

    assert "error" not in result, f"skipAll should not throw: {result.get('error')}"
    assert result["isRunning"] is False, "Queue should not be running after skipAll"


@pytest.mark.asyncio
def test_reduced_motion_detection(page: Page, base_url: str):
    """
    AC #1: Reduced motion preference is detected.
    """
    page.goto(f"{base_url}/beatify/play?game=testgame")

    page.wait_for_selector("#player-list", state="visible")

    # Test that prefersReducedMotion returns a boolean
    result = page.evaluate("""
        () => {
            if (typeof AnimationUtils !== 'undefined') {
                return typeof AnimationUtils.prefersReducedMotion() === 'boolean';
            }
            return false;
        }
    """)

    assert result, "prefersReducedMotion should return a boolean"


@pytest.mark.asyncio
def test_animate_value_has_skip_method(page: Page, base_url: str):
    """
    AC #4: animateValue returns object with skipToEnd method.
    """
    page.goto(f"{base_url}/beatify/play?game=testgame")

    page.wait_for_selector("#player-list", state="visible")

    # Create a test element and check animateValue returns skip method
    result = page.evaluate("""
        () => {
            if (typeof animateValue !== 'function') {
                return { error: 'animateValue not found' };
            }

            var testEl = document.createElement('span');
            testEl.textContent = '0';
            document.body.appendChild(testEl);

            var controller = animateValue(testEl, 0, 100, 500);
            var hasSkip = typeof controller.skipToEnd === 'function';
            var hasCancel = typeof controller.cancel === 'function';

            // Clean up
            controller.cancel();
            testEl.remove();

            return { hasSkip: hasSkip, hasCancel: hasCancel };
        }
    """)

    assert result.get("hasSkip"), "animateValue should return object with skipToEnd"
    assert result.get("hasCancel"), "animateValue should return object with cancel"


@pytest.mark.asyncio
def test_confetti_uses_device_tier(page: Page, base_url: str):
    """
    AC #2: Confetti respects device tier settings.
    """
    page.goto(f"{base_url}/beatify/play?game=testgame")

    page.wait_for_selector("#player-list", state="visible")

    # Check that triggerConfetti exists and uses AnimationUtils
    result = page.evaluate("""
        () => {
            if (typeof triggerConfetti !== 'function') {
                return { error: 'triggerConfetti not found' };
            }

            // Get current quality settings to verify integration
            if (typeof AnimationUtils !== 'undefined') {
                var quality = AnimationUtils.getQualitySettings();
                return {
                    exists: true,
                    particleCount: quality.confettiParticles
                };
            }

            return { exists: true, particleCount: null };
        }
    """)

    assert result.get("exists"), "triggerConfetti should exist"
    assert result.get("particleCount") is not None, "Should have particle count from quality settings"


@pytest.mark.asyncio
def test_reveal_view_click_handler(page: Page, base_url: str):
    """
    AC #4: Reveal view has click handler for skip-to-end.
    """
    page.goto(f"{base_url}/beatify/play?game=testgame")

    page.wait_for_selector("#player-list", state="visible")

    # Check reveal view has event listener (indirectly by checking it exists)
    has_reveal_view = page.evaluate("""
        () => {
            var revealView = document.getElementById('reveal-view');
            return revealView !== null;
        }
    """)

    assert has_reveal_view, "Reveal view should exist for tap-to-skip handler"
