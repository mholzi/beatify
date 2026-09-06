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
 * `node`, so the two renderers are cut out of the shipped source and run
 * against stubs. That makes this a behaviour test, not a grep: it asserts the
 * text that lands in the DOM.
 */
import { describe, it, expect, beforeAll } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const JS_DIR = join(__dirname, '..');
const WWW = join(__dirname, '..', '..');
const REPO = join(__dirname, '..', '..', '..', '..', '..');
const SRC = readFileSync(join(JS_DIR, 'dashboard.js'), 'utf8');
const MIN = readFileSync(join(JS_DIR, 'dashboard.min.js'), 'utf8');
const STATS_PY = readFileSync(
    join(REPO, 'custom_components', 'beatify', 'services', 'stats.py'),
    'utf8',
);
const LOCALES = ['en', 'de', 'es', 'fr', 'it', 'nl'];

const i18n = {};
beforeAll(() => {
    for (const l of LOCALES) {
        i18n[l] = JSON.parse(readFileSync(join(WWW, 'i18n', `${l}.json`), 'utf8'));
    }
});

function lookup(obj, key) {
    return key.split('.').reduce((n, p) => (n && typeof n === 'object' ? n[p] : undefined), obj);
}

/** Cut a top-level declaration out of the IIFE by matching its braces. */
function declaration(name) {
    for (const head of [`    function ${name}(`, `    var ${name} = {`]) {
        const start = SRC.indexOf(head);
        if (start === -1) continue;
        let i = SRC.indexOf('{', start);
        let depth = 0;
        for (; i < SRC.length; i++) {
            if (SRC[i] === '{') depth++;
            else if (SRC[i] === '}' && --depth === 0) return SRC.slice(start, i + 1);
        }
    }
    throw new Error(`dashboard.js no longer declares ${name}`);
}

/** BeatifyI18n.t / utils.t for one locale, same lookup + interpolation. */
function utilsFor(locale) {
    return {
        t(key, params) {
            const value = lookup(i18n[locale], key);
            if (typeof value !== 'string') return key;
            if (!params) return value;
            return Object.keys(params).reduce(
                (s, p) => s.replace(new RegExp(`\\{${p}\\}`, 'g'), params[p]),
                value,
            );
        },
    };
}

/** Minimal stand-in for the end-screen container and its two child spans. */
function stubDom() {
    const child = () => ({ textContent: '' });
    const els = { '.stats-comparison-icon': child(), '.stats-comparison-text': child() };
    const container = {
        className: 'stats-comparison',
        classList: { add() {}, remove() {} },
        querySelector: (sel) => els[sel],
    };
    return { document: { getElementById: () => container }, container, els };
}

function renderStats(performance, locale) {
    const dom = stubDom();
    const run = new Function(
        'document',
        'utils',
        `${declaration('renderStatsComparison')}\nreturn renderStatsComparison;`,
    )(dom.document, utilsFor(locale));
    run(performance);
    return {
        icon: dom.els['.stats-comparison-icon'].textContent,
        text: dom.els['.stats-comparison-text'].textContent,
    };
}

function motivational(message, difference, locale) {
    const run = new Function(
        'utils',
        `${declaration('MOTIVATIONAL_KEYS')};\n${declaration('motivationalText')}\nreturn motivationalText;`,
    )(utilsFor(locale));
    return run(message, difference);
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

    it('keeps the icons and the css modifier per branch', () => {
        expect(renderStats(FIRST, 'de').icon).toBe('🌟');
        expect(renderStats(RECORD, 'de').icon).toBe('🏆');
        expect(renderStats(ABOVE, 'de').icon).toBe('📈');
        expect(renderStats(BELOW, 'de').icon).toBe('📊');
    });

    it('no longer carries the literals, in the source or in the bundle', () => {
        for (const bundle of [SRC, MIN]) {
            expect(bundle).not.toContain('First game recorded! Avg: ');
            expect(bundle).not.toContain('NEW RECORD! ');
            expect(bundle).not.toContain(' vs all-time avg)');
        }
        expect(MIN).toContain('stats.firstGameRecorded');
        expect(MIN).toContain('stats.newRecordEnd');
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

    it('translates every type the server can emit', () => {
        expect(motivational(SERVER.first, 0, 'de')).toBe('Erstes Spiel! Maßstab gesetzt');
        expect(motivational(SERVER.record, 0, 'de')).toBe(
            'Neuer Rekord! Höchste Punktzahl aller Zeiten!',
        );
        expect(motivational(SERVER.strong, 7.5, 'de')).toBe(
            'Ausgezeichnet! 7.5 Pkt über Durchschnitt',
        );
        expect(motivational(SERVER.above, 2.5, 'de')).toBe(
            'Starkes Spiel! 2.5 Pkt über Durchschnitt',
        );
        expect(motivational(SERVER.close, -2.5, 'de')).toBe(
            'Knapp am Durchschnitt! Nur 2.5 Pkt darunter',
        );
    });

    it('drops the sign for the "below average" wording', () => {
        // The template says "below" in words, so a "-2.5 pts below" would read
        // as a double negative.
        expect(motivational(SERVER.close, -2.5, 'en')).toBe('Close to average! Just 2.5 pts below');
    });

    it('falls back to the server text for a type the map does not know', () => {
        expect(motivational({ type: 'legendary', message: 'Legendary!' }, 0, 'de')).toBe(
            'Legendary!',
        );
    });

    it('covers every message type services/stats.py emits', () => {
        const types = [...STATS_PY.matchAll(/"type":\s*"(\w+)"/g)].map((m) => m[1]);
        expect(types.length, 'the scan found no types — has stats.py been restructured?')
            .toBeGreaterThanOrEqual(5);
        const map = declaration('MOTIVATIONAL_KEYS');
        for (const t of new Set(types)) {
            expect(map, `dashboard.js has no translation for type "${t}"`).toContain(`'${t}':`);
        }
    });

    it('no longer prints the server string straight into the chip', () => {
        expect(SRC).not.toContain("textEl.textContent = message.message || ''");
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
