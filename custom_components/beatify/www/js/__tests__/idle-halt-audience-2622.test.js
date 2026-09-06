/**
 * #2622 — the idle-halt banner must not tell guests to tap a host-only button.
 *
 * `updateRevealView` toggled `#reveal-idle-halt` on `data.idle_halt` and never
 * looked at who was reading it. The one sentence it carried said "Tap Next
 * round to keep going." — but "Next round" lives in `#reveal-admin-controls`,
 * which stays `hidden` for guests. Every stalled round sent the whole room
 * hunting their phones for a button that is not there.
 *
 * Both audiences still get the banner (the round really did stall); only the
 * instruction differs. These tests drive the real `updateRevealView` for a host
 * and for a guest, and lock the two sentences against the locale files.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
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

// The imperative each locale uses for "tap it yourself". A guest cannot act,
// so none of these may appear in the guest sentence.
const TAP_VERB = { en: 'Tap', de: 'Tippe', es: 'Toca', fr: 'Appuie', it: 'Tocca', nl: 'Tik' };

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
    };
    return el;
}

let els;
let locale = 'en';
global.window = {
    BeatifyUtils: {
        t: (key) => key.split('.').reduce((n, p) => (n && typeof n === 'object' ? n[p] : undefined), i18n[locale]) ?? key,
        getLocalizedSongField: (song, field) => (song ? song[field] : undefined),
    },
    matchMedia: () => ({ matches: true, addEventListener: () => {} }),
};
global.WebSocket = { OPEN: 1 };
global.document = {
    getElementById: (id) => els[id] || null,
    querySelector: () => null,
};

const mockState = { playerName: null, lastRevealContext: null };
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

const { updateRevealView, stopRevealCountdown, renderIdleHalt, IDLE_HALT_KEYS } =
    await import('../player-reveal.js');

beforeEach(() => {
    locale = 'en';
    els = {
        'reveal-round': makeEl('reveal-round'),
        'reveal-total': makeEl('reveal-total'),
        'reveal-idle-halt': makeEl('reveal-idle-halt'),
        'reveal-idle-halt-text': makeEl('reveal-idle-halt-text'),
        'reveal-admin-controls': makeEl('reveal-admin-controls'),
        'next-round-btn': makeEl('next-round-btn'),
    };
    els['reveal-idle-halt'].classList.add('hidden');
    els['reveal-idle-halt-text'].setAttribute('data-i18n', IDLE_HALT_KEYS.host);
    mockState.playerName = null;
    mockState.lastRevealContext = null;
});

afterEach(() => stopRevealCountdown());

function stalledRound(playerName, hostName) {
    mockState.playerName = playerName;
    updateRevealView({
        round: 3,
        total_rounds: 10,
        idle_halt: true,
        song: { title: 'Africa', artist: 'Toto', year: 1982 },
        players: [
            { name: hostName, is_admin: true, score: 0 },
            { name: 'Bob', is_admin: false, score: 0 },
        ],
    });
    return {
        banner: els['reveal-idle-halt'],
        text: els['reveal-idle-halt-text'],
        adminControls: els['reveal-admin-controls'],
    };
}

describe('#2622 idle-halt banner speaks to its reader', () => {
    it('a guest is told to wait, not to tap a button they do not have', () => {
        const { banner, text, adminControls } = stalledRound('Bob', 'Alice');

        expect(banner.classList.contains('hidden')).toBe(false);
        expect(adminControls.classList.contains('hidden')).toBe(true);
        expect(text.textContent).toBe(i18n.en.reveal.idleHaltBannerGuest);
        expect(text.textContent).not.toContain('Tap Next round');
    });

    it('the host still gets the actionable sentence', () => {
        const { banner, text, adminControls } = stalledRound('Alice', 'Alice');

        expect(banner.classList.contains('hidden')).toBe(false);
        expect(adminControls.classList.contains('hidden')).toBe(false);
        expect(text.textContent).toBe(i18n.en.reveal.idleHaltBanner);
        expect(text.textContent).toContain('Tap Next round');
    });

    it('rewrites data-i18n too, so a language switch keeps the right sentence', () => {
        const { text } = stalledRound('Bob', 'Alice');
        expect(text.getAttribute('data-i18n')).toBe(IDLE_HALT_KEYS.guest);

        stalledRound('Alice', 'Alice');
        expect(text.getAttribute('data-i18n')).toBe(IDLE_HALT_KEYS.host);
    });

    it('hides the banner when the round is not stalled', () => {
        mockState.playerName = 'Bob';
        updateRevealView({ song: {}, players: [{ name: 'Bob', is_admin: false }] });
        expect(els['reveal-idle-halt'].classList.contains('hidden')).toBe(true);
    });

    it('survives a page without the banner', () => {
        expect(() => renderIdleHalt(null, true, false)).not.toThrow();
    });

    it('both sentences exist in all six locales and the guest one never says "tap"', () => {
        for (const l of LOCALES) {
            const host = i18n[l].reveal.idleHaltBanner;
            const guest = i18n[l].reveal.idleHaltBannerGuest;
            expect(host, `${l}: host`).toBeTruthy();
            expect(guest, `${l}: guest`).toBeTruthy();
            expect(guest, `${l}: distinct`).not.toBe(host);
            expect(guest, `${l}: imperative`).not.toContain(TAP_VERB[l]);
        }
    });

    it('the banner text node carries the id the renderer writes to', () => {
        expect(PLAYER_HTML).toContain('id="reveal-idle-halt-text"');
    });
});
