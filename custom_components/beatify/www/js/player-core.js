/**
 * Beatify Player - Core Module (Entry Point)
 * WebSocket connection, session management, state routing, reconnect logic, view switching
 */

import {
    state, showView, showConfirmModal,
    AnimationQueue, AnimationUtils,
    cleanupLeaderboardObserver, setupLeaderboardResizeHandler,
    cleanupVirtualPlayerList,
    setEnergyLevel, triggerConfetti, stopConfetti,
    initQrCollapsible, setupLobbyCollapsible,
    requestWakeLock, releaseWakeLock
} from './player-utils.js';

import {
    renderPlayerList, renderDifficultyBadge, renderQRCode,
    setupQRModal, setupInviteModal, closeInviteModal,
    updateAdminControls, setupAdminControls,
    showWelcomeBackToast, showEarlyRevealToast
} from './player-lobby.js';

import {
    startCountdown, stopCountdown,
    updateGameView, handleMetadataUpdate,
    updateLeaderboard, setupLeaderboardToggle, resetLeaderboardSummary,
    initYearSelector, handleSubmitAck, handleSubmitError,
    resetSubmissionState,
    handleArtistGuessAck, handleMovieGuessAck, handleTitleArtistGuessAck,
    handleStealAck, handleStealTargets,
    showAdminControlBar, hideAdminControlBar,
    showReactionBar, hideReactionBar, setupReactionBar,
    showFloatingReaction,
    updateControlBarState, handleSongStopped, handleVolumeChanged,
    handleNextRound, resetNextRoundPending, setupAdminControlBar, setupRevealControls,
    setupRevealLeaderboardToggle,
    resetSongStoppedState,
    showIntroSplashModal, hideIntroSplashModal
} from './player-game.js';

import { updateRevealView, setupRevealSheets, setupRevealReportBtn, setupTitleArtistVoting, stopRevealCountdown } from './player-reveal.js';

import { updateEndView, updatePausedView, handleNewGame } from './player-end.js';

// #1706/#1707: coalesce REVEAL/PLAYING re-renders. REVEAL broadcasts fire for
// every reaction/vote/override and PLAYING for every submission; without this a
// single socket frame re-ran the whole render pipeline (full leaderboard
// innerHTML rebuild + album backdrop decode) on every phone. The shared,
// unit-tested coalescer collapses a burst into ONE render per animation frame,
// rendering only the latest payload.
import { createRenderCoalescer } from './admin/util.js';

import {
    shouldShowTour, startTour, replayTour, forceExit as exitTour,
    setupTour, isActive as isTourActive, updateReadyCount
} from './player-tour.js';

// #1663 item 1: non-blocking toast replaces the blocking alert() (host-cannot-leave).
import { showToast } from './notify.js';

// #1664 item 2: retry game-status on transient errors before showing not-found.
import { fetchGameStatusWithRetry } from './player-game-status.js';

var utils = window.BeatifyUtils || {};
var debug = utils.debug || function() {};

// #1706/#1707: one coalesced render per phase. push(data) renders the latest
// payload of a burst on the next animation frame; .cancel() drops a pending
// render so a stale REVEAL frame can't flush into the PLAYING view after a
// phase flip (and vice-versa).
var pushRevealRender = createRenderCoalescer(updateRevealView);
var pushGameRender = createRenderCoalescer(updateGameView);

// ============================================
// Constants
// ============================================

var MAX_RECONNECT_ATTEMPTS = 7;
var MAX_RECONNECT_DELAY_MS = 30000;
var MAX_NAME_LENGTH = 20;
// #1663: how long a guest may sit on "Joining…" before we surface a retry.
// The join WS has no server-side ack timeout, so a dead/slow socket would
// otherwise hang the spinner forever.
var JOIN_TIMEOUT_MS = 10000;
var STORAGE_KEY_NAME = 'beatify_player_name';
var STORAGE_KEY_GAME_ID = 'beatify_game_id';
var STORAGE_KEY_LANGUAGE = 'beatify_language';

// ============================================
// Game ID Validation
// ============================================

/**
 * Validate game ID format
 * @param {string} id - Game ID to validate
 * @returns {boolean} - True if valid format
 */
function isValidGameIdFormat(id) {
    if (!id || typeof id !== 'string') {
        return false;
    }
    return /^[a-zA-Z0-9_-]{8,16}$/.test(id);
}

// ============================================
// Session Cookie Management (Story 11.1)
// ============================================

var SESSION_COOKIE_NAME = 'beatify_session';

function setSessionCookie(sessionId) {
    var secureFlag = location.protocol === 'https:' ? '; Secure' : '';
    document.cookie = SESSION_COOKIE_NAME + '=' + sessionId +
        '; path=/beatify; SameSite=Strict; max-age=86400' + secureFlag;
}

function getSessionCookie() {
    var cookies = document.cookie.split(';');
    for (var i = 0; i < cookies.length; i++) {
        var cookie = cookies[i].trim();
        if (cookie.indexOf(SESSION_COOKIE_NAME + '=') === 0) {
            return cookie.substring(SESSION_COOKIE_NAME.length + 1);
        }
    }
    return null;
}

function clearSessionCookie() {
    document.cookie = SESSION_COOKIE_NAME + '=; path=/beatify; max-age=0';
}

// ============================================
// localStorage Helpers (Story 7-3)
// ============================================

