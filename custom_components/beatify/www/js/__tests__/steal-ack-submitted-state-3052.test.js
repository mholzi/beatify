/**
 * #3052 — after a successful steal the "Submitted!" stamp stayed for the rest
 * of the game and a dead Submit button came back.
 *
 * handleStealAck used to hide #submit-btn and un-hide the legacy
 * #submitted-confirmation node; resetSubmissionState never re-hid that node.
 * A steal now goes through handleSubmitAck (same locked UI as a normal ack),
 * and the reset hides the legacy stamp.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

global.WebSocket = { OPEN: 1, CONNECTING: 0, CLOSED: 3 };
global.IntersectionObserver = class {
    observe() {}
    disconnect() {}
};
// Translator returns real templates for the sabotage format keys (so {name}/
// {effect} interpolation is exercised) and echoes the key otherwise.
const I18N = {};
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
        previousState: {},
        isPreviousStateInitialized: () => false,
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
    handleStealAck,
    resetSubmissionState,
} = await import('../player-game.js');

const ME = 'Me';

function setupDom() {
    els = {};
    for (const id of ['submit-btn', 'year-selector', 'submitted-banner', 'submitted-confirmation', 'bet-toggle']) {
        els[id] = makeEl(id);
    }
    els['submitted-confirmation'].classList.add('hidden');
    els['submitted-banner'].classList.add('hidden');
}

beforeEach(() => {
    vi.useFakeTimers();
    utilsMod.state.ws = null;
    utilsMod.state.playerName = ME;
    setupDom();
    resetSubmissionState();
});

afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
});

describe('steal ack locks the UI like a normal submit (#3052)', () => {
    it('keeps the submit button visible but disabled and waiting', () => {
        handleStealAck({ success: true, target: 'Bob', year: 1985 });
        expect(els['submit-btn'].classList.contains('hidden')).toBe(false);
        expect(els['submit-btn'].disabled).toBe(true);
        expect(els['submit-btn'].classList.contains('submit-arc--waiting')).toBe(true);
        expect(els['submitted-banner'].classList.contains('hidden')).toBe(false);
        expect(els['year-selector'].classList.contains('slider-arcade--locked')).toBe(true);
        expect(els['bet-toggle'].disabled).toBe(true);
    });

    it('does not un-hide the legacy "Submitted!" stamp', () => {
        handleStealAck({ success: true, target: 'Bob', year: 1985 });
        expect(els['submitted-confirmation'].classList.contains('hidden')).toBe(true);
    });

    it('resetSubmissionState hides a stamp left visible and re-arms the button', () => {
        els['submitted-confirmation'].classList.remove('hidden');
        handleStealAck({ success: true, target: 'Bob', year: 1985 });
        resetSubmissionState();
        expect(els['submitted-confirmation'].classList.contains('hidden')).toBe(true);
        expect(els['submit-btn'].disabled).toBe(false);
        expect(els['submit-btn'].classList.contains('submit-arc--waiting')).toBe(false);
    });
});
