/**
 * #2993: at phone width the host's "Bring back" button clipped the sat-out
 * badge after "sat", because the badge sat inside `.entry-name` (which
 * ellipsises) on the same line as the button. The sat-out row now wraps: the
 * badge is a sibling of `.entry-name` and only that row carries the wrap
 * class, so the CSS can move badge + button to a second line.
 *
 * Runs the real `renderAdminLeaderboard`.
 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { renderAdminLeaderboard } from '../admin/sections/render-helpers.js';

let els;

beforeEach(() => {
    els = {};
    globalThis.window = globalThis;
    globalThis.BeatifyUtils = { escapeHtml: (s) => String(s) };
    globalThis.document = {
        getElementById: (id) => (els[id] || (els[id] = { innerHTML: '' })),
    };
});

afterEach(() => {
    delete globalThis.BeatifyUtils;
    delete globalThis.document;
    delete globalThis.window;
});

const PLAYERS = [
    { rank: 1, name: 'Anna', score: 60, streak: 3 },
    { rank: 2, name: 'Ben', score: 45, rank_change: 1 },
    { rank: 3, name: 'Mia', score: 30, sat_out_by_host: true },
    { rank: 4, name: 'Leo', score: 20 },
    { rank: 5, name: 'Sofia', score: 10, connected: false },
];

function rows(withHostControls) {
    renderAdminLeaderboard(PLAYERS, 'admin-playing-leaderboard-list', withHostControls);
    const html = els['admin-playing-leaderboard-list'].innerHTML;
    // Each row is one top-level <div class="leaderboard-entry ...">…</div>.
    return html.split('<div class="leaderboard-entry').slice(1).map((r) => '<div class="leaderboard-entry' + r);
}

function rowClasses(row) {
    return row.match(/^<div class="([^"]*)"/)[1].split(/\s+/).filter(Boolean);
}

function entryName(row) {
    return row.match(/<span class="entry-name">([\s\S]*?)<\/span><span class="entry-meta">/)[1];
}

describe('#2993 sat-out row wraps in the admin leaderboard', () => {
    it.each([true, false])('the badge is outside .entry-name (host controls: %s)', (withHostControls) => {
        const mia = rows(withHostControls)[2];
        expect(entryName(mia)).toBe('Mia');
        expect(entryName(mia)).not.toContain('sat-out-badge');
        // …and it follows the score, before the host's button.
        const score = mia.indexOf('class="entry-score"');
        const badge = mia.indexOf('class="sat-out-badge"');
        expect(badge).toBeGreaterThan(score);
        if (withHostControls) {
            expect(mia.indexOf('data-action="reinstate"')).toBeGreaterThan(badge);
        }
    });

    it('only the sat-out row gets the wrap class', () => {
        const all = rows(true);
        const wrapped = all.map((r) => rowClasses(r).includes('leaderboard-entry--wrap'));
        expect(wrapped).toEqual([false, false, true, false, false]);
        expect(rowClasses(all[2])).toContain('is-sat-out');
    });

    it('rank and score of the sat-out guest stay visible (#2746)', () => {
        const mia = rows(true)[2];
        expect(mia).toContain('<span class="entry-rank">#3</span>');
        expect(mia).toContain('<span class="entry-score">30</span>');
    });

    it('the away badge stays inside .entry-name', () => {
        const sofia = rows(true)[4];
        expect(entryName(sofia)).toContain('away-badge');
        expect(rowClasses(sofia)).not.toContain('leaderboard-entry--wrap');
    });
});
