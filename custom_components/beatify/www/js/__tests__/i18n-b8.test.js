/**
 * #1402-B8 regression tests for i18n.js.
 *
 * 1. setLanguage() resolves with the EFFECTIVELY-APPLIED (normalized) code so a
 *    dashboard state carrying an unsupported language can't spin forever
 *    (getLanguage() never equalling the requested 'pt').
 * 2. getErrorMessage() falls back to errors.UNKNOWN for an unknown code instead
 *    of leaking the raw "errors.FOO" key (the old `|| t('errors.UNKNOWN')` was
 *    dead code because t() returns the key itself, never a falsy value).
 *
 * Loads the IIFE source in a vm sandbox (mirrors i18n-concurrency.test.js).
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';

const __dirname = dirname(fileURLToPath(import.meta.url));
const SRC = readFileSync(join(__dirname, '..', 'i18n.js'), 'utf8');

const PAYLOADS = {
    en: { greeting: 'Hello', errors: { TIMEOUT: 'Timed out', UNKNOWN: 'Something went wrong' } },
    de: { greeting: 'Hallo', errors: { TIMEOUT: 'Zeitüberschreitung', UNKNOWN: 'Etwas ist schiefgelaufen' } },
};

function loadI18n() {
    const fetchFn = (url) => {
        const m = /i18n\/([a-z]{2})\.json/.exec(url);
        const lang = m ? m[1] : 'en';
        return Promise.resolve({
            ok: true,
            status: 200,
            json: () => Promise.resolve(PAYLOADS[lang] || {}),
        });
    };
    const docShim = {
        documentElement: { lang: 'en' },
        querySelector: () => null,
        querySelectorAll: () => [],
    };
    const sandboxWindow = {};
    const ctx = {
        window: sandboxWindow,
        document: docShim,
        navigator: { language: 'en' },
        console,
        fetch: fetchFn,
        Promise, Object, Array, RegExp, encodeURIComponent, JSON, setTimeout,
    };
    vm.createContext(ctx);
    vm.runInContext(SRC, ctx);
    return sandboxWindow.BeatifyI18n;
}

describe('i18n #1402-B8: setLanguage resolves with applied code', () => {
    it('a supported code resolves with the same code', async () => {
        const i18n = loadI18n();
        const applied = await i18n.setLanguage('de');
        expect(applied).toBe('de');
        expect(i18n.getLanguage()).toBe('de');
    });

    it('an UNSUPPORTED code resolves with the normalized fallback (en), not the request', async () => {
        const i18n = loadI18n();
        const applied = await i18n.setLanguage('pt'); // not in SUPPORTED_LANGUAGES
        // Loop-break invariant: applied must equal getLanguage() so a caller
        // comparing the two settles instead of re-rendering forever.
        expect(applied).toBe('en');
        expect(i18n.getLanguage()).toBe('en');
        expect(applied).toBe(i18n.getLanguage());
    });

    it('early-return path (same lang, already loaded) still resolves with the code', async () => {
        const i18n = loadI18n();
        await i18n.setLanguage('de');
        const again = await i18n.setLanguage('de');
        expect(again).toBe('de');
    });
});

describe('i18n #1402-B8: getErrorMessage fallback to UNKNOWN', () => {
    it('returns the real message for a known error code', async () => {
        const i18n = loadI18n();
        await i18n.setLanguage('en');
        expect(i18n.getErrorMessage('TIMEOUT')).toBe('Timed out');
    });

    it('returns errors.UNKNOWN (not the raw key) for an unknown code', async () => {
        const i18n = loadI18n();
        await i18n.setLanguage('en');
        const msg = i18n.getErrorMessage('NOPE_DOES_NOT_EXIST');
        expect(msg).toBe('Something went wrong');
        expect(msg).not.toBe('errors.NOPE_DOES_NOT_EXIST');
    });
});
