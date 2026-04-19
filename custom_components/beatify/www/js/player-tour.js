/**
 * Beatify Player — Tour Module (Player onboarding v2)
 *
 * Four-card swipeable tour that teaches the core mechanics (year, bet, steal,
 * artist) before the host starts the game. See DESIGN.md §
 * "Player onboarding — post-QR education" for the full spec.
 *
 * State machine: JOINING → LEARNING → READY → PLAYING.
 * Server tracks `onboarded` on PlayerSession; client persists a localStorage
 * flag so returning players skip the tour automatically.
 */

import { state, showView } from './player-utils.js';

var utils = window.BeatifyUtils || {};

// ============================================
// Constants
// ============================================

var STORAGE_KEY_ONBOARDED = 'beatify_onboarded_v2';
var AUTO_ADVANCE_MS = 4000;
var TOTAL_CARDS = 4;
var READY_HOLD_MS = 1400; // dwell on ready screen before lobby

// ============================================
// localStorage helpers
// ============================================

function hasOnboardedFlag() {
    try {
        return localStorage.getItem(STORAGE_KEY_ONBOARDED) === '1';
    } catch (e) {
        return false;
    }
}

function setOnboardedFlag() {
    try {
        localStorage.setItem(STORAGE_KEY_ONBOARDED, '1');
    } catch (e) {
        // private mode — fall through; server state is still authoritative
    }
}

// ============================================
// Tour state
// ============================================

var tour = {
    active: false,
    replay: false,          // true when user tapped "Replay tour" in lobby
    currentIdx: 0,          // 0..3
    autoAdvanceTimer: null, // setTimeout handle
    readyTimer: null,       // setTimeout handle after tour ends
};

function clearAutoAdvance() {
    if (tour.autoAdvanceTimer) {
        clearTimeout(tour.autoAdvanceTimer);
        tour.autoAdvanceTimer = null;
    }
}

function scheduleAutoAdvance() {
    clearAutoAdvance();
    // Respect reduced-motion: no auto-advance (user must tap)
    if (window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        return;
    }
    tour.autoAdvanceTimer = setTimeout(function() {
        advance();
    }, AUTO_ADVANCE_MS);
}

// ============================================
// Rendering
// ============================================

/**
 * Render the progress segments for the current step.
 */
function renderProgress() {
    var segs = document.querySelectorAll('.tour-wiz-seg');
    for (var i = 0; i < segs.length; i++) {
        segs[i].classList.remove('filled', 'active');
        var inner = segs[i].querySelector('.tour-wiz-seg-inner');
        if (i < tour.currentIdx) {
            segs[i].classList.add('filled');
        } else if (i === tour.currentIdx) {
            segs[i].classList.add('active');
            if (!inner) {
                inner = document.createElement('div');
                inner.className = 'tour-wiz-seg-inner';
                segs[i].appendChild(inner);
            }
        }
    }
    var stepCountEl = document.getElementById('tour-step-num');
    if (stepCountEl) {
        stepCountEl.textContent = String(tour.currentIdx + 1);
    }
    // A11y: progress bar value must update so screen readers announce each step
    var progressBar = document.querySelector('.tour-wiz-progress');
    if (progressBar) {
        progressBar.setAttribute('aria-valuenow', String(tour.currentIdx + 1));
    }
}

/**
 * Show the card at the given index; hide others.
 */
function renderCard(idx) {
    var cards = document.querySelectorAll('.tour-card');
    for (var i = 0; i < cards.length; i++) {
        cards[i].classList.toggle('hidden', i !== idx);
    }
    // Last card's Next button reads "Let's play →" (key: onboarding.letsPlay).
    // Keep data-i18n on the span so BeatifyI18n.initPageTranslations() can retranslate
    // after a mid-tour language change.
    var nextBtn = document.getElementById('tour-next-btn');
    if (nextBtn) {
        var i18nKey = idx === TOTAL_CARDS - 1 ? 'onboarding.letsPlay' : 'onboarding.nextBtn';
        var fallback = idx === TOTAL_CARDS - 1 ? "Let's play" : 'Next';
        var label = utils.t ? utils.t(i18nKey) : fallback;
        if (label === i18nKey) label = fallback;
        nextBtn.innerHTML = '<span data-i18n="' + i18nKey + '">' + label + '</span>'
            + '<span class="chev" aria-hidden="true">→</span>';
    }
}

// ============================================
// Flow
// ============================================

function advance() {
    clearAutoAdvance();
    if (tour.currentIdx < TOTAL_CARDS - 1) {
        tour.currentIdx++;
        renderProgress();
        renderCard(tour.currentIdx);
        scheduleAutoAdvance();
    } else {
        finishTour();
    }
}

function skip() {
    clearAutoAdvance();
    finishTour();
}

function finishTour() {
    clearAutoAdvance();
    tour.active = false;

    // Replay mode: go straight back to lobby, no server ping, no flag write.
    if (tour.replay) {
        tour.replay = false;
        showView('lobby-view');
        return;
    }

    // First-time completion: persist flag + notify server + show ready, then lobby.
    setOnboardedFlag();
    sendOnboardedToServer();
    showReadyScreen();
}

