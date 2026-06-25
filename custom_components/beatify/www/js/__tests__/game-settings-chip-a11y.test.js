/**
 * #1583 — selection chips lacked aria-pressed / screen-reader state.
 *
 * The game-settings chips (language, timer, difficulty, …) are native
 * `<button>`s, so role, focusability and Enter/Space activation are already
 * provided by the browser. The defect was the missing `aria-pressed`: a screen
 * reader couldn't tell which chip in a single-select group was selected. The fix
 * keeps `aria-pressed` in lockstep with the visual `chip--active` class via the
 * `selectChip` helper, applied in both the click handler and the load path.
 *
 * The vitest env is `node` (no jsdom), so a minimal fake DOM models the chip
 * group: native-button semantics (Enter/Space → click) let us assert that
 * keyboard activation reaches the same handler and flips aria-pressed.
 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest';

// playlists.js (imported transitively by game-settings.js) reads `window` at
// module load, so the global must exist *before* the dynamic import below.
globalThis.window = globalThis;

const store = {};
globalThis.localStorage = {
    getItem: (k) => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v); },
    removeItem: (k) => { delete store[k]; },
};

const { setupGameSettings, selectChip } = await import('../admin/sections/game-settings.js');
const { adminState } = await import('../admin/state.js');

/** Minimal fake chip element that models a native <button>. */
function makeChip(dataKey, dataVal, { active = false } = {}) {
    const classes = new Set(['chip']);
    if (active) classes.add('chip--active');
    const attrs = { 'aria-pressed': active ? 'true' : 'false' };
    const listeners = {};
    const el = {
        tagName: 'BUTTON',
        dataset: { [dataKey]: dataVal },
        classList: {
            add: (c) => classes.add(c),
            remove: (c) => classes.delete(c),
            contains: (c) => classes.has(c),
            toggle: (c, force) => {
                const want = force === undefined ? !classes.has(c) : !!force;
                if (want) classes.add(c); else classes.delete(c);
                return want;
            },
        },
        setAttribute(k, v) { attrs[k] = String(v); },
        getAttribute(k) { return k in attrs ? attrs[k] : null; },
        addEventListener(type, fn) { (listeners[type] ||= []).push(fn); },
        // Native <button>: a click runs the click handlers with `this` = element.
        click() { (listeners.click || []).forEach((fn) => fn.call(el, { type: 'click' })); },
        // Native <button>: Enter and Space activate the default action (a click).
        pressKey(key) { if (key === 'Enter' || key === ' ') el.click(); },
        get isActive() { return classes.has('chip--active'); },
        get pressed() { return attrs['aria-pressed']; },
    };
    return el;
}

let chips;

beforeEach(() => {
    for (const k of Object.keys(store)) delete store[k];
    // Difficulty group: a clean 3-chip single-select set (no i18n/async).
    chips = [
        makeChip('difficulty', 'easy'),
        makeChip('difficulty', 'normal', { active: true }),
        makeChip('difficulty', 'hard'),
    ];
    const summary = { textContent: '' };
    globalThis.document = {
        querySelectorAll(selector) {
            // Only the difficulty group is populated; every other group is empty.
            return selector === '.chip[data-difficulty]' ? chips : [];
        },
        getElementById(id) {
            return id === 'game-settings-summary' ? summary : null;
        },
    };
    setupGameSettings();
});

afterEach(() => {
    delete globalThis.document;
});

describe('#1583 selection-chip a11y', () => {
    it('seeds the markup with native buttons + aria-pressed', () => {
        expect(chips.every((c) => c.tagName === 'BUTTON')).toBe(true);
        expect(chips.map((c) => c.pressed)).toEqual(['false', 'true', 'false']);
    });

    it('aria-pressed toggles to the clicked chip and clears the rest', () => {
        chips[2].click(); // select "hard"

        expect(chips.map((c) => c.pressed)).toEqual(['false', 'false', 'true']);
        // aria-pressed stays in lockstep with the visual class — no drift.
        expect(chips.map((c) => c.isActive)).toEqual([false, false, true]);
        expect(adminState.selectedDifficulty).toBe('hard');
    });

    it('keyboard activation (Enter / Space) toggles aria-pressed like a click', () => {
        chips[0].pressKey('Enter'); // select "easy" via keyboard
        expect(chips.map((c) => c.pressed)).toEqual(['true', 'false', 'false']);
        expect(adminState.selectedDifficulty).toBe('easy');

        chips[2].pressKey(' '); // Space selects "hard"
        expect(chips.map((c) => c.pressed)).toEqual(['false', 'false', 'true']);
        expect(adminState.selectedDifficulty).toBe('hard');
    });

    it('exactly one chip is pressed after any selection', () => {
        chips[1].click();
        expect(chips.filter((c) => c.pressed === 'true')).toHaveLength(1);
    });

    it('selectChip helper sets aria-pressed false on the non-matching chips', () => {
        selectChip('.chip[data-difficulty]', (c) => c.dataset.difficulty === 'easy');
        expect(chips.map((c) => c.pressed)).toEqual(['true', 'false', 'false']);
        expect(chips.map((c) => c.isActive)).toEqual([true, false, false]);
    });
});
