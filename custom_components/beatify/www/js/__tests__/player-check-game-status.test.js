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
     'triggerConfetti', 'stopConfetti', 'initQrCollapsible', 'setupLobbyCollapsible',
     'requestWakeLock', 'releaseWakeLock'],
    { state, showView },
));
vi.mock('../player-lobby.js', () => mockNamespace(
    ['renderPlayerList', 'renderDifficultyBadge', 'renderQRCode', 'setupQRModal',
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
     'setupRevealLeaderboardToggle', 'resetSongStoppedState', 'showIntroSplashModal',
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
