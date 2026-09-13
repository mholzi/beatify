/**
 * #2823 — the phone guess axis drew identical years on top of each other and
 * labelled every dot with one letter.
 *
 * #2827 — the year slider's decade labels overlapped on a phone.
 *
 * The rules are pure functions cut out of the shipped source (see
 * helpers/js-source.js), so what is tested is what ships:
 *
 *   1. initials are the TV axis's initials (#2502) — a parity test against
 *      dashboard.js keeps the two copies from drifting apart
 *   2. dots that would touch drop a row; identical years stack; past five rows
 *      the rest folds into "+N"; your own dot always sits on the line
 *   3. the year scale shows exactly min and max
 */
import { describe, it, expect } from 'vitest';
import { declaration, evaluate, readSource } from './helpers/js-source.js';

const REVEAL = readSource('player-reveal.js');
const DASHBOARD = readSource('dashboard.js');
const GAME = readSource('player-game.js');

const initials = evaluate([declaration(REVEAL, 'playerAxisInitials')], 'playerAxisInitials');
const tvInitials = evaluate([declaration(DASHBOARD, 'guessAxisInitials')], 'guessAxisInitials');
const layout = evaluate(
    [declaration(REVEAL, 'playerAxisInitials'), declaration(REVEAL, 'layoutPlayerDotAxis')],
    'layoutPlayerDotAxis',
);
const scaleMarks = evaluate([declaration(GAME, 'yearScaleMarks')], 'yearScaleMarks');

function score(off) { return off === 0 ? 10 : off <= 3 ? 5 : off <= 5 ? 1 : 0; }
function guesses(correct, pairs) {
    return pairs.map(([name, guess]) => {
        const off = Math.abs(guess - correct);
        return { name, guess, years_off: off, round_score: score(off) };
    });
}

// Eight guests, three on the same year, three names starting with M.
const ROUND = guesses(1983, [
    ['Mia', 1990], ['Michael', 1990], ['Markus', 1990], ['Lena', 1983],
    ['Laura', 1976], ['Tobi', 1985], ['Paul', 1970], ['Gisela', 2004],
]);

describe('#2823 initials', () => {
    it('gives Mia, Michael and Markus three different two-letter initials', () => {
        const a = initials(['Mia', 'Michael', 'Markus']);
        expect(a).toEqual({ Markus: 'MA', Mia: 'MI', Michael: 'MC' });
    });

    it('matches the TV axis for the same names, whatever the payload order', () => {
        const sets = [
            ['Lena', 'Tobi', 'gisela'],
            ['Anna Maria Berg', 'Anna Berg'],
            ['Max', 'Martin', 'Mia', 'Michael', 'Mira', 'Moritz'],
            ['Al', 'Al B', 'AL'],
            ['🎸', '★', 'Zoë', 'Ömer', 'Özlem'],
            ROUND.map((g) => g.name),
        ];
        for (const names of sets) {
            expect(initials(names)).toEqual(tvInitials(names));
            expect(initials(names.slice().reverse())).toEqual(tvInitials(names));
        }
    });
});

