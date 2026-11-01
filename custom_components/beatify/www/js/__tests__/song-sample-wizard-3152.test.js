/**
 * #3152 — the host sets how long the song plays, separately from the answer time.
 *
 * Step 4 of the wizard gets a second chip row under "Time per round": "Whole
 * round" plus 10/15/20/30 seconds. A step that is not shorter than the answer
 * time is shown disabled, a chosen step that stops being shorter falls back to
 * "Whole round", and one hint line appears only while a sample is chosen. The
 * choice travels in `sample_duration` of the start-game and update-lobby
 * payloads, where 0 means the whole round.
 *
 * The chip markup and the hint are the exported pure helpers; the render
 * function and the payload builder are module-private, so the shipped bytes
 * are cut out of the files and run (helpers/js-source.js).
 */
import { describe, it, expect } from 'vitest';
import { sampleChipsHtml, sampleHintText } from '../wizard.js';
import { SAMPLE_DURATION_OPTIONS, normalizeSampleDuration } from '../game-constants.js';
import { declaration, evaluate, readSource, locale } from './helpers/js-source.js';

const LOCALES = ['en', 'de', 'es', 'fr', 'it', 'nl'];
const en = locale('en');
const lookup = (dict) => (key, fallback) =>
    key.split('.').reduce((node, part) => (node && typeof node === 'object' ? node[part] : undefined), dict) ?? fallback;
const t = lookup(en);

/** Parse the chip buttons back out of the markup. */
function chips(html) {
    return [...html.matchAll(/<button([^>]*)>([^<]*)<\/button>/g)].map(([, attrs, label]) => ({
        value: Number(/data-value="(\d+)"/.exec(attrs)[1]),
        label,
        active: /class="wiz-chip active"/.test(attrs),
        disabled: /\sdisabled\b/.test(attrs),
    }));
}

describe('normalizeSampleDuration (#3152)', () => {
    it('keeps an offered step that is shorter than the round', () => {
        expect(normalizeSampleDuration(15, 30)).toBe(15);
        expect(normalizeSampleDuration('20', 45)).toBe(20);
    });

    it('turns a step that is not shorter than the round into "whole round"', () => {
        expect(normalizeSampleDuration(30, 30)).toBe(0);
        expect(normalizeSampleDuration(20, 15)).toBe(0);
    });

    it('turns anything that is not an offered step into "whole round"', () => {
        for (const junk of [undefined, null, '', 'abc', 0, 12, -10, 25, NaN]) {
            expect(normalizeSampleDuration(junk, 60)).toBe(0);
        }
    });
});

describe('the "Song plays for" chips (#3152)', () => {
    it('offers "Whole round" first, then every step, formatted like the timer chips', () => {
        const row = chips(sampleChipsHtml(0, 60, t));
        expect(row.map((c) => c.value)).toEqual([0, ...SAMPLE_DURATION_OPTIONS]);
        expect(row.map((c) => c.label)).toEqual(['Whole round', '10s', '15s', '20s', '30s']);
    });

    it('selects "Whole round" by default and nothing is disabled on a 45s round', () => {
        const row = chips(sampleChipsHtml(0, 45, t));
        expect(row.filter((c) => c.active).map((c) => c.value)).toEqual([0]);
        expect(row.some((c) => c.disabled)).toBe(false);
    });

    it('marks the chosen step', () => {
        const row = chips(sampleChipsHtml(15, 45, t));
        expect(row.filter((c) => c.active).map((c) => c.value)).toEqual([15]);
    });

    it.each([
        [15, [15, 20, 30]],
        [30, [30]],
        [45, []],
        [60, []],
    ])('on a %is round, disables exactly the steps that are not shorter', (round, disabled) => {
        const row = chips(sampleChipsHtml(0, round, t));
        expect(row.filter((c) => c.disabled).map((c) => c.value)).toEqual(disabled);
        // Greyed, not hidden: every step is still on screen.
        expect(row).toHaveLength(SAMPLE_DURATION_OPTIONS.length + 1);
        // "Whole round" can never be out of reach.
        expect(row[0].disabled).toBe(false);
    });

    it('shows "Whole round" as selected when the stored step no longer fits', () => {
        const row = chips(sampleChipsHtml(30, 30, t));
        expect(row.filter((c) => c.active).map((c) => c.value)).toEqual([0]);
    });

    it('labels "Whole round" in every locale', () => {
        const expected = {
            en: 'Whole round', de: 'Ganze Runde', es: 'Toda la ronda',
            fr: 'Toute la manche', it: 'Tutto il turno', nl: 'Hele ronde',
        };
        for (const lang of LOCALES) {
            const row = chips(sampleChipsHtml(0, 45, lookup(locale(lang))));
            expect(row[0].label, lang).toBe(expected[lang]);
        }
    });
});