function getStoredPlayerName() {
    try {
        var storedGameId = localStorage.getItem(STORAGE_KEY_GAME_ID);
        var storedName = localStorage.getItem(STORAGE_KEY_NAME);
        debug('[Beatify] Checking localStorage - storedGameId:', storedGameId, 'currentGameId:', state.gameId, 'storedName:', storedName);

        if (storedGameId && storedGameId === state.gameId) {
            debug('[Beatify] Game ID match, returning stored name:', storedName);
            return storedName;
        }

        if (storedGameId && storedGameId !== state.gameId) {
            debug('[Beatify] Different game ID, clearing stored data');
            localStorage.removeItem(STORAGE_KEY_NAME);
            localStorage.removeItem(STORAGE_KEY_GAME_ID);
        }
    } catch (e) {
        console.error('[Beatify] localStorage error:', e);
    }
    return null;
}

function storePlayerName(name) {
    try {
        localStorage.setItem(STORAGE_KEY_NAME, name);
        localStorage.setItem(STORAGE_KEY_GAME_ID, state.gameId);
        debug('[Beatify] Stored player name:', name, 'for game:', state.gameId);
    } catch (e) {
        console.error('[Beatify] Failed to store player name:', e);
    }
}

function clearStoredPlayerName() {
    try {
        localStorage.removeItem(STORAGE_KEY_NAME);
        localStorage.removeItem(STORAGE_KEY_GAME_ID);
    } catch (e) {
        // localStorage unavailable
    }
}

function storeGameLanguage(lang) {
    try {
        localStorage.setItem(STORAGE_KEY_LANGUAGE, lang);
    } catch (e) {
        // localStorage unavailable
    }
}

function getStoredLanguage() {
    try {
        return localStorage.getItem(STORAGE_KEY_LANGUAGE);
    } catch (e) {
        return null;
    }
}

// ============================================
// Reconnection UI (Story 7-3)
// ============================================

function getReconnectDelay() {
    // #1662: unified capped-exponential backoff shared with the spectator
    // dashboard via BeatifyUtils.reconnectBackoffDelay, so the reconnect policy
    // lives in ONE place instead of a bespoke linear ramp here (was #646:
    // 500ms x3 then linear) and an exponential curve on the dashboard.
    // state.reconnectAttempts is 1-based here (it is incremented in the onclose
    // handler BEFORE this is called); the helper never overflows for large
    // attempt counts, so the delay simply saturates at the 30s cap.
    if (utils.reconnectBackoffDelay) {
        return utils.reconnectBackoffDelay(state.reconnectAttempts, { maxDelay: MAX_RECONNECT_DELAY_MS });
    }
    // Fallback if utils failed to load: same capped exponential, 1-based attempt.
    return Math.min(1000 * Math.pow(2, state.reconnectAttempts - 1), MAX_RECONNECT_DELAY_MS);
}

/**
 * Build the shared WebSocket onclose handler (#1662).
 *
 * Both WS setups (connectWithSession / connectWebSocket) previously carried a
 * near-identical onclose block that diverged only in how it rescheduled the
 * reconnect. They now share the single, unit-tested orchestration in
 * BeatifyUtils.createWsCloseHandler; only the reconnect target differs and is
 * passed in as `scheduleReconnect`, so the guard/UI/backoff side effects stay
 * identical across both sockets.
 *
 * @param {Function} scheduleReconnect - performs the actual reconnect call.
 * @returns {Function} a WebSocket onclose handler.
 */
function makeSocketCloseHandler(scheduleReconnect) {
    var deps = {
        state: state,
        maxAttempts: MAX_RECONNECT_ATTEMPTS,
        getDelay: getReconnectDelay,
        scheduleReconnect: scheduleReconnect,
        stopHeartbeat: stopHeartbeat,
        onReconnecting: function(attempt, delay) {
            showReconnectingOverlay();
            updateReconnectStatus(attempt);
            debug('WebSocket closed. Reconnecting in ' + delay + 'ms... (attempt ' + attempt + ')');
        },
        onGiveUp: function() {
            hideReconnectingOverlay();
            showConnectionLostView();
        }
    };
    if (utils.createWsCloseHandler) {
        return utils.createWsCloseHandler(deps);
    }
    // Fallback if utils failed to load: inline the same contract so a missing
    // shared helper degrades to (not diverges from) the canonical behaviour.
    return function() {
        deps.stopHeartbeat();
        if (state.intentionalLeave) {
            state.intentionalLeave = false;
            return;
        }
        if (state.playerName && state.reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
            state.isReconnecting = true;
            state.reconnectAttempts++;
            var delay = getReconnectDelay();
            deps.onReconnecting(state.reconnectAttempts, delay);
            setTimeout(scheduleReconnect, delay);
        } else if (state.reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
            state.isReconnecting = false;
            deps.onGiveUp();
        }
    };
}

function showConnectionIndicator() {
    var el = document.getElementById('connection-indicator');
    if (el) {
        el.classList.remove('connection-indicator--connected');
        el.classList.add('connection-indicator--disconnected');
        el.setAttribute('aria-label', 'Disconnected');
        el.title = 'Disconnected';
    }
}

function hideConnectionIndicator() {
    var el = document.getElementById('connection-indicator');
    if (el) {
        el.classList.remove('connection-indicator--disconnected');
        el.classList.add('connection-indicator--connected');
        el.setAttribute('aria-label', 'Connected');
        el.title = 'Connected';
    }
}

function showReconnectingOverlay() {
    showConnectionIndicator();
    var overlay = document.getElementById('reconnecting-overlay');
    if (overlay) {
        overlay.classList.remove('hidden');
    }
}

function hideReconnectingOverlay() {
    var overlay = document.getElementById('reconnecting-overlay');
    if (overlay) {
        overlay.classList.add('hidden');
    }
}

function updateReconnectStatus(attempt) {
    var statusEl = document.getElementById('reconnect-status');
    if (statusEl) {
        statusEl.textContent = utils.t('join.reconnecting', {attempt: attempt, max: MAX_RECONNECT_ATTEMPTS});
    }
}

