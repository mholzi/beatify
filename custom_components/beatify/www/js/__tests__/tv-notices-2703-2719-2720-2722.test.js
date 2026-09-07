/**
 * The four things the TV showed as a number changing with no explanation.
 *
 * #2703 idle halt      — the round stalled and the screen said nothing.
 * #2719 Finale ×2      — the deciding round's scores doubled, unannounced.
 * #2720 movie quiz     — one guest earned +5 and only their phone knew why.
 * #2722 finale playoff — the game "ended", another song started, silence.
 *
 * All four flags were already in the TV payload (game/serializers.py); the
 * fix is display, not protocol. So these tests drive the REAL dashboard.js
 * through the surface the TV actually uses — a `state` broadcast on the
 * WebSocket — and assert what ends up on the elements.
 *
 * Deliberately NOT a source-text scan. #2701 catalogued the tests in this repo
 * that assert a particular string exists in a file: they pass while the feature
 * is broken and fail on a harmless rename. `dashboard.js` is a self-contained
 * IIFE with no exports, but it only touches a handful of globals, so a stubbed
 * `document` + a fake `WebSocket` are enough to run the shipped code end to
 * end and require BEHAVIOUR: banner hidden, flag set, banner rendered.
 *
 * The expected sentences are read from the locale files rather than typed
 * here, so a copy edit does not break the test and a MISSING key does — the
 * i18n lookup below returns the dotted key on a miss, which no assertion
 * accepts.
 */
import { describe, it, expect, beforeEach } from 'vitest';
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

let locale = 'en';
function lookup(key, loc) {
    return key.split('.').reduce((n, p) => (n && typeof n === 'object' ? n[p] : undefined), i18n[loc || locale]);
}
/** Mirrors BeatifyI18n.t: dotted lookup, `{param}` interpolation, key on a miss. */
function translate(key, paramsOrFallback) {
    const raw = lookup(key);
    if (typeof raw !== 'string') {
        return typeof paramsOrFallback === 'string' ? paramsOrFallback : key;
    }
    if (paramsOrFallback && typeof paramsOrFallback === 'object') {
        return Object.keys(paramsOrFallback).reduce(
            (s, p) => s.split(`{${p}}`).join(String(paramsOrFallback[p])), raw);
    }
    return raw;
}

// --- a document just real enough for dashboard.js ---------------------------
const els = {};
function makeEl(id) {
    const classes = new Set(['hidden']);
    const el = {
        id, textContent: '', innerHTML: '', src: '', style: {}, dataset: {}, _attrs: {},
        children: [], firstChild: null,
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
        getAttribute: (k) => (k in el._attrs ? el._attrs[k] : null),
        removeAttribute: (k) => { delete el._attrs[k]; },
        appendChild: (c) => { el.children.push(c); return c; },
        removeChild: () => {},
        insertAdjacentHTML: () => {},
        remove: () => {},
        addEventListener: () => {},
        removeEventListener: () => {},
        querySelector: () => null,
        querySelectorAll: () => [],
        closest: () => null,
        getBoundingClientRect: () => ({ width: 0, height: 0, top: 0, left: 0 }),
        focus: () => {},
        play: () => Promise.resolve(),
        pause: () => {},
    };
    return el;
}
/** `#id` — the element the renderers write to, created on first ask. */
const byId = (id) => (els[id] = els[id] || makeEl(id));
const visible = (id) => !byId(id).classList.contains('hidden');

global.window = {
    BeatifyUtils: {
        t: translate,
        escapeHtml: (s) => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;'),
        debug: () => {},
        waitForI18n: async () => false,
        getLocalizedSongField: (song, field) => (song ? song[field] : undefined),
        hydrateLeaderboard: (lb) => lb || [],
        showView: (all, viewId) => all.forEach((v) => v && v.classList.toggle('hidden', v.id !== viewId)),
        createReconnectGuard: () => ({ cancel: () => {}, schedule: () => {} }),
        formatNumber: (n) => String(n),
        animateValue: () => {},
        prefersReducedMotion: () => true,
        taVerdictLabel: (ok, pts) => (ok ? `+${pts}` : '0'),
        taTallyPercents: () => ({ yes: 0, no: 0 }),
    },
    addEventListener: () => {},
    matchMedia: () => ({ matches: true, addEventListener: () => {} }),
    location: { host: 'tv.local', protocol: 'http:', origin: 'http://tv.local' },
};
global.document = {
    readyState: 'complete',
    visibilityState: 'visible',
    body: makeEl('body'),
    documentElement: makeEl('html'),
    getElementById: byId,
    querySelector: () => null,
    querySelectorAll: () => [],
    createElement: (t) => makeEl(t),
    addEventListener: () => {},
};
Object.defineProperty(globalThis, 'navigator', { value: {}, configurable: true, writable: true });
global.location = global.window.location;

