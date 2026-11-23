/**
 * #3582: the one shared translation helper `tr(key, fallback, params)`.
 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { tr, interpolate } from '../translate.js';

const DICT = {
    en: { 'a.hit': 'Hit EN', 'a.onlyEn': 'Only English {n}', 'a.count': '{count} guests' },
    de: { 'a.hit': 'Treffer DE', 'a.count': '{count} Gäste' },
};

/** A BeatifyI18n stand-in with the real contract: current language, English fallback, key on miss. */
function makeI18n(lang) {
    return {
        t(key, params) {
            let v = DICT[lang][key];
            if (v === undefined && lang !== 'en') v = DICT.en[key];
            if (v === undefined) return key;
            if (params) {
                Object.keys(params).forEach((p) => {
                    v = v.replace(new RegExp('\\{' + p + '\\}', 'g'), params[p]);
                });
            }
            return v;
        },
    };
}

describe('shared translation helper (#3582)', () => {
    beforeEach(() => { global.window = { BeatifyI18n: makeI18n('de') }; });
    afterEach(() => { delete global.window; });

    it('returns the translation on a key hit', () => {
        expect(tr('a.hit', 'fallback')).toBe('Treffer DE');
    });

    it('falls back to English when the current language lacks the key', () => {
        expect(tr('a.onlyEn', 'fallback', { n: 3 })).toBe('Only English 3');
    });

    it('returns the explicit fallback for a missing key, never the raw key', () => {
        expect(tr('a.missing', 'Fallback text')).toBe('Fallback text');
    });

    it('returns the fallback when the translation is empty', () => {
        global.window.BeatifyI18n = { t: () => '' };
        expect(tr('a.hit', 'Fallback text')).toBe('Fallback text');
    });

    it('interpolates params into the translation', () => {
        expect(tr('a.count', '{count} guests', { count: 4 })).toBe('4 Gäste');
    });

    it('interpolates params into the fallback too', () => {
        expect(tr('a.missing', '{count} guests', { count: 4 })).toBe('4 guests');
        expect(tr('a.missing', 'Saved {n} tracks', { n: 12 })).toBe('Saved 12 tracks');
    });

    it('leaves a fallback without params untouched', () => {
        expect(tr('a.missing', 'Max {max} characters')).toBe('Max {max} characters');
    });

    it('uses the fallback when BeatifyI18n is absent or has no t()', () => {
        global.window = {};
        expect(tr('a.hit', 'Fallback text')).toBe('Fallback text');
        global.window = { BeatifyI18n: {} };
        expect(tr('a.hit', 'Fallback text')).toBe('Fallback text');
    });

    it('asks BeatifyUtils.t when BeatifyI18n is missing', () => {
        global.window = { BeatifyUtils: { t: (k, p) => (k === 'a.hit' ? 'Utils ' + (p ? p.n : '') : k) } };
        expect(tr('a.hit', 'Fallback text', { n: 2 })).toBe('Utils 2');
        expect(tr('a.missing', 'Fallback {n}', { n: 2 })).toBe('Fallback 2');
        global.window = { BeatifyI18n: {}, BeatifyUtils: { t: () => 'Via utils' } };
        expect(tr('a.hit', 'Fallback text')).toBe('Via utils');
    });

    it('does not consult BeatifyUtils when BeatifyI18n answers or misses', () => {
        global.window = { BeatifyI18n: makeI18n('de'), BeatifyUtils: { t: () => 'Via utils' } };
        expect(tr('a.hit', 'Fallback text')).toBe('Treffer DE');
        expect(tr('a.missing', 'Fallback text')).toBe('Fallback text');
    });

    it('uses the fallback when BeatifyI18n.t throws', () => {
        global.window = { BeatifyI18n: { t() { throw new Error('not ready'); } } };
        expect(tr('a.hit', 'Fallback text')).toBe('Fallback text');
    });

    it('works without a window at all', () => {
        delete global.window;
        expect(tr('a.hit', 'Fallback text')).toBe('Fallback text');
    });

    it('returns an undefined fallback as is', () => {
        expect(tr('a.missing')).toBeUndefined();
    });

    it('interpolate passes non-strings and missing params through', () => {
        expect(interpolate(undefined, { a: 1 })).toBeUndefined();
        expect(interpolate('x {a}', null)).toBe('x {a}');
        expect(interpolate('x {a} {a}', { a: 1 })).toBe('x 1 1');
    });
});
