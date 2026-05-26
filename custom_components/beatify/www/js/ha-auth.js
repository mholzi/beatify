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

  // -- Android Companion App auth bridge (#1114, #1120 — rc5) --------------
  //
  // HA Companion ships two auth bridges, both documented under
  // developers.home-assistant.io/docs/frontend/external-authentication/ :
  //
  //   - externalAppV2 (Companion ≥ 2026.4.2, recommended): origin-checked
  //     via WebViewCompat.addWebMessageListener. JS → native:
  //       window.externalAppV2.postMessage(JSON.stringify({
  //         id, type: "getExternalAuth",
  //         payload: { callback: "externalAuthSetToken", force }
  //       }))
  //
  //   - externalApp (legacy V1): addJavascriptInterface direct method.
  //       window.externalApp.getExternalAuth(JSON.stringify({
  //         callback: "externalAuthSetToken", force
  //       }))
  //
  // Both bridges call back into a fixed global function:
  //   window.externalAuthSetToken(success: boolean,
  //                               payload?: {access_token, expires_in})
  //
  // The callback name has been whitelisted by the Companion app since the
  // security fix GHSA-7jp2-p2fw-mgvf (Android 2026.4.4, iOS 2026.4.5) —
  // any name other than "externalAuthSetToken" / "externalAuthRevokeToken"
  // is silently rejected before the native handler runs. Earlier RCs (rc2
  // legacy path, rc3 externalBus path) used randomised callback names and
  // the wrong channel respectively; both were silently dropped on the
  // 2026.4.4 build that @Dtrieb tested on, falling through to the cookie
  // fetch that returned 401.
  //
  // externalBus is a separate channel for HA-frontend ↔ native commands
  // (NFC, Matter, navigation). It has no `get_external_auth` command;
  // rc3's attempt to route auth through it was misdiagnosed.
  //
  // We install a single multiplexed receiver at window.externalAuthSetToken
  // and serialise requests through a FIFO queue. In practice refreshAccess
  // coalesces concurrent calls into one in-flight request, so the queue
  // stays shallow — the queue is defensive against a Companion build that
  // races multiple responses.

  function isAndroidCompanion() {
    var ua = (typeof navigator !== 'undefined' && navigator.userAgent) || '';
    if (/Android/i.test(ua) && /Home ?Assistant|HACompanion|Hass/i.test(ua)) {
      return true;
    }
    // Some Companion builds rewrite the UA in ways that don't match the
    // strings above. The injected JS bridge is a stronger signal than UA.
    return _hasCompanionAuthBridge();
  }

  function _hasCompanionAuthBridge() {
    if (
      typeof window.externalAppV2 !== 'undefined' &&
      window.externalAppV2 !== null &&
      typeof window.externalAppV2.postMessage === 'function'
    ) {
      return true;
    }
    if (
      typeof window.externalApp !== 'undefined' &&
      window.externalApp !== null &&
      typeof window.externalApp.getExternalAuth === 'function'
    ) {
      return true;
    }
    return false;
  }

  // #1131 / rc10: when HA Android Companion is detected, ALWAYS skip the OAuth
  // dance and rely on the server-side UA+RFC1918 bypass in companion_auth.py.
  //
  // History: rc8/rc9 limited the client-side skip to "bridge missing" — the
  // reasoning was that builds with a working bridge could still get a real
  // Bearer token. Field data (Logan-80, nelbs) showed that path is wrong:
  // recent Companion builds advertise the bridge but it either never replies
  // or replies with a token HA rejects. The bridge attempt then runs into a
  // 10s timeout (see _CompanionAuthBridge below) and falls through to a hard
  // OAuth redirect that Companion's WebView blocks with "Invalid redirect URI".
  //
  // Trade-off: builds where the bridge would have worked no longer get a
  // real Bearer token. Admin endpoints continue to function because the
  // server-side bypass authorises any UA-matching request from an RFC1918
  // address. No HA per-user identity is exposed in beatify's admin surface,
  // so dropping the per-user token has no functional consequence.
  function isCompanionBypassMode() {
    var ua = (typeof navigator !== 'undefined' && navigator.userAgent) || '';
    if (!/Android/i.test(ua)) return false;
    if (!/Home ?Assistant|HACompanion|Hass/i.test(ua)) return false;
    return true;
  }

  // -- multiplexed callback receiver ---------------------------------------

  var _authCbQueue = []; // FIFO of {resolve, reject, timeoutId}
  var _authCbInstalled = false;
  var _authMessageId = 0;
  var _bridgePathLogged = false;

  function _installAuthCallback() {
    if (_authCbInstalled) return;
    var prior =
      typeof window.externalAuthSetToken === 'function'
        ? window.externalAuthSetToken
        : null;
    window.externalAuthSetToken = function (success, payload) {
      var entry = _authCbQueue.shift();
      if (!entry) {
        // No pending request — forward to a prior handler if one was
        // installed (e.g. HA frontend on a page that also loaded it).
        // Normally Beatify pages don't load HA frontend so prior is null.
        if (prior) {
          try { prior(success, payload); } catch (e) { /* ignore */ }
        }
        return;
      }
      if (entry.timeoutId) {
        try { clearTimeout(entry.timeoutId); } catch (e) { /* ignore */ }
      }
      if (success && payload && payload.access_token) {
        entry.resolve(payload);
      } else {
        var msg =
          payload && (payload.message || payload.error)
            ? payload.message || payload.error
            : 'Companion getExternalAuth rejected';
        entry.reject(new Error(msg));
      }
    };
    _authCbInstalled = true;
  }

  function _enqueueAuthRequest() {
    _installAuthCallback();
    var entry = { resolve: null, reject: null, timeoutId: null };
    entry.promise = new Promise(function (resolve, reject) {
      entry.resolve = resolve;
      entry.reject = reject;
    });
    entry.timeoutId = setTimeout(function () {
      var idx = _authCbQueue.indexOf(entry);
      if (idx >= 0) {
        _authCbQueue.splice(idx, 1);
        entry.reject(new Error('Companion getExternalAuth timeout (10s)'));
      }
    }, 10000);
    _authCbQueue.push(entry);
    return entry;
  }

  function _abortAuthRequest(entry, err) {
    var idx = _authCbQueue.indexOf(entry);
    if (idx >= 0) _authCbQueue.splice(idx, 1);
    if (entry.timeoutId) {
      try { clearTimeout(entry.timeoutId); } catch (e) { /* ignore */ }
    }
    entry.reject(err);
  }

  function _logBridgePathOnce(path) {
    if (_bridgePathLogged) return;
    _bridgePathLogged = true;
    try {
      console.log(
        '[BeatifyAuth] Companion bridge: ' + path +
        ' (ua: ' + ((navigator && navigator.userAgent) || 'unknown') + ')'
      );
    } catch (e) { /* ignore */ }
  }

  // Try modern externalAppV2 first, fall back to legacy externalApp.
  function getCompanionAuthToken(force) {
    var hasV2 =
      typeof window.externalAppV2 !== 'undefined' &&
      window.externalAppV2 !== null &&
      typeof window.externalAppV2.postMessage === 'function';
    var hasV1 =
      typeof window.externalApp !== 'undefined' &&
      window.externalApp !== null &&
      typeof window.externalApp.getExternalAuth === 'function';

    if (hasV2) {
      _logBridgePathOnce('externalAppV2.postMessage');
      var entry = _enqueueAuthRequest();
      _authMessageId += 1;
      try {
        window.externalAppV2.postMessage(
          JSON.stringify({
            id: _authMessageId,
            type: 'getExternalAuth',
            payload: {
              callback: 'externalAuthSetToken',
              force: !!force,
            },
          })
        );
      } catch (e) {
        _abortAuthRequest(entry, e);
      }
      return entry.promise.catch(function (err) {
        // V2 failed at runtime (sync throw, timeout, or native reject).
        // Try legacy V1 if it's also exposed — some Companion builds
        // expose both during the transition.
        if (hasV1) {
          console.warn(
            '[BeatifyAuth] externalAppV2 failed, falling back to legacy externalApp.getExternalAuth:',
            err && err.message ? err.message : err
          );
          return _sendViaLegacyGetExternalAuth(force);
        }
        throw err;
      });
    }
    if (hasV1) {
      _logBridgePathOnce('externalApp.getExternalAuth (legacy V1)');
      return _sendViaLegacyGetExternalAuth(force);
    }
    return Promise.reject(
      new Error('No Companion auth bridge method available')
    );
  }

  function _sendViaLegacyGetExternalAuth(force) {
    var entry = _enqueueAuthRequest();
    try {
      window.externalApp.getExternalAuth(
        JSON.stringify({
          callback: 'externalAuthSetToken',
          force: !!force,
        })
      );
    } catch (e) {
      _abortAuthRequest(entry, e);
    }
    return entry.promise;
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
    // rc6 (#1120 diagnostics): log token characteristics on each bridge
    // response. If `force: true` is honoured by Companion, the prefix
    // should change between successive calls; if it's the same prefix
    // every time, force is being silently ignored (H1 confirmed) and
    // we'll need a Companion-side fix.
    try {
      console.log(
        '[BeatifyAuth] Bridge token received (len=' +
        (payload.access_token ? payload.access_token.length : 0) +
        ', prefix=' +
        (payload.access_token
          ? String(payload.access_token).slice(0, 12)
          : 'null') +
        ', expires_in=' + expiresIn + ')'
      );
    } catch (e) { /* ignore */ }
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
   *
   * #1153: In Companion bypass mode the server authenticates via UA+RFC1918,
   * not a Bearer token. Calling refreshAccess() here would attempt the
   * Companion bridge (isAndroidCompanion() && _hasCompanionAuthBridge()), which
   * either never replies or returns a token HA's async_validate_access_token
   * rejects. admin_connect then receives ERR_UNAUTHORIZED, the recovery loop
   * exhausts, and the user sees the "unauthorized message". Return null
   * immediately so connectAdminWebSocket() sends ha_token: null and the server
   * falls through to is_companion_trusted_meta (UA+RFC1918 accept).
   */
  function getAccessToken() {
    if (isCompanionBypassMode()) return Promise.resolve(null);
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
   *
   * rc12 (#1131): when the page is running inside HA Android Companion's
   * WebView and `isCompanionBypassMode()` told `init()` to skip OAuth,
   * there is no access token to obtain — and calling `login()` here would
   * navigate to `/auth/authorize`, which Companion's WebView blocks with
   * "Invalid redirect URI" (the exact bug rc10 worked around for `init()`).
   * Resolve with `null` instead so callers can still send their WS / fetch
   * with no `ha_token`; the server-side bypass in `companion_auth.py`
   * accepts those requests on the UA+RFC1918 signature.
   *
   * Without this rc11 admin → "join the game as host" hung forever on
   * Android Companion: `admin.js:2562` awaits this function before sending
   * the WS join, so the WS upgrade fired (admin already had a socket open)
   * but the join message was never enqueued and `[WS-Debug] join` never
   * logged — the missing data point that surfaced the bug.
   */
  function ensureAuthenticated() {
    if (isCompanionBypassMode()) {
      return Promise.resolve(null);
    }
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
    if (isCompanionBypassMode()) {
      // Server authorizes via UA + RFC1918; sending a Bearer token would just
      // hit Path 1 of is_authorized_http (which would 401 since we have no
      // token to send) before falling through to the Companion path. Cleaner
      // to skip the header entirely.
      return fetch(url, opts);
    }
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
    if (isCompanionBypassMode()) {
      // No OAuth, no bridge — the server-side companion_auth.py grants
      // access via UA + RFC1918 detection. Skipping init() avoids the
      // /auth/authorize redirect that lands Companion users on the
      // "Invalid redirect URI" error page (#1131).
      try {
        console.info(
          '[BeatifyAuth] Companion bypass mode — server authorizes by UA+local-net'
        );
      } catch (e) { /* ignore */ }
      return Promise.resolve(true);
    }
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
    isCompanionBypassMode: isCompanionBypassMode,
  };
})();
