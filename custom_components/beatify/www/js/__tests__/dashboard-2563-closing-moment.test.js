/**
 * #2563 — the closing moment.
 *
 * The end screen showed the result and never the route to it. `round_scores`
 * had existed on the player since the beginning — `clutch_player` and
 * `comeback_king` are computed from it — but it was never serialized, so the
 * TV could only ever print the final number. It now rides along on each final
 * leaderboard entry, and three seconds of the end screen are spent on the one
 * round where the lead last changed hands.
 *
 * What matters about that choice of round is that it is mechanical. There is
 * no drama score and no "biggest swing": it is the last round at which the top
 * of the board changed hands to the player who finished first. A winner who
 * led from the first round has no such round, and the prologue is then skipped
 * rather than filled with something invented.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { declaration, evaluate, locale, readSource, WWW_DIR } from './helpers/js-source.js';

const DASHBOARD = readSource('dashboard.js');
const CSS = readFileSync(join(WWW_DIR, 'css', 'dashboard.css'), 'utf8');

/** The shipped chooser, compiled out of the file that ships. */
const findClosingMoment = evaluate(
    declaration(DASHBOARD, 'findClosingMoment', 'dashboard.js'),
    'findClosingMoment',
);

/** A leaderboard entry carrying a per-round delta series. */
function player(rank, name, rounds) {
    return { rank, name, score: rounds.reduce((a, b) => a + b, 0), round_scores: rounds };
}

describe('#2563 — which round the closing moment lands on', () => {
    it('is the round the eventual winner took the lead', () => {
        // Ben leads from round 1, Dana passes him in round 4 and stays there.
        const moment = findClosingMoment([
            player(1, 'Dana', [5, 5, 5, 40, 10]),
            player(2, 'Ben', [20, 10, 10, 0, 5]),
        ]);
        expect(moment.round).toBe(4);
        expect(moment.winner.name).toBe('Dana');
        expect(moment.loser.name).toBe('Ben');
    });

    it('takes the LAST change of hands, not the first', () => {
        // Dana is ahead after round 2, loses it again in round 3, and takes it
        // back in round 5. The closing shot is about how the game ended.
        const moment = findClosingMoment([
            player(1, 'Dana', [10, 30, 0, 0, 40]),
            player(2, 'Ben', [30, 5, 20, 10, 0]),
        ]);
        expect(moment.round).toBe(5);
    });

    it('carries the running totals, not the per-round deltas', () => {
        // The chart draws a climb; deltas would draw a sawtooth.
        const moment = findClosingMoment([
            player(1, 'Dana', [5, 5, 40]),
            player(2, 'Ben', [20, 10, 0]),
        ]);
        expect(moment.winner.cum).toEqual([0, 5, 10, 50]);
        expect(moment.loser.cum).toEqual([0, 20, 30, 30]);
    });

    it('ignores a lead change between two players who both lost', () => {
        // Chris passes Ben in round 2, but Dana wins the game. That swap is
        // not the story of the game and must not be the closing shot.
        const moment = findClosingMoment([
            player(1, 'Dana', [0, 0, 0, 100]),
            player(2, 'Ben', [20, 0, 0, 0]),
            player(3, 'Chris', [5, 20, 0, 0]),
        ]);
        expect(moment.round).toBe(4);
        expect(moment.loser.name).toBe('Chris');
    });
});

describe('#2563 — when there is no moment to show', () => {
    it('says so when the winner led from the first round', () => {
        expect(findClosingMoment([
            player(1, 'Dana', [30, 30, 30]),
            player(2, 'Ben', [10, 10, 10]),
        ])).toBeNull();
    });

    it('says so for a single player', () => {
        expect(findClosingMoment([player(1, 'Dana', [10, 10])])).toBeNull();
    });

    it('says so when the payload predates the field', () => {
        // An older backend, or a client that reconnects to one: the end screen
        // must render as it always did rather than throw on the way in.
        expect(findClosingMoment([
            { rank: 1, name: 'Dana', score: 90 },
            { rank: 2, name: 'Ben', score: 30 },
        ])).toBeNull();
        expect(findClosingMoment(null)).toBeNull();
        expect(findClosingMoment([])).toBeNull();
    });

    it('says so for a game of one round, where nothing changed hands', () => {
        expect(findClosingMoment([
            player(1, 'Dana', [30]),
            player(2, 'Ben', [10]),
        ])).toBeNull();
    });

    it('does not treat the opening round as an overtake', () => {
        // Before round 1 everyone is on zero. Whoever scores first has not
        // passed anybody, and a naive leader-changed check would call it one.
        expect(findClosingMoment([
            player(1, 'Dana', [10, 40]),
            player(2, 'Ben', [0, 0]),
        ])).toBeNull();
    });
});

describe('#2563 — the same game always yields the same moment', () => {
    it('breaks a tied lead by name rather than by payload order', () => {
        const rows = [
            player(1, 'Dana', [10, 0, 40]),
            player(2, 'Ben', [10, 0, 0]),
        ];
        const forwards = findClosingMoment(rows);
        const backwards = findClosingMoment(rows.slice().reverse());
        expect(forwards.round).toBe(backwards.round);
        expect(forwards.winner.name).toBe(backwards.winner.name);
        expect(forwards.loser.name).toBe(backwards.loser.name);
    });
});

describe('#2563 — the strings the prologue prints', () => {
    it('has both keys in every shipped language', () => {
        for (const lang of ['en', 'de', 'es', 'fr', 'it', 'nl']) {
            const strings = locale(lang).leaderboard;
            expect(strings.momentKicker, `${lang} momentKicker`).toBeTruthy();
            expect(strings.momentVerb, `${lang} momentVerb`).toBeTruthy();
            // The round number is the whole point of the kicker line.
            expect(strings.momentKicker, `${lang} momentKicker`).toContain('{round}');
        }
    });
});

describe('#2563 — the overlay can actually be hidden', () => {
    it('hides itself with its own rule, not with the bare .hidden', () => {
        // Same trap as `.podium-place` in #2130: `.end-moment` is display:flex,
        // which ties with `.hidden` on specificity. Without the explicit
        // combined rule the prologue would sit on the end screen all evening.
        expect(CSS).toContain('.end-moment.hidden');
    });
});
