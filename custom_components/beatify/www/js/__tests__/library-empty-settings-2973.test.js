/**
 * #2973: the wizard's library step read "Song popularity Top undefined%".
 *
 * With no saved library settings (the server answers `{}` and localStorage
 * holds nothing) nothing ever gave `adminState.libraryPopPercent` a value:
 * the panel's `syncControls()` wrote `Top ${undefined}%` over the markup's
 * "Top 50%", and the slider value became NaN. The same gap left the
 * songs-per-game and scan-size selects blank. adminState now starts with the
 * defaults the markup and the backend already assume.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { bootPage, restoreGlobals, saveGlobals } from './helpers/admin-page.js';

beforeEach(saveGlobals);
afterEach(restoreGlobals);

function fetchFor(settings) {
    return vi.fn(async (url) => {
        const u = String(url);
        let body = {};
        if (u.includes('/library-settings')) body = settings;
        return { ok: true, status: 200, json: async () => body };
    });
}

async function mount(settings) {
    const doc = bootPage(['library-settings'], { fetchImpl: fetchFor(settings) });
    const lib = await import('../admin/sections/library.js');
    const { adminState } = await import('../admin/state.js');
    const root = doc.byId['library-settings'];
    lib.mountLibraryPanel(root, { mode: 'wizard' });
    const $ = (k) => root.querySelector(`[data-lib="${k}"]`);
    return { lib, adminState, $ };
}

describe('#2973 empty library settings fall back to the defaults', () => {
    it('shows "Top 50%" and a valid slider position, never "undefined"', async () => {
        const { $ } = await mount({});
        await vi.waitFor(() => expect($('pop-value').textContent).toBe('Top 50%'));
        expect($('pop-value').textContent).not.toContain('undefined');
        // The slider is inverted: stored 50 % sits at 101 − 50.
        expect($('pop-range').value).toBe('51');
    });

    it('keeps every control on a real value', async () => {
        const { $ } = await mount({});
        await vi.waitFor(() => expect($('pop-value').textContent).toBe('Top 50%'));
        expect($('size').value).toBe('30');
        expect($('scan-size').value).toBe('2500');
        expect($('year-gate').value).toBe('strict');
    });

    it('sends the defaults it shows with the start-game payload', async () => {
        const { lib } = await mount({});
        const cfg = lib.getLibraryConfig();
        expect(cfg.popularity_percent).toBe(50);
        expect(cfg.size).toBe(30);
        expect(cfg.year_gate).toBe('strict');
    });

    it('still takes the saved value when there is one', async () => {
        const { $ } = await mount({ popularity_percent: 20, size: 50 });
        await vi.waitFor(() => expect($('pop-value').textContent).toBe('Top 20%'));
        expect($('size').value).toBe('50');
    });
});
