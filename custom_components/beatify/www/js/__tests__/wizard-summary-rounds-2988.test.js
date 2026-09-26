/**
 * #2988: the wizard's "Ready to play" summary left the round count out.
 *
 * #1475 dropped it for the "All songs" default, so with the default the host
 * could not see how long the game would run. The mode line now always carries
 * it: "10 rounds" for a cap, and for no cap the words the TV lobby uses since
 * #2958 ("All songs") — no new strings.
 */
import { describe, it, expect } from 'vitest';
import { roundsSummaryPart, doneSummaryHtml } from '../wizard.js';
import { declaration, evaluate, readSource, locale } from './helpers/js-source.js';

const LANGS = ['de', 'en', 'es', 'fr', 'it', 'nl'];
const tFor = (lang) => {
    const pack = locale(lang);
    return (key, fallback) => {
        const v = key.split('.').reduce((o, k) => (o ? o[k] : undefined), pack);
        return typeof v === 'string' ? v : fallback;
    };
};

describe('roundsSummaryPart (#2988)', () => {
    it('reads "10 rounds" for a cap', () => {
        expect(roundsSummaryPart(10, tFor('en'))).toBe('10 rounds');
        expect(roundsSummaryPart(25, tFor('de'))).toBe('25 Runden');
    });

    it.each(LANGS)('%s: no cap uses the lobby wording, never a number', (lang) => {
        const t = tFor(lang);
        const part = roundsSummaryPart(0, t);
        expect(part).toBe(locale(lang).dashboard.allSongs);
        expect(part).not.toMatch(/\d/);
    });

    it.each(LANGS)('%s: both keys exist, so no fallback English leaks in', (lang) => {
        const pack = locale(lang);
        expect(pack.wizard.summary.rounds.trim()).not.toBe('');
        expect(pack.dashboard.allSongs.trim()).not.toBe('');
    });
});

describe('the summary mode line carries the round count (#2988)', () => {
    function render(maxRounds, titleArtist = false) {
        let html = '';
        const el = { set innerHTML(v) { html = v; } };
        const t = tFor('en');
        evaluate([declaration(readSource('wizard.js'), '_renderDoneSummary', 'wizard.js')], '_renderDoneSummary', {
            document: { getElementById: (id) => (id === 'wiz-done-summary' ? el : null) },
            _speakerLabel: () => 'Kitchen',
            chosenSpeaker: 'media_player.kitchen',
            PROVIDERS: [{ id: 'spotify', label: 'Spotify' }],
            chosenProvider: 'spotify',
            chosenLevelUps: { lights: false, tts: false },
            chosenPlaylists: new Set(),
            _playlistName: (p) => p,
            chosenTitleArtistMode: titleArtist,
            chosenDifficulty: 'normal',
            chosenDuration: 45,
            chosenMaxRounds: maxRounds,
            chosenLanguage: 'en',
            _t: t,
            roundsSummaryPart,
            doneSummaryHtml,
        })();
        // #2995 splits the mode line into no-wrap segments; the text is unchanged.
        return html.replace(/<span class="wiz-done-seg">|<\/span>(?=[ <])/g, '');
    }

    it('shows "All songs" for the default', () => {
        expect(render(0)).toContain('Year mode · normal · 45s · All songs · EN');
    });

    it('shows the cap', () => {
        expect(render(10)).toContain('Year mode · normal · 45s · 10 rounds · EN');
    });

    it('also in Title & Artist mode', () => {
        expect(render(0, true)).toContain('Title &amp; Artist · 45s · All songs · EN');
    });
});
