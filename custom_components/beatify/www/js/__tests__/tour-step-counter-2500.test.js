/**
 * #2500 — the tour counter must come from the cards, not from a string.
 *
 * player.html carries five ``.tour-card`` sections, but all six ``stepOf``
 * translations still said "of 4": the fifth card arrived with Title & Artist
 * mode and the strings did not follow. Every first-time guest read
 * "Step 5 of 4" on the last card, before the first song played.
 *
 * The count now comes from ``totalCards()``, so it cannot disagree with the
 * DOM again. The companion check that the strings stay countless lives in
 * tests/unit/test_tour_step_counter_2500.py.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

// ---- browser-global stubs (before the import) ------------------------------
const memoryStore = {};
global.localStorage = {
    getItem: (k) => (k in memoryStore ? memoryStore[k] : null),
    setItem: (k, v) => { memoryStore[k] = String(v); },
    removeItem: (k) => { delete memoryStore[k]; },
};
global.window = { BeatifyUtils: { t: (key) => key }, matchMedia: () => ({ matches: false }) };
global.WebSocket = class MockWS { static OPEN = 1; };

/** A minimal element: text and attributes, enough for the header. */
function el() {
    return {
        textContent: '',
        attrs: {},
        classList: { add() {}, remove() {}, toggle() {} },
        querySelector: () => null,
        appendChild() {},
        setAttribute(k, v) { this.attrs[k] = v; },
        getAttribute(k) { return this.attrs[k] ?? null; },
    };
}

const dom = { cards: 0, num: el(), total: el(), bar: el(), segs: [] };

global.document = {
    getElementById: (id) => {
        if (id === 'tour-step-num') return dom.num;
        if (id === 'tour-step-total') return dom.total;
        return null;
    },
    querySelector: (sel) => (sel === '.tour-wiz-progress' ? dom.bar : null),
    querySelectorAll: (sel) => {
        if (sel === '.tour-card') return new Array(dom.cards).fill(null).map(() => el());
        if (sel === '.tour-wiz-seg') return dom.segs;
        return [];
    },
    addEventListener: () => {},
};

vi.mock('../player-utils.js', () => ({
    state: { ws: null, playerName: 'Markus' },
    showView: vi.fn(),
}));

const { renderProgress } = await import('../player-tour.js');

beforeEach(() => {
    dom.num = el();
    dom.total = el();
    dom.bar = el();
    dom.segs = [];
});

describe('#2500 the step counter counts the cards', () => {
    it('writes the real card count, not a number from a translation', () => {
        dom.cards = 5;

        renderProgress();

        expect(dom.total.textContent).toBe('5');
    });

    it('follows the DOM when a card is added or removed', () => {
        dom.cards = 7;
        renderProgress();
        expect(dom.total.textContent).toBe('7');

        dom.cards = 4;
        renderProgress();
        expect(dom.total.textContent).toBe('4');
    });

    it('keeps the progress bar’s upper bound on the same number', () => {
        dom.cards = 5;

        renderProgress();

        expect(dom.bar.getAttribute('aria-valuemax')).toBe('5');
        expect(dom.bar.getAttribute('aria-valuenow')).toBe('1');
    });
});
