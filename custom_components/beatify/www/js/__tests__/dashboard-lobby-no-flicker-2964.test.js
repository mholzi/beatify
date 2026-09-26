/**
 * #2964: the TV lobby's name wall must not flicker when someone joins.
 *
 * The wall used to be cleared and rebuilt on every render, and a join renders
 * twice — the join broadcast, then the guest's phone finishing or skipping
 * the onboarding tour flips `onboarded` and broadcasts again. Every name on
 * the TV vanished and slid back in, twice per guest. The fix keys the tiles by
 * name: a tile is created once, only the newcomer animates, and a render that
 * changes nothing on the wall touches no DOM at all.
 *
 * These tests run the real `renderPlayerList` (and the helpers it calls) from
 * dashboard.js against a small tree-shaped fake DOM that records every
 * mutation, so "existing tiles are not removed or re-created" is observed,
 * not inferred from the source.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { declaration, evaluate, readSource } from './helpers/js-source.js';

const SRC = readSource('dashboard.js');
const CSS = readSource('../css/dashboard.css');

// ---------------------------------------------------------------------------
// A fake DOM with real parent/child links and a mutation log
// ---------------------------------------------------------------------------

let log;
let created;

class Node {
    constructor(tag) {
        this.tagName = tag.toUpperCase();
        this.childNodes = [];
        this.parent = null;
        this.attrs = {};
        this.style = {};
        this._text = '';
        const classes = new Set();
        this._classes = classes;
        this.classList = {
            add: (...c) => c.forEach((x) => classes.add(x)),
            remove: (...c) => c.forEach((x) => classes.delete(x)),
            contains: (c) => classes.has(c),
            toggle: (c, force) => {
                const want = force === undefined ? !classes.has(c) : !!force;
                if (want) classes.add(c);
                else classes.delete(c);
                return want;
            },
        };
    }
    set className(v) {
        this._classes.clear();
        String(v).split(/\s+/).filter(Boolean).forEach((c) => this._classes.add(c));
    }
    get className() { return [...this._classes].join(' '); }
    set textContent(v) { this._text = String(v); this.childNodes = []; }
    get textContent() { return this._text + this.childNodes.map((c) => c.textContent).join(''); }
    get children() { return this.childNodes; }
    get firstElementChild() { return this.childNodes[0] || null; }
    get nextElementSibling() {
        if (!this.parent) return null;
        const sib = this.parent.childNodes;
        return sib[sib.indexOf(this) + 1] || null;
    }
    setAttribute(k, v) { this.attrs[k] = String(v); }
    getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
    _detach(node) {
        if (node.parent) {
            const sib = node.parent.childNodes;
            sib.splice(sib.indexOf(node), 1);
        }
    }
    appendChild(node) {
        log.push(['append', node]);
        this._detach(node);
        node.parent = this;
        this.childNodes.push(node);
        return node;
    }
    insertBefore(node, ref) {
        log.push(['insert', node]);
        this._detach(node);
        node.parent = this;
        const at = ref ? this.childNodes.indexOf(ref) : -1;
        if (at === -1) this.childNodes.push(node);
        else this.childNodes.splice(at, 0, node);
        return node;
    }
    removeChild(node) {
        log.push(['remove', node]);
        this._detach(node);
        node.parent = null;
        return node;
    }
    querySelector(sel) {
        const cls = sel.replace(/^\./, '');
        for (const c of this.childNodes) {
            if (c.classList.contains(cls)) return c;
            const deep = c.querySelector(sel);
            if (deep) return deep;
        }
        return null;
    }
}

let list;

function renderWall(players) {
    const document = {
        createElement: (tag) => { const n = new Node(tag); created.push(n); return n; },
        getElementById: (id) => (id === 'dashboard-player-list' ? list : null),
    };
    const snippets = ['lobbyWallColumns', 'buildPlayerTile', 'syncPlayerTile', 'renderPlayerList']
        .map((name) => declaration(SRC, name, 'dashboard.js'));
    evaluate(snippets, 'renderPlayerList', {
        document,
        utils: { t: (key, fallback) => fallback },
        endAvatarGradient: () => 'linear-gradient(#000,#fff)',
        scheduleNewTileFade: () => {},
    })(players);
}

const tiles = () => list.childNodes.filter((n) => n.getAttribute('data-player') !== null);
const names = () => tiles().map((n) => n.getAttribute('data-player'));
const tileOf = (name) => tiles().find((n) => n.getAttribute('data-player') === name);
const p = (name, extra) => Object.assign({ name, connected: true }, extra);

beforeEach(() => {
    log = [];
    created = [];
    list = new Node('div');
});

describe('a join adds one tile and leaves the others alone (#2964)', () => {
    it('keeps the existing tiles as the same nodes, never removed or re-inserted', () => {
        renderWall([p('Anna'), p('Ben'), p('Mia')]);
        const before = { Anna: tileOf('Anna'), Ben: tileOf('Ben'), Mia: tileOf('Mia') };
        log = [];
        created = [];

        renderWall([p('Anna'), p('Ben'), p('Mia'), p('Leo')]);

        expect(names()).toEqual(['Anna', 'Ben', 'Mia', 'Leo']);
        for (const name of ['Anna', 'Ben', 'Mia']) {
            expect(tileOf(name), `${name} is the same node`).toBe(before[name]);
            expect(log.some(([, node]) => node === before[name]), `${name} was not touched`).toBe(false);
        }
        // Exactly one new tile element was built (plus its avatar and name).
        expect(created.filter((n) => n.className.includes('dashboard-player-card'))).toHaveLength(1);
        expect(log.filter(([op]) => op === 'remove')).toHaveLength(0);
    });

    it('animates only the newcomer', () => {
        renderWall([p('Anna'), p('Ben')]);
        tiles().forEach((t) => t.classList.remove('is-new')); // the 2 s glow is over
        renderWall([p('Anna'), p('Ben'), p('Leo')]);
        expect(tileOf('Leo').classList.contains('is-new')).toBe(true);
        expect(tileOf('Anna').classList.contains('is-new')).toBe(false);
        expect(tileOf('Ben').classList.contains('is-new')).toBe(false);
    });

    it('keeps the "waiting for more…" tile last, as the same node', () => {
        renderWall([p('Anna')]);
        const waiting = list.childNodes[list.childNodes.length - 1];
        renderWall([p('Anna'), p('Ben')]);
        expect(list.childNodes[list.childNodes.length - 1]).toBe(waiting);
        expect(waiting.classList.contains('dashboard-player-card--waiting')).toBe(true);
    });
});

describe('the second broadcast of a join changes nothing (#2964)', () => {
    it('touches no DOM when only fields the wall does not show changed', () => {
        renderWall([p('Anna'), p('Ben', { onboarded: false })]);
        log = [];
        created = [];
        renderWall([p('Anna'), p('Ben', { onboarded: true, score: 0, language: 'de' })]);
        expect(log).toEqual([]);
        expect(created).toEqual([]);
    });
});

describe('the wall still follows real changes (#2964)', () => {
    it('marks a guest who went away on their existing tile', () => {
        renderWall([p('Anna'), p('Ben'), p('Mia')]);
        const ben = tileOf('Ben');
        const mia = tileOf('Mia');
        renderWall([p('Anna'), p('Ben', { connected: false }), p('Mia')]);
        expect(tileOf('Ben')).toBe(ben);
        expect(tileOf('Mia')).toBe(mia);
        expect(ben.classList.contains('dashboard-player-card--disconnected')).toBe(true);
        expect(ben.textContent).toContain('(away)');
        // Connected first: Ben moves behind Mia.
        expect(names()).toEqual(['Anna', 'Mia', 'Ben']);

        renderWall([p('Anna'), p('Ben'), p('Mia')]);
        expect(tileOf('Ben')).toBe(ben);
        expect(ben.classList.contains('dashboard-player-card--disconnected')).toBe(false);
        expect(ben.textContent).not.toContain('(away)');
    });

    it('removes only the tile of a guest who left', () => {
        renderWall([p('Anna'), p('Ben'), p('Mia')]);
        const anna = tileOf('Anna');
        const mia = tileOf('Mia');
        log = [];
        renderWall([p('Anna'), p('Mia')]);
        expect(names()).toEqual(['Anna', 'Mia']);
        expect(tileOf('Anna')).toBe(anna);
        expect(tileOf('Mia')).toBe(mia);
        expect(log.filter(([op]) => op === 'remove')).toHaveLength(1);
    });

    it('updates the column count with the players', () => {
        renderWall(['A', 'B', 'C', 'D', 'E', 'F'].map((n) => p(n)));
        expect(list.getAttribute('data-cols')).toBe('3');
        renderWall(['A', 'B', 'C', 'D', 'E', 'F', 'G'].map((n) => p(n)));
        expect(list.getAttribute('data-cols')).toBe('4');
    });
});

describe('only new tiles carry the slide-in (#2964)', () => {
    it('has no animation on the base tile rule', () => {
        const base = CSS.match(/\n\.dashboard-player-card \{[^}]*\}/)[0];
        expect(base).not.toMatch(/animation:/);
        expect(CSS).toMatch(/\.dashboard-player-card\.is-new \{[^}]*animation: slide-in/);
    });
});
