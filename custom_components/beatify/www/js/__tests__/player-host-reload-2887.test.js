/**
 * #2887 — reloading the host's player view must not lock the host out.
 *
 * A host who joined as a player keeps ``beatify_admin_name`` in sessionStorage.
 * On reload ``checkGameStatus`` stands down for that case, so the session
 * cookie was never used and ``resolveInitialConnection`` fell through to a
 * name-only ``join``. The server refuses a name-only claim on the host session
 * (#2501, deliberately), and the tab hung on "Connecting…" with a dead Resume
 * button.
 *
 * The fix: the stored-name path prefers the session cookie, and a host who
 * has to rejoin by name sends ``is_admin`` + ``ha_token`` like the handoff.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

// ---- browser-global stubs (must exist before player-core is imported) -------
const constructed = [];
function FakeWebSocket(url) {
    this.url = url;
    this.readyState = 0;
    this.send = vi.fn();
    this.close = vi.fn();
    constructed.push(this);
}
FakeWebSocket.CONNECTING = 0;
FakeWebSocket.OPEN = 1;
FakeWebSocket.CLOSING = 2;
FakeWebSocket.CLOSED = 3;
global.WebSocket = FakeWebSocket;

global.window = {
    BeatifyUtils: { debug: () => {}, t: (k) => k },
    addEventListener: () => {},
    location: { protocol: 'http:', host: 'ha.local', origin: 'http://ha.local', search: '' },
};
Object.defineProperty(global, 'navigator', { value: {}, configurable: true, writable: true });
global.sessionStorage = {
    _d: {},
    getItem(k) { return Object.prototype.hasOwnProperty.call(this._d, k) ? this._d[k] : null; },
    setItem(k, v) { this._d[k] = String(v); },
    removeItem(k) { delete this._d[k]; },
};
global.localStorage = {
    _d: {},
    getItem(k) { return Object.prototype.hasOwnProperty.call(this._d, k) ? this._d[k] : null; },
    setItem(k, v) { this._d[k] = String(v); },
    removeItem(k) { delete this._d[k]; },
};
global.document = {
    readyState: 'loading',       // defer initAll() → never runs under test
    visibilityState: 'visible',
    cookie: '',
    getElementById: () => null,
    addEventListener: () => {},
    removeEventListener: () => {},
};
const ensureAuthenticated = vi.fn().mockResolvedValue('ha-token-xyz');
global.BeatifyAuth = { init: async () => {}, ensureAuthenticated };
global.fetch = vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ exists: true, can_join: true }) });

// ---- sibling-module mocks (same shape as player-check-game-status.test.js) --
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

const { resolveInitialConnection } = await import('../player-core.js');

const GAME_ID = 'abcd1234';

function storeReturningPlayer(name) {
    global.localStorage.setItem('beatify_player_name', name);
    global.localStorage.setItem('beatify_game_id', GAME_ID);
}

/** Open the socket resolveInitialConnection created and return what it sent. */
async function openAndReadFirstMessage(ws) {
    ws.readyState = FakeWebSocket.OPEN;
    await ws.onopen();
    expect(ws.send).toHaveBeenCalledTimes(1);
    return JSON.parse(ws.send.mock.calls[0][0]);
}

beforeEach(() => {
    constructed.length = 0;
    showView.mockClear();
    ensureAuthenticated.mockClear();
    for (const k of Object.keys(state)) delete state[k];
    state.gameId = GAME_ID;
    global.document.cookie = '';
    global.sessionStorage._d = {};
    global.localStorage._d = {};
});

describe('#2887 host reloads the player view', () => {
    it('reconnects by session cookie instead of a name-only join', async () => {
        // The state after a reload: the handoff flag is gone, the host name
        // and the session cookie are both still there, no socket yet.
        global.sessionStorage.setItem('beatify_admin_name', 'QA-Host');
        global.document.cookie = 'beatify_session=host-sess-1';
        storeReturningPlayer('QA-Host');
        state.ws = null;

        await resolveInitialConnection();

        expect(constructed).toHaveLength(1);
        const msg = await openAndReadFirstMessage(constructed[0]);
        expect(msg).toEqual({ type: 'reconnect', session_id: 'host-sess-1' });
    });

    it('rejoins by name with the HA login when no cookie is left', async () => {
        global.sessionStorage.setItem('beatify_admin_name', 'QA-Host');
        storeReturningPlayer('QA-Host');
        state.ws = null;

        await resolveInitialConnection();

        expect(constructed).toHaveLength(1);
        const msg = await openAndReadFirstMessage(constructed[0]);
        expect(msg).toEqual({
            type: 'join', name: 'QA-Host', is_admin: true, ha_token: 'ha-token-xyz',
        });
        expect(ensureAuthenticated).toHaveBeenCalledTimes(1);
    });
});

describe('#2887 guests are unaffected', () => {
    it('a guest without a cookie still joins by name, with no admin claim', async () => {
        storeReturningPlayer('Alice');
        state.ws = null;

        await resolveInitialConnection();

        const msg = await openAndReadFirstMessage(constructed[0]);
        expect(msg).toEqual({ type: 'join', name: 'Alice' });
        expect(ensureAuthenticated).not.toHaveBeenCalled();
    });

    it('a guest whose name differs from the stored host name makes no admin claim', async () => {
        global.sessionStorage.setItem('beatify_admin_name', 'QA-Host');
        storeReturningPlayer('Alice');
        state.ws = null;

        await resolveInitialConnection();

        const msg = await openAndReadFirstMessage(constructed[0]);
        expect(msg).toEqual({ type: 'join', name: 'Alice' });
    });
});
