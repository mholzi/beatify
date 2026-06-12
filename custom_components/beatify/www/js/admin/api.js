/**
 * Beatify Admin — REST/WebSocket hub layer (#1279 Schritt 3/6).
 *
 * Second real ES module of the admin decomposition. Owns the admin WebSocket
 * connection lifecycle (connect, auth, reconnect/backoff, zombie-auth recovery)
 * and the inbound message dispatch. `admin.js` keeps the view-/game-state code
 * and registers its callbacks + state setters once via `initAdminApi()` (same
 * dependency-injection pattern step 2 used for `setCurrentGameResolver`).
 *
 * Why a resolver/DI shim instead of plain imports: the WS hub reaches into a
 * lot of admin-private mutable state (`currentGame`, `currentView`,
 * `isPlaying`, …) and view helpers (`handleAdminStateUpdate`, `showError`, …).
 * Importing those back from admin.js would create a hard module cycle and the
 * mutable bindings would not stay live. Instead admin.js injects live readers
 * (`getCurrentGame`), setters (`setIsPlaying`) and callbacks once at init, so
 * the hub always sees admin's current state without owning it.
 *
 * The WS socket itself (`adminWs`) and the connection-internal counters
 * (reconnect attempts, auth-recovery budget) live HERE and are encapsulated.
 * The ~18 admin.js sites that used to poke `adminWs` directly now go through
 * the exported accessors (`isAdminWsOpen`, `sendAdminWs`, `closeAdminWs`,
 * `resetReconnectAttempts`, `getAdminWs`).
 *
 * REST note: admin.js has no apiGet/apiPost wrappers — REST is done inline via
 * `fetch()` / `BeatifyAuth.fetch()` with `_adminHeaders()` (already in
 * admin/util.js since step 2). So the only shared REST helper, `_adminHeaders`,
 * already lives in util.js; this module re-exports it for a single api-surface
 * import in admin.js, and adds the two pure WS helpers below.
 */

import { _adminHeaders, _setAdminToken } from './util.js';

// Re-export the REST header helper so admin.js can import the whole hub surface
// (REST + WS) from one module. The implementation stays in util.js (step 2).
export { _adminHeaders };

// --- pure helpers (unit-tested) --------------------------------------------

const MAX_ADMIN_WS_AUTH_RECOVERIES = 2;
const MAX_ADMIN_RECONNECT = 10;

/**
 * Build the admin WS URL from a `location`-like object. Pure — no globals.
 * `wss:` on HTTPS, `ws:` otherwise.
 */
export function buildWsUrl(loc) {
    const protocol = loc.protocol === 'https:' ? 'wss:' : 'ws:';
    return protocol + '//' + loc.host + '/beatify/ws';
}

/**
 * Exponential backoff delay (ms) for reconnect attempt N (1-based), capped at
 * 30s. attempt=1 → 1000, 2 → 2000, … pure.
 */
export function reconnectDelay(attempt) {
    return Math.min(1000 * Math.pow(2, attempt - 1), 30000);
}

// --- injected admin dependencies -------------------------------------------
// admin.js registers these once via initAdminApi(). Defaults are inert so the
// module is import-safe before init (no TDZ, no throw at module eval).

let deps = {
    debug: () => {},
    // live state readers (admin.js owns these mutable bindings)
    getCurrentGame: () => null,
    getCurrentView: () => null,
    // state setters (admin-owned mutable state the hub must update)
    setIsPlaying: () => {},
    setAdminPlayerName: () => {},
    setAdminSessionId: () => {},
    getAdminPlayerName: () => null,
    // view / flow callbacks
    handleAdminStateUpdate: () => {},
    startLobbyPolling: () => {},
    stopLobbyPolling: () => {},
    showError: () => {},
    resetHomeStartButton: () => {},
};

/**
 * Register admin.js's live state readers, setters and callbacks. Called once
 * at admin module init. Missing keys keep their inert defaults.
 */
export function initAdminApi(overrides) {
    deps = { ...deps, ...(overrides || {}) };
}

// --- WS connection state (encapsulated in this module) ---------------------
let adminWs = null;
let adminReconnectAttempts = 0;
// Zombie-auth recovery state. The HA access token in localStorage can pass the
// local expiry check while being dead server-side (HA restart, refresh-token
// revoke). When the admin WS responds UNAUTHORIZED we force a refresh and
// reconnect; the recovery flow owns the reconnect during that window, so
// onclose must not double-schedule. The counter prevents an infinite loop if
// the refreshed token is *also* rejected — bounce to HA login.
let adminWsAuthRecovering = false;
let adminWsAuthRecoveryAttempts = 0;
// #1395: coalesce overlapping connectAdminWebSocket() calls. The function
// awaits getAccessToken() before it can assign adminWs, so two concurrent
// callers (visibilitychange, onclose backoff, sendAdminCommand reconnect,
// handleAdminJoin poll) could both pass the pre-await guard and each create a
// socket. This flag is set synchronously the moment a connect is in flight and
// cleared once the socket is assigned (or the attempt bails), so a second
// caller returns immediately instead of opening a duplicate, orphaned socket.
let adminWsConnecting = false;

