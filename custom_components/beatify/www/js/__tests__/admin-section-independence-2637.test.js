/**
 * #2637 — the admin sections must not reach back into admin.js through `window`.
 *
 * `admin.js` used to publish 14 names on `window` and the extracted sections
 * called back through them. That is a load-order dependency with nothing
 * watching it: a section only worked because admin.js happened to have executed
 * first, and the moment the order changed (or a `.min.js` drifted, as in #1263)
 * the failure showed up at a party rather than in CI.
 *
 * What is asserted here is behaviour, not source text. Every test runs with a
 * `window` whose reads of an admin-core name THROW — so a re-introduced
 * `window.loadStatus?.()` fails loudly at the moment it is evaluated instead of
 * silently no-opping the way the real `typeof … === 'function'` guards did. Then
 * each section is loaded on its own, with admin.js never imported at all, and
 * driven through the controls it renders. If a section needs the core to have
 * run first, it cannot pass.
 *
 * The last block checks the page's script manifest against the bundle's real
 * module graph: no file may be both an input of admin.min.js and a separate
 * `<script>` in admin.html, because that is two copies of one module with an
 * ordering problem between them.
 *
 * #2680 widened that last block. Comparing the `<script src>` names against the
 * bundle inputs only catches a file listed on the page *by name*. It missed
 * `admin/sections/library.js`, which admin.min.js inlines while `wizard.js` —
 * its own module tag — `import`ed it over the network: two instances, two sets
 * of module-level state, load order deciding which one a click reached. So the
 * check now walks each non-bundled script's whole import graph, not just its
 * filename.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { readFile } from 'node:fs/promises';
import { readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join, relative, resolve } from 'node:path';
import { build } from 'esbuild';
// #2679 extracted the page harness (the sentinel `window`, the hand-rolled DOM,
// bootPage) so a second suite could drive a section the same way.
import { bootPage, restoreGlobals, saveGlobals } from './helpers/admin-page.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const JS_DIR = resolve(HERE, '..');
const WWW_DIR = resolve(JS_DIR, '..');
const REPO_ROOT = resolve(WWW_DIR, '..', '..', '..');

beforeEach(saveGlobals);
afterEach(restoreGlobals);

// ---------------------------------------------------------------------------

/** Every module under www/js/admin/, discovered so a new section is covered. */
function adminModules() {
    const out = [];
    const walk = (dir) => {
        for (const entry of readdirSync(dir, { withFileTypes: true })) {
            const p = join(dir, entry.name);
            if (entry.isDirectory()) walk(p);
            else if (entry.isFile() && entry.name.endsWith('.js')) out.push(p);
        }
    };
    walk(join(JS_DIR, 'admin'));
    return out.sort();
}

describe('#2637 a section loads without the admin core', () => {
    it('finds the section modules it is about to import', () => {
        // Guards the guard: an empty sweep would make the test below vacuous.
        const names = adminModules().map((p) => relative(JS_DIR, p));
        expect(names).toContain('admin/sections/mix.js');
        expect(names).toContain('admin/sections/media-players.js');
        expect(names.length).toBeGreaterThan(10);
    });

    it.each(adminModules().map((p) => [relative(JS_DIR, p), p]))(
        '%s evaluates with no admin-core global on the page',
        async (_name, path) => {
            bootPage([]);
            // A throw here is the sentinel: the module reached for something
            // admin.js publishes while admin.js has never been imported.
            await expect(import(/* @vite-ignore */ path)).resolves.toBeTruthy();
        },
    );

    it('tts-settings and party-lights hand over their config as imports', async () => {
        bootPage([]);
        const { ttsConfig } = await import('../tts-settings.js');
        const { partyLightsConfig } = await import('../party-lights.js');
        // Before #2637 these two were classic scripts and the only way to reach
        // them was `window._ttsConfig` — a name the sentinel now refuses.
        const tts = ttsConfig();
        expect(typeof tts.enabled).toBe('boolean');
        expect(Object.keys(tts).filter((k) => k.startsWith('announce_'))).toHaveLength(23);
        const lights = partyLightsConfig();
        expect(typeof lights.enabled).toBe('boolean');
        expect(Array.isArray(lights.entity_ids)).toBe(true);
    });
});

