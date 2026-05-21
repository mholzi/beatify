/**
 * Unit tests for ha-auth.js token POST fallback.
 *
 * The bug under test: Safari 18 rejects the rc8 FormData /auth/token POST
 * with "TypeError: Load failed" (the request never leaves the browser),
 * and rejects the rc12 urlencoded fetch fallback with "Fetch API cannot
 * load … due to access control checks" (Safari incorrectly applies a
 * CORS check to a same-origin POST). rc13 falls back to XMLHttpRequest,
 * which uses a different network path internally and isn't subject to
 * the fetch CORS quirk for same-origin POST.
 *
 * Symptom for users: HA-login → flash of Beatify → bounce back to HA-login.
 *
 * Strategy: postToken tries FormData via fetch first (preserves rc8 Nabu
 * Casa SniTun support for Chrome and pre-Safari-18), falls back to XHR
 * urlencoded on TypeError. HTTP rejections (4xx/5xx) propagate without
 * retry — retrying a server-side invalid_grant just produces the same
 * response.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';

const __dirname = dirname(fileURLToPath(import.meta.url));
const SRC_PATH = join(__dirname, '..', 'ha-auth.js');
const SRC = readFileSync(SRC_PATH, 'utf8');

// Mock XMLHttpRequest that drives a queued list of responses. Each test
// configures one response shape (success/4xx/network-error) per XHR opened.
function makeMockXhrCtor(responseFn, callLog) {
    return function MockXMLHttpRequest() {
        const xhr = {
            _headers: {},
            open(method, url) { this._method = method; this._url = url; },
            setRequestHeader(k, v) { this._headers[k] = v; },
            withCredentials: false,
            onload: null,
            onerror: null,
            send(body) {
                callLog.push({ method: this._method, url: this._url, headers: this._headers, body, withCredentials: this.withCredentials });
                // Defer the callback so .send returns first, matching real XHR.
                setTimeout(() => {
                    const r = responseFn(body, this);
                    if (r.networkError) {
                        if (this.onerror) this.onerror();
                    } else {
                        this.status = r.status;
                        this.statusText = r.statusText || '';
                        this.responseText = r.responseText;
                        if (this.onload) this.onload();
                    }
                }, 0);
            },
        };
        return xhr;
    };
}

function loadHaAuth({ fetchFn, xhrCtor, localStorageData = {} } = {}) {
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
    const sandboxWindow = {
        location: { origin: 'https://ha.example', pathname: '/beatify/admin', search: '', hash: '' },
        localStorage: ls,
        sessionStorage: ss,
        crypto: { getRandomValues: (buf) => { for (let i = 0; i < buf.length; i++) buf[i] = i; return buf; } },
        history: { replaceState: () => {} },
    };
    const ctx = {
        window: sandboxWindow,
        localStorage: ls,
        sessionStorage: ss,
        document: { title: 'test' },
        console,
        fetch: fetchFn,
        XMLHttpRequest: xhrCtor,
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
        setTimeout,
    };
    vm.createContext(ctx);
    vm.runInContext(SRC, ctx);
    return { BeatifyAuth: sandboxWindow.BeatifyAuth, localStorage: ls };
}

describe('postToken transport fallback', () => {
    it('retries via XHR when FormData fetch throws TypeError (Safari 18 path)', async () => {
        const fetchCalls = [];
        const fetchFn = async (url, opts) => {
            fetchCalls.push({ url, body: opts.body });
            // Simulate Safari 18 + Nabu Casa: FormData request never leaves the browser.
            throw new TypeError('Load failed');
        };
        const xhrCalls = [];
        const xhrCtor = makeMockXhrCtor(() => ({
            status: 200,
            responseText: JSON.stringify({
                access_token: 'xhr-access',
                refresh_token: 'xhr-refresh',
                expires_in: 1800,
            }),
        }), xhrCalls);
        const { BeatifyAuth } = loadHaAuth({
            fetchFn,
            xhrCtor,
            localStorageData: { beatify_ha_refresh: 'stored-refresh' },
        });

        // getAccessToken with a stored refresh token but no fresh access takes
        // the refreshAccess path → postToken.
        const token = await BeatifyAuth.getAccessToken();

        expect(token).toBe('xhr-access');
        expect(fetchCalls).toHaveLength(1);
        expect(fetchCalls[0].body).toBeInstanceOf(FormData);
        expect(xhrCalls).toHaveLength(1);
        expect(xhrCalls[0].method).toBe('POST');
        expect(xhrCalls[0].url).toBe('https://ha.example/auth/token');
        expect(xhrCalls[0].body).toContain('grant_type=refresh_token');
        expect(xhrCalls[0].body).toContain('refresh_token=stored-refresh');
        expect(xhrCalls[0].headers['Content-Type']).toBe('application/x-www-form-urlencoded');
        expect(xhrCalls[0].withCredentials).toBe(true);
    });

    it('does NOT fall back to XHR on a 4xx fetch response — server rejection propagates', async () => {
        const fetchCalls = [];
        const fetchFn = async (url, opts) => {
            fetchCalls.push({ url, body: opts.body });
            // HA-side rejection (e.g. revoked refresh token). Retrying with XHR
            // would just produce the same 400.
            return {
                ok: false,
                status: 400,
                text: async () => 'invalid_grant',
            };
        };
        const xhrCalls = [];
        const xhrCtor = makeMockXhrCtor(() => ({ status: 500, responseText: 'should-not-be-called' }), xhrCalls);
        const { BeatifyAuth } = loadHaAuth({
            fetchFn,
            xhrCtor,
            localStorageData: { beatify_ha_refresh: 'revoked-refresh' },
        });

        const token = await BeatifyAuth.getAccessToken();

        expect(token).toBeNull();
        expect(fetchCalls).toHaveLength(1);
        expect(xhrCalls).toHaveLength(0);
    });

    it('skips the fallback when FormData fetch succeeds (Chrome / pre-Safari-18 path)', async () => {
        const fetchCalls = [];
        const fetchFn = async (url, opts) => {
            fetchCalls.push({ url, body: opts.body });
            return {
                ok: true,
                json: async () => ({
                    access_token: 'fetch-token',
                    refresh_token: 'fetch-refresh',
                    expires_in: 1800,
                }),
            };
        };
        const xhrCalls = [];
        const xhrCtor = makeMockXhrCtor(() => { throw new Error('XHR should not be invoked'); }, xhrCalls);
        const { BeatifyAuth } = loadHaAuth({
            fetchFn,
            xhrCtor,
            localStorageData: { beatify_ha_refresh: 'stored-refresh' },
        });

        const token = await BeatifyAuth.getAccessToken();

        expect(token).toBe('fetch-token');
        expect(fetchCalls).toHaveLength(1);
        expect(fetchCalls[0].body).toBeInstanceOf(FormData);
        expect(xhrCalls).toHaveLength(0);
    });

    it('surfaces XHR HTTP errors when the fallback path also fails server-side', async () => {
        const fetchFn = async () => { throw new TypeError('Load failed'); };
        const xhrCalls = [];
        const xhrCtor = makeMockXhrCtor(() => ({
            status: 400,
            responseText: 'invalid_grant',
        }), xhrCalls);
        const { BeatifyAuth } = loadHaAuth({
            fetchFn,
            xhrCtor,
            localStorageData: { beatify_ha_refresh: 'broken-refresh' },
        });

        // refreshAccess catches the rejection internally and returns null,
        // but the XHR fallback should have been attempted.
        const token = await BeatifyAuth.getAccessToken();

        expect(token).toBeNull();
        expect(xhrCalls).toHaveLength(1);
    });
});
