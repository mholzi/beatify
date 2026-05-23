/**
 * Unit tests for ha-auth.js — rc15 cookie-based session.
 *
 * rc15 moves the OAuth code exchange and refresh server-side because
 * Safari 18 silently refuses certain same-origin POSTs from the OAuth-
 * callback page state. ha-auth.js now never POSTs to an auth endpoint:
 *
 *   - The access token lives in a JS-readable `beatify_access` cookie
 *     (JSON {access_token, expires_at}) set by BeatifyAuthCallbackView.
 *   - The refresh token lives in an HttpOnly `beatify_refresh` cookie
 *     that JS can never read; only BeatifyAuthRefreshView reads it.
 *   - Silent refresh is a fetch GET to /beatify/auth/refresh.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';

const __dirname = dirname(fileURLToPath(import.meta.url));
const SRC_PATH = join(__dirname, '..', 'ha-auth.js');
const SRC = readFileSync(SRC_PATH, 'utf8');

function loadHaAuth({
    fetchFn,
    cookie = '',
    localStorageData = {},
    userAgent = '',
    externalApp = null,
} = {}) {
    const storage = (initial) => {
        const map = new Map(Object.entries(initial));
        return {
            getItem: (k) => (map.has(k) ? map.get(k) : null),
            setItem: (k, v) => { map.set(k, String(v)); },
            removeItem: (k) => { map.delete(k); },
            _map: map,
        };
    };
    const ls = storage(localStorageData);
    const ss = storage({});

    // Mutable cookie jar — JS reads via document.cookie, our shim allows
    // tests to seed an initial value and inspect mutations. Honors
    // Max-Age=0 by actually removing the entry, matching browsers.
    const cookieJar = { value: cookie };
    const documentShim = {
        title: 'test',
        get cookie() { return cookieJar.value; },
        set cookie(v) {
            const name = v.split('=')[0];
            const isDelete = /(?:^|;)\s*Max-Age=0\b/i.test(v);
            const remaining = cookieJar.value
                .split(';')
                .map((p) => p.replace(/^\s+/, ''))
                .filter((p) => p && !p.startsWith(name + '='));
            if (!isDelete) remaining.push(v.split(';')[0]);
            cookieJar.value = remaining.join('; ');
        },
    };

    const sandboxWindow = {
        location: {
            origin: 'https://ha.example',
            pathname: '/beatify/admin',
            search: '',
            hash: '',
            protocol: 'https:',
            replace: (url) => { sandboxWindow.location._lastReplace = url; },
        },
        localStorage: ls,
        sessionStorage: ss,
        crypto: { getRandomValues: (buf) => { for (let i = 0; i < buf.length; i++) buf[i] = i; return buf; } },
        history: { replaceState: () => {} },
        externalApp: externalApp || undefined,
    };
    const navigatorShim = { userAgent: userAgent };
    const ctx = {
        window: sandboxWindow,
        document: documentShim,
        navigator: navigatorShim,
        localStorage: ls,
        sessionStorage: ss,
        location: sandboxWindow.location,
        console,
        fetch: fetchFn,
        URLSearchParams,
        FormData,
        Promise,
        Date,
        Array,
        Object,
        Error,
        TypeError,
        parseInt,
        encodeURIComponent,
        decodeURIComponent,
        setTimeout,
        clearTimeout,
        Math,
        JSON,
    };
    vm.createContext(ctx);
    vm.runInContext(SRC, ctx);
    return {
        BeatifyAuth: sandboxWindow.BeatifyAuth,
        cookieJar,
        localStorage: ls,
        sandboxWindow,
    };
}

function cookieFor(name, payload) {
    return name + '=' + encodeURIComponent(JSON.stringify(payload));
}

describe('cookie session', () => {
    it('isAuthenticated() reads access_token + expires_at from beatify_access cookie', () => {
        const farFuture = Math.floor(Date.now() / 1000) + 3600;
        const { BeatifyAuth } = loadHaAuth({
            cookie: cookieFor('beatify_access', { access_token: 'abc', expires_at: farFuture }),
        });
        expect(BeatifyAuth.isAuthenticated()).toBe(true);
    });

    it('isAuthenticated() returns false when expires_at is in the past', () => {
        const farPast = Math.floor(Date.now() / 1000) - 60;
        const { BeatifyAuth } = loadHaAuth({
            cookie: cookieFor('beatify_access', { access_token: 'abc', expires_at: farPast }),
        });
        expect(BeatifyAuth.isAuthenticated()).toBe(false);
    });

    it('getAccessToken() returns the cookied token without hitting the network', async () => {
        const farFuture = Math.floor(Date.now() / 1000) + 3600;
        const fetchCalls = [];
        const { BeatifyAuth } = loadHaAuth({
            cookie: cookieFor('beatify_access', { access_token: 'cached', expires_at: farFuture }),
            fetchFn: async (...args) => { fetchCalls.push(args); throw new Error('should not fetch'); },
        });
        const token = await BeatifyAuth.getAccessToken();
        expect(token).toBe('cached');
        expect(fetchCalls).toHaveLength(0);
    });

    it('clears legacy localStorage keys on init (migration from rc11–rc14)', async () => {
        // With no fresh cookie, init() falls through to refreshAccess()
        // which calls fetch — stub it so the test doesn't hit the network.
        const fetchFn = async () => ({ ok: false, status: 401, json: async () => ({}) });
        const { BeatifyAuth, localStorage } = loadHaAuth({
            fetchFn,
            localStorageData: {
                beatify_ha_access: 'legacy-access',
                beatify_ha_refresh: 'legacy-refresh',
                beatify_ha_expires: '9999999999999',
            },
        });
        await BeatifyAuth.init({ requireAuth: false });
        expect(localStorage.getItem('beatify_ha_access')).toBeNull();
        expect(localStorage.getItem('beatify_ha_refresh')).toBeNull();
        expect(localStorage.getItem('beatify_ha_expires')).toBeNull();
    });
});

describe('refreshAccess via /beatify/auth/refresh', () => {
    it('GETs the refresh endpoint and returns the new token on 200', async () => {
        const fetchCalls = [];
        const fetchFn = async (url, opts) => {
            fetchCalls.push({ url, opts });
            return {
                ok: true,
                status: 200,
                json: async () => ({ access_token: 'fresh', expires_in: 1800 }),
            };
        };
        const { BeatifyAuth } = loadHaAuth({ fetchFn });
        const token = await BeatifyAuth.getAccessToken();
        expect(token).toBe('fresh');
        expect(fetchCalls).toHaveLength(1);
        expect(fetchCalls[0].url).toBe('https://ha.example/beatify/auth/refresh');
        expect(fetchCalls[0].opts.method).toBe('GET');
        expect(fetchCalls[0].opts.credentials).toBe('same-origin');
    });

    it('resolves null on 401 (refresh cookie revoked) so init() can redirect to login', async () => {
        const fetchFn = async () => ({
            ok: false,
            status: 401,
            json: async () => ({ error: 'no_refresh_token' }),
        });
        const { BeatifyAuth } = loadHaAuth({ fetchFn });
        const token = await BeatifyAuth.getAccessToken();
        expect(token).toBeNull();
    });

    it('coalesces concurrent refresh calls into a single in-flight request', async () => {
        let calls = 0;
        const fetchFn = async () => {
            calls += 1;
            // Resolve after a microtask so the second call piggybacks.
            await new Promise((r) => setTimeout(r, 0));
            return { ok: true, status: 200, json: async () => ({ access_token: 't', expires_in: 1800 }) };
        };
        const { BeatifyAuth } = loadHaAuth({ fetchFn });
        const [a, b] = await Promise.all([
            BeatifyAuth.getAccessToken(),
            BeatifyAuth.getAccessToken(),
        ]);
        expect(a).toBe('t');
        expect(b).toBe('t');
        expect(calls).toBe(1);
    });
});

describe('init() auth callback handling', () => {
    it('on ?auth_error= clears access cookie and redirects to login when requireAuth', async () => {
        // Pre-seed a cookie so we can check it gets cleared.
        const farFuture = Math.floor(Date.now() / 1000) + 3600;
        const { BeatifyAuth, cookieJar, sandboxWindow } = loadHaAuth({
            cookie: cookieFor('beatify_access', { access_token: 'stale', expires_at: farFuture }),
            fetchFn: async () => ({ ok: false, status: 401, json: async () => ({}) }),
        });
        // Simulate the post-callback redirect arrival.
        sandboxWindow.location.search = '?auth_error=exchange_failed';
        // requireAuth: true triggers a login() redirect, which never resolves —
        // so race it with a microtask sentinel.
        const result = await Promise.race([
            BeatifyAuth.init({ requireAuth: true }),
            new Promise((r) => setTimeout(() => r('LOGIN_NAVIGATED'), 5)),
        ]);
        expect(result).toBe('LOGIN_NAVIGATED');
        // login() called window.location.replace
        expect(sandboxWindow.location._lastReplace).toContain('/auth/authorize');
        // Stale access cookie cleared
        expect(cookieJar.value).not.toContain('beatify_access=');
    });

    it('on ?auth_state= matching sessionStorage trusts the freshly-set cookie', async () => {
        const farFuture = Math.floor(Date.now() / 1000) + 3600;
        const { BeatifyAuth, sandboxWindow } = loadHaAuth({
            cookie: cookieFor('beatify_access', { access_token: 'freshly-set', expires_at: farFuture }),
        });
        // Frontend stored this state before redirecting to /auth/authorize.
        sandboxWindow.sessionStorage.setItem('beatify_ha_oauth_state', 'state-abc');
        sandboxWindow.location.search = '?auth_state=state-abc';

        const ok = await BeatifyAuth.init({ requireAuth: true });
        expect(ok).toBe(true);
        expect(await BeatifyAuth.getAccessToken()).toBe('freshly-set');
    });

    it('on ?auth_state= mismatch wipes the cookie and re-logins', async () => {
        const farFuture = Math.floor(Date.now() / 1000) + 3600;
        const { BeatifyAuth, cookieJar, sandboxWindow } = loadHaAuth({
            cookie: cookieFor('beatify_access', { access_token: 'maybe-injected', expires_at: farFuture }),
        });
        sandboxWindow.sessionStorage.setItem('beatify_ha_oauth_state', 'expected');
        sandboxWindow.location.search = '?auth_state=attacker-supplied';

        const result = await Promise.race([
            BeatifyAuth.init({ requireAuth: true }),
            new Promise((r) => setTimeout(() => r('LOGIN_NAVIGATED'), 5)),
        ]);
        expect(result).toBe('LOGIN_NAVIGATED');
        expect(cookieJar.value).not.toContain('beatify_access=');
    });
});

describe('Android Companion auth bridge (#1114 rc3)', () => {
    const COMPANION_UA =
        'Mozilla/5.0 (Linux; Android 16; Pixel 7 Pro) AppleWebKit/537.36 ' +
        '(KHTML, like Gecko) Chrome/Mobile Safari Home Assistant/2026.4.4-full';

    function externalBusBridge({ respondWithToken = 'companion-fresh', respondSuccess = true, expiresIn = 1800 } = {}) {
        const calls = [];
        const bridge = {
            calls,
            externalApp: {
                externalBus(json) {
                    calls.push(JSON.parse(json));
                    // Simulate the native side calling window.externalBus
                    // back on a microtask, matching the async nature of the
                    // real Companion JS↔Kotlin bridge.
                    const parsed = JSON.parse(json);
                    setTimeout(() => {
                        if (typeof bridge.window?.externalBus !== 'function') return;
                        bridge.window.externalBus(
                            JSON.stringify({
                                type: 'result',
                                id: parsed.id,
                                success: respondSuccess,
                                result: respondSuccess
                                    ? { access_token: respondWithToken, expires_in: expiresIn }
                                    : null,
                                error: respondSuccess ? null : { message: 'auth_denied' },
                            })
                        );
                    }, 0);
                },
            },
        };
        return bridge;
    }

    function legacyGetExternalAuthBridge({ respondWithToken = 'legacy-fresh', respondSuccess = true, expiresIn = 1800 } = {}) {
        const calls = [];
        const bridge = {
            calls,
            externalApp: {
                getExternalAuth(json) {
                    calls.push(JSON.parse(json));
                    const parsed = JSON.parse(json);
                    setTimeout(() => {
                        const fn = bridge.window?.[parsed.callback];
                        if (typeof fn !== 'function') return;
                        if (respondSuccess) {
                            fn(true, { access_token: respondWithToken, expires_in: expiresIn });
                        } else {
                            fn(false, { message: 'auth_denied' });
                        }
                    }, 0);
                },
            },
        };
        return bridge;
    }

    it('refreshAccess() uses externalBus bridge on modern Companion (no /beatify/auth/refresh fetch)', async () => {
        const bridge = externalBusBridge({ respondWithToken: 'companion-bus-token' });
        const fetchFn = async () => { throw new Error('should not fetch — Companion path active'); };
        const { BeatifyAuth, sandboxWindow, cookieJar } = loadHaAuth({
            fetchFn,
            userAgent: COMPANION_UA,
            externalApp: bridge.externalApp,
        });
        bridge.window = sandboxWindow;
        const token = await BeatifyAuth.getAccessToken();
        expect(token).toBe('companion-bus-token');
        // The cookie was planted by _setSessionCookieFromCompanion.
        expect(cookieJar.value).toContain('beatify_access=');
        // The bridge was called with a get_external_auth command.
        expect(bridge.calls).toHaveLength(1);
        expect(bridge.calls[0].type).toBe('command');
        expect(bridge.calls[0].command).toBe('get_external_auth');
        expect(bridge.calls[0].payload.force).toBe(true);
    });

    it('refreshAccess() falls back to legacy getExternalAuth when only that method is exposed', async () => {
        const bridge = legacyGetExternalAuthBridge({ respondWithToken: 'companion-legacy-token' });
        const fetchFn = async () => { throw new Error('should not fetch — Companion legacy path active'); };
        const { BeatifyAuth, sandboxWindow, cookieJar } = loadHaAuth({
            fetchFn,
            userAgent: COMPANION_UA,
            externalApp: bridge.externalApp,
        });
        bridge.window = sandboxWindow;
        const token = await BeatifyAuth.getAccessToken();
        expect(token).toBe('companion-legacy-token');
        expect(cookieJar.value).toContain('beatify_access=');
        expect(bridge.calls).toHaveLength(1);
        expect(typeof bridge.calls[0].callback).toBe('string');
        expect(bridge.calls[0].force).toBe(true);
    });

    it('falls back from failing externalBus to legacy getExternalAuth when both are present', async () => {
        // externalBus rejects, getExternalAuth succeeds. Should land on the legacy token.
        const calls = { bus: [], legacy: [] };
        const bridge = {
            externalApp: {
                externalBus(json) {
                    const parsed = JSON.parse(json);
                    calls.bus.push(parsed);
                    setTimeout(() => {
                        sandbox.externalBus(
                            JSON.stringify({
                                type: 'result',
                                id: parsed.id,
                                success: false,
                                error: { message: 'bus_failure' },
                            })
                        );
                    }, 0);
                },
                getExternalAuth(json) {
                    const parsed = JSON.parse(json);
                    calls.legacy.push(parsed);
                    setTimeout(() => {
                        const fn = sandbox[parsed.callback];
                        if (typeof fn === 'function') {
                            fn(true, { access_token: 'fallback-token', expires_in: 1800 });
                        }
                    }, 0);
                },
            },
        };
        const fetchFn = async () => { throw new Error('should not fetch'); };
        const { BeatifyAuth, sandboxWindow } = loadHaAuth({
            fetchFn,
            userAgent: COMPANION_UA,
            externalApp: bridge.externalApp,
        });
        const sandbox = sandboxWindow;
        const token = await BeatifyAuth.getAccessToken();
        expect(token).toBe('fallback-token');
        expect(calls.bus).toHaveLength(1);
        expect(calls.legacy).toHaveLength(1);
    });

    it('detects Companion via injected externalApp even when UA does not match', async () => {
        // No Companion UA, but externalApp is injected — should still take the bridge path.
        const bridge = externalBusBridge({ respondWithToken: 'ua-fallback-token' });
        const fetchFn = async () => { throw new Error('should not fetch'); };
        const { BeatifyAuth, sandboxWindow } = loadHaAuth({
            fetchFn,
            userAgent: 'Mozilla/5.0 (Linux; Android 16) Chrome/Mobile Safari', // no "Home Assistant"
            externalApp: bridge.externalApp,
        });
        bridge.window = sandboxWindow;
        const token = await BeatifyAuth.getAccessToken();
        expect(token).toBe('ua-fallback-token');
    });

    it('still uses /beatify/auth/refresh when no Companion bridge is present (regression guard)', async () => {
        const fetchCalls = [];
        const fetchFn = async (url) => {
            fetchCalls.push(url);
            return { ok: true, status: 200, json: async () => ({ access_token: 'web-token', expires_in: 1800 }) };
        };
        const { BeatifyAuth } = loadHaAuth({
            fetchFn,
            userAgent: 'Mozilla/5.0 (Macintosh) Safari/605.1.15', // desktop browser, no Companion
        });
        const token = await BeatifyAuth.getAccessToken();
        expect(token).toBe('web-token');
        expect(fetchCalls[0]).toBe('https://ha.example/beatify/auth/refresh');
    });
});

describe('login() OAuth redirect', () => {
    it('uses /beatify/auth/callback as redirect_uri (rc18: restored from rc15)', () => {
        // rc16/rc17 routed redirect_uri at the page URL with a JS-bounce
        // hop to dodge HA Companion App's webview interception. rc18
        // restores rc15's clean architecture because the rc17 launcher's
        // target="_blank" already opens Beatify in external Safari
        // outside the Companion webview, so Companion's interception is
        // no longer reachable. Restoring the direct server-side
        // callback removes the extra navigation hop that broke Safari 18.
        const { BeatifyAuth, sandboxWindow } = loadHaAuth({});
        BeatifyAuth.login();
        const url = sandboxWindow.location._lastReplace;
        expect(url).toContain('/auth/authorize');
        expect(url).toContain('response_type=code');
        expect(url).toContain(
            'redirect_uri=' + encodeURIComponent('https://ha.example/beatify/auth/callback')
        );
        // client_id is origin + /beatify/ (unchanged across RCs).
        expect(url).toContain(
            'client_id=' + encodeURIComponent('https://ha.example/beatify/')
        );
    });
});
