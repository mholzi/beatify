/**
 * #3390 — honest join states on the phone.
 *
 * Offline, a server error and "game does not exist" used to render the same
 * "Game not found, get a new QR code" screen, and the status request could
 * spin forever. After a Home Assistant restart the phone said "Connected" and
 * froze on its last view. One fixture per state:
 *
 *   offline (fetch throws)          → offline-view
 *   server error (500, non-JSON)    → ha-error-view
 *   no game ({exists:false})        → not-found-view
 *   status timeout (request hangs)  → offline-view after 10 s per attempt
 *   slow (> 5 s)                    → second line on the loading view
 *   after HA restart (GAME_NOT_STARTED on the socket) → game-stopped-view,
 *                                     no reconnect, no jump into a new game
 *
 * Same harness as player-check-game-status.test.js: the real player-core and
 * player-game-status run against a mocked global fetch / WebSocket.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

global.WebSocket = { OPEN: 1, CONNECTING: 0, CLOSING: 2, CLOSED: 3 };
global.window = {
    BeatifyUtils: { debug: () => {}, t: (k) => k },
    addEventListener: () => {},
};
Object.defineProperty(global, 'navigator', { value: {}, configurable: true, writable: true });
global.sessionStorage = {
    _d: {},
    getItem(k) { return Object.prototype.hasOwnProperty.call(this._d, k) ? this._d[k] : null; },
    setItem(k, v) { this._d[k] = String(v); },
    removeItem(k) { delete this._d[k]; },
};
global.localStorage = { ...global.sessionStorage, _d: {} };
global.document = {
    readyState: 'loading',
    visibilityState: 'visible',
    cookie: '',
    getElementById: () => null,
    addEventListener: () => {},
    removeEventListener: () => {},
};

function mockNamespace(names, overrides) {
    const ns = {};
    for (const n of names) ns[n] = () => {};
    return { ...ns, ...(overrides || {}) };
}

const showView = vi.fn();
const state = {};

vi.mock('../player-utils.js', () => mockNamespace(
    ['showConfirmModal', 'AnimationQueue', 'AnimationUtils', 'cleanupLeaderboardObserver',
     'setupLeaderboardResizeHandler', 'cleanupVirtualPlayerList', 'setEnergyLevel',
     'triggerConfetti', 'stopConfetti', 'setupLobbyCollapsible',
     'requestWakeLock', 'releaseWakeLock'],
    // The error branch asks this first; GAME_NOT_STARTED is never a join rejection.
    { state, showView, isJoinRejection: () => false },
));
vi.mock('../player-lobby.js', () => mockNamespace(
    ['renderPlayerList', 'renderDifficultyBadge', 'renderLobbyBriefLine', 'renderQRCode', 'setupQRModal',
     'setupInviteModal', 'closeInviteModal', 'updateAdminControls', 'setupAdminControls',
     'showWelcomeBackToast', 'showEarlyRevealToast', 'handleStartFailure']));
vi.mock('../player-game.js', () => mockNamespace(
    ['startCountdown', 'stopCountdown', 'updateGameView', 'handleMetadataUpdate',
     'updateLeaderboard', 'setupLeaderboardToggle', 'resetLeaderboardSummary',
     'initYearSelector', 'handleSubmitAck', 'handleSubmitError', 'resetSubmissionState',
     'handleArtistGuessAck', 'handleMovieGuessAck', 'handleTitleArtistGuessAck',
     'handleStealAck', 'handleStealTargets', 'showAdminControlBar', 'hideAdminControlBar',
     'showReactionBar', 'hideReactionBar', 'setupReactionBar', 'showFloatingReaction',
     'updateControlBarState', 'handleSongStopped', 'handleVolumeChanged', 'handleNextRound',
     'resetNextRoundPending', 'setupAdminControlBar', 'setupRevealControls',
     'resetSongStoppedState', 'showIntroSplashModal',
     'hideIntroSplashModal']));
vi.mock('../player-reveal.js', () => mockNamespace(
    ['updateRevealView', 'setupRevealSheets', 'setupRevealReportBtn', 'setupTitleArtistVoting',
     'stopRevealCountdown', 'startRevealStaging']));
vi.mock('../player-end.js', () => mockNamespace(
    ['updateEndView', 'updatePausedView', 'handleNewGame', 'renderEndPlayerMessage']));
vi.mock('../player-tour.js', () => mockNamespace(
    ['shouldShowTour', 'startTour', 'replayTour', 'forceExit', 'setupTour', 'isActive',
     'updateReadyCount']));
vi.mock('../notify.js', () => mockNamespace(['showToast']));

const { checkGameStatus, recheckGameStatus, handleGameStopped, SLOW_STATUS_HINT_MS } =
    await import('../player-core.js');
const {
    GAME_STATUS_MAX_ATTEMPTS, GAME_STATUS_TIMEOUT_MS, statusFailureView,
    fetchGameStatusResult, STATUS_FAIL_OFFLINE, STATUS_FAIL_SERVER,
} = await import('../player-game-status.js');

const VALID_GAME_ID = 'abcd1234';
const okJson = (body) => ({ ok: true, status: 200, json: async () => body });
const http500 = () => ({ ok: false, status: 500, json: async () => ({}) });
// Every attempt's back-off together: 600 + 1200.
const ALL_BACKOFF_MS = 2000;

function classList(initial) {
    const set = new Set(initial || []);
    return {
        contains: (c) => set.has(c),
        add: (c) => set.add(c),
        remove: (c) => set.delete(c),
        toggle: (c, on) => { if (on) set.add(c); else set.delete(c); },
    };
}

beforeEach(() => {
    vi.useFakeTimers();
    showView.mockReset();
    state.gameId = VALID_GAME_ID;
    state.ws = null;
    state.playerName = null;
    global.document.cookie = '';
    global.document.getElementById = () => null;
    global.sessionStorage._d = {};
});

afterEach(() => {
    vi.clearAllTimers();
    vi.useRealTimers();
});

describe('#3390 offline: the request never reaches Home Assistant', () => {
    it('shows the offline view, never "game not found"', async () => {
        global.fetch = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));

        const p = checkGameStatus();
        await vi.advanceTimersByTimeAsync(ALL_BACKOFF_MS);
        await p;

        expect(global.fetch).toHaveBeenCalledTimes(GAME_STATUS_MAX_ATTEMPTS);
        expect(showView).toHaveBeenLastCalledWith('offline-view');
        expect(showView).not.toHaveBeenCalledWith('not-found-view');
    });

    it('"Try again" goes back to loading and asks again', async () => {
        global.fetch = vi.fn().mockResolvedValue(okJson({ exists: true, can_join: true }));

        await recheckGameStatus();

        expect(showView.mock.calls.map((c) => c[0])).toEqual(['loading-view', 'join-view']);
    });
});

describe('#3390 server error: Home Assistant answers, but with an error', () => {
    it('a 500 on every attempt shows the Home Assistant error view', async () => {
        global.fetch = vi.fn().mockResolvedValue(http500());

        const p = checkGameStatus();
        await vi.advanceTimersByTimeAsync(ALL_BACKOFF_MS);
        await p;

        expect(showView).toHaveBeenLastCalledWith('ha-error-view');
        expect(showView).not.toHaveBeenCalledWith('not-found-view');
    });

    it('a body that is not JSON counts as a server error too', async () => {
        global.fetch = vi.fn().mockResolvedValue({
            ok: true, status: 200, json: async () => { throw new SyntaxError('Unexpected token <'); },
        });

        const res = fetchGameStatusResult(VALID_GAME_ID);
        await vi.advanceTimersByTimeAsync(ALL_BACKOFF_MS);

        expect(await res).toEqual({ ok: false, reason: STATUS_FAIL_SERVER });
    });

    it('the reason of the LAST attempt decides the screen', async () => {
        global.fetch = vi.fn()
            .mockResolvedValueOnce(http500())
            .mockResolvedValueOnce(http500())
            .mockRejectedValueOnce(new TypeError('Failed to fetch'));

        const res = fetchGameStatusResult(VALID_GAME_ID);
        await vi.advanceTimersByTimeAsync(ALL_BACKOFF_MS);

        expect(await res).toEqual({ ok: false, reason: STATUS_FAIL_OFFLINE });
    });

    it('maps each reason to its own view', () => {
        expect(statusFailureView(STATUS_FAIL_OFFLINE)).toBe('offline-view');
        expect(statusFailureView(STATUS_FAIL_SERVER)).toBe('ha-error-view');
    });
});

describe('#3390 no game: the server says it does not exist', () => {
    it('keeps the not-found view for a real {exists:false}', async () => {
        global.fetch = vi.fn().mockResolvedValue(okJson({ exists: false }));

        await checkGameStatus();

        expect(global.fetch).toHaveBeenCalledTimes(1);
        expect(showView).toHaveBeenLastCalledWith('not-found-view');
    });
});

describe('#3390 status timeout: the request hangs', () => {
    it('gives each attempt 10 s, aborts it, then shows the offline view', async () => {
        const signals = [];
        global.fetch = vi.fn((url, init) => {
            signals.push(init && init.signal);
            return new Promise(() => {});  // never answers
        });

        let done = false;
        const p = checkGameStatus().then(() => { done = true; });

        await vi.advanceTimersByTimeAsync(GAME_STATUS_TIMEOUT_MS - 1);
        expect(done).toBe(false);
        expect(showView).not.toHaveBeenCalled();

        await vi.advanceTimersByTimeAsync(GAME_STATUS_TIMEOUT_MS * GAME_STATUS_MAX_ATTEMPTS + ALL_BACKOFF_MS);
        await p;

        expect(global.fetch).toHaveBeenCalledTimes(GAME_STATUS_MAX_ATTEMPTS);
        expect(signals.every((s) => s && s.aborted)).toBe(true);
        expect(showView).toHaveBeenLastCalledWith('offline-view');
    });
});

describe('#3390 slow: a second line after 5 s', () => {
    it('shows the slow hint while waiting and hides it once the answer is in', async () => {
        const hint = { classList: classList(['hidden']) };
        global.document.getElementById = (id) => (id === 'loading-slow-hint' ? hint : null);
        let answer;
        global.fetch = vi.fn(() => new Promise((resolve) => { answer = resolve; }));

        const p = checkGameStatus();
        await vi.advanceTimersByTimeAsync(SLOW_STATUS_HINT_MS - 1);
        expect(hint.classList.contains('hidden')).toBe(true);

        await vi.advanceTimersByTimeAsync(1);
        expect(hint.classList.contains('hidden')).toBe(false);

        answer(okJson({ exists: true, can_join: true }));
        await p;
        expect(hint.classList.contains('hidden')).toBe(true);
        expect(showView).toHaveBeenLastCalledWith('join-view');
    });

    it('a fast answer never shows it', async () => {
        const hint = { classList: classList(['hidden']) };
        global.document.getElementById = (id) => (id === 'loading-slow-hint' ? hint : null);
        global.fetch = vi.fn().mockResolvedValue(okJson({ exists: true, can_join: true }));

        await checkGameStatus();
        await vi.advanceTimersByTimeAsync(SLOW_STATUS_HINT_MS * 2);

        expect(hint.classList.contains('hidden')).toBe(true);
    });
});

describe('#3390 after a Home Assistant restart', () => {
    const realWebSocket = global.WebSocket;
    let sockets;

    class FakeWebSocket {
        constructor(url) {
            this.url = url;
            this.readyState = 0;
            this.sent = [];
            this.closed = false;
            sockets.push(this);
        }
        send(msg) { this.sent.push(JSON.parse(msg)); }
        close() { this.closed = true; this.readyState = 3; }
    }
    FakeWebSocket.CONNECTING = 0;
    FakeWebSocket.OPEN = 1;
    FakeWebSocket.CLOSING = 2;
    FakeWebSocket.CLOSED = 3;

    beforeEach(() => {
        sockets = [];
        global.WebSocket = FakeWebSocket;
        global.window.location = { protocol: 'http:', host: 'ha.local:8123', href: 'http://ha.local:8123/beatify/play?game=' + VALID_GAME_ID };
    });

    afterEach(() => {
        global.WebSocket = realWebSocket;
        delete global.window.location;
    });

    it('GAME_NOT_STARTED on the reconnect shows "This game has ended" instead of a frozen view', async () => {
        global.document.cookie = 'beatify_session=sess-123';
        global.fetch = vi.fn().mockResolvedValue(okJson({ exists: true, phase: 'PLAYING', can_join: true }));

        await checkGameStatus();
        expect(sockets).toHaveLength(1);
        const ws = sockets[0];
        ws.readyState = 1;
        ws.onopen();
        expect(ws.sent).toContainEqual({ type: 'reconnect', session_id: 'sess-123' });

        // The server lost the game in the restart.
        ws.onmessage({ data: JSON.stringify({ type: 'error', code: 'GAME_NOT_STARTED', message: 'No active game' }) });

        expect(showView).toHaveBeenLastCalledWith('game-stopped-view');
        expect(ws.closed).toBe(true);
        // The session belonged to the old game.
        expect(global.document.cookie).not.toContain('sess-123');
    });

    it('does not reconnect or jump into a new game on its own', async () => {
        state.playerName = 'Anna';
        const ws = new FakeWebSocket('ws://x');
        ws.readyState = 1;
        state.ws = ws;
        global.fetch = vi.fn().mockResolvedValue(okJson({ exists: true, phase: 'LOBBY', can_join: true }));

        handleGameStopped();

        expect(showView).toHaveBeenLastCalledWith('game-stopped-view');
        expect(state.playerName).toBeNull();
        expect(state.ws).toBeNull();
        // The onclose that follows the close() is the deliberate kind.
        expect(state.intentionalLeave).toBe(true);

        await vi.advanceTimersByTimeAsync(60000);
        expect(global.fetch).not.toHaveBeenCalled();
        expect(sockets).toHaveLength(1);
        expect(showView).toHaveBeenLastCalledWith('game-stopped-view');
        state.intentionalLeave = false;
    });

    it('"Join again" asks the server and lands where it says', async () => {
        global.fetch = vi.fn().mockResolvedValue(okJson({ exists: false }));

        handleGameStopped();
        await recheckGameStatus();

        expect(showView.mock.calls.map((c) => c[0]))
            .toEqual(['game-stopped-view', 'loading-view', 'not-found-view']);
    });
});
