/**
 * #3122 — the admin page's "Start Round" button for an intro round could not
 * be clicked.
 *
 * `#admin-intro-splash` carried the class `intro-splash`, the two-second flash
 * the phones use: it fades out 1.5 s after it appears and sets
 * `pointer-events: none`. A host running the game from the admin page saw the
 * box blink and had no way to confirm the round, so phones and TV waited for
 * the host forever (reported in #3027).
 *
 * The suite pins the shipped markup and the shipped stylesheet: the box that
 * holds the confirm button must not use a class that fades out or swallows
 * clicks, and it must not be hidden from assistive tech while it is shown.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const WWW = join(__dirname, '..', '..');
const HTML = readFileSync(join(WWW, 'admin.html'), 'utf8');
const CSS = readFileSync(join(WWW, 'css', 'styles.css'), 'utf8');
const ADMIN_JS = readFileSync(join(WWW, 'js', 'admin.js'), 'utf8');

/** The opening tag of the element with the given id. */
function openingTag(id) {
    const match = HTML.match(new RegExp(`<[a-z]+[^>]*\\bid="${id}"[^>]*>`));
    expect(match, `#${id} missing from admin.html`).not.toBeNull();
    return match[0];
}

/** Class names on the element with the given id. */
function classesOf(id) {
    const match = openingTag(id).match(/\bclass="([^"]*)"/);
    return match ? match[1].split(/\s+/).filter(Boolean) : [];
}

/** Declarations of every top-level rule whose selector is exactly `.name`. */
function rulesFor(name) {
    const re = new RegExp(`^\\.${name}\\s*\\{([^}]*)\\}`, 'gm');
    return [...CSS.matchAll(re)].map((m) => m[1]);
}

describe('#3122 admin intro splash — shipped markup', () => {
    it('keeps the confirm button inside #admin-intro-splash', () => {
        const start = HTML.indexOf('id="admin-intro-splash"');
        const button = HTML.indexOf('id="admin-confirm-intro"');
        expect(start).toBeGreaterThan(-1);
        expect(button).toBeGreaterThan(start);
        expect(button - start).toBeLessThan(1200);
    });

    it('does not style the box with the self-dismissing phone flash', () => {
        expect(classesOf('admin-intro-splash')).not.toContain('intro-splash');
    });

    it('starts hidden and is not permanently aria-hidden', () => {
        expect(classesOf('admin-intro-splash')).toContain('hidden');
        expect(openingTag('admin-intro-splash')).not.toMatch(/aria-hidden="true"/);
    });
});

describe('#3122 admin intro splash — shipped styles', () => {
    it('proves the guard: .intro-splash fades out and ignores clicks', () => {
        const flash = rulesFor('intro-splash').join('\n');
        expect(flash).toMatch(/pointer-events:\s*none/);
        expect(flash).toMatch(/intro-splash-out/);
    });

    it('gives every class on the box a rule that stays and takes clicks', () => {
        const classes = classesOf('admin-intro-splash').filter((c) => c !== 'hidden');
        expect(classes).toContain('admin-intro-splash');
        for (const name of classes) {
            const rules = rulesFor(name);
            expect(rules.length, `.${name} has no rule in styles.css`).toBeGreaterThan(0);
            const css = rules.join('\n');
            expect(css).not.toMatch(/pointer-events:\s*none/);
            expect(css).not.toMatch(/intro-splash-out/);
        }
    });
});

describe('#3122 admin intro splash — wiring', () => {
    it('shows the box from intro_splash_pending and sends the confirm action', () => {
        expect(ADMIN_JS).toMatch(
            /getElementById\('admin-intro-splash'\)[\s\S]{0,120}toggle\('hidden', !data\.intro_splash_pending\)/
        );
        expect(ADMIN_JS).toMatch(
            /getElementById\('admin-confirm-intro'\)[\s\S]{0,160}action: 'confirm_intro_splash'/
        );
    });
});
