/**
 * #1513 regression tests for playlist-generator.js auth transport.
 *
 * Bug: _saveLocally() (and _captureIssueSubmission) POSTed to auth-gated
 * endpoints with a bare fetch() — no Authorization header — so a normal
 * browser got 401 "Unauthorized" from is_authorized_http() (#1368/#1367).
 * Fix: route calls through _authFetch(), which prefers window.BeatifyAuth.fetch
 * (attaches the HA Bearer token) and falls back to window.fetch only when
 * BeatifyAuth is unavailable. These tests lock that behaviour in.
 */
import { describe, it, expect, vi } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const SRC = path.resolve(__dirname, '..', 'playlist-generator.js');

// Load the IIFE in a fresh VM context and return both the tested internals
// and the `window` object, so a test can install/inspect BeatifyAuth + fetch.
function load(win) {
    const code = fs.readFileSync(SRC, 'utf8');
    const ctx = {
        window: win,
        document: { addEventListener() {}, removeEventListener() {}, createElement: () => ({}) },
        navigator: {},
        URLSearchParams,
        URL,
        // Delegate to the *current* test-realm timers so vi.useFakeTimers()
        // (which swaps globalThis.setTimeout) intercepts the module's watchdog.
        setTimeout: (...a) => globalThis.setTimeout(...a),
        clearTimeout: (...a) => globalThis.clearTimeout(...a),
    };
    vm.createContext(ctx);
    vm.runInContext(code, ctx);
    return { api: ctx.window.PlaylistGenerator._internals, win: ctx.window };
}

function okResponse() {
    return { ok: true, json: async () => ({ filename: 'saved.json', success: true }) };
}

const SAVE_URL = '/beatify/api/playlists/save';

describe('#1513 playlist-generator auth transport', () => {
    it('_saveLocally uses window.BeatifyAuth.fetch when present (Bearer path)', async () => {
        const authFetch = vi.fn(() => Promise.resolve(okResponse()));
        const bareFetch = vi.fn(() => Promise.resolve(okResponse()));
        const win = { BeatifyAuth: { fetch: authFetch }, fetch: bareFetch };
        const { api } = load(win);

        await api._saveLocally({ name: 'X', songs: [] });

        expect(authFetch).toHaveBeenCalledTimes(1);
        expect(authFetch.mock.calls[0][0]).toBe(SAVE_URL);
        expect(authFetch.mock.calls[0][1]).toMatchObject({ method: 'POST' });
        // The bare fetch must NOT be used when BeatifyAuth is available.
        expect(bareFetch).not.toHaveBeenCalled();
    });

    it('_saveLocally falls back to window.fetch when BeatifyAuth is absent', async () => {
        const bareFetch = vi.fn(() => Promise.resolve(okResponse()));
        const win = { fetch: bareFetch }; // no BeatifyAuth
        const { api } = load(win);

        await api._saveLocally({ name: 'X', songs: [] });

        expect(bareFetch).toHaveBeenCalledTimes(1);
        expect(bareFetch.mock.calls[0][0]).toBe(SAVE_URL);
    });

    it('_authFetch prefers BeatifyAuth.fetch and returns its result', async () => {
        const sentinel = okResponse();
        const authFetch = vi.fn(() => Promise.resolve(sentinel));
        const bareFetch = vi.fn(() => Promise.resolve(okResponse()));
        const win = { BeatifyAuth: { fetch: authFetch }, fetch: bareFetch };
        const { api } = load(win);

        const res = await api._authFetch('/x', { method: 'GET' });

        expect(res).toBe(sentinel);
        expect(authFetch).toHaveBeenCalledWith('/x', { method: 'GET' });
        expect(bareFetch).not.toHaveBeenCalled();
    });

    it('_authFetch falls back to window.fetch when BeatifyAuth.fetch is not a function', async () => {
        const bareFetch = vi.fn(() => Promise.resolve(okResponse()));
        const win = { BeatifyAuth: {}, fetch: bareFetch };
        const { api } = load(win);

        await api._authFetch('/y', { method: 'POST' });

        expect(bareFetch).toHaveBeenCalledWith('/y', { method: 'POST' });
    });
});

const REQUESTS_URL = '/beatify/api/playlist-requests';

describe('#1655 _captureIssueSubmission auth transport', () => {
    it('routes both the GET and the POST through window.BeatifyAuth.fetch', async () => {
        const authFetch = vi.fn((url, opts) => {
            if (opts && opts.method === 'POST') {
                return Promise.resolve({ ok: true, json: async () => ({}) });
            }
            return Promise.resolve({ ok: true, json: async () => ({ requests: [], last_poll: null }) });
        });
        const bareFetch = vi.fn(() => Promise.resolve(okResponse()));
        const win = { BeatifyAuth: { fetch: authFetch }, fetch: bareFetch };
        const { api } = load(win);

        // Test seam: set the state the handler reads before firing.
        api._state.pendingSubmission = { spotify_url: '', playlist_name: 'X' };
        api._state.rootEl = {
            querySelector(sel) {
                if (sel.indexOf('issue_url') >= 0) {
                    return { value: 'https://github.com/mholzi/beatify/issues/123' };
                }
                return { innerHTML: '', value: '' };
            },
        };

        await api._captureIssueSubmission();

        expect(authFetch).toHaveBeenCalledTimes(2);
        expect(authFetch.mock.calls[0][0]).toBe(REQUESTS_URL);      // GET
        expect(authFetch.mock.calls[1][0]).toBe(REQUESTS_URL);      // POST
        expect(authFetch.mock.calls[1][1]).toMatchObject({ method: 'POST' });
        expect(bareFetch).not.toHaveBeenCalled();
        expect(api._state.capturedIssueNumber).toBe(123);
    });
});

describe('#1655 _runActionButton busy state + watchdog', () => {
    function fakeRoot(button) {
        return { querySelector: (sel) => (sel.indexOf('data-plg-action') >= 0 ? button : null) };
    }

    it('disables + relabels the button while running, restores it on settle', async () => {
        const { api } = load({});
        const button = { disabled: false, textContent: 'Save locally' };
        api._state.rootEl = fakeRoot(button);

        const p = api._runActionButton('save-local', () => Promise.resolve('ok'));
        // Busy while the work is in flight.
        expect(button.disabled).toBe(true);
        expect(button.textContent).not.toBe('Save locally');

        await p;
        // Restored on settle.
        expect(button.disabled).toBe(false);
        expect(button.textContent).toBe('Save locally');
    });

    it('restores the button via watchdog even if the work never settles (login redirect)', async () => {
        vi.useFakeTimers();
        try {
            const { api } = load({});
            const button = { disabled: false, textContent: 'Save locally' };
            api._state.rootEl = fakeRoot(button);

            // A never-resolving promise mimics BeatifyAuth.fetch's login-redirect path.
            api._runActionButton('save-local', () => new Promise(() => {}));
            expect(button.disabled).toBe(true);

            vi.advanceTimersByTime(12000);
            // Watchdog restored the button — it never stays permanently stuck.
            expect(button.disabled).toBe(false);
            expect(button.textContent).toBe('Save locally');
        } finally {
            vi.useRealTimers();
        }
    });
});
