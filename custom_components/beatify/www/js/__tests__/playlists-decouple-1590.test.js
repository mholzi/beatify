/**
 * #1590 — decouple the playlist-selection data store from the dead flat-admin
 * DOM.
 *
 * The flat #playlists section is dead UI (hidden via body.home-mode since
 * rc11/#1138) yet stayed load-bearing: selection-restore read the per-provider
 * song count back out of the rendered `.playlist-checkbox` dataset, so removing
 * `#playlists-list` would silently wipe the host's saved playlist selection.
 *
 * These tests pin the decoupling: with NO #playlists-list element present,
 * renderPlaylists must still populate adminState.playlistData AND restore
 * adminState.selectedPlaylists from localStorage — sourced from the in-memory
 * playlist data, not the DOM — without throwing.
 *
 * vitest env is `node` (no jsdom), so the DOM is hand-rolled (see
 * media-players-autorestore.test.js for the same pattern).
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

globalThis.CSS = globalThis.CSS || { escape: (s) => String(s) };

let store;

beforeEach(() => {
    store = {};
    globalThis.window = globalThis;
    globalThis.BeatifyUtils = { escapeHtml: (s) => String(s) };
    globalThis.localStorage = {
        getItem: (k) => (k in store ? store[k] : null),
        setItem: (k, v) => { store[k] = String(v); },
        removeItem: (k) => { delete store[k]; },
    };
    // No #playlists-list (or any flat-admin element) in the DOM: every lookup
    // returns null. This is exactly the "dead DOM removed" state #1590 targets.
    globalThis.document = {
        getElementById: () => null,
        querySelector: () => null,
        querySelectorAll: () => [],
    };
});

afterEach(() => {
    delete globalThis.window;
    delete globalThis.document;
    delete globalThis.localStorage;
    delete globalThis.BeatifyUtils;
    vi.restoreAllMocks();
});

const PLAYLISTS = [
    { path: 'a.json', name: 'Valid A', is_valid: true, song_count: 30, spotify_count: 25 },
    { path: 'b.json', name: 'Valid B', is_valid: true, song_count: 10, spotify_count: 10 },
    // Zero playable songs (empty playlist) → providerCount 0 → must be excluded.
    // NB: a non-zero song_count with spotify_count 0 would legacy-fall-back to
    // song_count (matching the live render), so an empty playlist is the only
    // way to exercise the providerCount>0 gate under the spotify provider.
    { path: 'c.json', name: 'Empty', is_valid: true, song_count: 0, spotify_count: 0 },
    // Invalid playlist → must be excluded.
    { path: 'd.json', name: 'Broken', is_valid: false, song_count: 0, errors: ['bad'] },
];

describe('providerCountForPlaylist (#1590)', () => {
    it('returns the provider-specific count, with documented fallbacks', async () => {
        const { providerCountForPlaylist } = await import('../admin/sections/playlists.js');
        const pl = {
            song_count: 30, spotify_count: 25, apple_music_count: 20,
            youtube_music_count: 0, tidal_count: 5, deezer_count: 3,
        };
        expect(providerCountForPlaylist(pl, 'spotify')).toBe(25);
        expect(providerCountForPlaylist(pl, 'apple_music')).toBe(20);
        expect(providerCountForPlaylist(pl, 'youtube_music')).toBe(0);
        expect(providerCountForPlaylist(pl, 'tidal')).toBe(5);
        expect(providerCountForPlaylist(pl, 'deezer')).toBe(3);
        // amazon_music has no per-track count → Alexa text-search plays all.
        expect(providerCountForPlaylist(pl, 'amazon_music')).toBe(30);
        // spotify with no count → legacy fallback to raw song_count.
        expect(providerCountForPlaylist({ song_count: 8 }, 'spotify')).toBe(8);
        // unknown provider → full song_count.
        expect(providerCountForPlaylist(pl, 'whatever')).toBe(30);
    });
});

describe('renderPlaylists data-store decoupling (#1590)', () => {
    it('restores selection from localStorage with NO #playlists-list in the DOM', async () => {
        const { renderPlaylists } = await import('../admin/sections/playlists.js');
        const { adminState } = await import('../admin/state.js');
        adminState.selectedProvider = 'spotify';
        adminState.activeFilterTags = ['all'];

        // Host previously selected the two valid+playable playlists plus the
        // zero-count and invalid ones (which must NOT come back).
        store['beatify_game_settings'] = JSON.stringify({
            selectedPlaylists: ['a.json', 'b.json', 'c.json', 'd.json'],
        });

        // Must not throw even though container (#playlists-list) is absent.
        expect(() => renderPlaylists(PLAYLISTS, '/playlists')).not.toThrow();

        // The in-memory data store is populated...
        expect(adminState.playlistData).toHaveLength(4);
        // ...and the selection is restored from data, excluding the zero-count
        // (c.json) and invalid (d.json) entries.
        const paths = adminState.selectedPlaylists.map((p) => p.path).sort();
        expect(paths).toEqual(['a.json', 'b.json']);
        // songCount carries the provider-specific count, not the raw song_count.
        const a = adminState.selectedPlaylists.find((p) => p.path === 'a.json');
        expect(a.songCount).toBe(25);
    });

    it('preserves selections across a provider-switch re-render without the DOM', async () => {
        const { renderPlaylists } = await import('../admin/sections/playlists.js');
        const { adminState } = await import('../admin/state.js');
        adminState.selectedProvider = 'spotify';
        adminState.activeFilterTags = ['all'];
        adminState.selectedPlaylists = [{ path: 'a.json', songCount: 99 }];

        renderPlaylists(PLAYLISTS, '/playlists', /* preserveSelection */ true);

        const paths = adminState.selectedPlaylists.map((p) => p.path);
        expect(paths).toEqual(['a.json']);
        // Re-derived from data on the new provider, not the stale 99.
        expect(adminState.selectedPlaylists[0].songCount).toBe(25);
    });
});