/** The socket dashboard.js opens; the tests push broadcasts through it. */
let socket = null;
class FakeWebSocket {
    constructor() { this.readyState = 1; socket = this; }
    send() {}
    close() {}
}
FakeWebSocket.OPEN = 1;
global.WebSocket = FakeWebSocket;

await import('../dashboard.js');

/**
 * Push one server `state` broadcast and let the #1705 render coalescer flush
 * (it schedules on requestAnimationFrame, falling back to setTimeout(16) here).
 * `_n` keeps every payload distinct so the coalescer's dirty-check never
 * skips a render the test is waiting for.
 */
let nonce = 0;
async function broadcast(state) {
    socket.onmessage({ data: JSON.stringify(Object.assign({ type: 'state', _n: nonce++ }, state)) });
    await new Promise((r) => setTimeout(r, 40));
}

const REVEAL = { phase: 'REVEAL', game_id: 'g1', round: 10, total_rounds: 10, song: { title: 'Africa', artist: 'Toto' }, players: [], leaderboard: [] };
const PLAYING = { phase: 'PLAYING', game_id: 'g1', round: 10, total_rounds: 10, song: { title: 'Africa', artist: 'Toto' }, players: [], leaderboard: [] };

beforeEach(() => { locale = 'en'; });

describe('#2703 the TV explains a stalled round', () => {
    it('says nothing while the round is running normally', async () => {
        await broadcast(REVEAL);
        expect(visible('dashboard-idle-halt')).toBe(false);
    });

    it('shows the audience sentence when the game is idle-halted', async () => {
        await broadcast({ ...REVEAL, idle_halt: true });
        expect(visible('dashboard-idle-halt')).toBe(true);
        expect(byId('dashboard-idle-halt-text').textContent)
            .toBe(i18n.en.reveal.idleHaltBannerGuest);
    });

    it('never tells the TV to tap a button it does not have', async () => {
        await broadcast({ ...REVEAL, idle_halt: true });
        // The TV is a read-only observer, so it must not get the host sentence.
        expect(byId('dashboard-idle-halt-text').textContent)
            .not.toBe(i18n.en.reveal.idleHaltBanner);
    });

    it('takes the banner back down when the host starts the next round', async () => {
        await broadcast({ ...REVEAL, idle_halt: true });
        await broadcast({ ...REVEAL, idle_halt: false });
        expect(visible('dashboard-idle-halt')).toBe(false);
    });
});

describe('#2719 the TV says why the last round scores double', () => {
    it('stays quiet on an ordinary round', async () => {
        await broadcast({ ...PLAYING, finale_double_active: false });
        expect(visible('dashboard-finale-banner-playing')).toBe(false);
    });

    it('announces Finale ×2 while the final round plays', async () => {
        await broadcast({ ...PLAYING, finale_double_active: true });
        expect(visible('dashboard-finale-banner-playing')).toBe(true);
        expect(byId('dashboard-finale-banner-playing').textContent)
            .toBe(i18n.en.game.finaleDouble);
    });

    it('keeps it up during the reveal, where the doubled scores are read out', async () => {
        await broadcast({ ...REVEAL, finale_double_active: true });
        expect(visible('dashboard-finale-banner-reveal')).toBe(true);
        expect(byId('dashboard-finale-banner-reveal').textContent)
            .toBe(i18n.en.game.finaleDouble);
    });

    it('does not infer the finale from last_round alone', async () => {
        // The server already folds `finale_double_enabled and last_round` into
        // the flag; a last round WITHOUT the opt-in bonus must stay silent.
        await broadcast({ ...REVEAL, last_round: true, finale_double_active: false });
        expect(visible('dashboard-finale-banner-reveal')).toBe(false);
    });
});

