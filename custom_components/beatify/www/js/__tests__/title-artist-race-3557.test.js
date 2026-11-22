/**
 * #3557: Title & Artist Race mode on the frontend (ported from the fork by
 * @Muggedadscher).
 *
 * Covers the pieces that decide what the room sees:
 * - the shared race chips + live feed (utils.js, used by the phone AND the TV),
 *   in particular that a correct guess whose text the server withheld reads
 *   "found the title" and never an empty quote,
 * - the guesser's own line after an attempt (player-game.js),
 * - the round verdict on the reveal, which used to read "Nailed it!" on a
 *   0-point Title & Artist round (player-reveal.js),
 * - the lobby sentence and the wizard's scoring summary.
 */
import { describe, it, expect } from 'vitest';
import { declaration, evaluate, locale, readSource } from './helpers/js-source.js';
import { translator } from './helpers/mini-dom.js';

global.window = global.window || {};
await import('../utils.js');
const U = global.window.BeatifyUtils;

const LOCALES = ['en', 'de', 'es', 'fr', 'it', 'nl'];
const T = Object.fromEntries(LOCALES.map((l) => [l, translator(locale(l)).t]));
const EN = T.en;

describe('race feed (utils.raceFeedHtml)', () => {
    it('renders newest first', () => {
        const html = U.raceFeedHtml([
            { player: 'Anna', field: 'title', guess: 'first', correct: false },
            { player: 'Ben', field: 'artist', guess: 'second', correct: false },
        ]);
        expect(html.indexOf('second')).toBeLessThan(html.indexOf('first'));
    });

    it('says "found the title" for a correct guess the server withheld', () => {
        const html = U.raceFeedHtml([{ player: 'Anna', field: 'title', guess: null, correct: true }]);
        expect(html).toContain('is-correct');
        expect(html).toContain('found the title');
        expect(html).not.toContain('“”');
    });

    it('says "found the artist" for the artist field', () => {
        const html = U.raceFeedHtml([{ player: 'Ben', field: 'artist', guess: null, correct: true }]);
        expect(html).toContain('found the artist');
    });

    it('shows the text of a correct guess once the server sends it (REVEAL)', () => {
        const html = U.raceFeedHtml([{ player: 'Anna', field: 'title', guess: 'Yesterday', correct: true }]);
        expect(html).toContain('Yesterday');
    });

    it('escapes player names and guesses', () => {
        const html = U.raceFeedHtml([
            { player: '<b>x</b>', field: 'title', guess: '<img src=x onerror=alert(1)>', correct: false },
        ]);
        expect(html).not.toContain('<img');
        expect(html).not.toContain('<b>x</b>');
        expect(html).toContain('&lt;img');
    });

    it('is empty for an empty or missing feed', () => {
        expect(U.raceFeedHtml([])).toBe('');
        expect(U.raceFeedHtml(undefined)).toBe('');
    });
});

