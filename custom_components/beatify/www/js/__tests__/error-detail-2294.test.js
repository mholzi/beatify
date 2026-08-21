/**
 * #2294 — a start failure must say WHICH rejection fired.
 *
 * The REST layer answers `{code, message}` and the client prefers the
 * `errors.<CODE>` translation. That is right for the headline and wrong as the
 * whole message: the create-game path returns twelve different rejections under
 * the single code INVALID_REQUEST, so the translation alone cannot distinguish
 * "no playlists selected" from "the speaker is unavailable". On 2026-08-21 that
 * cost an evening — Music Assistant had been down for five days, every speaker
 * was unavailable, and the banner said only "check your setup".
 *
 * The bar for every case below: would it have shown "Media player is
 * unavailable" that night?
 */
import { describe, it, expect } from 'vitest';
import { errorHeadlineAndDetail } from '../admin/util.js';

const DE = {
    'errors.INVALID_REQUEST': 'Diese Anfrage war ungültig. Prüfe deine Einrichtung.',
    'errors.PROVIDER_NOT_SUPPORTED': '{speaker} kann {provider} nicht abspielen.',
};

/** Stand-in for BeatifyI18n.t: returns the key itself when a string is missing. */
function t(key) {
    return Object.prototype.hasOwnProperty.call(DE, key) ? DE[key] : key;
}

describe('#2294 errorHeadlineAndDetail', () => {
    it('keeps the server reason as the detail line under the translation', () => {
        const out = errorHeadlineAndDetail(
            { code: 'INVALID_REQUEST', message: 'Media player is unavailable' }, t);
        expect(out.message).toBe(DE['errors.INVALID_REQUEST']);
        expect(out.detail).toBe('Media player is unavailable');
    });

    it('distinguishes two rejections that share the same code', () => {
        const a = errorHeadlineAndDetail(
            { code: 'INVALID_REQUEST', message: 'Media player is unavailable' }, t);
        const b = errorHeadlineAndDetail(
            { code: 'INVALID_REQUEST', message: 'No playlists selected' }, t);
        expect(a.message).toBe(b.message);      // same headline, as before
        expect(a.detail).not.toBe(b.detail);    // ...but no longer indistinguishable
    });

    it('adds no detail when the server message would repeat the headline', () => {
        const out = errorHeadlineAndDetail(
            { code: 'INVALID_REQUEST', message: DE['errors.INVALID_REQUEST'] }, t);
        expect(out.detail).toBe('');
    });

    it('falls back to the server message when the code has no translation', () => {
        const out = errorHeadlineAndDetail(
            { code: 'BRAND_NEW_CODE', message: 'Something specific went wrong' }, t);
        expect(out.message).toBe('Something specific went wrong');
        expect(out.detail).toBe('');
    });

    it('keeps the server message when the translation has unfilled placeholders', () => {
        // #1663: an older backend sends no {speaker}/{provider} details. Showing
        // the raw template would be worse than the English sentence.
        const out = errorHeadlineAndDetail(
            { code: 'PROVIDER_NOT_SUPPORTED', message: "Speaker can't play Apple Music" }, t);
        expect(out.message).toBe("Speaker can't play Apple Music");
        expect(out.detail).toBe('');
    });

    it('survives a body with no message and no code', () => {
        const out = errorHeadlineAndDetail({}, t, 'Failed to start game');
        expect(out.message).toBe('Failed to start game');
        expect(out.detail).toBe('');
    });

    it('survives a missing i18n entirely (Companion cold start)', () => {
        const out = errorHeadlineAndDetail(
            { code: 'INVALID_REQUEST', message: 'Media player is unavailable' }, null);
        expect(out.message).toBe('Media player is unavailable');
        expect(out.detail).toBe('');
    });

    it('does not let a throwing translator swallow the server message', () => {
        const boom = () => { throw new Error('i18n not initialised'); };
        const out = errorHeadlineAndDetail(
            { code: 'INVALID_REQUEST', message: 'Media player is unavailable' }, boom);
        expect(out.message).toBe('Media player is unavailable');
    });
});
