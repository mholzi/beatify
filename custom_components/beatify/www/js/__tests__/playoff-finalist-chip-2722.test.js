/**
 * #2722 — the two finalists were the only people in the room told nothing.
 *
 * When the last round ends in a tie for first, the game arms a playoff and
 * starts another song. Everyone who is out of that round gets a screen saying
 * so (`playoff_spectator`, #2578), and the TV now carries a banner. The two
 * players the playoff is ABOUT saw the ordinary "Final Round!" chip — the same
 * chip as every other last round — while a song nobody asked for started.
 *
 * `finale_playoff_active` and `playoff_spectator` have both been in the payload
 * since #1725/#2578, so this is display work. These tests drive the real
 * `updateGameView` and assert which sentence lands on the chip, in the order
 * of precedence the room needs: an unexplained EXTRA round outranks doubled
 * points, which outranks "this is the last one".
 *
 * Harness mirrors player-sabotage-1665.test.js: real module, mocked
 * player-utils.js, stubbed browser globals (the vitest env is `node`).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const LOCALES = ['en', 'de', 'es', 'fr', 'it', 'nl'];
const i18n = {};
for (const l of LOCALES) {
    i18n[l] = JSON.parse(readFileSync(join(__dirname, '..', '..', 'i18n', `${l}.json`), 'utf8'));
}
let locale = 'en';

global.WebSocket = { OPEN: 1, CONNECTING: 0, CLOSED: 3 };
global.IntersectionObserver = class { observe() {} disconnect() {} };
global.window = {
    BeatifyUtils: {
        t: (key) => key.split('.').reduce((n, p) => (n && typeof n === 'object' ? n[p] : undefined), i18n[locale]) ?? key,
    },
    matchMedia: () => ({ matches: true, addEventListener: () => {} }),
};

function makeEl(id) {
    const classes = new Set(['hidden']);
    const el = {
        id, textContent: '', className: '', disabled: false, _attrs: {},
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
        getAttribute: (k) => (k in el._attrs ? el._attrs[k] : null),
        querySelector: () => null,
        appendChild: (c) => c,
        addEventListener: () => {},
    };
    return el;
}

let els;
global.document = { getElementById: (id) => els[id] || null, createElement: () => makeEl() };

vi.mock('../player-utils.js', () => {
    const state = { ws: null, playerName: null };
    return {
        state,
        escapeHtml: (s) => String(s),
        showConfirmModal: async () => true,
        prefersReducedMotion: () => true,
        animateValue: () => {},
        previousState: {},
        isPreviousStateInitialized: () => false,
        detectRankChanges: () => ({}),
        updatePreviousState: () => {},
        AnimationUtils: {},
        AnimationQueue: { isRunning: () => false, skipAll: () => {} },
        LEADERBOARD_LAZY_CONFIG: {},
        lazyLeaderboardState: {},
        initLeaderboardObserver: () => {},
        renderLazyLeaderboardRange: () => {},
        renderLeaderboardEntry: () => '',
        calculateInitialVisibleRange: () => [0, 0],
        setupLeaderboardResizeHandler: () => {},
        setEnergyLevel: () => {},
        triggerConfetti: () => {},
        stopConfetti: () => {},
        isTitleArtistMode: () => false,
        createModalFocusTrap: () => ({ activate: () => {}, deactivate: () => {} }),
    };
});

const utilsMod = await import('../player-utils.js');
const { updateGameView, resetSubmissionState } = await import('../player-game.js');

const ME = 'Ada';
const RIVAL = 'Bob';
const OUT = 'Cleo';

beforeEach(() => {
    vi.useFakeTimers();
    locale = 'en';
    els = { 'last-round-banner': makeEl('last-round-banner') };
    utilsMod.state.ws = null;
    utilsMod.state.playerName = ME;
    resetSubmissionState();
});
afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
});

const chip = () => els['last-round-banner'];
const shown = () => !chip().classList.contains('hidden');

/** A playoff round: Ada and Bob tied for first, Cleo sitting it out. */
function playoff(extra) {
    return Object.assign({
        round: 11,
        total_rounds: 10,
        last_round: true,
        finale_playoff_active: true,
        players: [
            { name: ME, playoff_spectator: false },
            { name: RIVAL, playoff_spectator: false },
            { name: OUT, playoff_spectator: true },
        ],
    }, extra);
}

describe('#2722 the finalists are told they are in a playoff', () => {
    it('names the playoff instead of repeating "Final Round!"', () => {
        updateGameView(playoff());
        expect(shown()).toBe(true);
        expect(chip().textContent).toBe(i18n.en.game.finalePlayoffChip);
        expect(chip().textContent).not.toBe(i18n.en.game.finalRound);
    });

    it('outranks the Finale ×2 copy — an extra round needs explaining first', () => {
        updateGameView(playoff({ finale_double_active: true }));
        expect(chip().textContent).toBe(i18n.en.game.finalePlayoffChip);
    });

    it('leaves the ordinary final round alone', () => {
        updateGameView({ last_round: true, players: [{ name: ME }] });
        expect(shown()).toBe(true);
        expect(chip().textContent).toBe(i18n.en.game.finalRound);
    });

    it('still advertises Finale ×2 when no playoff is running', () => {
        updateGameView({ last_round: true, finale_double_active: true, players: [{ name: ME }] });
        expect(chip().textContent).toBe(i18n.en.game.finaleDouble);
    });

    it('does not claim a spectator is in the playoff', () => {
        utilsMod.state.playerName = OUT;
        updateGameView(playoff({ last_round: false }));
        // Cleo is watching, not playing — no chip claiming a tie for first.
        expect(chip().textContent).not.toBe(i18n.en.game.finalePlayoffChip);
    });

    it('does not claim an eliminated player is in the playoff', () => {
        utilsMod.state.playerName = OUT;
        updateGameView(playoff({
            last_round: false,
            players: [
                { name: ME, playoff_spectator: false },
                { name: OUT, playoff_spectator: false, eliminated: true },
            ],
        }));
        expect(chip().textContent).not.toBe(i18n.en.game.finalePlayoffChip);
    });

    it('hides the chip again on an ordinary mid-game round', () => {
        updateGameView(playoff());
        updateGameView({ last_round: false, players: [{ name: ME }] });
        expect(shown()).toBe(false);
    });

    it.each(LOCALES)('%s has a real sentence for it, not the dotted key', (loc) => {
        locale = loc;
        updateGameView(playoff());
        expect(chip().textContent).toBe(i18n[loc].game.finalePlayoffChip);
        expect(chip().textContent).not.toContain('game.finalePlayoffChip');
        expect(chip().textContent.length).toBeGreaterThan(0);
    });
});
