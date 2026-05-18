/**
 * Beatify — Home Assistant OAuth2 client (#998)
 *
 * Standalone, dependency-free auth helper shared by the admin console and the
 * "playing host" path on the player page. Implements Home Assistant's
 * IndieAuth-style OAuth2 flow so a host authenticates as a real HA user
 * before any admin action is allowed.
 *
 * Why this exists: /beatify/admin and the game-control endpoints used to be
 * wide open — anyone who could reach Home Assistant could host/control a game.
 * Now every admin REST call carries an HA bearer token and every admin
 * WebSocket message carries `ha_token`; the server rejects anything without a
 * valid HA login.
 *
 * Normal players never touch this module — joining /beatify/play stays
 * frictionless. It is only invoked on the admin page (on load) and on the
 * player page when someone claims the host role.
 *
 * Exposes `window.BeatifyAuth`.
 */
(function () {
  'use strict';

  // localStorage survives tab close so a host does not re-login every session.
  var K_ACCESS = 'beatify_ha_access';
  var K_REFRESH = 'beatify_ha_refresh';
  var K_EXPIRES = 'beatify_ha_expires';
  // sessionStorage: CSRF state lives only for the duration of one redirect.
  var K_STATE = 'beatify_ha_oauth_state';

  // Refresh a little early so a request never races the expiry boundary.
  var EXPIRY_MARGIN_MS = 30000;

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
    // The page that initiated login (/beatify/admin or /beatify/play).
    return origin() + window.location.pathname;
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

  // -- token storage -------------------------------------------------------

  function storeTokens(resp) {
    try {
      if (resp.access_token) localStorage.setItem(K_ACCESS, resp.access_token);
      // The refresh_token is only returned by the authorization_code grant,
      // not by a refresh — keep the existing one when refreshing.
      if (resp.refresh_token) localStorage.setItem(K_REFRESH, resp.refresh_token);
      var ttl = (resp.expires_in || 1800) * 1000;
      localStorage.setItem(K_EXPIRES, String(Date.now() + ttl - EXPIRY_MARGIN_MS));
    } catch (e) {
      /* private-mode / storage disabled — auth simply won't persist */
    }
  }

  function clearTokens() {
    try {
      localStorage.removeItem(K_ACCESS);
      localStorage.removeItem(K_REFRESH);
      localStorage.removeItem(K_EXPIRES);
    } catch (e) {
      /* ignore */
    }
  }

  function storedAccess() {
    try {
      return localStorage.getItem(K_ACCESS);
    } catch (e) {
      return null;
    }
  }
  function storedRefresh() {
    try {
      return localStorage.getItem(K_REFRESH);
    } catch (e) {
      return null;
    }
  }
  function accessFresh() {
    try {
      var exp = parseInt(localStorage.getItem(K_EXPIRES) || '0', 10);
      return !!storedAccess() && Date.now() < exp;
    } catch (e) {
      return false;
    }
  }

  // -- OAuth2 token endpoint ----------------------------------------------

  function postToken(params) {
    var body = Object.keys(params)
      .map(function (k) {
        return encodeURIComponent(k) + '=' + encodeURIComponent(params[k]);
      })
      .join('&');
    return fetch(origin() + '/auth/token', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: body,
    }).then(function (resp) {
      if (!resp.ok) {
        return resp.text().then(function (t) {
          throw new Error('HA token endpoint ' + resp.status + ': ' + t);
        });
      }
      return resp.json();
    });
  }

  function exchangeCode(code) {
    return postToken({
      grant_type: 'authorization_code',
      code: code,
      client_id: clientId(),
    }).then(function (resp) {
      storeTokens(resp);
      return resp.access_token;
    });
  }

  // Coalesce concurrent refreshes into a single in-flight request.
  var refreshInFlight = null;

  function refreshAccess() {
    if (refreshInFlight) return refreshInFlight;
    var rt = storedRefresh();
    if (!rt) return Promise.resolve(null);
    refreshInFlight = postToken({
      grant_type: 'refresh_token',
      refresh_token: rt,
      client_id: clientId(),
    })
      .then(function (resp) {
        storeTokens(resp);
        return resp.access_token || null;
      })
      .catch(function (err) {
        // Refresh token revoked / HA restarted with a wiped session — the
        // only recovery is a fresh login.
        console.warn('[BeatifyAuth] refresh failed:', err);
        clearTokens();
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

  // Detect & consume the ?code=&state= redirect HA sends back to us.
  function handleRedirectCallback() {
    var params = new URLSearchParams(window.location.search);
    var code = params.get('code');
    var state = params.get('state');
    if (!code) return Promise.resolve(false);

    var expected = null;
    try {
      expected = sessionStorage.getItem(K_STATE);
      sessionStorage.removeItem(K_STATE);
    } catch (e) {
      /* ignore */
    }
    if (expected && state !== expected) {
      console.warn('[BeatifyAuth] OAuth state mismatch — ignoring callback');
      stripQuery();
      return Promise.resolve(false);
    }

    return exchangeCode(code)
      .then(function () {
        stripQuery();
        return true;
      })
      .catch(function (err) {
        console.error('[BeatifyAuth] code exchange failed:', err);
        stripQuery();
        return false;
      });
  }

  // Remove ?code/&state/&auth_callback from the address bar after exchange.
  function stripQuery() {
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
   * Return a valid access token, refreshing if needed. Resolves null when the
   * user is not logged in (no tokens, or refresh failed).
   */
  function getAccessToken() {
    if (accessFresh()) return Promise.resolve(storedAccess());
    return refreshAccess();
  }

  /** True if a usable token exists or can be obtained without a redirect. */
  function isAuthenticated() {
    return accessFresh() || !!storedRefresh();
  }

  /**
   * Guarantee an access token. If none can be obtained this navigates away to
   * the HA login page and the returned promise never resolves.
   */
  function ensureAuthenticated() {
    return getAccessToken().then(function (token) {
      if (token) return token;
      login();
      return new Promise(function () {}); // navigating away
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
    return handleRedirectCallback().then(function () {
      if (isAuthenticated()) return true;
      if (options.requireAuth) {
        login();
        return new Promise(function () {});
      }
      return false;
    });
  }

  window.BeatifyAuth = {
    init: init,
    login: login,
    logout: clearTokens,
    isAuthenticated: isAuthenticated,
    getAccessToken: getAccessToken,
    ensureAuthenticated: ensureAuthenticated,
    fetch: authedFetch,
  };
})();
