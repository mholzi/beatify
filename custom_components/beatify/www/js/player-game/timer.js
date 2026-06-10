/**
 * Beatify Player - Game / Countdown Timer (Story 4.2)
 * Extracted from player-game.js (#1279 step 6/6). Self-contained: module-level
 * state (countdownInterval, _timerFloatObserver, _timerFloatObservedTarget) is
 * local to this cluster.
 */

import { state } from '../player-utils.js';

// ============================================
// Countdown Timer (Story 4.2)
// ============================================

var countdownInterval = null;

/**
 * Start countdown timer
 * @param {number} deadline - Server deadline timestamp in milliseconds
 */
export function startCountdown(deadline) {
    stopCountdown();

    var timerElement = document.getElementById('timer');
    if (!timerElement) return;

    var timerNeon = document.getElementById('timer-neon');
    // #817: floating mini-timer for when the main timer scrolls out of view.
    var timerFloat = document.getElementById('timer-float');
    var timerFloatNum = document.getElementById('timer-float-num');

    timerElement.classList.remove('timer--warning', 'timer--critical');
    if (timerNeon) timerNeon.classList.remove('timer-neon--warn');
    if (timerFloat) timerFloat.classList.remove('timer-float--warn');

    // #817: arm the IntersectionObserver once per countdown. Shows the
    // floating mini-timer when the main neon timer is NOT in viewport
    // (typical when user scrolls down to reach the Submit button) and
    // hides it when scrolled back up. Tear down on stopCountdown.
    _ensureTimerFloatObserver(timerNeon, timerFloat);

    // Watchdog tick counter — counts updateCountdown ticks spent past the
    // deadline so the round_timeout nudge can retry instead of firing once.
    var timedOutTicks = 0;

    function updateCountdown() {
        var now = Date.now();
        var remaining = Math.max(0, Math.ceil((deadline - now) / 1000));

        timerElement.textContent = remaining;
        if (timerFloatNum) timerFloatNum.textContent = remaining;

        if (remaining <= 5) {
            timerElement.classList.remove('timer--warning');
            timerElement.classList.add('timer--critical');
        } else if (remaining <= 10) {
            timerElement.classList.remove('timer--critical');
            timerElement.classList.add('timer--warning');
        } else {
            timerElement.classList.remove('timer--warning', 'timer--critical');
        }

        // Arcade timer neon ring + floating pill: pink by default, red + pulse at ≤10s
        if (timerNeon) {
            timerNeon.classList.toggle('timer-neon--warn', remaining <= 10);
        }
        if (timerFloat) {
            timerFloat.classList.toggle('timer-float--warn', remaining <= 10);
        }

        // ARIA announcements at key moments (Story 9.7)
        if (remaining === 10) {
            timerElement.setAttribute('aria-label', '10 seconds remaining');
        } else if (remaining === 5) {
            timerElement.setAttribute('aria-label', '5 seconds!');
        } else if (remaining === 0) {
            timerElement.setAttribute('aria-label', 'Time is up!');
        } else {
            timerElement.setAttribute('aria-label', 'Time remaining: ' + remaining + ' seconds');
        }

        if (remaining <= 0) {
            // Watchdog: the server's round timer is a single async task — if
            // it dies the round freezes on PLAYING forever (cancelled on a
            // pause and never restarted, lost to a resume/desync edge). Our
            // countdown is independent, so once it passes zero we nudge the
            // server to end the round. handle_round_timeout is idempotent and
            // only acts once the deadline truly passed — so a single nudge can
            // race (clock skew) or be dropped (socket mid-reconnect) with no
            // recovery. Keep nudging every few seconds until the phase leaves
            // PLAYING, which tears this countdown down (player-core.js). Do
            // NOT stopCountdown() here — that would make this single-shot.
            timedOutTicks += 1;
            if (timedOutTicks === 1 || timedOutTicks % 3 === 0) {
                if (state.ws && state.ws.readyState === WebSocket.OPEN) {
                    state.ws.send(JSON.stringify({ type: 'round_timeout' }));
                }
            }
        }
    }

    updateCountdown();
    countdownInterval = setInterval(updateCountdown, 1000);
}

// #817: IntersectionObserver state, scoped to one observer reused across
// rounds. Recreated lazily on first startCountdown call after stopCountdown
// (e.g. between rounds the DOM nodes can disappear/reappear).
var _timerFloatObserver = null;
var _timerFloatObservedTarget = null;

function _ensureTimerFloatObserver(timerNeon, timerFloat) {
    if (!timerFloat || !timerNeon) return;
    if (typeof IntersectionObserver === 'undefined') {
        // Fallback for ancient browsers — just always show the float during
        // PLAYING. stopCountdown will hide it.
        timerFloat.classList.remove('hidden');
        timerFloat.classList.add('timer-float--visible');
        return;
    }
    // If we're already observing the same target, leave it alone.
    if (_timerFloatObserver && _timerFloatObservedTarget === timerNeon) return;
    if (_timerFloatObserver) _timerFloatObserver.disconnect();

    _timerFloatObserver = new IntersectionObserver(function(entries) {
        var entry = entries[0];
        if (!entry) return;
        // When the main timer is NOT visible, show the float; otherwise hide.
        if (entry.isIntersecting) {
            timerFloat.classList.add('hidden');
            timerFloat.classList.remove('timer-float--visible');
        } else {
            timerFloat.classList.remove('hidden');
            timerFloat.classList.add('timer-float--visible');
        }
    }, {
        // Trigger as soon as any part of the main timer leaves the viewport.
        threshold: 0.1,
    });
    _timerFloatObserver.observe(timerNeon);
    _timerFloatObservedTarget = timerNeon;
}

/**
 * Stop countdown timer
 */
export function stopCountdown() {
    if (countdownInterval) {
        clearInterval(countdownInterval);
        countdownInterval = null;
    }
    // #817: hide the floating mini-timer between rounds. The main timer
    // node may also be torn down by view transitions; safe to leave the
    // observer in place — re-arming on the next startCountdown is cheap.
    var timerFloat = document.getElementById('timer-float');
    if (timerFloat) {
        timerFloat.classList.add('hidden');
        timerFloat.classList.remove('timer-float--visible', 'timer-float--warn');
    }
    if (_timerFloatObserver) {
        _timerFloatObserver.disconnect();
        _timerFloatObserver = null;
        _timerFloatObservedTarget = null;
    }
}