// --- WS accessors (used by admin.js view code instead of touching adminWs) -

/** Raw socket — for the rare reader that needs the live object. */
export function getAdminWs() {
    return adminWs;
}

/** True iff the admin WS is connected and OPEN. */
export function isAdminWsOpen() {
    return !!adminWs && adminWs.readyState === WebSocket.OPEN;
}

/**
 * Send a JSON payload over the admin WS if open. Returns true if sent.
 * Callers that need disconnect-feedback should use `sendAdminCommand`.
 */
export function sendAdminWs(payload) {
    if (isAdminWsOpen()) {
        adminWs.send(JSON.stringify(payload));
        return true;
    }
    return false;
}

/** Close + clear the admin WS (used when switching back to setup). */
export function closeAdminWs() {
    if (adminWs) {
        adminWs.close();
        adminWs = null;
    }
}

/** Reset the reconnect backoff counter (user-initiated reconnects). */
export function resetReconnectAttempts() {
    adminReconnectAttempts = 0;
}

// --- WS lifecycle ----------------------------------------------------------

/**
 * Connect admin WebSocket for real-time game state updates.
 * #998: authenticates via admin_connect with a Home Assistant access token.
 */
export async function connectAdminWebSocket() {
    // #1395: guard BEFORE the token await. An existing socket that is OPEN *or*
    // still CONNECTING means a connection is already established/in progress —
    // returning here stops a concurrent caller from overwriting `adminWs` with
    // a second socket and orphaning the first (the old check ran AFTER the
    // await and only matched OPEN, so a CONNECTING socket slipped through). The
    // `adminWsConnecting` flag covers the window where a connect is awaiting its
    // token and has not yet assigned adminWs.
    if (adminWsConnecting) return;
    if (adminWs &&
        (adminWs.readyState === WebSocket.OPEN ||
         adminWs.readyState === WebSocket.CONNECTING)) {
        return; // Already connected or connecting
    }

    adminWsConnecting = true;
    try {
        // #998: the admin WS is gated by HA login. getAccessToken() refreshes a
        // stale token transparently; null means the host is not logged in.
        var token = await BeatifyAuth.getAccessToken();
        // rc13 (#1131): in Companion bypass mode there is no OAuth token but the
        // WS must still open — server-side admin_connect accepts the request on
        // UA+RFC1918 signature when ha_token is falsy. Without this short-circuit
        // the admin WS never opens on Android Companion (no `[WS-Debug] upgrade`
        // log fires either, which is what surfaced the bug on rc12).
        if (!token && !BeatifyAuth.isCompanionBypassMode()) return;

        // Re-check after the await: another flow (e.g. zombie-auth recovery)
        // may have opened/started a socket while getAccessToken() was pending.
        if (adminWs &&
            (adminWs.readyState === WebSocket.OPEN ||
             adminWs.readyState === WebSocket.CONNECTING)) {
            return; // Already connected or connecting
        }

        var wsUrl = buildWsUrl(window.location);

        try {
            adminWs = new WebSocket(wsUrl);
        } catch (err) {
            console.error('[Admin WS] Failed to create WebSocket:', err);
            return;
        }
        var ws = adminWs;

        ws.onopen = function() {
            // #1395: ignore a late onopen from a socket that is no longer the
            // active one (it was superseded/closed); it must not reset counters
            // or send admin_connect on behalf of the current connection.
            if (ws !== adminWs) return;
            // rc6 (#1120 diagnostics): log token characteristics so chrome://inspect
            // captures whether force=true bridge calls actually return different
            // tokens across recovery cycles. Prefix only — first 12 chars, safe
            // to share; HA tokens are JWT so prefix is just the header.
            deps.debug(
                '[Admin WS] Connected, sending admin_connect (token: len=' +
                (token ? token.length : 0) +
                ', prefix=' +
                (token ? token.slice(0, 12) : 'null') +
                ', recoveryAttempt=' +
                adminWsAuthRecoveryAttempts + '/' + MAX_ADMIN_WS_AUTH_RECOVERIES +
                ')'
            );
            adminReconnectAttempts = 0;
            ws.send(JSON.stringify({
                type: 'admin_connect',
                ha_token: token
            }));
        };

        ws.onmessage = function(event) {
            // #1395: drop messages from a stale socket — they belong to a
            // connection we have already replaced and must not drive dispatch.
            if (ws !== adminWs) return;
            try {
                var data = JSON.parse(event.data);
                handleAdminWsMessage(data);
            } catch (err) {
                console.error('[Admin WS] Message parse error:', err);
            }
        };

        ws.onclose = function() {
            // #1395: only act if THIS socket is still the shared adminWs. After
            // closeAdminWs()+reconnect or the UNAUTHORIZED recovery (which nulls
            // adminWs and opens a fresh socket), the dead socket's deferred
            // onclose would otherwise null the module variable even though it now
            // points at the healthy replacement — isAdminWsOpen() would then
            // report disconnected and leak the live socket. Bail for orphans.
            if (ws !== adminWs) return;
            deps.debug('[Admin WS] Disconnected');
            adminWs = null;
            // Issue #550: Re-enable lobby polling while WS is down so
            // spectator admin still sees player join/leave updates
            if (deps.getCurrentView() === 'lobby') {
                deps.startLobbyPolling();
            }
            // Zombie-auth recovery owns the reconnect during refresh — skipping
            // the backoff path here avoids two parallel WSes racing admin_connect.
            if (adminWsAuthRecovering) return;
            // Auto-reconnect with backoff
            if (adminReconnectAttempts < MAX_ADMIN_RECONNECT && deps.getCurrentGame()) {
                adminReconnectAttempts++;
                var delay = reconnectDelay(adminReconnectAttempts);
                setTimeout(connectAdminWebSocket, delay);
            }
        };

        ws.onerror = function(err) {
            // #1395: an orphaned socket's error must not be treated as the
            // active connection's; the identity check keeps logs attributable.
            if (ws !== adminWs) return;
            console.error('[Admin WS] Error:', err);
        };
    } finally {
        // Released synchronously here: the socket (if any) is now assigned to
        // adminWs, so the CONNECTING/OPEN guard above takes over coalescing.
        adminWsConnecting = false;
    }
}

