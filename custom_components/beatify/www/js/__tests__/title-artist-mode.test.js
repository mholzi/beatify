/**
 * #1664 item 3: the unified Title & Artist mode detector (isTitleArtistMode).
 *
 * Before this, player-game.js keyed off the top-level `title_artist_mode` flag
 * while player-reveal.js sniffed `title_artist_challenge.correct_title`. Those
 * diverge exactly when the mode is on but the challenge payload hasn't populated
 * yet — the reveal path would then wrongly show the year duel. This locks the
 * shared helper to the authoritative flag so both call sites agree.
 */
import { describe, it, expect } from 'vitest';

// player-utils.js touches window/document at module eval; stub before import.
global.window = {
    BeatifyUtils: {},
    location: { search: '' },
    matchMedia: () => ({ matches: false, addEventListener: () => {} }),
};
global.document = { getElementById: () => null };

const { isTitleArtistMode } = await import('../player-utils.js');

describe('isTitleArtistMode (#1664)', () => {
    it('is true when the top-level flag is set', () => {
        expect(isTitleArtistMode({ title_artist_mode: true })).toBe(true);
    });

    it('is false when the flag is off / absent', () => {
        expect(isTitleArtistMode({ title_artist_mode: false })).toBe(false);
        expect(isTitleArtistMode({})).toBe(false);
    });

    it('keys off the flag, NOT the challenge payload (the old reveal drift)', () => {
        // Mode on but challenge not yet populated → still title-artist mode.
        expect(isTitleArtistMode({ title_artist_mode: true, title_artist_challenge: null })).toBe(true);
        // Challenge present but mode flag off → NOT title-artist mode.
        expect(
            isTitleArtistMode({ title_artist_mode: false, title_artist_challenge: { correct_title: 'x' } })
        ).toBe(false);
    });

    it('is defensive about null/undefined input', () => {
        expect(isTitleArtistMode(null)).toBe(false);
        expect(isTitleArtistMode(undefined)).toBe(false);
    });
});
