/**
 * #3391 steal/sabotage undo. Harness: see player-sabotage-1665.test.js.
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
    'steal.pending': 'Stealing from {name}…',
    'sabotage.pending': 'Sabotaging {name}…',
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
        style: {},
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
    // #3391: the undo toast docks its container on <body>.
    body: makeEl('body'),
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
    resetSubmissionState,
    handleStealTargets,
    handleSabotageTargets,
    handleSubmitGuess,
    cancelPendingPowerup,
    powerupUndoWindowMs,
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


/**
 * #3391 — steal and sabotage are one tap plus Undo.
 *
 * Tapping the target used to open a second "Steal Answer?" dialog. Now the tap
 * arms the power-up, a toast at the bottom offers Undo, and the WS message
 * leaves only when the toast runs out. Undo sends nothing.
 */

function sentLog() {
    const sent = [];
    utilsMod.state.ws = { readyState: 1, send: (p) => sent.push(JSON.parse(p)) };
    return sent;
}

function undoToast() {
    // The undo container is the only child the toast code appends to <body>.
    const container = document.body.kids[document.body.kids.length - 1];
    const toast = container.kids[container.kids.length - 1];
    return { toast, undoBtn: toast.kids.find((k) => k.className === 'beatify-toast-undo') };
}

beforeEach(() => {
    document.body = makeEl('body');
    els['steal-modal'] = makeEl('steal-modal');
    els['steal-modal'].children['.steal-modal-content'] = makeEl();
    els['steal-target-list'] = makeEl('steal-target-list');
    els['sabotage-modal'] = makeEl('sabotage-modal');
    els['sabotage-modal'].children['.steal-modal-content'] = makeEl();
    els['sabotage-target-list'] = makeEl('sabotage-target-list');
    els['steal-btn'] = makeEl('steal-btn');
    els['sabotage-btn'] = makeEl('sabotage-btn');
});

describe('steal: one tap plus Undo (#3391)', () => {
    it('closes the picker at once and sends the steal after 3 s', async () => {
        const sent = sentLog();
        handleStealTargets({ targets: ['Bob'], leaderboard: [] });
        els['steal-target-list'].kids[0].dispatch('click');

        expect(els['steal-modal'].classList.contains('hidden')).toBe(true);
        expect(sent).toEqual([]);
        expect(els['steal-btn'].disabled).toBe(true);
        expect(undoToast().toast.kids[0].kids.at(-1).textContent).toContain('Bob');

        await vi.advanceTimersByTimeAsync(2999);
        expect(sent).toEqual([]);
        await vi.advanceTimersByTimeAsync(1);
        expect(sent).toEqual([{ type: 'steal', target: 'Bob' }]);
        expect(els['steal-btn'].disabled).toBe(false);
    });

    it('Undo sends nothing, ever, and gives the buttons back', async () => {
        const sent = sentLog();
        handleStealTargets({ targets: ['Bob'], leaderboard: [] });
        els['steal-target-list'].kids[0].dispatch('click');
        undoToast().undoBtn.dispatch('click');
        await vi.advanceTimersByTimeAsync(10000);
        expect(sent).toEqual([]);
        expect(els['steal-btn'].disabled).toBe(false);
    });

    it('a new round drops an unsent steal', async () => {
        const sent = sentLog();
        handleStealTargets({ targets: ['Bob'], leaderboard: [] });
        els['steal-target-list'].kids[0].dispatch('click');
        resetSubmissionState();
        await vi.advanceTimersByTimeAsync(10000);
        expect(sent).toEqual([]);
    });

    it('cancelPendingPowerup (round over, paused) sends nothing', async () => {
        const sent = sentLog();
        handleStealTargets({ targets: ['Bob'], leaderboard: [] });
        els['steal-target-list'].kids[0].dispatch('click');
        cancelPendingPowerup();
        await vi.advanceTimersByTimeAsync(10000);
        expect(sent).toEqual([]);
    });

    it('Submit while a steal waits: the own guess wins, no steal leaves', async () => {
        const sent = sentLog();
        els['year-slider'] = makeEl('year-slider');
        els['year-slider'].value = '1990';
        els['submit-btn'] = makeEl('submit-btn');
        handleStealTargets({ targets: ['Bob'], leaderboard: [] });
        els['steal-target-list'].kids[0].dispatch('click');
        handleSubmitGuess();
        await vi.advanceTimersByTimeAsync(4000);
        expect(sent.map((m) => m.type)).toEqual(['submit']);
    });
});

describe('sabotage: one tap plus Undo (#3391)', () => {
    it('Submit while a sabotage waits sends the sabotage first', async () => {
        const sent = sentLog();
        els['year-slider'] = makeEl('year-slider');
        els['year-slider'].value = '1990';
        els['submit-btn'] = makeEl('submit-btn');
        handleSabotageTargets({ targets: ['Bob'], leaderboard: [] });
        els['sabotage-target-list'].kids[0].dispatch('click');
        expect(sent).toEqual([]);
        handleSubmitGuess();
        expect(sent.map((m) => m.type)).toEqual(['sabotage', 'submit']);
        await vi.advanceTimersByTimeAsync(4000);
        expect(sent.map((m) => m.type)).toEqual(['sabotage', 'submit']);
    });
});

describe('powerupUndoWindowMs (#3391)', () => {
    it('is 3 s while the round has time', () => {
        expect(powerupUndoWindowMs(null)).toBe(3000);
        expect(powerupUndoWindowMs(20000)).toBe(3000);
    });

    it('shrinks so the message still beats the deadline', () => {
        expect(powerupUndoWindowMs(2600)).toBe(2000);
    });

    it('sends at once when there is no time for a readable undo', () => {
        expect(powerupUndoWindowMs(1200)).toBe(0);
        expect(powerupUndoWindowMs(-50)).toBe(0);
    });
});
