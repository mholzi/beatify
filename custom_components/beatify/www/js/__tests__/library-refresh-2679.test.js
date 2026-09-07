/**
 * #2679 — the library sections must actually ask for a playlist refresh.
 *
 * Both `admin/sections/library.js` and `admin/sections/library-ai.js` write a
 * new playlist to the server and then have to tell the rest of the page that
 * the list changed. Both used to do it with
 *
 *     if (typeof window.loadPlaylists === 'function') window.loadPlaylists();
 *
 * on a global nothing in `www/` has ever assigned. The guard was permanently
 * false, the refresh never ran, and the "Mine" tab was stale after every save
 * for as long as the code existed. Nothing failed, because a guarded call on a
 * name nobody defines is invisible to every test that does not go looking for
 * it — which is the reason this suite exists rather than a comment.
 *
 * So the assertion is deliberately about the wiring itself: mount the real
 * panel, click the real button, and require that the injected `reloadPlaylists`
 * was called. Break the wiring — drop the parameter, drop the call, or hand it
 * to `openLibraryAiModal` without threading it through — and this goes red.
 * The `window` here is the #2637 sentinel, so a relapse to a page global does
 * not quietly pass either: reading one throws.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { bootPage, restoreGlobals, saveGlobals } from './helpers/admin-page.js';
import { block, evaluate, readSource } from './helpers/js-source.js';

beforeEach(saveGlobals);
afterEach(restoreGlobals);

/** A fetch that answers every endpoint the panel touches while mounting. */
function libraryFetch(overrides = {}) {
    return vi.fn(async (url) => {
        const u = String(url);
        for (const [needle, body] of Object.entries(overrides)) {
            if (u.includes(needle)) return { ok: true, status: 200, json: async () => body };
        }
        return { ok: true, status: 200, json: async () => ({}) };
    });
}

describe('#2679 the library panel refreshes the playlists after saving a mix', () => {
    it('calls the reloadPlaylists it was given', async () => {
        const fetchImpl = libraryFetch({
            '/library-playlists/generate': { saved: true, name: 'Fresh mix', songs: 30 },
        });
        const doc = bootPage(['library-settings'], { fetchImpl });
        const { mountLibraryPanel } = await import('../admin/sections/library.js');

        const reloadPlaylists = vi.fn();
        const root = doc.byId['library-settings'];
        mountLibraryPanel(root, { mode: 'admin', reloadPlaylists });

        const saveMix = root.querySelector('[data-lib="save-mix"]');
        expect(saveMix, 'admin mode must render the "save a fresh mix" button').not.toBeNull();
        saveMix.click();
        await vi.waitFor(() => expect(reloadPlaylists).toHaveBeenCalledTimes(1));
    });

    it('does not refresh when the server refused to save', async () => {
        // The refresh is a claim that the list changed. If nothing was written
        // there is nothing to re-pull, and a call here would paper over the
        // failure the toast is about to report.
        const fetchImpl = libraryFetch({
            '/library-playlists/generate': { saved: false, message: 'no pool yet' },
        });
        const doc = bootPage(['library-settings'], { fetchImpl });
        const { mountLibraryPanel } = await import('../admin/sections/library.js');

        const reloadPlaylists = vi.fn();
        const root = doc.byId['library-settings'];
        mountLibraryPanel(root, { mode: 'admin', reloadPlaylists });

        root.querySelector('[data-lib="save-mix"]').click();
        await new Promise((r) => setTimeout(r, 0));
        expect(reloadPlaylists).not.toHaveBeenCalled();
    });

    it('mounts without one — the wizard has no playlist list to refresh', async () => {
        // `mountLibraryPanel(root, { mode: 'wizard' })` in wizard.js passes no
        // reloadPlaylists. That must stay a no-op, not a TypeError.
        const doc = bootPage(['library-settings'], { fetchImpl: libraryFetch() });
        const { mountLibraryPanel } = await import('../admin/sections/library.js');
        const root = doc.byId['library-settings'];
        expect(() => mountLibraryPanel(root, { mode: 'admin' })).not.toThrow();
        expect(() => root.querySelector('[data-lib="save-mix"]').click()).not.toThrow();
    });

    it('hands the same refresh to the AI curation modal', async () => {
        // The two save paths are one feature. A fix that wires only the mix
        // button leaves "Create with AI…" exactly as stale as before, so the
        // hand-over is asserted rather than assumed.
        const doc = bootPage(['library-settings'], { fetchImpl: libraryFetch() });
        const library = await import('../admin/sections/library.js');
        const libraryAi = await import('../admin/sections/library-ai.js');
        const spy = vi.spyOn(libraryAi, 'openLibraryAiModal');

        const reloadPlaylists = vi.fn();
        const root = doc.byId['library-settings'];
        library.mountLibraryPanel(root, { mode: 'admin', reloadPlaylists });
        root.querySelector('[data-lib="ai-create"]').click();

        expect(spy).toHaveBeenCalledTimes(1);
        expect(spy.mock.calls[0][0]).toEqual({ reloadPlaylists });
    });
});

