/**
 * #1568 — the Smart Playlist Mixer "🎚️ Mix" tab was unreachable because its
 * markup lived only in admin.html's dead flat #playlists section (display:none
 * since rc11/#1138). The tab strip + Mix panel now ship inside the Playlist Hub
 * so they appear in every hub mount (incl. the live wizard step-3 picker).
 *
 * vitest env is `node` (no DOM) — these cover the pure markup builders.
 */
import { describe, it, expect } from 'vitest';
import { _topTabsHtml, _mixPanelHtml } from '../playlist-hub.js';

describe('playlist-hub #1568: top-level tab strip', () => {
    it('renders both Playlists and Mix tabs', () => {
        const html = _topTabsHtml('list');
        expect(html).toContain('data-plh-toptab="list"');
        expect(html).toContain('data-plh-toptab="mix"');
        expect(html).toContain('data-i18n="admin.playlistTabList"');
        expect(html).toContain('data-i18n="admin.playlistTabMix"');
        expect(html).toContain('🎚️');
    });

    it('marks the Playlists tab active by default', () => {
        const html = _topTabsHtml('list');
        // The "list" tab carries .active + aria-selected="true".
        expect(html).toMatch(/aria-selected="true" data-plh-toptab="list"/);
        expect(html).toMatch(/aria-selected="false" data-plh-toptab="mix"/);
    });

    it('marks the Mix tab active when selected', () => {
        const html = _topTabsHtml('mix');
        expect(html).toMatch(/aria-selected="true" data-plh-toptab="mix"/);
        expect(html).toMatch(/aria-selected="false" data-plh-toptab="list"/);
    });
});

describe('playlist-hub #1568: Mix panel markup', () => {
    it('exposes the IDs mix.js binds to', () => {
        const html = _mixPanelHtml();
        for (const id of ['mix-chip-cloud', 'mix-start', 'mix-preview-text', 'mix-error', 'mix-save-community']) {
            expect(html).toContain(`id="${id}"`);
        }
        // target-count segmented control + i18n keys
        expect(html).toContain('data-mix-count="50"');
        expect(html).toContain('data-i18n="admin.mixTitle"');
        expect(html).toContain('data-i18n="admin.mixStart"');
    });
});
