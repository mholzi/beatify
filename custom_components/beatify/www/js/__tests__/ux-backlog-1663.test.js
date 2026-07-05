/**
 * UX backlog #1663 — logic fixes.
 *
 * Covers two of the five logic/behaviour fixes that are cleanly unit-testable
 * against the real modules (no re-implementation):
 *
 *   - resetLeaderboardSummary() (player-game.js): a rematch must clear the
 *     previous game's leader badge, which updateLeaderboardSummary() left stuck
 *     because it early-returns on an empty leaderboard.
 *   - setupRevealReportBtn() (player-reveal.js): the data-quality report submit
 *     must surface an inline error when the WebSocket is closed / send throws,
 *     instead of returning silently.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

// ---- browser-global stubs (must exist before the modules import) -----------
global.WebSocket = { OPEN: 1, CONNECTING: 0, CLOSED: 3 };

function makeEl(id) {
    const classes = new Set();
    const children = {};
    const el = {
        id,
        textContent: '',
        disabled: false,
        _attrs: {},
        children,
        _listeners: {},
        classList: {
            add: (...c) => c.forEach((x) => classes.add(x)),
            remove: (...c) => c.forEach((x) => classes.delete(x)),
            contains: (c) => classes.has(c),
            toggle: (c, on) => { if (on) classes.add(c); else classes.delete(c); return classes.has(c); },
        },
        setAttribute: (k, v) => { el._attrs[k] = v; },
        getAttribute: (k) => el._attrs[k],
        addEventListener: (evt, fn) => { el._listeners[evt] = fn; },
        appendChild: (child) => { el._appended = child; return child; },
        querySelector: (sel) => children[sel] || null,
    };
    return el;
}

let els;
let queryMap;
global.window = {
    BeatifyUtils: { t: (key) => key, getLocalizedSongField: (song, field) => (song ? song[field] : undefined) },
    matchMedia: () => ({ matches: true, addEventListener: () => {} }),
};
global.document = {
    getElementById: (id) => els[id] || null,
    querySelector: (sel) => queryMap[sel] || null,
    createElement: () => makeEl(),
};

// player-reveal.js pulls in a shared mutable state + siblings; mock both.
const mockState = { ws: null, playerName: 'Alice', lastRevealContext: null };
vi.mock('../player-utils.js', () => ({
    state: mockState,
    escapeHtml: (s) => String(s),
    prefersReducedMotion: () => true,
    animateValue: () => {},
    animateScoreChange: () => {},
    showPointsPopup: () => {},
    previousState: {},
    isPreviousStateInitialized: () => false,
    isStreakMilestone: () => false,
    AnimationUtils: {},
    triggerConfetti: () => {},
    stopConfetti: () => {},
}));
vi.mock('../player-game.js', async (importOriginal) => {
    // Keep the real player-game exports (we test resetLeaderboardSummary), but
    // player-reveal only needs a few of them to import cleanly.
    const actual = await importOriginal();
    return actual;
});

const { resetLeaderboardSummary, updateLeaderboardSummary } = await import('../player-game.js');
const { setupRevealReportBtn } = await import('../player-reveal.js');

beforeEach(() => {
    els = {};
    queryMap = {};
    mockState.ws = null;
    mockState.lastRevealContext = null;
});

describe('resetLeaderboardSummary — #1663 rematch reset', () => {
    it('clears both summary badges', () => {
        els['leaderboard-summary'] = makeEl('leaderboard-summary');
        els['reveal-leaderboard-summary'] = makeEl('reveal-leaderboard-summary');
        // Simulate a finished game: leader text painted from a live board.
        updateLeaderboardSummary([{ name: 'Alice', score: 500 }]);
        expect(els['leaderboard-summary'].textContent).toBe('Alice: 500');

        resetLeaderboardSummary();
        expect(els['leaderboard-summary'].textContent).toBe('');
        expect(els['reveal-leaderboard-summary'].textContent).toBe('');
    });

    it('is a no-op when the summary elements are absent', () => {
        expect(() => resetLeaderboardSummary()).not.toThrow();
    });
});

describe('setupRevealReportBtn — #1663 failure feedback', () => {
    function wire() {
        const btn = makeEl('reveal-report-btn');
        els['reveal-report-btn'] = btn;
        const row = makeEl();
        queryMap['.reveal-report-row'] = row;
        setupRevealReportBtn();
        return { btn, row };
    }

    it('surfaces an inline error when the socket is closed', () => {
        const { btn, row } = wire();
        mockState.lastRevealContext = { song: { artist: 'Toto', title: 'Africa', year: 1982 } };
        mockState.ws = { readyState: WebSocket.CLOSED, send: () => {} };

        btn._listeners.click();

        // An error node was appended to the report row and the button stays usable.
        expect(row._appended).toBeTruthy();
        expect(row._appended.classList.contains('hidden')).toBe(false);
        expect(btn.disabled).toBe(false);
    });

    it('surfaces an inline error when send() throws', () => {
        const { btn, row } = wire();
        mockState.lastRevealContext = { song: { artist: 'Toto', title: 'Africa', year: 1982 } };
        mockState.ws = { readyState: WebSocket.OPEN, send: () => { throw new Error('boom'); } };

        btn._listeners.click();

        expect(row._appended).toBeTruthy();
        expect(row._appended.classList.contains('hidden')).toBe(false);
        expect(btn.disabled).toBe(false);
    });

    it('marks the button done on a successful send (no error node shown)', () => {
        const { btn } = wire();
        mockState.lastRevealContext = { song: { artist: 'Toto', title: 'Africa', year: 1982 } };
        let sent = null;
        mockState.ws = { readyState: WebSocket.OPEN, send: (msg) => { sent = msg; } };

        btn._listeners.click();

        expect(JSON.parse(sent).type).toBe('report_data');
        expect(btn.disabled).toBe(true);
        expect(btn.textContent).toBe('reveal.reportBtnDone');
    });
});