function showConnectionLostView() {
    showView('connection-lost-view');
}

// ============================================
// Game Status Check
// ============================================

/**
 * Check game status with the server.
 * Exported for #1664 retry coverage in __tests__/player-check-game-status.test.js.
 */
export async function checkGameStatus() {
    if (!state.gameId) {
        showView('not-found-view');
        return;
    }

    if (!isValidGameIdFormat(state.gameId)) {
        showView('not-found-view');
        return;
    }

    // #1664 item 2: silently retry transport/server errors (network blip, 5xx,
    // JSON-parse failure) a few times BEFORE falling back to not-found. During
    // the retries the current (loading) view stays put — no flash. Returns the
    // parsed data, or null once every attempt has failed.
    var data = await fetchGameStatusWithRetry(state.gameId);

    if (data === null) {
        // Every attempt hit a transport/server error → keep the previous
        // fallback behaviour and show not-found.
        console.error('Failed to check game status after retries');
        showView('not-found-view');
        return;
    }

    // A successful HTTP-200 {exists:false} is a legitimate "game does not exist"
    // answer from the server — show not-found immediately, no retry involved.
    if (!data.exists) {
        showView('not-found-view');
        return;
    }

    if (data.phase === 'END') {
        showView('ended-view');
        return;
    }

    var adminName = sessionStorage.getItem('beatify_admin_name');
    if (adminName) {
        return;
    }

    var sessionCookie = getSessionCookie();
    if (sessionCookie) {
        connectWithSession();
        return;
    }

    if (data.can_join) {
        showView('join-view');
    } else {
        showView('in-progress-view');
    }
}

// ============================================
// Admin Status (Story 3.5)
// ============================================

function checkAdminStatus() {
    var storedAdmin = sessionStorage.getItem('beatify_is_admin');
    var storedName = sessionStorage.getItem('beatify_admin_name');

    if (storedAdmin === 'true' && storedName) {
        state.isAdmin = true;
        state.playerName = storedName;
        sessionStorage.removeItem('beatify_is_admin');
    }
    return state.isAdmin;
}

// ============================================
// WebSocket Client (Story 3.2)
// ============================================

// Connection heartbeat (#967).
// The server pings the client (aiohttp heartbeat), but nothing on the client
// notices server *silence*. On a half-open socket the browser never fires
// onclose, so the player never reconnects and freezes on the last view while
// the game moves on. This client-side heartbeat sends an app-level ping on an
// interval; if no message arrives from the server for HEARTBEAT_TIMEOUT_MS,
// the socket is treated as dead and force-closed to trigger the reconnect
// path — which pulls fresh state and unsticks the player.
var HEARTBEAT_INTERVAL_MS = 15000;
var HEARTBEAT_TIMEOUT_MS = 40000;
var heartbeatTimer = null;

function startHeartbeat() {
    stopHeartbeat();
    state.lastServerActivity = Date.now();
    heartbeatTimer = setInterval(function() {
        if (!state.ws || state.ws.readyState !== WebSocket.OPEN) {
            return;
        }
        if (Date.now() - state.lastServerActivity > HEARTBEAT_TIMEOUT_MS) {
            console.warn('[Beatify] No server activity for '
                + HEARTBEAT_TIMEOUT_MS + 'ms — socket appears dead, forcing reconnect');
            try { state.ws.close(); } catch (e) { /* onclose drives reconnect */ }
            return;
        }
        try {
            state.ws.send(JSON.stringify({ type: 'ping' }));
        } catch (e) { /* next tick detects the dead socket via the timeout */ }
    }, HEARTBEAT_INTERVAL_MS);
}

function stopHeartbeat() {
    if (heartbeatTimer) {
        clearInterval(heartbeatTimer);
        heartbeatTimer = null;
    }
}

/**
 * Connect with session cookie (Story 11.2)
 */
function connectWithSession() {
    var sessionCookie = getSessionCookie();
    if (!sessionCookie) return;

    // Guard: don't open a second WebSocket if one is already connecting/open
    if (state.ws && (state.ws.readyState === WebSocket.CONNECTING || state.ws.readyState === WebSocket.OPEN)) {
        return;
    }

    // #1701: stamp the attempt so the visibilitychange foreground reconnect can
    // throttle bursts instead of hammering the server's per-IP WS rate limit.
    state.lastConnectStartedAt = Date.now();

    // #1700: the INITIAL session reconnect (before any reconnect_ack has set
    // state.playerName) had no failure path. The onclose ladder is gated on
    // state.playerName, so a first WS that fails to open retried nothing and
    // left the player on the loading spinner forever. Arm the join watchdog
    // around this initial connect: any server frame (reconnect_ack / state)
    // clears it via handleServerMessage → clearJoinTimeout, and if the socket
    // stalls the watchdog surfaces a retry instead of an infinite spinner.
    // Reconnects (playerName already known) keep relying on the onclose ladder.
    if (!state.playerName) {
        startJoinTimeout();
    }

    var wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    var wsUrl = wsProtocol + '//' + window.location.host + '/beatify/ws';

    state.ws = new WebSocket(wsUrl);

    state.ws.onopen = function() {
        state.reconnectAttempts = 0;
        state.isReconnecting = false;
        hideReconnectingOverlay();
        hideConnectionIndicator();
        startHeartbeat();

        state.ws.send(JSON.stringify({
            type: 'reconnect',
            session_id: sessionCookie
        }));
    };

    state.ws.onmessage = function(event) {
        try {
            var data = JSON.parse(event.data);
            handleServerMessage(data);
        } catch (e) {
            console.error('Failed to parse WebSocket message:', e);
        }
    };

    // #1662: shared onclose orchestration. This socket prefers the session
    // reconnect while the cookie exists, else falls back to a name-based join.
    state.ws.onclose = makeSocketCloseHandler(function() {
        if (getSessionCookie()) {
            connectWithSession();
        } else {
            connectWebSocket(state.playerName);
        }
    });

    state.ws.onerror = function(err) {
        console.error('WebSocket error:', err);
    };
}

