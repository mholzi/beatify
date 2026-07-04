/**
 * Beatify Player - Game / Countdown Timer (Story 4.2)
 * Extracted from player-game.js (#1279 step 6/6). Self-contained: module-level
 * state (countdownInterval, _timerFloatObserver, _timerFloatObservedTarget) is
 * local to this cluster.
 *
 * #1273 AC#3 — FE holds no authoritative timer state. The countdown is derived
 * from the server's authoritative timer. #1662: to stay immune to a wrong client
 * clock, it anchors to the server's *relative* `seconds_remaining` (re-anchored
 * to the client's own Date.now() on each state_update) rather than subtracting
 * the server wall-clock `deadline` from the client clock; the absolute `deadline`
 * is retained as a back-compat fallback and for the smooth-correct ease below.
 * When a fresh state_update carries a DIFFERENT deadline mid-round
 * (network jitter, reconnect, tab refresh, pre-round-TTS deadline shift), the
 * displayed seconds would otherwise hard-jump. "V1 Smooth Correct": instead of
 * snapping, the effective deadline EASES from the old value to the authoritative
 * server value over ~400ms — no visible jump, just a slightly faster tick — and
 * the neon ring flashes a brief ghost-ring catch-up glow that fits the existing
 * glowing-ring language.
 */

import { state } from '../player-utils.js';

// ============================================
// Countdown Timer (Story 4.2)
// ============================================

var countdownInterval = null;

// #1273: the deadline the countdown is currently rendering toward. Tracked so a
// re-pushed state_update can detect drift against what's on screen and decide
// between a silent no-op, a smooth ease, or a normal (re)start.
var activeDeadline = null;

// #1273: smooth-correct tuning.
// - DRIFT_THRESHOLD_MS: below this the new deadline is within clock-jitter noise;
//   adopt it silently (no ease, no visual) so we don't churn the ring every push.
// - EASE_DURATION_MS: how long the effective deadline glides old → new (~400ms).
var DRIFT_THRESHOLD_MS = 250;
var EASE_DURATION_MS = 400;

// rAF handle for the in-flight ease, so a newer push can cancel/replace it.
var _easeRaf = null;

function _cancelEase() {
    if (_easeRaf !== null && typeof cancelAnimationFrame === 'function') {
        cancelAnimationFrame(_easeRaf);
    }
    _easeRaf = null;
}

// easeOutCubic — fast first, settles gently into the server value.
function _easeOutCubic(t) {
    var p = 1 - t;
    return 1 - p * p * p;
}

/**
 * Start countdown timer
 * @param {number} deadline - Server deadline timestamp in milliseconds
 * @param {number} [secondsRemaining] - Server-computed *relative* seconds left
 *   (skew-immune). #1662: when present, the countdown re-anchors to the CLIENT's
 *   own clock (deadline := Date.now() + secondsRemaining·1000) instead of
 *   comparing the server wall-clock `deadline` to a possibly-wrong client
 *   `Date.now()`. Mirrors the TA-vote timer (player-reveal.js). Absent → fall
 *   back to the raw server `deadline` (older server / unit tests).
 */
