/**
 * #2619 — the TV's statistics line was built from English literals.
 *
 * Two places on the two screens the whole room looks at:
 *
 * 1. `renderStatsComparison` (end screen) concatenated 'First game recorded!
 *    Avg: …', 'NEW RECORD! … pts/round (prev: …)' and '… vs all-time avg',
 *    although `stats.firstGameRecorded`, `stats.newRecordEnd`,
 *    `stats.aboveAverageEnd` and `stats.belowAverageEnd` had been translated
 *    into all six locales the whole time. A German party saw one English line
 *    wedged between a German podium and German awards.
 * 2. `renderMotivationalMessage` (every reveal) printed `message.message`
 *    verbatim — a string composed in `services/stats.py`. The server does not
 *    know the language of the TV, so the fix keeps the server's `type` and
 *    numbers and picks the wording on the client, where the locale is known;
 *    the English string stays as the fallback for an unknown type.
 *
 * dashboard.js is a DOM-coupled IIFE with no exports and the vitest env is
 * `node`, so the renderers are cut out of the shipped source and run against
 * stubs. That makes these behaviour tests, not greps: they assert the text that
 * lands in the DOM.
 *
 * #2701 removed the three assertions against `dashboard.min.js`. They tested
 * the minifier, not the fix: `npm run build:check` rebuilds every bundle in
 * memory and fails on any drift from its source, so the bundle is already
 * guaranteed to carry whatever the source carries — while a `toContain` over
 * terser's output breaks whenever terser changes how it emits a string.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import {
    declaration,
    evaluate,
    locale,
    readSource,
    REPO_DIR,
} from './helpers/js-source.js';
import { doc, el, translator } from './helpers/mini-dom.js';

const SRC = readSource('dashboard.js');
const STATS_PY = readFileSync(
    join(REPO_DIR, 'custom_components', 'beatify', 'services', 'stats.py'),
    'utf8',
);
const LOCALES = ['en', 'de', 'es', 'fr', 'it', 'nl'];
const i18n = Object.fromEntries(LOCALES.map((l) => [l, locale(l)]));

function lookup(obj, key) {
    return key.split('.').reduce((n, p) => (n && typeof n === 'object' ? n[p] : undefined), obj);
}

const decl = (name) => declaration(SRC, name, 'dashboard.js');

/** Run the shipped end-screen renderer and read back what it painted. */
function renderStats(performance, lang) {
    const icon = el(null);
    const text = el(null);
    const container = el('end-stats-comparison', {
        children: { '.stats-comparison-icon': icon, '.stats-comparison-text': text },
    });
    evaluate(decl('renderStatsComparison'), 'renderStatsComparison', {
        document: doc({ 'end-stats-comparison': container }),
        utils: translator(i18n[lang]),
    })(performance);
    return { icon: icon.textContent, text: text.textContent, css: container.className };
}

/** Run the shipped reveal-chip renderer and read back what it painted. */
function renderChip(performance, lang) {
    const icon = el(null);
    const text = el(null);
    const container = el('reveal-motivational', {
        children: { '.motivational-icon': icon, '.motivational-text': text },
    });
    evaluate(
        [decl('MOTIVATIONAL_KEYS'), decl('motivationalText'), decl('renderMotivationalMessage')],
        'renderMotivationalMessage',
        {
            document: doc({ 'reveal-motivational': container }),
            utils: translator(i18n[lang]),
        },
    )(performance);
    return { icon: icon.textContent, text: text.textContent, css: container.className };
}

const FIRST = { is_first_game: true, current_avg: 12.34, all_time_avg: 0, difference: 0 };
const RECORD = {
    is_first_game: false,
    is_new_record: true,
    current_avg: 12.34,
    all_time_avg: 9.96,
    difference: 2.38,
};
const ABOVE = {
    is_first_game: false,
    is_new_record: false,
    is_above_average: true,
    current_avg: 12.34,
    all_time_avg: 10.0,
    difference: 2.34,
};
const BELOW = {
    is_first_game: false,
    is_new_record: false,
    is_above_average: false,
    current_avg: 7.66,
    all_time_avg: 10.0,
    difference: -2.34,
};