/**
 * Connect to WebSocket and send join message
 * @param {string} name - Player name
 */
function connectWebSocket(name) {
    // Already connected under the same name? No-op, keep the existing socket.
    var wsLive = state.ws && (state.ws.readyState === WebSocket.CONNECTING || state.ws.readyState === WebSocket.OPEN);
    if (wsLive && state.playerName === name) {
        return;
    }

    // Already connected under a DIFFERENT name? Close the old socket cleanly
    // and rejoin. Without this, the guard below silently returns and the
    // server keeps the player under the old identity while the client thinks
    // it changed. Regression guard: this path is hit when the user leaves &
    // rejoins in the same tab, or when an admin handoff reuses a live socket.
    if (wsLive) {
        if (!state.isAdmin) {
            try {
                state.ws.send(JSON.stringify({ type: 'leave' }));
            } catch (e) { /* CONNECTING state — server-side disconnect will clean up */ }
        }
        state.intentionalLeave = true;
        try { state.ws.close(); } catch (e) { /* ignore */ }
        state.ws = null;
        // Session cookie is tied to the old player; drop it so the new join
        // starts a fresh server session under the new name.
        clearSessionCookie();
    }

    state.playerName = name;
    storePlayerName(name);

    // #1701: stamp the attempt for the foreground-reconnect throttle.
    state.lastConnectStartedAt = Date.now();

    var wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    var wsUrl = wsProtocol + '//' + window.location.host + '/beatify/ws';

    state.ws = new WebSocket(wsUrl);

    state.ws.onopen = async function() {
        state.reconnectAttempts = 0;
        state.isReconnecting = false;
        hideReconnectingOverlay();
        hideConnectionIndicator();
        startHeartbeat();

        var joinMsg = { type: 'join', name: name };
        if (state.isAdmin) {
            // #998: claiming the host role on the player page requires a
            // logged-in HA user. ensureAuthenticated() returns the token, or
            // redirects to HA login (this tab navigates away). The server
            // validates ha_token before granting the admin claim.
            joinMsg.is_admin = true;
            joinMsg.ha_token = await BeatifyAuth.ensureAuthenticated();
        }
        state.ws.send(JSON.stringify(joinMsg));
    };

    state.ws.onmessage = function(event) {
        try {
            var data = JSON.parse(event.data);
            handleServerMessage(data);
        } catch (e) {
            console.error('Failed to parse WebSocket message:', e);
        }
    };

    // #1662: shared onclose orchestration. The name-based join reconnects by
    // rejoining under the same name (its original, unchanged behaviour).
    state.ws.onclose = makeSocketCloseHandler(function() {
        connectWebSocket(state.playerName);
    });

    state.ws.onerror = function(err) {
        console.error('WebSocket error:', err);
    };
}

// Set on state so end module can call without circular dep
state.connectWithSession = connectWithSession;
state.connectWebSocket = connectWebSocket;

// ============================================
// Server Message Handler
// ============================================

/**
 * Handle messages from server
 * @param {Object} data - Parsed message data
 */
