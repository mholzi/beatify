/**
 * #3221: the bet line in the points breakdown always read "Triple or Nothing",
 * also when the won bet paid ×2 or ×5 (difficulty bet scaling, #1727). #3157
 * fixed the value next to it; the label was still tied to one multiplier.
 *
 * The line now reads "All-in bonus" in every language, a wording that fits any
 * multiplier, and the value keeps showing the real one. Rendered from the
 * shipped `renderPointsBreakdown` with the real locale files.
 */
import { describe, it, expect } from 'vitest';
import { declaration, evaluate, locale, readSource } from './helpers/js-source.js';

const SRC = readSource('player-reveal.js');
const LANGS = ['en', 'de', 'es', 'fr', 'it', 'nl'];

const EXPECTED = {
    en: 'All-in bonus',
    de: 'All-in-Bonus',
    es: 'Bonus all-in',
    fr: 'Bonus all-in',
    it: 'Bonus all-in',
    nl: 'All-in-bonus',
};

function lookup(dict, key) {
    return key.split('.').reduce((node, part) => (node == null ? node : node[part]), dict);
}

/** Render the breakdown for a won bet at `mult` in `lang`; returns [label, value] of the bet row. */
function betRow(lang, mult) {
    const dict = locale(lang);
    const content = { innerHTML: '' };
    const player = {
        years_off: 0,
        base_score: 10,
        round_score: 30,
        speed_multiplier: 1,
        speed_bonus: 0,
        bet_outcome: 'won',
    };
    const render = evaluate(
        [declaration(SRC, 'computeTotalPoints', 'player-reveal.js'), declaration(SRC, 'renderPointsBreakdown', 'player-reveal.js')],
        'renderPointsBreakdown',
        {
            document: { getElementById: (id) => (id === 'points-breakdown-content' ? content : null) },
            state: { lastRevealContext: { player, betWinMultiplier: mult } },
            utils: {
                t: (key, params) => {
                    let s = lookup(dict, key);
                    if (typeof s !== 'string') return '';
                    for (const [k, v] of Object.entries(params || {})) s = s.replace(`{${k}}`, v);
                    return s;
                },
            },
            escapeHtml: (s) => String(s),
        },
    );
    render();
    const rows = [...content.innerHTML.matchAll(
        /<span class="emoji" aria-hidden="true">🎲<\/span><span>([^<]*)<\/span><\/span><span class="value value--multiplier">([^<]*)<\/span>/g,
    )];
    expect(rows).toHaveLength(1);
    return [rows[0][1], rows[0][2]];
}

describe('#3221 the bet line reads "All-in bonus" at every multiplier', () => {
    for (const lang of LANGS) {
        for (const mult of [2, 3, 5]) {
            it(`${lang} ×${mult}`, () => {
                expect(betRow(lang, mult)).toEqual([EXPECTED[lang], `×${mult}`]);
            });
        }
    }

    it('the label is the same at ×2, ×3 and ×5 in every language', () => {
        for (const lang of LANGS) {
            const labels = new Set([2, 3, 5].map((m) => betRow(lang, m)[0]));
            expect(labels.size).toBe(1);
        }
    });
});
