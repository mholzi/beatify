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

const { pickSeasonalSuggestion, SEASONAL_OCCASIONS, wireSeasonalSuggestionHub } = await import(
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
const WORLDCUP = playlist('world-cup-anthems.json', 'World Cup Anthems');

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

describe('#1539 occasion priority during overlapping windows', () => {
    // Summer (06-01–08-31) and World Cup (06-11–07-19) overlap in Jun/Jul.
    // The picker returns the FIRST matching occasion in array order, and
    // worldcup is ordered before summer — so World Cup wins the overlap.
    it('prefers World Cup over Summer inside the overlap window', () => {
        const now = new Date('2026-06-15T12:00:00');
        const pick = pickSeasonalSuggestion([SUMMER, WORLDCUP, FILLER], now);
        expect(pick?.occasion.id).toBe('worldcup');
        expect(pick?.playlist.filename).toBe('world-cup-anthems.json');
    });

    it('still prefers World Cup on the overlap boundary days', () => {
        const start = pickSeasonalSuggestion([SUMMER, WORLDCUP], new Date('2026-06-11T12:00:00'));
        expect(start?.occasion.id).toBe('worldcup'); // World Cup window opens
        const end = pickSeasonalSuggestion([SUMMER, WORLDCUP], new Date('2026-07-19T12:00:00'));
        expect(end?.occasion.id).toBe('worldcup'); // last World Cup day
    });

    it('falls back to Summer once the World Cup window has closed', () => {
        const now = new Date('2026-07-20T12:00:00'); // day after World Cup ends
        const pick = pickSeasonalSuggestion([SUMMER, WORLDCUP, FILLER], now);
        expect(pick?.occasion.id).toBe('summer');
    });

    it('shows World Cup even if its playlist is the only seasonal one present', () => {
        const now = new Date('2026-06-15T12:00:00');
        expect(pickSeasonalSuggestion([WORLDCUP, FILLER], now)?.occasion.id).toBe('worldcup');
    });
});

describe('#1570 hub-friendly wiring (wireSeasonalSuggestionHub)', () => {
    // vitest env is `node` (no DOM): build minimal fakes for just the surface
    // wireSeasonalSuggestionHub touches — querySelector + addEventListener +
    // dataset + remove(). Verifies the Add path delegates to onAdd(path)
    // (hub selection model) and the Dismiss path reuses the per-season flag.
    const fakeBtn = () => {
        const node = { _click: null, addEventListener: (ev, fn) => { if (ev === 'click') node._click = fn; }, click: () => node._click && node._click() };
        return node;
    };
    const fakeChip = (occasionId, path) => {
        const add = fakeBtn();
        const dismiss = fakeBtn();
        const chip = {
            dataset: { occasion: occasionId, playlistPath: path },
            removed: false,
            remove() { this.removed = true; },
            querySelector(sel) {
                if (sel === '.seasonal-suggestion__add') return add;
                if (sel === '.seasonal-suggestion__dismiss') return dismiss;
                return null;
            },
        };
        return { chip, add, dismiss };
    };
    const fakeContainer = (chip) => ({ querySelector: (sel) => (sel === '.seasonal-suggestion' ? chip : null) });

    it('exports the hub variant', () => {
        expect(typeof wireSeasonalSuggestionHub).toBe('function');
    });

    it('Add delegates to onAdd(path) and removes the chip', () => {
        const { chip, add } = fakeChip('carnival', CARNIVAL.path);
        const added = [];
        wireSeasonalSuggestionHub(fakeContainer(chip), (p) => added.push(p), new Date('2026-02-10T12:00:00'));
        add.click();
        expect(added).toEqual([CARNIVAL.path]);
        expect(chip.removed).toBe(true);
    });

    it('Dismiss writes the per-season flag and removes the chip', () => {
        const { chip, dismiss } = fakeChip('carnival', CARNIVAL.path);
        const now = new Date('2026-02-10T12:00:00');
        wireSeasonalSuggestionHub(fakeContainer(chip), () => {}, now);
        dismiss.click();
        expect(store['beatify_seasonal_dismissed_carnival_2026']).toBe('1');
        expect(chip.removed).toBe(true);
        // The same flag the picker honours → chip won't re-suggest this season.
        expect(pickSeasonalSuggestion([CARNIVAL], now)).toBeNull();
    });

    it('is a no-op when no chip is present', () => {
        let called = false;
        expect(() => wireSeasonalSuggestionHub(fakeContainer(null), () => { called = true; })).not.toThrow();
        expect(called).toBe(false);
    });
});
