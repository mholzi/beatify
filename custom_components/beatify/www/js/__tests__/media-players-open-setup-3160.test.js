/**
 * #3160 — openSpeakerSetup() is the destination of the "Select Speaker" button
 * in the start-game error banner (#2269).
 *
 * The first version expanded and scrolled to `#media-players`, but the banner
 * only shows after a start from the home view, where
 * `body.home-mode #media-players { display: none !important }` hides that
 * section: the tap did nothing. The action must leave the home view and open
 * wizard step 1, like "edit setup". The old test used fake nodes and could not
 * see the CSS, so this one asserts the calls that actually change the surface.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

let calls;

beforeEach(() => {
    calls = [];
    globalThis.window = globalThis;
    globalThis.BeatifyUtils = { escapeHtml: (s) => String(s) };
    globalThis.BeatifyI18n = { t: (k) => k };
    globalThis.document = {
        getElementById: () => null,
        querySelectorAll: () => [],
        querySelector: () => null,
    };
    window.BeatifyHome = { exit: () => calls.push('home.exit') };
    window.BeatifyWizard = { show: (step) => calls.push(`wizard.show(${step})`) };
});

afterEach(() => {
    delete globalThis.window;
    delete globalThis.document;
    delete globalThis.BeatifyUtils;
    delete globalThis.BeatifyI18n;
    vi.restoreAllMocks();
});

describe('openSpeakerSetup (#3160)', () => {
    it('leaves the home view first, then opens wizard step 1', async () => {
        const mp = await import('../admin/sections/media-players.js');
        mp.openSpeakerSetup();
        expect(calls).toEqual(['home.exit', 'wizard.show(1)']);
    });

    it('does not throw when the wizard or home view is not available', async () => {
        delete window.BeatifyHome;
        delete window.BeatifyWizard;
        const mp = await import('../admin/sections/media-players.js');
        expect(() => mp.openSpeakerSetup()).not.toThrow();
    });
});
