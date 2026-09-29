/**
 * #3057: two places still spoke English on a localized party.
 *
 *  1. The host phone showed the server's hard-coded English `message` on an
 *     error frame (and on the REST fallback / rematch toast) although
 *     `errors.<CODE>` exists in every locale.
 *  2. offline.html was English-only.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';
import { localizedErrorMessage } from '../admin/api.js';

const here = dirname(fileURLToPath(import.meta.url));
const www = join(here, '..', '..');
const read = (p) => readFileSync(join(www, p), 'utf8');

const DE = JSON.parse(read('i18n/de.json'));

function installI18n(dict) {
    globalThis.window = globalThis.window || globalThis;
    globalThis.BeatifyI18n = {
        t(key, params) {
            const v = key.split('.').reduce((o, k) => (o ? o[k] : undefined), dict);
            return typeof v === 'string' ? v : key;
        },
    };
    globalThis.window.BeatifyI18n = globalThis.BeatifyI18n;
}

describe('localizedErrorMessage (#3057)', () => {
    beforeEach(() => installI18n(DE));

    it('shows the translated errors.<CODE>, not the server English', () => {
        const msg = localizedErrorMessage({
            code: 'NAME_TAKEN', message: 'Name taken, choose another',
        });
        expect(msg).toBe(DE.errors.NAME_TAKEN);
        expect(msg).not.toBe('Name taken, choose another');
    });

    it('falls back to the server message for a code without a translation', () => {
        expect(localizedErrorMessage({ code: 'SOMETHING_NEW', message: 'Odd thing' }))
            .toBe('Odd thing');
    });

    it('falls back to the server message without i18n', () => {
        delete globalThis.window.BeatifyI18n;
        expect(localizedErrorMessage({ code: 'NAME_TAKEN', message: 'Name taken' }))
            .toBe('Name taken');
    });
});

describe('wiring', () => {
    it('the WS error branches no longer hand data.message to the UI', () => {
        const api = read('js/admin/api.js');
        expect(api).not.toMatch(/deps\.show(Error|SpeakerSetupError)\(data\.message\)/);
        expect(api).toContain('localizedErrorMessage(data)');
    });
    it('the REST start-gameplay fallback goes through errorHeadlineAndDetail', () => {
        const admin = read('js/admin.js');
        expect(admin).not.toContain('showSetupError(data.message ||');
        expect(admin).toContain('errorHeadlineAndDetail(');
    });
    it('the rematch failure toast looks the code up first', () => {
        const end = read('js/player-end.js');
        expect(end).not.toContain("throw new Error(e.message || 'Rematch failed')");
        expect(end).toContain('joinRejectionMessage(e.code');
    });
});

describe('offline.html (#3057)', () => {
    const html = read('offline.html');
    const script = html.slice(html.indexOf('<script>') + 8, html.indexOf('</script>'));

    function run({ store = {}, languages = [], language = '' } = {}) {
        const els = {
            'offline-title': { textContent: '' },
            'offline-text': { textContent: '' },
            'offline-retry': { textContent: '' },
        };
        const doc = { documentElement: { lang: 'en' }, getElementById: (id) => els[id] };
        const ctx = {
            document: doc,
            localStorage: { getItem: (k) => (k in store ? store[k] : null) },
            navigator: { languages, language },
        };
        vm.runInNewContext(script, ctx);
        return { lang: doc.documentElement.lang, title: els['offline-title'].textContent,
                 text: els['offline-text'].textContent, retry: els['offline-retry'].textContent };
    }

    it('has all three lines in all six languages', () => {
        for (const code of ['en', 'de', 'es', 'fr', 'nl', 'it']) {
            expect(html).toMatch(new RegExp(`\\b${code}: \\[`));
        }
        for (const code of ['de', 'es', 'fr', 'nl', 'it']) {
            const r = run({ store: { beatify_guest_language: code } });
            expect(r.lang).toBe(code);
            expect(r.title).not.toBe("You're offline");
            expect(r.text).not.toMatch(/^Beatify can't/);
            expect(r.retry).not.toBe('Retry');
        }
    });

    it('prefers the guest pick, then the last game language, then the browser', () => {
        expect(run({ store: { beatify_guest_language: 'nl', beatify_language: 'de' },
                     languages: ['fr-FR'] }).lang).toBe('nl');
        expect(run({ store: { beatify_language: 'de' }, languages: ['fr-FR'] }).lang).toBe('de');
        expect(run({ languages: ['it-IT', 'en'] }).lang).toBe('it');
        expect(run({ language: 'es-ES' }).lang).toBe('es');
    });

    it('stays English for an unsupported language', () => {
        const r = run({ languages: ['ja-JP'], language: 'ja-JP' });
        expect(r.lang).toBe('en');
        expect(r.title).toBe("You're offline");
    });
});
