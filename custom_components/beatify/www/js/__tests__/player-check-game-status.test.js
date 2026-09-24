/**
 * Retry coverage for checkGameStatus() + fetchGameStatusWithRetry (#1664 item 2).
 *
 * A single failed /beatify/api/game-status fetch (network blip, 5xx, or a
 * JSON-parse error) used to fall straight through to not-found-view, telling a
 * player on a flaky connection that the game does not exist. The fix silently
 * retries TRANSPORT/SERVER errors a few times before that fallback — but a
 * successful HTTP-200 {exists:false} is a legitimate "does not exist" answer
 * and must NOT be retried.
 *
 * These tests import the real player-core entry module (its sibling modules are
 * mocked so it loads in isolation) and the real player-game-status helper (so
 * the retry/back-off runs for real against a mocked global fetch). player-core
 * auto-runs a little bootstrap at import time; document.readyState is stubbed to
 * 'loading' so initAll() is deferred to a DOMContentLoaded that never fires, and
 * the top-level checkGameStatus() call hits the empty-gameId guard (state = {}),
 * so nothing but showView() runs at import.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

// ---- browser-global stubs (must exist before player-core is imported) -------
global.WebSocket = { OPEN: 1, CONNECTING: 0, CLOSING: 2, CLOSED: 3 };
global.window = {
    BeatifyUtils: { debug: () => {}, t: (k) => k },
    addEventListener: () => {},
};
// navigator is a read-only getter in Node; override it. No serviceWorker key →
// the SW-registration block at the bottom of player-core is skipped.
Object.defineProperty(global, 'navigator', { value: {}, configurable: true, writable: true });
global.sessionStorage = {
    _d: {},
    getItem(k) { return Object.prototype.hasOwnProperty.call(this._d, k) ? this._d[k] : null; },
    setItem(k, v) { this._d[k] = String(v); },
    removeItem(k) { delete this._d[k]; },
};
global.localStorage = { ...global.sessionStorage, _d: {} };
global.document = {
    readyState: 'loading',       // defer initAll() → never runs under test
    visibilityState: 'visible',
    cookie: '',                  // getSessionCookie() → null
    getElementById: () => null,  // optional-chained listeners no-op
    addEventListener: () => {},
    removeEventListener: () => {},
};

// ---- sibling-module mocks: player-core imports a lot; only state/showView are
// touched during import + the code paths these tests exercise. Build each mock
// namespace with every imported name present (as a no-op) so the static named
// imports always resolve, then override the couple we assert on. -------------
function mockNamespace(names, overrides) {
    const ns = {};
    for (const n of names) ns[n] = () => {};
    return { ...ns, ...(overrides || {}) };
}

const showView = vi.fn();
const connectWithSessionSpy = vi.fn();
const state = {};

vi.mock('../player-utils.js', () => mockNamespace(
    ['showConfirmModal', 'AnimationQueue', 'AnimationUtils', 'cleanupLeaderboardObserver',
     'setupLeaderboardResizeHandler', 'cleanupVirtualPlayerList', 'setEnergyLevel',
     'triggerConfetti', 'stopConfetti', 'setupLobbyCollapsible',
     'requestWakeLock', 'releaseWakeLock'],
    { state, showView },
));
vi.mock('../player-lobby.js', () => mockNamespace(
    ['renderPlayerList', 'renderDifficultyBadge', 'renderLobbyBriefLine', 'renderQRCode', 'setupQRModal',
     'setupInviteModal', 'closeInviteModal', 'updateAdminControls', 'setupAdminControls',
     'showWelcomeBackToast', 'showEarlyRevealToast']));
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
     'stopRevealCountdown']));
vi.mock('../player-end.js', () => mockNamespace(['updateEndView', 'updatePausedView', 'handleNewGame']));
vi.mock('../player-tour.js', () => mockNamespace(
    ['shouldShowTour', 'startTour', 'replayTour', 'forceExit', 'setupTour', 'isActive',
     'updateReadyCount']));
vi.mock('../notify.js', () => mockNamespace(['showToast']));

// player-game-status.js is intentionally NOT mocked — the real retry/back-off
// runs against the mocked global.fetch below.
const { checkGameStatus } = await import('../player-core.js');
const { GAME_STATUS_MAX_ATTEMPTS } = await import('../player-game-status.js');

const VALID_GAME_ID = 'abcd1234'; // 8 chars → passes isValidGameIdFormat

function okJson(body) {
    return { ok: true, status: 200, json: async () => body };
}

beforeEach(() => {
    vi.useFakeTimers();
    showView.mockClear();
    connectWithSessionSpy.mockClear();
    state.gameId = VALID_GAME_ID;
    global.document.cookie = '';
    global.sessionStorage._d = {};
});

afterEach(() => {
    vi.clearAllTimers();
    vi.useRealTimers();
});

describe('checkGameStatus retry on transient errors (#1664 item 2)', () => {
    it('retries a transient failure, then a later success routes to the correct view', async () => {
        global.fetch = vi.fn()
            .mockRejectedValueOnce(new Error('network blip'))
            .mockResolvedValueOnce(okJson({ exists: true, can_join: true }));

        const p = checkGameStatus();
        await vi.advanceTimersByTimeAsync(600); // flush the single back-off
        await p;

        expect(global.fetch).toHaveBeenCalledTimes(2);
        expect(showView).toHaveBeenCalledWith('join-view');
        // No premature not-found flash while retrying.
        expect(showView).not.toHaveBeenCalledWith('not-found-view');
    });

    it('gives up after MAX_ATTEMPTS transient failures and shows not-found', async () => {
        global.fetch = vi.fn().mockRejectedValue(new Error('server down'));

        const p = checkGameStatus();
        // back-off after attempts 1 and 2 (none after the final attempt): 600 + 1200.
        await vi.advanceTimersByTimeAsync(2000);
        await p;

        expect(global.fetch).toHaveBeenCalledTimes(GAME_STATUS_MAX_ATTEMPTS);
        expect(showView).toHaveBeenLastCalledWith('not-found-view');
    });

    it('treats HTTP-200 {exists:false} as a valid negative answer — not-found immediately, no retry', async () => {
        global.fetch = vi.fn().mockResolvedValue(okJson({ exists: false }));

        await checkGameStatus();

        expect(global.fetch).toHaveBeenCalledTimes(1); // exactly one call, no retry
        expect(showView).toHaveBeenCalledWith('not-found-view');
    });

    it('retries an HTTP 5xx (response not ok), then succeeds', async () => {
        global.fetch = vi.fn()
            .mockResolvedValueOnce({ ok: false, status: 503, json: async () => ({}) })
            .mockResolvedValueOnce(okJson({ exists: true, can_join: false }));

        const p = checkGameStatus();
        await vi.advanceTimersByTimeAsync(600);
        await p;

        expect(global.fetch).toHaveBeenCalledTimes(2);
        expect(showView).toHaveBeenCalledWith('in-progress-view');
    });
});

// ---------------------------------------------------------------------------
// #2947 — a reload on the podium (END phase)
// ---------------------------------------------------------------------------

const { ENDED_VIEW_POLL_MS } = await import('../player-core.js');

describe('checkGameStatus in the END phase (#2947)', () => {
    const realWebSocket = global.WebSocket;
    let sockets;

    class FakeWebSocket {
        constructor(url) {
            this.url = url;
            this.readyState = 0;
            this.sent = [];
            sockets.push(this);
        }
        send(msg) { this.sent.push(JSON.parse(msg)); }
        close() {}
    }
    FakeWebSocket.CONNECTING = 0;
    FakeWebSocket.OPEN = 1;
    FakeWebSocket.CLOSING = 2;
    FakeWebSocket.CLOSED = 3;

    let endedView;

    beforeEach(() => {
        sockets = [];
        global.WebSocket = FakeWebSocket;
        global.window.location = { protocol: 'http:', host: 'ha.local:8123', href: 'http://ha.local:8123/beatify/play?game=' + VALID_GAME_ID };
        state.ws = null;
        state.playerName = null;
        // ended-view is visible until showView() moves away from it.
        const classes = new Set();
        endedView = { classList: {
            contains: (c) => classes.has(c),
            add: (c) => classes.add(c),
            remove: (c) => classes.delete(c),
        } };
        global.document.getElementById = (id) => (id === 'ended-view' ? endedView : null);
        showView.mockImplementation((id) => {
            if (id === 'ended-view') endedView.classList.remove('hidden');
            else endedView.classList.add('hidden');
        });
    });

    afterEach(() => {
        global.WebSocket = realWebSocket;
        delete global.window.location;
        global.document.getElementById = () => null;
        showView.mockReset();
    });

    it('reconnects with the session cookie instead of dead-ending on ended-view', async () => {
        global.document.cookie = 'beatify_session=sess-123';
        global.fetch = vi.fn().mockResolvedValue(okJson({ exists: true, phase: 'END', can_join: false }));

        await checkGameStatus();

        expect(showView).not.toHaveBeenCalledWith('ended-view');
        expect(sockets).toHaveLength(1);
        expect(sockets[0].url).toBe('ws://ha.local:8123/beatify/ws');

        sockets[0].readyState = 1;
        sockets[0].onopen();
        expect(sockets[0].sent).toContainEqual({ type: 'reconnect', session_id: 'sess-123' });

        // No status polling on the session path — the socket carries the rematch.
        await vi.advanceTimersByTimeAsync(ENDED_VIEW_POLL_MS * 3);
        expect(global.fetch).toHaveBeenCalledTimes(1);
    });

    it('without a cookie shows ended-view, polls, and opens the join form once the rematch lobby is up', async () => {
        global.fetch = vi.fn()
            .mockResolvedValueOnce(okJson({ exists: true, phase: 'END', can_join: false }))
            .mockResolvedValueOnce(okJson({ exists: true, phase: 'END', can_join: false }))
            // The rematch minted a new game id; the server names it.
            .mockResolvedValueOnce(okJson({ exists: true, phase: 'LOBBY', can_join: true, game_id: 'newgame9' }));

        await checkGameStatus();

        expect(showView).toHaveBeenLastCalledWith('ended-view');
        expect(sockets).toHaveLength(0);

        await vi.advanceTimersByTimeAsync(ENDED_VIEW_POLL_MS);
        expect(global.fetch).toHaveBeenCalledTimes(2);
        expect(showView).toHaveBeenLastCalledWith('ended-view');

        await vi.advanceTimersByTimeAsync(ENDED_VIEW_POLL_MS);
        expect(global.fetch).toHaveBeenCalledTimes(3);
        expect(global.fetch.mock.calls[2][0]).toContain('game=' + VALID_GAME_ID);
        expect(showView).toHaveBeenLastCalledWith('join-view');
        expect(state.gameId).toBe('newgame9');

        // Left the view → the poll stops.
        await vi.advanceTimersByTimeAsync(ENDED_VIEW_POLL_MS * 3);
        expect(global.fetch).toHaveBeenCalledTimes(3);
    });

    it('stops polling as soon as the guest is no longer on ended-view', async () => {
        global.fetch = vi.fn().mockResolvedValue(okJson({ exists: true, phase: 'END', can_join: false }));

        await checkGameStatus();
        expect(showView).toHaveBeenLastCalledWith('ended-view');

        showView('some-other-view');
        await vi.advanceTimersByTimeAsync(ENDED_VIEW_POLL_MS * 3);

        expect(global.fetch).toHaveBeenCalledTimes(1);
    });

    it('a stale link that the server redirects to the rematch lands on the join form', async () => {
        global.fetch = vi.fn().mockResolvedValue(
            okJson({ exists: true, phase: 'LOBBY', can_join: true, game_id: 'newgame9' }));

        await checkGameStatus();

        expect(state.gameId).toBe('newgame9');
        expect(showView).toHaveBeenLastCalledWith('join-view');
    });
});
