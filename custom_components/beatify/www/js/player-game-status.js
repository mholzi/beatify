/**
 * Beatify Player - Game Status Fetch (with transient-error retry)
 *
 * Extracted from player-core.js `checkGameStatus()` (#1664 item 2).
 *
 * A single failed `/beatify/api/game-status` fetch (network blip, 5xx, or a
 * JSON-parse error) used to fall straight through to `showView('not-found-view')`,
 * so a player briefly on a flaky connection was told the game does not exist.
 *
 * This module isolates the fetch so it can silently retry TRANSPORT/SERVER
 * errors a few times before giving up, while a *successful* response is always
 * returned as-is — crucially, an HTTP-200 `{exists:false}` is a legitimate
 * "game does not exist" answer and must NOT be retried.
 */

// Number of attempts (1 initial + retries) before we give up on the fetch.
export var GAME_STATUS_MAX_ATTEMPTS = 3;
// Base backoff between attempts; scaled by the attempt number (600, 1200, ...).
export var GAME_STATUS_RETRY_BASE_MS = 600;

/** Promise-based sleep with no global state (testable via fake timers). */
export function sleep(ms) {
    return new Promise(function(resolve) {
        setTimeout(resolve, ms);
    });
}

// #3390: one request may take at most this long. Without it a request that
// hangs (HA busy, a captive portal swallowing the packets) kept the loading
// spinner up for good.
export var GAME_STATUS_TIMEOUT_MS = 10000;

/**
 * Why a status check got no answer (#3390). "Gibt es nicht" and "komme nicht
 * durch" are two different states and never share a screen:
 *   - 'offline': the request never reached Home Assistant (fetch threw, or it
 *     ran into the timeout). Wrong Wi-Fi, mobile data, a page from the cache.
 *   - 'server':  Home Assistant answered, but with an error (5xx, a body that
 *     is not JSON).
 */
export var STATUS_FAIL_OFFLINE = 'offline';
export var STATUS_FAIL_SERVER = 'server';

function makeServerError(message) {
    var err = new Error(message);
    err.statusFail = STATUS_FAIL_SERVER;
    return err;
}

/** One game-status request with a timeout. Throws on any failure. */
async function fetchGameStatusOnce(gameId, timeoutMs) {
    var controller = typeof AbortController === 'function' ? new AbortController() : null;
    var timer = null;
    var timedOut = new Promise(function(resolve, reject) {
        timer = setTimeout(function() {
            if (controller) {
                try { controller.abort(); } catch (e) { /* already done */ }
            }
            reject(new Error('game-status timed out after ' + timeoutMs + 'ms'));
        }, timeoutMs);
    });
    try {
        var request = (async function() {
            var response = await fetch(
                '/beatify/api/game-status?game=' + encodeURIComponent(gameId),
                controller ? { signal: controller.signal } : undefined
            );
            if (!response.ok) {
                throw makeServerError('HTTP ' + response.status);
            }
            try {
                return await response.json();
            } catch (parseErr) {
                throw makeServerError('game-status body is not JSON');
            }
        })();
        // The loser of the race must not surface as an unhandled rejection.
        request.catch(function() {});
        timedOut.catch(function() {});
        return await Promise.race([request, timedOut]);
    } finally {
        clearTimeout(timer);
    }
}

/**
 * Fetch + parse the game-status endpoint, silently retrying only on
 * transport/server errors (fetch throws, `!response.ok`, JSON parse throws or
 * the #3390 timeout).
 *
 * "Silent" = the caller does not switch views between attempts, so the current
 * (loading) view stays put with no flash.
 *
 * @param {string} gameId
 * @param {{maxAttempts?: number, baseDelayMs?: number, timeoutMs?: number}} [opts]
 * @returns {Promise<{ok: true, data: object} | {ok: false, reason: string}>}
 *   `data` is the parsed answer (including a valid `{exists:false}`); `reason`
 *   is STATUS_FAIL_OFFLINE or STATUS_FAIL_SERVER from the LAST attempt.
 */
export async function fetchGameStatusResult(gameId, opts) {
    opts = opts || {};
    var maxAttempts = opts.maxAttempts || GAME_STATUS_MAX_ATTEMPTS;
    var baseDelayMs = opts.baseDelayMs != null ? opts.baseDelayMs : GAME_STATUS_RETRY_BASE_MS;
    var timeoutMs = opts.timeoutMs || GAME_STATUS_TIMEOUT_MS;
    var reason = STATUS_FAIL_OFFLINE;

    for (var attempt = 1; attempt <= maxAttempts; attempt++) {
        try {
            // A parsed body — including a legitimate {exists:false} — is a real
            // server answer. Return immediately; never retry a valid response.
            var data = await fetchGameStatusOnce(gameId, timeoutMs);
            return { ok: true, data: data };
        } catch (err) {
            reason = (err && err.statusFail) || STATUS_FAIL_OFFLINE;
            console.warn('[Beatify] game-status attempt ' + attempt + '/' + maxAttempts
                + ' failed:', err);
            // Back off before the next try, but not after the final attempt.
            if (attempt < maxAttempts) {
                await sleep(baseDelayMs * attempt);
            }
        }
    }
    return { ok: false, reason: reason };
}

/**
 * The older shape of the same call: the parsed answer, or `null` once every
 * attempt has failed. Kept for the callers that only need "answer or not"
 * (the ended-view poll).
 *
 * @returns {Promise<object|null>}
 */
export async function fetchGameStatusWithRetry(gameId, opts) {
    var result = await fetchGameStatusResult(gameId, opts);
    return result.ok ? result.data : null;
}

/**
 * The view a failed status check lands on (#3390). Pure, for the tests.
 * @param {string} reason - STATUS_FAIL_OFFLINE or STATUS_FAIL_SERVER
 * @returns {string} view id
 */
export function statusFailureView(reason) {
    return reason === STATUS_FAIL_SERVER ? 'ha-error-view' : 'offline-view';
}
