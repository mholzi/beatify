/**
 * #2585 — each guest's phone speaks the guest's language.
 *
 * The host picks one language in the wizard; the server repeats it in every
 * `state` frame; player-core handed that straight to `setLanguage()`. So the
 * Dutch au pair, the Italian colleague and the German family all read the same
 * phone — the host's — even though all six locales ship.
 *
 * The rule under test, in order: a chip the guest tapped, else the first
 * supported entry in `navigator.languages`, else the host's language. The last
 * step is a decision, not the old behaviour: `setLanguage()` normalises an
 * unsupported code to English, and a Portuguese phone in a German room is
 * better served by the room's language than by English.
 *
 * The state-frame branch is cut out of the shipped `player-core.js` and run
 * (see `helpers/js-source.js`) rather than grepped, so a rename is invisible
 * here and a behavioural regression is not.
 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import vm from 'node:vm';
import { block, evaluate, locale, readSource } from './helpers/js-source.js';
import { doc, el } from './helpers/mini-dom.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const I18N_SRC = readFileSync(join(__dirname, '..', 'i18n.js'), 'utf8');
const LOCALES = ['en', 'de', 'es', 'fr', 'it', 'nl'];

// ---------------------------------------------------------------------------
// i18n.js: normalisation + browser match, in a vm sandbox (as i18n-b8 does).
// ---------------------------------------------------------------------------

/** Load the shipped i18n IIFE with a fake navigator. */
function loadI18n(navigatorShim = { language: 'en' }) {
    const sandboxWindow = {};
    const ctx = {
        window: sandboxWindow,
        document: { documentElement: {}, querySelector: () => null, querySelectorAll: () => [] },
        navigator: navigatorShim,
        console,
        fetch: () => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({}) }),
        Promise, Object, Array, RegExp, String, encodeURIComponent, JSON, setTimeout,
    };
    vm.createContext(ctx);
    vm.runInContext(I18N_SRC, ctx);
    return sandboxWindow.BeatifyI18n;
}

describe('#2585 normalising a browser language tag', () => {
    const i18n = loadI18n();

    it('reduces a regional tag to its supported base', () => {
        expect(i18n.normalizeLanguage('nl-BE')).toBe('nl');
        expect(i18n.normalizeLanguage('de-AT')).toBe('de');
        expect(i18n.normalizeLanguage('IT-ch')).toBe('it');
        expect(i18n.normalizeLanguage('fr_CA')).toBe('fr');
    });

    it('returns null for a language we do not ship', () => {
        // The whole point of null over 'en': the caller has to tell "this phone
        // speaks something we have" apart from "we have no idea".
        expect(i18n.normalizeLanguage('pt-BR')).toBeNull();
        expect(i18n.normalizeLanguage('pl')).toBeNull();
    });

    it('returns null for junk instead of throwing', () => {
        expect(i18n.normalizeLanguage('')).toBeNull();
        expect(i18n.normalizeLanguage(null)).toBeNull();
        expect(i18n.normalizeLanguage(undefined)).toBeNull();
        expect(i18n.normalizeLanguage(42)).toBeNull();
        expect(i18n.normalizeLanguage('-')).toBeNull();
    });

    it('is derived from SUPPORTED_LANGUAGES, not a hand-listed ladder', () => {
        // Every shipped locale resolves, with no per-locale branch to forget.
        for (const code of i18n.getSupportedLanguages()) {
            expect(i18n.normalizeLanguage(code + '-XX')).toBe(code);
        }
    });
});

