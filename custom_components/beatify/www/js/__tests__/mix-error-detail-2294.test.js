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
 *
 * #2701: the rendering rule used to be checked by slicing `showMixError` out of
 * `mix.js` and grepping the slice for `createElement('span')`. The function is
 * compiled and run here instead, against a document that records what it was
 * asked to create — so the assertion is about the element that reaches the
 * page, and a rewrite that produces the same element keeps passing.
 */
import { describe, it, expect } from 'vitest';
import { errorHeadlineAndDetail } from '../admin/util.js';
import { declaration, evaluate, readSource } from './helpers/js-source.js';
import { doc, el } from './helpers/mini-dom.js';

const MIX = readSource('admin/sections/mix.js');
// The element itself is written by the Mix tab's own template.
const HUB = readSource('playlist-hub.js');

const DE = { 'errors.INVALID_REQUEST': 'Diese Anfrage war ungültig. Prüfe deine Einrichtung.' };
const t = (key) => (Object.prototype.hasOwnProperty.call(DE, key) ? DE[key] : key);

/** Run the shipped `showMixError` and report what it put on the page. */
function showError(msg, detail) {
    const box = el('mix-error');
    box.classList.add('hidden');
    const document = doc({ 'mix-error': box });
    evaluate(declaration(MIX, 'showMixError', 'mix.js'), 'showMixError', { document })(msg, detail);
    return { box, detail: box.appended[0] || null };
}

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
});

describe('#2294 how the mix error is drawn', () => {
    it('shows the headline and reveals the box', () => {
        const { box } = showError('Failed to assemble mix.', '');
        expect(box.textContent).toBe('Failed to assemble mix.');
        expect(box.classList.contains('hidden')).toBe(false);
    });

    it('adds the server reason as a second line', () => {
        const { detail } = showError(
            DE['errors.INVALID_REQUEST'], 'No songs match the selected tags');
        expect(detail.textContent).toBe('No songs match the selected tags');
        expect(detail.className).toBe('mix-error-detail');
    });

    it('makes that second line an inline element, because #mix-error is a <p>', () => {
        // A <div> inside a <p> is closed by the parser, which would drop the
        // detail out of the error element entirely.
        expect(HUB).toMatch(/<p[^>]*\bid="mix-error"/);
        const { detail } = showError('Headline', 'The reason from the server');
        expect(detail.tagName).toBe('SPAN');
    });

    it('renders no detail when it would only repeat the headline', () => {
        expect(showError('Same text', 'Same text').detail).toBeNull();
    });

    it('renders no detail when there is none', () => {
        expect(showError('Headline', '').detail).toBeNull();
        expect(showError('Headline', undefined).detail).toBeNull();
    });
});
