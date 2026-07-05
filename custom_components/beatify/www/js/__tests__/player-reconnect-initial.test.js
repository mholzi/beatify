/**
 * #1700 / #1701 — session-reconnect failure path + foreground reconnect throttle.
 *
 * #1700: the INITIAL session reconnect (connectWithSession before any
 * reconnect_ack has set state.playerName) had no failure path — the onclose
 * reconnect ladder is gated on state.playerName, so a first WS that failed to
 * open retried nothing and left the player on the loading spinner forever. The
 * fix arms the join watchdog around the initial connect (any later connect,
 * where playerName is already known, still relies on the ladder).
 *
 * #1701: a backgrounding phone (or a shared IP behind CGNAT) foregrounding
 * repeatedly used to reset the attempt counter to 0 and open a fresh socket on
 * EVERY foreground — bursting past the server's per-IP WS rate limit (10/60s →
 * 429) and locking the player out. The fix throttles rapid foreground
 * reconnects and keeps the attempt counter across foregrounds.
 *
 * These tests import the real player-core entry (siblings mocked) exactly like
 * player-check-game-status.test.js, but with a constructable WebSocket stub and
 * a document that records its event listeners so the visibilitychange handler
 * can be fired directly.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

// ---- constructable WebSocket stub -------------------------------------------
class FakeWS {
    constructor(url) {
        this.url = url;
        this.readyState = FakeWS.CONNECTING;
        FakeWS.instances.push(this);
    }
    send() {}
    close() { this.readyState = FakeWS.CLOSED; }
}
FakeWS.CONNECTING = 0; FakeWS.OPEN = 1; FakeWS.CLOSING = 2; FakeWS.CLOSED = 3;
FakeWS.instances = [];
global.WebSocket = FakeWS;

// ---- browser-global stubs ----------------------------------------------------
const docListeners = {};
global.window = {
    BeatifyUtils: {
        debug: () => {},
        t: (k) => k,
        reconnectBackoffDelay: () => 1000,
        createWsCloseHandler: () => function () {},
    },
    addEventListener: () => {},
    location: { protocol: 'https:', host: 'example.org', search: '' },
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
    readyState: 'loading',       // defer initAll() → never runs under test
    visibilityState: 'visible',
    cookie: '',
    getElementById: () => null,
    addEventListener: (type, fn) => { (docListeners[type] = docListeners[type] || []).push(fn); },
    removeEventListener: () => {},
};

// ---- sibling-module mocks ----------------------------------------------------
function mockNamespace(names, overrides) {
    const ns = {};
    for (const n of names) ns[n] = () => {};
    return { ...ns, ...(overrides || {}) };
}
const state = {};
vi.mock('../player-utils.js', () => mockNamespace(
    ['showConfirmModal', 'AnimationQueue', 'AnimationUtils', 'cleanupLeaderboardObserver',
     'setupLeaderboardResizeHandler', 'cleanupVirtualPlayerList', 'setEnergyLevel',
     'triggerConfetti', 'stopConfetti', 'initQrCollapsible', 'setupLobbyCollapsible',
     'requestWakeLock', 'releaseWakeLock', 'showView'],
    { state }));
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

// Importing player-core wires state.connectWithSession + the visibilitychange
// listener; the top-level checkGameStatus() hits the empty-gameId guard.
await import('../player-core.js');

const FOREGROUND_THROTTLE_MS = 3000;

beforeEach(() => {
    vi.useFakeTimers();
    FakeWS.instances.length = 0;
    global.document.cookie = 'beatify_session=sess-abc';
    global.document.visibilityState = 'visible';
    // reset the shared state between cases
    state.ws = null;
    state.playerName = null;
    state.joinTimeoutId = null;
    state.reconnectAttempts = 0;
    state.lastConnectStartedAt = 0;
    state.isReconnecting = false;
    state.intentionalLeave = false;
});

afterEach(() => {
    vi.clearAllTimers();
    vi.useRealTimers();
});

describe('#1700 initial session reconnect failure path', () => {
    it('arms the join watchdog on the initial connect (no playerName yet)', () => {
        state.playerName = null;
        state.connectWithSession();

        expect(FakeWS.instances.length).toBe(1);          // socket opened
        expect(state.joinTimeoutId).toBeTruthy();          // watchdog armed
        expect(typeof state.lastConnectStartedAt).toBe('number'); // #1701 stamp
        expect(state.lastConnectStartedAt).toBeGreaterThan(0);
    });

    it('does NOT arm the watchdog on a reconnect (playerName already known)', () => {
        state.playerName = 'Alice';
        state.connectWithSession();

        expect(FakeWS.instances.length).toBe(1);
        expect(state.joinTimeoutId).toBeFalsy();           // ladder handles reconnects
    });

    it('no-ops when there is no session cookie', () => {
        global.document.cookie = '';
        state.playerName = null;
        state.connectWithSession();
        expect(FakeWS.instances.length).toBe(0);
        expect(state.joinTimeoutId).toBeFalsy();
    });
});

describe('#1701 foreground reconnect throttle', () => {
    function fireForeground() {
        (docListeners.visibilitychange || []).forEach((fn) => fn());
    }

    it('throttles a foreground reconnect that fires within the min interval', () => {
        state.playerName = 'Alice';
        state.ws = { readyState: FakeWS.CLOSED };
        state.reconnectAttempts = 2;
        state.lastConnectStartedAt = Date.now();   // just connected

        fireForeground();

        expect(FakeWS.instances.length).toBe(0);   // throttled — no new socket
        expect(state.reconnectAttempts).toBe(2);   // counter preserved
    });

    it('reconnects after the min interval WITHOUT resetting the mid-ladder counter', () => {
        state.playerName = 'Alice';
        state.ws = { readyState: FakeWS.CLOSED };
        state.reconnectAttempts = 2;
        state.lastConnectStartedAt = Date.now() - (FOREGROUND_THROTTLE_MS + 1000);

        fireForeground();

        expect(FakeWS.instances.length).toBe(1);   // reconnected
        expect(state.reconnectAttempts).toBe(2);   // NOT reset while under the cap
    });

    it('grants a fresh ladder only once the previous one is exhausted', () => {
        state.playerName = 'Alice';
        state.ws = { readyState: FakeWS.CLOSED };
        state.reconnectAttempts = 7;               // == MAX (exhausted)
        state.lastConnectStartedAt = Date.now() - (FOREGROUND_THROTTLE_MS + 1000);

        fireForeground();

        expect(FakeWS.instances.length).toBe(1);
        expect(state.reconnectAttempts).toBe(0);   // reset for one clean run
    });
});
