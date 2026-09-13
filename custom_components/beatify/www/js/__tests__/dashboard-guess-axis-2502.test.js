/**
 * #2502 — the room's guess spread on the TV (design Variant A).
 *
 * The TV reveal showed the top three guesses; a guest twenty years out was only
 * ever visible on their own phone. In year mode the lower band is now a year
 * axis with one dot per guess. The geometry lives in two pure functions inside
 * the dashboard IIFE; they are cut out of the shipped source and run here, so
 * each decision the design gate left open is pinned by a test:
 *
 *   1. initials are two letters and unique, resolved in name order
 *   2. the dashed span to the farthest guess, with the name from 10 years off
 *   3. the range zooms to the guesses but a >30-year outlier breaks the edge
 *   4. 64 px dots up to ten guests, 52 px above; five rows, then "+N"
 */
import { describe, it, expect } from 'vitest';
import { declaration, evaluate, locale, readSource } from './helpers/js-source.js';
import { doc, el } from './helpers/mini-dom.js';

const DASHBOARD = readSource('dashboard.js');
const SNIPPETS = [
    declaration(DASHBOARD, 'guessAxisInitials'),
    declaration(DASHBOARD, 'layoutGuessAxis'),
];
const initials = evaluate(SNIPPETS, 'guessAxisInitials');
const layout = evaluate(SNIPPETS, 'layoutGuessAxis');

function score(off) { return off === 0 ? 10 : off <= 3 ? 5 : off <= 5 ? 1 : 0; }
function guesses(correct, pairs) {
    return pairs.map(([name, guess]) => {
        const off = Math.abs(guess - correct);
        return { name, guess, years_off: off, round_score: score(off) };
    });
}

// The design gate's example round: Sweet Dreams, 1983.
const ROUND = guesses(1983, [
    ['Lena', 1983], ['Tobi', 1985], ['Jonas', 1986], ['Mia', 1986], ['Kemal', 1986],
    ['Paul', 1979], ['Gisela', 2004],
]);

describe('#2502 initials', () => {
    it('takes the first two letters of a single name', () => {
        expect(initials(['Lena', 'Tobi', 'gisela'])).toEqual({ Lena: 'LE', Tobi: 'TO', gisela: 'GI' });
    });

    it('takes first and last word initial of a longer name', () => {
        expect(initials(['Anna Maria Berg'])['Anna Maria Berg']).toBe('AB');
    });

    it('resolves a collision in name order, with a later letter before a digit', () => {
        const a = initials(['Michael', 'Mia', 'Mira']);
        // "Mia" sorts first and keeps MI; the others fall back to M + a later letter.
        expect(a.Mia).toBe('MI');
        expect(a.Michael).toBe('MC');
        expect(a.Mira).toBe('MR');
    });

    it('does not depend on the order the payload lists the names in', () => {
        const names = ['Max', 'Martin', 'Mia', 'Michael', 'Mira', 'Moritz'];
        const forward = initials(names);
        const backward = initials(names.slice().reverse());
        expect(backward).toEqual(forward);
        expect(new Set(Object.values(forward)).size).toBe(names.length);
    });

    it('falls back to a digit once the letters run out', () => {
        const a = initials(['Al', 'Al B', 'AL']);
        expect(new Set(Object.values(a)).size).toBe(3);
        expect(Object.values(a).some((v) => /\d/.test(v))).toBe(true);
    });

    it('survives a name with no letters at all', () => {
        const a = initials(['🎸', '★']);
        expect([a['🎸'], a['★']].sort()).toEqual(['?', '?2']);
    });
});

