/**
 * #2696: the analytics page never initialised translations.
 *
 * `analytics.js` called neither `BeatifyI18n.init()` nor
 * `initPageTranslations()`, and `analytics.html` loaded i18n.js plus the
 * bundle with no inline init. So `translations` stayed `{}`, `t()` handed
 * every key straight back, and the page rendered raw keys — the header
 * printed the literal "analyticsDashboard.none", the modal printed
 * "analyticsDashboard.pagination", and ~40 data-i18n spans stayed English in
 * every language. Nobody noticed for months, because a raw key still looks
 * like text.
 *
 * The one line that looked like it would fix it — `if (window.applyTranslations)`
 * in `renderPlaylistSongGrid` — was itself dead: nothing in the repo ever
 * assigns `window.applyTranslations`. i18n.js exposes `initPageTranslations`
 * on `BeatifyI18n`, never on `window`. Same dead-guard shape as #2679.
 *
 * This is a source-level guard, not a render test: the point is that a NEW
 * page cannot ship without wiring i18n, and that the dead `window.applyTranslations`
 * shape cannot come back anywhere in the tree.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const JS = join(__dirname, '..');           // .../www/js
const WWW = join(__dirname, '..', '..');    // .../www
const LOCALES = ['en', 'de', 'es', 'fr', 'it', 'nl'];

// A served `<script src>` maps back to the readable source the build compiles.
// `.min.js` is a 1:1 minify (scripts/build.mjs MINIFY); the two bundles name a
// different entry module (scripts/build.mjs BUNDLES).
const BUNDLE_ENTRY = {
    'player.bundle.min.js': 'player-core.js',
    'admin.min.js': 'admin.js',
};

// i18n.js DEFINES init/initPageTranslations. It must never count as a page
// CALLING them, or every page would pass just by loading the module.
const NOT_A_CALLER = new Set(['i18n.js']);

function sourceFor(fileName) {
    if (BUNDLE_ENTRY[fileName]) return BUNDLE_ENTRY[fileName];
    return fileName.replace(/\.min\.js$/, '.js');
}

/** Readable JS sources a page pulls in, plus its own inline scripts. */
function initCandidates(html) {
    const texts = [];

    // Inline <script> blocks — launcher.html initialises i18n this way.
    for (const m of html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/g)) {
        texts.push(m[1]);
    }

    for (const m of html.matchAll(/<script[^>]*\bsrc="\/beatify\/static\/js\/([^"?]+)/g)) {
        const served = m[1];
        if (served.startsWith('vendor/')) continue;
        const source = sourceFor(served.split('/').pop());
        if (NOT_A_CALLER.has(source)) continue;
        const path = join(JS, source);
        if (existsSync(path)) texts.push(readFileSync(path, 'utf8'));
    }

    return texts;
}

const PAGES = readdirSync(WWW)
    .filter((f) => f.endsWith('.html'))
    .map((f) => ({ name: f, html: readFileSync(join(WWW, f), 'utf8') }))
    .filter((p) => p.html.includes('data-i18n'));

function lookup(obj, key) {
    return key.split('.').reduce((n, p) => (n && typeof n === 'object' ? n[p] : undefined), obj);
}

describe('#2696 every translated page initialises i18n', () => {
    it('finds the pages to check', () => {
        // Cheap canary: if the glob ever comes back empty the assertions below
        // would all pass vacuously.
        expect(PAGES.length).toBeGreaterThanOrEqual(5);
        expect(PAGES.map((p) => p.name)).toContain('analytics.html');
    });

    it.each(PAGES.map((p) => p.name))('%s loads translations at startup', (name) => {
        const page = PAGES.find((p) => p.name === name);
        const texts = initCandidates(page.html);

        expect(
            texts.some((t) => t.includes('BeatifyI18n.init(')),
            `${name} has data-i18n markup but nothing it loads calls BeatifyI18n.init()`,
        ).toBe(true);

        expect(
            texts.some((t) => t.includes('BeatifyI18n.initPageTranslations(')),
            `${name} never calls BeatifyI18n.initPageTranslations(), so its data-i18n spans stay untranslated`,
        ).toBe(true);
    });
});

describe('#2696 the dead window.applyTranslations guard stays gone', () => {
    const sources = readdirSync(JS, { recursive: true })
        .filter((f) => typeof f === 'string' && f.endsWith('.js'))
        .filter((f) => !f.endsWith('.min.js') && !f.startsWith('vendor/') && !f.startsWith('__tests__'));

    it('no source references window.applyTranslations', () => {
        const offenders = sources.filter((f) =>
            readFileSync(join(JS, f), 'utf8').includes('applyTranslations'),
        );
        // Nothing assigns window.applyTranslations, so any guard on it is dead
        // code that silently skips the translation pass it claims to run.
        expect(offenders).toEqual([]);
    });
});

describe('#2696 analytics runtime strings resolve to real translations', () => {
    const analytics = readFileSync(join(JS, 'analytics.js'), 'utf8');
    const keys = [...analytics.matchAll(/BeatifyI18n\.t\('([^']+)'/g)].map((m) => m[1]);

    it('uses at least the two keys the issue named', () => {
        expect(keys).toContain('analyticsDashboard.none');
        expect(keys).toContain('analyticsDashboard.pagination');
    });

    it.each(LOCALES)('%s defines every key analytics.js renders at runtime', (locale) => {
        const dict = JSON.parse(readFileSync(join(WWW, 'i18n', `${locale}.json`), 'utf8'));
        const missing = keys.filter((k) => typeof lookup(dict, k) !== 'string');
        // A key missing from a locale prints the raw key just as surely as a
        // missing init() does.
        expect(missing).toEqual([]);
    });
});
