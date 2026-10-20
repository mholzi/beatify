/**
 * #3222: the lobby sentence names the song length and the answer time.
 *
 * Since #3152 the host can stop the song before the round ends. The time
 * clause used to say "every song runs just N seconds" with N = the round time,
 * which was the wrong number once a sample was set — and with a sample at the
 * default 45 s round it said nothing at all, although the music stops early.
 *
 * Variant A of the design gate: one clause, two numbers.
 *  - sample set   → "you hear 15 seconds of each song and get 30 to answer",
 *                   shown even when the round time is the 45 s default
 *  - no sample    → "every song plays through the whole 30-second round",
 *                   shown only when the round time is not the default
 *  - a sample that is not shorter than the round is no sample — the same rule
 *    as `RoundManager.sample_playback_seconds()` on the server.
 */
import { describe, it, expect } from 'vitest';
import { locale } from './helpers/js-source.js';
import { translator } from './helpers/mini-dom.js';

global.window = global.window || {};
await import('../utils.js');
const U = global.window.BeatifyUtils;

const LOCALES = ['en', 'de', 'es', 'fr', 'it', 'nl'];
const T = Object.fromEntries(LOCALES.map((l) => [l, translator(locale(l)).t]));

function lobby(overrides) {
    return Object.assign(
        {
            phase: 'LOBBY',
            total_rounds: 10,
            round_duration: 45,
            sample_duration: 0,
            difficulty: 'normal',
            title_artist_mode: false,
            sudden_death_mode: false,
        },
        overrides,
    );
}

describe('the time clause with a song sample (#3222)', () => {
    it('names both numbers in English', () => {
        const brief = U.buildLobbyBrief(lobby({ round_duration: 30, sample_duration: 15 }), T.en);
        expect(brief.text).toBe('10 rounds, you hear 15 seconds of each song and get 30 to answer.');
    });

    it('names both numbers in German', () => {
        const brief = U.buildLobbyBrief(lobby({ round_duration: 30, sample_duration: 15 }), T.de);
        expect(brief.text).toBe('10 Runden, ihr hört 15 Sekunden von jedem Song und habt 30 zum Antworten.');
    });

    it('speaks up at the default 45 s round as soon as a sample is set', () => {
        expect(U.buildLobbyBrief(lobby(), T.en).text).toBe('10 rounds, standard rules.');
        const brief = U.buildLobbyBrief(lobby({ sample_duration: 10 }), T.en);
        expect(brief.text).toBe('10 rounds, you hear 10 seconds of each song and get 45 to answer.');
    });

    it('sits in the rank slot of the time clause, behind Sudden Death', () => {
        const brief = U.buildLobbyBrief(
            lobby({ sudden_death_mode: true, round_duration: 30, sample_duration: 15 }),
            T.en,
        );
        expect(brief.text).toBe(
            '10 rounds, you hear 15 seconds of each song and get 30 to answer '
            + '— and a single wrong answer knocks you out.',
        );
        expect(brief.named).toBe(2);
    });

    it('opens an uncapped sentence with a capital', () => {
        const brief = U.buildLobbyBrief(
            lobby({ max_rounds: 0, total_rounds: 266, round_duration: 30, sample_duration: 15 }),
            T.en,
        );
        expect(brief.text).toBe('You hear 15 seconds of each song and get 30 to answer.');
    });
});

describe('the time clause without a sample (#3222)', () => {
    it('says the song plays the whole round', () => {
        const brief = U.buildLobbyBrief(lobby({ round_duration: 30 }), T.en);
        expect(brief.text).toBe('10 rounds, every song plays through the whole 30-second round.');
        expect(U.buildLobbyBrief(lobby({ round_duration: 30 }), T.de).text)
            .toBe('10 Runden, jeder Song läuft die ganze Runde, 30 Sekunden lang.');
    });

    it('stays silent at the default round time, as before', () => {
        expect(U.buildLobbyBrief(lobby({ sample_duration: 0 }), T.en).text).toBe('10 rounds, standard rules.');
        expect(U.buildLobbyBrief(lobby({ sample_duration: undefined }), T.en).text).toBe('10 rounds, standard rules.');
    });
});

describe('a sample that is not shorter than the round is no sample (#3222)', () => {
    it('treats sample == round as the whole round', () => {
        const brief = U.buildLobbyBrief(lobby({ round_duration: 30, sample_duration: 30 }), T.en);
        expect(brief.text).toBe('10 rounds, every song plays through the whole 30-second round.');
    });

    it('treats sample > round as the whole round', () => {
        const brief = U.buildLobbyBrief(lobby({ round_duration: 15, sample_duration: 20 }), T.en);
        expect(brief.text).toBe('10 rounds, every song plays through the whole 15-second round.');
    });

    it('treats sample > the default round as standard rules', () => {
        // Cannot happen through the wizard, but the clause must not invent a limit.
        expect(U.buildLobbyBrief(lobby({ round_duration: 45, sample_duration: 60 }), T.en).text)
            .toBe('10 rounds, standard rules.');
    });

    it('ignores garbage', () => {
        expect(U.buildLobbyBrief(lobby({ sample_duration: 'x' }), T.en).text).toBe('10 rounds, standard rules.');
        expect(U.buildLobbyBrief(lobby({ sample_duration: -5 }), T.en).text).toBe('10 rounds, standard rules.');
    });
});

describe('every locale renders both states whole (#3222)', () => {
    const cases = {
        sample: lobby({ round_duration: 30, sample_duration: 15 }),
        sampleDefaultRound: lobby({ sample_duration: 10 }),
        whole: lobby({ round_duration: 30 }),
        sampleWithSuddenDeath: lobby({ sudden_death_mode: true, round_duration: 30, sample_duration: 15 }),
    };
    for (const lang of LOCALES) {
        for (const [name, data] of Object.entries(cases)) {
            it(`${lang} · ${name}`, () => {
                const brief = U.buildLobbyBrief(data, T[lang]);
                expect(brief).not.toBeNull();
                expect(brief.text).not.toMatch(/[{}]/);
                expect(brief.text).not.toContain('lobby.brief');
                if (name.startsWith('sample')) {
                    expect(brief.text).toMatch(name === 'sampleDefaultRound' ? /10\D+45/ : /15\D+30/);
                } else {
                    expect(brief.text).toContain('30');
                }
            });
        }
    }
});
