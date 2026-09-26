/**
 * #2965 — at 1280×720 the late-join card covered the lowest leaderboard rows.
 *
 * The card ("Still open") is fixed to the bottom-right corner. From 1600 px up
 * the leaderboard keeps its footprint free (#2834); below that the column was
 * too narrow to give up 260 px, so the rule was switched off, and with five
 * players at 720p the last two names sat under the card. Between 1200 and
 * 1599 px the width now comes out of the artwork column, which was a fixed
 * 640 px around art that is only min(480px, 45vh) wide.
 *
 * The layout is pure CSS; this test reads the shipped rules and does the
 * arithmetic the browser does for the two screens named in the issue, so a
 * later change to any of the numbers has to keep the rows clear of the card.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { WWW_DIR } from './helpers/js-source.js';

const CSS = readFileSync(join(WWW_DIR, 'css', 'dashboard.css'), 'utf8');

const px = (re) => {
    const m = CSS.match(re);
    if (!m) throw new Error(`rule not found: ${re}`);
    return Number(m[1]);
};

// Shipped numbers.
const CORNER_MAX_W = px(/\.join-corner \{[^}]*max-width: (\d+)px/);
const RESERVE = px(/body\.join-corner-open \.playing-right-section \.dashboard-leaderboard \{\s*padding-right: calc\(clamp\(16px, 2\.2vw, 40px\) \+ (\d+)px\)/);
const CONTENT_PAD_X = px(/\n\.dashboard-playing-content \{[^}]*padding: \d+px (\d+)px/);
const MID = CSS.match(/@media \(min-width: 1200px\) and \(max-width: 1599px\) \{\s*\.dashboard-playing-content \{\s*grid-template-columns: min\(640px, (\d+)vh\) minmax\(0, 1fr\);\s*gap: (\d+)px;/);

function inset(width) {
    return Math.min(40, Math.max(16, width * 0.022));
}

/** Where the rows end and where the card starts, in viewport pixels. */
function geometry(width, height) {
    const artCol = Math.min(640, (Number(MID[1]) / 100) * height);
    const gap = Number(MID[2]);
    const rowsLeft = CONTENT_PAD_X + artCol + gap;
    const rowsRight = width - CONTENT_PAD_X - (inset(width) + RESERVE);
    const cardLeft = width - inset(width) - CORNER_MAX_W;
    return { rowsLeft, rowsRight, cardLeft, rowWidth: rowsRight - rowsLeft };
}

describe('#2965 the leaderboard ends before the join card on 720p/768p TVs', () => {
    it('has the 1200–1599 px rule that narrows the artwork column', () => {
        expect(MID).not.toBeNull();
    });

    it('no longer switches the reservation off above 1199 px', () => {
        expect(CSS).not.toMatch(/@media \(max-width: 1599px\) \{\s*body\.join-corner-open \.playing-right-section \.dashboard-leaderboard/);
        expect(CSS).toMatch(/@media \(max-width: 1199px\) \{\s*body\.join-corner-open \.playing-right-section \.dashboard-leaderboard \{\s*padding-right: 0;/);
    });

    for (const [w, h] of [[1280, 720], [1366, 768], [1440, 900]]) {
        it(`${w}×${h}: rows stop left of the card and stay wide`, () => {
            const g = geometry(w, h);
            expect(g.rowsRight).toBeLessThan(g.cardLeft);
            // Rank circle, a name and a three-digit score still fit comfortably.
            expect(g.rowWidth).toBeGreaterThanOrEqual(480);
            // The art (min(480px, 45vh)) still fits its narrower column.
            expect(Math.min(640, (Number(MID[1]) / 100) * h)).toBeGreaterThan(Math.min(480, 0.45 * h));
        });
    }
});
