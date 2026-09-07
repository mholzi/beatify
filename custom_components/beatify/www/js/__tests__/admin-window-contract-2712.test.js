/**
 * #2712 — the `window` handshakes around admin.js are a contract, and this file
 * is the only thing holding both ends of it together.
 *
 * #2637 killed the direction where a module under `admin/` reached back into
 * admin.js, and `admin-section-independence-2637.test.js` watches it. #2680
 * (landed with #2749) pulled wizard.js and playlist-hub.js into the admin bundle
 * so they stopped being separate downloads. Neither change touched the thing
 * that actually breaks: nothing anywhere asserts that the file assigning a name
 * on `window` and the file reading it back still agree on that name.
 *
 * They cannot agree by accident, because a mismatch is silent. Every read is
 * written `typeof window.x === 'function'`, `window.x?.()` or
 * `globalThis.x?.y?.()`, so a name dropped or renamed on the publishing side
 * does not throw — the wizard just finishes without refreshing the home view,
 * and no test, no log line and no user report says so. That is not
 * hypothetical: `window.loadPlaylists` (#2679) was guarded that way, was never
 * assigned by anything in www/, and stayed dead for months until #2749.
 *
 * WHY THIS IS DERIVED AND NOT A LIST SOMEONE MAINTAINS
 *
 * There already was a list — the block comment at the top of admin.js, which
 * announced itself as the whole list. It has been accurate and inaccurate by
 * turns, and nothing ever told anyone which. Its claim that "nothing under
 * ./admin/ reads any of the six" is false as of this commit: mix.js reads
 * BeatifyHome and media-players.js reads BeatifyPersistSetup. Both say
 * `globalThis.` rather than `window.`, which is the only reason #2637's
 * sentinel — a Proxy around `window` — does not see them.
 *
 * So both ends are read off the real artifacts on every run:
 *   - which scripts a page loads          → the `<script src>` list in the HTML
 *   - which files an entry point becomes  → esbuild's metafile
 *   - what each file publishes and reads  → an acorn parse, not a regex
 *
 * The parse is not a nicety. admin/sections/mix.js carries two comments
 * mentioning `window.loadStatus` to explain why it no longer reads it; a text
 * scan counts those as reads and the check quietly stops meaning anything.
 *
 * WHAT FAILS THIS FILE
 *   1. a handshake inside a bundle appears, moves or loses an end  → HANDSHAKES
 *   2. a handshake between entry points does the same              → CROSSINGS
 *   3. a page reads a project global nothing on that page publishes
 *   4. a project global is published that nothing anywhere reads
 */
import { describe, it, expect, beforeAll } from 'vitest';
import { parse } from 'acorn';
import { build } from 'esbuild';
import { readFile, readdir } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { dirname, join, relative, resolve } from 'node:path';

import { BUNDLES } from '../../../../../scripts/build.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const JS_DIR = resolve(HERE, '..');
const WWW_DIR = resolve(JS_DIR, '..');
const REPO_ROOT = resolve(WWW_DIR, '..', '..', '..');

// ---------------------------------------------------------------------------
// The contract
// ---------------------------------------------------------------------------

/**
 * Handshakes between two files that ship inside the SAME bundle.
 *
 * Format: `<bundle>  <name>: <publishers> -> <readers>`.
 *
 * This is where the nine names of #2712 live now. Since #2680 they are no
 * longer a boundary between downloads — every file listed here is inlined into
 * one artifact by esbuild — so `window` buys exactly one thing: it breaks an
 * import cycle. The verdict on each group is the point of the grouping, because
 * a pin that makes a bad shape permanent is worse than no pin.
 */