describe('#2823 stacking', () => {
    it('stacks identical years in one column, one row each', () => {
        const L = layout(ROUND, 1983, 'Lena');
        const col = L.dots.filter((d) => d.guess.guess === 1990);
        expect(col).toHaveLength(3);
        expect(new Set(col.map((d) => d.x)).size).toBe(1);
        expect(col.map((d) => d.row).sort()).toEqual([0, 1, 2]);
        expect(col.map((d) => d.initials).sort()).toEqual(['MA', 'MC', 'MI']);
    });

    it('keeps dots that are far enough apart on the line', () => {
        const L = layout(ROUND, 1983, null);
        const row = (n) => L.dots.find((d) => d.name === n).row;
        expect(row('Paul')).toBe(0);
        expect(row('Laura')).toBe(0);
        expect(row('Gisela')).toBe(0);
    });

    it('never lets two dots in one row touch at the narrowest plot', () => {
        const L = layout(ROUND, 1983, 'Mia');
        const minDx = 30 / 240 * 100;
        for (const a of L.dots) {
            for (const b of L.dots) {
                if (a !== b && a.row === b.row) expect(Math.abs(a.x - b.x)).toBeGreaterThanOrEqual(minDx - 1e-9);
            }
        }
        expect(L.rows).toBe(3);
    });

    it('does not depend on the order the payload lists the guesses in', () => {
        const strip = (L) => L.dots.map((d) => [d.name, d.row, d.plus]);
        expect(strip(layout(ROUND.slice().reverse(), 1983, 'Tobi'))).toEqual(strip(layout(ROUND, 1983, 'Tobi')));
    });

    it('puts your own dot on the line, even in a crowded year', () => {
        const L = layout(ROUND, 1983, 'Michael');
        const me = L.dots.find((d) => d.isMe);
        expect(me.name).toBe('Michael');
        expect(me.row).toBe(0);
        expect(me.plus).toBe(0);
    });

    it('folds everything past five rows into a "+N" dot', () => {
        const seven = guesses(1977, ['Ada', 'Bea', 'Cem', 'Dan', 'Eva', 'Fil', 'Gus'].map((n) => [n, 1977]));
        const L = layout(seven, 1977, null);
        expect(L.rows).toBe(5);
        expect(L.dots).toHaveLength(5);
        const plus = L.dots.filter((d) => d.plus);
        expect(plus).toHaveLength(1);
        // the fifth-row dot plus the two that had no row left
        expect(plus[0].row).toBe(4);
        expect(plus[0].plus).toBe(3);
    });

    it('never folds your own dot away', () => {
        const seven = guesses(1977, ['Ada', 'Bea', 'Cem', 'Dan', 'Eva', 'Fil', 'Zed'].map((n) => [n, 1977]));
        const L = layout(seven, 1977, 'Zed');
        expect(L.dots.find((d) => d.name === 'Zed')).toMatchObject({ row: 0, plus: 0, isMe: true });
    });

    it('shows a score bubble only where it does not touch another, yours first', () => {
        const L = layout(ROUND, 1983, 'Mia');
        const shown = L.dots.filter((d) => d.showScore);
        expect(shown.find((d) => d.name === 'Mia')).toBeTruthy();
        // Michael and Markus share Mia's year: their bubbles would sit on hers.
        expect(shown.find((d) => d.name === 'Michael')).toBeFalsy();
        expect(shown.find((d) => d.name === 'Markus')).toBeFalsy();
        const xs = shown.map((d) => d.x).sort((a, b) => a - b);
        for (let i = 1; i < xs.length; i++) expect(xs[i] - xs[i - 1]).toBeGreaterThanOrEqual(34 / 240 * 100);
    });

    it('ignores a guess without a year', () => {
        const L = layout([{ name: 'X', guess: null, years_off: null, round_score: 0 }, ...ROUND], 1983, null);
        expect(L.dots.find((d) => d.name === 'X')).toBeUndefined();
    });
});

describe('#2827 year scale', () => {
    it('labels exactly the lowest and the highest selectable year', () => {
        expect(scaleMarks(1950, 2026)).toEqual([
            { year: 1950, text: '1950', edge: 'start' },
            { year: 2026, text: '2026', edge: 'end' },
        ]);
    });

    it('uses full years, so a century-crossing span stays unambiguous', () => {
        expect(scaleMarks(1900, 2027).map((m) => m.text)).toEqual(['1900', '2027']);
    });

    it('draws nothing for a broken range', () => {
        expect(scaleMarks(2000, 2000)).toEqual([]);
        expect(scaleMarks(2010, 1990)).toEqual([]);
        expect(scaleMarks(NaN, 2026)).toEqual([]);
    });
});
