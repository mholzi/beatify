/**
 * Race-mode bug batch (ported from the fork by @Muggedadscher, #3557) — the
 * "0/2 abgegeben" submission strip must be hidden in
 * Race mode.
 *
 * Race mode never marks a player `submitted` (unlimited attempts), so the arcade
 * submission tracker was stuck at "0/N submitted" for the whole round. The live
 * race status chips + feed already show progress, so the strip is hidden.
 *
 * `renderSubmissionTracker` is an internal (non-exported) helper, so we lift its
 * source out of player-game.js and run it against a small getElementById-backed
 * DOM, injecting the module globals it reads (document, utils, state,
 * getInitials).
 */
import { describe, it, expect, beforeAll } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));

function makeNode() {
    return {
        _cls: new Set(),
        innerHTML: '',
        textContent: '',
        classList: {
            _s: null,
            add(...c) { c.forEach((x) => this._s.add(x)); },
            remove(...c) { c.forEach((x) => this._s.delete(x)); },
            contains(x) { return this._s.has(x); },
            toggle(x, on) { if (on) this._s.add(x); else this._s.delete(x); return this._s.has(x); },
        },
        get className() { return Array.from(this._cls).join(' '); },
    };
}
function wire(node) { node.classList._s = node._cls; return node; }

function makeDom() {
    const ids = ['submission-tracker', 'submitted-players', 'arc-submission-count',
        'submitted-banner', 'submitted-banner-text'];
    const reg = {};
    ids.forEach((id) => { reg[id] = wire(makeNode()); });
    return { getElementById: (id) => reg[id] || null, _reg: reg };
}

let renderSubmissionTracker;
beforeAll(() => {
    const src = readFileSync(join(__dirname, '../player-game.js'), 'utf8');
    const start = src.indexOf('function renderSubmissionTracker(players, raceMode) {');
    expect(start).toBeGreaterThan(-1);
    // Brace-match to the function's closing brace.
    let depth = 0, i = src.indexOf('{', start), end = -1;
    for (; i < src.length; i++) {
        if (src[i] === '{') depth++;
        else if (src[i] === '}') { depth--; if (depth === 0) { end = i; break; } }
    }
    const fnSrc = src.slice(start, end + 1);
    const utils = { t: (k) => k };
    const state = { playerName: 'Me' };
    const getInitials = (n) => String(n || '').slice(0, 2).toUpperCase();
    const escapeHtml = (s) => String(s == null ? '' : s);
    // #2562: the non-race path fills the submitted banner via the module-level
    // waitingLine() helper; the strip test only cares that the count renders, so
    // a stub is enough to satisfy the reference.
    const waitingLine = () => '';
    // A fresh `document` is injected per call so each test drives its own DOM.
    renderSubmissionTracker = (players, raceMode, dom) =>
        new Function(
            'document', 'utils', 'state', 'getInitials', 'escapeHtml', 'waitingLine', 'players', 'raceMode',
            fnSrc + '\nreturn renderSubmissionTracker(players, raceMode);'
        )(dom, utils, state, getInitials, escapeHtml, waitingLine, players, raceMode);
});

describe('renderSubmissionTracker — race mode', () => {
    it('hides the strip and clears the count in race mode', () => {
        const dom = makeDom();
        renderSubmissionTracker(
            [{ name: 'Joäni', submitted: false }, { name: 'Schlieri', submitted: false }],
            true, dom
        );
        expect(dom._reg['submission-tracker'].classList.contains('hidden')).toBe(true);
        expect(dom._reg['submitted-players'].innerHTML).toBe('');
        expect(dom._reg['arc-submission-count'].textContent).toBe('');
    });

    it('shows the strip and a count when NOT in race mode', () => {
        const dom = makeDom();
        renderSubmissionTracker(
            [{ name: 'Joäni', submitted: true }, { name: 'Schlieri', submitted: false }],
            false, dom
        );
        expect(dom._reg['submission-tracker'].classList.contains('hidden')).toBe(false);
        // "1/2" style count is rendered (localized key echoed by the stub).
        expect(dom._reg['arc-submission-count'].textContent).toContain('submittedCount');
    });
});