describe('#2502 range', () => {
    it('zooms to the guesses and the answer, snapped to five years', () => {
        const L = layout(ROUND, 1983, 1620);
        expect([L.min, L.max]).toEqual([1975, 2005]);
        expect(L.step).toBe(5);
        expect(L.brokenLow || L.brokenHigh).toBe(false);
    });

    it('never gets narrower than twenty years', () => {
        const L = layout(guesses(1990, [['A', 1990], ['B', 1991]]), 1990, 1620);
        expect(L.max - L.min).toBeGreaterThanOrEqual(20);
        expect(L.min).toBeLessThanOrEqual(1990);
        expect(L.max).toBeGreaterThanOrEqual(1991);
    });

    it('puts a guess more than 30 years out at a broken edge instead of compressing the rest', () => {
        const L = layout(guesses(1977, [['Ben', 1979], ['Mia', 1977], ['Olga', 2020]]), 1977, 1620);
        expect(L.brokenHigh).toBe(true);
        expect(L.brokenLow).toBe(false);
        expect(L.max).toBeLessThan(2020);
        const olga = L.dots.find((d) => d.name === 'Olga');
        expect(olga.x).toBe(1620);
        // Ben and Mia are still two years apart by more than a dot, not squeezed.
        const ben = L.dots.find((d) => d.name === 'Ben');
        const mia = L.dots.find((d) => d.name === 'Mia');
        expect(ben.x - mia.x).toBeGreaterThan(64);
    });

    it('hides the tick labels the big year would cover', () => {
        const L = layout(ROUND, 1983, 1620);
        const hidden = L.ticks.filter((t) => !t.label).map((t) => t.year);
        expect(hidden).toContain(1980);
        expect(hidden).toContain(1985);
        expect(L.ticks.find((t) => t.year === 2000).label).toBe(true);
    });

    it('keeps the year on screen when the answer sits at the edge', () => {
        // 1961 snaps the range to 1960-1990, so the answer is 54 px from the edge.
        const L = layout(guesses(1961, [['A', 1961], ['B', 1985]]), 1961, 1620);
        expect(L.correctX).toBeLessThan(100);
        expect(L.yearX).toBeGreaterThan(L.correctX);
    });
});

describe('#2502 dots and stacking', () => {
    it('stacks identical years in one column', () => {
        const L = layout(ROUND, 1983, 1620);
        const col = L.dots.filter((d) => d.guess === 1986);
        expect(new Set(col.map((d) => d.x)).size).toBe(1);
        expect(col.map((d) => d.row).sort()).toEqual([1, 2, 3]);
    });

    it('drops a neighbour a row when two dots would touch', () => {
        const L = layout(ROUND, 1983, 1620);
        // 54 px per year: 1985 and 1986 overlap, so the 1986 column starts a row lower.
        expect(L.dots.find((d) => d.name === 'Tobi').row).toBe(0);
        expect(Math.min(...L.dots.filter((d) => d.guess === 1986).map((d) => d.row))).toBe(1);
    });

    it('colours by hit quality', () => {
        const L = layout(ROUND, 1983, 1620);
        const kind = (n) => L.dots.find((d) => d.name === n).kind;
        expect(kind('Lena')).toBe('exact');
        expect(kind('Tobi')).toBe('near');
        expect(kind('Gisela')).toBe('off');
    });

    it('uses 64 px dots up to ten guests and 52 px above', () => {
        const ten = guesses(1990, Array.from({ length: 10 }, (_, i) => ['P' + i, 1970 + i * 4]));
        const eleven = guesses(1990, Array.from({ length: 11 }, (_, i) => ['P' + i, 1970 + i * 4]));
        expect(layout(ten, 1990, 1620).size).toBe(64);
        expect(layout(eleven, 1990, 1620).size).toBe(52);
    });

    it('folds everything past five rows into a "+N" dot', () => {
        const seven = guesses(1977, ['Ada', 'Bea', 'Cem', 'Dan', 'Eva', 'Fil', 'Gus'].map((n) => [n, 1977]));
        const L = layout(seven, 1977, 1620);
        expect(L.rows).toBe(5);
        expect(L.dots).toHaveLength(5);
        const last = L.dots.find((d) => d.row === 4);
        // the fifth-row dot plus the two that had no row left
        expect(last.plus).toBe(3);
        expect(L.dots.filter((d) => d.plus).length).toBe(1);
    });

    it('passes missed players through with initials that do not clash with the guessers', () => {
        const L = layout(guesses(1983, [['Mia', 1983]]), 1983, 1620, { missed: ['Michael'] });
        expect(L.missed).toEqual([{ name: 'Michael', initials: 'MC' }]);
        expect(L.dots[0].initials).toBe('MI');
    });

    it('ignores a guess without a year', () => {
        const L = layout([{ name: 'X', guess: null, years_off: null, round_score: 0 }], 1983, 1620);
        expect(L.dots).toHaveLength(0);
        expect(L.span).toBeNull();
    });
});

