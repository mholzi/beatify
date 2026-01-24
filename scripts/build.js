#!/usr/bin/env node
/**
 * Beatify Build Script (Story 18.4)
 *
 * Minifies JavaScript and CSS files for production deployment.
 *
 * Usage:
 *   npm run build          # Production build (minified)
 *   npm run build:dev      # Development build (source maps, no minify)
 *   npm run build:watch    # Watch mode for development
 */

const fs = require('fs');
const path = require('path');

// Determine build mode from args
const args = process.argv.slice(2);
const isDev = args.includes('--dev');
const isWatch = args.includes('--watch');

// Paths
const WWW_DIR = path.join(__dirname, '..', 'custom_components', 'beatify', 'www');
const JS_DIR = path.join(WWW_DIR, 'js');
const CSS_DIR = path.join(WWW_DIR, 'css');

// Files to process
const JS_FILES = [
    { src: 'utils.js', out: 'utils.min.js' },
    { src: 'player.js', out: 'player.min.js' },
    { src: 'admin.js', out: 'admin.min.js' },
    { src: 'dashboard.js', out: 'dashboard.min.js' },
    { src: 'i18n.js', out: 'i18n.min.js' }
];

const CSS_FILES = [
    { src: 'styles.css', out: 'styles.min.css' },
    { src: 'dashboard.css', out: 'dashboard.min.css' }
];

/**
 * Build JavaScript files using esbuild
 */
async function buildJS() {
    let esbuild;
    try {
        esbuild = require('esbuild');
    } catch (e) {
        console.error('esbuild not installed. Run: npm install');
        process.exit(1);
    }

    const results = [];

    for (const file of JS_FILES) {
        const srcPath = path.join(JS_DIR, file.src);
        const outPath = path.join(JS_DIR, file.out);

        if (!fs.existsSync(srcPath)) {
            console.warn(`⚠️  Skipping ${file.src} (not found)`);
            continue;
        }

        try {
            const result = await esbuild.build({
                entryPoints: [srcPath],
                outfile: outPath,
                bundle: false, // No bundling - files are standalone
                minify: !isDev,
                sourcemap: true, // Always generate source maps (AC5)
                target: ['es2015'], // IE11 not supported, ES6+ is fine
                format: 'iife',
                legalComments: 'none', // Remove license comments for smaller size
                drop: isDev ? [] : ['debugger'], // Remove debugger statements in prod (keep console for errors)
                logLevel: 'warning'
            });

            const srcSize = fs.statSync(srcPath).size;
            const outSize = fs.statSync(outPath).size;
            const reduction = Math.round((1 - outSize / srcSize) * 100);

            results.push({
                file: file.out,
                srcSize,
                outSize,
                reduction
            });

            console.log(`✓ ${file.src} → ${file.out} (${formatSize(srcSize)} → ${formatSize(outSize)}, -${reduction}%)`);
        } catch (e) {
            console.error(`✗ Error building ${file.src}:`, e.message);
        }
    }

    return results;
}

/**
 * Build CSS files using lightningcss
 */
async function buildCSS() {
    let lightningcss;
    try {
        lightningcss = require('lightningcss');
    } catch (e) {
        console.error('lightningcss not installed. Run: npm install');
        process.exit(1);
    }

    const results = [];

    for (const file of CSS_FILES) {
        const srcPath = path.join(CSS_DIR, file.src);
        const outPath = path.join(CSS_DIR, file.out);

        if (!fs.existsSync(srcPath)) {
            console.warn(`⚠️  Skipping ${file.src} (not found)`);
            continue;
        }

        try {
            const source = fs.readFileSync(srcPath);

            const { code, map } = lightningcss.transform({
                filename: srcPath,
                code: source,
                minify: !isDev,
                sourceMap: true,
                targets: {
                    // Support last 2 versions of major browsers
                    chrome: (100 << 16),
                    firefox: (100 << 16),
                    safari: (14 << 16),
                }
            });

            fs.writeFileSync(outPath, code);
            if (map) {
                fs.writeFileSync(outPath + '.map', map);
            }

            const srcSize = source.length;
            const outSize = code.length;
            const reduction = Math.round((1 - outSize / srcSize) * 100);

            results.push({
                file: file.out,
                srcSize,
                outSize,
                reduction
            });

            console.log(`✓ ${file.src} → ${file.out} (${formatSize(srcSize)} → ${formatSize(outSize)}, -${reduction}%)`);
        } catch (e) {
            console.error(`✗ Error building ${file.src}:`, e.message);
        }
    }

    return results;
}

/**
 * Format bytes as human-readable size
 */
function formatSize(bytes) {
    if (bytes < 1024) return bytes + 'B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + 'KB';
    return (bytes / (1024 * 1024)).toFixed(1) + 'MB';
}

/**
 * Watch mode for development
 */
async function watchMode() {
    const chokidar = require('chokidar');

    console.log('👀 Watching for changes...');

    const jsWatcher = chokidar.watch(path.join(JS_DIR, '*.js'), {
        ignored: /\.min\.js$/,
        persistent: true
    });

    const cssWatcher = chokidar.watch(path.join(CSS_DIR, '*.css'), {
        ignored: /\.min\.css$/,
        persistent: true
    });

    jsWatcher.on('change', async (filepath) => {
        console.log(`\n📝 Changed: ${path.basename(filepath)}`);
        await buildJS();
    });

    cssWatcher.on('change', async (filepath) => {
        console.log(`\n📝 Changed: ${path.basename(filepath)}`);
        await buildCSS();
    });
}

/**
 * Main entry point
 */
async function main() {
    console.log(`\n🔨 Beatify Build - ${isDev ? 'Development' : 'Production'} Mode\n`);
    console.log('─'.repeat(60));

    const startTime = Date.now();

    console.log('\n📦 Building JavaScript...\n');
    const jsResults = await buildJS();

    console.log('\n🎨 Building CSS...\n');
    const cssResults = await buildCSS();

    console.log('\n' + '─'.repeat(60));

    // Summary
    const totalSrcSize = [...jsResults, ...cssResults].reduce((sum, r) => sum + r.srcSize, 0);
    const totalOutSize = [...jsResults, ...cssResults].reduce((sum, r) => sum + r.outSize, 0);
    const totalReduction = Math.round((1 - totalOutSize / totalSrcSize) * 100);

    console.log(`\n📊 Summary:`);
    console.log(`   Total: ${formatSize(totalSrcSize)} → ${formatSize(totalOutSize)} (-${totalReduction}%)`);
    console.log(`   Build time: ${Date.now() - startTime}ms`);

    // Check against targets (AC1, AC2)
    const playerMin = jsResults.find(r => r.file === 'player.min.js');
    const stylesMin = cssResults.find(r => r.file === 'styles.min.css');

    if (playerMin) {
        const target = 100 * 1024;
        const status = playerMin.outSize <= target ? '✓' : '⚠️';
        console.log(`   ${status} player.min.js: ${formatSize(playerMin.outSize)} (target: <100KB)`);
    }

    if (stylesMin) {
        const target = 80 * 1024;
        const status = stylesMin.outSize <= target ? '✓' : '⚠️';
        console.log(`   ${status} styles.min.css: ${formatSize(stylesMin.outSize)} (target: <80KB)`);
    }

    console.log('\n✨ Build complete!\n');

    if (isWatch) {
        await watchMode();
    }
}

main().catch(e => {
    console.error('Build failed:', e);
    process.exit(1);
});