describe('#2585 matching the browser preference list', () => {
    it('takes the first supported entry of navigator.languages', () => {
        const i18n = loadI18n({ languages: ['pt-BR', 'it-IT', 'en-US'], language: 'pt-BR' });
        expect(i18n.matchBrowserLanguage()).toBe('it');
    });

    it('falls back to navigator.language when there is no list', () => {
        const i18n = loadI18n({ language: 'nl-NL' });
        expect(i18n.matchBrowserLanguage()).toBe('nl');
    });

    it('answers null when the phone speaks nothing we ship', () => {
        const i18n = loadI18n({ languages: ['pt-BR', 'pt'], language: 'pt-BR' });
        expect(i18n.matchBrowserLanguage()).toBeNull();
    });

    it('still gives detectBrowserLanguage a usable code (unchanged contract)', () => {
        expect(loadI18n({ language: 'pt-BR' }).detectBrowserLanguage()).toBe('en');
        expect(loadI18n({ language: 'de-DE' }).detectBrowserLanguage()).toBe('de');
    });
});

describe('#2585 every supported language can name itself', () => {
    const i18n = loadI18n();

    it('has an endonym and a flag for each supported code', () => {
        const options = i18n.getLanguageOptions();
        expect(options.map((o) => o.code)).toEqual(i18n.getSupportedLanguages());
        for (const option of options) {
            // The fallback label is the uppercased code; hitting it means a
            // locale was added to SUPPORTED_LANGUAGES without an endonym, and
            // Polish (#2475) is queued to do exactly that.
            expect(option.label, option.code).not.toBe(option.code.toUpperCase());
            expect(option.flag.length, option.code).toBeGreaterThan(0);
        }
    });

    it('names each language in itself, not in the reader\'s language', () => {
        const byCode = Object.fromEntries(i18n.getLanguageOptions().map((o) => [o.code, o.label]));
        expect(byCode.nl).toBe('Nederlands');
        expect(byCode.de).toBe('Deutsch');
        expect(byCode.it).toBe('Italiano');
    });

    it('hands out a copy of the supported list', () => {
        const first = i18n.getSupportedLanguages();
        first.push('pl');
        expect(i18n.getSupportedLanguages()).not.toContain('pl');
    });
});

// ---------------------------------------------------------------------------
// player-language.js — the module the join screen runs on.
// ---------------------------------------------------------------------------

globalThis.window = globalThis;

const {
    guestLanguage, resolveStateLanguage, readStoredLanguage, storeGuestLanguage,
    renderGuestLanguage, setupGuestLanguage, chooseGuestLanguage,
    STORAGE_KEY_GUEST_LANGUAGE,
} = await import('../player-language.js');

/** A localStorage stand-in whose contents the test can see. */
function fakeStorage(seed = {}) {
    const store = { ...seed };
    return {
        store,
        getItem: (k) => (k in store ? store[k] : null),
        setItem: (k, v) => { store[k] = String(v); },
        removeItem: (k) => { delete store[k]; },
    };
}

/** A localStorage that throws on every touch, as private mode can. */
const hostileStorage = {
    getItem() { throw new Error('SecurityError'); },
    setItem() { throw new Error('QuotaExceededError'); },
    removeItem() { throw new Error('SecurityError'); },
};

let restoreI18n;
beforeEach(() => {
    restoreI18n = globalThis.window.BeatifyI18n;
});
afterEach(() => {
    globalThis.window.BeatifyI18n = restoreI18n;
    delete globalThis.document;
});

/** Install a minimal BeatifyI18n on `window`, as the browser would. */
function installI18n({ current = 'en', browser = null } = {}) {
    const real = loadI18n();
    const applied = [];
    const shim = {
        applied,
        current,
        t: (key) => key,
        getLanguage: () => shim.current,
        setLanguage: (code) => { applied.push(code); shim.current = code; return Promise.resolve(code); },
        initPageTranslations: () => { shim.translated = (shim.translated || 0) + 1; },
        normalizeLanguage: real.normalizeLanguage,
        getSupportedLanguages: real.getSupportedLanguages,
        getLanguageOptions: real.getLanguageOptions,
        matchBrowserLanguage: () => browser,
    };
    globalThis.window.BeatifyI18n = shim;
    return shim;
}

