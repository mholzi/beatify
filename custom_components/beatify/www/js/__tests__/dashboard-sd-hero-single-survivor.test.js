/**
 * The END screen crowned a "Last One Standing" who was not standing alone.
 *
 * `renderSuddenDeathLastStanding` (dashboard.js) took `survivors[0].name`
 * whenever `sudden_death_mode` was set, without checking how many players were
 * still alive. A Sudden Death game that ends by round exhaustion leaves two or
 * more survivors, and the TV then announced the top-scoring one as the sole
 * survivor — while the leaderboard right below it showed the others still in
 * the game.
 *
 * The backend never agreed with that screen: `_superlative_last_one_standing`
 * (game/scoring.py) withholds the award unless exactly one player survived and
 * at least one was eliminated, and `compute_winners`
 * (game/state_serialization.py) has crowned the top-scoring *survivor* since
 * #1749 precisely for the round-exhaustion case. Only the renderer had not
 * caught up.
 *
 * Reachable in practice since the selectable round count (#1475): elimination
 * starts in round 2 and removes one player per round, so N players need N
 * rounds — a cap of 10 leaves 11 players with two survivors. Before #1475 the
 * same state required the playlist to run out.
 *
 * dashboard.js is a self-contained IIFE with no exported helpers (it runs
 * init() + service-worker registration at import) and the vitest env is `node`
 * with no jsdom, so — as in dashboard-b8.test.js and
 * dashboard-art-src-guard.test.js — this asserts the load-bearing LOGIC.
 * `suddenDeathSurvivorName` below is copied VERBATIM from dashboard.js and
 * kept in sync manually.
 */
import { describe, it, expect } from 'vitest';

// Verbatim copy of the decision helper in dashboard.js.
function suddenDeathSurvivorName(data) {
    if (!data || !data.sudden_death_mode) return null;

    var leaderboard = data.leaderboard || [];
    if (leaderboard.length) {
        var survivors = leaderboard.filter(function(e) { return !e.eliminated; });
        var eliminated = leaderboard.filter(function(e) { return e.eliminated; });
        if (survivors.length !== 1 || !eliminated.length) return null;
        return survivors[0].name || null;
    }

    var awards = data.superlatives || [];
    var award = awards.find(function(a) { return a.id === 'last_one_standing'; });
    return (award && award.player_name) || null;
}

/** Leaderboard entry helper — `alive: false` means eliminated. */
const entry = (name, alive) => ({ name, eliminated: !alive });

describe('Last One Standing hero — who may be crowned', () => {
    it('crowns the sole survivor of a game that ran to its 1v1 conclusion', () => {
        const data = {
            sudden_death_mode: true,
            leaderboard: [entry('Ada', true), entry('Bob', false), entry('Cleo', false)],
        };
        expect(suddenDeathSurvivorName(data)).toBe('Ada');
    });

    it('stays hidden when the round cap ends the game with two survivors', () => {
        // The regression: 11 players, cap 10 → 9 eliminated, 2 still alive.
        const leaderboard = [entry('Ada', true), entry('Bob', true)];
        for (let i = 0; i < 9; i++) leaderboard.push(entry(`Out${i}`, false));
        expect(suddenDeathSurvivorName({ sudden_death_mode: true, leaderboard })).toBeNull();
    });

    it('stays hidden when nobody was ever eliminated', () => {
        // Sudden Death armed but force-ended in round 1 — everyone still alive.
        const data = {
            sudden_death_mode: true,
            leaderboard: [entry('Ada', true), entry('Bob', true)],
        };
        expect(suddenDeathSurvivorName(data)).toBeNull();
    });

    it('stays hidden for a solo game, where one survivor is not an achievement', () => {
        const data = { sudden_death_mode: true, leaderboard: [entry('Ada', true)] };
        expect(suddenDeathSurvivorName(data)).toBeNull();
    });

    it('stays hidden when Sudden Death was off', () => {
        const data = {
            sudden_death_mode: false,
            leaderboard: [entry('Ada', true), entry('Bob', false)],
        };
        expect(suddenDeathSurvivorName(data)).toBeNull();
    });

    it('falls back to the backend award when the leaderboard is missing', () => {
        // The award carries the same rule server-side, so it needs no re-check.
        const data = {
            sudden_death_mode: true,
            superlatives: [
                { id: 'risk_taker', player_name: 'Bob' },
                { id: 'last_one_standing', player_name: 'Ada' },
            ],
        };
        expect(suddenDeathSurvivorName(data)).toBe('Ada');
    });

    it('stays hidden when neither leaderboard nor award identifies a survivor', () => {
        expect(suddenDeathSurvivorName({ sudden_death_mode: true })).toBeNull();
        expect(suddenDeathSurvivorName({ sudden_death_mode: true, superlatives: [] })).toBeNull();
        expect(suddenDeathSurvivorName(null)).toBeNull();
    });

    it('does not crown an unnamed survivor', () => {
        const data = {
            sudden_death_mode: true,
            leaderboard: [{ name: '', eliminated: false }, entry('Bob', false)],
        };
        expect(suddenDeathSurvivorName(data)).toBeNull();
    });
});
