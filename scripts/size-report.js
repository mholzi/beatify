#!/usr/bin/env node
/**
 * Size Report Script (Story 18.4)
 *
 * Reports file sizes and gzip sizes for Beatify bundles.
 */

const fs = require('fs');
const path = require('path');
const zlib = require('zlib');

const WWW_DIR = path.join(__dirname, '..', 'custom_components', 'beatify', 'www');

const FILES = [
    { path: 'js/player.js', type: 'source' },
    { path: 'js/player.min.js', type: 'minified' },
    { path: 'js/admin.js', type: 'source' },
    { path: 'js/admin.min.js', type: 'minified' },
    { path: 'js/dashboard.js', type: 'source' },
    { path: 'js/dashboard.min.js', type: 'minified' },
    { path: 'js/i18n.js', type: 'source' },
    { path: 'js/i18n.min.js', type: 'minified' },
    { path: 'css/styles.css', type: 'source' },
    { path: 'css/styles.min.css', type: 'minified' },
    { path: 'css/dashboard.css', type: 'source' },
    { path: 'css/dashboard.min.css', type: 'minified' }
];

function formatSize(bytes) {
    if (bytes < 1024) return bytes + 'B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + 'KB';
    return (bytes / (1024 * 1024)).toFixed(1) + 'MB';
}

function getGzipSize(filepath) {
    try {
        const content = fs.readFileSync(filepath);
        const gzipped = zlib.gzipSync(content);
        return gzipped.length;
    } catch (e) {
        return null;
    }
}

console.log('\n📊 Beatify Bundle Size Report\n');
console.log('─'.repeat(70));
console.log(
    'File'.padEnd(30) +
    'Size'.padStart(10) +
    'Gzipped'.padStart(12) +
    'Type'.padStart(12)
);
console.log('─'.repeat(70));

let totalSource = 0;
let totalMinified = 0;
let totalGzipped = 0;

for (const file of FILES) {
    const filepath = path.join(WWW_DIR, file.path);

    if (!fs.existsSync(filepath)) {
        continue;
    }

    const size = fs.statSync(filepath).size;
    const gzipSize = getGzipSize(filepath);

    if (file.type === 'source') {
        totalSource += size;
    } else {
        totalMinified += size;
        if (gzipSize) totalGzipped += gzipSize;
    }

    console.log(
        file.path.padEnd(30) +
        formatSize(size).padStart(10) +
        (gzipSize ? formatSize(gzipSize) : '-').padStart(12) +
        file.type.padStart(12)
    );
}

console.log('─'.repeat(70));
console.log(
    'Total (minified)'.padEnd(30) +
    formatSize(totalMinified).padStart(10) +
    formatSize(totalGzipped).padStart(12) +
    ''.padStart(12)
);
console.log(
    'Total (source)'.padEnd(30) +
    formatSize(totalSource).padStart(10) +
    ''.padStart(12) +
    ''.padStart(12)
);

if (totalSource > 0 && totalMinified > 0) {
    const reduction = Math.round((1 - totalMinified / totalSource) * 100);
    console.log(`\nReduction: ${reduction}%`);
}

// Target checks
console.log('\n📋 Target Checks:');
const playerMin = path.join(WWW_DIR, 'js/player.min.js');
const stylesMin = path.join(WWW_DIR, 'css/styles.min.css');

if (fs.existsSync(playerMin)) {
    const size = fs.statSync(playerMin).size;
    const gzip = getGzipSize(playerMin);
    console.log(`   player.min.js: ${formatSize(size)} (target <100KB) ${size <= 100 * 1024 ? '✓' : '✗'}`);
    console.log(`   player.min.js gzipped: ${formatSize(gzip)} (target <35KB) ${gzip <= 35 * 1024 ? '✓' : '✗'}`);
}

if (fs.existsSync(stylesMin)) {
    const size = fs.statSync(stylesMin).size;
    const gzip = getGzipSize(stylesMin);
    console.log(`   styles.min.css: ${formatSize(size)} (target <80KB) ${size <= 80 * 1024 ? '✓' : '✗'}`);
    console.log(`   styles.min.css gzipped: ${formatSize(gzip)} (target <25KB) ${gzip <= 25 * 1024 ? '✓' : '✗'}`);
}

console.log('');