describe('#2619 end-screen stats line', () => {
    it('speaks German on a German TV', () => {
        // These four failed before the fix: the literals were English whatever
        // the locale said.
        expect(renderStats(FIRST, 'de').text).toBe('Erstes Spiel erfasst! Durchschnitt: 12.3 Pkt/Runde');
        expect(renderStats(RECORD, 'de').text).toBe('NEUER REKORD! 12.3 Pkt/Runde (vorher: 10.0)');
        expect(renderStats(ABOVE, 'de').text).toBe('12.3 Pkt/Runde (+2.3 vs Gesamtdurchschnitt)');
        expect(renderStats(BELOW, 'de').text).toBe('7.7 Pkt/Runde (-2.3 vs Gesamtdurchschnitt)');
    });

    it('leaves the English wording byte-identical to what shipped', () => {
        expect(renderStats(FIRST, 'en').text).toBe('First game recorded! Avg: 12.3 pts/round');
        expect(renderStats(RECORD, 'en').text).toBe('NEW RECORD! 12.3 pts/round (prev: 10.0)');
        expect(renderStats(ABOVE, 'en').text).toBe('12.3 pts/round (+2.3 vs all-time avg)');
        expect(renderStats(BELOW, 'en').text).toBe('7.7 pts/round (-2.3 vs all-time avg)');
    });

    it('renders no English in any non-English locale', () => {
        for (const l of LOCALES.filter((x) => x !== 'en')) {
            for (const p of [FIRST, RECORD, ABOVE, BELOW]) {
                expect(renderStats(p, l).text, l).not.toMatch(/pts\/round|all-time avg|NEW RECORD/);
            }
        }
    });

    it('never leaves a raw key on the screen', () => {
        // `t()` returns the key on a miss (#1402-B8), so a key that lost its
        // translation shows up as "stats.newRecordEnd" on the TV rather than
        // as an empty line — visible, but only to whoever is looking.
        for (const l of LOCALES) {
            for (const p of [FIRST, RECORD, ABOVE, BELOW]) {
                expect(renderStats(p, l).text, l).not.toMatch(/^stats\./);
                expect(renderStats(p, l).text, l).not.toMatch(/\{[a-z_]+\}/i);
            }
        }
    });

    it('keeps the icons and the css modifier per branch', () => {
        for (const [perf, icon, modifier] of [
            [FIRST, '🌟', 'stats-comparison--first'],
            [RECORD, '🏆', 'stats-comparison--record'],
            [ABOVE, '📈', 'stats-comparison--above'],
            [BELOW, '📊', 'stats-comparison--below'],
        ]) {
            const out = renderStats(perf, 'de');
            expect(out.icon).toBe(icon);
            expect(out.css).toContain(modifier);
        }
    });
});

