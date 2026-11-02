/**
 * #3390 — in the admin, a load error is not an empty state.
 *
 *   - wizard: a failed /api/status said "No speakers found, install Music
 *     Assistant"; lights and TTS did the same with their lists,
 *   - playlist hub: every part-fetch was caught into an empty list, so the
 *     ready-made error card never appeared,
 *   - request list: a failed load wrote {requests: []} into the cache — "could
 *     not load" became "No requests yet" and the good list was gone,
 *   - admin lobby: the REST poll that stands in for a dropped socket failed
 *     silently and the player list froze while looking live.
 *
 * One fixture per state, against the shipped modules.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import fs from 'node:fs';
import vm from 'node:vm';
import { join } from 'node:path';
import { JS_DIR, locale } from './helpers/js-source.js';
import { fetchJsonResult, loadErrorHtml } from '../wizard.js';
import { playlistLoadOutcome, _loadErrorCardHtml } from '../playlist-hub.js';
import { createLobbyFreshness } from '../admin/util.js';

const LOCALES = ['en', 'de', 'es', 'fr', 'it', 'nl'];
const okJson = (body) => ({ ok: true, status: 200, json: async () => body });
const http500 = { ok: false, status: 500, json: async () => { throw new SyntaxError('Unexpected token <'); } };
const identity = (_key, fallback) => fallback;

describe('wizard: speakers, lights and TTS that did not load (#3390)', () => {
    it('fetchJsonResult reports a 500 as a failure, not as data', async () => {
        expect(await fetchJsonResult('/x', async () => http500)).toEqual({ ok: false, data: null });
    });

    it('fetchJsonResult reports a network error as a failure', async () => {
        const res = await fetchJsonResult('/x', async () => { throw new TypeError('Failed to fetch'); });
        expect(res).toEqual({ ok: false, data: null });
    });

    it('fetchJsonResult passes a real empty answer through as ok', async () => {
        expect(await fetchJsonResult('/x', async () => okJson({ media_players: [] })))
            .toEqual({ ok: true, data: { media_players: [] } });
    });

    it('the speaker error says what happened and offers a retry — no reinstall advice', () => {
        const html = loadErrorHtml('speakers', identity);
        expect(html).toContain("Couldn't load your speakers");
        expect(html).toContain('Your speakers are probably fine');
        expect(html).toContain('data-wiz-retry="speakers"');
        expect(html).not.toMatch(/Music Assistant|No speakers found/);
    });

    it.each(['lights', 'tts'])('the %s error has its own title and a retry', (kind) => {
        const html = loadErrorHtml(kind, identity);
        expect(html).toContain(`data-wiz-retry="${kind}"`);
        expect(html).toContain("Home Assistant didn't answer");
        expect(html).not.toMatch(/No lights available|add one in HA first/);
    });
});

describe('playlist hub: the error card is reachable (#3390)', () => {
    it('a failed status load with nothing on screen is an error', () => {
        expect(playlistLoadOutcome(null, [])).toEqual({ playlists: [], error: 'load-failed' });
    });

    it('a failed refresh keeps the list from the last good load', () => {
        const prev = [{ path: 'a.json' }];
        expect(playlistLoadOutcome(null, prev)).toEqual({ playlists: prev, error: null });
    });

    it('a real answer replaces the list, even an empty one', () => {
        expect(playlistLoadOutcome({ playlists: [] }, [{ path: 'a.json' }])).toEqual({ playlists: [], error: null });
    });

    it('the card says what happened, what to do, and has the retry action', () => {
        const html = _loadErrorCardHtml('playlistHub.error.title', 'Could not load playlists');
        expect(html).toContain('Could not load playlists');
        expect(html).toContain('Home Assistant didn&#39;t answer');  // escaped by _escape
        expect(html).toContain('data-plh-action="retry"');
    });
});

describe('request list: an error never overwrites the real state (#3390)', () => {
    function loadModule(fetchImpl) {
        const win = { location: { origin: 'http://ha.local' } };
        const ctx = vm.createContext({ window: win, fetch: fetchImpl, console: { ...console, error() {}, warn() {} }, localStorage: { removeItem() {} } });
        vm.runInContext(fs.readFileSync(join(JS_DIR, 'playlist-requests.js'), 'utf8'), ctx);
        return win.PlaylistRequests;
    }
    const goodList = { requests: [{ issue_number: 7, playlist_name: 'Disco', requested_at: '2026-10-01T00:00:00Z', status: 'pending' }], last_poll: null };

    let fetchImpl;
    let PR;
    beforeEach(() => {
        fetchImpl = vi.fn();
        PR = loadModule((...a) => fetchImpl(...a));
    });

    it('a 500 rejects instead of answering "no requests"', async () => {
        fetchImpl.mockResolvedValue(http500);
        await expect(PR.getRequestsForDisplayAsync()).rejects.toThrow(/Could not load/);
    });

    it('a failed reload leaves the last good list in the cache', async () => {
        fetchImpl.mockResolvedValueOnce(okJson(goodList));
        await PR.loadRequestsAsync();
        fetchImpl.mockRejectedValueOnce(new TypeError('Failed to fetch'));
        await expect(PR.loadRequestsAsync()).rejects.toThrow();
        expect(PR.loadRequests().requests).toHaveLength(1);
    });

    it('submitting while the list does not load does not save over the stored requests', async () => {
        fetchImpl
            // the worker accepts the request
            .mockResolvedValueOnce(okJson({ success: true, issue_number: 9, playlist_name: 'Funk' }))
            // the stored list does not load
            .mockResolvedValueOnce(http500);
        const res = await PR.submitRequest('https://open.spotify.com/playlist/abc');
        expect(res.issue_number).toBe(9);
        const posts = fetchImpl.mock.calls.filter(([, init]) => init && init.method === 'POST');
        // Only the worker POST — no save that would replace the list with [Funk].
        expect(posts).toHaveLength(1);
    });

    it('a 5xx page from the worker gives a code the UI can translate, not "Unexpected token"', async () => {
        fetchImpl.mockResolvedValueOnce(http500);
        await expect(PR.submitRequest('https://open.spotify.com/playlist/abc'))
            .rejects.toMatchObject({ code: 'github_error' });
    });
});

describe('admin lobby: a stalled poll says so (#3390)', () => {
    it('stays quiet for the first 10 s of failures, then names the age', () => {
        let t = 0;
        const f = createLobbyFreshness({ thresholdMs: 10000, now: () => t });
        t = 9000;
        expect(f.fail()).toBeNull();
        t = 40500;
        expect(f.fail()).toBe(40);
    });

    it('a good poll resets the clock', () => {
        let t = 0;
        const f = createLobbyFreshness({ thresholdMs: 10000, now: () => t });
        t = 30000;
        f.ok();
        t = 35000;
        expect(f.fail()).toBeNull();
    });

    it('the poll shows the line on failure and clears it on success', () => {
        const admin = fs.readFileSync(join(JS_DIR, 'admin.js'), 'utf8');
        const poll = admin.slice(admin.indexOf('function startLobbyPolling()'), admin.indexOf('function stopLobbyPolling()'));
        expect(poll).toContain('setLobbyStaleLine(lobbyFreshness.fail())');
        expect(poll).toContain('setLobbyStaleLine(null)');
        // A non-OK answer is a failure too, not a silent return.
        expect(poll).not.toMatch(/if \(!response\.ok\) return;/);
    });
});

describe('copy for the new admin states, all six languages (#3390)', () => {
    const KEYS = [
        'wizard.loadError.speakersTitle', 'wizard.loadError.speakersHint',
        'wizard.loadError.lightsTitle', 'wizard.loadError.ttsTitle', 'wizard.loadError.hint',
        'playlistHub.error.body', 'playlistHub.error.requestsTitle', 'admin.home.playersStale',
    ];
    const get = (obj, path) => path.split('.').reduce((o, k) => (o ? o[k] : undefined), obj);

    it.each(LOCALES)('%s has every key, and the stale line keeps {seconds}', (lang) => {
        const d = locale(lang);
        for (const k of KEYS) expect(typeof get(d, k), `${lang} ${k}`).toBe('string');
        expect(get(d, 'admin.home.playersStale')).toContain('{seconds}');
    });
});
