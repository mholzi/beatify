/**
 * #3581 - the round-end card is one shared helper (askBeforeEndingRound in
 * round-end-choice.js) used by the admin browser and the player host controls,
 * and it traps focus on both. Real round-end-choice.js + real focus trap over a
 * fake DOM that tracks activeElement.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import {
    askBeforeEndingRound, makeRoundEndT, noteRoundState, closeRoundEndChoice,
} from '../round-end-choice.js';

const here = path.dirname(fileURLToPath(import.meta.url));

function makeDoc() {
    const docListeners = {};
    const doc = {
        activeElement: null,
        addEventListener(t, fn) { (docListeners[t] = docListeners[t] || []).push(fn); },
        removeEventListener(t, fn) {
            docListeners[t] = (docListeners[t] || []).filter((f) => f !== fn);
        },
        _fire(t, ev) { (docListeners[t] || []).slice().forEach((f) => f(ev)); },
        _count(t) { return (docListeners[t] || []).length; },
    };
    const els = {};
    const mk = (id) => {
        const l = {};
        const attrs = {};
        const el = {
            id, disabled: false, hidden: false, dataset: {}, children: [], _text: '',
            classList: {
                _s: new Set(id === 'round-end-modal' ? ['hidden'] : []),
                add(c) { this._s.add(c); },
                remove(c) { this._s.delete(c); },
                contains(c) { return this._s.has(c); },
            },
            getAttribute: (k) => (k in attrs ? attrs[k] : null),
            setAttribute: (k, v) => { attrs[k] = v; },
            addEventListener: (e, fn) => { (l[e] = l[e] || []).push(fn); },
            removeEventListener: (e, fn) => { l[e] = (l[e] || []).filter((f) => f !== fn); },
            appendChild(c) { this.children.push(c); },
            querySelector: () => null,
            click() { (l.click || []).slice().forEach((fn) => fn()); },
            focus() { doc.activeElement = el; },
        };
        Object.defineProperty(el, 'textContent', {
            get: () => el._text,
            set: (v) => { el._text = v; el.children = []; },
        });
        return el;
    };
    ['round-end-modal', 'round-end-title', 'round-end-sub', 'round-end-score',
        'round-end-score-sub', 'round-end-swap', 'round-end-swap-sub',
        'round-end-void', 'round-end-keep', 'round-end-reasons', 'trigger',
    ].forEach((id) => { els[id] = mk(id); });
    const backdrop = mk('backdrop');
    const content = {
        querySelectorAll: () => [
            els['round-end-score'], els['round-end-void'], els['round-end-keep'],
        ],
    };
    els['round-end-modal'].ownerDocument = doc;
    els['round-end-modal'].querySelector = (sel) => {
        if (sel === '.modal-backdrop') return backdrop;
        if (sel === '.modal-content') return content;
        return null;
    };
    doc.getElementById = (id) => els[id] || null;
    doc.createElement = () => mk('');
    doc._el = (id) => els[id];
    return doc;
}

const PLAYING = {
    phase: 'PLAYING', round: 5, seconds_remaining: 22,
    admin_round_end_preview: { round: 5, player_count: 8, submitted_count: 3 },
};

// The two pages differ only in where they get a translation from.
const PAGES = {
    admin: () => makeRoundEndT((k) => k),
    player: () => makeRoundEndT(() => null),
};

describe.each(Object.keys(PAGES))('round-end dialog on the %s page (#3581)', (page) => {
    let doc;
    let on;
    let done;

    function open() {
        doc.getElementById('trigger').focus();
        done = askBeforeEndingRound({ doc, t: PAGES[page](), on });
    }

    beforeEach(() => {
        noteRoundState(PLAYING, 1000);
        doc = makeDoc();
        on = { score: vi.fn(), swap: vi.fn(), void: vi.fn() };
    });

    it('opens the dialog and moves focus to "keep playing"', () => {
        open();
        expect(doc._el('round-end-modal').classList.contains('hidden')).toBe(false);
        expect(doc.activeElement).toBe(doc._el('round-end-keep'));
        expect(doc._count('keydown')).toBe(1);
        closeRoundEndChoice();
    });

    it('traps Tab on the last control and Shift+Tab on the first', () => {
        open();
        doc.activeElement = doc._el('round-end-keep'); // last
        const tab = vi.fn();
        doc._fire('keydown', { key: 'Tab', shiftKey: false, preventDefault: tab });
        expect(tab).toHaveBeenCalled();
        expect(doc.activeElement).toBe(doc._el('round-end-score')); // wrapped to first

        const back = vi.fn();
        doc._fire('keydown', { key: 'Tab', shiftKey: true, preventDefault: back });
        expect(back).toHaveBeenCalled();
        expect(doc.activeElement).toBe(doc._el('round-end-keep')); // wrapped to last
        closeRoundEndChoice();
    });

    it('Escape closes it, restores focus, sends nothing', async () => {
        open();
        doc._fire('keydown', { key: 'Escape', preventDefault: () => {} });
        await done;
        expect(doc._el('round-end-modal').classList.contains('hidden')).toBe(true);
        expect(doc.activeElement).toBe(doc._el('trigger'));
        expect(doc._count('keydown')).toBe(0);
        expect(on.score).not.toHaveBeenCalled();
        expect(on.swap).not.toHaveBeenCalled();
        expect(on.void).not.toHaveBeenCalled();
    });

    it('cancel ("keep playing") closes it, restores focus, sends nothing', async () => {
        open();
        doc._el('round-end-keep').click();
        await done;
        expect(doc._el('round-end-modal').classList.contains('hidden')).toBe(true);
        expect(doc.activeElement).toBe(doc._el('trigger'));
        expect(on.score).not.toHaveBeenCalled();
    });

    it('confirm triggers the end-round action', async () => {
        open();
        doc._el('round-end-score').click();
        await done;
        expect(on.score).toHaveBeenCalledTimes(1);
        expect(on.void).not.toHaveBeenCalled();
        expect(doc.activeElement).toBe(doc._el('trigger'));
    });

    it('"void" passes the picked reason through', async () => {
        open();
        doc._el('round-end-void').click();
        await done;
        expect(on.void).toHaveBeenCalledWith(null);
    });
});

describe('both pages use the shared helper (#3581)', () => {
    const read = (f) => readFileSync(path.join(here, '..', f), 'utf8');

    it.each(['admin.js', 'player-game.js'])('%s has no private copy of the dialog', (file) => {
        const src = read(file);
        expect(src).toContain('askBeforeEndingRound as askRoundEnd');
        expect(src).not.toMatch(/openRoundEndChoice\s*\(/);
        expect(src).not.toMatch(/function _tRoundEnd/);
    });
});

// #3590: a click does not always focus its button (Safari, programmatic
// clicks), so nothing holds focus when the card opens. The caller names the
// opener and focus goes back to it on every exit.
describe('round-end dialog returns focus to the named opener (#3590)', () => {
    beforeEach(() => noteRoundState(PLAYING, 1000));

    it.each([
        ['Escape', (doc) => doc._fire('keydown', { key: 'Escape', preventDefault: () => {} })],
        ['keep playing', (doc) => doc._el('round-end-keep').click()],
    ])('on %s', async (_name, close) => {
        const doc = makeDoc();
        const on = { score: vi.fn(), swap: vi.fn(), void: vi.fn() };
        doc.activeElement = null; // nothing focused: the trigger was clicked, not tabbed to
        const done = askBeforeEndingRound({
            doc, t: makeRoundEndT(() => null), on, returnFocus: doc._el('trigger'),
        });
        close(doc);
        await done;
        expect(doc.activeElement).toBe(doc._el('trigger'));
    });
});
