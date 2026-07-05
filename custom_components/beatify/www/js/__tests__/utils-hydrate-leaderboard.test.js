/**
 * Tests for BeatifyUtils.hydrateLeaderboard (#1765).
 *
 * The server now sends the in-round leaderboard as slim {rank, name,
 * rank_change} entries; the per-player fields (score, streak, is_admin,
 * connected, eliminated, eliminated_round) ride in the same frame's players
 * array and are re-attached client-side by this helper on receipt. These tests
 * lock the join so every downstream render path keeps seeing full entries.
 */
import { describe, it, expect } from 'vitest';

// utils.js assigns to window.BeatifyUtils at eval; stub the global first.
global.window = global.window || {};
await import('../utils.js');
const U = global.window.BeatifyUtils;

describe('BeatifyUtils.hydrateLeaderboard (#1765)', () => {
    it('re-attaches per-player fields onto slim entries by name', () => {
        const leaderboard = [
            { rank: 1, name: 'Bob', rank_change: 1 },
            { rank: 2, name: 'Alice', rank_change: -1 },
        ];
        const players = [
            {
                name: 'Alice',
                score: 50,
                streak: 2,
                is_admin: false,
                connected: true,
                eliminated: false,
                eliminated_round: null,
            },
            {
                name: 'Bob',
                score: 80,
                streak: 0,
                is_admin: true,
                connected: false,
                eliminated: true,
                eliminated_round: 3,
            },
        ];

        const out = U.hydrateLeaderboard(leaderboard, players);

        expect(out[0]).toEqual({
            rank: 1,
            name: 'Bob',
            rank_change: 1,
            score: 80,
            streak: 0,
            is_admin: true,
            connected: false,
            eliminated: true,
            eliminated_round: 3,
        });
        expect(out[1].name).toBe('Alice');
        expect(out[1].score).toBe(50);
        expect(out[1].connected).toBe(true);
        // Rank fields from the leaderboard entry are preserved.
        expect(out[1].rank).toBe(2);
        expect(out[1].rank_change).toBe(-1);
    });

    it('keeps entry fields on overlap (non-destructive) so a full final board passes through', () => {
        // The END-phase final leaderboard already carries score + its stat block;
        // hydration must NOT clobber those with the (possibly absent) player copy.
        const finalBoard = [
            {
                rank: 1,
                name: 'Alice',
                score: 120,
                best_streak: 5,
                rounds_played: 8,
                bets_won: 2,
                is_admin: true,
                connected: true,
            },
        ];
        const players = [{ name: 'Alice', score: 999, connected: false }];

        const out = U.hydrateLeaderboard(finalBoard, players);

        expect(out[0].score).toBe(120); // entry wins, not the player's 999
        expect(out[0].connected).toBe(true); // entry wins
        expect(out[0].best_streak).toBe(5); // final-only field preserved
    });

    it('leaves an entry untouched when no matching player exists', () => {
        const leaderboard = [{ rank: 1, name: 'Ghost', rank_change: 0 }];
        const out = U.hydrateLeaderboard(leaderboard, []);
        expect(out[0]).toEqual({ rank: 1, name: 'Ghost', rank_change: 0 });
    });

    it('tolerates a missing/empty players array', () => {
        const leaderboard = [{ rank: 1, name: 'Alice', rank_change: 0 }];
        expect(U.hydrateLeaderboard(leaderboard, undefined)).toEqual(leaderboard);
        expect(U.hydrateLeaderboard(leaderboard, null)).toEqual(leaderboard);
    });

    it('returns a non-array input unchanged', () => {
        expect(U.hydrateLeaderboard(undefined, [])).toBe(undefined);
        expect(U.hydrateLeaderboard(null, [])).toBe(null);
    });
});
