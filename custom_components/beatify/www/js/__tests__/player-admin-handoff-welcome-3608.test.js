/**
 * #3608 - "Welcome back" is for a returning player, not for the host's first
 * arrival on the player page.
 *
 * admin.js joins the host as a player and hands the session cookie to the
 * player page, which reconnects with it (resolveInitialConnection). The server
 * answers that with reconnect_ack, and the handler used to greet every
 * reconnect_ack with "Welcome back, <name>!" - so a host who had joined seconds
 * earlier was welcomed back. A genuine reload keeps the toast.
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
const { showWelcomeBackToast } = vi.hoisted(() => ({ showWelcomeBackToast: vi.fn() }));
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
     'showEarlyRevealToast'],
    { showWelcomeBackToast }));
vi.mock('../player-game.js', () => mockNamespace(
    ['startCountdown', 'stopCountdown', 'updateGameView', 'handleMetadataUpdate',
     'updateLeaderboard', 'setupLeaderboardToggle', 'resetLeaderboardSummary',
     'initYearSelector', 'handleSubmitAck', 'handleSubmitError', 'resetSubmissionState', 'cancelPendingPowerup',
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

async function reconnectAndAck(ws, name) {
    ws.readyState = FakeWebSocket.OPEN;
    await ws.onopen();
    ws.onmessage({ data: JSON.stringify({ type: 'reconnect_ack', name, success: true }) });
}

beforeEach(() => {
    constructed.length = 0;
    showWelcomeBackToast.mockClear();
    for (const k of Object.keys(state)) delete state[k];
    state.gameId = GAME_ID;
    global.document.cookie = '';
    global.sessionStorage._d = {};
    global.localStorage._d = {};
});

describe('#3608 welcome-back toast', () => {
    it('is not shown on the host handoff from the admin page', async () => {
        global.sessionStorage.setItem('beatify_admin_name', 'QA-Admin');
        global.sessionStorage.setItem('beatify_is_admin', 'true');
        global.document.cookie = 'beatify_session=host-sess-1';
        state.ws = null;

        await resolveInitialConnection();
        await reconnectAndAck(constructed[0], 'QA-Admin');

        expect(showWelcomeBackToast).not.toHaveBeenCalled();
        expect(state.playerName).toBe('QA-Admin');
    });

    it('is shown when the host later reloads the player page', async () => {
        // After the handoff the is_admin flag is consumed; only the name stays.
        global.sessionStorage.setItem('beatify_admin_name', 'QA-Admin');
        global.document.cookie = 'beatify_session=host-sess-1';
        global.localStorage.setItem('beatify_player_name', 'QA-Admin');
        global.localStorage.setItem('beatify_game_id', GAME_ID);
        state.ws = null;

        await resolveInitialConnection();
        await reconnectAndAck(constructed[0], 'QA-Admin');

        expect(showWelcomeBackToast).toHaveBeenCalledWith('QA-Admin');
    });

    it('is shown to a returning guest', async () => {
        global.document.cookie = 'beatify_session=guest-sess-1';
        global.localStorage.setItem('beatify_player_name', 'Alice');
        global.localStorage.setItem('beatify_game_id', GAME_ID);
        state.ws = null;

        await resolveInitialConnection();
        await reconnectAndAck(constructed[0], 'Alice');

        expect(showWelcomeBackToast).toHaveBeenCalledWith('Alice');
    });
});
