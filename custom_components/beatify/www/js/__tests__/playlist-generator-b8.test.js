/**
 * #1402-B8 regression tests for playlist-generator.js.
 *
 * Finding 2: _t() must return the English fallback (not the raw i18n key) when
 *   a translation is missing. BeatifyI18n.t(key, params) takes a PARAMS OBJECT
 *   as its second arg and returns the key itself when missing — the old code
 *   passed the fallback string as params and `if (got)` let the raw key leak.
 * Finding 5: opening the modal must clear stale per-session state
 *   (savedFilename / pendingSubmission / capturedIssueNumber) so a reopen does
 *   not render last session's "Saved as…" / submission banners.
 */
import { describe, it, expect, beforeAll } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const SRC = path.resolve(__dirname, '..', 'playlist-generator.js');

function loadWithI18n(i18nStub) {
    const code = fs.readFileSync(SRC, 'utf8');
    const win = {};
    if (i18nStub) win.BeatifyI18n = i18nStub;
    const ctx = {
        window: win,
        document: { addEventListener() {}, removeEventListener() {} },
        navigator: {},
        URLSearchParams,
        URL,
    };
    vm.createContext(ctx);
    vm.runInContext(code, ctx);
    return ctx.window.PlaylistGenerator._internals;
}

describe('playlist-generator #1402-B8 finding 2: _t fallback', () => {
    it('returns the fallback string when i18n is absent', () => {
        const api = loadWithI18n(null);
        expect(api._t('playlistGenerator.copyPrompt', 'Copy prompt')).toBe('Copy prompt');
    });

    it('returns the fallback (not the raw key) when the key is MISSING', () => {
        // A faithful BeatifyI18n.t: echoes the key back when unknown.
        const api = loadWithI18n({ t: (key) => key });
        const out = api._t('playlistGenerator.unknownKey', 'Human fallback');
        expect(out).toBe('Human fallback');
        expect(out).not.toBe('playlistGenerator.unknownKey');
    });

    it('returns the real translation when the key resolves', () => {
        const api = loadWithI18n({ t: (key) => (key === 'k.hit' ? 'Übersetzt' : key) });
        expect(api._t('k.hit', 'fallback')).toBe('Übersetzt');
    });

    it('interpolates {placeholders} into the resolved/fallback string', () => {
        const api = loadWithI18n({ t: (key) => key });
        expect(api._t('k.miss', 'Saved {n} tracks', { n: 12 })).toBe('Saved 12 tracks');
    });
});

describe('playlist-generator #1402-B8 finding 5: session reset on open', () => {
    it('_resetSessionState clears stale submission/save fields', () => {
        const api = loadWithI18n(null);
        const dirty = {
            rootEl: { some: 'node' },
            lastValidation: { ok: true },
            lastJsonText: '{"x":1}',
            guideOpen: false,
            savedFilename: 'last-session.json',
            pendingSubmission: { spotify_url: 'x' },
            capturedIssueNumber: 4242,
        };
        api._resetSessionState(dirty);
        expect(dirty.savedFilename).toBeNull();
        expect(dirty.pendingSubmission).toBeNull();
        expect(dirty.capturedIssueNumber).toBeNull();
        expect(dirty.lastValidation).toBeNull();
        expect(dirty.lastJsonText).toBe('');
        expect(dirty.guideOpen).toBe(true);
    });
});
