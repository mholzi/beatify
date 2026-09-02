/**
 * #2508 — a mid-game reload must not race its own two connection paths.
 *
 * A page load starts both: the bootstrap ``checkGameStatus()`` finds the
 * session cookie and opens a socket that sends ``reconnect``, and ``initAll``
 * finds the stored name and calls ``connectWebSocket``. Nothing coordinated
 * them. In the window where the first socket is OPEN but ``reconnect_ack`` has
 * not landed, ``state.playerName`` is still null — so ``connectWebSocket`` saw
 * a live socket under a *different* name, sent ``leave`` (which removes the
 * player server-side), dropped the cookie and joined fresh. Mid-game a fresh
 * join inherits the room average: reload in round five holding 300 points,
 * come back at the bottom of the board.
 *
 * ``resolveInitialConnection`` is now the single owner of that decision. These
 * tests drive it directly, since that is where the race lived.
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

const { resolveInitialConnection } = await import('../player-core.js');

const GAME_ID = 'abcd1234';

/** A returning player: name plus the game it belongs to, as storePlayerName writes it. */
function storeReturningPlayer(name) {
    global.localStorage.setItem('beatify_player_name', name);
    global.localStorage.setItem('beatify_game_id', GAME_ID);
}

/** The socket the session path opened, still waiting for reconnect_ack. */
function sessionSocketAwaitingAck() {
    const ws = new FakeWebSocket('ws://ha.local/beatify/ws');
    ws.readyState = FakeWebSocket.OPEN;
    ws.send.mockClear();
    return ws;
}

beforeEach(() => {
    constructed.length = 0;
    showView.mockClear();
    for (const k of Object.keys(state)) delete state[k];
    state.gameId = GAME_ID;
    global.document.cookie = '';
    global.sessionStorage._d = {};
    global.localStorage._d = {};
});

describe('#2508 the session path owns the connection', () => {
    it('does not send leave while a session reconnect is still unacknowledged', async () => {
        // The exact window: socket OPEN, no reconnect_ack yet, so playerName is
        // still null while a stored name from the previous visit exists.
        global.document.cookie = 'beatify_session=sess-123';
        storeReturningPlayer('Alice');
        const sessionWs = sessionSocketAwaitingAck();
        state.ws = sessionWs;
        state.playerName = null;

        await resolveInitialConnection();

        expect(sessionWs.send).not.toHaveBeenCalled();   // no "leave"
        expect(sessionWs.close).not.toHaveBeenCalled();
        expect(state.ws).toBe(sessionWs);                // same socket, same session
        expect(constructed).toHaveLength(1);             // no second socket
    });

    it('leaves a socket that is still CONNECTING alone too', async () => {
        global.document.cookie = 'beatify_session=sess-123';
        storeReturningPlayer('Alice');
        const sessionWs = sessionSocketAwaitingAck();
        sessionWs.readyState = FakeWebSocket.CONNECTING;
        state.ws = sessionWs;

        await resolveInitialConnection();

        expect(sessionWs.send).not.toHaveBeenCalled();
        expect(state.ws).toBe(sessionWs);
        expect(constructed).toHaveLength(1);
    });

    it('keeps the cookie, so the reconnect in flight can still be acknowledged', async () => {
        global.document.cookie = 'beatify_session=sess-123';
        storeReturningPlayer('Alice');
        state.ws = sessionSocketAwaitingAck();

        await resolveInitialConnection();

        expect(global.document.cookie).toContain('sess-123');
    });
});

describe('#2508 the name path still runs when nobody owns the socket', () => {
    it('auto-reconnects by stored name when no socket is live', async () => {
        storeReturningPlayer('Alice');
        state.ws = null;

        await resolveInitialConnection();

        expect(constructed).toHaveLength(1);
        expect(state.playerName).toBe('Alice');
    });

    it('reconnects by stored name after the session socket has closed', async () => {
        storeReturningPlayer('Alice');
        const dead = new FakeWebSocket('ws://ha.local/beatify/ws');
        dead.readyState = FakeWebSocket.CLOSED;
        constructed.length = 0;
        state.ws = dead;

        await resolveInitialConnection();

        expect(constructed).toHaveLength(1);
        expect(state.playerName).toBe('Alice');
    });

    it('connects nothing when there is no stored name and no socket', async () => {
        state.ws = null;

        await resolveInitialConnection();

        expect(constructed).toHaveLength(0);
    });
});