const HANDSHAKES = [
    // --- CYCLE-BREAKER. Keep, for now; the cycle is real. -------------------
    // admin.js imports wizard.js, so wizard.js cannot import admin.js back.
    // `window` is the classic way out and there is no cheap alternative that
    // does not mean moving loadStatus/loadSavedSettings/BeatifyHome into a
    // third module that both sides import. That refactor is worth doing and is
    // not this PR; until then these five are pinned here, which is the part
    // that was missing.
    'admin.min.js  BeatifyHome: admin.js -> admin/sections/mix.js, wizard.js',
    'admin.min.js  BeatifyNoteLocalSetupWrite: admin.js -> wizard.js',
    'admin.min.js  BeatifyPersistSetup: admin.js -> admin/sections/media-players.js, wizard.js',
    'admin.min.js  BeatifyWizard: wizard.js -> admin.js',
    'admin.min.js  loadSavedSettings: admin.js -> wizard.js',
    'admin.min.js  loadStatus: admin.js -> wizard.js',

    // --- SHOULD BE AN IMPORT. No cycle; nobody has had time. ----------------
    // Neither playlist-hub.js nor wizard.js is imported by mix.js,
    // seasonal-suggestion.js or tts-settings.js, so each of these three could
    // be a plain `import` today and esbuild would resolve it at build time —
    // which `npm run build:check` already covers, unlike `window`.
    'admin.min.js  BeatifyMixPanel: admin/sections/mix.js -> playlist-hub.js',
    'admin.min.js  BeatifySeasonal: admin/sections/seasonal-suggestion.js -> playlist-hub.js',
    'admin.min.js  BeatifyTtsPresets: tts-settings.js -> wizard.js',

    // --- SHOULD BE AN IMPORT, and is load-bearing in two bundles. -----------
    // library-fix.js is an input of BOTH admin.min.js and player.bundle.min.js,
    // so this name is never a cross-download contract — publisher and readers
    // are inlined together on both pages. The comment at library-fix.js:256
    // says the reveal screen "has no module access to this one", which stopped
    // being true when player-core.js started importing it. #2712's issue text
    // counted this as one of the nine on the strength of that comment.
    'admin.min.js  BeatifyCrateDiggerFix: admin/sections/library-fix.js -> admin.js, admin/sections/library.js',
    'player.bundle.min.js  BeatifyCrateDiggerFix: admin/sections/library-fix.js -> player-reveal.js',
];

/**
 * Handshakes that really do cross from one downloaded entry point to another.
 *
 * Format: `<page>  <name>: <publishers> -> <readers>`, both sides being the
 * `<script src>` filenames the page loads.
 */
const CROSSINGS = [
    // --- FOLD. The last of admin.min.js's outbound names. -------------------
    // playlist-requests.js and playlist-generator.js are still classic
    // `<script>` tags and title-artist-bonuses.js is still its own module, so
    // these four cannot import. None of the three is loaded by any page other
    // than admin.html, so folding them in the way #2680 folded wizard.js would
    // retire this whole group.
    'admin.html  BEATIFY_VERSION: admin.min.js -> playlist-requests.min.js',
    'admin.html  BeatifyTitleArtist: title-artist-bonuses.js -> admin.min.js',
    'admin.html  PlaylistGenerator: playlist-generator.min.js -> admin.min.js',
    'admin.html  PlaylistRequests: playlist-requests.min.js -> admin.min.js',

    // --- KEEP. Shared libraries, loaded by several pages. -------------------
    // ha-auth.js, i18n.js and utils.js are loaded by admin, player, dashboard
    // and analytics, each of which has its own bundle. Folding them in would
    // put four copies of the i18n dictionary and four independent auth-token
    // caches on the box. `window` is the right channel here and these should
    // still be in this table in a year — what they needed was the pin, not a
    // refactor. `BeatifyUtils` reaching playlist-requests.min.js is exactly as
    // unguarded as `loadStatus` reaching wizard.js.
    'admin.html  BeatifyAuth: ha-auth.js -> admin.min.js, playlist-generator.min.js',
    'admin.html  BeatifyI18n: i18n.js -> admin.min.js, ha-auth.js, playlist-generator.min.js',
    'admin.html  BeatifyUtils: utils.js -> admin.min.js, playlist-requests.min.js',
    'analytics.html  BeatifyI18n: i18n.js -> analytics.min.js',
    'dashboard.html  BeatifyUtils: utils.js -> dashboard.min.js',
    'player.html  BeatifyAuth: ha-auth.js -> player.bundle.min.js',
    'player.html  BeatifyI18n: i18n.min.js -> ha-auth.js, player.bundle.min.js',
    'player.html  BeatifyUtils: utils.min.js -> player.bundle.min.js',
];

/**
 * Globals published on purpose with no reader anywhere in this repo.
 *
 * The dead-write check would otherwise flag them, and it should stay strict: a
 * published name nothing reads is what #2679 was. Both of these are documented
 * at their assignment site as handles for something outside the repo, so they
 * are named here rather than weakening the rule.
 */
const PUBLISHED_FOR_NOBODY_IN_THIS_REPO = {
    BeatifyNotify: 'notify.js — a handle for classic (non-module) callers and for poking at toasts from the devtools console',
    t: 'i18n.js — shorthand alias for BeatifyI18n.t, same reason',
};

// ---------------------------------------------------------------------------
// Reading the tree
// ---------------------------------------------------------------------------

const GLOBAL_OBJECTS = new Set(['window', 'globalThis']);

/** Depth-first over every AST node, handing each one its parent. */
function walk(node, parent, visit) {
    if (!node || typeof node !== 'object') return;
    if (Array.isArray(node)) {
        for (const child of node) walk(child, parent, visit);
        return;
    }
    if (typeof node.type !== 'string') return;
    visit(node, parent);
    for (const key of Object.keys(node)) {
        if (key === 'type' || key === 'start' || key === 'end' || key === 'loc') continue;
        walk(node[key], node, visit);
    }
}

