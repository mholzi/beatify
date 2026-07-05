/**
 * Regression test for #1184: the per-player dot-axis must actually render.
 *
 * The dot-axis (renderPlayerDotAxis) was originally wired into
 * renderRoundAnalytics(), which went dead at the v3.2.0 "Guess Duel" reveal
 * redesign (its only call site was removed) and has since been deleted. The
 * live reveal-v2 analytics surface is the round-stats bottom-sheet
 * (renderRoundStatsSheet), so the dot-axis must be emitted there. This test
 * fails if the wiring is removed again (dot-axis goes back to never rendering).
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

// vitest runs in node env — stub browser globals BEFORE importing the module
// so its top-level `var utils = window.BeatifyUtils || {};` doesn't throw.
let statsContentEl;
global.window = {
    BeatifyUtils: { t: (key) => key },
};
global.document = {
    getElementById: (id) => (id === 'round-stats-content' ? statsContentEl : null),
};

// Isolate player-reveal.js from its heavy DOM dependencies. Provide the
// named imports it actually uses in renderRoundStatsSheet: `state` and
// `escapeHtml`. The rest are referenced only inside other functions.
const mockState = { lastRevealContext: null, playerName: null };
vi.mock('../player-utils.js', () => ({
    state: mockState,
    escapeHtml: (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'),
    prefersReducedMotion: () => true,
    animateValue: () => {},
    animateScoreChange: () => {},
    showPointsPopup: () => {},
    previousState: {},
    isPreviousStateInitialized: () => false,
    isStreakMilestone: () => false,
    AnimationUtils: {},
    triggerConfetti: () => {},
    stopConfetti: () => {},
}));
vi.mock('../player-game.js', () => ({
    updateLeaderboard: () => {},
    renderArtistReveal: () => {},
    renderMovieReveal: () => {},
}));

const { renderRoundStatsSheet } = await import('../player-reveal.js');

describe('renderRoundStatsSheet — dot-axis wiring (#1184)', () => {
    beforeEach(() => {
        statsContentEl = { innerHTML: '' };
        mockState.playerName = 'Alice';
        mockState.lastRevealContext = {
            song: { year: 1990 },
            difficulty: null,
            analytics: {
                total_submitted: 2,
                average_guess: 1991,
                all_guesses: [
                    { name: 'Alice', guess: 1990, years_off: 0, round_score: 10 },
                    { name: 'Bob', guess: 1993, years_off: 3, round_score: 4 },
                ],
            },
        };
    });

    it('renders the per-player dot-axis inside the round-stats sheet', () => {
        renderRoundStatsSheet();
        // The dot-axis container proves renderPlayerDotAxis was called from here.
        expect(statsContentEl.innerHTML).toContain('dotaxis-wrap');
        // One dot per player.
        const dotCount = (statsContentEl.innerHTML.match(/dotaxis-dot dotaxis-dot--/g) || []).length;
        expect(dotCount).toBe(2);
        // The current player gets the "me" ring.
        expect(statsContentEl.innerHTML).toContain('dotaxis-dot--me');
        // Score bubbles surface the per-player round score.
        expect(statsContentEl.innerHTML).toContain('+10');
    });

    it('omits the dot-axis when there are no guesses', () => {
        mockState.lastRevealContext.analytics.all_guesses = [];
        renderRoundStatsSheet();
        expect(statsContentEl.innerHTML).not.toContain('dotaxis-wrap');
    });

    // #1663 item 3 (A11y — Icon+Text status): each legend row carries an
    // accuracy chip (glyph + word), so the reveal result no longer relies on the
    // dot colour alone. Exact (years_off 0) → exact chip; scored-but-not-exact →
    // near chip.
    it('adds icon+text accuracy chips to each legend row (#1663)', () => {
        renderRoundStatsSheet();
        // Alice = exact (years_off 0); Bob scored 4 but years_off 3 = near.
        expect(statsContentEl.innerHTML).toContain('dotaxis-legend-acc--exact');
        expect(statsContentEl.innerHTML).toContain('dotaxis-legend-acc--near');
        // The glyph is aria-hidden and paired with the word (colour is secondary).
        expect(statsContentEl.innerHTML).toContain('dotaxis-legend-acc-glyph');
        // Dots expose the accuracy word to screen readers via aria-label.
        expect(statsContentEl.innerHTML).toContain('role="img"');
        expect(statsContentEl.innerHTML).toContain('aria-label=');
    });

    it('marks a zero-score, non-exact guess as "off" (#1663)', () => {
        mockState.lastRevealContext.analytics.all_guesses = [
            { name: 'Alice', guess: 1970, years_off: 20, round_score: 0 },
        ];
        renderRoundStatsSheet();
        expect(statsContentEl.innerHTML).toContain('dotaxis-legend-acc--off');
    });
});
