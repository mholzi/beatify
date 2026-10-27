/**
 * #3303 — the encore offer (#2503) on the host's own phone.
 *
 * Variant A of the design gate: the admin page's block (badge, outline button,
 * hint line; same markup and classes as `#admin-encore`) inside
 * `#reveal-admin-controls`, above "Next round". It shows only when the server
 * sent `encore_available` AND the reader is the host; the tap sends the same
 * `{type:'admin', action:'extend_rounds'}` the admin page sends.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const WWW = join(__dirname, '..', '..');
const LOCALES = ['en', 'de', 'es', 'fr', 'it', 'nl'];
const i18n = {};
for (const l of LOCALES) {
    i18n[l] = JSON.parse(readFileSync(join(WWW, 'i18n', `${l}.json`), 'utf8'));
}
const PLAYER_HTML = readFileSync(join(WWW, 'player.html'), 'utf8');

function makeEl(id) {
    const classes = new Set();
    const children = {};
    const el = {
        id,
        textContent: '',
        innerHTML: '',
        _attrs: {},
        children,
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
        getAttribute: (k) => el._attrs[k],
        querySelector: (sel) => children[sel] || null,
        disabled: false,
        _listeners: {},
        addEventListener: (ev, fn) => { (el._listeners[ev] = el._listeners[ev] || []).push(fn); },
        click: () => (el._listeners.click || []).forEach((fn) => fn({ currentTarget: el })),
    };
    return el;
}

let els;
let locale = 'en';
global.window = {
    BeatifyUtils: {
        t: (key, params) => {
            let s = key.split('.').reduce((n, p) => (n && typeof n === 'object' ? n[p] : undefined), i18n[locale]) ?? key;
            for (const [k, v] of Object.entries(params || {})) s = s.replace('{' + k + '}', String(v));
            return s;
        },
        getLocalizedSongField: (song, field) => (song ? song[field] : undefined),
    },
    matchMedia: () => ({ matches: true, addEventListener: () => {} }),
};
global.WebSocket = { OPEN: 1 };
global.document = {
    getElementById: (id) => els[id] || null,
    querySelector: () => null,
};

const sent = [];
const mockState = {
    playerName: null,
    lastRevealContext: null,
    ws: { readyState: 1, send: (m) => sent.push(JSON.parse(m)) },
};
vi.mock('../player-utils.js', () => ({
    state: mockState,
    escapeHtml: (s) => String(s),
    prefersReducedMotion: () => true,
    animateValue: () => {},
    previousState: {},
    isPreviousStateInitialized: () => false,
    AnimationUtils: {},
    triggerConfetti: () => {},
    stopConfetti: () => {},
    isTitleArtistMode: (data) => !!(data && data.title_artist_mode),
}));
vi.mock('../player-game.js', () => ({
    updateLeaderboard: () => {},
    renderArtistReveal: () => {},
    renderMovieReveal: () => {},
}));

const { updateRevealView, stopRevealCountdown } = await import('../player-reveal.js');

const IDS = [
    'reveal-round', 'reveal-total', 'reveal-admin-controls', 'next-round-btn',
    'player-encore', 'player-encore-btn', 'player-encore-label', 'player-encore-hint',
];

beforeEach(() => {
    locale = 'en';
    sent.length = 0;
    els = {};
    for (const id of IDS) els[id] = makeEl(id);
    els['reveal-admin-controls'].classList.add('hidden');
    els['player-encore'].classList.add('hidden');
    mockState.playerName = null;
    mockState.lastRevealContext = null;
});

function reveal(reader, extra) {
    mockState.playerName = reader;
    updateRevealView({
        round: 9,
        total_rounds: 10,
        song: { title: 'Take On Me', artist: 'a-ha', year: 1985 },
        players: [
            { name: 'Host', is_admin: true, score: 0 },
            { name: 'Guest', is_admin: false, score: 0 },
        ],
        ...extra,
    });
    stopRevealCountdown();
    return els['player-encore'];
}

describe('#3303 encore offer on the phone host', () => {
    it('host + encore_available: block shows with count and new finish line', () => {
        locale = 'de';
        const box = reveal('Host', { encore_available: true, encore_rounds: 5 });
        expect(box.classList.contains('hidden')).toBe(false);
        expect(els['player-encore-label'].textContent).toBe('5 Runden dranhängen');
        expect(els['player-encore-hint'].textContent)
            .toBe('Das Ziel rückt auf 15. Der Punktestand bleibt.');
    });

    it('host without encore_available: block stays hidden', () => {
        const box = reveal('Host', {});
        expect(box.classList.contains('hidden')).toBe(true);
    });

    it('guest never sees it, even if the key leaked into the payload', () => {
        const box = reveal('Guest', { encore_available: true, encore_rounds: 5 });
        expect(box.classList.contains('hidden')).toBe(true);
    });

    it('closes again on the next reveal once the window is gone', () => {
        reveal('Host', { encore_available: true, encore_rounds: 5 });
        const box = reveal('Host', { encore_available: false });
        expect(box.classList.contains('hidden')).toBe(true);
    });

    it('tap sends extend_rounds as an admin action, once per tap', () => {
        reveal('Host', { encore_available: true, encore_rounds: 5 });
        reveal('Host', { encore_available: true, encore_rounds: 5 });
        els['player-encore-btn'].click();
        expect(sent).toEqual([{ type: 'admin', action: 'extend_rounds' }]);
        expect(els['player-encore-btn'].disabled).toBe(true);
    });

    it('a guest tap is impossible: no listener is wired for a guest render', () => {
        reveal('Guest', { encore_available: true, encore_rounds: 5 });
        els['player-encore-btn'].click();
        expect(sent).toEqual([]);
    });

    it('markup mirrors #admin-encore and sits inside the host-only controls, above Next round', () => {
        const ctrl = PLAYER_HTML.indexOf('id="reveal-admin-controls"');
        const box = PLAYER_HTML.indexOf('id="player-encore" class="encore-offer hidden"');
        const next = PLAYER_HTML.indexOf('id="next-round-btn"');
        expect(ctrl).toBeGreaterThan(-1);
        expect(box).toBeGreaterThan(ctrl);
        expect(next).toBeGreaterThan(box);
        expect(PLAYER_HTML).toContain('class="encore-badge" data-i18n="admin.encoreBadge"');
        expect(PLAYER_HTML).toContain('id="player-encore-btn" type="button" class="btn btn-outline btn-full-width"');
        expect(PLAYER_HTML).toContain('id="player-encore-hint" class="encore-hint"');
    });
});
