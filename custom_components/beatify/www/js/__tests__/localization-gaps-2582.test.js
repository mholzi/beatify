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
 */
import { describe, it, expect, beforeAll } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const JS = join(__dirname, '..');            // .../www/js
const WWW = join(__dirname, '..', '..');    // .../www
const LOCALES = ['en', 'de', 'es', 'fr', 'it', 'nl'];

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

const i18n = {};
beforeAll(() => {
    for (const l of LOCALES) {
        i18n[l] = JSON.parse(readFileSync(join(WWW, 'i18n', `${l}.json`), 'utf8'));
    }
});

function lookup(obj, key) {
    return key.split('.').reduce((n, p) => (n && typeof n === 'object' ? n[p] : undefined), obj);
}

describe('#2582 localisation gaps', () => {
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

    it('the TV podium no longer hard-codes PTS', () => {
        const html = readFileSync(join(WWW, 'dashboard.html'), 'utf8');
        const roh = html.match(/<span class="podium-pts">PTS<\/span>/g) || [];
        expect(roh.length).toBe(0);
        const uebersetzt = html.match(/podium-pts" data-i18n="reveal\.pointsShort"/g) || [];
        expect(uebersetzt.length).toBe(3);
    });

    it('the shared vinyl graphic asks i18n for the unit', () => {
        const src = readFileSync(join(JS, 'player-end.js'), 'utf8');
        expect(src).toContain("utils.t('reveal.pointsShort')");
        expect(src).not.toContain("ctx.fillText('PTS'");
    });

    it('ADMIN_CANNOT_LEAVE looks up the code before the server text', () => {
        const src = readFileSync(join(JS, 'player-core.js'), 'utf8');
        expect(src).toContain("utils.t('errors.ADMIN_CANNOT_LEAVE')");
        expect(src).not.toContain(
            "showToast(data.message || 'Host cannot leave. End the game instead.')",
        );
        for (const l of LOCALES) {
            expect(lookup(i18n[l], 'errors.ADMIN_CANNOT_LEAVE'), l).toBeTruthy();
        }
    });

    it('the library-fix fallback can actually fall back (#1402-B8 again)', () => {
        const src = readFileSync(join(JS, 'admin', 'sections', 'library-fix.js'), 'utf8');
        // The broken shape returned the key, which is truthy, so `|| fallback`
        // never ran.
        expect(src).not.toContain('window.BeatifyI18n.t(key)) || fallback');
        expect(src).toContain('s === key');
    });
});
