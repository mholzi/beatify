/**
 * #3158 — the value line of an end-screen award card.
 *
 * TV and phone each carried a `switch (award.value_label)` over a different
 * subset of the fourteen labels scoring.py emits, so a value lost its unit on
 * one screen or both. `BeatifyUtils.awardValueText` is now the only place; the
 * texts below are what both screens render, read from the shipped locale files.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

global.window = global.window || {};
await import('../utils.js');
const U = global.window.BeatifyUtils;

const I18N = join(dirname(fileURLToPath(import.meta.url)), '..', '..', 'i18n');

function translator(locale) {
    const data = JSON.parse(readFileSync(join(I18N, locale + '.json'), 'utf8'));
    return (key) => key.split('.').reduce((node, part) => (node ? node[part] : undefined), data) || key;
}

function text(locale, value_label, value) {
    return U.awardValueText({ value, value_label }, translator(locale));
}

const EN = [
    ['avg_time', 3.2, '3.2 s avg'],
    ['streak', 5, '5 in a row'],
    ['bets', 4, '4 bets'],
    ['points', 27, '27 pts in final 3'],
    ['close_guesses', 3, '3 close guesses'],
    ['ghost_avg', 6.5, '6.5 gp per round'],
    ['eliminated', 3, '3 knocked out'],
    ['movie_bonus', 2, '2 movie songs'],
    ['intro_bonuses', 3, '3 intro bonuses'],
    ['improvement', 4.5, '+4.5 pts per round'],
    ['perfect_rounds', 2, '2 perfect rounds'],
    ['exact_titles', 3, '3 exact titles'],
    ['artists', 4, '4 artists named'],
    ['near_misses', 2, '2 near misses']
];

const DE = [
    ['avg_time', 3.2, '3.2 s durchschn.'],
    ['streak', 5, '5 in Folge'],
    ['bets', 4, '4 Wetten'],
    ['points', 27, '27 Pkt in letzten 3'],
    ['close_guesses', 3, '3 knappe Tipps'],
    ['ghost_avg', 6.5, '6.5 GP pro Runde'],
    ['eliminated', 3, '3 ausgeschieden'],
    ['movie_bonus', 2, '2 Film-Songs'],
    ['intro_bonuses', 3, '3 Intro-Boni'],
    ['improvement', 4.5, '+4.5 Pkt pro Runde'],
    ['perfect_rounds', 2, '2 perfekte Runden'],
    ['exact_titles', 3, '3 exakte Titel'],
    ['artists', 4, '4 Künstler erraten'],
    ['near_misses', 2, '2 knapp daneben']
];

describe('BeatifyUtils.awardValueText (#3158)', () => {
    it.each(EN)('en: %s', (label, value, expected) => {
        expect(text('en', label, value)).toBe(expected);
    });

    it.each(DE)('de: %s', (label, value, expected) => {
        expect(text('de', label, value)).toBe(expected);
    });

    it('covers all fourteen labels the server emits', () => {
        expect(EN.map((row) => row[0]).sort()).toEqual([
            'artists', 'avg_time', 'bets', 'close_guesses', 'eliminated',
            'exact_titles', 'ghost_avg', 'improvement', 'intro_bonuses',
            'movie_bonus', 'near_misses', 'perfect_rounds', 'points', 'streak'
        ]);
    });

    it('never leaves a raw key or a bare number for a known label', () => {
        ['en', 'de', 'es', 'fr', 'it', 'nl'].forEach((locale) => {
            EN.forEach(([label, value]) => {
                const out = text(locale, label, value);
                expect(out, locale + ' ' + label).not.toContain('superlatives.');
                expect(out.length, locale + ' ' + label).toBeGreaterThan(String(value).length + 2);
            });
        });
    });

    it('uses the singular for exactly one knocked-out player', () => {
        expect(text('en', 'eliminated', 1)).toBe('1 knocked out');
        expect(text('de', 'eliminated', 1)).toBe('1 ausgeschieden');
        expect(text('es', 'eliminated', 1)).toBe('1 eliminado');
        expect(text('fr', 'eliminated', 1)).toBe('1 éliminé');
        expect(text('it', 'eliminated', 1)).toBe('1 eliminato');
        expect(text('nl', 'eliminated', 1)).toBe('1 uitgeschakeld');
    });

    it('uses the plural for more than one knocked-out player', () => {
        expect(text('es', 'eliminated', 2)).toBe('2 eliminados');
        expect(text('fr', 'eliminated', 2)).toBe('2 éliminés');
        expect(text('it', 'eliminated', 2)).toBe('2 eliminati');
    });

    it('leads the improvement with a plus sign in every locale', () => {
        expect(text('es', 'improvement', 4.5)).toBe('+4.5 pts por ronda');
        expect(text('fr', 'improvement', 4.5)).toBe('+4.5 pts par manche');
        expect(text('it', 'improvement', 4.5)).toBe('+4.5 punti per turno');
        expect(text('nl', 'improvement', 4.5)).toBe('+4.5 pt per ronde');
    });

    it('puts the plus sign on the improvement only', () => {
        EN.filter((row) => row[0] !== 'improvement').forEach(([label, value]) => {
            expect(text('en', label, value)).not.toContain('+');
        });
    });

    it('separates the seconds from the number', () => {
        expect(text('fr', 'avg_time', 2.8)).toBe('2.8 s moyenne');
        expect(text('nl', 'avg_time', 2.8)).toBe('2.8 s gem.');
    });

    it('shows the number alone for a label it does not know', () => {
        expect(U.awardValueText({ value: 7, value_label: 'something_new' })).toBe('7');
    });

    it('falls back to the shared t() when no translator is passed', () => {
        // No BeatifyI18n in this environment: t() derives a readable fallback.
        expect(U.awardValueText({ value: 2, value_label: 'bets' })).toBe('2 Bets');
    });
});
