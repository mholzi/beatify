/**
 * Sabotage power-up coverage for player-game.js (#1665).
 *
 * The Sabotage power-up is the twin of Steal: the saboteur picks only a TARGET;
 * the effect is rolled server-side. These tests exercise the real module (no
 * re-implementation) and assert the observable DOM / WebSocket effects:
 *
 *   - the sabotage button shows only while the token is in hand AND we have not
 *     submitted (updateGameView → updateSabotageUI),
 *   - handleSabotageTargets opens the picker and populates one row per target,
 *   - clicking a target row sends the `sabotage` WS message with that target,
 *   - handleSabotageAck spends the token and toasts the rolled effect,
 *   - handleSabotaged renders the "you've been sabotaged" banner and reflects a
 *     forced-bet by locking the bet toggle on.
 *
 * Browser globals are stubbed for the node test env; player-utils.js is mocked
 * so the module loads in isolation (mirrors player-game-state.test.js).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

global.WebSocket = { OPEN: 1, CONNECTING: 0, CLOSED: 3 };
global.IntersectionObserver = class {
    observe() {}
    disconnect() {}
};
// Translator returns real templates for the sabotage format keys (so {name}/
// {effect} interpolation is exercised) and echoes the key otherwise.
const I18N = {
    'sabotage.success': 'Sabotaged {name} · {effect}',
    'sabotage.hit': "You've been sabotaged by {name}! ({effect})",
    'sabotage.effect.timer_cut': 'Timer cut',
    'sabotage.effect.forced_bet': 'Forced bet',
    'sabotage.effect.freeze': 'Freeze',
};
global.window = {
    BeatifyUtils: { t: (key) => (key in I18N ? I18N[key] : key) },
    matchMedia: () => ({ matches: true, addEventListener: () => {} }),
};

// Element stub: classList + querySelector + appendChild (records children) +
// addEventListener (so a rendered target row can be "clicked").
function makeEl(id) {
    const classes = new Set();
    const children = {};
    const kids = [];
    const listeners = {};
    let innerHTML = '';
    const el = {
        id,
        className: '',
        textContent: '',
        disabled: false,
        _attrs: {},
        children,
        kids,
        classList: {
            add: (...c) => c.forEach((x) => classes.add(x)),
            remove: (...c) => c.forEach((x) => classes.delete(x)),
            contains: (c) => classes.has(c),
            toggle: (c, on) => {
                const want = on === undefined ? !classes.has(c) : on;
                if (want) classes.add(c); else classes.delete(c);
                return classes.has(c);
            },
        },
        setAttribute: (k, v) => { el._attrs[k] = v; },
        removeAttribute: (k) => { delete el._attrs[k]; },
        getAttribute: (k) => (k in el._attrs ? el._attrs[k] : null),
        querySelector: (sel) => children[sel] || null,
        appendChild: (child) => { kids.push(child); return child; },
        addEventListener: (type, fn) => { (listeners[type] = listeners[type] || []).push(fn); },
        dispatch: (type) => { (listeners[type] || []).forEach((fn) => fn()); },
    };
    Object.defineProperty(el, 'innerHTML', {
        get: () => innerHTML,
        set: (v) => { innerHTML = v; if (v === '') { kids.length = 0; } },
    });
    return el;
}

let els;
global.document = {
    getElementById: (id) => els[id] || null,
    createElement: () => makeEl(),
};

vi.mock('../player-utils.js', () => {
    const state = { ws: null, playerName: null };
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
        isTitleArtistMode: () => false,
        // #1665: the sabotage modal reuses the steal focus-trap helper.
        createModalFocusTrap: () => ({ activate: () => {}, deactivate: () => {} }),
    };
});

const utilsMod = await import('../player-utils.js');
const {
    updateGameView,
    handleSubmitAck,
    resetSubmissionState,
    handleSabotageTargets,
    handleSabotageAck,
    handleSabotaged,
} = await import('../player-game.js');

const ME = 'Me';

beforeEach(() => {
    vi.useFakeTimers();
    els = {};
    utilsMod.state.ws = null;
    utilsMod.state.playerName = ME;
    // Fresh per-round module state (clears hasSubmitted / forced-bet / freeze).
    resetSubmissionState();
});

afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
});

describe('sabotage button visibility (#1665)', () => {
    beforeEach(() => {
        els['sabotage-btn'] = makeEl('sabotage-btn');
        els['sabotage-indicator'] = makeEl('sabotage-indicator');
        els['sabotage-btn'].classList.add('hidden');
        els['sabotage-indicator'].classList.add('hidden');
    });

    it('shows the button when the token is in hand and not submitted', () => {
        updateGameView({ players: [{ name: ME, sabotage_available: true }] });
        expect(els['sabotage-btn'].classList.contains('hidden')).toBe(false);
        expect(els['sabotage-indicator'].classList.contains('hidden')).toBe(false);
    });

    it('hides the button when no token is available', () => {
        updateGameView({ players: [{ name: ME, sabotage_available: false }] });
        expect(els['sabotage-btn'].classList.contains('hidden')).toBe(true);
    });

    it('hides the button once this player has submitted', () => {
        handleSubmitAck();  // flips internal hasSubmitted
        updateGameView({ players: [{ name: ME, sabotage_available: true }] });
        expect(els['sabotage-btn'].classList.contains('hidden')).toBe(true);
    });
});

describe('sabotage target picker (#1665)', () => {
    beforeEach(() => {
        els['sabotage-modal'] = makeEl('sabotage-modal');
        els['sabotage-modal'].classList.add('hidden');
        els['sabotage-modal'].children['.steal-modal-content'] = makeEl();
        els['sabotage-target-list'] = makeEl('sabotage-target-list');
    });

    it('opens the modal and renders one row per target', () => {
        handleSabotageTargets({
            targets: ['Bob', 'Carol'],
            leaderboard: [
                { name: 'Bob', rank: 1, score: 120 },
                { name: 'Carol', rank: 2, score: 80 },
            ],
        });
        expect(els['sabotage-modal'].classList.contains('hidden')).toBe(false);
        expect(els['sabotage-target-list'].kids.length).toBe(2);
    });

    it('sends the sabotage WS message with the chosen target on select', async () => {
        const sent = [];
        utilsMod.state.ws = {
            readyState: 1,
            send: (payload) => sent.push(JSON.parse(payload)),
        };

        handleSabotageTargets({ targets: ['Bob'], leaderboard: [] });
        const row = els['sabotage-target-list'].kids[0];
        row.dispatch('click');            // selectSabotageTarget('Bob')
        await vi.runAllTimersAsync();     // let the confirm promise resolve

        expect(sent).toEqual([{ type: 'sabotage', target: 'Bob' }]);
    });
});

describe('sabotage acknowledgment for the saboteur (#1665)', () => {
    beforeEach(() => {
        els['sabotage-btn'] = makeEl('sabotage-btn');
        els['sabotage-indicator'] = makeEl('sabotage-indicator');
        els['sabotage-confirmation'] = makeEl('sabotage-confirmation');
        els['sabotage-confirmation'].classList.add('hidden');
        els['sabotage-confirmation-text'] = makeEl('sabotage-confirmation-text');
    });

    it('spends the token, hides the button, and toasts the rolled effect', () => {
        handleSabotageAck({ success: true, target: 'Bob', effect: 'freeze' });
        expect(els['sabotage-btn'].classList.contains('hidden')).toBe(true);
        expect(els['sabotage-confirmation'].classList.contains('hidden')).toBe(false);
        expect(els['sabotage-confirmation-text'].textContent).toContain('Bob');
    });
});

describe('you-were-sabotaged reflection for the target (#1665)', () => {
    beforeEach(() => {
        els['sabotaged-banner'] = makeEl('sabotaged-banner');
        els['sabotaged-banner'].classList.add('hidden');
        els['sabotaged-banner-text'] = makeEl('sabotaged-banner-text');
        els['bet-toggle'] = makeEl('bet-toggle');
    });

    it('renders the banner naming the saboteur', () => {
        handleSabotaged({ by: 'Bob', effect: 'timer_cut' });
        expect(els['sabotaged-banner'].classList.contains('hidden')).toBe(false);
        expect(els['sabotaged-banner-text'].textContent).toContain('Bob');
    });

    it('locks the bet toggle on when a forced-bet is rolled', () => {
        handleSabotaged({ by: 'Bob', effect: 'forced_bet' });
        expect(els['bet-toggle'].classList.contains('is-active')).toBe(true);
        expect(els['bet-toggle'].classList.contains('bet-arc--forced')).toBe(true);
    });
});
