/**
 * #1568 — the Smart Playlist Mixer "🎚️ Mix" tab was unreachable because its
 * markup lived only in admin.html's dead flat #playlists section (display:none
 * since rc11/#1138). The tab strip + Mix panel now ship inside the Playlist Hub
 * so they appear in every hub mount (incl. the live wizard step-3 picker).
 *
 * vitest env is `node` (no DOM) — these cover the pure markup builders.
 */
import { describe, it, expect } from 'vitest';
import { _topTabsHtml, _mixPanelHtml, _mixCtaBarHtml } from '../playlist-hub.js';

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

describe('playlist-hub #1625: Mix tab Continue CTA', () => {
    it('default _mixPanelHtml keeps the standalone "Start mix" button', () => {
        const html = _mixPanelHtml();
        expect(html).toContain('id="mix-start"');
        expect(html).toContain('data-i18n="admin.mixStart"');
        // The save-as-community checkbox stays (assembly reads it).
        expect(html).toContain('id="mix-save-community"');
    });

    it('_mixPanelHtml(true) omits the "Start mix" button in the wizard', () => {
        const html = _mixPanelHtml(true);
        expect(html).not.toContain('id="mix-start"');
        expect(html).not.toContain('data-i18n="admin.mixStart"');
        // Chip cloud + save-community survive so the wizard mix still works.
        expect(html).toContain('id="mix-chip-cloud"');
        expect(html).toContain('id="mix-save-community"');
    });

    it('renders a "Weiter" mix-continue CTA (no request FAB, no count chip) when onContinue is set', () => {
        const html = _mixCtaBarHtml({ onContinue: () => {} });
        expect(html).toContain('data-plh-action="mix-continue"');
        expect(html).toContain('id="mix-continue"');
        // Reuses the list "Continue" label key/text.
        expect(html).toContain('Continue');
        // NO playlists-specific request FAB, NO selected-count chip.
        expect(html).not.toContain('data-plh-action="request-new"');
        expect(html).not.toContain('plh-cta-fab');
        expect(html).not.toContain('plh-cta-count');
    });

    it('includes a Back button only when showBack is set', () => {
        const withBack = _mixCtaBarHtml({ onContinue: () => {}, showBack: true });
        expect(withBack).toContain('data-plh-action="back"');
        const noBack = _mixCtaBarHtml({ onContinue: () => {} });
        expect(noBack).not.toContain('data-plh-action="back"');
    });

    it('is empty without an onContinue callback (standalone mount → no Mix CTA)', () => {
        expect(_mixCtaBarHtml({})).toBe('');
        expect(_mixCtaBarHtml({ showBack: true })).toBe('');
        expect(_mixCtaBarHtml()).toBe('');
    });
});
