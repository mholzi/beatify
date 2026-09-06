#!/usr/bin/env node
/**
 * Beatify frontend build — single source of truth for the served minified assets.
 *
 * Edit the readable sources under www/js/ and www/css/ and run `npm run build`;
 * never hand-edit a `.min.js` or `.min.css`. `npm run build:check` rebuilds in
 * memory and fails if any committed artifact drifts from its source — that drift
 * is what caused #1263 (Amazon-Music admin UI lived in admin.js but never made it
 * into admin.min.js).
 *
 * CSS was outside this guard until #2098 and drifted the same way, silently: three
 * merged features (Sudden Death elimination UI #827, Streak-Shield #1666, Mix-tab
 * CTA #1625) shipped their markup and JS but not their styles, because
 * admin.html and player.html load styles.min.css.
 *
 * The same run also writes the pre-compressed `.gz` siblings that HA's static
 * handler serves to every phone (#2640), and `--check` verifies those too — an
 * unchecked `.gz` outranks the fresh file for every browser and would be a
 * worse trap than shipping none at all.
 *
 * Usage:
 *   node scripts/build.mjs           # write all bundles + .gz siblings to disk
 *   node scripts/build.mjs --check   # verify committed artifacts match source (CI)
 */
import { build } from "esbuild";
import { readFile, readdir, stat, unlink, writeFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";
import { fileURLToPath } from "node:url";
import { gunzipSync, gzipSync } from "node:zlib";

const WWW_DIR = "custom_components/beatify/www";
const JS_DIR = `${WWW_DIR}/js`;
const CSS_DIR = `${WWW_DIR}/css`;

// Per-file minify: readable IIFE source → minified IIFE, 1:1.
// #2637 removed "party-lights" and "tts-settings" from this list: both are ES
// modules imported by admin.js now, so they arrive through the admin bundle and
// a standalone .min.js for them would be a second, unloaded copy.
const MINIFY = [
  "analytics",
  "dashboard",
  "i18n",
  "playlist-generator",
  "playlist-requests",
  "utils",
];

// ESM bundles: an entry module that `import`s its siblings → one minified bundle.
// admin (#1279 step 2): now an ES module that imports ./admin/util.js; bundled
// to admin.min.js and loaded via `<script type="module">` in admin.html.
const BUNDLES = [
  { entry: "player-core", out: "player.bundle.min.js", format: "esm" },
  { entry: "admin", out: "admin.min.js", format: "esm" },
];

// Stylesheets: readable source → minified, 1:1. Every HTML page loads the
// .min.css, never the readable one, so anything missing here does not reach a
// screen. Sourcemaps are emitted alongside because the committed tree has them
// and dropping them would take away the only way to debug the shipped CSS.
const CSS = ["styles", "analytics", "dashboard", "library"];

/** Build one target and return { path, contents } without touching disk. */
async function compile(target) {
  const common = {
    minify: true,
    legalComments: "none",
    write: false,
    logLevel: "silent",
  };
  if (target.kind === "css") {
    const r = await build({
      ...common,
      entryPoints: [path.join(CSS_DIR, `${target.name}.css`)],
      outfile: path.join(CSS_DIR, `${target.name}.min.css`),
      bundle: false,
      sourcemap: true,
      loader: { ".css": "css" },
    });
    return r.outputFiles.map((f) => ({ path: f.path, contents: f.contents }));
  }
  if (target.kind === "minify") {
    const r = await build({
      ...common,
      entryPoints: [path.join(JS_DIR, `${target.name}.js`)],
      bundle: false,
    });
    return { path: path.join(JS_DIR, `${target.name}.min.js`), contents: r.outputFiles[0].contents };
  }
  const r = await build({
    ...common,
    entryPoints: [path.join(JS_DIR, `${target.entry}.js`)],
    bundle: true,
    format: target.format,
  });
  return { path: path.join(JS_DIR, target.out), contents: r.outputFiles[0].contents };
}

function targets() {
  return [
    ...MINIFY.map((name) => ({ kind: "minify", name })),
    ...BUNDLES.map((b) => ({ kind: "bundle", ...b })),
    ...CSS.map((name) => ({ kind: "css", name })),
  ];
}

// ---------------------------------------------------------------------------
// Pre-compressed `.gz` siblings (#2640)
//
// HA registers /beatify/static through aiohttp's static handler, which never
// compresses on the fly. It does serve `<file>.gz` verbatim when the request
// carries `Accept-Encoding: gzip` (aiohttp web_fileresponse,
// `_get_file_path_stat_encoding`) — and every browser sends that header. With
// no sibling on disk each phone pulls the raw bytes over the party wifi.
//
// The siblings are committed, not built at install time: HACS copies the repo
// directory onto the box and never runs a build step there, so a `.gz` that
// only exists after `npm run build` would never reach a single user.
//
// Which files: every compressible static asset of at least GZIP_MIN_BYTES.
// A mechanical rule, no allowlist to drift. `__tests__/` is dev-only and never
// requested; `.map` files are fetched only with devtools open and would add
// ~326 KB to every HACS download for nobody's benefit.
const GZIP_EXTENSIONS = new Set([".html", ".css", ".js", ".json", ".svg", ".webmanifest"]);
// Under ~1 KB the gzip header plus a cold dictionary usually costs more than it
// saves, and the extra file is a second thing that can go stale.
const GZIP_MIN_BYTES = 1024;
const GZIP_SKIP_DIRS = new Set(["__tests__"]);

async function walkFiles(dir, out = []) {
  for (const entry of await readdir(dir, { withFileTypes: true })) {
    const p = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      if (!GZIP_SKIP_DIRS.has(entry.name)) await walkFiles(p, out);
    } else if (entry.isFile()) {
      out.push(p);
    }
  }
  return out;
}

