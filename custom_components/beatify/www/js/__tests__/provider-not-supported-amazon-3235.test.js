/**
 * #3235 — a speaker that can't play Amazon Music is told to pick an Echo.
 *
 * errors.PROVIDER_NOT_SUPPORTED ends with "Switch to a Music Assistant
 * speaker." That is wrong for Amazon Music, which is not on Music Assistant and
 * only plays on an Amazon Echo. The server tags that refusal with
 * message_key PROVIDER_NOT_SUPPORTED_AMAZON; the client resolves it under
 * errors.host.* like every other #3076 key. Other providers keep the old text.
 */
import { describe, it, expect } from 'vitest';
import { locale } from './helpers/js-source.js';
import { errorHeadlineAndDetail, speakerRejectedText } from '../admin/util.js';

function i18n(lang) {
    const dict = locale(lang);
    return (key, params) => {
        const v = key.split('.').reduce((o, k) => (o && typeof o === 'object' ? o[k] : undefined), dict);
        if (typeof v !== 'string') return key;
        return v.replace(/\{(\w+)\}/g, (m, n) => (params && params[n] != null ? String(params[n]) : m));
    };
}

const AMAZON = {
    code: 'PROVIDER_NOT_SUPPORTED',
    error: 'PROVIDER_NOT_SUPPORTED',
    message_key: 'PROVIDER_NOT_SUPPORTED_AMAZON',
    message: 'Amazon Music is not supported on this speaker. Use an Amazon Echo (alexa_media).',
    speaker: 'Küche',
    provider: 'Amazon Music',
    provider_id: 'amazon_music',
    media_player: 'media_player.wohnzimmer',
    current_speaker: 'Wohnzimmer',
};

const APPLE = {
    ...AMAZON,
    message_key: undefined,
    message: 'Apple Music is not supported on this speaker. Use Music Assistant.',
    provider: 'Apple Music',
    provider_id: 'apple_music',
};

describe('#3235 Amazon Music refusal points to an Echo', () => {
    it('start error in English', () => {
        const out = errorHeadlineAndDetail(AMAZON, i18n('en'));
        expect(out.message).toBe("Küche can't play Amazon Music. Choose an Amazon Echo as the speaker.");
        expect(out.message).not.toMatch(/Music Assistant/);
    });

    it('start error in German', () => {
        const out = errorHeadlineAndDetail(AMAZON, i18n('de'));
        expect(out.message).toBe('Küche kann Amazon Music nicht abspielen. Wähle einen Amazon Echo als Lautsprecher.');
    });

    it('lobby banner (#3223) in English and German', () => {
        expect(speakerRejectedText(AMAZON, [], i18n('en')).message).toBe(
            "Küche can't play Amazon Music. Choose an Amazon Echo as the speaker. The game stays on Wohnzimmer.");
        expect(speakerRejectedText(AMAZON, [], i18n('de')).message).toBe(
            'Küche kann Amazon Music nicht abspielen. Wähle einen Amazon Echo als Lautsprecher. '
            + 'Das Spiel bleibt auf Wohnzimmer.');
    });

    it('other providers keep the Music Assistant advice', () => {
        expect(errorHeadlineAndDetail(APPLE, i18n('en')).message).toBe(
            "Küche can't play Apple Music. Switch to a Music Assistant speaker.");
        expect(errorHeadlineAndDetail(APPLE, i18n('de')).message).toBe(
            'Küche kann Apple Music nicht abspielen. Wechsle zu einem Music-Assistant-Lautsprecher.');
    });

    it('the key exists in all six languages with the {speaker} placeholder', () => {
        for (const lang of ['en', 'de', 'es', 'fr', 'it', 'nl']) {
            const v = locale(lang).errors.host.PROVIDER_NOT_SUPPORTED_AMAZON;
            expect(v, lang).toMatch(/\{speaker\}/);
            expect(v, lang).toMatch(/Amazon Echo/);
        }
    });
});
