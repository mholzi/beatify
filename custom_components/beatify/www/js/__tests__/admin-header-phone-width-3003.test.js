/**
 * #3003: at 390px the admin header ran 19px off the screen — the 72px
 * wordmark (245px wide) plus three 44px actions did not fit, the reset button
 * was clipped and the page scrolled sideways.
 *
 * Below 420px the wordmark now scales with the viewport and the gap tightens;
 * the header may wrap, so anything extra (the "Finish setup" pill) moves to a
 * second line instead of off the screen. Measured in Chrome on the built
 * stylesheet: 390px → wordmark 186px, reset button ends at 382; 360px →
 * wordmark 172px, reset ends at 352; scrollWidth equals innerWidth at both.
 *
 * vitest has no layout engine, so this pins the rules that produce that
 * result in the source and the shipped .min.css, and re-does the width budget
 * with the numbers measured above.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { WWW_DIR } from './helpers/js-source.js';

const CSS = readFileSync(join(WWW_DIR, 'css', 'styles.css'), 'utf8');
const MIN = readFileSync(join(WWW_DIR, 'css', 'styles.min.css'), 'utf8');

function stripComments(src) {
    return src.replace(/\/\*[\s\S]*?\*\//g, '');
}

/** Body of the first `@media (max-width: 420px)` block that styles the admin header. */
function phoneBlock(src) {
    const clean = stripComments(src);
    const re = /@media\s*\(max-width:\s*420px\)\s*\{/g;
    let m;
    while ((m = re.exec(clean))) {
        let depth = 1;
        let i = re.lastIndex;
        for (; i < clean.length && depth; i++) {
            if (clean[i] === '{') depth++;
            else if (clean[i] === '}') depth--;
        }
        const body = clean.slice(re.lastIndex, i - 1);
        if (body.includes('.admin-header')) return body;
    }
    return null;
}

describe('#3003 admin header fits a phone', () => {
    it.each([['styles.css', CSS], ['styles.min.css', MIN]])('%s scales the wordmark below 420px', (_, src) => {
        const block = phoneBlock(src);
        expect(block).not.toBeNull();
        expect(block.replace(/\s+/g, '')).toContain('.admin-header.wordmark{font-size:clamp(2.5rem,14vw,var(--font-size-hero))');
    });

    it.each([['styles.css', CSS], ['styles.min.css', MIN]])('%s lets the header wrap instead of overflowing', (_, src) => {
        const flat = stripComments(src).replace(/\s+/g, '');
        const header = flat.match(/\.admin-header\{([^}]*)\}/)[1];
        expect(header).toContain('flex-wrap:wrap');
        const actions = flat.match(/\.admin-header-actions\{([^}]*)\}/)[1];
        expect(actions).toContain('margin-left:auto');
    });

    it.each([360, 390])('the width budget holds at %ipx', (vw) => {
        // Outfit 900 "Beatify" is 245px wide at 72px (measured) → 3.4px per px.
        const wordmark = Math.min(72, Math.max(40, 0.14 * vw)) * (245 / 72);
        const actions = 3 * 44 + 2 * 8; // 📲 📊 ⟲, 8px apart
        const gap = 8;
        const bodyMargin = 2 * 8;
        expect(wordmark + gap + actions).toBeLessThanOrEqual(vw - bodyMargin);
    });
});
