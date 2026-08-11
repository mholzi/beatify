/**
 * How a Sudden Death game ended — and which of the two endings the END screen
 * is allowed to announce.
 *
 * History in two steps:
 *
 * 1. #2103 stopped the screen from crowning a "Last One Standing" who was not
 *    standing alone. `renderSuddenDeathLastStanding` had taken
 *    `survivors[0].name` whenever `sudden_death_mode` was set, so a game ending
 *    by round exhaustion announced the top-scoring survivor as sole survivor
 *    while the leaderboard below still showed the others in the game.
 * 2. #2105 gave that second ending words of its own. Hiding the hero was
 *    correct but silent: the mode's whole promise is "the last one left wins",
 *    and a game that ends with several alive said nothing about it.
 *
 * The backend was right throughout: `_superlative_last_one_standing`
 * (game/scoring.py) withholds the award unless exactly one player survived and
 * at least one was eliminated, and `compute_winners`
 * (game/state_serialization.py) has crowned the top-scoring *survivor* since
 * #1749 for the round-exhaustion case.
 *
 * Both endings are reachable in practice since the selectable round count
 * (#1475): elimination starts in round 2 and removes one player per round, so
 * N players need N rounds — a cap of 10 leaves 11 players with two survivors.
 *
 * dashboard.js is a self-contained IIFE with no exported helpers (it runs
 * init() + service-worker registration at import) and the vitest env is `node`
 * with no jsdom, so — as in dashboard-b8.test.js and
 * dashboard-art-src-guard.test.js — this asserts the load-bearing LOGIC.
 * `suddenDeathEnding` below is copied VERBATIM from dashboard.js and kept in
 * sync manually.
 */
import { describe, it, expect } from 'vitest';

// Verbatim copy of the decision helper in dashboard.js.
function suddenDeathEnding(data) {
    if (!data || !data.sudden_death_mode) return null;

    var stats = data.game_stats || {};
    var rounds = stats.total_rounds != null ? stats.total_rounds : (data.round || 0);
    var leaderboard = data.leaderboard || [];

    if (leaderboard.length) {
        var survivors = leaderboard.filter(function(e) { return !e.eliminated; });
        var eliminated = leaderboard.filter(function(e) { return e.eliminated; });
        if (!eliminated.length || !survivors.length) return null;
        var name = survivors[0].name;
        if (!name) return null;
        return {
            kind: survivors.length === 1 ? 'sole' : 'points',
            name: name,
            survivors: survivors.length,
            rounds: rounds
        };
    }

    var awards = data.superlatives || [];
    var award = awards.find(function(a) { return a.id === 'last_one_standing'; });
    if (!award || !award.player_name) return null;
    return { kind: 'sole', name: award.player_name, survivors: 1, rounds: rounds };
}

/** Leaderboard entry helper — `alive: false` means eliminated. */
const entry = (name, alive) => ({ name, eliminated: !alive });

/** 11 players, cap 10 → 9 eliminated, 2 alive. Survivors sort first (#1749). */
function cappedGame() {
    const leaderboard = [entry('Ada', true), entry('Bob', true)];
    for (let i = 0; i < 9; i++) leaderboard.push(entry(`Out${i}`, false));
    return { sudden_death_mode: true, leaderboard, game_stats: { total_rounds: 10 } };
}

describe('Sudden Death ending — the 1v1 finish', () => {
    it('reports a sole survivor when the game ran to its conclusion', () => {
        const data = {
            sudden_death_mode: true,
            leaderboard: [entry('Ada', true), entry('Bob', false), entry('Cleo', false)],
            game_stats: { total_rounds: 3 },
        };
        expect(suddenDeathEnding(data)).toEqual({
            kind: 'sole', name: 'Ada', survivors: 1, rounds: 3,
        });
    });

    it('falls back to the backend award when the leaderboard is missing', () => {
        // The award carries the same rule server-side, so it needs no re-check.
        const data = {
            sudden_death_mode: true,
            superlatives: [
                { id: 'risk_taker', player_name: 'Bob' },
                { id: 'last_one_standing', player_name: 'Ada' },
            ],
            game_stats: { total_rounds: 7 },
        };
        expect(suddenDeathEnding(data)).toEqual({
            kind: 'sole', name: 'Ada', survivors: 1, rounds: 7,
        });
    });
});

describe('Sudden Death ending — the points win (#2105)', () => {
    it('reports a points win when the rounds ran out with two alive', () => {
        expect(suddenDeathEnding(cappedGame())).toEqual({
            kind: 'points', name: 'Ada', survivors: 2, rounds: 10,
        });
    });

    it('names the top-scoring survivor, not a late-eliminated high scorer', () => {
        // The final leaderboard renders survivors first (#1749), so the winner
        // is the first entry — never someone below the cut-line.
        const data = {
            sudden_death_mode: true,
            leaderboard: [entry('Ada', true), entry('Bob', true), entry('Cleo', false)],
            game_stats: { total_rounds: 4 },
        };
        expect(suddenDeathEnding(data).name).toBe('Ada');
    });

    it('carries the count and the round number that explain the ending', () => {
        const data = {
            sudden_death_mode: true,
            leaderboard: [
                entry('Ada', true), entry('Bob', true), entry('Cleo', true), entry('Dan', false),
            ],
            game_stats: { total_rounds: 12 },
        };
        const ending = suddenDeathEnding(data);
        expect(ending.survivors).toBe(3);
        expect(ending.rounds).toBe(12);
    });

    it('falls back to data.round when game_stats has no round count', () => {
        // Same fallback chain the END header uses, so hero and header agree.
        const data = { ...cappedGame(), game_stats: {}, round: 10 };
        expect(suddenDeathEnding(data).rounds).toBe(10);
    });
});

describe('Sudden Death ending — when the hero must stay hidden', () => {
    it('stays hidden when nobody was ever eliminated', () => {
        // Armed but force-ended in round 1 — an ordinary game, not a showdown.
        const data = {
            sudden_death_mode: true,
            leaderboard: [entry('Ada', true), entry('Bob', true)],
        };
        expect(suddenDeathEnding(data)).toBeNull();
    });

    it('stays hidden for a solo game, where one survivor is not an achievement', () => {
        const data = { sudden_death_mode: true, leaderboard: [entry('Ada', true)] };
        expect(suddenDeathEnding(data)).toBeNull();
    });

    it('stays hidden when Sudden Death was off', () => {
        const data = {
            sudden_death_mode: false,
            leaderboard: [entry('Ada', true), entry('Bob', false)],
        };
        expect(suddenDeathEnding(data)).toBeNull();
    });

    it('stays hidden when no survivor is left at all', () => {
        const data = {
            sudden_death_mode: true,
            leaderboard: [entry('Ada', false), entry('Bob', false)],
        };
        expect(suddenDeathEnding(data)).toBeNull();
    });

    it('stays hidden when neither leaderboard nor award identifies a survivor', () => {
        expect(suddenDeathEnding({ sudden_death_mode: true })).toBeNull();
        expect(suddenDeathEnding({ sudden_death_mode: true, superlatives: [] })).toBeNull();
        expect(suddenDeathEnding(null)).toBeNull();
    });

    it('does not crown an unnamed survivor', () => {
        const data = {
            sudden_death_mode: true,
            leaderboard: [{ name: '', eliminated: false }, entry('Bob', false)],
        };
        expect(suddenDeathEnding(data)).toBeNull();
    });
});
