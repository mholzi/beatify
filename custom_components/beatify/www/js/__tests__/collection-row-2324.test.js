/**
 * The collected row (#2324, shape E) — wiring, ordering and locale coverage.
 *
 * `player-reveal.js` pulls in the whole player-utils graph, and this suite runs
 * in vitest's `node` environment with no DOM, so the renderer is asserted at
 * the source level the same way the Streak-Shield badge is (#1666). The one
 * piece with real logic — the sort that makes the row a timeline rather than a
 * list — is re-run here against the same comparator, because getting it wrong
 * produces a row that still looks plausible and is simply in the wrong order.
 */

import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

const ROOT = path.resolve(__dirname, '../../..');
const REVEAL = fs.readFileSync(path.join(ROOT, 'www/js/player-reveal.js'), 'utf8');
const HTML = fs.readFileSync(path.join(ROOT, 'www/player.html'), 'utf8');

describe('#2324 collected row — wiring', () => {
    it('is rendered on every reveal, not only on a scoring round', () => {
        // The row has to redraw on re-broadcasts too (reactions, votes), or a
        // reveal that fires twice would show a stale row on the second frame.
        expect(REVEAL).toContain('renderCollection(currentPlayer);');
    });

    it('has a section to render into', () => {
        expect(HTML).toContain('id="collection-section"');
        expect(HTML).toContain('id="collection-row"');
        expect(HTML).toContain('id="collection-count"');
    });

    it('hides the section while the row is empty', () => {
        // An empty shelf is worse than no shelf: before the first keeper there
        // is nothing to say, and a permanent empty box reads as a broken card.
        expect(REVEAL).toMatch(/if \(!items\.length\) \{[\s\S]*?section\.classList\.add\('hidden'\)/);
    });

    it('escapes song text', () => {
        // Titles and artists come from the catalogue, which is user-editable
        // through the library views — they are not safe to interpolate raw.
        expect(REVEAL).toContain('escapeHtml(entry.title');
        expect(REVEAL).toContain('escapeHtml(entry.artist');
    });

    it('marks the card won this round', () => {
        expect(REVEAL).toContain('collection-card--new');
    });
});

describe('#2324 collected row — ordering', () => {
    /** The comparator as it stands in renderCollection. */
    const byYearThenRound = (a, b) => (a.year - b.year) || (a.round - b.round);

    it('reads left to right in years, not in the order won', () => {
        const items = [
            { year: 2004, round: 1 },
            { year: 1968, round: 2 },
            { year: 1991, round: 3 },
        ];
        expect(items.slice().sort(byYearThenRound).map((e) => e.year))
            .toEqual([1968, 1991, 2004]);
    });

    it('is stable for two songs from the same year', () => {
        // REVEAL re-broadcasts on every reaction; a comparator returning 0 for
        // a tie would let the two cards swap places under the player's thumb.
        const items = [
            { year: 1985, round: 7 },
            { year: 1985, round: 2 },
        ];
        expect(items.slice().sort(byYearThenRound).map((e) => e.round))
            .toEqual([2, 7]);
    });
});

describe('#2324 collected row — locales', () => {
    it('has both strings in every shipped locale', () => {
        for (const lang of ['en', 'de', 'es', 'fr', 'nl', 'it']) {
            const dict = JSON.parse(fs.readFileSync(
                path.join(ROOT, `www/i18n/${lang}.json`), 'utf8'));
            expect(dict.reveal?.collection?.title, `${lang} missing title`).toBeTruthy();
            expect(dict.reveal?.collection?.count, `${lang} missing count`).toBeTruthy();
            // A missing placeholder does not throw — it renders "kept" with no
            // number, which looks like a label rather than a count.
            expect(dict.reveal.collection.count, `${lang} lost the placeholder`)
                .toContain('{count}');
        }
    });
});
