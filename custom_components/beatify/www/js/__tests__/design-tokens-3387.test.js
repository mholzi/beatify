/**
 * #3387: one shared design-token file, and every token in use is defined.
 *
 * The design-system review found 48 `var(--…)` names with no definition. Five
 * are set by JavaScript at runtime; the other 43 were leftovers from older
 * naming schemes. A `var()` without a fallback that points at nothing makes the
 * whole declaration invalid, so the browser drops it silently: the capability
 * dot in the wizard and the "party lights off" dot went transparent, inputs and
 * request rows lost their border, and "dim" text rendered white.
 *
 * The checks:
 *  1. every `var(--x)` in the readable CSS sources, the inline `<style>` blocks
 *     and `style="…"` attributes of the pages, and the JS sources is defined
 *     somewhere in CSS/HTML, or is one of the names JS sets at runtime;
 *  2. the global palette lives in tokens.css only: no other `:root` block, and
 *     the launcher and the offline page link the token file;
 *  3. white on the primary-button fill reaches WCAG AA for normal text (4.5:1),
 *     and the primary buttons use that fill;
 *  4. a rule that sets the Outfit display font only asks for a weight that is
 *     loaded (700 or 900), so nothing is synthesised or silently swapped.
 */
import { describe, it, expect } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { WWW_DIR } from './helpers/js-source.js';

const CSS_DIR = join(WWW_DIR, 'css');
const JS_DIR = join(WWW_DIR, 'js');

/** Custom properties that only ever get their value from JavaScript. */
const JS_SET = new Set([
    '--row', // dashboard.js / player-reveal.js: row index for staggered motion
    '--len', // dashboard.js: digit count of the reel
    '--guess-axis-year', // dashboard.js: position on the guess axis
    '--dotaxis-extra-rows', // player-reveal.js: extra rows of the dot axis
    '--ta-vote-progress', // player-reveal.js: Title & Artist vote bar
]);

const stripComments = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '');

function cssSources() {
    return readdirSync(CSS_DIR)
        .filter((f) => f.endsWith('.css') && !f.endsWith('.min.css'))
        .map((f) => ({ name: `css/${f}`, text: stripComments(readFileSync(join(CSS_DIR, f), 'utf8')) }));
}

function htmlPages() {
    return readdirSync(WWW_DIR)
        .filter((f) => f.endsWith('.html'))
        .map((f) => ({ name: f, text: readFileSync(join(WWW_DIR, f), 'utf8') }));
}

/** CSS that a page carries itself: `<style>` blocks and `style="…"` attributes. */
function inlineCss(html) {
    const blocks = [...html.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)].map((m) => m[1]);
    const attrs = [...html.matchAll(/\sstyle="([^"]*)"/g)].map((m) => m[1]);
    return stripComments([...blocks, ...attrs].join('\n'));
}

function jsSources(dir = JS_DIR, out = []) {
    for (const f of readdirSync(dir)) {
        const p = join(dir, f);
        if (statSync(p).isDirectory()) {
            if (f !== '__tests__' && f !== 'vendor') jsSources(p, out);
        } else if (f.endsWith('.js') && !f.endsWith('.min.js')) {
            out.push({ name: relative(WWW_DIR, p), text: readFileSync(p, 'utf8') });
        }
    }
    return out;
}

