/**
 * #2582: localisation gaps on all three party surfaces.
 *
 * Four separate holes, one issue:
 *
 * 1. 16 keys used by the wizard and the playlist generator existed in **no**
 *    locale. Every call site uses `_t(key, fallback)`, so no raw key ever
 *    showed — the English fallback did. A German host picking Amazon Music got
 *    a three-step English walkthrough next to a fully German explainer.
 * 2. The TV podium carried a hard-coded "PTS" while `reveal.pointsShort`
 *    existed in all six locales, and the shareable vinyl graphic painted the
 *    same literal.
 * 3. `ADMIN_CANNOT_LEAVE` preferred the server's English text over the
 *    translated code — the one branch #2532/#2553 missed.
 * 4. `library-fix.js` reimplemented the i18n fallback helper with the
 *    #1402-B8 bug: `t()` returns the key on a miss, and a key is truthy, so
 *    the fallback could never win.
 *
 * #2701: points 2, 3 and 4 were `expect(src).toContain(...)` pairs. Each of the
 * three is a small pure function or a single branch, so each is now compiled
 * out of the shipped file and run — see `helpers/js-source.js`. Point 2's TV
 * half stays an assertion on the markup, for the reason given at that test.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { block, declaration, evaluate, locale, readSource, WWW_DIR } from './helpers/js-source.js';
import { translator } from './helpers/mini-dom.js';

const LOCALES = ['en', 'de', 'es', 'fr', 'it', 'nl'];
const i18n = Object.fromEntries(LOCALES.map((l) => [l, locale(l)]));

const NEUE_KEYS = [
    'wizard.step2.explainer.amazonTitle',
    'wizard.step2.explainer.amazonBody',
    'wizard.step2.explainer.amazonStep1',
    'wizard.step2.explainer.amazonStep2',
    'wizard.step2.explainer.amazonStep3',
    'wizard.step2.explainer.amazonPrimary',
    'wizard.step5.tts.testNoSpeaker',
    'playlistGenerator.actions.captureIssue',
    'playlistGenerator.actions.dismissSubmission',
    'playlistGenerator.actions.working',
    'playlistGenerator.saveLocal.success',
    'playlistGenerator.saveLocal.error',
    'playlistGenerator.submit.pasteIssuePrompt',
    'playlistGenerator.submit.captured',
    'playlistGenerator.submit.captureError',
    'playlistGenerator.submit.invalidIssueUrl',
];

function lookup(obj, key) {
    return key.split('.').reduce((n, p) => (n && typeof n === 'object' ? n[p] : undefined), obj);
}

describe('#2582 the sixteen missing keys', () => {
    it('all 16 keys exist in all six locales', () => {
        for (const l of LOCALES) {
            for (const k of NEUE_KEYS) {
                expect(lookup(i18n[l], k), `${l}: ${k}`).toBeTruthy();
            }
        }
    });

    it('translations are not just the English string copied over', () => {
        // The two that must differ in every language; the rest may legitimately
        // share a word (e.g. product names).
        for (const l of LOCALES.filter((x) => x !== 'en')) {
            expect(lookup(i18n[l], 'playlistGenerator.actions.working')).not.toBe(
                lookup(i18n.en, 'playlistGenerator.actions.working'),
            );
            expect(lookup(i18n[l], 'wizard.step5.tts.testNoSpeaker')).not.toBe(
                lookup(i18n.en, 'wizard.step5.tts.testNoSpeaker'),
            );
        }
    });

    it('placeholders survive translation', () => {
        const mit = {
            'playlistGenerator.saveLocal.success': '{filename}',
            'playlistGenerator.saveLocal.error': '{error}',
            'playlistGenerator.submit.captured': '{n}',
            'playlistGenerator.submit.captureError': '{error}',
        };
        for (const l of LOCALES) {
            for (const [k, ph] of Object.entries(mit)) {
                expect(lookup(i18n[l], k), `${l}: ${k} lost ${ph}`).toContain(ph);
            }
        }
    });
});

describe('#2582 the points unit on the two end screens', () => {
    const PLAYER_END = readSource('player-end.js');

    /** Run the shipped label helper against one locale. */
    const label = (lang) => evaluate(
        declaration(PLAYER_END, '_ptsLabel', 'player-end.js'),
        '_ptsLabel',
        { utils: lang === null ? {} : translator(i18n[lang]) },
    )();

    it('paints the translated unit on the shareable vinyl', () => {
        expect(label('de')).toBe(i18n.de.reveal.pointsShort.toUpperCase());
        expect(label('en')).toBe(i18n.en.reveal.pointsShort.toUpperCase());
    });

    it('never paints a raw key onto the graphic', () => {
        // The graphic is what guests post; "reveal.pointsShort" on it would
        // outlive the party. `t()` returns the key on a miss (#1402-B8), so the
        // miss has to be checked for explicitly.
        for (const l of LOCALES) {
            expect(label(l), l).not.toMatch(/^reveal\./i);
        }
        // i18n not loaded yet: an English unit beats a broken one.
        expect(label(null)).toBe('PTS');
        expect(evaluate(
            declaration(PLAYER_END, '_ptsLabel', 'player-end.js'),
            '_ptsLabel',
            { utils: { t: (key) => key } },
        )()).toBe('PTS');
    });

    it('the TV podium asks i18n for the unit (markup guard)', () => {
        // This one stays an assertion on the markup on purpose: the three
        // podium labels are static HTML translated by the `data-i18n` sweep at
        // load, so there is no function to run — the defect is literally
        // "does the element carry the attribute". The count is part of it: the
        // podium has three stands and #2582 was one of them being missed.
        const html = readFileSync(join(WWW_DIR, 'dashboard.html'), 'utf8');
        expect(html.match(/<span class="podium-pts">PTS<\/span>/g) || []).toHaveLength(0);
        expect(html.match(/podium-pts" data-i18n="reveal\.pointsShort"/g) || []).toHaveLength(3);
    });

    it('the unit exists in all six locales', () => {
        for (const l of LOCALES) {
            expect(lookup(i18n[l], 'reveal.pointsShort'), l).toBeTruthy();
        }
    });
});

