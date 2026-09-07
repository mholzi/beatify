/**
 * #2578, TV side: the finalists get a badge, nobody gets a skull.
 *
 * Design variant B. The server no longer marks non-leaders `eliminated`, so
 * the skulls disappear on their own; what is added is the positive statement —
 * two players are in the playoff.
 *
 * #2701: the badge used to be checked by grepping `dashboard.js` for
 * `'playoffLaeuft && !entry.playoff_spectator'`. That fails on a rename of a
 * German local and passes if the badge is attached to the wrong row. The
 * renderer is run for real here instead: `renderLeaderboard` is cut out of the
 * shipped file and given a `_reconcileRows` stub that captures the rows it
 * builds, so the assertions are about which player carries the badge.
 */
import { describe, it, expect } from 'vitest';
import { declaration, evaluate, locale, readSource } from './helpers/js-source.js';
import { doc, el, translator } from './helpers/mini-dom.js';

const DASHBOARD = readSource('dashboard.js');

global.window = global.window || {};
await import('../utils.js');
const U = global.window.BeatifyUtils;

/**
 * Run the shipped `renderLeaderboard` and return the HTML it produced per row.
 * `_reconcileRows` is where the rows meet the DOM, so stubbing it captures the
 * complete output without needing a diffing DOM.
 */
function renderRows(leaderboard, { lang = 'en', players = null } = {}) {
    const container = el('leaderboard');
    let captured = null;
    evaluate(
        declaration(DASHBOARD, 'renderLeaderboard', 'dashboard.js'),
        'renderLeaderboard',
        {
            document: doc({ leaderboard: container }),
            utils: translator(locale(lang), { escapeHtml: U.escapeHtml }),
            _reconcileRows: (target, rows) => {
                expect(target).toBe(container);
                captured = rows;
            },
        },
    )(leaderboard, players, 'leaderboard', false, false);
    return captured;
}

const rowFor = (rows, name) => rows.find((r) => r.key === name).html;

describe('#2578 playoff spectators on the TV', () => {
    it('hydrateLeaderboard carries playoff_spectator', () => {
        const out = U.hydrateLeaderboard(
            [
                { rank: 1, name: 'Anna', rank_change: 0 },
                { rank: 3, name: 'Clara', rank_change: 0 },
            ],
            [
                { name: 'Anna', score: 84, playoff_spectator: false },
                { name: 'Clara', score: 66, playoff_spectator: true },
            ],
        );
        expect(out[0].playoff_spectator).toBe(false);
        expect(out[1].playoff_spectator).toBe(true);
    });

    it('badges the finalists and leaves the spectators plain', () => {
        const rows = renderRows([
            { rank: 1, name: 'Anna', score: 84, playoff_spectator: false },
            { rank: 1, name: 'Bea', score: 84, playoff_spectator: false },
            { rank: 3, name: 'Clara', score: 66, playoff_spectator: true },
            { rank: 4, name: 'Dana', score: 51, playoff_spectator: true },
        ]);
        expect(rowFor(rows, 'Anna')).toContain('finalist-badge');
        expect(rowFor(rows, 'Bea')).toContain('finalist-badge');
        expect(rowFor(rows, 'Clara')).not.toContain('finalist-badge');
        expect(rowFor(rows, 'Dana')).not.toContain('finalist-badge');
    });

    it('nobody gets a skull for standing outside the playoff', () => {
        // The regression that started #2578: six of eight rows rendered 💀
        // although nobody had been eliminated.
        const rows = renderRows([
            { rank: 1, name: 'Anna', score: 84, playoff_spectator: false },
            { rank: 3, name: 'Clara', score: 66, playoff_spectator: true },
        ]);
        expect(rows.map((r) => r.html).join('')).not.toContain('💀');
    });

    it('the badge only appears while a playoff is running', () => {
        // Derived from the data, not from a separate flag that could go stale:
        // with no spectator in the board there is no playoff, so no badge.
        const rows = renderRows([
            { rank: 1, name: 'Anna', score: 84, playoff_spectator: false },
            { rank: 2, name: 'Clara', score: 66, playoff_spectator: false },
        ]);
        expect(rows.map((r) => r.html).join('')).not.toContain('finalist-badge');
    });

    it('the badge carries the translated label, not a literal', () => {
        const rows = renderRows(
            [
                { rank: 1, name: 'Anna', score: 84, playoff_spectator: false },
                { rank: 3, name: 'Clara', score: 66, playoff_spectator: true },
            ],
            { lang: 'de' },
        );
        expect(rowFor(rows, 'Anna')).toContain(locale('de').reveal.finalePlayoff);
    });

    it('the label exists in all six locales', () => {
        for (const l of ['en', 'de', 'es', 'fr', 'it', 'nl']) {
            expect(locale(l).reveal?.finalePlayoff, l).toBeTruthy();
        }
    });
});
