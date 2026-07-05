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

/**
 * Fetch + parse the game-status endpoint, silently retrying only on
 * transport/server errors (fetch throws, `!response.ok`, or JSON parse throws).
 *
 * "Silent" = the caller does not switch views between attempts, so the current
 * (loading) view stays put with no flash.
 *
 * @param {string} gameId
 * @param {{maxAttempts?: number, baseDelayMs?: number}} [opts]
 * @returns {Promise<object|null>} the parsed status object on a successful
 *   response (including a valid `{exists:false}`), or `null` once every attempt
 *   has failed with a transport/server error.
 */
export async function fetchGameStatusWithRetry(gameId, opts) {
    opts = opts || {};
    var maxAttempts = opts.maxAttempts || GAME_STATUS_MAX_ATTEMPTS;
    var baseDelayMs = opts.baseDelayMs != null ? opts.baseDelayMs : GAME_STATUS_RETRY_BASE_MS;

    for (var attempt = 1; attempt <= maxAttempts; attempt++) {
        try {
            var response = await fetch('/beatify/api/game-status?game=' + encodeURIComponent(gameId));
            if (!response.ok) {
                throw new Error('HTTP ' + response.status);
            }
            // A parsed body — including a legitimate {exists:false} — is a real
            // server answer. Return immediately; never retry a valid response.
            return await response.json();
        } catch (err) {
            console.warn('[Beatify] game-status attempt ' + attempt + '/' + maxAttempts
                + ' failed:', err);
            // Back off before the next try, but not after the final attempt.
            if (attempt < maxAttempts) {
                await sleep(baseDelayMs * attempt);
            }
        }
    }
    // Every attempt hit a transport/server error → let the caller fall back.
    return null;
}
