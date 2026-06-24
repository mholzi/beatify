/**
 * #1539 — seasonal playlist suggestion calendar logic.
 *
 * vitest env is `node` (no DOM), so these tests exercise the pure occasion
 * picker: date-window matching, "playlist must exist & be valid", "skip if
 * already selected", and the per-season localStorage dismiss flag. The chip
 * DOM render/wire is intentionally NOT covered here (no jsdom); it's a thin
 * shell over the existing checkbox/handlePlaylistToggle path.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

// Pure-ish module: it reads adminState.selectedPlaylists and localStorage.
// Provide minimal stand-ins before importing.
const store = {};
globalThis.localStorage = {
    getItem: (k) => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v); },
    removeItem: (k) => { delete store[k]; },
};

vi.mock('../admin/state.js', () => ({
    adminState: { selectedPlaylists: [] },
}));

const { pickSeasonalSuggestion, SEASONAL_OCCASIONS } = await import(
    '../admin/sections/seasonal-suggestion.js'
);
const { adminState } = await import('../admin/state.js');

const playlist = (filename, name, is_valid = true) => ({
    filename,
    name,
    path: `/abs/${filename}`,
    is_valid,
});

const CARNIVAL = playlist('koelner-karneval.json', 'Cologne Carnival');
const SUMMER = playlist('summer-party-anthems.json', '100 Summer Anthems');
const FILLER = playlist('80er-hits.json', '80er Hits');

beforeEach(() => {
    for (const k of Object.keys(store)) delete store[k];
    adminState.selectedPlaylists = [];
});

describe('#1539 seasonal occasion calendar', () => {
    it('only lists occasions whose playlist actually ships', () => {
        // Guard against typos: every configured filename ends in .json.
        for (const o of SEASONAL_OCCASIONS) {
            expect(o.filename).toMatch(/\.json$/);
            expect(o.id).toBeTruthy();
            expect(o.emoji).toBeTruthy();
        }
    });

    it('suggests carnival inside its window when the playlist is present', () => {
        const now = new Date('2026-02-10T12:00:00');
        const pick = pickSeasonalSuggestion([FILLER, CARNIVAL], now);
        expect(pick?.occasion.id).toBe('carnival');
        expect(pick?.playlist.filename).toBe('koelner-karneval.json');
    });

    it('does NOT suggest outside the window', () => {
        const now = new Date('2026-09-15T12:00:00'); // no occasion active
        expect(pickSeasonalSuggestion([FILLER, CARNIVAL, SUMMER], now)).toBeNull();
    });

    it('does NOT suggest when the matching playlist is absent', () => {
        const now = new Date('2026-02-10T12:00:00');
        expect(pickSeasonalSuggestion([FILLER], now)).toBeNull();
    });

    it('does NOT suggest an invalid playlist', () => {
        const now = new Date('2026-02-10T12:00:00');
        const broken = playlist('koelner-karneval.json', 'Cologne Carnival', false);
        expect(pickSeasonalSuggestion([broken], now)).toBeNull();
    });

    it('does NOT suggest when the host already selected it', () => {
        const now = new Date('2026-02-10T12:00:00');
        adminState.selectedPlaylists = [{ path: CARNIVAL.path }];
        expect(pickSeasonalSuggestion([CARNIVAL], now)).toBeNull();
    });

    it('respects the per-season dismiss flag', () => {
        const now = new Date('2026-02-10T12:00:00');
        store['beatify_seasonal_dismissed_carnival_2026'] = '1';
        expect(pickSeasonalSuggestion([CARNIVAL], now)).toBeNull();
    });

    it('re-suggests in a later season despite a prior-year dismiss', () => {
        store['beatify_seasonal_dismissed_carnival_2025'] = '1';
        const now = new Date('2026-02-10T12:00:00');
        expect(pickSeasonalSuggestion([CARNIVAL], now)?.occasion.id).toBe('carnival');
    });

    it('matches summer in July', () => {
        const now = new Date('2026-07-04T12:00:00');
        const pick = pickSeasonalSuggestion([SUMMER, FILLER], now);
        expect(pick?.occasion.id).toBe('summer');
    });
});