describe('the hint under the chips (#3152)', () => {
    it('is empty for "Whole round"', () => {
        expect(sampleHintText(0, 45, t)).toBe('');
    });

    it('is empty when the chosen step is not shorter than the round', () => {
        expect(sampleHintText(30, 30, t)).toBe('');
    });

    it('names the song time and the answer time', () => {
        expect(sampleHintText(15, 30, t)).toBe('Music stops after 15s. Players keep 30s to answer.');
        expect(sampleHintText(15, 30, lookup(locale('de')))).toBe(
            'Die Musik endet nach 15 s. Zum Antworten bleiben 30 s.',
        );
    });

    it('has both placeholders and the field label in every locale', () => {
        for (const lang of LOCALES) {
            const step4 = locale(lang).wizard.step4;
            expect(step4.sample, lang).toBeTruthy();
            expect(step4.sampleHint, lang).toContain('{song}');
            expect(step4.sampleHint, lang).toContain('{round}');
            expect(sampleHintText(10, 45, lookup(locale(lang))), lang).not.toMatch(/[{}]/);
        }
    });
});

describe('the chip row in the wizard (#3152)', () => {
    const WIZARD = readSource('wizard.js');

    /** Build the two elements and the shipped render function around a state. */
    function mount(sample, round) {
        const listeners = [];
        const group = {
            innerHTML: '',
            querySelectorAll: (selector) => {
                expect(selector).toBe('.wiz-chip:not([disabled])');
                return chips(group.innerHTML)
                    .filter((c) => !c.disabled)
                    .map((c) => ({
                        dataset: { value: String(c.value) },
                        addEventListener: (_event, fn) => listeners.push({ value: c.value, fn }),
                    }));
            },
        };
        const hidden = new Set(['hidden']);
        const hint = {
            textContent: '',
            classList: { toggle: (c, on) => { if (on) hidden.add(c); else hidden.delete(c); } },
        };
        const api = evaluate(
            [
                `let chosenSampleDuration = ${sample};`,
                `let chosenDuration = ${round};`,
                declaration(WIZARD, '_renderSampleDuration', 'wizard.js'),
            ],
            `{
                render: _renderSampleDuration,
                state: () => ({ sample: chosenSampleDuration, round: chosenDuration }),
                setRound: (v) => { chosenDuration = v; },
            }`,
            {
                document: { getElementById: (id) => ({ 'wiz-sample': group, 'wiz-sample-hint': hint })[id] || null },
                sampleChipsHtml,
                sampleHintText,
                normalizeSampleDuration,
                _t: t,
                // Stands in for the full step re-render, which ends up here again.
                _renderGameMode: () => api.render(),
                _chipPicked: () => {},  // #3367: motion only, covered in ux-motion-3367
            },
        );
        return {
            api,
            group,
            hint,
            hintShown: () => !hidden.has('hidden'),
            tap: (value) => {
                const hit = listeners.filter((l) => l.value === value).pop();
                if (!hit) throw new Error(`chip ${value} is not tappable`);
                hit.fn();
            },
        };
    }

    it('starts on "Whole round" with the hint hidden', () => {
        const w = mount(0, 45);
        w.api.render();
        expect(chips(w.group.innerHTML).find((c) => c.active).value).toBe(0);
        expect(w.hintShown()).toBe(false);
    });

    it('picking a step selects it and shows the hint', () => {
        const w = mount(0, 30);
        w.api.render();
        w.tap(15);
        expect(w.api.state().sample).toBe(15);
        expect(chips(w.group.innerHTML).find((c) => c.active).value).toBe(15);
        expect(w.hintShown()).toBe(true);
        expect(w.hint.textContent).toBe('Music stops after 15s. Players keep 30s to answer.');
    });

    it('a disabled step cannot be tapped', () => {
        const w = mount(0, 30);
        w.api.render();
        expect(() => w.tap(30)).toThrow(/not tappable/);
    });

    it('falls back to "Whole round" when the answer time drops to the sample', () => {
        const w = mount(20, 45);
        w.api.render();
        expect(w.hintShown()).toBe(true);

        w.api.setRound(15);  // the host taps the 15s timer chip
        w.api.render();

        expect(w.api.state().sample).toBe(0);
        expect(chips(w.group.innerHTML).find((c) => c.active).value).toBe(0);
        expect(w.hintShown()).toBe(false);
        expect(w.hint.textContent).toBe('');
    });

    it('keeps the sample when the answer time stays longer', () => {
        const w = mount(15, 45);
        w.api.setRound(30);
        w.api.render();
        expect(w.api.state().sample).toBe(15);
    });

    it('going back to "Whole round" hides the hint again', () => {
        const w = mount(15, 45);
        w.api.render();
        w.tap(0);
        expect(w.api.state().sample).toBe(0);
        expect(w.hintShown()).toBe(false);
    });
});

