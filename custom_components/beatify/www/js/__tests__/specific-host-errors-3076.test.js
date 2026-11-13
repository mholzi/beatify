/**
 * #3076: the host phone shows the SPECIFIC server message again.
 *
 * #3057 looked every error up as `errors.<CODE>`, which is generic by design:
 * "Need at least one connected player to start" (code GAME_NOT_STARTED) read
 * "Game has not started". The server now sends a stable `message_key` per
 * message; `errors.host.<message_key>` wins, `errors.<CODE>` is the fallback.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { errorHeadlineAndDetail, specificErrorText } from '../admin/util.js';
import { localizedErrorMessage } from '../admin/api.js';

const here = dirname(fileURLToPath(import.meta.url));
const www = join(here, '..', '..');
const LOCALES = ['en', 'de', 'es', 'fr', 'nl', 'it'];
const dict = Object.fromEntries(
    LOCALES.map((l) => [l, JSON.parse(readFileSync(join(www, 'i18n', l + '.json'), 'utf8'))]),
);

function translator(d) {
    return (key, params) => {
        const v = key.split('.').reduce((o, k) => (o ? o[k] : undefined), d);
        if (typeof v !== 'string') return key;
        return params && typeof params === 'object'
            ? v.replace(/\{([a-z_]+)\}/gi, (m, p) => (p in params ? params[p] : m))
            : v;
    };
}

const frame = {
    type: 'error',
    code: 'GAME_NOT_STARTED',
    message: 'Need at least one connected player to start',
    message_key: 'NEED_PLAYERS',
    min_players: 1,
};

describe('nobody has joined yet and the host tries to start (#3076)', () => {
    it.each(LOCALES)('%s: shows the need-players text, not the generic code text', (l) => {
        const t = translator(dict[l]);
        const shown = errorHeadlineAndDetail(frame, t, frame.message).message;
        expect(shown).toBe(dict[l].errors.host.NEED_PLAYERS);
        expect(shown).not.toBe(dict[l].errors.GAME_NOT_STARTED);
    });

    // #3386: the server's meaning plus the host's next step.
    it('English reads like the server text', () => {
        const t = translator(dict.en);
        expect(errorHeadlineAndDetail(frame, t, '').message).toBe(
            'At least one player must join before the game can start.',
        );
    });

    it('German is the translated sentence', () => {
        const t = translator(dict.de);
        expect(errorHeadlineAndDetail(frame, t, '').message).toBe(
            'Mindestens ein Spieler muss beitreten, bevor das Spiel starten kann.',
        );
    });

    it('the WS error branch goes through the same lookup', () => {
        globalThis.window = globalThis.window || globalThis;
        globalThis.window.BeatifyI18n = { t: translator(dict.de) };
        expect(localizedErrorMessage(frame)).toBe('Mindestens ein Spieler muss beitreten, bevor das Spiel starten kann.');
        delete globalThis.window.BeatifyI18n;
    });

    it('the player-side call sites pass the whole frame so the key reaches the lookup', () => {
        const rd = (f) => readFileSync(join(www, 'js', f), 'utf8');
        expect(rd('player-core.js')).toContain('joinRejectionMessage(data.code, data.message, utils.t, data)');
        expect(rd('player-end.js')).toContain("utils.t, e)");
        expect(rd('player-lobby.js')).toContain('specificErrorText(data, utils.t)');
        expect(rd('player-utils.js')).toContain('specificErrorText(data, t)');
    });
});

describe('fallbacks stay in place', () => {
    const t = translator(dict.de);

    it('a code without a message_key still gets errors.<CODE>', () => {
        const r = errorHeadlineAndDetail({ code: 'NAME_TAKEN', message: 'Name taken' }, t, '');
        expect(r.message).toBe(dict.de.errors.NAME_TAKEN);
    });

    it('an unknown message_key falls back to errors.<CODE>', () => {
        const r = errorHeadlineAndDetail(
            { code: 'GAME_NOT_STARTED', message: 'x', message_key: 'BRAND_NEW' },
            t,
            '',
        );
        expect(r.message).toBe(dict.de.errors.GAME_NOT_STARTED);
    });

    it('an unfilled placeholder falls back instead of showing {braces}', () => {
        const r = errorHeadlineAndDetail(
            { code: 'GAME_NOT_STARTED', message: 'x', message_key: 'GAME_PAUSED' },
            t,
            '',
        );
        expect(r.message).toBe(dict.de.errors.GAME_NOT_STARTED);
    });

    it('no key, no i18n: the server text', () => {
        expect(specificErrorText({ message_key: 'NEED_PLAYERS' }, null)).toBeNull();
        expect(errorHeadlineAndDetail({ message: 'Server text' }, null, '').message).toBe(
            'Server text',
        );
    });
});

describe('every locale carries every specific key', () => {
    const keys = Object.keys(dict.en.errors.host);
    it('has the keys', () => expect(keys.length).toBeGreaterThan(50));
    it.each(LOCALES)('%s has them all, with the English placeholders', (l) => {
        const host = dict[l].errors.host;
        expect(Object.keys(host).sort()).toEqual([...keys].sort());
        for (const k of keys) {
            const ph = (s) => (s.match(/\{[a-z_]+\}/g) || []).sort().join();
            expect(host[k].trim().length, l + '.' + k).toBeGreaterThan(0);
            expect(ph(host[k]), l + '.' + k).toBe(ph(dict.en.errors.host[k]));
        }
    });
});