describe('#2585 which language a phone claims for itself', () => {
    it('prefers the chip the guest tapped over the browser guess', () => {
        installI18n({ browser: 'de' });
        expect(guestLanguage(fakeStorage({ [STORAGE_KEY_GUEST_LANGUAGE]: 'it' }))).toBe('it');
    });

    it('uses the browser guess when nothing was tapped', () => {
        installI18n({ browser: 'nl' });
        expect(guestLanguage(fakeStorage())).toBe('nl');
    });

    it('claims nothing when the phone speaks a language we do not ship', () => {
        installI18n({ browser: null });
        expect(guestLanguage(fakeStorage())).toBeNull();
    });

    it('ignores a stored value that is no longer a supported locale', () => {
        // A 'pl' left behind by a build where Polish existed (#2475) must not
        // pin the phone to a locale whose JSON is gone.
        installI18n({ browser: 'de' });
        expect(readStoredLanguage(fakeStorage({ [STORAGE_KEY_GUEST_LANGUAGE]: 'pl' }))).toBeNull();
        expect(guestLanguage(fakeStorage({ [STORAGE_KEY_GUEST_LANGUAGE]: 'pl' }))).toBe('de');
    });

    it('survives a localStorage that throws (private mode)', () => {
        installI18n({ browser: 'fr' });
        expect(() => readStoredLanguage(hostileStorage)).not.toThrow();
        expect(readStoredLanguage(hostileStorage)).toBeNull();
        expect(guestLanguage(hostileStorage)).toBe('fr');
        expect(() => storeGuestLanguage('it', hostileStorage)).not.toThrow();
        expect(storeGuestLanguage('it', hostileStorage)).toBe(false);
    });

    it('stores a normalised code, and refuses one we do not ship', () => {
        installI18n();
        const storage = fakeStorage();
        expect(storeGuestLanguage('NL-be', storage)).toBe(true);
        expect(storage.store[STORAGE_KEY_GUEST_LANGUAGE]).toBe('nl');
        expect(storeGuestLanguage('pt', storage)).toBe(false);
        expect(storage.store[STORAGE_KEY_GUEST_LANGUAGE]).toBe('nl');
    });

    it('uses a key of its own, not the host-language cache', () => {
        // player-core writes the host's pick to `beatify_language`; if the two
        // shared a key the host would overwrite the guest on every frame.
        expect(STORAGE_KEY_GUEST_LANGUAGE).not.toBe('beatify_language');
        expect(readSource('player-core.js')).toContain("STORAGE_KEY_LANGUAGE = 'beatify_language'");
    });
});

describe('#2585 the host language is a default, not a command', () => {
    it('yields to a guest who has a language of their own', () => {
        expect(resolveStateLanguage('nl', 'de')).toBe('nl');
    });

    it('follows the host when the guest has none', () => {
        expect(resolveStateLanguage(null, 'de')).toBe('de');
    });

    it('has nothing to apply when neither side knows', () => {
        expect(resolveStateLanguage(null, null)).toBeNull();
    });
});

// ---------------------------------------------------------------------------
// The branch that ships in player-core.js, executed.
// ---------------------------------------------------------------------------

const PLAYER_CORE = readSource('player-core.js');
const LANGUAGE_BRANCH = block(PLAYER_CORE, '        if (data.language) {', 'player-core.js');

/**
 * Run the shipped `if (data.language) { … }` branch of handleServerMessage.
 * Everything it closes over is stubbed, so a missing stub is a ReferenceError
 * rather than a silent pass.
 */
