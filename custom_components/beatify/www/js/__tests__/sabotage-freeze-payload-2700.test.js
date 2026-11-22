/**
 * #2700 — the sabotage freeze window comes off the wire, not out of a copy.
 *
 * The server already did the hard part: `game/player_registry.py` counts the
 * freeze down against its own clock and ships the remainder as
 * `sabotage_freeze_remaining` on every player-state frame (and, since #2700, as
 * `freeze_remaining` on the private "you were sabotaged" hit). Nothing in
 * `www/js/` read either field. `player-game.js` instead carried
 * `var SABOTAGE_FREEZE_MS = 3000;` under a comment calling itself a mirror of
 * `const.SABOTAGE_FREEZE_SECONDS` — with no test holding the two together.
 *
 * Tuning that constant therefore unlocked the submit button at the wrong moment:
 * the server kept answering ERR_FROZEN while the button looked live.
 *
 * These tests drive the real module. The first one reads
 * `SABOTAGE_FREEZE_SECONDS` out of `const.py`, so it fails the moment the
 * constant is changed there and the client is still working from a copy — which
 * is the whole point of the pair with #2699. The rest pin the payload as the
 * only source of the duration, and the fallback for a payload that has none.
 *
 * Harness (element stubs, player-utils mock) mirrors player-sabotage-1665.test.js.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const CONST_PY = readFileSync(join(__dirname, '..', '..', '..', 'const.py'), 'utf8');
const PLAYER_GAME_SRC = readFileSync(join(__dirname, '..', 'player-game.js'), 'utf8');

/** The freeze duration as the server defines it, in whole seconds. */
const FREEZE_SECONDS = (() => {
    const m = /^SABOTAGE_FREEZE_SECONDS\s*(?::[^=]+)?=\s*(\d+)/m.exec(CONST_PY);
    if (!m) throw new Error('SABOTAGE_FREEZE_SECONDS not found in const.py');
    return Number(m[1]);
})();

global.WebSocket = { OPEN: 1, CONNECTING: 0, CLOSED: 3 };
global.IntersectionObserver = class {
    observe() {}
    disconnect() {}
};
global.window = {
    BeatifyUtils: { t: (key) => key },
    matchMedia: () => ({ matches: true, addEventListener: () => {} }),
};

function makeEl(id) {
    const classes = new Set();
    const children = {};
    const kids = [];
    const listeners = {};
    let innerHTML = '';
    const el = {
        id,
        className: '',
        textContent: '',
        value: '1990',
        disabled: false,
        _attrs: {},
        children,
        kids,
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
        querySelector: (sel) => children[sel] || null,
        appendChild: (child) => { kids.push(child); return child; },
        addEventListener: (type, fn) => { (listeners[type] = listeners[type] || []).push(fn); },
        dispatch: (type) => { (listeners[type] || []).forEach((fn) => fn()); },
    };
    Object.defineProperty(el, 'innerHTML', {
        get: () => innerHTML,
        set: (v) => { innerHTML = v; if (v === '') { kids.length = 0; } },
    });
    return el;
}

let els;
global.document = {
    getElementById: (id) => els[id] || null,
    createElement: () => makeEl(),
};

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
        isTitleArtistRaceMode: () => false,
        createModalFocusTrap: () => ({ activate: () => {}, deactivate: () => {} }),
    };
});

const utilsMod = await import('../player-utils.js');
const {
    updateGameView,
    handleSubmitGuess,
    handleSabotaged,
    resetSubmissionState,
} = await import('../player-game.js');

const ME = 'Me';
let sent;

beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-09-07T12:00:00Z'));
    els = {};
    els['submit-btn'] = makeEl('submit-btn');
    els['year-slider'] = makeEl('year-slider');
    els['sabotaged-banner'] = makeEl('sabotaged-banner');
    els['sabotaged-banner-text'] = makeEl('sabotaged-banner-text');
    sent = [];
    utilsMod.state.ws = { readyState: 1, send: (p) => sent.push(JSON.parse(p)) };
    utilsMod.state.playerName = ME;
    resetSubmissionState();
});

afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
});

/** Did a submit actually leave the phone? */
function submitAccepted() {
    sent.length = 0;
    handleSubmitGuess();
    return sent.some((m) => m.type === 'submit');
}

/** One player-state frame naming this player. */
function frame(extra) {
    return { players: [{ name: ME, connected: true, eliminated: false, ...extra }] };
}