describe('the wizard markup and persistence (#3152)', () => {
    const html = readSource('../admin.html');
    const WIZARD = readSource('wizard.js');

    it('puts the new field directly under "Time per round", in the same pattern', () => {
        const timer = html.indexOf('id="wiz-timer"');
        const sample = html.indexOf('id="wiz-sample"');
        const rounds = html.indexOf('id="wiz-rounds"');
        expect(timer).toBeGreaterThan(-1);
        expect(sample).toBeGreaterThan(timer);
        expect(rounds).toBeGreaterThan(sample);
        expect(html).toContain('<label class="wiz-field-label" data-i18n="wizard.step4.sample">');
        expect(html).toContain('<div id="wiz-sample" class="wiz-chip-group"></div>');
        expect(html).toContain('<div id="wiz-sample-hint" class="wiz-difficulty-hint hidden"></div>');
    });

    it('stores the choice in the settings blob next to the timer', () => {
        const persist = declaration(WIZARD, '_persistGameSettings', 'wizard.js');
        const stored = {};
        const run = evaluate(
            [
                'let chosenProvider = "spotify", chosenDifficulty = "normal", chosenDuration = 30;',
                'let chosenSampleDuration = 15, chosenRevealAutoAdvance = 0, chosenMaxRounds = 0;',
                'let chosenLanguage = "en", chosenArtistChallenge = true, chosenMovieQuiz = true;',
                'let chosenIntroMode = false, chosenClosestWins = false, chosenSuddenDeath = false;',
                'let chosenTitleArtistMode = false, chosenRampupOrder = false, chosenFinaleDouble = false;',
                'let chosenFinaleTiebreaker = false, chosenComebackToken = false, chosenBetScaling = false;',
                'let chosenSabotage = false;',
                persist,
            ],
            '_persistGameSettings',
            {
                LS_GAME_SETTINGS: 'beatify_game_settings',
                localStorage: {
                    getItem: () => null,
                    setItem: (key, value) => { stored[key] = JSON.parse(value); },
                },
                detectPlayStyle: () => null,
                chosenPlaylists: new Set(),
                normalizeSampleDuration,
                console,
            },
        );
        run();
        expect(stored.beatify_game_settings.duration).toBe(30);
        expect(stored.beatify_game_settings.sampleDuration).toBe(15);
    });
});

describe('the start-game / update-lobby payload (#3152)', () => {
    const ADMIN = readSource('admin.js');

    function payload(blob, selectedDuration) {
        const build = evaluate(declaration(ADMIN, 'buildGameOptionsPayload', 'admin.js'), 'buildGameOptionsPayload', {
            adminState: { selectedDuration },
            window: {},
            localStorage: { getItem: () => (blob === null ? null : JSON.stringify(blob)) },
            STORAGE_GAME_SETTINGS: 'beatify_game_settings',
            normalizeSampleDuration,
        });
        return build();
    }

    it('sends the stored sample length', () => {
        expect(payload({ sampleDuration: 15 }, 30).sample_duration).toBe(15);
    });

    it('sends 0 for "whole round" and for a blob written before the setting', () => {
        expect(payload({ sampleDuration: 0 }, 45).sample_duration).toBe(0);
        expect(payload({}, 45).sample_duration).toBe(0);
        expect(payload(null, 45).sample_duration).toBe(0);
    });

    it('never sends a sample the server would reject for this round duration', () => {
        // Stored for a 45s round; the round is 15s by the time the game starts.
        expect(payload({ sampleDuration: 20 }, 15).sample_duration).toBe(0);
        expect(payload({ sampleDuration: 30 }, 30).sample_duration).toBe(0);
    });

    it('keeps sending the round duration next to it', () => {
        const body = payload({ sampleDuration: 10 }, 60);
        expect(body.round_duration).toBe(60);
        expect(body.sample_duration).toBe(10);
    });
});
