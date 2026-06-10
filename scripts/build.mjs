#!/usr/bin/env node
/**
 * Beatify frontend build — single source of truth for the served `.min.js` bundles.
 *
 * Edit the readable `.js` sources under www/js/ and run `npm run build`; never
 * hand-edit a `.min.js`. `npm run build:check` rebuilds in memory and fails if any
 * committed `.min.js` drifts from its source — that drift is what caused #1263
 * (Amazon-Music admin UI lived in admin.js but never made it into admin.min.js).
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

/** Build one target and return { path, contents } without touching disk. */
async function compile(target) {
  const common = {
    minify: true,
    legalComments: "none",
    write: false,
    logLevel: "silent",
  };
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
  ];
}

async function run() {
  const check = process.argv.includes("--check");
  const results = await Promise.all(targets().map(compile));

  if (!check) {
    const { writeFile } = await import("node:fs/promises");
    await Promise.all(results.map((r) => writeFile(r.path, r.contents)));
    console.log(`✅ built ${results.length} bundles`);
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
    console.error("❌ min.js out of sync with source — run `npm run build` and commit:");
    for (const d of drifted) console.error(`   - ${d}`);
    process.exit(1);
  }
  console.log(`✅ all ${results.length} bundles match source`);
}

run().catch((e) => {
  console.error(e);
  process.exit(1);
});
