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
    externalAppV2 = null,
    sessionStorageData = {},
    withDomBody = false,
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
    const ss = storage(sessionStorageData);

    // Mutable cookie jar — JS reads via document.cookie, our shim allows
    // tests to seed an initial value and inspect mutations. Honors
    // Max-Age=0 by actually removing the entry, matching browsers.
    const cookieJar = { value: cookie };
    // Minimal DOM shim so #1394's _renderAuthError() can mount its error card.
    // Only created when withDomBody is set; otherwise document has no body and
    // _renderAuthError() short-circuits (matching a not-yet-painted page).
    let bodyShim = null;
    if (withDomBody) {
        const makeEl = () => {
            const el = {
                style: { cssText: '' },
                children: [],
                _listeners: {},
                setAttribute() {},
                set innerHTML(html) { this._html = html; },
                get innerHTML() { return this._html || ''; },
                appendChild(c) { this.children.push(c); return c; },
                addEventListener(ev, fn) { this._listeners[ev] = fn; },
                querySelector() { return makeEl(); },
            };
            return el;
        };
        bodyShim = makeEl();
    }
    const documentShim = {
        title: 'test',
        body: bodyShim,
        createElement: bodyShim ? () => ({
            style: { cssText: '' },
            _listeners: {},
            id: '',
            setAttribute() {},
            set innerHTML(html) { this._html = html; },
            get innerHTML() { return this._html || ''; },
            appendChild() {},
            querySelector() { return { addEventListener: () => {} }; },
        }) : undefined,
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
        externalAppV2: externalAppV2 || undefined,
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
        sessionStorage: ss,
        documentShim,
        bodyShim,
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

describe('bounded login loop on persistent OAuth failure (#1394)', () => {
    const K = 'beatify_login_attempts';

    function failingCallback(attemptsSoFar) {
        // Each "page load" arrives back from the server with ?auth_error= and
        // carries forward the attempt counter in sessionStorage (which survives
        // the redirect in a real browser).
        return loadHaAuth({
            fetchFn: async () => ({ ok: false, status: 401, json: async () => ({}) }),
            sessionStorageData: attemptsSoFar > 0 ? { [K]: String(attemptsSoFar) } : {},
            withDomBody: true,
        });
    }

    it('keeps redirecting while under the attempt budget, incrementing the counter', async () => {
        // First failed callback: counter 0 -> 1, still redirects.
        const ctx = failingCallback(0);
        ctx.sandboxWindow.location.search = '?auth_error=exchange_failed';
        const result = await Promise.race([
            ctx.BeatifyAuth.init({ requireAuth: true }),
            new Promise((r) => setTimeout(() => r('LOGIN_NAVIGATED'), 5)),
        ]);
        expect(result).toBe('LOGIN_NAVIGATED');
        expect(ctx.sandboxWindow.location._lastReplace).toContain('/auth/authorize');
        expect(ctx.sessionStorage.getItem(K)).toBe('1');
    });

    it('stops redirecting and renders an error once the budget is exhausted', async () => {
        // Arrive back on the page with the counter already at the max (3 prior
        // failed login redirects). The 4th callback must NOT redirect again.
        const ctx = failingCallback(3);
        ctx.sandboxWindow.location.search = '?auth_error=exchange_failed';
        const result = await ctx.BeatifyAuth.init({ requireAuth: true });
        // init() resolves (does NOT hang on a never-resolving login redirect).
        expect(result).toBe(false);
        // No new /auth/authorize redirect was issued.
        expect(ctx.sandboxWindow.location._lastReplace).toBeUndefined();
        // A user-visible error card was mounted instead of looping.
        expect(ctx.bodyShim.children.length).toBe(1);
    });

    it('drives the full loop to a bounded stop (no infinite redirect)', async () => {
        // Simulate consecutive page loads, carrying the counter forward each
        // time exactly as a real browser would across the redirect bounce.
        let attempts = 0;
        let redirects = 0;
        for (let i = 0; i < 10; i++) {
            const ctx = failingCallback(attempts);
            ctx.sandboxWindow.location.search = '?auth_error=exchange_failed';
            const result = await Promise.race([
                ctx.BeatifyAuth.init({ requireAuth: true }),
                new Promise((r) => setTimeout(() => r('LOGIN_NAVIGATED'), 5)),
            ]);
            const next = ctx.sessionStorage.getItem(K);
            attempts = next ? parseInt(next, 10) : attempts;
            if (result === 'LOGIN_NAVIGATED') redirects += 1;
            else break; // budget exhausted — loop terminated
        }
        // Loop is bounded: at most MAX_LOGIN_ATTEMPTS (3) redirects, then stop.
        expect(redirects).toBe(3);
    });

    it('resets the counter after a successful callback so later sessions get a fresh budget', async () => {
        const farFuture = Math.floor(Date.now() / 1000) + 3600;
        const ctx = loadHaAuth({
            cookie: cookieFor('beatify_access', { access_token: 'freshly-set', expires_at: farFuture }),
            sessionStorageData: { [K]: '2' }, // two prior failures
            withDomBody: true,
        });
        ctx.sandboxWindow.sessionStorage.setItem('beatify_ha_oauth_state', 'state-ok');
        ctx.sandboxWindow.location.search = '?auth_state=state-ok';
        const ok = await ctx.BeatifyAuth.init({ requireAuth: true });
        expect(ok).toBe(true);
        // Counter cleared on the successful callback.
        expect(ctx.sessionStorage.getItem(K)).toBeNull();
    });

    it('also bounds the refresh-failed branch (no callback, refresh keeps failing)', async () => {
        // No ?auth_error in the URL: init() falls through to refreshAccess(),
        // which 401s. With the counter at max, it must stop instead of looping.
        const ctx = loadHaAuth({
            fetchFn: async () => ({ ok: false, status: 401, json: async () => ({}) }),
            sessionStorageData: { [K]: '3' },
            withDomBody: true,
        });
        const result = await ctx.BeatifyAuth.init({ requireAuth: true });
        expect(result).toBe(false);
        expect(ctx.sandboxWindow.location._lastReplace).toBeUndefined();
    });
});

describe('Android Companion auth bridge (#1114, #1120 — rc5)', () => {
    const COMPANION_UA =
        'Mozilla/5.0 (Linux; Android 16; Pixel 7 Pro) AppleWebKit/537.36 ' +
        '(KHTML, like Gecko) Chrome/Mobile Safari Home Assistant/2026.4.4-full';

    // UA that has "Android" (so isAndroidCompanion() returns true via bridge
    // detection) but NOT "Home Assistant" (so isCompanionBypassMode() = false).
    // Bridge tests use this UA so they exercise the bridge code path — the full
    // COMPANION_UA triggers bypass mode (#1153) and short-circuits getAccessToken()
    // before the bridge is consulted.
    const ANDROID_NO_HA_UA =
        'Mozilla/5.0 (Linux; Android 16; Pixel 7 Pro) Chrome/Mobile Safari/537.36';

    // externalAppV2 is the modern, origin-checked Companion bridge added in
    // 2026.4.2 alongside the security fix GHSA-7jp2-p2fw-mgvf. JS → native:
    // postMessage({type:"getExternalAuth"}). Native → JS: invokes the fixed
    // global function window.externalAuthSetToken(success, payload).
    function externalAppV2Bridge({
        respondWithToken = 'v2-fresh',
        respondSuccess = true,
        expiresIn = 1800,
    } = {}) {
        const calls = [];
        const bridge = {
            calls,
            externalAppV2: {
                postMessage(json) {
                    calls.push(JSON.parse(json));
                    setTimeout(() => {
                        const fn = bridge.window?.externalAuthSetToken;
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

    // externalApp (V1) is the legacy direct method, retained for older
    // Companion builds. Same fixed callback name; security fix whitelisted
    // it so randomised callback names no longer work.
    function legacyGetExternalAuthBridge({
        respondWithToken = 'v1-fresh',
        respondSuccess = true,
        expiresIn = 1800,
    } = {}) {
        const calls = [];
        const bridge = {
            calls,
            externalApp: {
                getExternalAuth(json) {
                    calls.push(JSON.parse(json));
                    setTimeout(() => {
                        const fn = bridge.window?.externalAuthSetToken;
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

    it('refreshAccess() uses externalAppV2.postMessage on modern Companion (no /beatify/auth/refresh fetch)', async () => {
        // Uses ANDROID_NO_HA_UA: bridge IS consulted (isAndroidCompanion() returns
        // true via _hasCompanionAuthBridge()), but bypass mode is NOT active
        // (isCompanionBypassMode() requires both "Android" AND "Home Assistant").
        const bridge = externalAppV2Bridge({ respondWithToken: 'v2-token' });
        const fetchFn = async () => { throw new Error('should not fetch — Companion V2 path active'); };
        const { BeatifyAuth, sandboxWindow, cookieJar } = loadHaAuth({
            fetchFn,
            userAgent: ANDROID_NO_HA_UA,
            externalAppV2: bridge.externalAppV2,
        });
        bridge.window = sandboxWindow;
        const token = await BeatifyAuth.getAccessToken();
        expect(token).toBe('v2-token');
        // The cookie was planted by _setSessionCookieFromCompanion.
        expect(cookieJar.value).toContain('beatify_access=');
        // V2 message shape: {id, type: "getExternalAuth", payload: {callback, force}}
        expect(bridge.calls).toHaveLength(1);
        expect(bridge.calls[0].type).toBe('getExternalAuth');
        expect(bridge.calls[0].payload.callback).toBe('externalAuthSetToken');
        expect(bridge.calls[0].payload.force).toBe(true);
        // The whitelisted callback is required by Companion ≥ 2026.4.4.
    });

    it('refreshAccess() uses legacy externalApp.getExternalAuth when V2 is unavailable', async () => {
        const bridge = legacyGetExternalAuthBridge({ respondWithToken: 'v1-token' });
        const fetchFn = async () => { throw new Error('should not fetch — Companion V1 path active'); };
        const { BeatifyAuth, sandboxWindow, cookieJar } = loadHaAuth({
            fetchFn,
            userAgent: ANDROID_NO_HA_UA,
            externalApp: bridge.externalApp,
        });
        bridge.window = sandboxWindow;
        const token = await BeatifyAuth.getAccessToken();
        expect(token).toBe('v1-token');
        expect(cookieJar.value).toContain('beatify_access=');
        // V1 message shape: {callback, force}. The callback MUST be the
        // fixed string "externalAuthSetToken" — Companion ≥ 2026.4.4 silently
        // rejects any other name (security fix GHSA-7jp2-p2fw-mgvf).
        expect(bridge.calls).toHaveLength(1);
        expect(bridge.calls[0].callback).toBe('externalAuthSetToken');
        expect(bridge.calls[0].force).toBe(true);
    });

    it('falls back from failing V2 to legacy V1 when both are present', async () => {
        // V2 rejects, V1 succeeds. Should land on the V1 token.
        const calls = { v2: [], v1: [] };
        const bridge = {
            externalAppV2: {
                postMessage(json) {
                    calls.v2.push(JSON.parse(json));
                    setTimeout(() => {
                        sandbox.externalAuthSetToken(false, { message: 'v2_failure' });
                    }, 0);
                },
            },
            externalApp: {
                getExternalAuth(json) {
                    calls.v1.push(JSON.parse(json));
                    setTimeout(() => {
                        sandbox.externalAuthSetToken(true, {
                            access_token: 'fallback-token',
                            expires_in: 1800,
                        });
                    }, 0);
                },
            },
        };
        const fetchFn = async () => { throw new Error('should not fetch'); };
        const { BeatifyAuth, sandboxWindow } = loadHaAuth({
            fetchFn,
            userAgent: ANDROID_NO_HA_UA,
            externalApp: bridge.externalApp,
            externalAppV2: bridge.externalAppV2,
        });
        const sandbox = sandboxWindow;
        const token = await BeatifyAuth.getAccessToken();
        expect(token).toBe('fallback-token');
        expect(calls.v2).toHaveLength(1);
        expect(calls.v1).toHaveLength(1);
    });

    it('detects Companion via injected externalAppV2 even when UA does not match', async () => {
        // No Companion UA, but externalAppV2 is injected — should still take the bridge path.
        const bridge = externalAppV2Bridge({ respondWithToken: 'ua-fallback-token' });
        const fetchFn = async () => { throw new Error('should not fetch'); };
        const { BeatifyAuth, sandboxWindow } = loadHaAuth({
            fetchFn,
            userAgent: 'Mozilla/5.0 (Linux; Android 16) Chrome/Mobile Safari', // no "Home Assistant"
            externalAppV2: bridge.externalAppV2,
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

describe('Companion bypass mode (#1131 — UA + RFC1918 trust on server)', () => {
    const COMPANION_UA =
        'Mozilla/5.0 (Linux; Android 16; Pixel 7 Pro) AppleWebKit/537.36 ' +
        '(KHTML, like Gecko) Chrome/Mobile Safari Home Assistant/2026.4.4-full';

    it('isCompanionBypassMode() returns true when Companion UA is set and no bridge is exposed', () => {
        const { BeatifyAuth } = loadHaAuth({
            userAgent: COMPANION_UA,
            // neither externalApp nor externalAppV2 — older Companion build
            // that hides the bridge or has the security fix not deployed.
        });
        expect(BeatifyAuth.isCompanionBypassMode()).toBe(true);
    });

    it('isCompanionBypassMode() returns true even when externalAppV2 is exposed (rc10: bridge unreliable)', () => {
        // rc10 (#1131): field data shows recent Companion builds advertise the
        // bridge but it either never replies or replies with a token HA rejects.
        // The bypass therefore ignores bridge presence and trusts the
        // server-side UA+RFC1918 check unconditionally.
        const { BeatifyAuth } = loadHaAuth({
            userAgent: COMPANION_UA,
            externalAppV2: { postMessage() {} },
        });
        expect(BeatifyAuth.isCompanionBypassMode()).toBe(true);
    });

    it('isCompanionBypassMode() returns false on desktop browsers', () => {
        const { BeatifyAuth } = loadHaAuth({
            userAgent: 'Mozilla/5.0 (Macintosh) Safari/605',
        });
        expect(BeatifyAuth.isCompanionBypassMode()).toBe(false);
    });

    it('init() resolves true and skips OAuth flow in Companion bypass mode', async () => {
        const fetchCalls = [];
        const fetchFn = async (url) => {
            fetchCalls.push(url);
            // Should never be called — but if init regresses to call refresh,
            // we want the test to fail loudly with a clear assertion below.
            return { ok: true, status: 200, json: async () => ({}) };
        };
        const { BeatifyAuth } = loadHaAuth({
            fetchFn,
            userAgent: COMPANION_UA,
        });
        const ok = await BeatifyAuth.init({ requireAuth: true });
        expect(ok).toBe(true);
        // No /beatify/auth/refresh call, no /auth/authorize redirect.
        expect(fetchCalls).toHaveLength(0);
    });

    it('authedFetch() in Companion bypass mode sends NO Authorization header (server detects via UA+IP)', async () => {
        const observedHeaders = [];
        const fetchFn = async (url, opts) => {
            observedHeaders.push({ url, headers: opts?.headers });
            return { ok: true, status: 200 };
        };
        const { BeatifyAuth } = loadHaAuth({
            fetchFn,
            userAgent: COMPANION_UA,
        });
        await BeatifyAuth.fetch('/beatify/api/lights');
        expect(observedHeaders).toHaveLength(1);
        // Either undefined headers (no opts passed) or no Authorization key.
        const h = observedHeaders[0].headers;
        expect(h?.Authorization).toBeUndefined();
    });

    it('getAccessToken() returns null in bypass mode even when bridge is exposed (#1153)', async () => {
        // rc10 showed the bridge either never replies or gives a token that HA's
        // async_validate_access_token rejects → admin WS sends ERR_UNAUTHORIZED
        // → recovery loop → visible "unauthorized message". In bypass mode
        // getAccessToken() must return null so connectAdminWebSocket() sends
        // ha_token: null; the server then accepts via UA+RFC1918 companion trust.
        const bridgeCalls = [];
        const fetchFn = async () => { throw new Error('should not fetch'); };
        const { BeatifyAuth, sandboxWindow } = loadHaAuth({
            fetchFn,
            userAgent: COMPANION_UA, // full Android + "Home Assistant" UA → bypass mode
            externalAppV2: {
                postMessage(json) {
                    bridgeCalls.push(JSON.parse(json));
                    // bridge would reply with a token — but it must never be called
                    setTimeout(() => {
                        const fn = sandboxWindow.externalAuthSetToken;
                        if (typeof fn === 'function') fn(true, { access_token: 'bridge-token', expires_in: 1800 });
                    }, 0);
                },
            },
        });
        const token = await BeatifyAuth.getAccessToken();
        expect(token).toBeNull();           // bypass mode → null, not the bridge token
        expect(bridgeCalls).toHaveLength(0); // bridge was NOT called at all
    });

    it('ensureAuthenticated() resolves null in Companion bypass mode (rc12: no OAuth attempt)', async () => {
        // rc11 admin → "join as host" hung on Android Companion because
        // ensureAuthenticated() called login() → /auth/authorize → blocked
        // by Companion's WebView ("Invalid redirect URI"). The returned
        // promise never resolved and `adminWs.send({...ha_token: token})`
        // never fired. rc12 short-circuits to null so the WS send proceeds
        // and the server-side bypass kicks in on UA+RFC1918.
        let loginCalls = 0;
        const fetchFn = async () => {
            // refreshAccess should NOT be called either — bypass mode means
            // there is no OAuth to refresh.
            return { ok: false, status: 401 };
        };
        const { BeatifyAuth, sandboxWindow } = loadHaAuth({
            fetchFn,
            userAgent: COMPANION_UA,
        });
        const _originalReplace = sandboxWindow.location.replace;
        sandboxWindow.location.replace = function (url) {
            loginCalls += 1;
            return _originalReplace.call(this, url);
        };
        const token = await BeatifyAuth.ensureAuthenticated();
        expect(token).toBeNull();
        expect(loginCalls).toBe(0); // no /auth/authorize navigation
    });

    it('handleServerRejection() resolves null in bypass mode WITHOUT refresh or OAuth redirect (#1393)', async () => {
        // #1393: when the server rejects a bypass-mode connection (Companion
        // reached Beatify over a non-RFC1918 address), handleServerRejection()
        // previously ran refreshAccess() then login() → window.location.replace
        // to /auth/authorize → the Invalid-redirect-URI / #1153 screen with no
        // recovery. The guard must resolve null without ANY fetch (refresh) or
        // location.replace (OAuth redirect).
        let fetchCalls = 0;
        let replaceCalls = 0;
        const fetchFn = async () => {
            fetchCalls += 1;
            return { ok: false, status: 401 };
        };
        const { BeatifyAuth, sandboxWindow } = loadHaAuth({
            fetchFn,
            userAgent: COMPANION_UA,
        });
        const _origReplace = sandboxWindow.location.replace;
        sandboxWindow.location.replace = function (url) {
            replaceCalls += 1;
            return _origReplace.call(this, url);
        };
        const token = await BeatifyAuth.handleServerRejection();
        expect(token).toBeNull();
        expect(fetchCalls).toBe(0);   // no refreshAccess() bridge/HTTP attempt
        expect(replaceCalls).toBe(0); // no /auth/authorize navigation
    });

    it('handleServerRejection() in a NORMAL browser still refreshes + redirects (no regression)', async () => {
        // Desktop / non-Companion: the guard must NOT change the existing
        // recovery — a server rejection still forces a refresh and, when that
        // fails, an OAuth redirect.
        let replaceUrl = null;
        const fetchFn = async () => ({ ok: false, status: 401 }); // refresh fails
        const { BeatifyAuth, sandboxWindow } = loadHaAuth({
            fetchFn,
            userAgent: 'Mozilla/5.0 (Macintosh) Safari/605',
        });
        sandboxWindow.location.replace = (url) => { replaceUrl = url; };
        // The returned promise never resolves (navigating away) — assert the
        // side effect instead, after a tick lets refreshAccess reject.
        BeatifyAuth.handleServerRejection();
        await new Promise((r) => setTimeout(r, 0));
        expect(replaceUrl).toContain('/auth/authorize');
    });

    it('login() is suppressed in bypass mode — no /auth/authorize redirect (#1393)', () => {
        // #1393 defensive guard: a direct login() call in bypass mode must NOT
        // window.location.replace to /auth/authorize (the Invalid-redirect-URI
        // screen). It logs an actionable hint and returns.
        let replaceCalls = 0;
        const { BeatifyAuth, sandboxWindow } = loadHaAuth({
            userAgent: COMPANION_UA,
        });
        sandboxWindow.location.replace = () => { replaceCalls += 1; };
        BeatifyAuth.login();
        expect(replaceCalls).toBe(0);
        expect(sandboxWindow.location._lastReplace).toBeUndefined();
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
