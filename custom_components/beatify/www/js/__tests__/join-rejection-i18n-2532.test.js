/**
 * #2532 — a refused guest must read the rejection in their own language.
 *
 * #2511 gave the rejection a home on the join view but passed the server's own
 * ``message`` through untouched, so a German screen ("Gib deinen Namen ein",
 * "Beitreten") answered a taken name with "Name taken, choose another". The
 * translations were never missing — ``errors.NAME_TAKEN`` and its three
 * siblings exist in all six locales and were simply never looked up.
 *
 * Two things are pinned here, and the second is the one that would slip:
 *
 *   1. all four codes in JOIN_REJECTED_CODES resolve, not just the observed one;
 *   2. the fallback actually falls back. ``t('errors.' + code) || message``
 *      reads correctly and is dead code — ``t`` returns the key on a miss, and
 *      invents a title-cased string when there is no fallback, so the right-hand
 *      side is unreachable and an unknown code reaches the guest as
 *      "errors.SOMETHING".
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

global.window = global.window || {};
global.window.location = global.window.location || { search: '', href: '' };
global.window.matchMedia = global.window.matchMedia
    || (() => ({ matches: false, addEventListener: () => {} }));
global.document = global.document || { getElementById: () => null };
global.URLSearchParams = global.URLSearchParams || URLSearchParams;

const { joinRejectionMessage, JOIN_REJECTED_CODES } = await import('../player-utils.js');

const __dirname = dirname(fileURLToPath(import.meta.url));
const i18n = (lang) => JSON.parse(
    readFileSync(join(__dirname, '..', '..', 'i18n', `${lang}.json`), 'utf8'),
);
const PLAYER_CORE = readFileSync(join(__dirname, '..', 'player-core.js'), 'utf8');

const LOCALES = ['en', 'de', 'es', 'fr', 'it', 'nl'];

/** utils.t as utils.js implements it: two-arg form, explicit fallback on miss. */
function makeT(lang) {
    const dict = i18n(lang);
    return (key, fallback) => {
        const hit = key.split('.').reduce((o, k) => (o == null ? o : o[k]), dict);
        if (typeof hit === 'string') return hit;
        return typeof fallback === 'string' ? fallback : key;
    };
}

describe('#2532 — every rejection code is localized, in every locale', () => {
    it.each(LOCALES)('%s has all four codes translated', (lang) => {
        const errors = i18n(lang).errors || {};
        for (const code of JOIN_REJECTED_CODES) {
            expect(typeof errors[code], `${lang}.errors.${code}`).toBe('string');
            expect(errors[code].length).toBeGreaterThan(0);
        }
    });

    it.each(JOIN_REJECTED_CODES)('%s resolves to the German wording', (code) => {
        const out = joinRejectionMessage(code, 'Name taken, choose another', makeT('de'));
        expect(out).toBe(i18n('de').errors[code]);
        expect(out).not.toBe('Name taken, choose another');
    });

    it('gives the Spanish guest Spanish, not English', () => {
        // The exact case from the live test, in the language it was reported in.
        expect(joinRejectionMessage('NAME_TAKEN', 'Name taken, choose another', makeT('es')))
            .toBe(i18n('es').errors.NAME_TAKEN);
    });

    it('leaves English as English', () => {
        expect(joinRejectionMessage('GAME_FULL', 'Game is full', makeT('en')))
            .toBe(i18n('en').errors.GAME_FULL);
    });
});

describe('#2532 — the fallback chain actually falls back', () => {
    it('uses the server message for a code with no translation', () => {
        expect(joinRejectionMessage('SOMETHING_NEW', 'Server said no', makeT('de')))
            .toBe('Server said no');
    });

    it('never surfaces the raw key to the guest', () => {
        const out = joinRejectionMessage('SOMETHING_NEW', 'Server said no', makeT('de'));
        expect(out).not.toContain('errors.');
    });

    it('survives a missing server message', () => {
        expect(joinRejectionMessage('SOMETHING_NEW', undefined, makeT('de')))
            .toBe('Could not join');
    });

    it('survives a missing translator', () => {
        expect(joinRejectionMessage('NAME_TAKEN', 'Name taken', null)).toBe('Name taken');
    });

    it('survives a missing code', () => {
        expect(joinRejectionMessage(undefined, 'Name taken', makeT('de'))).toBe('Name taken');
    });
});

describe('#2532 — the shipped call site uses the lookup', () => {
    it('player-core.js hands the code to joinRejectionMessage', () => {
        expect(PLAYER_CORE).toContain(
            'failJoin(joinRejectionMessage(data.code, data.message, utils.t))',
        );
    });

    it('player-core.js no longer passes the raw server message', () => {
        expect(PLAYER_CORE).not.toContain("failJoin(data.message || 'Could not join')");
    });

    it('does not use the || form, which can never reach its right-hand side', () => {
        expect(PLAYER_CORE).not.toMatch(/t\('errors\.'\s*\+\s*data\.code\)\s*\|\|/);
    });
});
