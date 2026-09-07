/**
 * #2697: the song-statistics code targeted containers that had been removed.
 *
 * When the section became compact rows, `analytics.html` lost
 * `#playlist-song-stats`, `#song-stats-empty` and `#song-summary-cards`, but
 * `analytics.js` kept rendering into them. `renderPlaylistSongGrid`,
 * `showSongStatsEmpty`, `handleSummaryCardClick` and the delegated
 * `.view-details-btn` listener were all early-return no-ops: the empty state
 * never appeared (the rows just read `--`) and a row tap did nothing, so
 * "View All Songs" always opened `by_playlist[0]` whichever row was tapped.
 *
 * A `getElementById` on a missing id is silent — it returns null and the
 * guard clause above it swallows the miss. So the guard here is mechanical:
 * every id analytics.js reaches for must exist in analytics.html.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const JS = join(__dirname, '..');
const WWW = join(__dirname, '..', '..');

const js = readFileSync(join(JS, 'analytics.js'), 'utf8');
const html = readFileSync(join(WWW, 'analytics.html'), 'utf8');

const htmlIds = new Set([...html.matchAll(/\bid="([^"]+)"/g)].map((m) => m[1]));
const jsIds = [...js.matchAll(/getElementById\('([^']+)'\)/g)].map((m) => m[1]);

// The comments below still name the removed containers on purpose — the
// history is why the rebind looks the way it does. Only executable code counts.
const code = js.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');

describe('#2697 analytics.js only targets elements the page has', () => {
    it('reads a plausible number of ids from both sides', () => {
        expect(htmlIds.size).toBeGreaterThan(10);
        expect(jsIds.length).toBeGreaterThan(10);
    });

    it('every getElementById target exists in analytics.html', () => {
        const missing = [...new Set(jsIds)].filter((id) => !htmlIds.has(id));
        expect(missing).toEqual([]);
    });

    it('the removed containers are gone from the JS', () => {
        for (const dead of [
            'playlist-song-stats',
            'song-stats-empty',
            'song-summary-cards',
            'view-details-btn',
            'song-summary-card',
        ]) {
            expect(code).not.toContain(dead);
        }
    });
});

describe('#2697 the live summary rows open their own playlist', () => {
    it('binds row activation to the container the page actually has', () => {
        expect(js).toContain("getElementById('song-summary-compact')");
        expect(js).toContain("closest('.song-row')");
        expect(html).toContain('id="song-summary-compact"');
    });

    it('slugs the playlist name the way the server derives playlist_id', () => {
        // services/stats.py compute_song_stats():
        //   "playlist_id": playlist_name.lower().replace(" ", "-")
        // The API hands the row a playlist NAME, so the two must agree or the
        // modal lookup finds nothing and the tap is silently inert again.
        expect(js).toContain(".toLowerCase().replace(/ /g, '-')");
    });

    it('keeps the rows reachable by keyboard', () => {
        // They are <div>s, so role/tabindex and an Enter/Space handler are the
        // only things making them operable at all.
        expect(js).toContain("row.setAttribute('role', 'button')");
        expect(js).toContain("addEventListener('keydown'");
    });
});