/** Static files that must carry a committed `.gz` sibling. */
export async function gzipTargets(root = WWW_DIR) {
  const files = await walkFiles(root);
  const targets = [];
  for (const p of files) {
    if (p.endsWith(".gz") || p.endsWith(".map")) continue;
    if (!GZIP_EXTENSIONS.has(path.extname(p))) continue;
    if ((await stat(p)).size < GZIP_MIN_BYTES) continue;
    targets.push(p);
  }
  return targets.sort();
}

async function existingGzips(root = WWW_DIR) {
  return (await walkFiles(root)).filter((p) => p.endsWith(".gz")).sort();
}

/** Rewrite every `.gz` sibling from its current source and drop orphans. */
export async function writeGzipSiblings(root = WWW_DIR) {
  const targets = await gzipTargets(root);
  const wanted = new Set(targets.map((p) => `${p}.gz`));
  await Promise.all(
    targets.map(async (src) =>
      writeFile(`${src}.gz`, gzipSync(await readFile(src), { level: 9 })),
    ),
  );
  const removed = [];
  for (const gz of await existingGzips(root)) {
    if (!wanted.has(gz)) {
      await unlink(gz);
      removed.push(gz);
    }
  }
  return { written: wanted.size, removed };
}

/**
 * Verify the committed `.gz` siblings, returning a list of problems.
 *
 * The comparison decompresses the sibling and matches it against the file next
 * to it — deliberately not a byte comparison of the gzip stream. zlib stamps the
 * build host's OS into the gzip header (0x13 on macOS, 0x03 on Linux), so
 * comparing bytes would fail in CI for a perfectly fresh file.
 *
 * A stale `.gz` is worse than none: every browser sends `Accept-Encoding: gzip`,
 * so the sibling wins, and aiohttp even derives the ETag from the *compressed*
 * file's mtime and size — the browser then caches the old bytes as if they were
 * current. A `curl` without the header sees the fresh file and shows nothing.
 */
export async function checkGzipSiblings(root = WWW_DIR) {
  const problems = [];
  const targets = await gzipTargets(root);
  const wanted = new Set(targets.map((p) => `${p}.gz`));

  for (const src of targets) {
    const gz = `${src}.gz`;
    let compressed;
    try {
      compressed = await readFile(gz);
    } catch {
      problems.push(`${gz} (missing)`);
      continue;
    }
    let plain;
    try {
      plain = gunzipSync(compressed);
    } catch {
      problems.push(`${gz} (not a readable gzip stream)`);
      continue;
    }
    if (!plain.equals(await readFile(src))) {
      problems.push(`${gz} (stale — decompresses to something other than ${path.basename(src)})`);
    }
  }

  for (const gz of await existingGzips(root)) {
    if (!wanted.has(gz)) problems.push(`${gz} (orphan — nothing on disk it belongs to)`);
  }

  return problems;
}

async function run() {
  const check = process.argv.includes("--check");
  // A CSS target emits two files (the stylesheet and its sourcemap), so compile()
  // may return an array. Flatten before anything downstream counts or writes.
  const results = (await Promise.all(targets().map(compile))).flat();

  if (!check) {
    await Promise.all(results.map((r) => writeFile(r.path, r.contents)));
    // Gzip *after* the artifacts land, so the siblings compress the fresh bytes.
    const { written, removed } = await writeGzipSiblings();
    console.log(`✅ built ${results.length} artifacts, ${written} .gz siblings`);
    for (const r of removed) console.log(`   - removed orphan ${r}`);
    return;
  }

  const drifted = [];
  for (const r of results) {
    let committed;
    try {
      committed = await readFile(r.path);
    } catch {
      drifted.push(`${r.path} (missing — run npm run build)`);
      continue;
    }
    if (!committed.equals(Buffer.from(r.contents))) drifted.push(r.path);
  }

  // A `.gz` sibling is checked against the file it sits next to, and the loop
  // above has already tied that file to its source — so the two checks together
  // prove the compressed bytes a phone receives came from the current source.
  const gzProblems = await checkGzipSiblings();

  if (drifted.length || gzProblems.length) {
    console.error("❌ static assets out of sync — run `npm run build` and commit:");
    for (const d of drifted) console.error(`   - ${d}`);
    for (const g of gzProblems) console.error(`   - ${g}`);
    process.exit(1);
  }
  const gzCount = (await gzipTargets()).length;
  console.log(`✅ all ${results.length} artifacts and ${gzCount} .gz siblings match source`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  run().catch((e) => {
    console.error(e);
    process.exit(1);
  });
}