function handleServerMessage(data) {
    // Heartbeat: any inbound message proves the socket is alive (#967).
    state.lastServerActivity = Date.now();
    if (data.type === 'pong') {
        return;
    }

    // #1663: the server answered, so the initial join isn't hanging — cancel the
    // join watchdog before it can wrongly reset a join that actually succeeded.
    clearJoinTimeout();

    // #1287: cold-start bridge. The admin pressed start; the server fires this
    // the moment it begins connecting the Music Assistant speaker + loading
    // round 1 (~10-15s of otherwise-empty wait). Show the animated vinyl-disc
    // loader; the subsequent PLAYING `state` broadcast replaces it. Only players
    // already past the join screen (i.e. who saw the lobby) should see it — a
    // visitor still on the join form keeps their form.
    if (data.type === 'game_starting') {
        var loadingEl = document.getElementById('loading-view');
        var lobbyEl = document.getElementById('lobby-view');
        var joinEl = document.getElementById('join-view');
        var lobbyActive = lobbyEl && !lobbyEl.classList.contains('hidden');
        var loadingActive = loadingEl && !loadingEl.classList.contains('hidden');
        var joinActive = joinEl && !joinEl.classList.contains('hidden');
        if (lobbyActive || loadingActive || !joinActive) {
            showView('starting-view');
        }
        return;
    }

    var joinBtn = document.getElementById('join-btn');
    var nameInput = document.getElementById('name-input');

    if (data.type === 'state') {
        var players = data.players || [];
        var currentPlayer = players.find(function(p) { return p.name === state.playerName; });
        if (currentPlayer) {
            state.isAdmin = currentPlayer.is_admin === true;
        }

        // Apply language from game state (Story 12.4, 16.3)
        if (data.language) {
            storeGameLanguage(data.language);
            if (typeof BeatifyI18n !== 'undefined' && data.language !== BeatifyI18n.getLanguage()) {
                BeatifyI18n.setLanguage(data.language).then(function() {
                    BeatifyI18n.initPageTranslations();
                    renderPlayerList(players);
                    if (data.difficulty) {
                        renderDifficultyBadge(data.difficulty, data.title_artist_mode);
                    }
                    if (data.phase === 'REVEAL') {
                        pushRevealRender(data);
                    }
                    // Re-apply control bar labels after language load (#300)
                    // updateControlBarState() uses utils.t() which needs i18n ready
                    if (data.phase === 'PLAYING' || data.phase === 'REVEAL') {
                        updateControlBarState(data.phase);
                    }
                });
            }
        }

        // #1009: capture the join URL from any phase, so the in-game
        // "Invite players" button works even when this client never saw
        // the lobby (e.g. the admin joins as a player mid-game).
        if (data.join_url) {
            renderQRCode(data.join_url);
        }

        if (data.phase === 'LOBBY') {
            stopCountdown();
            stopRevealCountdown();
            pushGameRender.cancel();     // #1707: drop any pending coalesced render
            pushRevealRender.cancel();   // #1706
            hideAdminControlBar();
            hideReactionBar();
            state.currentRoundNumber = 0;
            setEnergyLevel('warmup');
            var startBtn = document.getElementById('start-game-btn');
            if (startBtn) {
                startBtn.disabled = false;
                startBtn.innerHTML = '<span class="btn-icon" aria-hidden="true">🎉</span><span data-i18n="lobby.startGame">' + utils.t('lobby.startGame') + '</span>';
            }

            // Cache lobby meta for the ready screen's waiting-count line
            state.lastPlayerCount = players.length;
            state.lastDifficulty = data.difficulty
                ? (utils.t ? utils.t('game.difficulty' + data.difficulty.charAt(0).toUpperCase() + data.difficulty.slice(1)) : data.difficulty)
                : '';

            // Onboarding v2 gate: first-time players land on the tour, not the lobby.
            // Returning players (localStorage flag) and onboarded server-side players
            // fall straight through to lobby-view. Admin always skips the tour.
            if (!isTourActive() && shouldShowTour(currentPlayer)) {
                startTour();
            } else {
                // Show lobby unless the ready screen is mid-hold (brief dwell after tour)
                var readyView = document.getElementById('ready-view');
                var readyVisible = readyView && !readyView.classList.contains('hidden');
                if (!readyVisible && !isTourActive()) {
                    showView('lobby-view');
                }
                // Keep the ready count line fresh while the ready screen is up
                if (readyVisible) {
                    updateReadyCount(players, state.lastDifficulty);
                }
            }

            renderPlayerList(players);
            if (data.difficulty) {
                renderDifficultyBadge(data.difficulty, data.title_artist_mode);
            }
            updateAdminControls(players);
        } else if (data.phase === 'PLAYING') {
            // If game started while player was on tour, dump them into the game.
            if (isTourActive()) {
                exitTour();
            }
            stopConfetti();
            stopRevealCountdown();  // leaving REVEAL for the next round
            requestWakeLock(); // #622: keep screen on during gameplay
            var newRound = data.round || 1;
            if (newRound !== state.currentRoundNumber) {
                state.currentRoundNumber = newRound;
                resetSubmissionState();
            }
            resetNextRoundPending();
            setEnergyLevel('party');
            showView('game-view');
            closeInviteModal();
            pushRevealRender.cancel();   // #1706: leaving REVEAL — drop stale render
            pushGameRender(data);        // #1707: coalesced PLAYING render
            if (data.intro_splash_pending) {
                showIntroSplashModal(state.isAdmin);
            } else {
                hideIntroSplashModal();
            }
            if (data.difficulty) {
                renderDifficultyBadge(data.difficulty, data.title_artist_mode);
            }
            if (data.deadline) {
                // #1662: pass the server's relative seconds_remaining so the
                // countdown anchors to the client's own clock (skew-immune).
                startCountdown(data.deadline, data.seconds_remaining);
            }
            initYearSelector();
            setupLeaderboardToggle();
            showAdminControlBar();
            updateControlBarState('PLAYING');
            hideReactionBar();
        } else if (data.phase === 'REVEAL') {
            stopCountdown();
            if (data.early_reveal) {
                showEarlyRevealToast();
            }
            setEnergyLevel('party');
            showView('reveal-view');
            pushGameRender.cancel();     // #1707: leaving PLAYING — drop stale render
            pushRevealRender(data);      // #1706: coalesced REVEAL render
            setupRevealLeaderboardToggle();
            showAdminControlBar();
            updateControlBarState('REVEAL');
            state.hasReactedThisPhase = false;
            showReactionBar();
        } else if (data.phase === 'PAUSED') {
            stopCountdown();
            stopRevealCountdown();
            pushGameRender.cancel();
            pushRevealRender.cancel();
            hideAdminControlBar();
            hideReactionBar();
            setEnergyLevel('warmup');
            showView('paused-view');
            updatePausedView(data);
        } else if (data.phase === 'END') {
            stopCountdown();
            stopRevealCountdown();
            pushGameRender.cancel();
            pushRevealRender.cancel();
            hideAdminControlBar();
            hideReactionBar();
            releaseWakeLock(); // #622: allow screen to sleep again
            state.currentRoundNumber = 0;
            setEnergyLevel('warmup');
            showView('end-view');
            updateEndView(data);
            clearStoredPlayerName();
        }
    } else if (data.type === 'join_ack') {
        // #646: Request wake lock early — not just during PLAYING
        requestWakeLock();
        if (data.session_id) {
            setSessionCookie(data.session_id);
        }
        try {
            sessionStorage.removeItem('beatify_admin_name');
            sessionStorage.removeItem('beatify_is_admin');
        } catch (e) {
            // Ignore storage errors
        }
    } else if (data.type === 'reconnect_ack') {
        if (data.success && data.name) {
            state.playerName = data.name;
            storePlayerName(data.name);
            showWelcomeBackToast(data.name);
        } else {
            clearSessionCookie();
            clearStoredPlayerName();
            state.playerName = null;
            showView('join-view');
        }
    } else if (data.type === 'submit_ack') {
        handleSubmitAck();
    } else if (data.type === 'metadata_update') {
        handleMetadataUpdate(data.song);
    } else if (data.type === 'error') {
        if (data.code === 'ROUND_EXPIRED' || data.code === 'ALREADY_SUBMITTED') {
            handleSubmitError(data);
            return;
        }
        if (data.code === 'GAME_ENDED') {
            showView('end-view');
            return;
        }
        if (data.code === 'NOT_ADMIN') {
            state.isAdmin = false;
            hideAdminControlBar();
            console.warn('Admin action rejected: not admin');
            return;
        }
        if (data.code === 'SESSION_TAKEOVER') {
            // #1718: NOT a network failure — the player reopened the game on
            // another device/tab. Show dedicated copy (no "check your network"
            // hint, no blind Try-Again that would just race the takeover); the
            // rejoin button starts a fresh join instead.
            state.isReconnecting = false;
            hideReconnectingOverlay();
            state.playerName = null;
            showView('session-takeover-view');
            console.warn('Session taken over by another tab');
            return;
        }
        if (data.code === 'SESSION_NOT_FOUND') {
            // #646: Don't clear session cookie during reconnect — may be transient
            if (state.isReconnecting) {
                console.warn('SESSION_NOT_FOUND during reconnect, will retry with session');
                return;
            }
            clearSessionCookie();
            state.intentionalLeave = true;
            if (state.ws) {
                state.ws.close();
            }
            showView('join-view');
            return;
        }
        if (data.code === 'ADMIN_CANNOT_LEAVE') {
            state.intentionalLeave = false;
            // #1663 item 1: non-blocking toast (was blocking alert()).
            showToast(data.message || 'Host cannot leave. End the game instead.');
            return;
        }
        if (data.code === 'INVALID_ACTION' && data.message === 'No song playing') {
            resetSongStoppedState();
            console.warn('[Beatify] Stop song failed: No song playing');
            return;
        }
        if (data.code === 'INVALID_ACTION') {
            // A benign, late action rejection — e.g. a year/artist/movie
            // guess that landed just after the round flipped PLAYING ->
            // REVEAL. This is NOT a session failure: the catch-all below
            // would wrongly dump the player to the join screen and wipe
            // their stored session. Surface it inline and stay put — the
            // next state broadcast renders the reveal view. (#934)
            console.warn('[Beatify] Action rejected:', data.message);
            handleSubmitError(data);
            return;
        }
        showView('join-view');
        showJoinError(data.message);
        if (joinBtn) {
            joinBtn.disabled = false;
            joinBtn.textContent = utils.t('join.joinButton');
        }
        if (nameInput) {
            nameInput.focus();
        }
        state.playerName = null;
        clearStoredPlayerName();
    } else if (data.type === 'song_stopped') {
        handleSongStopped();
    } else if (data.type === 'volume_changed') {
        handleVolumeChanged(data.level);
    } else if (data.type === 'game_ended') {
        handleGameEnded();
    } else if (data.type === 'rematch_started') {
        debug('[Player] Rematch started - transitioning to lobby');
        AnimationQueue.clear();
        stopConfetti();
        resetLeaderboardSummary();  // #1663: drop the previous game's leader badge
        showView('lobby-view');
        // Reset any rematch button spinner (in case admin triggered this)
        var rematchBtn = document.getElementById('player-rematch-btn');
        if (rematchBtn) { rematchBtn.disabled = false; rematchBtn.textContent = '🔁'; }
        var sessionId = getSessionCookie();
        if (sessionId) {
            if (state.ws && state.ws.readyState === WebSocket.OPEN) {
                // Existing WS still alive — reuse it (avoid creating a second connection)
                state.reconnectAttempts = 0;
                state.ws.send(JSON.stringify({ type: 'reconnect', session_id: sessionId }));
            } else {
                // WS was closed — open a fresh one
                state.reconnectAttempts = 0;
                connectWithSession();
            }
        }
    } else if (data.type === 'left') {
        handleLeftGame();
    } else if (data.type === 'steal_targets') {
        handleStealTargets(data);
    } else if (data.type === 'steal_ack') {
        handleStealAck(data);
    } else if (data.type === 'artist_guess_ack') {
        handleArtistGuessAck(data);
    } else if (data.type === 'movie_guess_ack') {
        handleMovieGuessAck(data);
    } else if (data.type === 'title_artist_guess_ack') {
        handleTitleArtistGuessAck(data);
    } else if (data.type === 'player_reaction') {
        showFloatingReaction(data.player_name, data.emoji);
    }
}