const definedIn = (text) => new Set([...text.matchAll(/(--[\w-]+)\s*:/g)].map((m) => m[1]));
const usedIn = (text) => [...text.matchAll(/var\(\s*(--[\w-]+)/g)].map((m) => m[1]);

/** The :root block of tokens.css as { name: raw value }. */
function tokens() {
    const css = stripComments(readFileSync(join(CSS_DIR, 'tokens.css'), 'utf8'));
    const root = css.match(/:root\s*\{([\s\S]*?)\}/);
    const out = {};
    for (const m of root[1].matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) out[m[1]] = m[2].trim();
    return out;
}

function luminance(hex) {
    const n = hex.replace('#', '');
    const full = n.length === 3 ? [...n].map((c) => c + c).join('') : n;
    const [r, g, b] = [0, 2, 4].map((i) => parseInt(full.slice(i, i + 2), 16) / 255);
    const lin = (c) => (c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4);
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}
function contrast(a, b) {
    const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
    return (hi + 0.05) / (lo + 0.05);
}

describe('#3387 every var() is defined', () => {
    const css = cssSources();
    const pages = htmlPages();
    const js = jsSources();
    const defined = new Set();
    for (const s of css) definedIn(s.text).forEach((d) => defined.add(d));
    for (const p of pages) definedIn(inlineCss(p.text)).forEach((d) => defined.add(d));

    it('finds the token file and a meaningful number of definitions', () => {
        // Guards the guard: a wrong path would make the checks below vacuous.
        expect(css.map((s) => s.name)).toContain('css/tokens.css');
        expect(defined.size).toBeGreaterThan(100);
    });

    it('has no var() pointing at an undefined name', () => {
        const missing = [];
        const sources = [
            ...css,
            ...pages.map((p) => ({ name: p.name, text: inlineCss(p.text) })),
            ...js,
        ];
        for (const s of sources) {
            for (const name of usedIn(s.text)) {
                if (!defined.has(name) && !JS_SET.has(name)) missing.push(`${s.name}: ${name}`);
            }
        }
        expect([...new Set(missing)]).toEqual([]);
    });

    it('keeps the JS allowlist honest: each name is really set by JS and used by CSS', () => {
        const allJs = js.map((s) => s.text).join('\n');
        const allCss = css.map((s) => s.text).join('\n');
        for (const name of JS_SET) {
            expect(allJs, name).toContain(name);
            expect(allCss, name).toContain(`var(${name}`);
            expect(defined.has(name), `${name} is defined in CSS now, drop it from JS_SET`).toBe(false);
        }
    });
});

describe('#3387 one shared tokens.css', () => {
    it('is the only file with a :root palette', () => {
        const offenders = [];
        for (const s of cssSources()) {
            if (s.name !== 'css/tokens.css' && /:root\s*\{[^}]*--color-/.test(s.text)) offenders.push(s.name);
        }
        for (const p of htmlPages()) {
            if (/:root\s*\{[^}]*--/.test(inlineCss(p.text))) offenders.push(p.name);
        }
        expect(offenders).toEqual([]);
    });

    it('is bundled into styles.css and linked by the pages that do not load it', () => {
        expect(readFileSync(join(CSS_DIR, 'styles.css'), 'utf8')).toMatch(/@import\s+["']\.\/tokens\.css["']/);
        for (const page of htmlPages()) {
            if (page.text.includes('styles.min.css')) continue;
            expect(page.text, page.name).toContain('/beatify/static/css/tokens.min.css');
        }
    });

    it('is precached for the offline page', () => {
        const sw = readFileSync(join(WWW_DIR, 'sw.js'), 'utf8');
        expect(sw).toContain("'/beatify/static/css/tokens.min.css'");
    });

    it('defines --color-text-primary exactly once', () => {
        const hits = [];
        for (const s of cssSources()) if (/--color-text-primary\s*:/.test(s.text)) hits.push(s.name);
        for (const p of htmlPages()) if (/--color-text-primary\s*:/.test(inlineCss(p.text))) hits.push(p.name);
        expect(hits).toEqual(['css/tokens.css']);
    });
});

describe('#3387 primary button contrast', () => {
    const t = tokens();
    const white = t['--color-text-white'];
    const fill = t['--color-accent-primary-fill'];

    it('white on the fill reaches 4.5:1, white on the glow pink does not', () => {
        expect(fill).toMatch(/^#[0-9a-f]{6}$/i);
        expect(contrast(white, fill)).toBeGreaterThanOrEqual(4.5);
        // The glow keeps #ff2d6a. If this ever passes, the fill token is moot.
        expect(contrast(white, t['--color-accent-primary'])).toBeLessThan(4.5);
    });

    const PRIMARY = [
        ['css/styles.css', '.btn-primary'],
        ['css/styles.css', '.btn-neon'],
        ['css/styles.css', 'body.theme-dark .join-btn'],
        ['css/styles.css', 'body.theme-dark .submit-btn'],
        ['css/styles.css', '.submit-arc'],
        ['css/styles.css', '.btn-tour-next'],
        ['css/styles.css', '.plh-btn-primary'],
        ['css/styles.css', '.plh-cta-start'],
        ['css/styles.css', '#reveal-view .next-round-btn'],
        ['css/dashboard.css', '.leaderboard-entry.is-top-1 .entry-rank'],
    ];
    it.each(PRIMARY)('%s %s sits on the fill token', (file, selector) => {
        const css = stripComments(readFileSync(join(WWW_DIR, file), 'utf8'));
        const esc = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        const bodies = [...css.matchAll(new RegExp(`(?:^|\\n|\\})\\s*${esc}\\s*\\{([^}]*)\\}`, 'g'))]
            .map((m) => m[1])
            .filter((b) => /background\s*:/.test(b));
        expect(bodies.length, selector).toBeGreaterThan(0);
        for (const b of bodies) expect(b).toMatch(/background\s*:\s*var\(--color-accent-primary-fill\)/);
    });
});

describe('#3387 fonts', () => {
    it('body text is the system stack', () => {
        expect(tokens()['--font-body']).toBe('var(--font-system)');
        for (const s of cssSources()) expect(s.text, s.name).not.toMatch(/['"]Inter['"]/);
        for (const p of htmlPages()) {
            expect(inlineCss(p.text), p.name).not.toMatch(/['"]Inter['"]/);
            expect(p.text, p.name).not.toContain('family=Inter');
        }
    });

    it('a rule with the Outfit display font only asks for a loaded weight', () => {
        const loaded = new Set(['700', '900', 'bold', 'var(--font-weight-bold)', 'inherit']);
        const offenders = [];
        const sources = [...cssSources(), ...htmlPages().map((p) => ({ name: p.name, text: inlineCss(p.text) }))];
        for (const s of sources) {
            for (const m of s.text.matchAll(/([^{}]*)\{([^{}]*)\}/g)) {
                const body = m[2];
                if (!/font-family\s*:\s*(var\(--font-display\)|['"]Outfit['"])/.test(body)) continue;
                for (const w of body.matchAll(/font-weight\s*:\s*([^;!}]+)/g)) {
                    if (!loaded.has(w[1].trim())) offenders.push(`${s.name}: ${m[1].trim()} → ${w[1].trim()}`);
                }
            }
        }
        expect(offenders).toEqual([]);
    });

    it('the pages load exactly Outfit 700 and 900', () => {
        for (const p of htmlPages()) {
            for (const m of p.text.matchAll(/family=Outfit:wght@([\d;]+)/g)) expect(m[1], p.name).toBe('700;900');
        }
    });
});