describe('#2720 the movie quiz result reaches the TV', () => {
    const withMovie = (results) => ({
        ...REVEAL,
        movie_challenge: { correct_movie: 'Top Gun', options: ['Top Gun'], results },
    });

    it('is hidden when no movie quiz ran', async () => {
        await broadcast(REVEAL);
        expect(visible('reveal-movie-challenge')).toBe(false);
    });

    it('names the film and the guest who got it', async () => {
        await broadcast(withMovie({ winners: [{ name: 'Ada', time: 3.1, bonus: 5 }], wrong_guesses: [] }));
        expect(visible('reveal-movie-challenge')).toBe(true);
        const html = byId('reveal-movie-challenge').innerHTML;
        expect(html).toContain('Top Gun');
        expect(html).toContain('Ada');
        expect(html).toContain('+5');
        expect(html).toContain(i18n.en.movieChallenge.theMovieWas);
    });

    it('names the film even when nobody got it', async () => {
        await broadcast(withMovie({ winners: [], wrong_guesses: [{ name: 'Bob', guess: 'Alien' }] }));
        expect(visible('reveal-movie-challenge')).toBe(true);
        const html = byId('reveal-movie-challenge').innerHTML;
        expect(html).toContain('Top Gun');
        expect(html).toContain(i18n.en.movieChallenge.noWinner);
    });

    it('escapes a player name instead of injecting it as markup', async () => {
        await broadcast(withMovie({ winners: [{ name: '<img src=x>', bonus: 5 }], wrong_guesses: [] }));
        expect(byId('reveal-movie-challenge').innerHTML).not.toContain('<img src=x>');
    });

    it('is still shown in Title & Artist mode — the quiz runs independently', async () => {
        await broadcast({
            ...withMovie({ winners: [{ name: 'Ada', bonus: 5 }], wrong_guesses: [] }),
            title_artist_mode: true,
        });
        expect(visible('reveal-movie-challenge')).toBe(true);
    });
});

describe('#2722 the TV explains the extra song', () => {
    const roster = [
        { name: 'Ada', playoff_spectator: false },
        { name: 'Bob', playoff_spectator: false },
        { name: 'Cleo', playoff_spectator: true },
    ];

    it('stays hidden while no playoff is running', async () => {
        await broadcast({ ...PLAYING, leaderboard: roster });
        expect(visible('dashboard-playoff-banner-playing')).toBe(false);
    });

    it('names the two who are still playing', async () => {
        await broadcast({ ...PLAYING, finale_playoff_active: true, leaderboard: roster, players: roster });
        expect(visible('dashboard-playoff-banner-playing')).toBe(true);
        const text = byId('dashboard-playoff-banner-playing').textContent;
        expect(text).toContain('Ada');
        expect(text).toContain('Bob');
        expect(text).not.toContain('Cleo');
    });

    it('does not treat a player eliminated earlier as a finalist', async () => {
        await broadcast({
            ...PLAYING,
            finale_playoff_active: true,
            leaderboard: [...roster, { name: 'Dan', playoff_spectator: false, eliminated: true }],
        });
        expect(byId('dashboard-playoff-banner-playing').textContent).not.toContain('Dan');
    });

    it('still explains the extra song when the roster has not arrived', async () => {
        await broadcast({ ...PLAYING, finale_playoff_active: true, leaderboard: [], players: [] });
        expect(visible('dashboard-playoff-banner-playing')).toBe(true);
        expect(byId('dashboard-playoff-banner-playing').textContent)
            .toContain(i18n.en.dashboard.finalePlayoffBannerAnon);
    });

    it('carries into the reveal, where the tie is on screen', async () => {
        await broadcast({ ...REVEAL, finale_playoff_active: true, leaderboard: roster, players: roster });
        expect(visible('dashboard-playoff-banner-reveal')).toBe(true);
        expect(byId('dashboard-playoff-banner-reveal').textContent).toContain('Ada');
    });
});

describe('the four notices speak every language the game does', () => {
    it.each(LOCALES)('%s renders real sentences, not dotted keys', async (loc) => {
        locale = loc;
        await broadcast({
            ...REVEAL,
            idle_halt: true,
            finale_double_active: true,
            finale_playoff_active: true,
            leaderboard: [{ name: 'Ada' }, { name: 'Bob' }],
            movie_challenge: { correct_movie: 'Top Gun', results: { winners: [], wrong_guesses: [] } },
        });
        const texts = [
            byId('dashboard-idle-halt-text').textContent,
            byId('dashboard-finale-banner-reveal').textContent,
            byId('dashboard-playoff-banner-reveal').textContent,
            byId('reveal-movie-challenge').innerHTML,
        ];
        for (const t of texts) {
            expect(t.length).toBeGreaterThan(0);
            expect(t).not.toMatch(/\b(reveal|game|dashboard|movieChallenge)\.[a-zA-Z]+\b/);
        }
        // The playoff sentence must actually interpolate the finalists.
        expect(byId('dashboard-playoff-banner-reveal').textContent).toContain('Ada');
        expect(byId('dashboard-playoff-banner-reveal').textContent).not.toContain('{players}');
    });
});
