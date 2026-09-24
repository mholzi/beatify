/**
 * #2939 — a Music Assistant playlist as the Crate Digger song source.
 *
 * The panel has to do three things the host can see:
 *   1. with "My playlist" chosen, hide popularity and genres (they no longer
 *      apply) and show "37 of 45 songs usable" where the match count sits;
 *   2. expand the missing songs grouped by reason, each with its way out;
 *   3. hand the wizard the number for "Continue with N songs", capped at the
 *      songs-per-game setting, and block Continue until a playlist is usable.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { bootPage, restoreGlobals, saveGlobals } from './helpers/admin-page.js';

beforeEach(saveGlobals);
afterEach(restoreGlobals);

const PLAYLIST = { item_id: '26', provider: 'library', name: 'Grillfest Sommer 26' };

const CHECK = {
    total: 45,
    usable: 37,
    usable_by_gate: { strict: 37, balanced: 40, tags_ok: 41 },
    dropped: {
        no_year: { count: 5, songs: [
            { title: 'Ein Stern', artist: 'DJ Ötzi', year: 2012 },
            { title: 'Skandal im Sperrbezirk', artist: 'Spider Murphy Gang' },
            { title: 'Major Tom', artist: 'Peter Schilling' },
            { title: 'Tage wie diese', artist: 'Die Toten Hosen' },
        ] },
        not_scanned: { count: 3, songs: [{ title: 'Cordula Grün', artist: 'Josh.' }] },
        not_in_library: { count: 0, songs: [] },
        duplicate: { count: 0, songs: [] },
    },
};

function fetchFor(settings, check = CHECK) {
    const calls = [];
    const impl = vi.fn(async (url) => {
        const u = String(url);
        calls.push(u);
        let body = {};
        if (u.includes('/library-playlists/ma/check')) body = check;
        else if (u.includes('/library-playlists/ma')) body = { playlists: [PLAYLIST] };
        else if (u.includes('/library-settings')) body = settings;
        return { ok: true, status: 200, json: async () => body };
    });
    impl.calls = calls;
    return impl;
}

async function mount(settings, check) {
    const fetchImpl = fetchFor(settings, check);
    const doc = bootPage(['library-settings'], { fetchImpl });
    const lib = await import('../admin/sections/library.js');
    const { adminState } = await import('../admin/state.js');
    const root = doc.byId['library-settings'];
    const onSourceChanged = vi.fn();
    lib.mountLibraryPanel(root, { mode: 'wizard', onSourceChanged });
    const $ = (k) => root.querySelector(`[data-lib="${k}"]`);
    return { lib, adminState, root, $, fetchImpl, onSourceChanged };
}

describe('#2939 Crate Digger with a Music Assistant playlist', () => {
    it('shows "37 of 45 songs usable" and hides the library-only filters', async () => {
        const { $, fetchImpl } = await mount({ source: 'playlist', ma_playlist: PLAYLIST, size: 50 });
        await vi.waitFor(() => expect($('playlist-count').textContent).toBe('37 of 45 songs usable'));
        expect($('playlist-row').classList.contains('hidden')).toBe(false);
        expect($('pop-row').classList.contains('hidden')).toBe(true);
        expect($('genre-row').classList.contains('hidden')).toBe(true);
        const check = fetchImpl.calls.find((u) => u.includes('/ma/check'));
        expect(check).toContain('item_id=26');
        expect(check).toContain('gate=strict');
    });

    it('expands the missing songs by reason, each with a way out', async () => {
        const { $ } = await mount({ source: 'playlist', ma_playlist: PLAYLIST });
        await vi.waitFor(() => expect($('playlist-why').classList.contains('hidden')).toBe(false));
        expect($('playlist-why').textContent).toContain('8 missing');
        $('playlist-why').click();
        const html = $('playlist-dropped').innerHTML;
        expect(html).toContain('5 · no reliable year');
        expect(html).toContain('3 · not scanned yet');
        expect(html).toContain('+ 2 more'); // 5 no-year songs, 3 shown
        expect(html).not.toContain('Tage wie diese');
        // The honest way out: the next gate that actually adds songs.
        expect(html).toContain('data-gate="balanced"');
        expect(html).toContain('Relax year accuracy → 40 usable');
        expect(html).toContain('data-way="scan"');
        // Empty reasons are not rendered at all.
        expect(html).not.toContain('not in your library');
    });

    it('hands the wizard the number for Continue, capped at songs per game', async () => {
        const { lib, adminState, $, onSourceChanged } = await mount({
            source: 'playlist', ma_playlist: PLAYLIST, size: 30,
        });
        await vi.waitFor(() => expect($('playlist-count').textContent).toContain('37'));
        expect(onSourceChanged).toHaveBeenCalled();
        expect(lib.getLibrarySourceStatus()).toEqual({ playlist: true, ready: true, songs: 30 });
        adminState.librarySize = 50;
        expect(lib.getLibrarySourceStatus().songs).toBe(37);
    });

    it('blocks Continue while no usable playlist is picked', async () => {
        const empty = { ...CHECK, usable: 0, usable_by_gate: {} };
        const { lib, $ } = await mount({ source: 'playlist', ma_playlist: PLAYLIST }, empty);
        await vi.waitFor(() => expect($('playlist-count').textContent).toBe('0 of 45 songs usable'));
        expect(lib.getLibrarySourceStatus()).toEqual({ playlist: true, ready: false, songs: null });
    });

    it('leaves the whole-library game untouched', async () => {
        const { lib, $, fetchImpl } = await mount({ popularity_percent: 20 });
        await new Promise((r) => setTimeout(r, 0));
        expect(lib.getLibrarySourceStatus()).toEqual({ playlist: false, ready: true, songs: null });
        expect($('playlist-row').classList.contains('hidden')).toBe(true);
        expect($('pop-row').classList.contains('hidden')).toBe(false);
        expect(fetchImpl.calls.some((u) => u.includes('/library-playlists/ma'))).toBe(false);
    });

    it('sends source and playlist in the start-game library config', async () => {
        const { lib } = await mount({ source: 'playlist', ma_playlist: PLAYLIST });
        await vi.waitFor(() => expect(lib.getLibraryConfig().source).toBe('playlist'));
        expect(lib.getLibraryConfig().ma_playlist).toEqual(PLAYLIST);
    });
});
