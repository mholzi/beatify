/**
 * #3093 - an intro-splash modal must not outlive the PLAYING phase.
 *
 * A phone that opened the "Intro Round! Waiting for host..." modal kept it
 * (backdrop, aria-modal, focus trap) on top of the reveal when the host
 * skipped the round, because hideIntroSplashModal() had a single call site in
 * the PLAYING branch. REVEAL, PAUSED and END must close it too.
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
const showIntroSplashModal = vi.fn();
const hideIntroSplashModal = vi.fn();
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
     'resetSongStoppedState'],
    { showIntroSplashModal, hideIntroSplashModal }));
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

async function connect() {
    state.ws = null;
    await resolveInitialConnection();
    const ws = constructed[0];
    ws.readyState = FakeWebSocket.OPEN;
    return (frame) => ws.onmessage({ data: JSON.stringify(frame) });
}

beforeEach(() => {
    constructed.length = 0;
    showView.mockClear();
    showIntroSplashModal.mockClear();
    hideIntroSplashModal.mockClear();
    for (const k of Object.keys(state)) delete state[k];
    state.gameId = GAME_ID;
    global.document.cookie = 'beatify_session=sess-1';
    global.sessionStorage._d = {};
    global.localStorage._d = {};
    global.localStorage.setItem('beatify_player_name', 'Alice');
    global.localStorage.setItem('beatify_game_id', GAME_ID);
});

describe('#3093 intro splash modal is closed when PLAYING is left', () => {
    for (const phase of ['REVEAL', 'PAUSED', 'END']) {
        it(`a ${phase} frame closes the modal a PLAYING frame opened`, async () => {
            const send = await connect();

            send({ type: 'state', phase: 'PLAYING', round: 3, intro_splash_pending: true, players: [] });
            expect(showIntroSplashModal).toHaveBeenCalledTimes(1);
            expect(hideIntroSplashModal).not.toHaveBeenCalled();

            send({ type: 'state', phase, round: 3, intro_splash_pending: false, players: [] });
            expect(hideIntroSplashModal).toHaveBeenCalledTimes(1);
        });
    }

    it('a PLAYING frame without the flag still closes it (resume path unchanged)', async () => {
        const send = await connect();
        send({ type: 'state', phase: 'PLAYING', round: 3, intro_splash_pending: false, players: [] });
        expect(showIntroSplashModal).not.toHaveBeenCalled();
        expect(hideIntroSplashModal).toHaveBeenCalledTimes(1);
    });
});