describe('#2679 the AI curation modal refreshes the playlists after saving', () => {
    it('calls the reloadPlaylists it was opened with', async () => {
        const resolved = { name: 'AI Mix', songs: [{ artist: 'A', title: 'B', year: 1999 }] };
        const fetchImpl = libraryFetch({
            '/library-playlists/resolve': { matched: 1, unmatched: [], playlist: resolved },
            '/playlists/save': { success: true },
        });
        const doc = bootPage([], { fetchImpl });
        const { openLibraryAiModal } = await import('../admin/sections/library-ai.js');

        const reloadPlaylists = vi.fn();
        openLibraryAiModal({ reloadPlaylists });

        const modal = doc.body.querySelector('[id="library-ai-modal"]');
        expect(modal, 'opening the modal must attach it to the page').not.toBeNull();
        modal.querySelector('[data-ai="paste"]').value = JSON.stringify({
            songs: [{ artist: 'A', title: 'B' }],
        });
        modal.querySelector('[data-ai="resolve"]').click();
        await vi.waitFor(() => expect(modal.querySelector('[data-ai="save"]').disabled).toBe(false));

        modal.querySelector('[data-ai="save"]').click();
        await vi.waitFor(() => expect(reloadPlaylists).toHaveBeenCalledTimes(1));
    });

    it('does not refresh when the save failed', async () => {
        const resolved = { name: 'AI Mix', songs: [{ artist: 'A', title: 'B', year: 1999 }] };
        const fetchImpl = vi.fn(async (url) => {
            const u = String(url);
            if (u.includes('/library-playlists/resolve')) {
                return { ok: true, status: 200, json: async () => ({ matched: 1, unmatched: [], playlist: resolved }) };
            }
            if (u.includes('/playlists/save')) {
                return { ok: false, status: 500, json: async () => ({ message: 'disk full' }) };
            }
            return { ok: true, status: 200, json: async () => ({}) };
        });
        const doc = bootPage([], { fetchImpl });
        const { openLibraryAiModal } = await import('../admin/sections/library-ai.js');

        const reloadPlaylists = vi.fn();
        openLibraryAiModal({ reloadPlaylists });

        const modal = doc.body.querySelector('[id="library-ai-modal"]');
        modal.querySelector('[data-ai="paste"]').value = JSON.stringify({
            songs: [{ artist: 'A', title: 'B' }],
        });
        modal.querySelector('[data-ai="resolve"]').click();
        await vi.waitFor(() => expect(modal.querySelector('[data-ai="save"]').disabled).toBe(false));

        modal.querySelector('[data-ai="save"]').click();
        await vi.waitFor(() => expect(modal.querySelector('[data-ai="save"]').disabled).toBe(false));
        expect(reloadPlaylists).not.toHaveBeenCalled();
    });
});

describe('#2679 the dependency reaches the panel from the page init', () => {
    /**
     * The two tests above prove the panel uses what it is handed. This one
     * covers the rest of the chain, because a refresh that is never injected is
     * exactly as stale as a refresh that is never called — and that is the half
     * `window.loadPlaylists` hid for so long.
     */
    it('game-settings passes its reloadPlaylists down to the Crate Digger panel', async () => {
        const fetchImpl = vi.fn(async (url) => {
            if (String(url).includes('/library-playlists/generate')) {
                return { ok: true, status: 200, json: async () => ({ saved: true, name: 'Fresh mix', songs: 30 }) };
            }
            return { ok: true, status: 200, json: async () => ({}) };
        });
        const doc = bootPage(['library-settings'], { fetchImpl });
        const { setupGameSettings } = await import('../admin/sections/game-settings.js');

        const reloadPlaylists = vi.fn();
        setupGameSettings({ reloadPlaylists });

        const saveMix = doc.byId['library-settings'].querySelector('[data-lib="save-mix"]');
        expect(saveMix, 'setupGameSettings must have mounted the library panel').not.toBeNull();
        saveMix.click();
        await vi.waitFor(() => expect(reloadPlaylists).toHaveBeenCalledTimes(1));
    });

    it('admin.js hands setupGameSettings its own status reload', () => {
        // admin.js's init() is a few hundred lines of page wiring and cannot be
        // booted in this environment, so the call site itself is cut out of the
        // shipped file and run against stubs (helpers/js-source.js). These are
        // the bytes that ship: drop the argument and the assertion below fails;
        // delete the call and `block` throws naming the file.
        //
        // The header is anchored on the newline + indent of the statement, not
        // on the bare name: admin.js also *describes* this call in a comment a
        // few hundred lines up, and a header that matched prose would cut out
        // the wrong bytes.
        const call = block(readSource('admin.js'), '\n    setupGameSettings({', 'admin.js');
        const setupGameSettings = vi.fn();
        const loadStatus = () => {};
        evaluate([`${call});`], 'null', { setupGameSettings, loadStatus });

        expect(setupGameSettings).toHaveBeenCalledTimes(1);
        expect(setupGameSettings.mock.calls[0][0].reloadPlaylists).toBe(loadStatus);
    });
});
