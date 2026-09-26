/**
 * #3004: the wizard's "ready" summary showed English in every language —
 * "3 picked · 80s Hits + more" for the playlists and "lights" / "voice" /
 * "none" for the atmosphere, built as literals in `_renderDoneSummary`. The
 * difficulty on the mode line was the raw id ("easy" on a German card).
 *
 * Runs the shipped `_renderDoneSummary` against each shipped locale.
 */
import { describe, it, expect } from 'vitest';
import { roundsSummaryPart, doneSummaryHtml } from '../wizard.js';
import { declaration, evaluate, readSource, locale } from './helpers/js-source.js';
import { translator } from './helpers/mini-dom.js';

const LANGS = ['de', 'en', 'es', 'fr', 'it', 'nl'];

/** `_t(key, fallback, params)` over a real locale, like wizard.js's own. */
function tFor(lang) {
    const { t } = translator(locale(lang));
    return (key, fallback, params) => {
        const out = t(key, params || fallback);
        return out === key ? fallback : out;
    };
}

function render(lang, { playlists = ['80s Hits', 'Rock'], lights = true, tts = true, difficulty = 'easy' } = {}) {
    let html = '';
    const el = { set innerHTML(v) { html = v; } };
    evaluate([declaration(readSource('wizard.js'), '_renderDoneSummary', 'wizard.js')], '_renderDoneSummary', {
        document: { getElementById: (id) => (id === 'wiz-done-summary' ? el : null) },
        _speakerLabel: () => 'Esszimmer',
        chosenSpeaker: 'media_player.esszimmer',
        PROVIDERS: [{ id: 'apple_music', label: 'Apple Music' }],
        chosenProvider: 'apple_music',
        chosenLevelUps: { lights, tts },
        chosenPlaylists: new Set(playlists),
        _playlistName: (p) => p,
        chosenTitleArtistMode: false,
        chosenDifficulty: difficulty,
        chosenDuration: 15,
        chosenMaxRounds: 20,
        chosenLanguage: lang,
        _t: tFor(lang),
        roundsSummaryPart,
        doneSummaryHtml,
    })();
    // Value of each line, keyed by its label; mode segments joined back up.
    const values = {};
    for (const m of html.matchAll(/<span>([^<]*)<\/span><strong>([\s\S]*?)<\/strong>/g)) {
        values[m[1]] = m[2].replace(/<[^>]+>/g, '').replace(/\s+/g, ' ').trim();
    }
    return values;
}

describe('#3004 the ready summary is translated', () => {
    it('English reads as before, with the step names for the level-ups', () => {
        const v = render('en');
        expect(v.Playlist).toBe('2 picked · 80s Hits + more');
        expect(v.Atmosphere).toBe('Party lights + Voice announcements');
        expect(render('en', { lights: false, tts: false }).Atmosphere).toBe('none');
        expect(v.Mode).toContain('Year mode · Easy · 15s · 20 rounds · EN');
    });

    it('German shows the values from the live test in German', () => {
        const v = render('de', { playlists: ['80s Hits', 'Rock', 'Pop'], tts: false, difficulty: 'normal' });
        expect(v.Playlist).toBe('3 gewählt · 80s Hits + weitere');
        expect(v['Atmosphäre']).toBe('Party-Licht');
        expect(render('de', { lights: false, tts: false })['Atmosphäre']).toBe('keine');
    });

    it.each(LANGS)('%s: every value comes from the locale file', (lang) => {
        const pack = locale(lang);
        const s = pack.wizard.summary;
        const v = render(lang);
        expect(v[s.playlist]).toBe(s.playlistsPicked.replace('{n}', '2').replace('{first}', '80s Hits'));
        expect(v[s.atmosphere]).toBe(`${pack.wizard.step5.lights.title} + ${pack.wizard.step5.tts.title}`);
        expect(render(lang, { lights: false, tts: false })[s.atmosphere]).toBe(s.atmosphereNone);
        expect(v[s.mode]).toContain(` · ${pack.wizard.step4.easy} · `);
    });

    it.each(LANGS.filter((l) => l !== 'en'))('%s: no English literal is left on the card', (lang) => {
        const text = Object.values(render(lang)).join(' | ') + ' | '
            + Object.values(render(lang, { lights: false, tts: false })).join(' | ');
        expect(text).not.toMatch(/\bpicked\b|\+ more\b|\blights\b|\bvoice\b|\bnone\b|\beasy\b/);
    });

    it.each(LANGS)('%s: the new keys keep their placeholders', (lang) => {
        const s = locale(lang).wizard.summary;
        expect(s.playlistsPicked).toContain('{n}');
        expect(s.playlistsPicked).toContain('{first}');
        expect(s.atmosphereNone.trim()).not.toBe('');
    });
});