// ============================================
// Game Life Cycle Handlers
// ============================================

function handleLeftGame() {
    clearStoredPlayerName();
    clearSessionCookie();

    state.playerName = null;
    state.isAdmin = false;

    showView('join-view');
}

async function handleLeaveGame() {
    if (!state.ws || state.ws.readyState !== WebSocket.OPEN) {
        return;
    }

    if (state.isAdmin) {
        // #1663 item 1: non-blocking toast (was blocking alert()).
        showToast(utils.t('player.hostCannotLeave'));
        return;
    }

    var confirmed = await showConfirmModal(
        utils.t('player.leaveGameTitle') || 'Leave Game?',
        utils.t('player.leaveGameWarning') || 'Your score will be lost.',
        utils.t('player.leaveGame') || 'Leave',
        utils.t('common.cancel')
    );
    if (!confirmed) {
        return;
    }

    state.intentionalLeave = true;

    state.ws.send(JSON.stringify({ type: 'leave' }));
}

function handleGameEnded() {
    var wasAdmin = state.isAdmin;

    clearStoredPlayerName();
    try {
        sessionStorage.removeItem('beatify_admin_name');
        sessionStorage.removeItem('beatify_is_admin');
    } catch (e) {
        // Ignore storage errors
    }

    cleanupLeaderboardObserver();
    cleanupVirtualPlayerList();

    AnimationQueue.clear();
    stopConfetti();

    state.playerName = null;
    state.isAdmin = false;

    if (state.ws && state.ws.readyState === WebSocket.OPEN) {
        state.ws.close();
    }
    state.ws = null;

    var endView = document.getElementById('end-view');
    if (!endView || !endView.classList.contains('hidden')) {
        return;
    }

    var endMessage = document.getElementById('end-player-message');
    if (endMessage) {
        endMessage.innerHTML =
            '<p>Thanks for playing!</p>' +
            '<p class="rejoin-hint">Scan the QR code again to join the next game.</p>';
        endMessage.classList.remove('hidden');
    }

    showView('end-view');
}

