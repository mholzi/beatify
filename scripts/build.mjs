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
 * Usage:
 *   node scripts/build.mjs           # write all bundles to disk
 *   node scripts/build.mjs --check   # verify committed bundles match source (CI)
 */
import { build } from "esbuild";
import { readFile } from "node:fs/promises";
import path from "node:path";
import process from "node:process";

const JS_DIR = "custom_components/beatify/www/js";
const CSS_DIR = "custom_components/beatify/www/css";

// Per-file minify: readable IIFE source → minified IIFE, 1:1.
const MINIFY = [
  "analytics",
  "dashboard",
  "i18n",
  "party-lights",
  "playlist-generator",
  "playlist-requests",
  "tts-settings",
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
const CSS = ["styles", "analytics", "dashboard"];

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

async function run() {
  const check = process.argv.includes("--check");
  // A CSS target emits two files (the stylesheet and its sourcemap), so compile()
  // may return an array. Flatten before anything downstream counts or writes.
  const results = (await Promise.all(targets().map(compile))).flat();

  if (!check) {
    const { writeFile } = await import("node:fs/promises");
    await Promise.all(results.map((r) => writeFile(r.path, r.contents)));
    console.log(`✅ built ${results.length} artifacts`);
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

  if (drifted.length) {
    console.error("❌ minified asset out of sync with source — run `npm run build` and commit:");
    for (const d of drifted) console.error(`   - ${d}`);
    process.exit(1);
  }
  console.log(`✅ all ${results.length} artifacts match source`);
}

run().catch((e) => {
  console.error(e);
  process.exit(1);
});
