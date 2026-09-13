/**
 * #2821 — the reveal standings were unreadable outside year mode.
 *
 * #2502 capped the year-mode card at eight rows (seven plus "+ N more") and
 * gave it plain 24 px rows. Title & Artist mode kept rows that shrank with the
 * player count until the text was a few pixels tall. It now gets the same
 * pattern with its taller card: past ten rows, nine plus "+ N more". The CSS
 * hides rows from the same index, so the number in the line has to match.
 */
import { describe, it, expect } from 'vitest';
import { declaration, evaluate, locale, readSource } from './helpers/js-source.js';
import { doc, el, translator } from './helpers/mini-dom.js';

const DASHBOARD = readSource('dashboard.js');
const CSS = readSource('../css/dashboard.css');

function setup() {
    const root = el('dashboard-reveal');
    const more = el('reveal-leaderboard-more');
    more.classList.add('hidden');
    const fn = evaluate([declaration(DASHBOARD, 'renderStandingsMore')], 'renderStandingsMore', {
        document: doc({ 'dashboard-reveal': root, 'reveal-leaderboard-more': more }),
        utils: translator(locale('en')),
    });
    return { fn, root, more };
}

describe('#2821 standings cap', () => {
    it('keeps the year-mode cap at eight', () => {
        const r = setup();
        r.fn(8, true);
        expect(r.root.classList.contains('reveal-standings-capped')).toBe(false);
        r.fn(20, true);
        expect(r.root.classList.contains('reveal-standings-capped')).toBe(true);
        expect(r.more.textContent).toContain('13');
    });

    it('caps Title & Artist mode past ten rows with nine shown', () => {
        const r = setup();
        r.fn(10, false);
        expect(r.root.classList.contains('reveal-standings-capped')).toBe(false);
        expect(r.more.classList.contains('hidden')).toBe(true);
        r.fn(20, false);
        expect(r.root.classList.contains('reveal-standings-capped')).toBe(true);
        expect(r.more.classList.contains('hidden')).toBe(false);
        expect(r.more.textContent).toContain('11');
    });

    it('hides rows in CSS from the index the line counts from', () => {
        expect(CSS).toMatch(/reveal-standings-capped\.reveal-axis-mode #reveal-leaderboard \.leaderboard-entry:nth-child\(n\+8\)/);
        expect(CSS).toMatch(/reveal-standings-capped:not\(\.reveal-axis-mode\) #reveal-leaderboard \.leaderboard-entry:nth-child\(n\+10\)/);
    });
});
