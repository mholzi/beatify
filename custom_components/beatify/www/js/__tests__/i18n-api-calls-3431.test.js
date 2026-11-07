/**
 * #3431: library-ai.js called `BeatifyI18n.apply()`, which i18n.js never
 * exposed, so the Crate Digger AI modal stayed English in every language.
 * Every `BeatifyI18n.<name>` used in the shipped sources must be part of the
 * object i18n.js returns.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { JS_DIR } from './helpers/js-source.js';

function sources(dir) {
    const out = [];
    for (const name of readdirSync(dir)) {
        const p = join(dir, name);
        if (name === '__tests__' || name === 'node_modules') continue;
        if (statSync(p).isDirectory()) out.push(...sources(p));
        else if (name.endsWith('.js') && !name.endsWith('.min.js')) out.push(p);
    }
    return out;
}

const i18n = readFileSync(join(JS_DIR, 'i18n.js'), 'utf8');
const ret = i18n.slice(i18n.lastIndexOf('return {'));
const exposed = new Set([...ret.slice(0, ret.indexOf('}')).matchAll(/(\w+)\s*:/g)].map((m) => m[1]));

describe('#3431 BeatifyI18n calls match the exposed API', () => {
    it('i18n.js exposes initPageTranslations', () => {
        expect(exposed.has('initPageTranslations')).toBe(true);
    });

    it('no source calls a BeatifyI18n member that does not exist', () => {
        const missing = [];
        for (const file of sources(JS_DIR)) {
            const src = readFileSync(file, 'utf8');
            for (const m of src.matchAll(/BeatifyI18n\.(\w+)/g)) {
                if (!exposed.has(m[1])) missing.push(`${file.slice(JS_DIR.length + 1)}: ${m[1]}`);
            }
        }
        expect(missing).toEqual([]);
    });
});
