/**
 * #2982: the TV's "(away)" marker for a disconnected guest was hard-coded
 * English, so it stayed English on a German, Spanish, French, Italian or Dutch
 * dashboard. It now reads the same `lobby.away` key the phones already use.
 *
 * The tile tests run the real `buildPlayerTile` / `syncPlayerTile` from
 * dashboard.js with a `t()` backed by each shipped locale file.
 */
import { describe, it, expect } from 'vitest';
import { declaration, evaluate, readSource, locale } from './helpers/js-source.js';

const SRC = readSource('dashboard.js');
const LANGS = ['de', 'en', 'es', 'fr', 'it', 'nl'];

class Node {
    constructor(tag) {
        this.tagName = tag.toUpperCase();
        this.childNodes = [];
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
    setAttribute(k, v) { this.attrs[k] = String(v); }
    getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
    appendChild(n) { this.childNodes.push(n); return n; }
    removeChild(n) { this.childNodes.splice(this.childNodes.indexOf(n), 1); return n; }
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

function tFor(lang) {
    const pack = locale(lang);
    return (key, fallback) => {
        const v = key.split('.').reduce((o, k) => (o ? o[k] : undefined), pack);
        return typeof v === 'string' ? v : fallback;
    };
}

function tileFns(lang) {
    const snippets = ['buildPlayerTile', 'syncPlayerTile'].map((n) => declaration(SRC, n, 'dashboard.js'));
    return evaluate(snippets, '{ buildPlayerTile, syncPlayerTile }', {
        document: { createElement: (tag) => new Node(tag) },
        utils: { t: tFor(lang), escapeHtml: (s) => s },
        endAvatarGradient: () => 'linear-gradient(#000,#fff)',
    });
}

describe('every shipped language has the away word (#2982)', () => {
    it.each(LANGS)('%s has a non-empty lobby.away', (lang) => {
        const word = locale(lang).lobby && locale(lang).lobby.away;
        expect(typeof word).toBe('string');
        expect(word.trim()).not.toBe('');
    });
});

describe('the TV lobby tile speaks the dashboard language (#2982)', () => {
    it.each(LANGS)('%s: a guest who is away is marked in that language', (lang) => {
        const { buildPlayerTile } = tileFns(lang);
        const tile = buildPlayerTile({ name: 'Ben', connected: false });
        const badge = tile.querySelector('.away-badge');
        expect(badge.textContent).toBe('(' + locale(lang).lobby.away + ')');
    });

    it('German reads "(abwesend)", not "(away)"', () => {
        const { buildPlayerTile, syncPlayerTile } = tileFns('de');
        const tile = buildPlayerTile({ name: 'Ben', connected: true });
        expect(tile.querySelector('.away-badge')).toBeNull();
        syncPlayerTile(tile, { name: 'Ben', connected: false });
        expect(tile.querySelector('.away-badge').textContent).toBe('(abwesend)');
    });
});

describe('no hard-coded English marker is left on the TV (#2982)', () => {
    it('dashboard.js has no literal "(away)"', () => {
        expect(SRC).not.toMatch(/'\(away\)'|>\(away\)</);
    });
});