export function startCountdown(deadline, secondsRemaining) {
    // #1662: derive a CLIENT-LOCAL deadline from the server's relative remaining
    // seconds so a wrong client clock can't skew the countdown. Everything below
    // (drift-compare, smooth-correct ease, watchdog) then operates on a deadline
    // that lives entirely in the client's own Date.now() frame.
    var effectiveDeadline =
        (typeof secondsRemaining === 'number' && isFinite(secondsRemaining))
            ? Date.now() + secondsRemaining * 1000
            : deadline;

    // #1273: smooth-correct path. If a countdown is already live and this push
    // carries a *different* authoritative deadline, glide to it instead of the
    // hard stop+restart below — but only when the drift is real (> threshold)
    // and we can actually animate (rAF present; absent under tests / SSR).
    if (
        countdownInterval !== null &&
        activeDeadline !== null &&
        typeof requestAnimationFrame === 'function'
    ) {
        var drift = Math.abs(effectiveDeadline - activeDeadline);
        if (drift <= DRIFT_THRESHOLD_MS) {
            // Within jitter noise — adopt the server value silently, keep ticking.
            activeDeadline = effectiveDeadline;
            return;
        }
        if (_smoothCorrectTo(effectiveDeadline)) return;
        // _smoothCorrectTo returned false (DOM gone) → fall through to a clean restart.
    }

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

    // #1273: this is now the deadline the screen renders toward. updateCountdown
    // reads activeDeadline (not the captured param) so the smooth-correct ease
    // can retarget it live without tearing down the interval.
    activeDeadline = effectiveDeadline;

    // Watchdog tick counter — counts updateCountdown ticks spent past the
    // deadline so the round_timeout nudge can retry instead of firing once.
    var timedOutTicks = 0;

    function updateCountdown() {
        var now = Date.now();
        var remaining = Math.max(0, Math.ceil((activeDeadline - now) / 1000));

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

// #1273: paint a remaining-seconds value onto the main timer + float pill and
// reconcile the warning/critical threshold classes. Factored out so the
// smooth-correct ease can repaint intermediate frames with the exact same
// rules the 1 s interval uses. Returns false if the timer node is gone.
function _paintRemaining(remaining) {
    var timerElement = document.getElementById('timer');
    if (!timerElement) return false;
    var timerNeon = document.getElementById('timer-neon');
    var timerFloat = document.getElementById('timer-float');
    var timerFloatNum = document.getElementById('timer-float-num');

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
    if (timerNeon) timerNeon.classList.toggle('timer-neon--warn', remaining <= 10);
    if (timerFloat) timerFloat.classList.toggle('timer-float--warn', remaining <= 10);
    return true;
}

/**
 * #1273 AC#3 — V1 Smooth Correct. Glide the on-screen countdown from the
 * currently-rendered deadline to the authoritative server `newDeadline` over
 * ~400ms instead of hard-jumping. The interval keeps running underneath (so the
 * watchdog + ARIA logic is untouched); this just paints eased intermediate
 * frames on top and adds a brief ghost-ring catch-up glow. On completion the
 * eased value lands exactly on `newDeadline`, which becomes the new
 * activeDeadline the interval renders from.
 *
 * @param {number} newDeadline - authoritative server deadline (epoch ms)
 * @returns {boolean} true if the ease was armed, false if DOM was missing
 */
function _smoothCorrectTo(newDeadline) {
    var timerNeon = document.getElementById('timer-neon');
    if (!document.getElementById('timer')) return false;

    var fromDeadline = activeDeadline;
    var startTs = Date.now();

    _cancelEase();
    // Ghost-ring: a short catch-up glow on the neon ring while we reconcile.
    if (timerNeon) timerNeon.classList.add('timer-neon--catchup');

    function frame() {
        var elapsed = Date.now() - startTs;
        var t = elapsed / EASE_DURATION_MS;
        if (t >= 1) {
            // Settled — hand the authoritative deadline back to the interval.
            activeDeadline = newDeadline;
            _paintRemaining(Math.max(0, Math.ceil((newDeadline - Date.now()) / 1000)));
            if (timerNeon) timerNeon.classList.remove('timer-neon--catchup');
            _easeRaf = null;
            return;
        }
        // Eased deadline glides from old → new; the displayed seconds follow.
        var eased = fromDeadline + (newDeadline - fromDeadline) * _easeOutCubic(t);
        // Keep activeDeadline in step so a concurrent interval tick agrees.
        activeDeadline = eased;
        _paintRemaining(Math.max(0, Math.ceil((eased - Date.now()) / 1000)));
        _easeRaf = requestAnimationFrame(frame);
    }
    _easeRaf = requestAnimationFrame(frame);
    return true;
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
    // #1273: tear down any in-flight smooth-correct ease and clear its state so
    // the next round starts clean (no stale deadline, no lingering ghost-ring).
    _cancelEase();
    activeDeadline = null;
    var timerNeonStop = document.getElementById('timer-neon');
    if (timerNeonStop) timerNeonStop.classList.remove('timer-neon--catchup');
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
