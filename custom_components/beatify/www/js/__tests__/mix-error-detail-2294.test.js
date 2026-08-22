/**
 * #2294 — the Mix tab was the last place that threw the server's reason away.
 *
 * Both mix paths (preview and assemble) preferred the `errors.<CODE>`
 * translation over the backend `message`. `errors.INVALID_REQUEST` is one
 * string shared by every rejection, so a failed mix could not say whether no
 * tags matched, the provider was wrong, or the speaker was gone.
 *
 * These cover the decision (via the shared helper) and the rendering rule that
 * is specific to this surface: #mix-error is a <p>, so the detail must be a
 * <span> — a block child would close the paragraph.
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, it, expect } from 'vitest';
import { errorHeadlineAndDetail } from '../admin/util.js';

const DE = { 'errors.INVALID_REQUEST': 'Diese Anfrage war ungültig. Prüfe deine Einrichtung.' };
const t = (key) => (Object.prototype.hasOwnProperty.call(DE, key) ? DE[key] : key);

describe('#2294 mix errors keep the server reason', () => {
    it('separates two mix rejections that share INVALID_REQUEST', () => {
        const a = errorHeadlineAndDetail(
            { code: 'INVALID_REQUEST', message: 'No songs match the selected tags' }, t);
        const b = errorHeadlineAndDetail(
            { code: 'INVALID_REQUEST', message: 'Media player is unavailable' }, t);
        expect(a.message).toBe(DE['errors.INVALID_REQUEST']);
        expect(a.detail).toBe('No songs match the selected tags');
        expect(b.detail).toBe('Media player is unavailable');
    });

    it('falls back to the mix-specific default when the body carries nothing', () => {
        const out = errorHeadlineAndDetail({}, t, 'Failed to assemble mix.');
        expect(out.message).toBe('Failed to assemble mix.');
        expect(out.detail).toBe('');
    });

    it('uses a span for the detail, because #mix-error is a <p>', () => {
        // A <div> inside a <p> is closed by the parser, which would drop the
        // detail out of the error element entirely.
        const src = readMixSource();
        const fn = src.slice(src.indexOf('function showMixError'));
        const body = fn.slice(0, fn.indexOf('\n}'));
        expect(body).toContain("createElement('span')");
        expect(body).not.toContain("createElement('div')");
    });

    it('renders no detail when it would only repeat the headline', () => {
        const src = readMixSource();
        const fn = src.slice(src.indexOf('function showMixError'));
        const body = fn.slice(0, fn.indexOf('\n}'));
        expect(body).toContain('detail !== msg');
    });
});

function readMixSource() {
    const here = fileURLToPath(import.meta.url);
    return readFileSync(here.replace(/__tests__.*/, 'admin/sections/mix.js'), 'utf8');
}