describe('the freeze window is const.py\'s, not a copy (#2700)', () => {
    it('locks the submit button for exactly SABOTAGE_FREEZE_SECONDS', () => {
        // The server hit carries the countdown it computed. A client holding its
        // own `SABOTAGE_FREEZE_MS = 3000` unlocks here at 3s no matter what
        // const.py says — so raising SABOTAGE_FREEZE_SECONDS turns this red
        // until the client stops keeping a copy.
        handleSabotaged({ by: 'Bob', effect: 'freeze', freeze_remaining: FREEZE_SECONDS });

        expect(submitAccepted()).toBe(false);
        vi.advanceTimersByTime(FREEZE_SECONDS * 1000 - 100);
        expect(submitAccepted()).toBe(false);

        vi.advanceTimersByTime(100);
        expect(submitAccepted()).toBe(true);
    });

    it('follows the payload rather than any fixed duration', () => {
        // Deliberately not the const.py value: whatever the server sends is the
        // window, whether that is shorter or longer than today's setting.
        const odd = FREEZE_SECONDS + 6;
        handleSabotaged({ by: 'Bob', effect: 'freeze', freeze_remaining: odd });

        vi.advanceTimersByTime(FREEZE_SECONDS * 1000 + 500);
        expect(submitAccepted()).toBe(false);

        vi.advanceTimersByTime(odd * 1000);
        expect(submitAccepted()).toBe(true);
    });

    it('re-aims the lock from every player-state frame', () => {
        // A reload or reconnect mid-freeze arrives with no banner and no hit —
        // only the broadcast. The remainder in it is enough to finish the lock.
        updateGameView(frame({ sabotage_freeze_remaining: 4 }));
        expect(submitAccepted()).toBe(false);

        vi.advanceTimersByTime(2000);
        updateGameView(frame({ sabotage_freeze_remaining: 2 }));
        expect(submitAccepted()).toBe(false);

        vi.advanceTimersByTime(2000);
        expect(submitAccepted()).toBe(true);
    });

    it('releases the button when the server reports 0 remaining', () => {
        handleSabotaged({ by: 'Bob', effect: 'freeze', freeze_remaining: FREEZE_SECONDS });
        expect(submitAccepted()).toBe(false);

        updateGameView(frame({ sabotage_freeze_remaining: 0 }));
        expect(submitAccepted()).toBe(true);
        expect(els['submit-btn'].classList.contains('submit-arc--frozen')).toBe(false);
    });
});

describe('a hit that carries no duration (#2700 fallback)', () => {
    it('holds the lock until a state frame supplies the remainder', () => {
        // An older server's `sabotaged` message has no freeze_remaining. Erring
        // closed keeps the button honest — it never claims to be tappable while
        // the server would answer ERR_FROZEN. The state broadcast follows in the
        // same tick and supplies the real number.
        handleSabotaged({ by: 'Bob', effect: 'freeze' });

        expect(submitAccepted()).toBe(false);
        vi.advanceTimersByTime(60_000);
        expect(submitAccepted()).toBe(false);

        updateGameView(frame({ sabotage_freeze_remaining: 1 }));
        expect(submitAccepted()).toBe(false);
        vi.advanceTimersByTime(1000);
        expect(submitAccepted()).toBe(true);
    });

    it('a frame with no freeze field at all leaves an active lock alone', () => {
        handleSabotaged({ by: 'Bob', effect: 'freeze', freeze_remaining: FREEZE_SECONDS });
        updateGameView(frame({}));  // e.g. a cached client's older payload shape
        expect(submitAccepted()).toBe(false);
    });

    it('the next round clears the lock', () => {
        handleSabotaged({ by: 'Bob', effect: 'freeze' });
        expect(submitAccepted()).toBe(false);
        resetSubmissionState();
        expect(submitAccepted()).toBe(true);
    });
});

describe('player-game.js keeps no copy of the duration (#2700)', () => {
    it('has no SABOTAGE_FREEZE_MS constant', () => {
        expect(/\bvar\s+SABOTAGE_FREEZE_MS\b/.test(PLAYER_GAME_SRC)).toBe(false);
        expect(/SABOTAGE_FREEZE_MS\s*=/.test(PLAYER_GAME_SRC)).toBe(false);
    });

    it('reads the server-computed remainder off both payloads', () => {
        expect(PLAYER_GAME_SRC).toContain('sabotage_freeze_remaining');
        expect(PLAYER_GAME_SRC).toContain('freeze_remaining');
    });
});