/**
 * The globals one source file writes and the ones it reads.
 *
 * `window.x = …` and `window.x++` are writes; everything else naming a property
 * of `window`/`globalThis` is a read, which covers `window.x()`, `window.x?.()`,
 * `typeof window.x === 'function'` and `globalThis.x?.y?.()`. Both objects
 * count, because both are used for this in www/js and treating only `window` as
 * the channel is precisely how #2637's sentinel misses mix.js:374.
 *
 * Computed access (`window[name]`) is invisible to this and to any other static
 * check; nothing in www/js reaches across a file boundary that way today.
 */
function scanGlobals(source) {
    const ast = parse(source, { ecmaVersion: 'latest', sourceType: 'module' });
    const publishes = new Set();
    const reads = new Set();
    walk(ast, null, (node, parent) => {
        if (node.type !== 'MemberExpression' || node.computed) return;
        if (node.object.type !== 'Identifier' || !GLOBAL_OBJECTS.has(node.object.name)) return;
        if (node.property.type !== 'Identifier') return;
        const written = parent && (
            (parent.type === 'AssignmentExpression' && parent.left === node) ||
            (parent.type === 'UpdateExpression' && parent.argument === node)
        );
        (written ? publishes : reads).add(node.property.name);
    });
    return { publishes, reads };
}

/** Every hand-written source under www/js/ — vendor and tests are not ours. */
async function sourceFiles(dir = JS_DIR, out = []) {
    for (const entry of await readdir(dir, { withFileTypes: true })) {
        const p = join(dir, entry.name);
        if (entry.isDirectory()) {
            if (entry.name !== 'vendor' && entry.name !== '__tests__') await sourceFiles(p, out);
        } else if (entry.name.endsWith('.js') && !entry.name.endsWith('.min.js')) {
            out.push(relative(JS_DIR, p));
        }
    }
    return out.sort();
}

/**
 * The module graph esbuild actually produces for one source file, as www/js
 * paths. Run for every entry point, not just the two bundles: a classic script
 * answers with itself, and a `<script type="module">` answers with everything
 * it imports. That last case is not theoretical — until #2680, wizard.js pulled
 * five modules over the network that admin.min.js had already inlined.
 */
async function moduleGraph(file) {
    const result = await build({
        entryPoints: [join(JS_DIR, file)],
        bundle: true,
        format: 'esm',
        write: false,
        metafile: true,
        logLevel: 'silent',
    });
    return Object.keys(result.metafile.inputs)
        .map((p) => relative(JS_DIR, resolve(REPO_ROOT, p)))
        .sort();
}

const SCRIPT_SRC_RE = /<script[^>]+src="\/beatify\/static\/js\/([^"?]+)/g;
/** `<script src>` name → the source file esbuild should start from. */
const BUNDLE_ENTRY = new Map(BUNDLES.map((b) => [b.out, `${b.entry}.js`]));

let scans;   // www/js path -> { publishes, reads }
let bundles; // bundle artifact name -> [www/js paths]
let pages;   // page -> Map(script src -> { files, publishes, reads })
let projectGlobals;

/** Union the scan of every file behind one entry point. */
function aggregate(files) {
    const publishes = new Set();
    const reads = new Set();
    for (const f of files) {
        const scan = scans.get(f);
        if (!scan) throw new Error(`${f} is in a module graph but not under www/js/`);
        for (const n of scan.publishes) publishes.add(n);
        for (const n of scan.reads) reads.add(n);
    }
    return { files, publishes, reads };
}

beforeAll(async () => {
    scans = new Map();
    for (const file of await sourceFiles()) {
        scans.set(file, scanGlobals(await readFile(join(JS_DIR, file), 'utf8')));
    }

    projectGlobals = new Set();
    for (const { publishes } of scans.values()) {
        for (const name of publishes) projectGlobals.add(name);
    }

    bundles = new Map();
    for (const b of BUNDLES) bundles.set(b.out, await moduleGraph(`${b.entry}.js`));

    pages = new Map();
    const graphs = new Map();
    for (const name of (await readdir(WWW_DIR)).filter((f) => f.endsWith('.html')).sort()) {
        const html = await readFile(join(WWW_DIR, name), 'utf8');
        const entries = new Map();
        for (const [, src] of html.matchAll(SCRIPT_SRC_RE)) {
            if (src.startsWith('vendor/')) continue;
            if (!graphs.has(src)) {
                graphs.set(src, bundles.get(src) || await moduleGraph(BUNDLE_ENTRY.get(src) || src.replace(/\.min\.js$/, '.js')));
            }
            entries.set(src, aggregate(graphs.get(src)));
        }
        pages.set(name, entries);
    }
});