/**
 * Route incoming WebSocket messages.
 */
export function handleAdminWsMessage(data) {
    switch (data.type) {
        case 'admin_connect_ack':
            deps.debug('[Admin WS] Authenticated, game_id:', data.game_id);
            // Authenticated cleanly — reset the zombie-auth recovery budget
            // so future revocations get their full attempt allowance.
            adminWsAuthRecoveryAttempts = 0;
            // Stop REST polling — WS pushes are active
            deps.stopLobbyPolling();
            break;

        case 'state':
            deps.handleAdminStateUpdate(data);
            break;

        case 'join_ack':
            // Admin successfully joined as player
            deps.setIsPlaying(true);
            if (data.session_id) {
                deps.setAdminSessionId(data.session_id);
                // Match player-core.js cookie convention: path=/beatify +
                // Secure on HTTPS. The old path=/ without Secure was silently
                // rejected by Nabu Casa's HTTPS tunnel, so /play never saw
                // the identity and prompted for name again.
                var secureFlag = location.protocol === 'https:' ? '; Secure' : '';
                document.cookie = 'beatify_session=' + data.session_id +
                    '; path=/beatify; max-age=86400; SameSite=Strict' + secureFlag;
            }
            deps.debug('[Admin WS] Joined as player:', deps.getAdminPlayerName());
            break;

        case 'metadata_update':
            // Update album art when metadata arrives after round start
            if (data.song) {
                var artEl = document.getElementById('admin-album-art');
                if (artEl && data.song.album_art) artEl.src = data.song.album_art;
            }
            break;

        case 'admin_token_update':
            // Issue #535: Update admin token after rematch (new game_id + token)
            _setAdminToken(data.admin_token, data.game_id);
            deps.debug('[Admin WS] Admin token updated for game:', data.game_id);
            break;

        case 'error':
            console.error('[Admin WS] Error:', data.code, data.message);
            if (data.code === 'UNAUTHORIZED') {
                // Server rejected ha_token even though BeatifyAuth's local
                // expiry says it's fresh — HA wiped the session (restart,
                // refresh-token revoke). Without recovery the onclose path
                // reconnects with the same dead token forever. Force a
                // token refresh; on success, reconnect. If refresh also
                // fails handleServerRejection() navigates to HA login. The
                // attempt counter prevents an infinite loop if the
                // refreshed token is also rejected.
                if (adminWsAuthRecovering) {
                    // Already recovering — let the in-flight refresh finish.
                    break;
                }
                if (adminWsAuthRecoveryAttempts >= MAX_ADMIN_WS_AUTH_RECOVERIES) {
                    // #1393: in Companion bypass mode the server authorizes via
                    // UA+RFC1918, so an exhausted recovery means the request
                    // reached Beatify over a non-local address — re-login via
                    // OAuth can't fix that and BeatifyAuth.login()'s
                    // /auth/authorize redirect would land the Companion WebView
                    // on the Invalid-redirect-URI screen (#1153). Surface an
                    // actionable local-network hint and stop, no redirect.
                    if (BeatifyAuth.isCompanionBypassMode()) {
                        console.warn(
                            '[Admin WS] Auth recovery exhausted in Companion ' +
                            'bypass mode — Beatify was reached over a non-local ' +
                            'address; OAuth re-login would hit the ' +
                            'Invalid-redirect-URI screen. Surfacing local-network hint.'
                        );
                        var companionMsg =
                            (window.BeatifyI18n && BeatifyI18n.t('admin.companionLocalNetworkRequired')) ||
                            'Beatify admin requires local network access from the ' +
                            'Companion app — open Beatify in an external browser, ' +
                            'or connect to your home Wi-Fi.';
                        try { deps.showError(companionMsg); } catch (e) { /* showError may not be in scope on early load */ }
                        break;
                    }
                    // Refreshed access token still rejected. Sessions are
                    // wedged — bounce to HA login. rc6 (#1120): surface a
                    // visible toast first so the user knows what's
                    // happening instead of silently watching the admin
                    // page reload after ~20s of dead WebSocket.
                    console.warn(
                        '[Admin WS] Auth recovery exhausted after ' +
                        MAX_ADMIN_WS_AUTH_RECOVERIES +
                        ' attempts; HA rejected every bridge-supplied token. ' +
                        'Forcing re-login.'
                    );
                    var exhaustedMsg =
                        (window.BeatifyI18n && BeatifyI18n.t('admin.wsAuthFailed')) ||
                        'Home Assistant rejected the access token. Re-authenticating…';
                    try { deps.showError(exhaustedMsg); } catch (e) { /* showError may not be in scope on early load */ }
                    BeatifyAuth.logout();
                    BeatifyAuth.login();
                    break;
                }
                adminWsAuthRecovering = true;
                adminWsAuthRecoveryAttempts++;
                console.warn(
                    '[Admin WS] UNAUTHORIZED — recovery attempt ' +
                    adminWsAuthRecoveryAttempts + '/' + MAX_ADMIN_WS_AUTH_RECOVERIES +
                    ' (server message: ' + (data.message || '') + ')'
                );
                var deadWs = adminWs;
                adminWs = null;
                try { deadWs?.close(); } catch (e) { /* ignore */ }
                BeatifyAuth.handleServerRejection().then(function (token) {
                    adminWsAuthRecovering = false;
                    if (!token) return; // handleServerRejection navigated away
                    adminReconnectAttempts = 0;
                    connectAdminWebSocket();
                });
            } else if (data.code === 'NAME_TAKEN' || data.code === 'NAME_INVALID') {
                deps.showError(data.message);
                deps.setIsPlaying(false);
                deps.setAdminPlayerName(null);
                var joinBtn = document.getElementById('admin-join-btn');
                if (joinBtn) {
                    joinBtn.disabled = false;
                    joinBtn.textContent = BeatifyI18n.t('admin.join');
                }
            } else {
                // #949: a start_game / next_round rejection — MEDIA_PLAYER_UNAVAILABLE,
                // GAME_NOT_STARTED, NO_SONGS_REMAINING, INVALID_ACTION, … startGameplay()
                // left the home "Start game" button on "⏳ Starting…" and returned to
                // wait for a broadcast. Un-stick the button and surface the message so
                // the host is not staring at a frozen "Starting…".
                deps.resetHomeStartButton();
                deps.showError(data.message);
            }
            break;

        default:
            // Ignore other message types (player_reaction, song_stopped, etc.)
            break;
    }
}

/**
 * #648: Send an admin WS command with feedback when disconnected.
 * Shows error + triggers reconnect if WS is down.
 */
export function sendAdminCommand(payload) {
    if (isAdminWsOpen()) {
        adminWs.send(JSON.stringify(payload));
        return true;
    }
    deps.showError(BeatifyI18n.t('admin.connectionLost') || 'Connection lost — reconnecting...');
    adminReconnectAttempts = 0;
    connectAdminWebSocket();
    return false;
}
