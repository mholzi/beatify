/**
 * #1767 — the dashboard reassigned album-art `src` on every changed render.
 *
 * The #1705 coalescer only skips fully identical states; any real change (one
 * vote, one submission tick) passes through and renderPlayingView (:852) +
 * renderRevealView (:1090) unconditionally reassigned albumArt.src. Setting src
 * — even to the same URL — re-runs the browser image-load algorithm; on weak TV
 * hardware that's a re-decode + paint per broadcast during vote-heavy REVEALs.
 *
 * The fix mirrors the #1706/#1707 player-side guard (player-game.js): track the
 * last requested URL on the element (`_beatifyRequestedSrc`; album_art can be
 * relative so the resolved `.src` is unreliable) and skip the reassignment when
 * unchanged.
 *
 * dashboard.js is a self-contained IIFE with no exported helpers (it runs init()
 * + service-worker registration at import), and the vitest env is `node` (no
 * jsdom), so — as with dashboard-b8.test.js — this asserts the load-bearing
 * LOGIC of the fix. `applyAlbumArt` below is the album-art block copied VERBATIM
 * from both renderers; the test locks in its src-assignment behaviour.
 */
import { describe, it, expect, beforeEach } from 'vitest';

// Verbatim copy of the guarded album-art block now in renderPlayingView /
// renderRevealView (dashboard.js). Kept in sync with the source manually.
function applyAlbumArt(albumArt, song) {
    var newArtSrc = song.album_art || '/beatify/static/img/no-artwork.svg';
    if (albumArt._beatifyRequestedSrc !== newArtSrc) {
        albumArt._beatifyRequestedSrc = newArtSrc;
        albumArt.onerror = function() {
            this._beatifyRequestedSrc = null;
            this.src = '/beatify/static/img/no-artwork.svg';
        };
        albumArt.src = newArtSrc;
    }
}

/** Fake <img> that counts every `src` assignment (each = one image-load run). */
function makeImg() {
    let src = '';
    return {
        srcAssignments: 0,
        _beatifyRequestedSrc: undefined,
        onerror: null,
        set src(v) { this.srcAssignments += 1; src = v; },
        get src() { return src; },
    };
}

let img;
beforeEach(() => { img = makeImg(); });

describe('#1767 dashboard album-art unchanged-src guard', () => {
    it('assigns src once, then skips repeated renders of the same art', () => {
        const song = { album_art: 'https://ha.local/media/cover-42.jpg' };
        applyAlbumArt(img, song);
        expect(img.srcAssignments).toBe(1);

        // Vote-heavy REVEAL: 30 more changed broadcasts, same album art.
        for (let i = 0; i < 30; i++) applyAlbumArt(img, song);
        expect(img.srcAssignments).toBe(1);
        expect(img.src).toBe('https://ha.local/media/cover-42.jpg');
    });

    it('reassigns src when the art changes (next round)', () => {
        applyAlbumArt(img, { album_art: 'a.jpg' });
        applyAlbumArt(img, { album_art: 'b.jpg' });
        expect(img.srcAssignments).toBe(2);
        expect(img.src).toBe('b.jpg');
    });

    it('falls back to no-artwork placeholder when album_art is missing, once', () => {
        applyAlbumArt(img, {});
        applyAlbumArt(img, {});
        expect(img.srcAssignments).toBe(1);
        expect(img.src).toBe('/beatify/static/img/no-artwork.svg');
    });

    it('onerror resets the tracker so a later retry with the same url re-attempts', () => {
        const song = { album_art: 'flaky.jpg' };
        applyAlbumArt(img, song);
        expect(img.srcAssignments).toBe(1);

        // The load failed → placeholder swapped in and tracker cleared.
        img.onerror.call(img);
        expect(img.srcAssignments).toBe(2);
        expect(img.src).toBe('/beatify/static/img/no-artwork.svg');

        // Same URL arrives again on the next broadcast → guard lets it retry.
        applyAlbumArt(img, song);
        expect(img.srcAssignments).toBe(3);
        expect(img.src).toBe('flaky.jpg');
    });
});
