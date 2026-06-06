/**
 * Regression test for the player reveal auto-advance countdown.
 *
 * Mirrors the admin sticky-Next countdown (#1048) and the TV dashboard ring
 * (#1185): the chip shows only when reveal_auto_advance > 0, a start time is
 * present, and the round is not idle-halted. Asserts the show/hide gating and
 * teardown so the countdown can't silently regress (the #1184 lesson).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

// vitest runs in node env — stub browser globals BEFORE importing the module.
let chipEl, numEl, fgCircle;
function makeEl(extra) {
    return Object.assign({
        classList: {
            _set: new Set(),
            add(c) { this._set.add(c); },
            remove(c) { this._set.delete(c); },
            contains(c) { return this._set.has(c); },
        },
        style: {},
        querySelector: () => fgCircle,
    }, extra || {});
}
global.window = { BeatifyUtils: { t: (k) => k } };
global.document = {
    getElementById: (id) => {
        if (id === 'player-reveal-countdown') return chipEl;
        if (id === 'player-reveal-countdown-num') return numEl;
        return null;
    },
};

vi.mock('../player-utils.js', () => ({
    state: {},
    escapeHtml: (s) => String(s),
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

const { updateRevealCountdown, stopRevealCountdown } = await import('../player-reveal.js');

describe('player reveal auto-advance countdown', () => {
    beforeEach(() => {
        fgCircle = { style: {} };
        numEl = makeEl();
        chipEl = makeEl();
        chipEl.classList.add('hidden'); // starts hidden per markup
    });
    afterEach(() => {
        stopRevealCountdown(); // clear any live interval between tests
    });

    it('shows the countdown when auto-advance is running', () => {
        const started = Date.now();
        updateRevealCountdown({ reveal_auto_advance: 10, reveal_started_at: started, idle_halt: false });
        expect(chipEl.classList.contains('hidden')).toBe(false);
        // A numeric remaining is painted (~10s, never above duration).
        const n = Number(numEl.textContent);
        expect(n).toBeGreaterThan(0);
        expect(n).toBeLessThanOrEqual(10);
    });

    it('hides the countdown when auto-advance is off (default)', () => {
        updateRevealCountdown({ reveal_auto_advance: 0, reveal_started_at: 0, idle_halt: false });
        expect(chipEl.classList.contains('hidden')).toBe(true);
    });

    it('hides the countdown during idle-halt', () => {
        updateRevealCountdown({ reveal_auto_advance: 10, reveal_started_at: Date.now(), idle_halt: true });
        expect(chipEl.classList.contains('hidden')).toBe(true);
    });

    it('stopRevealCountdown hides the chip', () => {
        updateRevealCountdown({ reveal_auto_advance: 10, reveal_started_at: Date.now(), idle_halt: false });
        stopRevealCountdown();
        expect(chipEl.classList.contains('hidden')).toBe(true);
    });
});
