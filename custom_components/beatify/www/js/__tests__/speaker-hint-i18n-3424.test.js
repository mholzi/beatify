/**
 * #3424: the hint under the speaker list ("Tidal and Deezer require a Music
 * Assistant speaker") was built from English fragments in every language.
 * Runs the shipped `providerHintText` against real locale files.
 */
import { describe, it, expect } from 'vitest';
import { declaration, evaluate, readSource, locale } from './helpers/js-source.js';
import { translator } from './helpers/mini-dom.js';

const SRC = readSource('admin/sections/media-players.js');

function hintFor(lang, maLabels, amazon = false) {
    const { t } = translator(locale(lang));
    const tr = (key, fallback, params) => {
        const out = t(key, params);
        return out === key ? fallback : out;
    };
    const fn = evaluate(
        [
            declaration(SRC, 'formatNameList', 'media-players.js'),
            declaration(SRC, 'providerHintText', 'media-players.js'),
        ],
        'providerHintText',
        { tr, Intl, window: { BeatifyI18n: { getLanguage: () => lang } } },
    );
    return fn(maLabels, amazon);
}

describe('#3424 speaker hint is translated', () => {
    it('English: singular and plural agree with the verb', () => {
        expect(hintFor('en', ['Tidal'])).toBe('Tidal requires a Music Assistant speaker');
        expect(hintFor('en', ['Tidal', 'Deezer'])).toBe('Tidal and Deezer require a Music Assistant speaker');
        expect(hintFor('en', ['A', 'B', 'C'])).toBe('A, B, and C require a Music Assistant speaker');
    });

    it('German: own sentence, German "und"', () => {
        expect(hintFor('de', ['Tidal'])).toBe('Tidal braucht einen Music-Assistant-Lautsprecher');
        expect(hintFor('de', ['Tidal', 'Deezer'])).toBe('Tidal und Deezer brauchen einen Music-Assistant-Lautsprecher');
    });

    it('the Amazon Music sentence is translated and joined with a dot', () => {
        expect(hintFor('de', ['Tidal'], true)).toBe(
            'Tidal braucht einen Music-Assistant-Lautsprecher · Amazon Music braucht einen Amazon Echo (alexa_media)');
        expect(hintFor('en', [], true)).toBe('Amazon Music requires an Amazon Echo (alexa_media)');
    });

    it('nothing to say gives an empty string', () => {
        expect(hintFor('en', [])).toBe('');
    });

    it('no shipped locale reads English except en', () => {
        for (const lang of ['de', 'es', 'fr', 'it', 'nl']) {
            const text = hintFor(lang, ['Tidal', 'Deezer']);
            expect(text, lang).not.toMatch(/ require/);
            expect(text, lang).not.toContain('{services}');
        }
    });
});
