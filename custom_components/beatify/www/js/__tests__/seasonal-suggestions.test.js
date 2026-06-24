/**
 * #1539 — seasonal playlist suggestion logic.
 *
 * Covers the pure decision logic (window matching, once-per-season flag,
 * installed-playlist lookup, and the combined pick) without a DOM. The vitest
 * env is `node`, so we mock the few globals the module touches at import time
 * (window.BeatifyUtils) and supply a tiny localStorage stub.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

globalThis.window = globalThis;
globalThis.BeatifyUtils = { escapeHtml: (s) => String(s) };

let store;
globalThis.localStorage = {
    getItem: (k) => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v); },
    removeItem: (k) => { delete store[k]; },
};

const { adminState } = await import('../admin/state.js');
const { __testables } = await import('../admin/sections/seasonal-suggestions.js');
const { inWindow, seasonKey, pickSuggestion, findInstalledPlaylist, OCCASIONS } = __testables;

// Helper: a Date at noon on a given month/day (avoids TZ edge at midnight).
const day = (m, d, y = 2026) => new Date(y, m - 1, d, 12, 0, 0);

const carnival = OCCASIONS.find((o) => o.id === 'carnival');
const summer = OCCASIONS.find((o) => o.id === 'summer');
const december = OCCASIONS.find((o) => o.id === 'december');

beforeEach(() => {
    store = {};
    adminState.playlistData = [];
});

describe('inWindow', () => {
    it('matches a plain window inclusively', () => {
        expect(inWindow(day(6, 1), summer.window)).toBe(true);   // start edge
        expect(inWindow(day(8, 31), summer.window)).toBe(true);  // end edge
        expect(inWindow(day(7, 15), summer.window)).toBe(true);  // middle
        expect(inWindow(day(5, 31), summer.window)).toBe(false); // before
        expect(inWindow(day(9, 1), summer.window)).toBe(false);  // after
    });

    it('matches a year-wrapping window (Dec → Jan)', () => {
        expect(inWindow(day(12, 1), december.window)).toBe(true);
        expect(inWindow(day(12, 25), december.window)).toBe(true);
        expect(inWindow(day(1, 6), december.window)).toBe(true);
        expect(inWindow(day(1, 7), december.window)).toBe(false);
        expect(inWindow(day(11, 30), december.window)).toBe(false);
    });
});

describe('seasonKey', () => {
    it('uses the calendar year for a plain occasion', () => {
        expect(seasonKey(carnival, day(2, 10, 2026))).toContain('carnival_2026');
    });

    it('rolls a Jan tail back to the December start year', () => {
        expect(seasonKey(december, day(12, 20, 2026))).toContain('december_2026');
        expect(seasonKey(december, day(1, 3, 2027))).toContain('december_2026');
    });
});

describe('findInstalledPlaylist', () => {
    it('matches by filename suffix across any directory', () => {
        adminState.playlistData = [
            { name: 'Cologne Carnival', path: '/cfg/playlists/community/koelner-karneval.json', is_valid: true },
        ];
        expect(findInstalledPlaylist(carnival)?.name).toBe('Cologne Carnival');
    });

    it('ignores invalid playlists', () => {
        adminState.playlistData = [
            { name: 'x', path: '/cfg/playlists/koelner-karneval.json', is_valid: false },
        ];
        expect(findInstalledPlaylist(carnival)).toBe(null);
    });

    it('returns null when not installed', () => {
        adminState.playlistData = [{ name: 'y', path: '/cfg/playlists/80er-hits.json', is_valid: true }];
        expect(findInstalledPlaylist(carnival)).toBe(null);
    });

    it('honours the files preference order', () => {
        adminState.playlistData = [
            { name: 'Summer Party', path: '/p/summer-party-anthems.json', is_valid: true },
            { name: 'Sommerklassiker', path: '/p/community/sommerklassiker.json', is_valid: true },
        ];
        // sommerklassiker is first in the preference list
        expect(findInstalledPlaylist(summer)?.name).toBe('Sommerklassiker');
    });
});

describe('pickSuggestion', () => {
    it('returns the active occasion whose playlist is installed', () => {
        adminState.playlistData = [
            { name: 'Cologne Carnival', path: '/p/community/koelner-karneval.json', is_valid: true },
        ];
        const picked = pickSuggestion(day(2, 10));
        expect(picked?.occasion.id).toBe('carnival');
        expect(picked?.playlist.name).toBe('Cologne Carnival');
    });

    it('returns null outside any window', () => {
        adminState.playlistData = [
            { name: 'Cologne Carnival', path: '/p/community/koelner-karneval.json', is_valid: true },
        ];
        expect(pickSuggestion(day(10, 1))).toBe(null);
    });

    it('returns null when the seasonal flag is already set', () => {
        adminState.playlistData = [
            { name: 'Cologne Carnival', path: '/p/community/koelner-karneval.json', is_valid: true },
        ];
        store[seasonKey(carnival, day(2, 10))] = 'dismissed';
        expect(pickSuggestion(day(2, 10))).toBe(null);
    });

    it('returns null when the occasion is active but the playlist is not installed', () => {
        adminState.playlistData = [{ name: 'z', path: '/p/80er-hits.json', is_valid: true }];
        expect(pickSuggestion(day(2, 10))).toBe(null);
    });
});
