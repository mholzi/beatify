/**
 * Race-mode bug batch — dashboard leaderboard must never show a name twice.
 * Ported from the fork by @Muggedadscher (#3557).
 *
 * `_reconcileRows` (dashboard.js) keeps its keyed row list in sync with the DOM.
 * A duplicate key (the same player shipped twice — e.g. an NFC/NFD duplicate
 * session) used to wedge it: two DOM nodes shared one data-row-key, and the
 * keyed removal pass could never prune either because the key stayed "desired".
 * The orphan then persisted and accumulated across rounds — the "our two names
 * appear multiple times on the dashboard" report.
 *
 * dashboard.js is a DOM-coupled IIFE with no exports, so we lift the
 * `_reconcileRows` source out of the file and run it against a minimal but
 * faithful DOM (insertBefore / removeChild / firstElementChild / children).
 */
import { describe, it, expect, beforeAll } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));

// --- minimal DOM ------------------------------------------------------------
function makeEl() {
    const el = {
        _children: [],
        _attrs: {},
        parentNode: null,
        _html: '',
        getAttribute(k) { return k in this._attrs ? this._attrs[k] : null; },
        setAttribute(k, v) { this._attrs[k] = String(v); },
        set innerHTML(v) {
            this._html = v;
            // Parse into exactly one opaque child element (reconcile reads
            // firstElementChild and then stamps its own data-row-key).
            const child = makeEl();
            this._children = [child];
            child.parentNode = this;
        },
        get innerHTML() { return this._html; },
        get firstElementChild() { return this._children[0] || null; },
        get children() { return this._children; },
        get nextElementSibling() {
            const p = this.parentNode;
            if (!p) return null;
            const i = p._children.indexOf(this);
            return (i >= 0 && i + 1 < p._children.length) ? p._children[i + 1] : null;
        },
        insertBefore(node, ref) {
            if (node.parentNode) {
                const oi = node.parentNode._children.indexOf(node);
                if (oi >= 0) node.parentNode._children.splice(oi, 1);
            }
            const idx = ref ? this._children.indexOf(ref) : this._children.length;
            this._children.splice(idx < 0 ? this._children.length : idx, 0, node);
            node.parentNode = this;
            return node;
        },
        // #2820 on main swaps a changed row in place.
        replaceChild(fresh, old) {
            const i = this._children.indexOf(old);
            if (i < 0) return old;
            if (fresh.parentNode) {
                const fi = fresh.parentNode._children.indexOf(fresh);
                if (fi >= 0) fresh.parentNode._children.splice(fi, 1);
            }
            this._children.splice(this._children.indexOf(old), 1, fresh);
            fresh.parentNode = this;
            old.parentNode = null;
            return old;
        },
        removeChild(node) {
            const i = this._children.indexOf(node);
            if (i >= 0) this._children.splice(i, 1);
            node.parentNode = null;
            return node;
        },
    };
    return el;
}

const fakeDocument = { createElement: () => makeEl() };

// --- lift _reconcileRows out of dashboard.js --------------------------------
let reconcile;
beforeAll(() => {
    const src = readFileSync(join(__dirname, '../dashboard.js'), 'utf8');
    const start = src.indexOf('function _reconcileRows(container, rows) {');
    expect(start).toBeGreaterThan(-1);
    const marker = 'container._beatifyRowSigs = newSig;';
    const mEnd = src.indexOf(marker, start);
    expect(mEnd).toBeGreaterThan(-1);
    // include the marker line and its closing brace
    const closeBrace = src.indexOf('}', mEnd);
    const fnSrc = src.slice(start, closeBrace + 1);
    reconcile = new Function('document', fnSrc + '\nreturn _reconcileRows;')(fakeDocument);
});

function rowsFrom(pairs) {
    return pairs.map(([name, score]) => ({
        key: String(name),
        html: '<div class="leaderboard-entry"><span>' + name + '</span><span>' + score + '</span></div>',
    }));
}

function keysOf(container) {
    return container._children.map((c) => c.getAttribute('data-row-key'));
}

describe('_reconcileRows — duplicate-name resilience', () => {
    it('renders each unique name once', () => {
        const c = makeEl();
        reconcile(c, rowsFrom([['Joäni', 30], ['Schlieri', 20]]));
        expect(keysOf(c)).toEqual(['Joäni', 'Schlieri']);
    });

    it('collapses a duplicate key to a single row (no wedge)', () => {
        const c = makeEl();
        // Backend momentarily ships the same player twice.
        reconcile(c, rowsFrom([['Joäni', 30], ['Schlieri', 20], ['Joäni', 10]]));
        const keys = keysOf(c);
        expect(keys.filter((k) => k === 'Joäni').length).toBe(1);
        expect(keys.length).toBe(2);
    });

    it('self-heals: once the duplicate stops, the DOM holds one row per name', () => {
        const c = makeEl();
        // Duplicate frame first...
        reconcile(c, rowsFrom([['Joäni', 30], ['Schlieri', 20], ['Joäni', 10]]));
        // ...then a clean frame (backend deduped). No orphan may survive.
        reconcile(c, rowsFrom([['Joäni', 30], ['Schlieri', 20]]));
        const keys = keysOf(c);
        expect(keys).toEqual(['Joäni', 'Schlieri']);
        expect(keys.filter((k) => k === 'Joäni').length).toBe(1);
    });

    it('does not accumulate rows across many repeated renders', () => {
        const c = makeEl();
        for (let i = 0; i < 6; i++) {
            reconcile(c, rowsFrom([['Joäni', i], ['Schlieri', i * 2]]));
        }
        expect(c._children.length).toBe(2);
    });
});
