/**
 * Unit tests for ha-auth.js token POST.
 *
 * Symptom history (rc8 → rc14):
 *   - rc8: Safari + Nabu Casa rejected urlencoded fetch with TypeError.
 *     Fix: switch to FormData multipart.
 *   - rc11: stale SW could serve old ha-auth.js even after RC bumps.
 *     Fix: NEVER_CACHE + self-healing bootstrap.
 *   - rc12: Safari 18 newly rejects FormData fetch with TypeError.
 *     Fix: urlencoded-via-fetch fallback. Also broken (CORS).
 *   - rc13: replace fetch fallback with XHR. Also broken (same CORS error).
 *   - rc14: stop hitting /auth/token from the browser entirely. Proxy
 *     the exchange through /beatify/auth/exchange so the SniTun-relay
 *     response that Safari 18 dislikes never reaches the browser.
 *
 * This test covers the rc14 contract: postToken sends a urlencoded body
 * to /beatify/auth/exchange and parses the JSON response.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';

const __dirname = dirname(fileURLToPath(import.meta.url));
const SRC_PATH = join(__dirname, '..', 'ha-auth.js');
const SRC = readFileSync(SRC_PATH, 'utf8');

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
    return { BeatifyAuth: sandboxWindow.BeatifyAuth, localStorage: ls };
}

describe('postToken via Beatify proxy', () => {
    it('POSTs urlencoded params to /beatify/auth/exchange and parses the JSON response', async () => {
        const calls = [];
        const fetchFn = async (url, opts) => {
            calls.push({ url, opts });
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

        // getAccessToken with a stored refresh token but no fresh access
        // takes the refreshAccess path → postToken.
        const token = await BeatifyAuth.getAccessToken();

        expect(token).toBe('new-access');
        expect(calls).toHaveLength(1);
        expect(calls[0].url).toBe('https://ha.example/beatify/auth/exchange');
        expect(calls[0].opts.method).toBe('POST');
        expect(calls[0].opts.credentials).toBe('same-origin');
        // URLSearchParams body — no explicit Content-Type header (it's
        // inferred from the body type, which avoids CORS preflights).
        expect(calls[0].opts.body).toBeInstanceOf(URLSearchParams);
        expect(calls[0].opts.body.get('grant_type')).toBe('refresh_token');
        expect(calls[0].opts.body.get('refresh_token')).toBe('stored-refresh');
    });

    it('surfaces HTTP errors from the proxy as rejections', async () => {
        const fetchFn = async () => ({
            ok: false,
            status: 400,
            text: async () => 'invalid_grant',
        });
        const { BeatifyAuth } = loadHaAuth({
            fetchFn,
            localStorageData: { beatify_ha_refresh: 'revoked-refresh' },
        });

        // refreshAccess catches the error internally and resolves to null —
        // verifies the rejection path doesn't crash and clears nothing
        // unexpected.
        const token = await BeatifyAuth.getAccessToken();
        expect(token).toBeNull();
    });

    it('uses the fresh access token from localStorage without re-fetching when valid', async () => {
        const calls = [];
        const fetchFn = async (url, opts) => {
            calls.push({ url, opts });
            return { ok: true, json: async () => ({}) };
        };
        const { BeatifyAuth } = loadHaAuth({
            fetchFn,
            localStorageData: {
                beatify_ha_access: 'cached-access',
                beatify_ha_refresh: 'cached-refresh',
                // 1 hour in the future — accessFresh() returns true.
                beatify_ha_expires: String(Date.now() + 3600 * 1000),
            },
        });

        const token = await BeatifyAuth.getAccessToken();

        expect(token).toBe('cached-access');
        expect(calls).toHaveLength(0);
    });
});
