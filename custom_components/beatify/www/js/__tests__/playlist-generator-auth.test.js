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
        document: { addEventListener() {}, removeEventListener() {} },
        navigator: {},
        URLSearchParams,
        URL,
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