async function runLanguageBranch({ hostLanguage, guest, current }) {
    const seen = { setLanguage: [], gameLanguage: [], guestRenders: 0 };
    evaluate([LANGUAGE_BRANCH], 'true', {
        data: { language: hostLanguage, phase: 'LOBBY' },
        players: [],
        storeGameLanguage: (l) => seen.gameLanguage.push(l),
        guestLanguage: () => guest,
        resolveStateLanguage,
        BeatifyI18n: {
            getLanguage: () => current,
            setLanguage: (l) => { seen.setLanguage.push(l); return Promise.resolve(l); },
            initPageTranslations: () => {},
        },
        renderGuestLanguage: () => { seen.guestRenders += 1; },
        renderPlayerList: () => {},
        renderDifficultyBadge: () => {},
        renderLobbyBriefLine: () => {},
        pushRevealRender: () => {},
        updateControlBarState: () => {},
        renderHostDrawer: () => {},
    });
    await Promise.resolve();
    await Promise.resolve();
    return seen;
}

describe('#2585 a state frame no longer overwrites the guest', () => {
    it('leaves a Dutch phone in Dutch at a German host\'s party', async () => {
        const seen = await runLanguageBranch({ hostLanguage: 'de', guest: 'nl', current: 'nl' });
        expect(seen.setLanguage).toEqual([]);
        expect(seen.gameLanguage).toEqual(['de']);
    });

    it('re-asserts the guest language if a frame already flipped the phone', async () => {
        const seen = await runLanguageBranch({ hostLanguage: 'de', guest: 'nl', current: 'de' });
        expect(seen.setLanguage).toEqual(['nl']);
    });

    it('applies the host language to a phone with none of its own', async () => {
        const seen = await runLanguageBranch({ hostLanguage: 'de', guest: null, current: 'en' });
        expect(seen.setLanguage).toEqual(['de']);
        // The line under the join button names the language in force, so it
        // has to be redrawn when the host's pick lands.
        expect(seen.guestRenders).toBe(1);
    });

    it('still records the host language for the next cold start', async () => {
        const seen = await runLanguageBranch({ hostLanguage: 'it', guest: 'nl', current: 'nl' });
        expect(seen.gameLanguage).toEqual(['it']);
    });
});

// ---------------------------------------------------------------------------
// The join-screen line.
// ---------------------------------------------------------------------------

/** The join-language markup as a fake DOM, plus handles to inspect it. */
function joinDom() {
    const listeners = new Map();
    const withEvents = (node) => {
        node.addEventListener = (type, fn) => {
            const key = node;
            if (!listeners.has(key)) listeners.set(key, {});
            (listeners.get(key)[type] ||= []).push(fn);
        };
        node.click = () => (listeners.get(node)?.click || []).forEach((fn) => fn({ type: 'click' }));
        return node;
    };
    const root = el('join-language');
    root.classList.add('hidden');
    const current = el('join-language-current');
    const toggle = withEvents(el('join-language-toggle'));
    const chips = withEvents(el('join-language-chips'));
    chips.classList.add('hidden');
    globalThis.document = doc({
        'join-language': root,
        'join-language-current': current,
        'join-language-toggle': toggle,
        'join-language-chips': chips,
    }, { createElement: withEvents });
    return { root, current, toggle, chips };
}

