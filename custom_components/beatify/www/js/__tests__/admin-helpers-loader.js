/**
 * Smoke-test loader for admin.js pure helpers (#1279, Schritt 1/6).
 *
 * admin.js is a CLASSIC GLOBAL SCRIPT — no `export`s, no `import`s, and a pile
 * of top-level side effects (document.addEventListener, IIFEs, serviceWorker
 * registration). It cannot be `import`ed, and evaluating the whole file would
 * require stubbing its entire browser surface.
 *
 * Decomposition step 1 must NOT touch production code, so instead of adding
 * exports we extract the SOURCE TEXT of the individual pure helpers straight
 * out of admin.js at test time (brace-matched) and eval only those snippets in
 * a controlled scope. The tests therefore run the EXACT production source and
 * stay in sync automatically — if someone edits `escapeHtml` in admin.js, the
 * extracted text (and the test) changes with it.
 *
 * When step 2 turns these helpers into a real ESM `admin/util.js`, this loader
 * is deleted and the tests switch to a plain `import`.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ADMIN_JS = join(__dirname, '..', 'admin.js');

let _src = null;
function adminSource() {
    if (_src === null) _src = readFileSync(ADMIN_JS, 'utf8');
    return _src;
}

/**
 * Extract a top-level `function NAME(...) { ... }` declaration's full source
 * text by matching braces from its opening `{`. Throws if the name is absent
 * (so a renamed/removed helper fails loudly instead of silently testing stale
 * inlined copies).
 */
export function extractFunction(name) {
    const src = adminSource();
    const re = new RegExp(`(?:^|\\n)((?:async\\s+)?function\\s+${name}\\s*\\()`);
    const m = re.exec(src);
    if (!m) throw new Error(`admin.js: function ${name} not found`);
    const start = m.index + (m[0].startsWith('\n') ? 1 : 0);
    // find the first '{' after the signature
    let i = src.indexOf('{', m.index + m[0].length - 1);
    if (i === -1) throw new Error(`admin.js: no body for ${name}`);
    const end = matchBrace(src, i);
    return src.slice(start, end + 1);
}

/**
 * Extract a top-level `const NAME = { ... };` object literal source text.
 */
export function extractConst(name) {
    const src = adminSource();
    const re = new RegExp(`(?:^|\\n)(const\\s+${name}\\s*=\\s*)`);
    const m = re.exec(src);
    if (!m) throw new Error(`admin.js: const ${name} not found`);
    const start = m.index + (m[0].startsWith('\n') ? 1 : 0);
    let i = src.indexOf('{', m.index + m[0].length - 1);
    if (i === -1) throw new Error(`admin.js: no object body for ${name}`);
    const end = matchBrace(src, i);
    return src.slice(start, end + 1) + ';';
}

// Brace matcher that skips string/template/comment content so braces inside
// HTML-template literals (buildRequestRowHtml) don't throw off the count.
function matchBrace(src, openIdx) {
    let depth = 0;
    let i = openIdx;
    let mode = 'code'; // code | sq | dq | tpl | line | block
    while (i < src.length) {
        const c = src[i];
        const n = src[i + 1];
        if (mode === 'code') {
            if (c === '/' && n === '/') { mode = 'line'; i += 2; continue; }
            if (c === '/' && n === '*') { mode = 'block'; i += 2; continue; }
            if (c === "'") { mode = 'sq'; i++; continue; }
            if (c === '"') { mode = 'dq'; i++; continue; }
            if (c === '`') { mode = 'tpl'; i++; continue; }
            if (c === '{') depth++;
            else if (c === '}') { depth--; if (depth === 0) return i; }
        } else if (mode === 'line') {
            if (c === '\n') mode = 'code';
        } else if (mode === 'block') {
            if (c === '*' && n === '/') { mode = 'code'; i += 2; continue; }
        } else if (mode === 'sq') {
            if (c === '\\') { i += 2; continue; }
            if (c === "'") mode = 'code';
        } else if (mode === 'dq') {
            if (c === '\\') { i += 2; continue; }
            if (c === '"') mode = 'code';
        } else if (mode === 'tpl') {
            if (c === '\\') { i += 2; continue; }
            if (c === '`') mode = 'code';
            // NOTE: nested ${ } interpolation braces are intentionally ignored
            // for these helpers (none nest an unbalanced object literal inside).
        }
        i++;
    }
    throw new Error('admin.js: unbalanced braces while extracting helper');
}

/**
 * Compile a set of extracted declarations into a single live scope and return
 * the requested names. `globals` is injected as in-scope variables (e.g.
 * currentGame, localStorage, document, REQUEST_STATUS_LABELS) so the helpers
 * resolve their free references against test stubs instead of real browser
 * globals.
 */
export function loadHelpers({ functions = [], consts = [], globals = {}, expose }) {
    const decls = [
        ...consts.map(extractConst),
        ...functions.map(extractFunction),
    ].join('\n\n');
    const exposeNames = expose || functions;
    const globalKeys = Object.keys(globals);
    const body = `
        ${decls}
        return { ${exposeNames.join(', ')} };
    `;
    // eslint-disable-next-line no-new-func
    const factory = new Function(...globalKeys, body);
    return factory(...globalKeys.map((k) => globals[k]));
}