// ============================================
// Join Form
// ============================================

function showJoinError(message) {
    var validationMsg = document.getElementById('name-validation-msg');
    if (validationMsg) {
        validationMsg.textContent = message;
        validationMsg.classList.remove('hidden');
    }
}

function validateName(name) {
    var trimmed = (name || '').trim();
    if (!trimmed) {
        return { valid: false, error: 'Please enter a name' };
    }
    if (trimmed.length > MAX_NAME_LENGTH) {
        return { valid: false, error: 'Name too long (max 20 characters)' };
    }
    return { valid: true, name: trimmed };
}

function handleJoinClick() {
    var nameInput = document.getElementById('name-input');
    var joinBtn = document.getElementById('join-btn');
    var validationMsg = document.getElementById('name-validation-msg');
    if (!nameInput || !joinBtn) return;

    var result = validateName(nameInput.value);
    if (!result.valid) return;

    joinBtn.disabled = true;
    joinBtn.textContent = utils.t('game.joining');

    if (validationMsg) {
        validationMsg.classList.add('hidden');
    }

    connectWebSocket(result.name);
    startJoinTimeout();
}

// #1663: guard the initial guest join. connectWebSocket() opens a WS but the
// join only "succeeds" once the server answers (join_ack / first state frame).
// If the socket stalls, the join button stays a disabled "Joining…" spinner
// forever. Arm a timer on join; clearJoinTimeout() cancels it the moment any
// server message arrives (see handleServerMessage).
function startJoinTimeout() {
    clearJoinTimeout();
    state.joinTimeoutId = setTimeout(handleJoinTimeout, JOIN_TIMEOUT_MS);
}

function clearJoinTimeout() {
    if (state.joinTimeoutId) {
        clearTimeout(state.joinTimeoutId);
        state.joinTimeoutId = null;
    }
}

function handleJoinTimeout() {
    state.joinTimeoutId = null;

    // Tear the stalled socket down so "Try again" starts from a clean slate
    // (and the onclose reconnect ladder doesn't fire behind our back).
    if (state.ws) {
        state.intentionalLeave = true;
        try { state.ws.close(); } catch (e) { /* ignore */ }
        state.ws = null;
    }

    // Re-enable the join form and surface the retry affordance.
    var joinBtn = document.getElementById('join-btn');
    if (joinBtn) {
        joinBtn.disabled = false;
        joinBtn.textContent = utils.t('join.joinButton') || 'Join Game';
    }
    showJoinError(utils.t('errors.joinTimeout') || "Couldn't connect. Please try again.");
    showView('join-view');
}

function setupJoinForm() {
    var nameInput = document.getElementById('name-input');
    var joinBtn = document.getElementById('join-btn');
    var validationMsg = document.getElementById('name-validation-msg');
    if (!nameInput || !joinBtn) return;

    nameInput.addEventListener('input', function() {
        var result = validateName(this.value);
        joinBtn.disabled = !result.valid;
        if (validationMsg) {
            validationMsg.textContent = (!result.valid && this.value) ? result.error : '';
            validationMsg.classList.toggle('hidden', result.valid || !this.value);
        }
    });

    joinBtn.addEventListener('click', handleJoinClick);
    nameInput.addEventListener('keypress', function(e) {
        if (e.key === 'Enter' && !joinBtn.disabled) {
            handleJoinClick();
        }
    });
}

// ============================================
// Retry Connection (Story 7-4)
// ============================================

function setupRetryConnection() {
    var retryBtn = document.getElementById('retry-connection-btn');
    if (retryBtn) {
        retryBtn.addEventListener('click', function() {
            if (state.playerName) {
                state.reconnectAttempts = 0;
                showView('loading-view');
                connectWebSocket(state.playerName);
            } else {
                checkGameStatus();
            }
        });
    }

    // #1718: session-takeover rejoin — this tab lost the session to another
    // device/tab, so drop our (now-orphaned) session cookie and re-run the
    // status check to land on a fresh join, rather than racing the takeover.
    var rejoinBtn = document.getElementById('session-rejoin-btn');
    if (rejoinBtn) {
        rejoinBtn.addEventListener('click', function() {
            clearSessionCookie();
            clearStoredPlayerName();
            state.playerName = null;
            state.reconnectAttempts = 0;
            showView('loading-view');
            checkGameStatus();
        });
    }
}

// ============================================
// Initialization
// ============================================