describe('#2585 the join screen states the language', () => {
    it('names the language in force, in that language', () => {
        installI18n({ current: 'nl' });
        const dom = joinDom();
        renderGuestLanguage();
        expect(dom.current.textContent).toContain('Nederlands');
        expect(dom.root.classList.contains('hidden')).toBe(false);
    });

    it('offers the other languages, not the one already in force', () => {
        installI18n({ current: 'nl' });
        const dom = joinDom();
        renderGuestLanguage();
        const offered = dom.chips.appended.map((c) => c.getAttribute('data-lang'));
        expect(offered).not.toContain('nl');
        expect(offered).toEqual(['en', 'de', 'es', 'fr', 'it']);
        expect(dom.chips.appended[0].textContent).toContain('English');
    });

    it('keeps the chips out of the way until the link is tapped', () => {
        installI18n({ current: 'de' });
        const dom = joinDom();
        setupGuestLanguage();
        expect(dom.chips.classList.contains('hidden')).toBe(true);
        expect(dom.toggle.getAttribute('aria-expanded')).toBe('false');

        dom.toggle.click();
        expect(dom.chips.classList.contains('hidden')).toBe(false);
        expect(dom.toggle.getAttribute('aria-expanded')).toBe('true');

        dom.toggle.click();
        expect(dom.chips.classList.contains('hidden')).toBe(true);
        expect(dom.toggle.getAttribute('aria-expanded')).toBe('false');
    });

    it('applies, stores and re-states the language a guest taps', async () => {
        const shim = installI18n({ current: 'de' });
        const storage = fakeStorage();
        globalThis.localStorage = storage;
        const dom = joinDom();
        setupGuestLanguage();
        dom.toggle.click();

        const italian = dom.chips.appended.find((c) => c.getAttribute('data-lang') === 'it');
        // The fake DOM keeps every child ever appended, so remember where the
        // re-render starts.
        const beforeRerender = dom.chips.appended.length;
        italian.click();
        await Promise.resolve();
        await Promise.resolve();

        expect(shim.applied).toEqual(['it']);
        expect(storage.store[STORAGE_KEY_GUEST_LANGUAGE]).toBe('it');
        expect(dom.current.textContent).toContain('Italiano');
        // Contradicted once, the statement now reads Italian and offers German.
        const reoffered = dom.chips.appended.slice(beforeRerender).map((c) => c.getAttribute('data-lang'));
        expect(reoffered).toEqual(['en', 'de', 'es', 'fr', 'nl']);
        expect(dom.chips.classList.contains('hidden')).toBe(true);
        delete globalThis.localStorage;
    });

    it('marks each chip with its own lang so a screen reader switches voice', () => {
        installI18n({ current: 'en' });
        const dom = joinDom();
        renderGuestLanguage();
        for (const chip of dom.chips.appended) {
            expect(chip.getAttribute('lang')).toBe(chip.getAttribute('data-lang'));
        }
    });

    it('hides the row rather than showing an unnamed language', () => {
        globalThis.window.BeatifyI18n = undefined;
        const dom = joinDom();
        renderGuestLanguage();
        expect(dom.root.classList.contains('hidden')).toBe(true);
    });

    it('does nothing on a page without the join markup', () => {
        installI18n();
        globalThis.document = doc({});
        expect(() => renderGuestLanguage()).not.toThrow();
        expect(() => setupGuestLanguage()).not.toThrow();
    });

    it('does nothing when i18n never loaded and a chip is somehow tapped', async () => {
        globalThis.window.BeatifyI18n = undefined;
        await expect(chooseGuestLanguage('it')).resolves.toBeUndefined();
    });
});

// ---------------------------------------------------------------------------
// Translations.
// ---------------------------------------------------------------------------

describe('#2585 the line is translated everywhere', () => {
    const KEYS = ['otherLanguage', 'chooseLanguage'];

    it('carries both keys in all six locales', () => {
        for (const lang of LOCALES) {
            const join = locale(lang).join;
            expect(typeof join, lang).toBe('object');
            for (const key of KEYS) {
                expect(typeof join[key], `${lang}.join.${key}`).toBe('string');
                expect(join[key].trim().length, `${lang}.join.${key}`).toBeGreaterThan(0);
            }
        }
    });

    it('translates them rather than copying English', () => {
        const english = locale('en').join;
        for (const lang of LOCALES.filter((l) => l !== 'en')) {
            const join = locale(lang).join;
            for (const key of KEYS) {
                expect(join[key], `${lang}.join.${key}`).not.toBe(english[key]);
            }
        }
    });

    it('keeps markup out of the strings', () => {
        for (const lang of LOCALES) {
            for (const key of KEYS) {
                expect(locale(lang).join[key]).not.toMatch(/[<>{}]/);
            }
        }
    });
});