describe('#2582 ADMIN_CANNOT_LEAVE looks up the code before the server text', () => {
    const PLAYER_CORE = readSource('player-core.js');

    /** The shipped branch, wrapped so it can be called. */
    function handle(data, { lang } = {}) {
        const toasts = [];
        const state = { intentionalLeave: true };
        const branch = block(
            PLAYER_CORE,
            "if (data.code === 'ADMIN_CANNOT_LEAVE') {",
            'player-core.js',
        );
        evaluate(
            [`function run(data) {\n${branch}\n}`],
            'run',
            { state, utils: lang ? translator(i18n[lang]) : {}, showToast: (m) => toasts.push(m) },
        )(data);
        return { toasts, state };
    }

    const SERVER_TEXT = 'Host cannot leave. End the game instead.';

    it('shows the German sentence to a German host', () => {
        const { toasts } = handle({ code: 'ADMIN_CANNOT_LEAVE', message: SERVER_TEXT }, { lang: 'de' });
        expect(toasts).toEqual([i18n.de.errors.ADMIN_CANNOT_LEAVE]);
        expect(toasts[0]).not.toBe(SERVER_TEXT);
    });

    it('prefers the translation in every locale that has one', () => {
        for (const l of LOCALES.filter((x) => x !== 'en')) {
            const { toasts } = handle(
                { code: 'ADMIN_CANNOT_LEAVE', message: SERVER_TEXT }, { lang: l },
            );
            expect(toasts[0], l).toBe(i18n[l].errors.ADMIN_CANNOT_LEAVE);
        }
    });

    it('falls back to the server text while i18n has nothing', () => {
        expect(handle({ code: 'ADMIN_CANNOT_LEAVE', message: SERVER_TEXT }).toasts)
            .toEqual([SERVER_TEXT]);
    });

    it('keeps the host in the game', () => {
        // The toast is only half of it: a rejected leave must not leave
        // `intentionalLeave` set, or the next socket close is treated as
        // deliberate and the host is dropped for real.
        expect(handle({ code: 'ADMIN_CANNOT_LEAVE', message: SERVER_TEXT }).state.intentionalLeave)
            .toBe(false);
    });

    it('the key exists in all six locales', () => {
        for (const l of LOCALES) {
            expect(lookup(i18n[l], 'errors.ADMIN_CANNOT_LEAVE'), l).toBeTruthy();
        }
    });
});

describe('#2582 the library-fix fallback can actually fall back (#1402-B8 again)', () => {
    const LIBRARY_FIX = readSource('admin/sections/library-fix.js');

    /** The shipped `_t`, with `BeatifyI18n` swapped for a controlled one. */
    function t(key, fallback, i18nStub) {
        return evaluate(
            declaration(LIBRARY_FIX, '_t', 'library-fix.js'),
            '_t',
            { window: { BeatifyI18n: i18nStub } },
        )(key, fallback);
    }

    const REAL = { t: (key) => lookup(i18n.de, key) ?? key };

    it('returns the translation when there is one', () => {
        expect(t('errors.ADMIN_CANNOT_LEAVE', 'fallback', REAL))
            .toBe(i18n.de.errors.ADMIN_CANNOT_LEAVE);
    });

    it('returns the fallback when the key is missing', () => {
        // The broken shape returned the key, which is truthy, so `|| fallback`
        // never ran and the admin showed "library.fix.noSuchKey" on screen.
        expect(t('library.fix.noSuchKey', 'Fix it', REAL)).toBe('Fix it');
    });

    it('returns the fallback when the translation is empty', () => {
        expect(t('whatever', 'Fix it', { t: () => '' })).toBe('Fix it');
    });

    it('returns the fallback before i18n has loaded at all', () => {
        expect(t('whatever', 'Fix it', undefined)).toBe('Fix it');
    });
});
