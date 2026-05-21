/**
 * Unit tests for ha-auth.js token POST fallback.
 *
 * The bug under test: Safari 18 throws "TypeError: Load failed" on the
 * FormData /auth/token POST (the rc8 fix that survives Nabu Casa SniTun).
 * The request never reaches HA, exchangeCode rejects, init bounces to
 * login() — the symptom is a HA-login → flash-of-Beatify → HA-login loop.
 *
 * The fix: postToken tries FormData first, falls back to urlencoded on
 * TypeError. Other errors (HTTP 4xx/5xx) propagate without a retry —
 * retrying a server rejection just wastes a request.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';

const __dirname = dirname(fileURLToPath(import.meta.url));
const SRC_PATH = join(__dirname, '..', 'ha-auth.js');
const SRC = readFileSync(SRC_PATH, 'utf8');

// Build a fresh sandbox per test so localStorage / window.BeatifyAuth from
// one test don't leak into the next.
function loadHaAuth({ fetchFn, localStorageData = {} } = {}) {
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
        // ha-auth.js references bare `localStorage` / `sessionStorage` (not
        // window.localStorage) — expose them at the top level of the vm
        // context so the IIFE can read them.
        localStorage: ls,
        sessionStorage: ss,
        document: { title: 'test' },
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
        setTimeout,
    };
    vm.createContext(ctx);
    vm.runInContext(SRC, ctx);
    return { BeatifyAuth: sandboxWindow.BeatifyAuth, localStorage: ls, calls: [] };
}

describe('postToken transport fallback', () => {
    it('retries with urlencoded body when FormData fetch throws TypeError', async () => {
        const calls = [];
        const fetchFn = async (url, opts) => {
            calls.push({ url, body: opts.body, headers: opts.headers });
            if (opts.body instanceof FormData) {
                // Simulate Safari 18: the FormData request never leaves the browser.
                throw new TypeError('Load failed');
            }
            // urlencoded fallback succeeds
            return {
                ok: true,
                json: async () => ({
                    access_token: 'new-access',
                    refresh_token: 'new-refresh',
                    expires_in: 1800,
                }),
            };
        };
        const { BeatifyAuth } = loadHaAuth({
            fetchFn,
            localStorageData: { beatify_ha_refresh: 'stored-refresh' },
        });

        // getAccessToken with a stored refresh token but no fresh access token
        // takes the refreshAccess path, which calls postToken.
        const token = await BeatifyAuth.getAccessToken();

        expect(token).toBe('new-access');
        expect(calls).toHaveLength(2);
        expect(calls[0].body).toBeInstanceOf(FormData);
        expect(typeof calls[1].body).toBe('string');
        expect(calls[1].body).toContain('grant_type=refresh_token');
        expect(calls[1].body).toContain('refresh_token=stored-refresh');
        expect(calls[1].headers['Content-Type']).toBe('application/x-www-form-urlencoded');
    });

    it('does NOT retry on a 4xx HTTP response — server rejection propagates', async () => {
        const calls = [];
        const fetchFn = async (url, opts) => {
            calls.push({ url, body: opts.body });
            // Server-side rejection (e.g. revoked refresh token). Retrying with
            // urlencoded would just produce the same 400 — pointless work.
            return {
                ok: false,
                status: 400,
                text: async () => 'invalid_grant',
            };
        };
        const { BeatifyAuth } = loadHaAuth({
            fetchFn,
            localStorageData: { beatify_ha_refresh: 'revoked-refresh' },
        });

        // refreshAccess catches the error internally and resolves to null.
        // What we care about is that only ONE fetch happened — no fallback
        // retry on a server-level rejection.
        const token = await BeatifyAuth.getAccessToken();

        expect(token).toBeNull();
        expect(calls).toHaveLength(1);
        expect(calls[0].body).toBeInstanceOf(FormData);
    });

    it('skips the fallback when the FormData request succeeds', async () => {
        const calls = [];
        const fetchFn = async (url, opts) => {
            calls.push({ url, body: opts.body });
            return {
                ok: true,
                json: async () => ({
                    access_token: 'cloud-token',
                    refresh_token: 'cloud-refresh',
                    expires_in: 1800,
                }),
            };
        };
        const { BeatifyAuth } = loadHaAuth({
            fetchFn,
            localStorageData: { beatify_ha_refresh: 'stored-refresh' },
        });

        const token = await BeatifyAuth.getAccessToken();

        expect(token).toBe('cloud-token');
        expect(calls).toHaveLength(1);
        expect(calls[0].body).toBeInstanceOf(FormData);
    });
});
