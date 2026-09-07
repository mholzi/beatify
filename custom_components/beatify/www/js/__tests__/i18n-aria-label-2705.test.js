/**
 * #2705 — initPageTranslations() applies data-i18n-aria-label.
 *
 * player.html had carried the attribute on eight controls (the reaction
 * buttons, the round-stats and breakdown info buttons, the auto-advance
 * countdown) since those screens landed, but nothing in i18n.js ever read it:
 * every screen reader heard "Fire reaction" in English regardless of locale.
 * admin.html's icon-only install and analytics buttons need the same, so the
 * attribute is now honoured — and this test keeps it honoured.
 *
 * Loads the IIFE source in a vm sandbox (mirrors i18n-b8.test.js).
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';

const __dirname = dirname(fileURLToPath(import.meta.url));
const SRC = readFileSync(join(__dirname, '..', 'i18n.js'), 'utf8');

const PAYLOADS = {
    en: { reaction: { fire: 'Fire reaction' }, common: { close: 'Close' } },
    de: { reaction: { fire: 'Feuer-Reaktion' }, common: { close: 'Schließen' } },
};

/** Minimal element stub: remembers attributes and the last textContent write. */
function el(attrs) {
    return {
        attrs: { ...attrs },
        textContent: '',
        title: '',
        placeholder: '',
        getAttribute(name) {
            return Object.prototype.hasOwnProperty.call(this.attrs, name)
                ? this.attrs[name]
                : null;
        },
        setAttribute(name, value) {
            this.attrs[name] = value;
        },
    };
}

function loadI18n(elements) {
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
        querySelectorAll: (selector) => elements[selector] || [],
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

describe('#2705: data-i18n-aria-label', () => {
    it('rewrites aria-label into the active locale', async () => {
        const button = el({
            'data-i18n-aria-label': 'reaction.fire',
            'aria-label': 'Fire reaction',
        });
        const i18n = loadI18n({ '[data-i18n-aria-label]': [button] });
        await i18n.setLanguage('de');
        i18n.initPageTranslations();
        expect(button.getAttribute('aria-label')).toBe('Feuer-Reaktion');
    });

    it('leaves the markup alone when the key is missing', async () => {
        const button = el({
            'data-i18n-aria-label': 'reaction.nope',
            'aria-label': 'Nope reaction',
        });
        const i18n = loadI18n({ '[data-i18n-aria-label]': [button] });
        await i18n.setLanguage('de');
        i18n.initPageTranslations();
        expect(button.getAttribute('aria-label')).toBe('Nope reaction');
    });

    it('does not write textContent — the label is the only target', async () => {
        const button = el({
            'data-i18n-aria-label': 'common.close',
            'aria-label': 'Close',
        });
        const i18n = loadI18n({ '[data-i18n-aria-label]': [button] });
        await i18n.setLanguage('de');
        i18n.initPageTranslations();
        expect(button.textContent).toBe('');
        expect(button.getAttribute('aria-label')).toBe('Schließen');
    });
});
