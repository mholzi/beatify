/**
 * Beatify Admin — pure utility helpers (#1279 Schritt 2/6).
 *
 * Extracted verbatim from admin.js as the first real ES module of the admin
 * decomposition. These helpers are side-effect-free (or depend only on the
 * browser `localStorage` / `sessionStorage` / `document` globals and the
 * admin-private `currentGame` state).
 *
 * `currentGame` lives in admin.js as mutable module state, so it is injected
 * here once via `setCurrentGameResolver()` (admin.js registers a closure that
 * always reads its live `currentGame` binding — no need to touch every
 * assignment site). Tests inject their own resolver.
 *
 * admin.js re-exposes these on `window` (compat shim) for any classic script
 * that still reads the old globals.
 */

// --- currentGame injection -------------------------------------------------
// admin.js owns the mutable `currentGame`; we read it through a resolver so the
// token helpers see live updates without util.js importing admin state.
let _currentGameResolver = () => null;

/** Register how util.js reads the live `currentGame` (admin.js calls this once). */
export function setCurrentGameResolver(fn) {
    _currentGameResolver = typeof fn === 'function' ? fn : () => null;
}

// --- admin token (#386 / #477) ---------------------------------------------
export function _getAdminToken() {
    try {
        var gameId = _currentGameResolver()?.game_id;
        if (gameId) {
            var token = localStorage.getItem('beatify_admin_token_' + gameId);
            if (token) return token;
        }
        return localStorage.getItem('beatify_admin_token');
    } catch(e) { return null; }
}

export function _setAdminToken(token, gameId) {
    try {
        if (gameId) localStorage.setItem('beatify_admin_token_' + gameId, token);
        localStorage.setItem('beatify_admin_token', token);
        // Migrate: also clear old sessionStorage key
        sessionStorage.removeItem('beatify_admin_token');
    } catch(e) {}
}

