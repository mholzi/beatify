/**
 * Bet-payout label render coverage for player-game.js (#1727).
 *
 * renderBetPayout surfaces the active won-bet multiplier on the bet toggle so
 * players see what they are betting for: a flat ×3 when difficulty bet scaling
 * is off, or 2/3/5× (easy/normal/hard) when the opt-in setting is on. The value
 * is served in the game-state `bet_win_multiplier` field.
 *
 * Browser globals are stubbed for the node test env; player-utils.js and
 * player-reveal.js are mocked so the module loads in isolation (mirrors
 * player-game-state.test.js).
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

global.WebSocket = { OPEN: 1, CONNECTING: 0, CLOSED: 3 };
global.IntersectionObserver = class {
    observe() {}
    disconnect() {}
};
global.window = {
    BeatifyUtils: { t: (key) => key },
    matchMedia: () => ({ matches: true, addEventListener: () => {} }),
};

function makeEl(id) {
    const children = {};
    const el = {
        id,
        textContent: '',
        _attrs: {},
        children,
        setAttribute: (k, v) => { el._attrs[k] = v; },
        removeAttribute: (k) => { delete el._attrs[k]; },
        getAttribute: (k) => (k in el._attrs ? el._attrs[k] : null),
        querySelector: (sel) => children[sel] || null,
    };
    return el;
}

let els;
global.document = {
    getElementById: (id) => els[id] || null,
};

vi.mock('../player-utils.js', () => {
    const state = { ws: null };
    return {
        state,
        escapeHtml: (s) => String(s),
        showConfirmModal: async () => true,
        prefersReducedMotion: () => true,
        animateValue: () => {},
        animateScoreChange: () => {},
        showPointsPopup: () => {},
        previousState: {},
        isPreviousStateInitialized: () => false,
        isStreakMilestone: () => false,
        detectRankChanges: () => ({}),
        updatePreviousState: () => {},
        AnimationUtils: {},
        AnimationQueue: { isRunning: () => false, skipAll: () => {} },
        LEADERBOARD_LAZY_CONFIG: {},
        lazyLeaderboardState: {},
        initLeaderboardObserver: () => {},
        renderLazyLeaderboardRange: () => {},
        renderLeaderboardEntry: () => '',
        calculateInitialVisibleRange: () => [0, 0],
        setupLeaderboardResizeHandler: () => {},
        setEnergyLevel: () => {},
        triggerConfetti: () => {},
        stopConfetti: () => {},
    };
});

const { renderBetPayout } = await import('../player-game.js');

// Build a #bet-toggle with a nested .bet-label (data-i18n bound, like the HTML).
function makeBetToggle() {
    const toggle = makeEl('bet-toggle');
    const label = makeEl();
    label.setAttribute('data-i18n', 'game.betShort');
    label.textContent = '×3';
    toggle.children['.bet-label'] = label;
    return { toggle, label };
}

describe('renderBetPayout (#1727)', () => {
    beforeEach(() => {
        els = {};
    });

    it('paints the flat ×3 payout and drops the i18n binding', () => {
        const { toggle, label } = makeBetToggle();
        els['bet-toggle'] = toggle;

        renderBetPayout({ bet_win_multiplier: 3 });

        expect(label.textContent).toBe('×3');
        // once set from live state, the static i18n key must not clobber it later
        expect(label.getAttribute('data-i18n')).toBe(null);
    });

    it('paints the boosted ×5 Hard payout', () => {
        const { toggle, label } = makeBetToggle();
        els['bet-toggle'] = toggle;

        renderBetPayout({ bet_win_multiplier: 5 });

        expect(label.textContent).toBe('×5');
    });

    it('paints the ×2 Easy payout', () => {
        const { toggle, label } = makeBetToggle();
        els['bet-toggle'] = toggle;

        renderBetPayout({ bet_win_multiplier: 2 });

        expect(label.textContent).toBe('×2');
    });

    it('leaves the static i18n label untouched when no multiplier is sent', () => {
        const { toggle, label } = makeBetToggle();
        els['bet-toggle'] = toggle;

        renderBetPayout({});

        expect(label.textContent).toBe('×3');
        expect(label.getAttribute('data-i18n')).toBe('game.betShort');
    });

    it('is a no-op (no throw) when the bet toggle is absent', () => {
        expect(() => renderBetPayout({ bet_win_multiplier: 5 })).not.toThrow();
    });
});
