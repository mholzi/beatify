/**
 * #3371 — the pause message on a missing music provider.
 *
 * Seen in the live test of v4.8.8-rc1 with Apple Music signed out in Music
 * Assistant: the speaker was fine, yet guests were told "The speaker isn't
 * responding", and the TV showed that line in German in an English game.
 *
 * Part 1 — the wording. `game.pausedSpeaker` (TV) and `player.speakerUnavailable`
 * (phones) are the only two texts shown for `pause_reason: media_player_error`,
 * which a dead speaker AND an unavailable provider share. Neither may name the
 * speaker. The admin headline (#3339) is a separate key and stays as it is.
 *
 * Part 2 — the TV language. `BeatifyI18n.getLanguage()` answers the NEW code the
 * moment a switch starts, while `t()` keeps answering in the OLD locale until
 * the file has loaded. `handleStateUpdate` compared the state's language with
 * `getLanguage()`, so a state arriving in that window looked "already
 * switched" and was painted in the previous language. The real i18n.js and the
 * real handleStateUpdate run here; only the DOM render and the network are
 * stubs.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { declaration, evaluate, readSource, locale, JS_DIR } from './helpers/js-source.js';

const LANGS = ['de', 'en', 'es', 'fr', 'it', 'nl'];
const SPEAKER_WORD = {
    de: /lautsprecher|box/i,
    en: /speaker/i,
    es: /altavoz/i,
    fr: /enceinte/i,
    it: /altoparlante|casse/i,
    nl: /speaker|luidspreker/i,
};

describe('#3371 pause wording does not blame the speaker', () => {
    for (const lang of LANGS) {
        it(`${lang}: TV and phone text are neutral`, () => {
            const pack = locale(lang);
            const tv = pack.game.pausedSpeaker;
            const phone = pack.player.speakerUnavailable;
            expect(tv).toBeTruthy();
            expect(phone).toBeTruthy();
            expect(tv).not.toMatch(SPEAKER_WORD[lang]);
            expect(phone).not.toMatch(SPEAKER_WORD[lang]);
            // Both surfaces say the same thing.
            expect(phone.replace(/\.$/, '')).toBe(tv);
        });
    }

    it('en reads as the agreed neutral sentence', () => {
        expect(locale('en').player.speakerUnavailable).toBe(
            'The music has stopped for a moment — the host is on it.',
        );
    });

    it('the TV English fallback does not name the speaker either', () => {
        const src = readSource('dashboard.js');
        const at = src.indexOf("key = 'game.pausedSpeaker';");
        expect(at).toBeGreaterThan(-1);
        const from = src.indexOf('fallback =', at);
        const fallback = src.slice(from, src.indexOf('\n', from));
        expect(fallback).not.toMatch(/speaker/i);
    });

    it('the admin headline of #3339 still names the provider', () => {
        for (const lang of LANGS) {
            const text = locale(lang).admin.pauseRecovery.mediaPlayerErrorProviderUnavailable;
            expect(text).toContain('{provider}');
        }
    });
});

// ---------------------------------------------------------------------------
// TV language
// ---------------------------------------------------------------------------

const I18N_SRC = readFileSync(`${JS_DIR}/i18n.js`, 'utf8');
const DASHBOARD = readSource('dashboard.js');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** Real i18n.js in a sandbox; locale files arrive after `delay(lang)` ms. */
function loadI18n({ browser, delay = () => 5, down = () => false }) {
    const w = {};
    const ctx = {
        window: w,
        document: {
            documentElement: { lang: 'en' },
            querySelector: () => null,
            querySelectorAll: () => [],
        },
        navigator: { language: browser, languages: [browser] },
        console: { warn() {}, log() {} },
        fetch: (url) => {
            const lang = /i18n\/([a-z]{2})\.json/.exec(url)[1];
            return new Promise((resolve) =>
                setTimeout(
                    () =>
                        resolve(
                            down(lang)
                                ? { ok: false, status: 503 }
                                : { ok: true, status: 200, json: () => Promise.resolve(locale(lang)) },
                        ),
                    delay(lang),
                ),
            );
        },
        Promise, Object, Array, RegExp, encodeURIComponent, JSON, setTimeout,
    };
    vm.createContext(ctx);
    vm.runInContext(I18N_SRC, ctx);
    return w.BeatifyI18n;
}

