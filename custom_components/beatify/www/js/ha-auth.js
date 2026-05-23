/**
 * Beatify — Home Assistant OAuth2 client (#998)
 *
 * Standalone, dependency-free auth helper shared by the admin console and the
 * "playing host" path on the player page. Implements Home Assistant's
 * IndieAuth-style OAuth2 flow so a host authenticates as a real HA user
 * before any admin action is allowed.
 *
 * rc15 architecture (Safari 18 workaround):
 *   Safari 18 silently refuses certain same-origin POSTs from the OAuth-
 *   callback page state — fetch (FormData + urlencoded), XHR, /auth/token
 *   and the rc14 /beatify/auth/exchange proxy. The browser was never the
 *   right layer to fix this. rc15 moves the OAuth code exchange and the
 *   refresh flow server-side; this module never POSTs to an auth endpoint.
 *
 *   - login() redirects to /auth/authorize with redirect_uri=
 *     /beatify/auth/callback. The Beatify server (BeatifyAuthCallbackView)
 *     receives the code, exchanges it over loopback HTTP, and sets two
 *     cookies before redirecting back to /beatify/admin.
 *   - beatify_access cookie: JS-readable JSON {access_token, expires_at}.
 *     This module reads it on page load and includes the token in
 *     Authorization headers for /beatify/api/* calls.
 *   - beatify_refresh cookie: HttpOnly. Never exposed to JS. The refresh
 *     view (BeatifyAuthRefreshView) reads it server-side when this module
 *     does fetch GET /beatify/auth/refresh.
 *
 * Normal players never touch this module — joining /beatify/play stays
 * frictionless. It is only invoked on the admin page (on load) and on the
 * player page when someone claims the host role.
 *
 * Exposes `window.BeatifyAuth`.
 */
