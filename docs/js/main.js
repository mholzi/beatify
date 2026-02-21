/**
 * Beatify - GitHub Pages JavaScript
 * Minimal vanilla JS for dynamic badges and interactions
 */

(function() {
  'use strict';

  // Smooth scroll for anchor links (fallback for browsers without CSS scroll-behavior)
  function initSmoothScroll() {
    document.querySelectorAll('a[href^="#"]').forEach(function(anchor) {
      anchor.addEventListener('click', function(e) {
        var targetId = this.getAttribute('href');
        if (targetId === '#') return;

        var target = document.querySelector(targetId);
        if (target) {
          e.preventDefault();
          target.scrollIntoView({
            behavior: 'smooth',
            block: 'start'
          });

          // Update URL without scrolling
          if (history.pushState) {
            history.pushState(null, null, targetId);
          }
        }
      });
    });
  }

  // Add loading state to badge images
  function initBadgeLoading() {
    var badges = document.querySelectorAll('.badges-row img');
    badges.forEach(function(badge) {
      badge.addEventListener('load', function() {
        this.style.opacity = '1';
      });
      badge.addEventListener('error', function() {
        // Hide broken badges gracefully
        this.style.display = 'none';
      });
    });
  }

  // Initialize when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function() {
      initSmoothScroll();
      initBadgeLoading();
    });
  } else {
    initSmoothScroll();
    initBadgeLoading();
  }
})();
