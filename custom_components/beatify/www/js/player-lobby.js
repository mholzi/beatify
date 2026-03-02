/**
 * Beatify Player - Lobby Module
 * Lobby view rendering, QR code, player list, join flow UI
 */

import {
    state, escapeHtml, virtualPlayerList,
    initVirtualPlayerList, setVirtualPlayerListItems
} from './player-utils.js';

var utils = window.BeatifyUtils || {};

// ============================================
// Player List Rendering (Story 3.3)
// ============================================

var previousPlayers = [];

/**
 * Render player list in lobby (Story 18.2: Virtual scrolling for 15+ players)
 * @param {Array} players - Array of player objects
 */
export function renderPlayerList(players) {
    var listEl = document.getElementById('player-list');
    var countEl = document.getElementById('player-count');
    var countBadgeEl = document.getElementById('player-count-badge');
    var playersSummaryEl = document.getElementById('players-summary');
    var playersEmptyEl = document.getElementById('players-empty');
    if (!listEl) return;
    if (!players || !Array.isArray(players)) {
        players = [];
    }

    var count = players.length;

    if (countEl) {
        countEl.textContent = count === 1
            ? utils.t('lobby.playerJoined')
            : utils.t('lobby.playersJoined', { count: count });
    }

    if (countBadgeEl) {
        countBadgeEl.textContent = count;
    }

    if (playersSummaryEl) {
        playersSummaryEl.textContent = count;
    }

    if (playersEmptyEl) {
        playersEmptyEl.classList.toggle('hidden', count > 0);
    }

    var sortedPlayers = players.slice().sort(function(a, b) {
        if (a.connected !== b.connected) {
            return a.connected ? -1 : 1;
        }
        return 0;
    });

    var previousNames = previousPlayers.map(function(p) { return p.name; });
    var newNames = sortedPlayers
        .filter(function(p) { return previousNames.indexOf(p.name) === -1; })
        .map(function(p) { return p.name; });

    if (!virtualPlayerList.container) {
        initVirtualPlayerList(listEl);
    }

    var renderPlayerCard = function(player) {
        var isNew = newNames.indexOf(player.name) !== -1;
        var isYou = player.name === state.playerName;
        var isDisconnected = player.connected === false;
        var classes = [
            'player-card',
            isNew ? 'is-new' : '',
            isYou ? 'player-card--you' : '',
            isDisconnected ? 'player-card--disconnected' : ''
        ].filter(Boolean).join(' ');

        var awayBadge = isDisconnected ? '<span class="away-badge">(away)</span>' : '';

        return '<div class="' + classes + '" data-player="' + escapeHtml(player.name) + '">' +
            '<span class="player-name">' +
                escapeHtml(player.name) +
                (isYou ? '<span class="you-badge">' + utils.t('leaderboard.you') + '</span>' : '') +
                awayBadge +
            '</span>' +
        '</div>';
    };

    setVirtualPlayerListItems(sortedPlayers, renderPlayerCard);

    setTimeout(function() {
        var container = virtualPlayerList.isVirtual ? virtualPlayerList.contentWrapper : listEl;
        if (!container) return;
        var newCards = container.querySelectorAll('.is-new');
        for (var i = 0; i < newCards.length; i++) {
            newCards[i].classList.remove('is-new');
        }
    }, 2000);

    previousPlayers = players.slice();
}

// ============================================
// Difficulty Badge (Story 14.1)
// ============================================

/**
 * Render difficulty badge in lobby and game views
 * @param {string} difficulty - Difficulty level ('easy', 'normal', or 'hard')
 */
export function renderDifficultyBadge(difficulty) {
    var labelKey = {
        easy: 'game.difficultyEasy',
        normal: 'game.difficultyNormal',
        hard: 'game.difficultyHard'
    }[difficulty] || 'game.difficultyNormal';

    var label = utils.t(labelKey);

    var lobbyBadge = document.getElementById('lobby-difficulty-badge');
    var gameBadge = document.getElementById('game-difficulty-badge');

    if (lobbyBadge) {
        lobbyBadge.textContent = label;
        lobbyBadge.className = 'difficulty-badge difficulty-badge--' + (difficulty || 'normal');
    }

    if (gameBadge) {
        gameBadge.textContent = label;
        gameBadge.className = 'difficulty-badge difficulty-badge--' + (difficulty || 'normal');
    }
}