/**
 * Names one file assigns and a DIFFERENT file in the same bundle reads back.
 * A file that publishes a name and reads it again is talking to itself, not
 * handing anything over — admin.js does that with BeatifyHome all day.
 */
function derivedHandshakes() {
    const lines = [];
    for (const [artifact, files] of bundles) {
        const names = new Set();
        for (const f of files) for (const n of scans.get(f).publishes) names.add(n);
        for (const name of [...names].sort()) {
            const from = files.filter((f) => scans.get(f).publishes.has(name));
            const to = files.filter((f) => scans.get(f).reads.has(name) && !scans.get(f).publishes.has(name));
            if (!to.length) continue;
            lines.push(`${artifact}  ${name}: ${from.join(' + ')} -> ${to.join(', ')}`);
        }
    }
    return lines;
}

/** The same, one level up: entry point to entry point, per page. */
function derivedCrossings() {
    const lines = [];
    for (const [page, entries] of pages) {
        const names = new Set();
        for (const { reads } of entries.values()) for (const n of reads) names.add(n);
        for (const name of [...names].sort()) {
            const from = [...entries].filter(([, e]) => e.publishes.has(name)).map(([src]) => src).sort();
            const to = [...entries].filter(([, e]) => e.reads.has(name) && !e.publishes.has(name)).map(([src]) => src).sort();
            if (!from.length || !to.length) continue;
            lines.push(`${page}  ${name}: ${from.join(' + ')} -> ${to.join(', ')}`);
        }
    }
    return lines;
}

// ---------------------------------------------------------------------------

describe('#2712 the window contract around the admin bundle', () => {
    it('reads the pages, bundles and sources it is about to check', () => {
        // Guards the guard: every assertion below compares against a derived
        // set, and a derivation that silently produced nothing would make all
        // of them pass while checking air.
        expect([...pages.keys()]).toContain('admin.html');
        expect([...pages.keys()]).toContain('player.html');
        expect(pages.get('admin.html').size).toBeGreaterThanOrEqual(6);

        // admin.min.js is a bundle, not one file — if this collapses to 1 the
        // metafile lookup broke and every in-bundle handshake disappears.
        expect(bundles.get('admin.min.js').length).toBeGreaterThan(20);
        expect(bundles.get('admin.min.js')).toContain('wizard.js');
        expect(bundles.get('admin.min.js')).toContain('admin/sections/mix.js');

        // The scan itself: a parse that returned nothing would leave every set
        // empty and every check below vacuous.
        expect(scans.size).toBeGreaterThan(30);
        expect(projectGlobals.size).toBeGreaterThan(10);
        expect(scans.get('wizard.js').reads.size).toBeGreaterThan(0);
    });

    it('hands over exactly the globals the in-bundle table declares', () => {
        // Sorted on both sides: the tables are grouped by verdict, because the
        // verdict is the part a reader needs, and the derivation comes out
        // grouped by artifact and name. Order is not the contract.
        expect([...derivedHandshakes()].sort()).toEqual([...HANDSHAKES].sort());
    });

    it('crosses exactly the entry-point boundaries the table declares', () => {
        expect([...derivedCrossings()].sort()).toEqual([...CROSSINGS].sort());
    });

    it('never reads a project global the page does not publish', () => {
        // The failure of #2712 stated directly: wizard.js reads
        // window.loadStatus, so something admin.html loads has to assign it.
        //
        // Browser and vendor globals are not in `projectGlobals` — nothing of
        // ours assigns window.location or window.NoSleep — so they are out of
        // scope here without an allowlist to keep up to date.
        //
        // This rule cannot see a name deleted from EVERY file: with no writer
        // left it is not a project global any more, and the surviving read
        // looks like a read of some browser API. That case belongs to the two
        // tables, and they catch it.
        const dead = [];
        for (const [page, entries] of pages) {
            const published = new Set();
            for (const { publishes } of entries.values()) for (const n of publishes) published.add(n);
            for (const [src, { reads }] of entries) {
                for (const name of reads) {
                    if (!projectGlobals.has(name) || published.has(name)) continue;
                    dead.push(`${page}: ${src} reads window.${name}, which no script on that page publishes`);
                }
            }
        }
        expect(dead.sort()).toEqual([]);
    });

    it('never publishes a project global nothing reads', () => {
        // #2679's shape from the writing end: a name that survived a rename on
        // the reading side keeps being assigned, costs nothing visible, and
        // quietly documents a handshake that no longer happens.
        const readSomewhere = new Set();
        for (const { reads } of scans.values()) for (const n of reads) readSomewhere.add(n);
        const unread = [...projectGlobals]
            .filter((n) => !readSomewhere.has(n) && !(n in PUBLISHED_FOR_NOBODY_IN_THIS_REPO))
            .sort();
        expect(unread).toEqual([]);
    });
});
