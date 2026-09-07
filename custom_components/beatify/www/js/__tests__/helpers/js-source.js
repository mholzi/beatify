/**
 * Run a piece of the SHIPPED frontend source, instead of asserting on its text.
 *
 * Why this exists (#2701): a handful of suites had grown into `expect(src)
 * .toContain('...')` greps. Such a test fails on a harmless rename and passes
 * while the behaviour it is named after is broken — the two costs #2701
 * describes. But the code they cover is genuinely hard to import: `dashboard.js`
 * is a DOM-coupled IIFE with no exports, and several admin/player helpers are
 * module-private. vitest runs in the `node` environment here with no jsdom, and
 * the repo's convention is to hand-roll the little DOM a test needs rather than
 * take on a dependency.
 *
 * So: cut the declaration out of the file on disk, compile it with `new
 * Function`, and hand it stubs for everything it closes over. The bytes under
 * test are the bytes that ship — a rename inside the function is invisible to
 * the test, and a behavioural regression fails it.
 *
 * Everything is compiled in strict mode, which is what the browser does too:
 * `dashboard.js` opens with `'use strict'` and the ES modules are strict by
 * definition. That matters for more than tidiness — reading an undeclared
 * identifier throws a ReferenceError under strict mode, which is exactly the
 * defect #2617 shipped.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const HERE = dirname(fileURLToPath(import.meta.url));
/** `custom_components/beatify/www/js` */
export const JS_DIR = join(HERE, '..', '..');
/** `custom_components/beatify/www` */
export const WWW_DIR = join(JS_DIR, '..');
/** repository root */
export const REPO_DIR = join(WWW_DIR, '..', '..', '..');

/** Read a frontend source file, path relative to `www/js`. */
export function readSource(relPath) {
    return readFileSync(join(JS_DIR, relPath), 'utf8');
}

/** Read a JSON locale file, e.g. `locale('de')`. */
export function locale(lang) {
    return JSON.parse(readFileSync(join(WWW_DIR, 'i18n', `${lang}.json`), 'utf8'));
}

/**
 * Slice out the balanced `{ … }` that starts at or after `from`.
 * Returns the source from `from` up to and including the closing brace.
 */
function balanced(src, from) {
    let i = src.indexOf('{', from);
    if (i === -1) throw new Error('no opening brace after offset ' + from);
    let depth = 0;
    for (; i < src.length; i++) {
        const c = src[i];
        if (c === '{') depth++;
        else if (c === '}' && --depth === 0) return src.slice(from, i + 1);
    }
    throw new Error('unbalanced braces from offset ' + from);
}

/**
 * Cut one top-level declaration out of a source file, verbatim.
 *
 * Accepts the shapes the frontend actually uses: a bare `function f()`, an
 * `export function f()`, either of those indented four spaces inside the
 * dashboard IIFE, and `var NAME = {` / `const NAME = {` for the lookup tables.
 *
 * Throws — loudly, naming the file — when the declaration is gone. That is the
 * one thing a source guard did well and this keeps: a test whose subject has
 * been deleted must fail rather than silently cover nothing.
 */
export function declaration(src, name, label = 'the source') {
    for (const head of [
        `\nfunction ${name}(`,
        `\nexport function ${name}(`,
        `\n    function ${name}(`,
        `\nvar ${name} = {`,
        `\n    var ${name} = {`,
        `\nexport var ${name} = {`,
        `\nconst ${name} = {`,
        `\n    const ${name} = {`,
    ]) {
        const at = src.indexOf(head);
        if (at === -1) continue;
        // +1 skips the newline the head is anchored on.
        return balanced(src, at + 1).replace(/^export\s+/, '');
    }
    throw new Error(`${label} no longer declares ${name}`);
}

/**
 * Cut out a statement that begins with `header` (an `if (…) {` line, say),
 * balanced braces included. Used where the interesting code is one branch of a
 * long dispatcher that would need thirty stubs to reach.
 */
export function block(src, header, label = 'the source') {
    const at = src.indexOf(header);
    if (at === -1) throw new Error(`${label} no longer contains \`${header}\``);
    return balanced(src, at);
}

/**
 * Compile extracted snippets and evaluate `returnExpr` against `scope`.
 *
 * `scope` becomes the free variables of the snippet — the closure the browser
 * would have provided. Anything the snippet touches and `scope` does not name
 * throws a ReferenceError, which is a feature, not a limitation.
 */
export function evaluate(snippets, returnExpr, scope = {}) {
    const names = Object.keys(scope);
    const body = `'use strict';\n${[].concat(snippets).join('\n')}\nreturn (${returnExpr});`;
    return new Function(...names, body)(...names.map((n) => scope[n]));
}
