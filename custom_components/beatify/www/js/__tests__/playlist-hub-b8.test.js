/**
 * #1402-B8 finding 2 regression test for playlist-hub.js _t().
 *
 * _t() must fall back to the English literal when a translation is missing.
 * BeatifyI18n.t(key, params) returns the key itself when unknown, so the old
 * `if (val) return val` leaked the raw key (e.g. "playlistHub.chips.pop")
 * onto a genre chip instead of "Pop".
 */
import { describe, it, expect, afterEach } from 'vitest';
import { _t } from '../playlist-hub.js';

afterEach(() => {
    delete globalThis.window;
});

function setI18n(stub) {
    globalThis.window = { BeatifyI18n: stub };
}

describe('playlist-hub #1402-B8: _t fallback', () => {
    it('returns the fallback when no i18n is present', () => {
        globalThis.window = {};
        expect(_t('playlistHub.chips.pop', 'Pop')).toBe('Pop');
    });

    it('returns the fallback (not the raw key) when the key is MISSING', () => {
        setI18n({ t: (key) => key }); // faithful: echoes key when unknown
        const out = _t('playlistHub.chips.pop', 'Pop');
        expect(out).toBe('Pop');
        expect(out).not.toBe('playlistHub.chips.pop');
    });

    it('returns the translation when the key resolves', () => {
        setI18n({ t: (key) => (key === 'playlistHub.chips.pop' ? 'Música pop' : key) });
        expect(_t('playlistHub.chips.pop', 'Pop')).toBe('Música pop');
    });
});
