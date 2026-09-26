/**
 * #2987: wizard step 3 had no "STEP 3 · PLAYLIST" eyebrow.
 *
 * Steps 1, 2 and 4 open with one; step 3 is filled edge to edge by the
 * playlist hub, which had no place for it. The hub now takes an `eyebrow`
 * mount option and renders it above its tab strip, and only the wizard passes
 * one — the admin page's hub has no steps.
 */
import { describe, it, expect, vi, afterEach } from 'vitest';
import { mount } from '../playlist-hub.js';
import { declaration, evaluate, readSource, locale } from './helpers/js-source.js';

function fakeRoot() {
    return {
        innerHTML: '',
        classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
        setAttribute() {},
        addEventListener() {},
        querySelector: () => null,
        querySelectorAll: () => [],
    };
}

afterEach(() => vi.unstubAllGlobals());

function mountHub(options) {
    vi.stubGlobal('fetch', () => Promise.reject(new Error('offline')));
    vi.stubGlobal('window', {});
    vi.stubGlobal('document', { getElementById: () => null, querySelector: () => null, querySelectorAll: () => [] });
    const root = fakeRoot();
    mount(root, Object.assign({ initialPlaylists: [] }, options));
    return root.innerHTML;
}

describe('the hub renders an eyebrow only when given one (#2987)', () => {
    it('renders the label above the tab strip', () => {
        const html = mountHub({ eyebrow: 'Step 3 · Playlist', onContinue() {} });
        const at = html.indexOf('plh-eyebrow');
        expect(at).toBeGreaterThan(-1);
        expect(html).toContain('>Step 3 · Playlist</div>');
        expect(at).toBeLessThan(html.indexOf('plh-toptabs'));
    });

    it('escapes it', () => {
        expect(mountHub({ eyebrow: '<b>x</b>' })).toContain('&lt;b&gt;x&lt;/b&gt;');
    });

    it('renders nothing extra on the admin page, which passes no eyebrow', () => {
        expect(mountHub({})).not.toContain('plh-eyebrow');
    });
});

describe('the wizard passes the step-3 eyebrow (#2987)', () => {
    it('mounts the hub with wizard.step3.eyebrow', () => {
        let options = null;
        const root = {};
        evaluate([declaration(readSource('wizard.js'), '_renderPlaylists', 'wizard.js')], '_renderPlaylists', {
            document: { getElementById: (id) => (id === 'playlist-hub-root' ? root : null) },
            _hubMounted: false,
            chosenPlaylists: new Set(),
            cachedStatus: null,
            plhMount: (r, o) => { options = o; },
            plhSetSelection() {},
            _t: (key, fallback) => (key === 'wizard.step3.eyebrow' ? 'SCHRITT 3' : fallback),
            _updateCta() {},
            _advance() {},
            _showFrame() {},
            currentStep: 3,
            window: {},
        })();
        expect(options).not.toBeNull();
        expect(options.eyebrow).toBe('SCHRITT 3');
    });

    it.each(['de', 'en', 'es', 'fr', 'it', 'nl'])('%s has wizard.step3.eyebrow', (lang) => {
        const v = locale(lang).wizard.step3.eyebrow;
        expect(typeof v).toBe('string');
        expect(v.trim()).not.toBe('');
    });
});
