/**
 * #3019: the reveal leaderboard shows the same row badges as the round
 * leaderboard.
 *
 * The TV had two hand-copied row builders. The reveal copy never got the
 * sabotage badge (#2584) or the finalist badge (#2578), so both vanished the
 * moment the round flipped to the reveal — exactly when the room looks at the
 * TV and asks "who got hit?". Both renderers now share buildLeaderboardRowHtml.
 *
 * The shipped renderers are cut out of dashboard.js and run for real (see
 * helpers/js-source.js); `_reconcileRows` is stubbed to capture the rows.
 */
import { describe, it, expect } from 'vitest';
import { declaration, evaluate, locale, readSource } from './helpers/js-source.js';
import { doc, el, translator } from './helpers/mini-dom.js';

const DASHBOARD = readSource('dashboard.js');

global.window = global.window || {};
await import('../utils.js');
const U = global.window.BeatifyUtils;

function run(fnName, containerId, args, lang = 'en') {
    const container = el(containerId);
    let captured = null;
    evaluate(
        [
            declaration(DASHBOARD, 'buildLeaderboardRowHtml', 'dashboard.js'),
            declaration(DASHBOARD, fnName, 'dashboard.js'),
        ],
        fnName,
        {
            document: doc({ [containerId]: container }),
            utils: translator(locale(lang), { escapeHtml: U.escapeHtml }),
            _reconcileRows: (target, rows) => {
                expect(target).toBe(container);
                captured = rows;
            },
        },
    )(...args);
    return captured;
}

const reveal = (board, lang) =>
    run('renderRevealLeaderboard', 'reveal-leaderboard', [board], lang);
const playing = (board, lang) =>
    run('renderLeaderboard', 'dashboard-leaderboard', [board, null, 'dashboard-leaderboard', false, false], lang);
const rowFor = (rows, name) => rows.find((r) => r.key === name).html;

const SABOTAGE_BOARD = [
    { rank: 1, name: 'Anna', score: 84, rank_change: 0 },
    { rank: 2, name: 'Ben', score: 71, rank_change: -1, sabotaged_by: 'Anna', sabotage_effect: 'freeze' },
];

const PLAYOFF_BOARD = [
    { rank: 1, name: 'Anna', score: 84, playoff_spectator: false },
    { rank: 1, name: 'Bea', score: 84, playoff_spectator: false },
    { rank: 3, name: 'Clara', score: 66, playoff_spectator: true },
];

describe('#3019 reveal leaderboard keeps the row badges', () => {
    it('renders into #reveal-leaderboard', () => {
        expect(reveal(SABOTAGE_BOARD)).toHaveLength(2);
    });

    it('shows the sabotage badge on the hit player, naming the culprit', () => {
        const rows = reveal(SABOTAGE_BOARD, 'de');
        const ben = rowFor(rows, 'Ben');
        expect(ben).toContain('sabotage-badge');
        expect(ben).toContain('❄️ Anna');
        expect(ben).toContain(locale('de').sabotage.effect.freeze);
        expect(rowFor(rows, 'Anna')).not.toContain('sabotage-badge');
    });

    it('shows the finalist badge on the two finalists only', () => {
        const rows = reveal(PLAYOFF_BOARD);
        expect(rowFor(rows, 'Anna')).toContain('finalist-badge');
        expect(rowFor(rows, 'Bea')).toContain('finalist-badge');
        expect(rowFor(rows, 'Clara')).not.toContain('finalist-badge');
    });

    it('keeps its own rank-change arrows', () => {
        const ben = rowFor(reveal(SABOTAGE_BOARD), 'Ben');
        expect(ben).toContain('entry-change is-negative');
        expect(ben).not.toContain('rank-down');
    });

    it('matches the round leaderboard row for row, apart from the arrows', () => {
        const board = [...SABOTAGE_BOARD, { rank: 3, name: 'Cem', score: 40, rank_change: 2, streak: 5 }];
        const normalize = (html) => html
            .replace('entry-change is-positive', 'rank-up')
            .replace('entry-change is-negative', 'rank-down');
        const r = reveal(board);
        const p = playing(board);
        for (const name of ['Anna', 'Ben', 'Cem']) {
            expect(normalize(rowFor(r, name))).toBe(rowFor(p, name));
        }
    });
});
