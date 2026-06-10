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

// --- request-row rendering -------------------------------------------------
export const REQUEST_STATUS_LABELS = {
    pending: '⏳ Pending',
    ready: '✅ Ready',
    installed: '✓ Installed',
    declined: '❌ Declined',
};

/**
 * Build the HTML for one request row (legacy #my-requests-list card).
 */
export function buildRequestRowHtml(request) {
    const statusLabel = REQUEST_STATUS_LABELS[request.status] || request.status;
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