function sendOnboardedToServer() {
    if (!state.ws || state.ws.readyState !== WebSocket.OPEN) {
        // No live socket yet — server will reflect the flag once client
        // re-sends after join. We write localStorage so subsequent visits skip.
        return;
    }
    try {
        state.ws.send(JSON.stringify({ type: 'player_onboarded' }));
    } catch (e) {
        console.warn('[Beatify] Failed to send player_onboarded:', e);
    }
}

// ============================================
// Ready screen
// ============================================

function showReadyScreen() {
    // Populate copy
    var nameEl = document.getElementById('ready-name');
    if (nameEl) {
        var template = utils.t ? utils.t('onboarding.ready', { name: state.playerName || '' }) : null;
        nameEl.textContent = template && template !== 'onboarding.ready'
            ? template
            : "You're in, " + (state.playerName || '') + '!';
    }

    var subEl = document.getElementById('ready-subtitle');
    if (subEl) {
        subEl.textContent = utils.t ? utils.t('onboarding.readySubtitle') : 'Get ready to play';
    }

    var labelEl = document.getElementById('ready-label');
    if (labelEl) {
        labelEl.textContent = utils.t ? utils.t('onboarding.waitingHost') : 'Waiting for host to start';
    }

    updateReadyCount();
    showView('ready-view');

    // Hold ready for a moment, then drop into lobby (unless game starts in the meantime).
    if (tour.readyTimer) clearTimeout(tour.readyTimer);
    tour.readyTimer = setTimeout(function() {
        tour.readyTimer = null;
        // Only swap to lobby if we're still on ready-view (phase may have changed).
        var ready = document.getElementById('ready-view');
        if (ready && !ready.classList.contains('hidden')) {
            showView('lobby-view');
        }
    }, READY_HOLD_MS);
}

/**
 * Called from player-core state handler to refresh ready screen meta
 * whenever a state update arrives during the brief ready-hold window.
 */
export function updateReadyCount(playersArg, difficultyArg) {
    var el = document.getElementById('ready-count');
    if (!el) return;
    var count = (playersArg && playersArg.length) || state.lastPlayerCount || 0;
    var difficulty = difficultyArg || state.lastDifficulty || '';
    if (!count) { el.textContent = ''; return; }
    var template = utils.t
        ? utils.t('onboarding.waitingCount', { count: count, difficulty: difficulty })
        : null;
    if (template && template !== 'onboarding.waitingCount') {
        el.textContent = template;
    } else {
        el.textContent = count + ' players in lobby';
    }
}

// ============================================
// Public API
// ============================================

/**
 * Decide whether to show the tour based on server + local state.
 * @param {Object} currentPlayer - player row from state.players
 * @returns {boolean} true if tour should run
 */
export function shouldShowTour(currentPlayer) {
    if (!currentPlayer) return false;
    if (currentPlayer.is_admin) return false;
    if (currentPlayer.onboarded === true) return false;
    if (hasOnboardedFlag()) {
        // Client says done but server hasn't heard — send it now.
        sendOnboardedToServer();
        return false;
    }
    return true;
}

/**
 * Enter the tour view from a fresh join (LEARNING state).
 */
export function startTour() {
    tour.active = true;
    tour.replay = false;
    tour.currentIdx = 0;
    renderProgress();
    renderCard(0);
    showView('tour-view');
    scheduleAutoAdvance();
}

/**
 * Enter the tour in replay mode (from lobby "Replay" link).
 * No server ping, no flag write — just informational.
 */
export function replayTour() {
    tour.active = true;
    tour.replay = true;
    tour.currentIdx = 0;
    renderProgress();
    renderCard(0);
    showView('tour-view');
    scheduleAutoAdvance();
}

/**
 * Force-exit the tour (e.g. game started while user was touring).
 */
export function forceExit() {
    if (!tour.active) return;
    clearAutoAdvance();
    if (tour.readyTimer) {
        clearTimeout(tour.readyTimer);
        tour.readyTimer = null;
    }
    tour.active = false;
    tour.replay = false;
    // Don't flag as onboarded on force-exit; next lobby visit resumes the tour.
}

/**
 * Attach Skip/Next/tap-card/replay-link event listeners once at init.
 */
export function setupTour() {
    // Skip link at top-right of the progress header
    var skipLink = document.getElementById('tour-skip-link');
    if (skipLink) skipLink.addEventListener('click', function(e) { e.preventDefault(); skip(); });

    // Bottom Skip button
    var skipBtn = document.getElementById('tour-skip-btn');
    if (skipBtn) skipBtn.addEventListener('click', skip);

    // Bottom Next / Let's play button
    var nextBtn = document.getElementById('tour-next-btn');
    if (nextBtn) nextBtn.addEventListener('click', advance);

    // Replay link in lobby
    var replayLink = document.getElementById('replay-tour-link');
    if (replayLink) replayLink.addEventListener('click', function(e) {
        e.preventDefault();
        replayTour();
    });

    // Pause auto-advance on tap anywhere within the tour card (lets reader linger)
    var container = document.querySelector('.tour-container');
    if (container) {
        container.addEventListener('touchstart', clearAutoAdvance, { passive: true });
        container.addEventListener('mousedown', clearAutoAdvance);
    }
}

export function isActive() {
    return tour.active;
}