describe('#2619 reveal motivation chip', () => {
    const SERVER = {
        first: { type: 'first', message: 'First game! Setting the benchmark' },
        record: { type: 'record', message: 'New Record! Highest scoring game ever!' },
        strong: { type: 'strong', message: 'Excellent! 7.5 pts above average' },
        above: { type: 'above', message: 'Strong game! 2.5 pts above average' },
        close: { type: 'close', message: 'Close to average! Just 2.5 pts below' },
    };

    it('paints the translated wording into the chip, not the server string', () => {
        // The regression this replaces a grep for: the chip used to render
        // `message.message` verbatim, so a German TV read the English sentence
        // the server had composed.
        expect(renderChip({ message: SERVER.first, difference: 0 }, 'de').text)
            .toBe('Erstes Spiel! Maßstab gesetzt');
        expect(renderChip({ message: SERVER.record, difference: 0 }, 'de').text)
            .toBe('Neuer Rekord! Höchste Punktzahl aller Zeiten!');
        expect(renderChip({ message: SERVER.strong, difference: 7.5 }, 'de').text)
            .toBe('Ausgezeichnet! 7.5 Pkt über Durchschnitt');
        expect(renderChip({ message: SERVER.above, difference: 2.5 }, 'de').text)
            .toBe('Starkes Spiel! 2.5 Pkt über Durchschnitt');
        expect(renderChip({ message: SERVER.close, difference: -2.5 }, 'de').text)
            .toBe('Knapp am Durchschnitt! Nur 2.5 Pkt darunter');
    });

    it('keeps the per-type icon and css modifier', () => {
        const out = renderChip({ message: SERVER.record, difference: 0 }, 'de');
        expect(out.icon).toBe('🏆');
        expect(out.css).toContain('motivational-message--record');
    });

    it('drops the sign for the "below average" wording', () => {
        // The template says "below" in words, so a "-2.5 pts below" would read
        // as a double negative.
        expect(renderChip({ message: SERVER.close, difference: -2.5 }, 'en').text)
            .toBe('Close to average! Just 2.5 pts below');
    });

    it('falls back to the server text for a type the map does not know', () => {
        const unknown = { type: 'legendary', message: 'Legendary!' };
        expect(renderChip({ message: unknown, difference: 0 }, 'de').text).toBe('Legendary!');
    });

    it('translates every message type services/stats.py can emit', () => {
        // Not a grep over the key map: each type the server can send is
        // actually rendered, and a type the client cannot translate falls back
        // to the server's English — which is exactly what would show on the TV.
        const types = [...STATS_PY.matchAll(/"type":\s*"(\w+)"/g)].map((m) => m[1]);
        expect(types.length, 'the scan found no types — has stats.py been restructured?')
            .toBeGreaterThanOrEqual(5);
        for (const type of new Set(types)) {
            const english = `SERVER TEXT for ${type}`;
            const painted = renderChip(
                { message: { type, message: english }, difference: 2.5 },
                'de',
            ).text;
            expect(painted, `dashboard.js has no translation for type "${type}"`)
                .not.toBe(english);
        }
    });

    it('hides the chip when the round carries no message', () => {
        const icon = el(null);
        const text = el(null);
        const container = el('reveal-motivational', {
            children: { '.motivational-icon': icon, '.motivational-text': text },
        });
        evaluate(
            [decl('MOTIVATIONAL_KEYS'), decl('motivationalText'), decl('renderMotivationalMessage')],
            'renderMotivationalMessage',
            {
                document: doc({ 'reveal-motivational': container }),
                utils: translator(i18n.de),
            },
        )(null);
        expect(container.classList.contains('hidden')).toBe(true);
    });
});

describe('#2619 the keys behind it', () => {
    const KEYS = [
        'stats.firstGameRecorded',
        'stats.newRecordEnd',
        'stats.aboveAverageEnd',
        'stats.belowAverageEnd',
        'stats.firstGame',
        'stats.newRecord',
        'stats.strongGame',
        'stats.aboveAverage',
        'stats.closeToAverage',
    ];

    it('exist as non-empty strings in all six locales', () => {
        for (const l of LOCALES) {
            for (const k of KEYS) {
                const v = lookup(i18n[l], k);
                expect(typeof v === 'string' && v.trim(), `${l}: ${k}`).toBeTruthy();
            }
        }
    });

    it('keep their placeholders through translation', () => {
        const needed = {
            'stats.firstGameRecorded': ['{avg}'],
            'stats.newRecordEnd': ['{avg}', '{prev}'],
            'stats.aboveAverageEnd': ['{avg}', '{diff}'],
            'stats.belowAverageEnd': ['{avg}', '{diff}'],
            'stats.strongGame': ['{diff}'],
            'stats.aboveAverage': ['{diff}'],
            'stats.closeToAverage': ['{diff}'],
        };
        for (const l of LOCALES) {
            for (const [k, phs] of Object.entries(needed)) {
                for (const ph of phs) {
                    expect(lookup(i18n[l], k), `${l}: ${k} lost ${ph}`).toContain(ph);
                }
            }
        }
    });

    it('are actually translated, not the English copied over', () => {
        for (const l of LOCALES.filter((x) => x !== 'en')) {
            for (const k of KEYS) {
                expect(lookup(i18n[l], k), `${l}: ${k}`).not.toBe(lookup(i18n.en, k));
            }
        }
    });
});