async function initAll() {
    // #998: consume any pending HA login redirect (?code=). Normal players
    // never authenticate — requireAuth:false means this only exchanges a
    // code if the host claimed the admin role and came back from HA login.
    try { await BeatifyAuth.init({ requireAuth: false }); } catch (e) { /* non-fatal */ }

    var deviceTier = AnimationUtils.getDeviceTier();
    document.body.classList.add('device-tier-' + deviceTier);

    var i18nAvailable = await utils.waitForI18n();
    if (!i18nAvailable) {
        console.error('[Player] BeatifyI18n module failed to load - UI will use fallback text');
    } else {
        var storedLang = getStoredLanguage();
        await BeatifyI18n.init(storedLang);
        BeatifyI18n.initPageTranslations();
    }

    var dashboardHintEl = document.getElementById('dashboard-hint-url');
    if (dashboardHintEl) {
        dashboardHintEl.textContent = window.location.origin + '/beatify/dashboard';
    }

    var playerDashboardUrl = document.getElementById('player-dashboard-url');
    if (playerDashboardUrl) {
        playerDashboardUrl.href = window.location.origin + '/beatify/dashboard';
    }

    setupJoinForm();
    setupTour();
    setupQRModal();
    setupInviteModal();
    setupAdminControls();
    setupRevealSheets();
    setupRevealReportBtn();
    setupTitleArtistVoting();
    setupRevealControls();
    setupAdminControlBar();
    setupRetryConnection();
    setupLeaderboardResizeHandler();
    initQrCollapsible();
    setupLobbyCollapsible();
    setupReactionBar();

    // Admin-handoff: if admin.js redirected us via handleSwitchToPlayerView,
    // the URL carries ?session=<id> (and sessionStorage has the fallback).
    // Prefer reconnect-by-session so the server's player-registry treats us
    // as the same player instead of a fresh join that races ERR_NAME_TAKEN.
    var urlParams = new URLSearchParams(window.location.search);
    var urlSession = urlParams.get('session');
    var stashedSession = null;
    try { stashedSession = sessionStorage.getItem('beatify_session'); } catch (e) { /* private mode */ }
    var handoffSession = urlSession || stashedSession;
    if (handoffSession) {
        setSessionCookie(handoffSession);
        try { sessionStorage.removeItem('beatify_session'); } catch (e) { /* ignore */ }
    }

    if (checkAdminStatus() && state.playerName) {
        // Cookie set above (or already set by admin.js join_ack) — prefer
        // connectWithSession so we reconnect as the same player.
        if (getSessionCookie()) {
            connectWithSession();
        } else {
            connectWebSocket(state.playerName);
        }
        return;
    }

    var storedName = getStoredPlayerName();
    if (storedName && state.gameId) {
        debug('[Beatify] Auto-reconnecting as:', storedName);
        connectWebSocket(storedName);
        return;
    }

    if (storedName) {
        var nameInput = document.getElementById('name-input');
        var joinBtn = document.getElementById('join-btn');
        if (nameInput) {
            nameInput.value = storedName;
            if (joinBtn) {
                var result = validateName(storedName);
                joinBtn.disabled = !result.valid;
            }
        }
    }
}

// Initialize and check game status
checkGameStatus();

// Wire refresh/retry buttons
document.getElementById('refresh-btn')?.addEventListener('click', function() {
    showView('loading-view');
    checkGameStatus();
});

document.getElementById('retry-btn')?.addEventListener('click', function() {
    showView('loading-view');
    checkGameStatus();
});

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initAll);
} else {
    initAll();
}

// ============================================
// Service Worker Registration (Story 18.5)
// ============================================

if ('serviceWorker' in navigator) {
    window.addEventListener('load', function() {
        navigator.serviceWorker.register('/beatify/sw.js', {
            scope: '/beatify/'
        }).then(function(registration) {
            debug('[Beatify] SW registered:', registration.scope);
        }).catch(function(error) {
            console.warn('[Beatify] SW registration failed:', error);
        });
    });
}

// ============================================
// iOS Safari Reconnect on App Foreground
// ============================================
// iOS aggressively closes WebSocket connections when the app is backgrounded.
// When the user returns from another app (e.g. WhatsApp, Safari), we immediately
// reconnect if the socket is dead — without waiting for the onclose backoff timer.
// #1701: minimum gap between two foreground-triggered reconnects. A phone that
// toggles foreground rapidly (or a shared IP behind a proxy/CGNAT) must not open
// a fresh socket on every single foreground — that bursts past the server's
// per-IP WS rate limit (10/60s → 429) and locks the player out while the server
// is healthy.
var FOREGROUND_RECONNECT_MIN_INTERVAL_MS = 3000;

document.addEventListener('visibilitychange', function() {
    if (document.visibilityState === 'visible') {
        // #646: Re-acquire wake lock when tab becomes visible during any active session
        if (state.playerName) {
            requestWakeLock();
        }
        var ws = state.ws;
        if (!ws || ws.readyState === WebSocket.CLOSING || ws.readyState === WebSocket.CLOSED) {
            if (state.playerName) {
                // #1701: throttle rapid foreground reconnects.
                var sinceLast = Date.now() - (state.lastConnectStartedAt || 0);
                if (sinceLast < FOREGROUND_RECONNECT_MIN_INTERVAL_MS) {
                    debug('[Beatify] Foreground reconnect throttled ('
                        + sinceLast + 'ms since last attempt).');
                    return;
                }
                // #1701: do NOT reset the attempt counter on every foreground —
                // that restarted the ladder mid-outage and let a backgrounding
                // phone exhaust the server's per-IP budget by itself. onopen
                // already resets it on a real reconnect; here we only grant a
                // fresh ladder once we've fully exhausted the previous one (the
                // user explicitly returned, so give them one more clean run).
                if (state.reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
                    state.reconnectAttempts = 0;
                }
                debug('[Beatify] Page visible, WebSocket dead — reconnecting.');
                connectWithSession();
            }
        }
    }
});