/**
 * The shipped handleStateUpdate, wired to the real i18n.js. `painted` records
 * what the TV would show: the state's language next to the language the pause
 * text was actually rendered in.
 */
function tv(i18n) {
    const painted = [];
    const scope = {
        BeatifyI18n: i18n,
        _scheduleRender: (d) =>
            painted.push({
                n: d.n,
                game: d.language,
                text: i18n.t('game.pausedSpeaker'),
            }),
        setTimeout,
        Promise,
        // Play without a speaker: the "Sound on" prompt follows the game.
        _setTvTarget: () => {},
    };
    const consts = [
        DASHBOARD.match(/var _stateSeq = 0;/)[0],
        DASHBOARD.match(/var LANGUAGE_WAIT_MS = \d+;/)[0],
    ];
    const handle = evaluate(
        [
            ...consts,
            declaration(DASHBOARD, 'handleStateUpdate', 'dashboard.js'),
            declaration(DASHBOARD, '_handleStateNow', 'dashboard.js'),
        ],
        'handleStateUpdate',
        scope,
    );
    return { handle, painted };
}

const inLang = (lang) => locale(lang).game.pausedSpeaker;

describe('#3371 the TV paints in the game language', () => {
    it('control: a settled TV in the game language paints at once, in that language', async () => {
        const i18n = loadI18n({ browser: 'en-US' });
        await i18n.init();
        const { handle, painted } = tv(i18n);
        handle({ n: 1, language: 'en' });
        expect(painted).toEqual([{ n: 1, game: 'en', text: inLang('en') }]);
    });

    it('control: a single state that triggers the switch is painted after it, in the new language', async () => {
        const i18n = loadI18n({ browser: 'en-US' });
        await i18n.init();
        const { handle, painted } = tv(i18n);
        handle({ n: 1, language: 'de' });
        await sleep(60);
        expect(painted).toEqual([{ n: 1, game: 'de', text: inLang('de') }]);
    });

    it('a second state during the switch is not painted in the old language', async () => {
        // A German game on a TV that was showing English: the lobby broadcast
        // starts the switch, the pause broadcast follows before de.json is in.
        const i18n = loadI18n({ browser: 'en-US' });
        await i18n.init();
        const { handle, painted } = tv(i18n);
        handle({ n: 1, language: 'de' });
        handle({ n: 2, language: 'de' });
        await sleep(60);
        expect(painted.length).toBeGreaterThan(0);
        for (const p of painted) expect(p.text).toBe(inLang(p.game));
        // The newest state is the one on screen.
        expect(painted[painted.length - 1].n).toBe(2);
    });

    it('English game, English translations still loading: the first paint is English', async () => {
        // The TV came up in a German browser while Home Assistant could not
        // serve en.json (a restart), so it has no English at all. The state
        // that starts the switch and the one right behind it both belong to an
        // English game.
        let haUp = false;
        const i18n = loadI18n({
            browser: 'de-DE',
            delay: (lang) => (haUp && lang === 'en' ? 30 : 1),
            down: (lang) => !haUp && lang === 'en',
        });
        await i18n.setLanguage('de');
        haUp = true;
        const { handle, painted } = tv(i18n);
        handle({ n: 1, language: 'en' });
        handle({ n: 2, language: 'en' });
        await sleep(80);
        expect(painted.length).toBeGreaterThan(0);
        for (const p of painted) expect(p.text).toBe(inLang('en'));
    });

    it('a state superseded while waiting is dropped, not painted over the newer one', async () => {
        const i18n = loadI18n({ browser: 'en-US', delay: () => 20 });
        await i18n.init();
        const { handle, painted } = tv(i18n);
        handle({ n: 1, language: 'de' });
        handle({ n: 2, language: 'de' });
        handle({ n: 3, language: 'de' });
        await sleep(120);
        expect(painted.map((p) => p.n)).toEqual([3]);
    });

    it('i18n.js exposes the in-flight window the TV waits on', async () => {
        const i18n = loadI18n({ browser: 'en-US' });
        await i18n.init();
        expect(i18n.isSwitching()).toBe(false);
        const pending = i18n.setLanguage('es');
        expect(i18n.getLanguage()).toBe('es');
        expect(i18n.isSwitching()).toBe(true);
        await pending;
        expect(i18n.isSwitching()).toBe(false);
    });
});
