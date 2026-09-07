/**
 * #2699 — the Sudden Death floor is one number, and every surface renders it.
 *
 * It used to live in four places, none of them authoritative: a local
 * `const SUDDEN_DEATH_MIN_PLAYERS = 3` in wizard.js gating the card, a bare
 * `if connected_count < 3:` in server/game_views.py, the warning sentence beside
 * it, and the digit spelled out in all six locale files. Raising it anywhere
 * left the host a card enabled for a game the server then started *without*
 * Sudden Death — no error on any surface.
 *
 * It now lives in `const.py`, is mirrored into `game-constants.js` (held there
 * by game-constants-mirror.test.js) and reaches the screen through a `{min}`
 * placeholder. This file guards the last leg of that chain: that the
 * substitution actually happens, in every locale, through the real i18n module.
 *
 * The assertion that matters is the negative one. Each rendered string must
 * contain the const.py number *and no other digit* — so a locale that quietly
 * keeps spelling out "3" while const.py has moved on fails here rather than on
 * someone's phone. A `{min}` that survives to the screen fails too, which is the
 * worse of the two outcomes it is guarding against.
 *
 * The i18n module is loaded in a vm sandbox against the REAL locale files
 * (i18n-b8.test.js does the same against stub payloads).
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';

const __dirname = dirname(fileURLToPath(import.meta.url));
const BEATIFY = join(__dirname, '..', '..', '..');
const CONST_PY = readFileSync(join(BEATIFY, 'const.py'), 'utf8');
const WIZARD_SRC = readFileSync(join(BEATIFY, 'www', 'js', 'wizard.js'), 'utf8');
const GAME_VIEWS_SRC = readFileSync(join(BEATIFY, 'server', 'game_views.py'), 'utf8');
const I18N_SRC = readFileSync(join(BEATIFY, 'www', 'js', 'i18n.js'), 'utf8');

const LOCALES = ['en', 'de', 'es', 'fr', 'it', 'nl'];

/** The floor as the server defines it. */
const MIN_PLAYERS = (() => {
    const m = /^SUDDEN_DEATH_MIN_PLAYERS\s*(?::[^=]+)?=\s*(\d+)/m.exec(CONST_PY);
    if (!m) throw new Error('SUDDEN_DEATH_MIN_PLAYERS not found in const.py');
    return Number(m[1]);
})();

/** The two strings that name the floor to the host. */
const GATE_KEYS = ['admin.suddenDeathDisabledTooltip', 'admin.suddenDeathDisabledGate'];

function localePayload(lang) {
    return JSON.parse(
        readFileSync(join(BEATIFY, 'www', 'i18n', `${lang}.json`), 'utf8'),
    );
}

/** Load i18n.js in a sandbox, serving the real locale files over its fetch. */
function loadI18n() {
    const fetchFn = (url) => {
        const m = /i18n\/([a-z]{2})\.json/.exec(url);
        return Promise.resolve({
            ok: true,
            status: 200,
            json: () => Promise.resolve(localePayload(m ? m[1] : 'en')),
        });
    };
    const sandboxWindow = {};
    const ctx = {
        window: sandboxWindow,
        document: {
            documentElement: { lang: 'en' },
            querySelector: () => null,
            querySelectorAll: () => [],
        },
        navigator: { language: 'en' },
        console,
        fetch: fetchFn,
        Promise, Object, Array, RegExp, encodeURIComponent, JSON, setTimeout,
    };
    vm.createContext(ctx);
    vm.runInContext(I18N_SRC, ctx);
    return sandboxWindow.BeatifyI18n;
}

describe('const.py owns the Sudden Death floor (#2699)', () => {
    it('defines SUDDEN_DEATH_MIN_PLAYERS as a sensible number', () => {
        expect(MIN_PLAYERS).toBeGreaterThan(1);
    });

    it('wizard.js imports it instead of declaring its own', () => {
        expect(WIZARD_SRC).toMatch(
            /import \{[\s\S]*?SUDDEN_DEATH_MIN_PLAYERS[\s\S]*?\} from '\.\/game-constants\.js'/,
        );
        expect(/^const SUDDEN_DEATH_MIN_PLAYERS\s*=/m.test(WIZARD_SRC)).toBe(false);
    });

    it('game_views.py compares against the constant, not a literal', () => {
        expect(GAME_VIEWS_SRC).toContain('connected_count < SUDDEN_DEATH_MIN_PLAYERS');
        expect(/connected_count < \d/.test(GAME_VIEWS_SRC)).toBe(false);
    });
});

describe('every locale renders the floor from the constant (#2699)', () => {
    for (const lang of LOCALES) {
        it(`${lang}: the gate strings take {min} and nothing else`, () => {
            const payload = localePayload(lang);
            for (const key of GATE_KEYS) {
                const [section, name] = key.split('.');
                const raw = payload[section][name];
                expect(raw, `${lang}.${key}`).toContain('{min}');
                // A second number in the sentence would be a second home for
                // the floor — the defect #2699 is about.
                expect(raw.replace(/\{min\}/g, ''), `${lang}.${key}`).not.toMatch(/\d/);
            }
        });

        it(`${lang}: t() substitutes the const.py value at render time`, async () => {
            const i18n = loadI18n();
            await i18n.setLanguage(lang);
            for (const key of GATE_KEYS) {
                const rendered = i18n.t(key, { min: MIN_PLAYERS });
                expect(rendered, `${lang}.${key}`).not.toBe(key);
                // The placeholder must not reach the screen…
                expect(rendered, `${lang}.${key}`).not.toContain('{min}');
                // …and the number on screen must be the one const.py holds,
                // with no stale digit left beside it.
                expect(rendered, `${lang}.${key}`).toContain(String(MIN_PLAYERS));
                expect(
                    rendered.split(String(MIN_PLAYERS)).join(''),
                    `${lang}.${key}`,
                ).not.toMatch(/\d/);
            }
        });
    }
});