describe('#2637 the media-players Refresh button runs on an injected dependency', () => {
    it('calls the refreshStatus it was given at init', async () => {
        const doc = bootPage(['media-players-list', 'media-player-validation-msg', 'start-game']);
        const { initMediaPlayers, renderMediaPlayers } = await import('../admin/sections/media-players.js');

        const refreshStatus = vi.fn();
        initMediaPlayers({ refreshStatus });
        renderMediaPlayers([]); // no compatible players → the empty state

        const button = doc.byId['media-players-list'].querySelector('[data-action="refresh-status"]');
        expect(button, 'the empty state must offer a Refresh control').not.toBeNull();
        button.click();
        expect(refreshStatus).toHaveBeenCalledTimes(1);
    });

    it('does not blow up when nothing was injected', async () => {
        // The old inline onclick="loadStatus()" needed a page global to exist.
        // Without an injected dependency the button must simply do nothing.
        const doc = bootPage(['media-players-list', 'media-player-validation-msg', 'start-game']);
        const { renderMediaPlayers } = await import('../admin/sections/media-players.js');
        renderMediaPlayers([]);
        const button = doc.byId['media-players-list'].querySelector('[data-action="refresh-status"]');
        expect(() => button.click()).not.toThrow();
    });
});

describe('#2637 the playlists section clears its own filters', () => {
    it('resets the filter state when its Clear button is clicked', async () => {
        const doc = bootPage(['playlists-list', 'playlist-filter-bar', 'start-game']);
        const { adminState } = await import('../admin/state.js');
        const { renderPlaylists, updateActiveFilterTags } = await import('../admin/sections/playlists.js');

        adminState.activeFilters = { decade: '1980s', style: '', region: '', special: '' };
        updateActiveFilterTags();
        renderPlaylists(
            [{ path: '/pl/a.json', name: 'A', is_valid: true, tags: ['1990s'], song_count: 10 }],
            '/pl',
        );

        const clear = doc.byId['playlists-list'].querySelector('[data-action="clear-filters"]');
        expect(clear, 'a filter that matches nothing must offer a way out').not.toBeNull();
        clear.click();

        expect(adminState.activeFilterTags).toEqual(['all']);
        expect(adminState.activeFilters).toEqual({ decade: '', style: '', region: '', special: '' });
        // The re-render happened: the playlist the filter was hiding is back.
        expect(doc.byId['playlists-list'].innerHTML).toContain('/pl/a.json');
    });
});

describe('#2637 the Mix tab refreshes through its injected dependency', () => {
    it('calls refreshStatus after saving the mix as a community playlist', async () => {
        const fetchImpl = vi.fn(async (url) => {
            if (String(url).includes('/playlists/mix')) {
                return { ok: true, json: async () => ({ success: true, path: '/pl/mix.json', song_count: 42 }) };
            }
            return { ok: true, json: async () => ({ success: true, song_count: 42, playlist_count: 3 }) };
        });
        const doc = bootPage(
            ['mix-chip-cloud', 'mix-start', 'mix-save-community', 'mix-error', 'mix-preview-text'],
            { fetchImpl },
        );
        const { adminState } = await import('../admin/state.js');
        const { initMixTab, renderMixChipCloud } = await import('../admin/sections/mix.js');

        const startGame = vi.fn();
        const refreshStatus = vi.fn();
        initMixTab({ startGame, refreshStatus });

        adminState.selectedMediaPlayer = { entityId: 'media_player.kitchen', platform: 'mass' };
        adminState.playlistData = [{ path: '/pl/a.json', name: 'A', is_valid: true, tags: ['1980s'] }];
        renderMixChipCloud();

        const chip = doc.byId['mix-chip-cloud'].querySelector('[data-mix-tag="1980s"]');
        expect(chip, 'a tagged playlist must produce a chip to select').not.toBeNull();
        chip.click(); // select the tag so the mix has something to assemble

        // initMixTab() has already bound #mix-start (it calls bindMixPanel).
        doc.byId['mix-save-community'].checked = true;
        doc.byId['mix-start'].dispatch('click');
        // startMix awaits the assemble POST before the refresh; let it settle.
        await new Promise((r) => setTimeout(r, 0));

        expect(refreshStatus).toHaveBeenCalledTimes(1);
        expect(startGame).toHaveBeenCalledTimes(1);
    });
});

