/**
 * Unit tests for i18n.js concurrency safety (#1399).
 *
 * setLanguage() sets currentLanguage synchronously, then awaits an async
 * fetch before committing the module-global `translations`. Two concurrent
 * setLanguage() calls (admin loadSavedSettings vs. wizard language chip vs.
 * dashboard state-driven switch) could finish out of order: a slow de.json
 * fetch landing AFTER setLanguage('en') would clobber the active locale,
 * leaving currentLanguage='en' but translations=German.
 *
 * These tests load the IIFE source in a vm sandbox (mirroring ha-auth.test.js)
 * with a controllable fetch whose per-locale resolution we can delay, and prove
 * a stale loadTranslations fetch does NOT overwrite a newer setLanguage locale.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';

const __dirname = dirname(fileURLToPath(import.meta.url));
const SRC = readFileSync(join(__dirname, '..', 'i18n.js'), 'utf8');

// Translation payloads keyed by locale; `greeting` makes the active locale
// trivially observable via BeatifyI18n.t('greeting').
const PAYLOADS = {
    en: { greeting: 'Hello' },
    de: { greeting: 'Hallo' },
    es: { greeting: 'Hola' },
};

/**
 * Build a fetch shim with manually-resolvable promises per locale.
 * Returns { fetch, release(lang), fetched } so a test can drive completion
 * order independently of call order.
 */
function makeControllableFetch() {
    const pending = {}; // lang -> { resolve }
    const fetched = []; // order of fetch calls (lang codes)
    const fetchFn = (url) => {
        const m = /i18n\/([a-z]{2})\.json/.exec(url);
        const lang = m ? m[1] : 'en';
        fetched.push(lang);
        return new Promise((resolve) => {
            const respond = () => resolve({
                ok: true,
                status: 200,
                json: () => Promise.resolve(PAYLOADS[lang] || {}),
            });
            pending[lang] = { respond };
        });
    };
    return {
        fetch: fetchFn,
        fetched,
        release(lang) {
            if (!pending[lang]) throw new Error('no pending fetch for ' + lang);
            pending[lang].respond();
        },
        isPending(lang) { return !!pending[lang]; },
    };
}

function loadI18n(fetchFn) {
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
        Promise,
        Object,
        Array,
        RegExp,
        encodeURIComponent,
        JSON,
        setTimeout,
    };
    vm.createContext(ctx);
    vm.runInContext(SRC, ctx);
    return sandboxWindow.BeatifyI18n;
}

// Let microtasks flush so awaited continuations run after a release().
const flush = () => new Promise((r) => setTimeout(r, 0));

describe('i18n concurrency (#1399)', () => {
    it('a stale (slow) de fetch does NOT clobber a newer en locale', async () => {
        const fc = makeControllableFetch();
        const i18n = loadI18n(fc.fetch);

        // First flush English fallback (fetched eagerly on the first load).
        const pDe = i18n.setLanguage('de');
        // de load also fetches 'en' fallback first; release it so de fetch starts.
        await flush();
        fc.release('en');
        await flush();

        // Now start switching to es while de is still in flight.
        const pEs = i18n.setLanguage('es');
        await flush();

        // Release the NEWER es load first, then the STALE de load.
        fc.release('es');
        await pEs;
        fc.release('de');
        await pDe;
        await flush();

        // Active locale is es; the late de result must have been discarded.
        expect(i18n.getLanguage()).toBe('es');
        expect(i18n.t('greeting')).toBe('Hola');
    });

    it('out-of-order completion: slow de lands after es, es wins', async () => {
        const fc = makeControllableFetch();
        const i18n = loadI18n(fc.fetch);

        const pDe = i18n.setLanguage('de');
        await flush();
        fc.release('en'); // fallback
        await flush();

        const pEs = i18n.setLanguage('es');
        await flush();
        fc.release('es');
        fc.release('de'); // both released; es is the latest gen
        await Promise.all([pDe, pEs]);
        await flush();

        expect(i18n.getLanguage()).toBe('es');
        expect(i18n.t('greeting')).toBe('Hola');
    });

    it('languageReady() resolves to the latest in-flight load, not a superseded one', async () => {
        const fc = makeControllableFetch();
        const i18n = loadI18n(fc.fetch);

        const pDe = i18n.setLanguage('de');
        await flush();
        fc.release('en');
        await flush();

        i18n.setLanguage('es'); // supersede de
        await flush();

        // languageReady reflects the es load; awaiting it then reading t()
        // must give the es locale once es resolves.
        const ready = i18n.languageReady();
        fc.release('es');
        fc.release('de');
        await ready;
        await pDe;
        await flush();

        expect(i18n.getLanguage()).toBe('es');
        expect(i18n.t('greeting')).toBe('Hola');
    });

    it('single switch still commits its translations normally', async () => {
        const fc = makeControllableFetch();
        const i18n = loadI18n(fc.fetch);

        const pDe = i18n.setLanguage('de');
        await flush();
        fc.release('en');
        await flush();
        fc.release('de');
        await pDe;

        expect(i18n.getLanguage()).toBe('de');
        expect(i18n.t('greeting')).toBe('Hallo');
        expect(i18n.isReady()).toBe(true);
    });
});