(function () {
  'use strict';

  // JS-readable session cookie set by BeatifyAuthCallbackView. Contains a
  // URL-encoded JSON object: {access_token: string, expires_at: number}.
  // expires_at is an absolute Unix timestamp (seconds) so we don't depend
  // on the client clock matching the server when the cookie was set.
  var ACCESS_COOKIE = 'beatify_access';

  // sessionStorage: CSRF state lives only for the duration of one redirect.
  var K_STATE = 'beatify_ha_oauth_state';

  // Old rc8–rc14 localStorage keys. We clear them once on init so a user
  // upgrading from a previous RC doesn't carry forward dead state that
  // could confuse a future debugger.
  var LEGACY_LOCAL_KEYS = [
    'beatify_ha_access',
    'beatify_ha_refresh',
    'beatify_ha_expires',
  ];

  // client_id / redirect_uri share the HA host, so HA auto-allows the
  // redirect without needing link-rel discovery. Computed per page load so
  // local + Nabu Casa origins each work without configuration.
  function origin() {
    return window.location.origin;
  }
  function clientId() {
    return origin() + '/beatify/';
  }
  function redirectUri() {
    // rc18: back to the rc15 architecture — redirect_uri points at the
    // server-side callback view directly. The intermediate rc16/rc17
    // detour (redirect_uri = page URL, then JS-bounce to the callback
    // view) was a workaround for HA Companion App intercepting
    // /auth/authorize inside its WKWebView. rc17's launcher change
    // (`<a target="_blank">`) already opens Beatify in external Safari
    // outside Companion's webview, so Companion never sees the OAuth
    // flow at all — making the JS bounce both unnecessary and
    // disruptive (Safari 18 broke when an extra script-driven nav
    // happened during the OAuth-callback page load).
    return origin() + '/beatify/auth/callback';
  }

  function randomState() {
    var bytes = new Uint8Array(16);
    (window.crypto || window.msCrypto).getRandomValues(bytes);
    return Array.prototype.map
      .call(bytes, function (b) {
        return ('0' + b.toString(16)).slice(-2);
      })
      .join('');
  }

  // -- cookie session ------------------------------------------------------

  function _readSessionCookie() {
    try {
      var raw = document.cookie || '';
      var prefix = ACCESS_COOKIE + '=';
      var parts = raw.split(';');
      for (var i = 0; i < parts.length; i++) {
        var p = parts[i].replace(/^\s+/, '');
        if (p.indexOf(prefix) === 0) {
          var value = p.substring(prefix.length);
          var data = JSON.parse(decodeURIComponent(value));
          if (data && data.access_token && data.expires_at) return data;
          return null;
        }
      }
      return null;
    } catch (e) {
      return null;
    }
  }

  function _clearAccessCookie() {
    // The HttpOnly refresh cookie can only be cleared server-side (the
    // refresh view does this when refresh fails). The access cookie is
    // JS-readable, so we can wipe it here on logout / state mismatch.
    try {
      document.cookie =
        ACCESS_COOKIE +
        '=; Max-Age=0; Path=/beatify; SameSite=Lax' +
        (location.protocol === 'https:' ? '; Secure' : '');
    } catch (e) {
      /* ignore */
    }
  }

  function _migrateFromLocalStorage() {
    // One-shot cleanup of pre-rc15 localStorage keys. Cookies are now the
    // canonical session source; leftover entries here can only mislead.
    try {
      for (var i = 0; i < LEGACY_LOCAL_KEYS.length; i++) {
        localStorage.removeItem(LEGACY_LOCAL_KEYS[i]);
      }
    } catch (e) {
      /* private-mode storage disabled — safe to ignore */
    }
  }

  function storedAccess() {
    var data = _readSessionCookie();
    return data ? data.access_token : null;
  }

  function accessFresh() {
    var data = _readSessionCookie();
    if (!data) return false;
    // expires_at from the server is Unix seconds; Date.now() is millis.
    return data.expires_at * 1000 > Date.now();
  }

  // -- Android Companion App auth bridge (#1114 follow-up) -----------------
  //
  // rc3 of the v3.4.3 launcher cycle: rc2 introduced a Companion bridge but
  // only knew `window.externalApp.getExternalAuth(jsonString)`. Recent
  // Companion builds (≥ 2026.4.x) dropped that direct method and only
  // expose the generic `window.externalApp.externalBus(jsonString)` channel
  // used by the HA frontend. Result: `_hasCompanionAuthBridge()` returned
  // false, refreshAccess() fell through to fetch /beatify/auth/refresh,
  // and Companion's WebView returned 401 (no cookie context). rc3 tries
  // the externalBus protocol first, then falls back to the legacy direct
  // method for older Companion builds. Responses arrive via
  // `window.externalBus({type:"result", id, success, result})`, which rc3
  // installs as a multiplexed receiver keyed by command id.
  //
  // We also widen the Android-Companion UA regex (some builds report
  // "HACompanion" or just "Hass" instead of "Home Assistant") and treat
  // the mere presence of a Companion JS bridge as a sufficient signal —
  // if the native app injected `externalApp.externalBus`, we are on
  // Companion regardless of what the UA string claims.

  function isAndroidCompanion() {
    var ua = (typeof navigator !== 'undefined' && navigator.userAgent) || '';
    if (/Android/i.test(ua) && /Home ?Assistant|HACompanion|Hass/i.test(ua)) {
      return true;
    }
    // Some Companion builds rewrite the UA in ways that don't match the
    // strings above. The injected JS bridge is a stronger signal than UA.
    if (
      typeof window.externalApp !== 'undefined' &&
      window.externalApp !== null &&
      (typeof window.externalApp.externalBus === 'function' ||
        typeof window.externalApp.getExternalAuth === 'function')
    ) {
      return true;
    }
    return false;
  }

  function _hasCompanionAuthBridge() {
    if (
      typeof window.externalApp === 'undefined' ||
      window.externalApp === null
    ) {
      return false;
    }
    return (
      typeof window.externalApp.externalBus === 'function' ||
      typeof window.externalApp.getExternalAuth === 'function'
    );
  }

  // -- externalBus path (newer Companion) ----------------------------------
  //
  // Native ↔ JS protocol:
  //   JS → native:  window.externalApp.externalBus(JSON.stringify({
  //                   id, type:"command", command:"get_external_auth",
  //                   payload:{force}
  //                 }))
  //   native → JS:  window.externalBus({type:"result", id, success, result})
  //                 result = {access_token, expires_in}
  //
  // The HA frontend defines `window.externalBus` and routes responses to
  // its own command table. Beatify's admin/dashboard/player pages do not
  // load the HA frontend, so `window.externalBus` is unset and we install
  // our own. If something else already set it (shouldn't happen on our
  // pages, but be defensive), we wrap rather than replace.

  var _externalBusPending = {}; // id → {resolve, reject, timeoutId}
  var _externalBusCommandId = 0;
  var _externalBusInstalled = false;

  function _ensureExternalBusReceiver() {
    if (_externalBusInstalled) return;
    var prior =
      typeof window.externalBus === 'function' ? window.externalBus : null;
    window.externalBus = function (raw) {
      try {
        var msg = typeof raw === 'string' ? JSON.parse(raw) : raw;
        if (
          msg &&
          msg.type === 'result' &&
          typeof msg.id !== 'undefined' &&
          _externalBusPending[msg.id]
        ) {
          var entry = _externalBusPending[msg.id];
          delete _externalBusPending[msg.id];
          if (entry.timeoutId) {
            try { clearTimeout(entry.timeoutId); } catch (e) { /* ignore */ }
          }
          if (msg.success && msg.result && msg.result.access_token) {
            entry.resolve(msg.result);
          } else {
            var errMsg = 'externalBus get_external_auth rejected';
            if (msg.error) {
              errMsg = typeof msg.error === 'string'
                ? msg.error
                : msg.error.message || msg.error.code || JSON.stringify(msg.error);
            }
            entry.reject(new Error(errMsg));
          }
          return; // claimed by us — don't forward
        }
      } catch (e) {
        /* malformed — fall through to prior handler */
      }
      if (prior) {
        try { prior(raw); } catch (e) { /* ignore */ }
      }
    };
    _externalBusInstalled = true;
  }

  function _sendViaExternalBus(force) {
    return new Promise(function (resolve, reject) {
      if (
        typeof window.externalApp === 'undefined' ||
        window.externalApp === null ||
        typeof window.externalApp.externalBus !== 'function'
      ) {
        reject(new Error('externalBus method unavailable'));
        return;
      }
      _ensureExternalBusReceiver();
      _externalBusCommandId += 1;
      var id = _externalBusCommandId;
      var timeoutId = setTimeout(function () {
        if (_externalBusPending[id]) {
          delete _externalBusPending[id];
          reject(new Error('externalBus get_external_auth timeout (10s)'));
        }
      }, 10000);
      _externalBusPending[id] = {
        resolve: resolve,
        reject: reject,
        timeoutId: timeoutId,
      };
      try {
        window.externalApp.externalBus(
          JSON.stringify({
            id: id,
            type: 'command',
            command: 'get_external_auth',
            payload: { force: !!force },
          })
        );
      } catch (e) {
        delete _externalBusPending[id];
        try { clearTimeout(timeoutId); } catch (e2) { /* ignore */ }
        reject(e);
      }
    });
  }

  // -- legacy getExternalAuth path (older Companion) -----------------------
  //
  // Older Companion builds (pre-2026.4.x) exposed the auth bridge as a
  // dedicated method. The native side calls back into a generated
  // window[callbackName](success, payload) function. Kept as a fallback
  // for users on older Companion installs.

  function _sendViaLegacyGetExternalAuth(force) {
    return new Promise(function (resolve, reject) {
      if (
        typeof window.externalApp === 'undefined' ||
        window.externalApp === null ||
        typeof window.externalApp.getExternalAuth !== 'function'
      ) {
        reject(new Error('legacy getExternalAuth method unavailable'));
        return;
      }
      var callbackName =
        '__beatifyAuthCb_' +
        Date.now() +
        '_' +
        Math.floor(Math.random() * 1e9);
      var timeoutId = setTimeout(function () {
        try { delete window[callbackName]; } catch (e) { /* ignore */ }
        reject(new Error('legacy getExternalAuth timeout (10s)'));
      }, 10000);
      window[callbackName] = function (success, payload) {
        try { clearTimeout(timeoutId); } catch (e) { /* ignore */ }
        try { delete window[callbackName]; } catch (e) { /* ignore */ }
        if (success && payload && payload.access_token) {
          resolve(payload);
        } else {
          var msg =
            payload && (payload.message || payload.error)
              ? payload.message || payload.error
              : 'legacy getExternalAuth rejected';
          reject(new Error(msg));
        }
      };
      try {
        window.externalApp.getExternalAuth(
          JSON.stringify({ callback: callbackName, force: !!force })
        );
      } catch (e) {
        try { clearTimeout(timeoutId); } catch (e2) { /* ignore */ }
        try { delete window[callbackName]; } catch (e2) { /* ignore */ }
        reject(e);
      }
    });
  }

  // Try modern externalBus first, fall back to legacy direct method.
  function getCompanionAuthToken(force) {
    if (
      typeof window.externalApp !== 'undefined' &&
      window.externalApp !== null &&
      typeof window.externalApp.externalBus === 'function'
    ) {
      return _sendViaExternalBus(force).catch(function (err) {
        if (
          window.externalApp &&
          typeof window.externalApp.getExternalAuth === 'function'
        ) {
          console.warn(
            '[BeatifyAuth] externalBus failed, falling back to legacy getExternalAuth:',
            err && err.message ? err.message : err
          );
          return _sendViaLegacyGetExternalAuth(force);
        }
        throw err;
      });
    }
    if (
      typeof window.externalApp !== 'undefined' &&
      window.externalApp !== null &&
      typeof window.externalApp.getExternalAuth === 'function'
    ) {
      return _sendViaLegacyGetExternalAuth(force);
    }
    return Promise.reject(
      new Error('No Companion auth bridge method available')
    );
  }

  // Persist a Companion-supplied token in the JS-readable session cookie so
  // the rest of the module (accessFresh / storedAccess / authedFetch) keeps
  // working without further branching. The HttpOnly refresh cookie isn't
  // needed on Companion — we just call getExternalAuth(force=true) again
  // when the access token expires.
  function _setSessionCookieFromCompanion(payload) {
    var expiresIn =
      typeof payload.expires_in === 'number' && payload.expires_in > 0
        ? payload.expires_in
        : 1800;
    var expiresAt = Math.floor(Date.now() / 1000) + expiresIn;
    var cookieValue = encodeURIComponent(
      JSON.stringify({
        access_token: payload.access_token,
        expires_at: expiresAt,
      })
    );
    var cookieStr =
      ACCESS_COOKIE +
      '=' +
      cookieValue +
      '; Path=/beatify; SameSite=Lax; Max-Age=' +
      expiresIn;
    if (location.protocol === 'https:') cookieStr += '; Secure';
    try { document.cookie = cookieStr; } catch (e) { /* ignore */ }
  }

  // -- silent refresh via /beatify/auth/refresh ----------------------------

  // Coalesce concurrent refreshes into a single in-flight request.
  var refreshInFlight = null;

  function refreshAccess() {
    if (refreshInFlight) return refreshInFlight;
    if (isAndroidCompanion() && _hasCompanionAuthBridge()) {
      // Skip the /beatify/auth/refresh round-trip entirely. The HttpOnly
      // refresh cookie was set by the server-side OAuth callback view,
      // which is unreachable on Companion (see comment block above). Use
      // the Companion in-app token bridge instead.
      refreshInFlight = getCompanionAuthToken(true)
        .then(function (payload) {
          _setSessionCookieFromCompanion(payload);
          return payload.access_token;
        })
        .catch(function (err) {
          console.warn(
            '[BeatifyAuth] Companion getExternalAuth refresh failed:',
            err && err.message ? err.message : err
          );
          return null;
        })
        .then(function (token) {
          refreshInFlight = null;
          return token;
        });
      return refreshInFlight;
    }
    refreshInFlight = fetch(origin() + '/beatify/auth/refresh', {
      method: 'GET',
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
    })
      .then(function (resp) {
        if (!resp.ok) {
          // 401 means the server cleared the refresh cookie (refresh
          // token revoked, HA wiped, etc). The browser receives the
          // Set-Cookie wipe automatically. Surface null so callers
          // fall through to login().
          return null;
        }
        return resp.json().then(function (body) {
          return (body && body.access_token) || null;
        });
      })
      .catch(function (err) {
        // Network failure — don't clear cookies on a transient blip.
        console.warn('[BeatifyAuth] refresh GET failed:', err);
        return null;
      })
      .finally(function () {
        refreshInFlight = null;
      });
    return refreshInFlight;
  }

  // -- redirect (login) ----------------------------------------------------

  function _legacyOAuthLogin() {
    var state = randomState();
    try {
      sessionStorage.setItem(K_STATE, state);
    } catch (e) {
      /* ignore — state check is best-effort if storage is unavailable */
    }
    var url =
      origin() +
      '/auth/authorize?response_type=code' +
      '&client_id=' +
      encodeURIComponent(clientId()) +
      '&redirect_uri=' +
      encodeURIComponent(redirectUri()) +
      '&state=' +
      encodeURIComponent(state);
    window.location.replace(url);
  }

  function login() {
    if (isAndroidCompanion() && _hasCompanionAuthBridge()) {
      // Companion path: pull a fresh token from the in-app bridge, plant
      // it in the cookie, and reload so init() re-enters with cookies
      // already valid. Avoids the /auth/authorize redirect that Companion
      // intercepts and 403s.
      getCompanionAuthToken(true)
        .then(function (payload) {
          _setSessionCookieFromCompanion(payload);
          window.location.href = origin() + '/beatify/admin';
        })
        .catch(function (err) {
          console.warn(
            '[BeatifyAuth] Companion login bridge failed, falling back to OAuth:',
            err && err.message ? err.message : err
          );
          _legacyOAuthLogin();
        });
      return;
    }
    _legacyOAuthLogin();
  }

  /**
   * Consume the ?auth_state= / ?auth_error= echo BeatifyAuthCallbackView
   * appends after the server-side code exchange. The callback view has
   * already set cookies (or cleared them on failure); we just validate
   * the state echo here for CSRF and strip the query.
   *
   * Returns:
   *   true  — state validated, cookies should hold a fresh session
   *   false — state mismatch OR ?auth_error= present; caller may re-login
   *   null  — no auth callback in this URL (regular page load)
   */
  function _consumeAuthCallback() {
    var params = new URLSearchParams(window.location.search);
    var authError = params.get('auth_error');
    var authState = params.get('auth_state');
    if (!authError && !authState) return null;

    if (authError) {
      console.warn(
        '[BeatifyAuth] server-side OAuth exchange returned error:',
        authError
      );
      _clearAccessCookie();
      _stripQuery();
      return false;
    }

    var expected = null;
    try {
      expected = sessionStorage.getItem(K_STATE);
      sessionStorage.removeItem(K_STATE);
    } catch (e) {
      /* ignore */
    }
    _stripQuery();
    if (expected && authState !== expected) {
      console.warn('[BeatifyAuth] OAuth state mismatch — clearing session');
      _clearAccessCookie();
      return false;
    }
    return true;
  }

  function _stripQuery() {
    try {
      window.history.replaceState(
        {},
        document.title,
        window.location.pathname + window.location.hash
      );
    } catch (e) {
      /* ignore */
    }
  }

  // -- public API ----------------------------------------------------------

  /**
   * Return a valid access token, refreshing via the server if needed.
   * Resolves null when no session can be obtained without a redirect.
   */
  function getAccessToken() {
    if (accessFresh()) return Promise.resolve(storedAccess());
    return refreshAccess();
  }

  /** True if a usable token is in the cookie. Refresh is async, see init(). */
  function isAuthenticated() {
    return accessFresh();
  }

  /**
   * Guarantee an access token. If none can be obtained this navigates away
   * to the HA login page and the returned promise never resolves.
   */
  function ensureAuthenticated() {
    return getAccessToken().then(function (token) {
      if (token) return token;
      login();
      return new Promise(function () {}); // navigating away
    });
  }

  /**
   * Recover when a non-HTTP transport (e.g. WebSocket admin auth) reports the
   * cookied access token is rejected server-side. Force a server-side
   * refresh — the local cookie's expires_at could still be in the future
   * even after HA wiped the refresh token (HA restart, user logged out
   * elsewhere).
   */
  function handleServerRejection() {
    _clearAccessCookie();
    return refreshAccess().then(function (token) {
      if (token) return token;
      login();
      return new Promise(function () {});
    });
  }

  /**
   * fetch() wrapper that attaches the HA bearer token and transparently
   * refreshes + retries once on 401. On unrecoverable auth failure it
   * redirects to login.
   */
  function authedFetch(url, opts) {
    opts = opts || {};
    return getAccessToken().then(function (token) {
      if (!token) {
        login();
        return new Promise(function () {});
      }
      return doFetch(url, opts, token, true);
    });
  }

  function doFetch(url, opts, token, allowRetry) {
    var headers = {};
    var src = opts.headers || {};
    Object.keys(src).forEach(function (k) {
      headers[k] = src[k];
    });
    headers['Authorization'] = 'Bearer ' + token;
    var merged = {};
    Object.keys(opts).forEach(function (k) {
      merged[k] = opts[k];
    });
    merged.headers = headers;
    return fetch(url, merged).then(function (resp) {
      if (resp.status !== 401 || !allowRetry) return resp;
      // Token may have expired between the freshness check and the request,
      // or been revoked server-side — refresh once and retry.
      return refreshAccess().then(function (fresh) {
        if (!fresh) {
          login();
          return new Promise(function () {});
        }
        return doFetch(url, opts, fresh, false);
      });
    });
  }

  /**
   * Initialise on page load.
   * @param {{requireAuth?: boolean}} options
   *   requireAuth: when true (admin console), redirect to HA login immediately
   *   if the user is not authenticated. When false (player page), just consume
   *   any pending redirect — login is deferred until the host role is claimed.
   * @returns {Promise<boolean>} resolves true when authenticated.
   */
  function init(options) {
    options = options || {};
    _migrateFromLocalStorage();
    var callbackResult = _consumeAuthCallback();

    // callbackResult === false means the server-side exchange reported a
    // failure or the state echo didn't match what we stored before login.
    // In either case the cookies are not usable; jump straight to login.
    if (callbackResult === false) {
      if (options.requireAuth) {
        login();
        return new Promise(function () {});
      }
      return Promise.resolve(false);
    }

    if (accessFresh()) {
      // Cookie has a fresh access token (either from the just-completed
      // callback, or a returning session within the cookie's lifetime).
      return Promise.resolve(true);
    }

    // No fresh access in the cookie — try a silent refresh. The HttpOnly
    // refresh cookie may still be valid even if the access cookie has
    // already expired (different lifetimes by design).
    return refreshAccess().then(function (token) {
      if (token) return true;
      if (!options.requireAuth) return false;
      login();
      return new Promise(function () {});
    });
  }

  window.BeatifyAuth = {
    init: init,
    login: login,
    logout: _clearAccessCookie,
    isAuthenticated: isAuthenticated,
    getAccessToken: getAccessToken,
    ensureAuthenticated: ensureAuthenticated,
    fetch: authedFetch,
    handleServerRejection: handleServerRejection,
  };
})();
