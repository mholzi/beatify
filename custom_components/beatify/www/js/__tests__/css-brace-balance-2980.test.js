/**
 * #2980: every CSS source must close every block it opens.
 *
 * styles.css went for months with an `@media (prefers-reduced-motion: reduce)`
 * block and the `.end-action-hint` rule left open. Nothing failed: browsers
 * (and esbuild's minifier) accept the unclosed block and quietly nest every
 * later rule inside it, so ~70 rules — Sudden Death, the comeback overlay,
 * the end-round picker, Encore, the ghost league, sit-out/re-admit — applied
 * only with "reduce motion" switched on, or not at all.
 *
 * This counts braces in each readable source after removing comments and
 * string literals (a `{` inside `content: "{"` or a comment is not a block).
 * Depth must never go below zero and must end at zero. On failure it names the
 * line of every block still open, which is where the missing `}` belongs.
 */
import { describe, it, expect } from 'vitest';
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { WWW_DIR } from './helpers/js-source.js';

const CSS_DIR = join(WWW_DIR, 'css');
const SOURCES = readdirSync(CSS_DIR).filter((f) => f.endsWith('.css') && !f.endsWith('.min.css'));

/** Replace comments and strings with spaces, keeping newlines for line numbers. */
function stripCommentsAndStrings(css) {
    let out = '';
    let i = 0;
    const blank = (s) => s.replace(/[^\n]/g, ' ');
    while (i < css.length) {
        if (css.startsWith('/*', i)) {
            const end = css.indexOf('*/', i + 2);
            const stop = end === -1 ? css.length : end + 2;
            out += blank(css.slice(i, stop));
            i = stop;
        } else if (css[i] === '"' || css[i] === "'") {
            const q = css[i];
            let j = i + 1;
            while (j < css.length && css[j] !== q && css[j] !== '\n') {
                if (css[j] === '\\') j++;
                j++;
            }
            out += blank(css.slice(i, j + 1));
            i = j + 1;
        } else {
            out += css[i];
            i++;
        }
    }
    return out;
}

/** Returns { stray: [lines of `}` with nothing open], open: [lines of unclosed `{`] }. */
function braceReport(css) {
    const text = stripCommentsAndStrings(css);
    const open = [];
    const stray = [];
    let line = 1;
    for (const c of text) {
        if (c === '\n') line++;
        else if (c === '{') open.push(line);
        else if (c === '}') {
            if (open.length) open.pop();
            else stray.push(line);
        }
    }
    return { stray, open };
}

describe('the brace counter itself (#2980)', () => {
    it('ignores braces in comments and strings', () => {
        expect(braceReport('/* { */ a { content: "{"; b: \'}\' }')).toEqual({ stray: [], open: [] });
    });
    it('reports the line of a block left open', () => {
        expect(braceReport('a { x: 1; }\n@media (x) {\n  b { y: 2; }\nc { z: 3; }\n').open).toEqual([2]);
    });
    it('reports a stray closing brace', () => {
        expect(braceReport('a { }\n}\n').stray).toEqual([2]);
    });
});

describe('CSS sources close every block they open (#2980)', () => {
    it('finds the readable sources', () => {
        expect(SOURCES).toContain('styles.css');
        expect(SOURCES).toContain('dashboard.css');
    });

    it.each(SOURCES)('%s is balanced', (file) => {
        const report = braceReport(readFileSync(join(CSS_DIR, file), 'utf8'));
        expect(report, `${file}: unclosed blocks open at lines ${report.open.join(', ')}; stray } at ${report.stray.join(', ')}`)
            .toEqual({ stray: [], open: [] });
    });
});