// ============================================
// QR Code Sharing (Story 3.4)
// ============================================

var currentJoinUrl = null;

/**
 * Render QR code for sharing
 * @param {string} joinUrl - URL to encode in QR
 */
export function renderQRCode(joinUrl) {
    if (!joinUrl) return;
    currentJoinUrl = joinUrl;

    var container = document.getElementById('player-qr-code');
    if (!container) return;

    container.innerHTML = '';

    if (typeof QRCode !== 'undefined') {
        new QRCode(container, {
            text: joinUrl,
            width: 128,
            height: 128,
            colorDark: '#000000',
            colorLight: '#ffffff',
            correctLevel: QRCode.CorrectLevel.M
        });
    } else {
        container.innerHTML = '<p class="status-error">QR code library not loaded</p>';
    }

    container.onclick = openQRModal;
    container.onkeydown = function(e) {
        if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            openQRModal();
        }
    };
}

function openQRModal() {
    if (!currentJoinUrl) return;

    var modal = document.getElementById('qr-modal');
    var modalCode = document.getElementById('qr-modal-code');
    if (!modal || !modalCode) return;

    modalCode.innerHTML = '';

    if (typeof QRCode !== 'undefined') {
        new QRCode(modalCode, {
            text: currentJoinUrl,
            width: 256,
            height: 256,
            colorDark: '#000000',
            colorLight: '#ffffff',
            correctLevel: QRCode.CorrectLevel.M
        });
    } else {
        modalCode.innerHTML = '<p class="status-error">QR code library not loaded</p>';
    }

    modal.classList.remove('hidden');
    document.body.style.overflow = 'hidden';

    var closeBtn = document.getElementById('qr-modal-close');
    if (closeBtn) closeBtn.focus();
}

function closeQRModal() {
    var modal = document.getElementById('qr-modal');
    if (modal) {
        modal.classList.add('hidden');
        document.body.style.overflow = '';
    }
}

/**
 * Setup QR modal event handlers
 */
export function setupQRModal() {
    var modal = document.getElementById('qr-modal');
    var backdrop = modal ? modal.querySelector('.qr-modal-backdrop') : null;
    var closeBtn = document.getElementById('qr-modal-close');

    if (backdrop) {
        backdrop.addEventListener('click', closeQRModal);
    }
    if (closeBtn) {
        closeBtn.addEventListener('click', closeQRModal);
    }

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && modal && !modal.classList.contains('hidden')) {
            closeQRModal();
        }
    });
}

// ============================================
// Invite Modal (Story 16.5)
// ============================================

export function openInviteModal() {
    if (!currentJoinUrl) return;

    var modal = document.getElementById('invite-modal');
    var modalCode = document.getElementById('invite-modal-code');
    var urlInput = document.getElementById('invite-modal-url');
    if (!modal || !modalCode) return;

    modalCode.innerHTML = '';

    if (typeof QRCode !== 'undefined') {
        new QRCode(modalCode, {
            text: currentJoinUrl,
            width: 256,
            height: 256,
            colorDark: '#000000',
            colorLight: '#ffffff',
            correctLevel: QRCode.CorrectLevel.M
        });
    } else {
        modalCode.innerHTML = '<p class="status-error">QR code library not loaded</p>';
    }

    if (urlInput) {
        urlInput.value = currentJoinUrl;
    }

    modal.classList.remove('hidden');
    document.body.style.overflow = 'hidden';

    var closeBtn = document.getElementById('invite-modal-close');
    if (closeBtn) closeBtn.focus();
}

export function closeInviteModal() {
    var modal = document.getElementById('invite-modal');
    if (modal) {
        modal.classList.add('hidden');
        document.body.style.overflow = '';
    }
    var feedback = document.getElementById('invite-copy-feedback');
    if (feedback) feedback.classList.add('hidden');
}