describe('race chips (utils.raceChipsHtml)', () => {
    it('marks a solved field with its winner and leaves the other open', () => {
        const html = U.raceChipsHtml({
            title_solved: true, title_winner: 'Anna',
            artist_solved: false, artist_winner: null,
        });
        expect(html).toMatch(/ta-race-chip is-solved" data-field="title"/);
        expect(html).toContain('🏆 Anna');
        expect(html).toMatch(/ta-race-chip" data-field="artist"/);
        expect(html).toContain('open');
    });

    it('escapes the winner name', () => {
        const html = U.raceChipsHtml({ title_solved: true, title_winner: '<script>' });
        expect(html).not.toContain('<script>');
    });
});

describe("the guesser's own line (raceAckText)", () => {
    const raceAckText = evaluate(
        [declaration(readSource('player-game.js'), 'raceAckText', 'player-game.js')],
        'raceAckText',
    );

    it('celebrates a won field', () => {
        expect(raceAckText({ won_title: true }, EN)).toBe('You got the title! 🏆');
        expect(raceAckText({ won_artist: true }, EN)).toBe('You got the artist! 🏆');
        expect(raceAckText({ won_title: true, won_artist: true }, EN)).toBe('You got both! 🏆');
    });

    it('says "someone was faster" for a correct guess on a field already won', () => {
        expect(raceAckText({ title_status: 'correct', artist_status: 'skipped' }, EN))
            .toBe('Right, but someone was faster!');
    });

    it('says "keep guessing" for a miss, near misses included', () => {
        expect(raceAckText({ title_status: 'wrong', artist_status: 'skipped' }, EN))
            .toBe('Not quite, keep guessing!');
    });

    it('has a translation in every locale', () => {
        for (const lang of LOCALES) {
            const text = raceAckText({ won_title: true }, T[lang]);
            expect(text, lang).not.toContain('titleArtist.');
        }
    });
});

describe('reveal verdict (titleArtistVerdict)', () => {
    const src = readSource('player-reveal.js');
    function verdictFor(ta, name) {
        return evaluate(
            [
                declaration(src, '_taVerdictForCount', 'player-reveal.js'),
                declaration(src, '_taOwnVerdict', 'player-reveal.js'),
                declaration(src, 'titleArtistVerdict', 'player-reveal.js'),
            ],
            'titleArtistVerdict',
            { utils: { t: EN } },
        )(ta, name);
    }

    it('counts the fields a racer won first', () => {
        const ta = { race: { title_winner: 'Anna', artist_winner: 'Ben' } };
        expect(verdictFor(ta, 'Anna').tier).toBe('partial');
        expect(verdictFor({ race: { title_winner: 'Anna', artist_winner: 'Anna' } }, 'Anna').tier).toBe('win');
        expect(verdictFor(ta, 'Cleo').tier).toBe('miss');
    });

    it('is "Not this time" for a 0-point one-shot round, not "Nailed it!"', () => {
        const ta = {
            results: [{ player: 'Anna', title_status: 'wrong', artist_status: 'skipped' }],
            voting_open: false,
        };
        const v = verdictFor(ta, 'Anna');
        expect(v.tier).toBe('miss');
        expect(v.text).toBe('Not this time');
    });

    it('still waits for the room while a near miss is being voted on', () => {
        const ta = {
            results: [{ player: 'Anna', title_status: 'near_miss', artist_status: 'exact' }],
            voting_open: true,
        };
        expect(verdictFor(ta, 'Anna').tier).toBe('pending');
    });

    it('returns null without a payload', () => {
        expect(verdictFor(null, 'Anna')).toBeNull();
    });
});

describe('lobby sentence names the race', () => {
    const lobby = (overrides) => Object.assign({
        phase: 'LOBBY', total_rounds: 10, round_duration: 45, difficulty: 'normal',
        title_artist_mode: true, title_artist_race_mode: true,
    }, overrides);

    it('uses the race clause in place of the plain Title & Artist one', () => {
        const brief = U.buildLobbyBrief(lobby(), EN);
        expect(brief.text).toContain('first right guess wins');
        expect(brief.text).not.toContain('instead of the year');
    });

    it('ignores a race flag without Title & Artist', () => {
        const brief = U.buildLobbyBrief(lobby({ title_artist_mode: false }), EN);
        expect(brief.text).not.toContain('first right guess wins');
    });

    it('renders a whole sentence in every locale', () => {
        const rendered = LOCALES.map((l) => U.buildLobbyBrief(lobby(), T[l]).text);
        rendered.forEach((text) => {
            expect(text).not.toMatch(/[{}]/);
            expect(text).not.toContain('lobby.brief');
        });
        expect(new Set(rendered).size).toBe(LOCALES.length);
    });
});

describe('wizard scoring summary', async () => {
    // wizard.js touches browser globals at import time.
    global.document = global.document || {
        getElementById: () => null,
        querySelector: () => null,
        querySelectorAll: () => [],
        createElement: () => ({ classList: { add() {}, remove() {}, toggle() {} }, style: {} }),
        body: { classList: { add() {}, remove() {} } },
    };
    const { difficultyDisplayFor } = await import('../wizard.js');

    it('shows the race scoring in race mode', () => {
        expect(difficultyDisplayFor(true, true)).toEqual({
            showChips: false,
            summaryKey: 'wizard.step4.taRaceScoring',
        });
    });

    it('keeps the year chips in Year mode even with a stored race flag', () => {
        expect(difficultyDisplayFor(false, true)).toEqual({ showChips: true, summaryKey: null });
    });
});
