/**
 * #1586 — the Smart Playlist Mixer now offers a tracklist preview: a
 * "Preview tracklist" button asks the backend to assemble + de-dupe the mix in
 * preview mode (no file written) and renders the resulting `{title, artist,
 * year}` rows so the host sees exactly which songs land in the mix before
 * "Start mix" / saving as a community playlist.
 *
 * vitest env is `node` (no DOM) — these cover the pure markup builder
 * `_mixTracklistHtml`, which mix.js feeds the backend's `tracks` array into.
 */
import { describe, it, expect } from 'vitest';
import { _mixTracklistHtml } from '../admin/sections/mix.js';

const TRACKS_A = [
    { title: 'Take On Me', artist: 'a-ha', year: 1985 },
    { title: 'Billie Jean', artist: 'Michael Jackson', year: 1983 },
];

const TRACKS_B = [
    { title: 'Smells Like Teen Spirit', artist: 'Nirvana', year: 1991 },
];

describe('#1586 _mixTracklistHtml: tracklist preview rendering', () => {
    it('renders one row per track with title + artist + year', () => {
        const html = _mixTracklistHtml(TRACKS_A);
        // Two ordered-list items, one per track.
        expect((html.match(/<li class="mix-track">/g) || []).length).toBe(2);
        expect(html).toContain('Take On Me');
        expect(html).toContain('a-ha');
        expect(html).toContain('1985');
        expect(html).toContain('Billie Jean');
        expect(html).toContain('Michael Jackson');
        // Heading reflects the count.
        expect(html).toContain('2 tracks in this mix');
    });

    it('updates to show the new set when the tracks change', () => {
        const first = _mixTracklistHtml(TRACKS_A);
        const second = _mixTracklistHtml(TRACKS_B);
        // The re-render reflects the new set and drops the old entries.
        expect(second).toContain('Smells Like Teen Spirit');
        expect(second).toContain('Nirvana');
        expect(second).not.toContain('Take On Me');
        expect(second).toContain('1 tracks in this mix');
        expect((second.match(/<li class="mix-track">/g) || []).length).toBe(1);
        expect(first).not.toBe(second);
    });

    it('shows an empty-state message when there are no tracks', () => {
        const html = _mixTracklistHtml([]);
        expect(html).toContain('mix-tracklist-empty');
        expect(html).toContain('No tracks to preview.');
        expect(html).not.toContain('<li');
    });

    it('tolerates a non-array argument', () => {
        expect(_mixTracklistHtml(undefined)).toContain('mix-tracklist-empty');
        expect(_mixTracklistHtml(null)).toContain('mix-tracklist-empty');
    });

    it('escapes HTML in track title and artist', () => {
        const html = _mixTracklistHtml([
            { title: '<b>hax</b>', artist: 'A & B', year: 2000 },
        ]);
        expect(html).toContain('&lt;b&gt;hax&lt;/b&gt;');
        expect(html).toContain('A &amp; B');
        expect(html).not.toContain('<b>hax</b>');
    });

    it('omits the year span when no year is present', () => {
        const html = _mixTracklistHtml([{ title: 'Untagged', artist: 'Someone' }]);
        expect(html).toContain('Untagged');
        expect(html).not.toContain('mix-track-year');
    });
});