function copyJoinUrl() {
    var urlInput = document.getElementById('invite-modal-url');
    var feedback = document.getElementById('invite-copy-feedback');
    if (!urlInput || !currentJoinUrl) return;

    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(currentJoinUrl).then(function() {
            showCopyFeedback(feedback);
        }).catch(function() {
            fallbackCopy(urlInput, feedback);
        });
    } else {
        fallbackCopy(urlInput, feedback);
    }
}

function fallbackCopy(urlInput, feedback) {
    urlInput.select();
    urlInput.setSelectionRange(0, 99999);
    try {
        document.execCommand('copy');
        showCopyFeedback(feedback);
    } catch (e) {
        console.warn('[Beatify] Copy failed:', e);
    }
}

function showCopyFeedback(feedback) {
    if (!feedback) return;
    feedback.classList.remove('hidden');
    setTimeout(function() {
        feedback.classList.add('hidden');
    }, 2000);
}

/**
 * Setup invite modal event handlers
 */
export function setupInviteModal() {
    var modal = document.getElementById('invite-modal');
    var backdrop = modal ? modal.querySelector('.invite-modal-backdrop') : null;
    var closeBtn = document.getElementById('invite-modal-close');
    var inviteBtn = document.getElementById('invite-players-btn');
    var copyBtn = document.getElementById('invite-copy-btn');

    if (backdrop) {
        backdrop.addEventListener('click', closeInviteModal);
    }
    if (closeBtn) {
        closeBtn.addEventListener('click', closeInviteModal);
    }
    if (inviteBtn) {
        inviteBtn.addEventListener('click', openInviteModal);
    }
    if (copyBtn) {
        copyBtn.addEventListener('click', copyJoinUrl);
    }

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape' && modal && !modal.classList.contains('hidden')) {
            closeInviteModal();
        }
    });
}

// ============================================
// Admin Controls (Story 3.5)
// ============================================

/**
 * Update admin controls visibility based on player state
 * @param {Array} players - Players from state
 */
export function updateAdminControls(players) {
    var adminControls = document.getElementById('admin-controls');
    var lobbyStatus = document.getElementById('lobby-status');
    if (!adminControls) return;
    if (!players || !Array.isArray(players)) {
        players = [];
    }

    var currentPlayer = players.find(function(p) { return p.name === state.playerName; });
    var playerIsAdmin = currentPlayer?.is_admin === true;

    if (playerIsAdmin) {
        adminControls.classList.remove('hidden');
        if (lobbyStatus) lobbyStatus.classList.add('hidden');
    } else {
        adminControls.classList.add('hidden');
        if (lobbyStatus) lobbyStatus.classList.remove('hidden');
    }
}

/**
 * Setup admin control event handlers
 */
export function setupAdminControls() {
    var startBtn = document.getElementById('start-game-btn');

    startBtn?.addEventListener('click', function() {
        if (!state.ws || state.ws.readyState !== WebSocket.OPEN) return;

        startBtn.disabled = true;
        startBtn.textContent = utils.t('game.starting');

        state.ws.send(JSON.stringify({
            type: 'admin',
            action: 'start_game'
        }));
    });
}

// ============================================
// Toast Notifications
// ============================================

/**
 * Show welcome back toast (Story 11.2)
 * @param {string} name - Player name
 */
export function showWelcomeBackToast(name) {
    var indicator = document.getElementById('volume-indicator');
    if (indicator) {
        indicator.textContent = utils.t('player.welcomeBack', {name: name});
        indicator.classList.remove('hidden');
        indicator.classList.add('is-visible');
        setTimeout(function() {
            indicator.classList.remove('is-visible');
            setTimeout(function() {
                indicator.classList.add('hidden');
            }, 300);
        }, 2000);
    }
}

/**
 * Show early reveal toast (Story 20.9)
 */
export function showEarlyRevealToast() {
    var indicator = document.getElementById('volume-indicator');
    if (indicator) {
        indicator.textContent = utils.t('earlyReveal.message') || 'All guesses in!';
        indicator.classList.remove('hidden');
        indicator.classList.add('is-visible');
        setTimeout(function() {
            indicator.classList.remove('is-visible');
            setTimeout(function() {
                indicator.classList.add('hidden');
            }, 300);
        }, 1500);
    }
}
