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
    updateLeaderboard, setupLeaderboardToggle,
    initYearSelector, handleSubmitAck, handleSubmitError,
    resetSubmissionState,
    handleArtistGuessAck, handleMovieGuessAck,
    handleStealAck, handleStealTargets,
    showAdminControlBar, hideAdminControlBar,
    showReactionBar, hideReactionBar, setupReactionBar,
    showFloatingReaction,
    updateControlBarState, handleSongStopped, handleVolumeChanged,
    handleNextRound, resetNextRoundPending, setupAdminControlBar, setupRevealControls,
    setupRevealLeaderboardToggle, setupRoundAnalyticsToggle,
    resetSongStoppedState,
    showIntroSplashModal, hideIntroSplashModal
} from './player-game.js';

import { updateRevealView, setupRevealSheets } from './player-reveal.js';

import { updateEndView, updatePausedView, handleNewGame } from './player-end.js';

import {
    shouldShowTour, startTour, replayTour, forceExit as exitTour,
    setupTour, isActive as isTourActive, updateReadyCount
} from './player-tour.js';

var utils = window.BeatifyUtils || {};

// ============================================
// Constants
// ============================================

var MAX_RECONNECT_ATTEMPTS = 10;
var MAX_RECONNECT_DELAY_MS = 30000;
var MAX_NAME_LENGTH = 20;
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
        console.log('[Beatify] Checking localStorage - storedGameId:', storedGameId, 'currentGameId:', state.gameId, 'storedName:', storedName);

        if (storedGameId && storedGameId === state.gameId) {
            console.log('[Beatify] Game ID match, returning stored name:', storedName);
            return storedName;
        }

        if (storedGameId && storedGameId !== state.gameId) {
            console.log('[Beatify] Different game ID, clearing stored data');
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
        console.log('[Beatify] Stored player name:', name, 'for game:', state.gameId);
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
    // #646: First 3 attempts are fast (500ms), then linear ramp to cap
    if (state.reconnectAttempts <= 3) return 500;
    return Math.min(1000 * (state.reconnectAttempts - 2), MAX_RECONNECT_DELAY_MS);
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
 * Check game status with the server
 */
async function checkGameStatus() {
    if (!state.gameId) {
        showView('not-found-view');
        return;
    }

    if (!isValidGameIdFormat(state.gameId)) {
        showView('not-found-view');
        return;
    }

    try {
        var response = await fetch('/beatify/api/game-status?game=' + encodeURIComponent(state.gameId));
        var data = await response.json();

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

    } catch (err) {
        console.error('Failed to check game status:', err);
        showView('not-found-view');
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

    var wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    var wsUrl = wsProtocol + '//' + window.location.host + '/beatify/ws';

    state.ws = new WebSocket(wsUrl);

    state.ws.onopen = function() {
        state.reconnectAttempts = 0;
        state.isReconnecting = false;
        hideReconnectingOverlay();
        hideConnectionIndicator();

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

    state.ws.onclose = function() {
        if (state.intentionalLeave) {
            state.intentionalLeave = false;
            return;
        }
        if (state.playerName && state.reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
            state.isReconnecting = true;
            state.reconnectAttempts++;
            showReconnectingOverlay();
            updateReconnectStatus(state.reconnectAttempts);

            var delay = getReconnectDelay();
            console.log('WebSocket closed. Reconnecting in ' + delay + 'ms... (attempt ' + state.reconnectAttempts + ')');
            // #646: Keep using session reconnect while cookie exists
            if (getSessionCookie()) {
                setTimeout(connectWithSession, delay);
            } else {
                setTimeout(function() { connectWebSocket(state.playerName); }, delay);
            }
        } else if (state.reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
            state.isReconnecting = false;
            hideReconnectingOverlay();
            showConnectionLostView();
        }
    };

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

    var wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    var wsUrl = wsProtocol + '//' + window.location.host + '/beatify/ws';

    state.ws = new WebSocket(wsUrl);

    state.ws.onopen = function() {
        state.reconnectAttempts = 0;
        state.isReconnecting = false;
        hideReconnectingOverlay();
        hideConnectionIndicator();

        var joinMsg = { type: 'join', name: name };
        if (state.isAdmin) {
            joinMsg.is_admin = true;
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

    state.ws.onclose = function() {
        if (state.intentionalLeave) {
            state.intentionalLeave = false;
            return;
        }
        if (state.playerName && state.reconnectAttempts < MAX_RECONNECT_ATTEMPTS) {
            state.isReconnecting = true;
            state.reconnectAttempts++;
            showReconnectingOverlay();
            updateReconnectStatus(state.reconnectAttempts);

            var delay = getReconnectDelay();
            console.log('WebSocket closed. Reconnecting in ' + delay + 'ms... (attempt ' + state.reconnectAttempts + ')');
            setTimeout(function() { connectWebSocket(state.playerName); }, delay);
        } else if (state.reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
            state.isReconnecting = false;
            hideReconnectingOverlay();
            showConnectionLostView();
        }
    };

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
                        renderDifficultyBadge(data.difficulty);
                    }
                    if (data.phase === 'REVEAL') {
                        updateRevealView(data);
                    }
                    // Re-apply control bar labels after language load (#300)
                    // updateControlBarState() uses utils.t() which needs i18n ready
                    if (data.phase === 'PLAYING' || data.phase === 'REVEAL') {
                        updateControlBarState(data.phase);
                    }
                });
            }
        }

        if (data.phase === 'LOBBY') {
            stopCountdown();
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
                renderDifficultyBadge(data.difficulty);
            }
            if (data.join_url) {
                renderQRCode(data.join_url);
            }
            updateAdminControls(players);
        } else if (data.phase === 'PLAYING') {
            // If game started while player was on tour, dump them into the game.
            if (isTourActive()) {
                exitTour();
            }
            stopConfetti();
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
            updateGameView(data);
            if (data.intro_splash_pending) {
                showIntroSplashModal(state.isAdmin);
            } else {
                hideIntroSplashModal();
            }
            if (data.difficulty) {
                renderDifficultyBadge(data.difficulty);
            }
            if (data.deadline) {
                startCountdown(data.deadline);
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
            updateRevealView(data);
            setupRevealLeaderboardToggle();
            setupRoundAnalyticsToggle();
            showAdminControlBar();
            updateControlBarState('REVEAL');
            state.hasReactedThisPhase = false;
            showReactionBar();
        } else if (data.phase === 'PAUSED') {
            stopCountdown();
            hideAdminControlBar();
            hideReactionBar();
            setEnergyLevel('warmup');
            showView('paused-view');
            updatePausedView(data);
        } else if (data.phase === 'END') {
            stopCountdown();
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
            state.isReconnecting = false;
            hideReconnectingOverlay();
            state.playerName = null;
            showConnectionLostView();
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
            alert(data.message || 'Host cannot leave. End the game instead.');
            return;
        }
        if (data.code === 'INVALID_ACTION' && data.message === 'No song playing') {
            resetSongStoppedState();
            console.warn('[Beatify] Stop song failed: No song playing');
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
        console.log('[Player] Rematch started - transitioning to lobby');
        AnimationQueue.clear();
        stopConfetti();
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
        alert(utils.t('player.hostCannotLeave'));
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
}

// ============================================
// Initialization
// ============================================

async function initAll() {
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
        console.log('[Beatify] Auto-reconnecting as:', storedName);
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
            console.log('[Beatify] SW registered:', registration.scope);
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
document.addEventListener('visibilitychange', function() {
    if (document.visibilityState === 'visible') {
        // #646: Re-acquire wake lock when tab becomes visible during any active session
        if (state.playerName) {
            requestWakeLock();
        }
        var ws = state.ws;
        if (!ws || ws.readyState === WebSocket.CLOSING || ws.readyState === WebSocket.CLOSED) {
            if (state.playerName) {
                console.log('[Beatify] Page visible, WebSocket dead — reconnecting immediately.');
                state.reconnectAttempts = 0; // reset backoff so it reconnects instantly
                connectWithSession();
            }
        }
    }
});
