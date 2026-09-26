/**
 * #2974: the reveal's "Your collection" card read "1988Here I AmDominoe".
 *
 * `renderCollection` always wrote year, title and artist into three spans;
 * the stylesheet stacks them (the card is a flex column). But those rules sat
 * after a `@media (prefers-reduced-motion: reduce) {` in styles.css whose
 * closing brace is missing, so they only applied on phones that ask for
 * reduced motion. Everywhere else the card was a plain block and the three
 * inline spans ran together. The rules now stand above that query.
 *
 * Checked twice: the markup keeps the three fields in their own elements, and
 * the rules that lay them out are at the top level of the stylesheet — not
 * inside any @media or other block — in the source and the shipped .min.css.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { declaration, evaluate, readSource, WWW_DIR } from './helpers/js-source.js';

const CSS = readFileSync(join(WWW_DIR, 'css', 'styles.css'), 'utf8');
const MIN = readFileSync(join(WWW_DIR, 'css', 'styles.min.css'), 'utf8');

/** Brace depth at which each `selector {` opens, comments and strings stripped. */
function depthOf(src, selector) {
    const clean = src.replace(/\/\*[\s\S]*?\*\//g, (c) => c.replace(/[^\n]/g, ' '));
    const at = clean.indexOf(`${selector} {`);
    if (at === -1) throw new Error(`${selector} not found`);
    let depth = 0;
    for (let i = 0; i < at; i++) {
        if (clean[i] === '{') depth++;
        else if (clean[i] === '}') depth--;
    }
    return depth;
}

function minDepthOf(src, selector) {
    const at = src.indexOf(`${selector}{`);
    if (at === -1) throw new Error(`${selector} not found in .min.css`);
    let depth = 0;
    for (let i = 0; i < at; i++) {
        if (src[i] === '{') depth++;
        else if (src[i] === '}') depth--;
    }
    return depth;
}

describe('#2974 the collection card keeps year, title and artist apart', () => {
    it('renders the three fields as three separate elements, in order', () => {
        const row = { innerHTML: '', textContent: '', querySelector: () => null };
        const section = { classList: { add() {}, remove() {} } };
        const document = {
            getElementById: (id) => ({ 'collection-section': section, 'collection-row': row })[id] || null,
        };
        const render = evaluate(declaration(readSource('player-reveal.js'), 'renderCollection', 'player-reveal.js'), 'renderCollection', {
            document,
            escapeHtml: (s) => String(s),
            utils: { t: () => '' },
            prefersReducedMotion: () => true,
        });
        render({ collection: [{ year: 1988, title: 'Here I Am', artist: 'Dominoe', round: 3 }] });
        const spans = [...row.innerHTML.matchAll(/<span class="collection-card-(year|title|artist)">([^<]*)<\/span>/g)]
            .map((m) => [m[1], m[2]]);
        expect(spans).toEqual([['year', '1988'], ['title', 'Here I Am'], ['artist', 'Dominoe']]);
    });

    it('stacks them: the card is a flex column', () => {
        const card = CSS.slice(CSS.indexOf('\n.collection-card {'), CSS.indexOf('}', CSS.indexOf('\n.collection-card {')));
        expect(card).toMatch(/display: flex;/);
        expect(card).toMatch(/flex-direction: column;/);
    });

    for (const sel of ['.collection-row', '.collection-card', '.collection-card-year', '.collection-card-title', '.collection-card-artist']) {
        it(`${sel} applies on every phone, not only with reduced motion`, () => {
            expect(depthOf(CSS, `\n${sel}`)).toBe(0);
            expect(minDepthOf(MIN, sel)).toBe(0);
        });
    }

    it('uses the dark reveal surface, so its white text stays readable', () => {
        const card = CSS.slice(CSS.indexOf('\n.collection-card {'), CSS.indexOf('}', CSS.indexOf('\n.collection-card {')));
        expect(card).not.toMatch(/--color-bg-white/);
        expect(card).toMatch(/background: var\(--color-dark-surface/);
    });
});