/** Every module esbuild pulls in when `entry` is bundled, as JS_DIR-relative paths. */
async function moduleGraph(entry) {
    const result = await build({
        entryPoints: [join(JS_DIR, entry)],
        bundle: true,
        format: 'esm',
        write: false,
        metafile: true,
        logLevel: 'silent',
    });
    return Object.keys(result.metafile.inputs)
        .map((p) => relative(JS_DIR, resolve(REPO_ROOT, p)));
}

describe('#2637 nothing is both bundled and loaded on its own', () => {
    /**
     * admin.html's `<script src>` list is the page's load order; the bundle's
     * esbuild metafile is its real module graph. A file appearing in both means
     * the page runs two copies of one module and something has to load first —
     * exactly the shape that made `window._ttsConfig` necessary.
     */
    let inputs;
    let scripts;

    beforeEach(async () => {
        if (!inputs) inputs = await moduleGraph('admin.js');
        if (!scripts) {
            const html = await readFile(join(WWW_DIR, 'admin.html'), 'utf8');
            scripts = [...html.matchAll(/<script[^>]+src="\/beatify\/static\/js\/([^"?]+)/g)]
                .map((m) => m[1]);
        }
    });

    it('bundles the two config sections that used to be classic scripts', () => {
        // This is what puts them under `npm run build:check` (#1263).
        expect(inputs).toContain('tts-settings.js');
        expect(inputs).toContain('party-lights.js');
    });

    it('does not also load a bundled module as its own script tag', () => {
        const duplicated = scripts
            .filter((src) => src !== 'admin.min.js')
            .map((src) => src.replace(/\.min\.js$/, '.js'))
            .filter((src) => inputs.includes(src));
        expect(duplicated).toEqual([]);
    });

    /**
     * #2680: the check above compares filenames, so it only sees a duplicate
     * that admin.html names out loud. `wizard.js` was never named as a bundle
     * input — it reached `admin/sections/library.js` by `import`, one level
     * down, and the page ran two copies of it for months with every test green.
     *
     * So: take each script the page loads that is NOT the admin bundle, bundle
     * it the way the browser would resolve its imports, and intersect its whole
     * graph with the admin bundle's. A shared file means two instances with two
     * sets of module-level state and load order picking the winner.
     *
     * The rule this enforces: a file is a bundle input OR its own entry point,
     * never both. Fixing a hit means moving the entry point into the bundle
     * (what #2680 did with wizard.js) or taking the shared file out of it —
     * never leaving both.
     */
    it('does not reach a bundled module by import from another entry point', async () => {
        const bundled = new Set(inputs);
        const entryPoints = scripts
            .filter((src) => src !== 'admin.min.js')
            // Vendor drops are third-party artifacts with no source graph here.
            .filter((src) => !src.startsWith('vendor/'))
            // A `.min.js` on the page is built from the readable sibling; that
            // sibling is what has the imports.
            .map((src) => src.replace(/\.min\.js$/, '.js'));

        const shared = [];
        for (const entry of entryPoints) {
            for (const dep of await moduleGraph(entry)) {
                if (dep !== entry && bundled.has(dep)) shared.push(`${entry} imports ${dep}`);
            }
        }
        expect(shared).toEqual([]);
    });
});