describe('#2502 the farthest guess', () => {
    it('draws the span with the years and, from ten years off, the name', () => {
        const L = layout(ROUND, 1983, 1620, { spanLabelChars: 16 });
        expect(L.span).not.toBeNull();
        expect(L.span.years).toBe(21);
        expect(L.span.name).toBe('Gisela');
        const gisela = L.dots.find((d) => d.name === 'Gisela');
        // The span ends before the dot and starts after the last dot on the way.
        expect(L.span.to).toBeLessThan(gisela.x);
        const tobi = L.dots.find((d) => d.name === 'Tobi');
        expect(L.span.from).toBeGreaterThan(tobi.x);
    });

    it('keeps the span but drops the name under ten years', () => {
        const L = layout(guesses(1983, [['Lena', 1983], ['Paul', 1992]]), 1983, 1620, { spanLabelChars: 15 });
        expect(L.span.years).toBe(9);
        expect(L.span.name).toBeNull();
    });

    it('runs the other way for a guess that is too early', () => {
        const L = layout(guesses(1991, [['Anna', 1991], ['Rafa', 1975]]), 1991, 1620);
        expect(L.span.years).toBe(16);
        expect(L.span.name).toBe('Rafa');
        expect(L.span.from).toBeGreaterThan(L.dots.find((d) => d.name === 'Rafa').x);
    });

    it('leaves the span out when the farthest guess sits in the crowd', () => {
        const L = layout(guesses(1983, [['A', 1983], ['B', 1984], ['C', 1985]]), 1983, 1620, { spanLabelChars: 15 });
        expect(L.span).toBeNull();
    });

    it('leaves the span out when everyone was exact', () => {
        const L = layout(guesses(1983, [['A', 1983], ['B', 1983]]), 1983, 1620);
        expect(L.span).toBeNull();
    });
});

describe('#2502 renderer', () => {
    function render(data) {
        const root = el('reveal-guess-axis');
        root.classList.add('hidden');
        const band = el(null);
        band.style.setProperty = (k, v) => { band.style[k] = v; };
        root.parentNode = band;
        const plot = el('guess-axis-plot');
        plot.clientWidth = 1620;
        const missed = el('guess-axis-missed');
        const document = doc({ 'reveal-guess-axis': root, 'guess-axis-plot': plot, 'guess-axis-missed': missed });
        const t = (key, params) => {
            const table = locale('en').dashboard;
            const leaf = key.split('.').pop();
            return String(table[leaf]).replace('{count}', params && params.count);
        };
        const fn = evaluate(SNIPPETS.concat(declaration(DASHBOARD, 'renderGuessAxis')), 'renderGuessAxis', {
            document,
            utils: { t, escapeHtml: (s) => String(s).replace(/</g, '&lt;') },
        });
        return { fn, root, plot, missed, band };
    }

    const DATA = {
        song: { year: 1983 },
        round_analytics: { all_guesses: ROUND },
        players: ROUND.map((g) => ({ name: g.name, missed_round: false }))
            .concat([{ name: 'Markus', missed_round: true }, { name: 'Ghost', missed_round: true, eliminated: true }]),
    };

    it('draws a dot per guess, the span and the missed line', () => {
        const r = render(DATA);
        r.fn(DATA, true);
        expect(r.root.classList.contains('hidden')).toBe(false);
        for (const ini of ['LE', 'TO', 'JO', 'MI', 'KE', 'PA', 'GI']) {
            expect(r.plot.innerHTML).toContain('>' + ini + '<');
        }
        expect(r.plot.innerHTML).toContain('21 years off');
        expect(r.plot.innerHTML).toContain('guess-axis-span-name');
        // dots land on beat two of the #2702 staging
        expect(r.plot.innerHTML).toContain('class="guess-axis-dots" data-stage="2"');
        expect(r.missed.innerHTML).toContain('No guess');
        expect(r.missed.innerHTML).toContain('Markus');
        // eliminated players are spectators, not "no guess"
        expect(r.missed.innerHTML).not.toContain('Ghost');
        expect(Number(r.band.style['--guess-axis-year'])).toBeGreaterThan(0);
    });

    it('hides itself outside axis mode', () => {
        const r = render(DATA);
        r.root.classList.remove('hidden');
        r.fn(DATA, false);
        expect(r.root.classList.contains('hidden')).toBe(true);
    });
});

describe('#2502 translations', () => {
    const KEYS = ['guessAxisTitle', 'guessAxisNoGuess', 'guessAxisYearsOff', 'guessAxisYearsOffOne', 'standingsMore'];

    it('exist in every locale', () => {
        for (const lang of ['de', 'en', 'es', 'fr', 'it', 'nl']) {
            const table = locale(lang).dashboard;
            for (const key of KEYS) {
                expect(typeof table[key], `${lang}: dashboard.${key}`).toBe('string');
                expect(table[key].trim().length).toBeGreaterThan(0);
            }
            expect(table.guessAxisYearsOff).toContain('{count}');
            expect(table.standingsMore).toContain('{count}');
        }
    });
});