export function _adminHeaders() {
    var token = _getAdminToken();
    var headers = { 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = 'Bearer ' + token;
    return headers;
}

// --- media-player grouping -------------------------------------------------
export function groupPlayersByPlatform(players) {
    const groups = {};
    players.forEach(player => {
        const platform = player.platform || 'unknown';
        if (!groups[platform]) {
            groups[platform] = [];
        }
        groups[platform].push(player);
    });
    return groups;
}

// --- i18n helper -----------------------------------------------------------
/**
 * Resolve a translation key via the global BeatifyI18n module, falling back to
 * the supplied English string when i18n is unavailable (e.g. in unit tests /
 * before the module loads) or the key is missing. BeatifyI18n.t() returns the
 * key itself for a missing translation, so we treat that as "not found".
 * @param {string} key
 * @param {string} fallback
 * @returns {string}
 */
export function tr(key, fallback) {
    const m = (typeof window !== 'undefined') && window.BeatifyI18n;
    if (m && typeof m.t === 'function') {
        const v = m.t(key);
        if (typeof v === 'string' && v && v !== key) return v;
    }
    return fallback;
}

// --- request-row rendering -------------------------------------------------
// English fallbacks (with status emoji). The live label is resolved through
// i18n at render time so German-first hosts don't see hard English (#1577).
export const REQUEST_STATUS_LABELS = {
    pending: '⏳ Pending',
    ready: '✅ Ready',
    installed: '✓ Installed',
    declined: '❌ Declined',
};

const REQUEST_STATUS_I18N_KEYS = {
    pending: 'admin.requestStatusPending',
    ready: 'admin.requestStatusReady',
    installed: 'admin.requestStatusInstalled',
    declined: 'admin.requestStatusDeclined',
};

/**
 * Build the HTML for one request row (legacy #my-requests-list card).
 */
export function buildRequestRowHtml(request) {
    const i18nKey = REQUEST_STATUS_I18N_KEYS[request.status];
    const statusLabel = i18nKey
        ? tr(i18nKey, REQUEST_STATUS_LABELS[request.status])
        : (REQUEST_STATUS_LABELS[request.status] || request.status);
    const playlistName = escapeHtml(request.playlist_name || request.name || 'Untitled request');
    const relativeTime = request.relative_time || '';
    const updateBtn = (request.status === 'ready' && request.update_available)
        ? `<a href="https://github.com/mholzi/beatify/releases" target="_blank" rel="noopener" class="btn btn-primary request-update-btn">Update to v${escapeHtml(request.release_version || '')}</a>`
        : '';

    const thumbnail = request.thumbnail_url
        ? `<img class="request-item-thumbnail" src="${request.thumbnail_url}" alt="">`
        : `<div class="request-item-thumbnail-placeholder">🎵</div>`;
    return `
        <div class="request-item">
            ${thumbnail}
            <div class="request-item-info">
                <div class="request-item-name">${playlistName}</div>
                <div class="request-item-meta">${escapeHtml(relativeTime)}</div>
            </div>
            <span class="request-status request-status--${request.status}">${statusLabel}</span>
            ${updateBtn}
        </div>
    `;
}

/**
 * Escape HTML to prevent XSS
 */
export function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// --- wake-lock-first gesture guard (#1396, same defect class as #1122/#1207) -
/**
 * Invoke `requestWakeLock` SYNCHRONOUSLY, then run `action`.
 *
 * iOS HA Companion WKWebView consumes the user-activation after the first
 * `await`, so the Layer 2 NoSleep.js silent-video fallback can only call
 * `video.play()` if the wake lock is requested *before* any await/WS send,
 * inside the click's gesture window. #1122/#1207 fixed this for the
 * #home-start-game path (admin.js ~L606); the rematch-confirm and legacy
 * #start-game paths still acquired the lock only after an await, so this helper
 * gives both the same gesture-first guarantee. `action`'s later
 * `_requestWakeLock()` calls remain idempotent re-affirms (guarded by
 * `_noSleepActive`).
 *
 * @param {Function} requestWakeLock - the synchronous-entry wake-lock requester
 * @param {Function} action - the (possibly async) start/rematch work
 * @returns {*} whatever `action` returns (e.g. its promise)
 */
export function acquireWakeLockFirst(requestWakeLock, action) {
    if (typeof requestWakeLock === 'function') requestWakeLock();
    return typeof action === 'function' ? action() : undefined;
}

/**
 * Hydrate the scalar game-settings flags from a parsed `beatify_game_settings`
 * object into `adminState`, in place. Single source of truth for the
 * localStorage(camelCase) → adminState mapping so a new mode flag can't be
 * added to the wizard + start payload but silently dropped on the home→start
 * hydration path (that gap shipped `title_artist_mode` as a year game — #1180).
 *
 * Playlist hydration stays in the caller — it needs adminState.playlistData.
 *
 * @param {Object} adminState - the shared admin state object (mutated)
 * @param {Object} s - parsed settings (may be partial / from an older build)
 */
export function applyStoredGameSettings(adminState, s) {
    if (!adminState || !s || typeof s !== 'object') return;
    if (s.language) adminState.selectedLanguage = s.language;
    if (s.duration) adminState.selectedDuration = s.duration;
    if (typeof s.revealAutoAdvance === 'number') adminState.revealAutoAdvance = s.revealAutoAdvance;
    if (s.difficulty) adminState.selectedDifficulty = s.difficulty;
    if (s.provider) adminState.selectedProvider = s.provider;
    if (typeof s.artistChallenge === 'boolean') adminState.artistChallengeEnabled = s.artistChallenge;
    if (typeof s.movieQuiz === 'boolean') adminState.movieQuizEnabled = s.movieQuiz;
    if (typeof s.introMode === 'boolean') adminState.introModeEnabled = s.introMode;
    if (typeof s.closestWinsMode === 'boolean') adminState.closestWinsModeEnabled = s.closestWinsMode;
    if (typeof s.titleArtistMode === 'boolean') adminState.titleArtistModeEnabled = s.titleArtistMode;
    if (typeof s.rampupOrder === 'boolean') adminState.rampupOrderEnabled = s.rampupOrder;
    if (typeof s.finaleDouble === 'boolean') adminState.finaleDoubleEnabled = s.finaleDouble;
    if (typeof s.finaleTiebreaker === 'boolean') adminState.finaleTiebreakerEnabled = s.finaleTiebreaker;
}

// --- admin-state dirty-check (#1584 / #1659) -------------------------------
/**
 * Keys the server re-stamps with wall-clock timestamps rather than logical
 * state. Both are in the server's `_now()` units:
 *   - `deadline`          — PLAYING round timer end (serializers.py L96)
 *   - `reveal_started_at` — REVEAL entry epoch-ms (serializers.py L203, #1048)
 *
 * They can differ between two otherwise-identical broadcasts (e.g. a resume
 * re-stamp) and are consumed only by CLIENT-side 1-Hz countdown timers that
 * re-read the value on their own tick — NOT by the per-broadcast DOM render.
 * So a payload that differs ONLY in these must still dirty-skip the repaint.
 * Excluding them is safe: a real state change (new round / phase) always also
 * changes non-volatile fields (`round`, `phase`, `song`, `players`, …), so the
 * projection can never mask a genuine change into a false "equal".
 * @type {string[]}
 */
export const ADMIN_STATE_VOLATILE_KEYS = ['deadline', 'reveal_started_at'];

/**
 * Shallow projection of an admin-state payload with the known-volatile keys
 * removed. Returns the input untouched when none are present (the common case:
 * LOBBY/END frames carry no timestamp, and same-phase bursts share the same
 * key set), so no allocation happens on the hot path.
 * @param {any} state
 * @returns {any}
 */
function _projectAdminState(state) {
    if (!state || typeof state !== 'object') return state;
    let hasVolatile = false;
    for (let i = 0; i < ADMIN_STATE_VOLATILE_KEYS.length; i++) {
        if (ADMIN_STATE_VOLATILE_KEYS[i] in state) { hasVolatile = true; break; }
    }
    if (!hasVolatile) return state;
    const projected = Object.assign({}, state);
    for (let i = 0; i < ADMIN_STATE_VOLATILE_KEYS.length; i++) {
        delete projected[ADMIN_STATE_VOLATILE_KEYS[i]];
    }
    return projected;
}

/**
 * Cheap "unchanged?" check for the render coalescer's dirty-skip (#1584).
 *
 * Both payloads are the server's own stable-key-order JSON serialization of the
 * game state, so a string compare is a sound (and far cheaper than the DOM
 * rebuild) equality test. #1659: the volatile timestamp keys
 * (`ADMIN_STATE_VOLATILE_KEYS`) are stripped from BOTH sides first, so two
 * logically-equal states that differ only by a re-stamped timestamp still
 * dirty-skip instead of forcing a wasted repaint. Any failure (e.g. a cyclic
 * payload) falls back to "changed" → render.
 * @param {any} a
 * @param {any} b
 * @returns {boolean}
 */
export function adminStateEqual(a, b) {
    try {
        return JSON.stringify(_projectAdminState(a)) === JSON.stringify(_projectAdminState(b));
    } catch (e) {
        return false;
    }
}

// --- WS-broadcast render coalescing (#1584) --------------------------------
/**
 * Default frame scheduler: coalesce onto the next animation frame so a burst of
 * WS `state` broadcasts collapses into a single paint. Falls back to a ~16ms
 * timeout where `requestAnimationFrame` is unavailable (background tab, unit
 * tests, no DOM).
 */
function _defaultSchedule(cb) {
    if (typeof requestAnimationFrame === 'function') return requestAnimationFrame(cb);
    return setTimeout(cb, 16);
}

/**
 * Wrap a (potentially expensive) `render(data)` so that rapid calls coalesce
 * into ONE render per animation frame, and only the LATEST payload of a burst
 * is rendered — the final state of a burst is never dropped (#1584:
 * `handleAdminStateUpdate` rebuilt leaderboard + result cards + reveal on every
 * single `state` broadcast, janking weak hosts under fast updates).
 *
 * Returns a `push(data)` function (the drop-in replacement for the bare
 * `render`). Two coalescing mechanisms, both behaviour-preserving:
 *   1. Throttle: while a flush is already scheduled, extra pushes just swap in
 *      the newer payload instead of scheduling another render.
 *   2. Dirty-check (optional `isEqual`): if the incoming payload equals the one
 *      already on screen (and nothing is pending), skip the repaint entirely.
 *
 * `push.flush()` renders any pending payload synchronously (e.g. before
 * navigating away); `push.cancel()` drops a pending render without rendering.
 *
 * @param {(data:any)=>void} render          the heavy render to coalesce
 * @param {Object} [options]
 * @param {(cb:Function)=>any} [options.schedule] frame scheduler (default rAF)
 * @param {(a:any,b:any)=>boolean} [options.isEqual] cheap "unchanged?" check
 * @returns {((data:any)=>void) & {flush:Function, cancel:Function}}
 */
export function createRenderCoalescer(render, options) {
    const opts = options || {};
    const schedule = typeof opts.schedule === 'function' ? opts.schedule : _defaultSchedule;
    const isEqual = typeof opts.isEqual === 'function' ? opts.isEqual : null;

    let pending = false;     // a flush is scheduled
    let hasLatest = false;   // we hold an un-rendered payload
    let latest;              // newest payload of the burst (last wins)
    let lastRendered;        // payload currently on screen (dirty-check ref)
    let hasRendered = false;

    function flush() {
        pending = false;
        if (!hasLatest) return;
        const data = latest;
        hasLatest = false;
        latest = undefined;
        lastRendered = data;
        hasRendered = true;
        render(data);
    }

    function push(data) {
        // Dirty-check: identical to what's already painted and nothing queued →
        // skip the repaint (and the render's idempotent side-effects).
        if (isEqual && hasRendered && !hasLatest && isEqual(data, lastRendered)) {
            return;
        }
        latest = data;       // coalesce: newest payload wins
        hasLatest = true;
        if (!pending) {
            pending = true;
            schedule(flush);
        }
    }

    push.flush = flush;
    push.cancel = function cancel() {
        pending = false;
        hasLatest = false;
        latest = undefined;
    };
    return push;
}
