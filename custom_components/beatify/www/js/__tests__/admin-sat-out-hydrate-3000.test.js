/**
 * #3000: in PLAYING/REVEAL the server sends slim leaderboard entries
 * ({rank, name, rank_change}); `sat_out_by_host` only rides in `players[]`.
 * `hydrateLeaderboard()` did not carry it over, so the host's leaderboard never
 * showed the sat-out badge or the "Bring back" button (#2746, #2993).
 *
 * Runs the real `hydrateLeaderboard` into the real `renderAdminLeaderboard`,
 * the same two steps `renderAdminState` takes.
 */
import { describe, it, expect, beforeAll, beforeEach } from 'vitest';
import { renderAdminLeaderboard } from '../admin/sections/render-helpers.js';

globalThis.window = globalThis.window || globalThis;
await import('../utils.js');
const U = globalThis.window.BeatifyUtils;

let els;

beforeAll(() => {
    globalThis.BeatifyUtils = U;
});

beforeEach(() => {
    els = {};
    globalThis.document = {
        getElementById: (id) => (els[id] || (els[id] = { innerHTML: '', textContent: '' })),
    };
});

// Shape of the live-test frame: slim leaderboard, full players array.
const LEADERBOARD = [
    { rank: 1, name: 'Dieter', rank_change: 0 },
    { rank: 2, name: 'Ben', rank_change: 0 },
];
const PLAYERS = [
    { name: 'Dieter', score: 40, connected: true, sat_out_by_host: true },
    { name: 'Ben', score: 20, connected: true, sat_out_by_host: false },
];

function renderedRows() {
    const hydrated = U.hydrateLeaderboard(LEADERBOARD, PLAYERS);
    renderAdminLeaderboard(hydrated, null, true);
    return ['admin-playing-leaderboard-list', 'admin-reveal-leaderboard'].map((id) =>
        els[id].innerHTML.split('<div class="leaderboard-entry').slice(1)
    );
}

describe('#3000 sat-out state reaches the admin leaderboard', () => {
    it('hydrateLeaderboard carries sat_out_by_host from players[]', () => {
        const [dieter, ben] = U.hydrateLeaderboard(LEADERBOARD, PLAYERS);
        expect(dieter.sat_out_by_host).toBe(true);
        expect(ben.sat_out_by_host).toBe(false);
    });

    it('both admin lists show the badge and "Bring back" for the sat-out guest', () => {
        for (const [dieter, ben] of renderedRows()) {
            expect(dieter).toContain('is-sat-out');
            expect(dieter).toContain('leaderboard-entry--wrap');
            expect(dieter).toContain('class="sat-out-badge"');
            expect(dieter).toContain('data-action="reinstate"');
            expect(dieter).not.toContain('data-action="sit-out"');

            expect(ben).not.toContain('is-sat-out');
            expect(ben).toContain('data-action="sit-out"');
        }
    });

    it('an entry that already carries the field keeps its own value', () => {
        const [dieter] = U.hydrateLeaderboard(
            [{ rank: 1, name: 'Dieter', sat_out_by_host: false }],
            PLAYERS
        );
        expect(dieter.sat_out_by_host).toBe(false);
    });
});
