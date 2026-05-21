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
    // rc15: redirect_uri is the server-side callback view, not the page.
    // The view performs the code exchange and sets cookies before the
    // browser ever reaches the admin page again.
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

  // -- silent refresh via /beatify/auth/refresh ----------------------------

  // Coalesce concurrent refreshes into a single in-flight request.
  var refreshInFlight = null;

  function refreshAccess() {
    if (refreshInFlight) return refreshInFlight;
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

  function login() {
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
