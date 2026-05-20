/**
 * Unit tests for playlist-generator.js pure helpers (#1052).
 * Validator must:
 *   - Catch missing required fields, wrong types, bad URI shapes.
 *   - Warn (not fail) when LLM-tell heuristics fire (same Apple ID across
 *     regions; duplicate ISRC across songs).
 *   - Accept a fully valid bundled playlist (gold-standard "Das Boot" song).
 */
import { describe, it, expect, beforeAll } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const SRC = path.resolve(__dirname, '..', 'playlist-generator.js');

let api;

beforeAll(() => {
    // The module is an IIFE that attaches window.PlaylistGenerator. Evaluate
    // it inside a fresh VM context with a stub window/document.
    const code = fs.readFileSync(SRC, 'utf8');
    const ctx = {
        window: {},
        document: { addEventListener() {}, removeEventListener() {} },
        navigator: {},
        URLSearchParams,
        URL,
    };
    vm.createContext(ctx);
    vm.runInContext(code, ctx);
    api = ctx.window.PlaylistGenerator._internals;
});

// ------------------------------------------------------------------
// Helpers to build a valid song / playlist
// ------------------------------------------------------------------

function goldSong(overrides = {}) {
    return Object.assign({
        artist: 'U96',
        title: 'Das Boot',
        year: 1991,
        isrc: 'DEPI81403435',
        uri: 'spotify:track:5A3IdgGphzKS2etiGFB73S',
        uri_apple_music: 'applemusic://track/965771834',
        uri_apple_music_by_region: {
            us: 'applemusic://track/965253291',
            de: 'applemusic://track/965253292',
            gb: 'applemusic://track/965253293',
            fr: 'applemusic://track/965253294',
            es: 'applemusic://track/965253295',
            nl: 'applemusic://track/965253296',
            it: 'applemusic://track/965253297',
        },
        uri_youtube_music: 'https://music.youtube.com/watch?v=0snTYLgg9w0',
        uri_tidal: null,
        uri_deezer: 'deezer://track/94877938',
        fun_fact: 'Trance classic from 1991.',
        fun_fact_de: 'Trance-Klassiker von 1991.',
        fun_fact_es: 'Clásico trance de 1991.',
        fun_fact_fr: 'Classique trance de 1991.',
        fun_fact_nl: 'Trance-klassieker uit 1991.',
    }, overrides);
}

function goldPlaylist(songs) {
    return {
        name: 'Trance Classics',
        version: '1.0',
        tags: ['trance', '1990s'],
        language: 'en',
        author: 'Beatify Community',
        added_date: '2026-05-18',
        description: 'Trance + hands-up classics.',
        songs: songs || [goldSong()],
    };
}

// ------------------------------------------------------------------
// validatePlaylist
// ------------------------------------------------------------------

describe('validatePlaylist', () => {
    it('accepts a fully valid playlist', () => {
        const v = api.validatePlaylist(JSON.stringify(goldPlaylist()));
        expect(v.parseError).toBeNull();
        expect(v.topErrors).toEqual([]);
        expect(v.songResults).toHaveLength(1);
        expect(v.songResults[0].errors).toEqual([]);
        expect(v.ok).toBe(true);
    });

    it('flags JSON parse errors', () => {
        const v = api.validatePlaylist('not json {');
        expect(v.parseError).toBeTruthy();
        expect(v.ok).toBe(false);
    });

    it('flags missing top-level fields', () => {
        const bad = goldPlaylist();
        delete bad.author;
        delete bad.added_date;
        const v = api.validatePlaylist(JSON.stringify(bad));
        const fields = v.topErrors.map((e) => e.field).sort();
        expect(fields).toContain('author');
        expect(fields).toContain('added_date');
        expect(v.ok).toBe(false);
    });

    it('flags wrong added_date format', () => {
        const bad = goldPlaylist();
        bad.added_date = '2026/05/18';
        const v = api.validatePlaylist(JSON.stringify(bad));
        expect(v.topErrors.find((e) => e.field === 'added_date')).toBeTruthy();
        expect(v.ok).toBe(false);
    });

    it('flags empty songs[]', () => {
        const v = api.validatePlaylist(JSON.stringify(goldPlaylist([])));
        expect(v.topErrors.find((e) => e.field === 'songs')).toBeTruthy();
        expect(v.ok).toBe(false);
    });
});

// ------------------------------------------------------------------
// validateSong (per-field)
// ------------------------------------------------------------------

describe('validateSong', () => {
    it('marks all 15 fields ok for the gold song', () => {
        const r = api.validateSong(goldSong(), 0);
        const expectedFields = [
            'artist', 'title', 'year', 'isrc', 'uri',
            'uri_apple_music', 'uri_apple_music_by_region',
            'uri_youtube_music', 'uri_tidal', 'uri_deezer',
            'fun_fact', 'fun_fact_de', 'fun_fact_es', 'fun_fact_fr', 'fun_fact_nl',
        ];
        for (const f of expectedFields) expect(r.fields[f]).toBe(true);
        expect(r.errors).toEqual([]);
    });

    it('flags bad spotify uri shape', () => {
        const r = api.validateSong(goldSong({ uri: 'spotify:track:nope' }), 0);
        expect(r.fields.uri).toBe(false);
        expect(r.errors.some((e) => e.field === 'uri')).toBe(true);
    });

    it('flags malformed apple_music id', () => {
        const r = api.validateSong(goldSong({ uri_apple_music: 'applemusic://track/' }), 0);
        expect(r.fields.uri_apple_music).toBe(false);
    });

    it('flags missing apple_music regions', () => {
        const s = goldSong();
        delete s.uri_apple_music_by_region.de;
        const r = api.validateSong(s, 0);
        expect(r.fields.uri_apple_music_by_region).toBe(false);
        expect(r.errors.find((e) => e.field === 'uri_apple_music_by_region').message).toMatch(/missing for .*de/);
    });

    it('warns when all apple regions share one ID (LLM tell)', () => {
        const s = goldSong();
        // Same ID across all regions.
        for (const k of Object.keys(s.uri_apple_music_by_region)) {
            s.uri_apple_music_by_region[k] = 'applemusic://track/111111111';
        }
        const r = api.validateSong(s, 0);
        // Still passes shape...
        expect(r.fields.uri_apple_music_by_region).toBe(true);
        expect(r.errors).toEqual([]);
        // ...but warns.
        expect(r.warnings.some((w) => w.field === 'uri_apple_music_by_region')).toBe(true);
    });

    it('accepts null uri_tidal', () => {
        const r = api.validateSong(goldSong({ uri_tidal: null }), 0);
        expect(r.fields.uri_tidal).toBe(true);
    });

    it('accepts null uri_deezer but rejects garbage', () => {
        const okR = api.validateSong(goldSong({ uri_deezer: null }), 0);
        expect(okR.fields.uri_deezer).toBe(true);
        const badR = api.validateSong(goldSong({ uri_deezer: 'http://deezer.com/track/1' }), 0);
        expect(badR.fields.uri_deezer).toBe(false);
    });

    it('rejects year out of range and non-integer', () => {
        expect(api.validateSong(goldSong({ year: 1899 }), 0).fields.year).toBe(false);
        expect(api.validateSong(goldSong({ year: 2999 }), 0).fields.year).toBe(false);
        expect(api.validateSong(goldSong({ year: '1990' }), 0).fields.year).toBe(false);
    });

    it('rejects malformed ISRC', () => {
        expect(api.validateSong(goldSong({ isrc: 'BADISRC' }), 0).fields.isrc).toBe(false);
        expect(api.validateSong(goldSong({ isrc: 'depi81403435' }), 0).fields.isrc).toBe(false); // lowercase
    });

    it('flags missing fun_fact translations', () => {
        const r = api.validateSong(goldSong({ fun_fact_de: '' }), 0);
        expect(r.fields.fun_fact_de).toBe(false);
        expect(r.errors.some((e) => e.field === 'fun_fact_de')).toBe(true);
    });
});

// ------------------------------------------------------------------
// Cross-song heuristics
// ------------------------------------------------------------------

describe('duplicate ISRC detection', () => {
    it('warns when two songs share an ISRC', () => {
        const s1 = goldSong();
        const s2 = goldSong({ artist: 'Other', title: 'Different' });
        const v = api.validatePlaylist(JSON.stringify(goldPlaylist([s1, s2])));
        const dupWarning = v.songResults[1].warnings.find((w) => w.field === 'isrc');
        expect(dupWarning).toBeTruthy();
    });
});

// ------------------------------------------------------------------
// buildPrompt
// ------------------------------------------------------------------

describe('buildPrompt', () => {
    it('includes the Spotify URL and the playlist ID when valid', () => {
        const url = 'https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=abc';
        const p = api.buildPrompt(url);
        expect(p).toContain(url);
        expect(p).toContain('37i9dQZF1DXcBWIGoYBM5M');
    });

    it('lists all 15 per-song fields', () => {
        const p = api.buildPrompt('https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M');
        for (const f of ['artist', 'title', 'year', 'isrc', 'uri', 'uri_apple_music', 'uri_apple_music_by_region', 'uri_youtube_music', 'uri_tidal', 'uri_deezer', 'fun_fact', 'fun_fact_de', 'fun_fact_es', 'fun_fact_fr', 'fun_fact_nl']) {
            expect(p).toContain(f);
        }
    });

    it('embeds the gold-standard Das Boot example', () => {
        const p = api.buildPrompt('https://open.spotify.com/playlist/x');
        expect(p).toContain('Das Boot');
        expect(p).toContain('DEPI81403435');
    });

    it('includes pre-fetched track list when provided', () => {
        const p = api.buildPrompt('x', { trackList: [{ artist: 'U96', title: 'Das Boot' }] });
        expect(p).toContain('U96 — Das Boot');
    });
});

// ------------------------------------------------------------------
// parseSpotifyPlaylistId / slugify
// ------------------------------------------------------------------

describe('parseSpotifyPlaylistId', () => {
    it('extracts the id from a canonical URL', () => {
        expect(api.parseSpotifyPlaylistId('https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M'))
            .toBe('37i9dQZF1DXcBWIGoYBM5M');
    });
    it('extracts the id from a URL with si= query', () => {
        expect(api.parseSpotifyPlaylistId('https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M?si=abc'))
            .toBe('37i9dQZF1DXcBWIGoYBM5M');
    });
    it('returns null for non-playlist URLs', () => {
        expect(api.parseSpotifyPlaylistId('https://open.spotify.com/track/x')).toBeNull();
        expect(api.parseSpotifyPlaylistId('garbage')).toBeNull();
        expect(api.parseSpotifyPlaylistId('')).toBeNull();
    });
});

describe('slugify', () => {
    it('lowercases and replaces non-alphanumerics with hyphens', () => {
        expect(api.slugify('Trance Classics!')).toBe('trance-classics');
        expect(api.slugify('70s & 80s Hits')).toBe('70s-80s-hits');
    });
    it('falls back to untitled-playlist for empty input', () => {
        expect(api.slugify('')).toBe('untitled-playlist');
        expect(api.slugify('   ')).toBe('untitled-playlist');
    });
});

// ------------------------------------------------------------------
// buildSubmitIssueUrl
// ------------------------------------------------------------------

describe('buildSubmitIssueUrl', () => {
    it('produces a github.com new-issue URL with title and label', () => {
        const url = api.buildSubmitIssueUrl(goldPlaylist());
        expect(url.startsWith('https://github.com/mholzi/beatify/issues/new?')).toBe(true);
        const qs = new URL(url).searchParams;
        expect(qs.get('title')).toContain('Trance Classics');
        expect(qs.get('labels')).toBe('community-playlist-submission');
        expect(qs.get('body')).toContain('Trance Classics');
    });
});

// ------------------------------------------------------------------
// formatValidationForLLM
// ------------------------------------------------------------------

describe('formatValidationForLLM', () => {
    it('on parse failure, returns a self-contained prompt mentioning the parser error', () => {
        const v = api.validatePlaylist('not json {');
        const out = api.formatValidationForLLM(v, 'not json {');
        expect(out).toContain('could not be parsed');
        expect(out).toContain('markdown fences');
        expect(out).toContain('schema you were originally given');
    });

    it('on a clean playlist, says no issues and embeds the original JSON', () => {
        const pl = goldPlaylist();
        const txt = JSON.stringify(pl);
        const v = api.validatePlaylist(txt);
        const out = api.formatValidationForLLM(v, txt);
        expect(out).toContain('No errors or warnings');
        expect(out).toContain('"name": "Trance Classics"');
        expect(out).toContain('```json');
    });

    it('lists each per-song error with field path, song reference, and actual value', () => {
        const bad = goldSong({
            uri_youtube_music: 'https://youtube.com/not-music',
            artist: 'Robert Miles',
            title: 'Children',
        });
        const pl = goldPlaylist([goldSong(), bad]);
        const txt = JSON.stringify(pl);
        const v = api.validatePlaylist(txt);
        const out = api.formatValidationForLLM(v, txt);
        expect(out).toContain('songs[1].uri_youtube_music');
        expect(out).toContain('Robert Miles / Children');
        expect(out).toContain('https://youtube.com/not-music');
        expect(out).toContain('## Errors');
    });

    it('lists clean song indices in a do-not-modify directive when a mix is present', () => {
        // gold song has distinct per-region Apple IDs → no warning.
        // Two copies share an ISRC → song[1] gets a duplicate-ISRC warning.
        // Song[1] also has a bad uri → an error.
        // So song[0] is fully clean; song[1] has 1 error and 1 warning.
        const clean = goldSong({ artist: 'A', title: 'B' });
        const broken = goldSong({ artist: 'C', title: 'D', uri: 'spotify:track:bad' });
        const pl = goldPlaylist([clean, broken]);
        const txt = JSON.stringify(pl);
        const v = api.validatePlaylist(txt);
        const out = api.formatValidationForLLM(v, txt);
        expect(out).toContain('## Errors');
        expect(out).toContain('## Warnings');
        expect(out).toMatch(/do not modify them.*songs\[0\]/);
    });

    it('reports "(missing)" for top-level fields that were absent', () => {
        const pl = goldPlaylist();
        delete pl.author;
        const txt = JSON.stringify(pl);
        const v = api.validatePlaylist(txt);
        const out = api.formatValidationForLLM(v, txt);
        expect(out).toContain('`author`');
        expect(out).toContain('(missing)');
    });

    it('truncates long string values in echoes', () => {
        const long = 'x'.repeat(500);
        const s = goldSong({ uri: long });
        const txt = JSON.stringify(goldPlaylist([s]));
        const v = api.validatePlaylist(txt);
        const out = api.formatValidationForLLM(v, txt);
        const lines = out.split('\n');
        const errorLine = lines.find((l) => l.includes('songs[0].uri'));
        // 500-char URI must not survive verbatim into the error line; both
        // the validator's _echo and the LLM brief's _summarizeValue cap it.
        expect(errorLine.length).toBeLessThan(400);
        expect(errorLine).toContain('…');
    });
});

// ------------------------------------------------------------------
// sanitizePlaylistText — paste-corruption auto-clean
// ------------------------------------------------------------------

describe('sanitizePlaylistText', () => {
    it('returns the input unchanged when no wrappers are present', () => {
        const txt = JSON.stringify(goldPlaylist());
        const s = api.sanitizePlaylistText(txt);
        expect(s.changes).toBe(0);
        expect(s.text).toBe(txt);
    });

    it('strips <…> Markdown autolink wrappers from uri_youtube_music', () => {
        const corrupt = goldSong({
            uri_youtube_music: '<https://music.youtube.com/watch?v=0snTYLgg9w0>',
        });
        const txt = JSON.stringify(goldPlaylist([corrupt]));
        const s = api.sanitizePlaylistText(txt);
        expect(s.changes).toBe(1);
        const cleaned = JSON.parse(s.text);
        expect(cleaned.songs[0].uri_youtube_music).toBe('https://music.youtube.com/watch?v=0snTYLgg9w0');
    });

    it('strips wrappers from all URI fields including the per-region Apple map', () => {
        const s1 = goldSong();
        s1.uri = '<spotify:track:5A3IdgGphzKS2etiGFB73S>';
        s1.uri_apple_music = '<applemusic://track/965771834>';
        s1.uri_deezer = '<deezer://track/94877938>';
        s1.uri_apple_music_by_region.de = '<applemusic://track/965771835>';
        const txt = JSON.stringify(goldPlaylist([s1]));
        const s = api.sanitizePlaylistText(txt);
        expect(s.changes).toBe(4);
        const c = JSON.parse(s.text);
        expect(c.songs[0].uri).toBe('spotify:track:5A3IdgGphzKS2etiGFB73S');
        expect(c.songs[0].uri_apple_music).toBe('applemusic://track/965771834');
        expect(c.songs[0].uri_deezer).toBe('deezer://track/94877938');
        expect(c.songs[0].uri_apple_music_by_region.de).toBe('applemusic://track/965771835');
    });

    it('does NOT strip wrappers from non-URI fields (fun_fact mentions are preserved)', () => {
        const s1 = goldSong({ fun_fact: 'A track named <Sandstorm> by Darude.' });
        const txt = JSON.stringify(goldPlaylist([s1]));
        const s = api.sanitizePlaylistText(txt);
        expect(s.changes).toBe(0);
        expect(JSON.parse(s.text).songs[0].fun_fact).toContain('<Sandstorm>');
    });

    it('reports parseError instead of throwing on invalid JSON', () => {
        const s = api.sanitizePlaylistText('{ not json');
        expect(s.parseError).toBeTruthy();
        expect(s.changes).toBe(0);
    });

    it('a sanitized corrupt playlist round-trips through validatePlaylist as ok', () => {
        const corrupt = goldSong({
            uri_youtube_music: '<https://music.youtube.com/watch?v=0snTYLgg9w0>',
            uri: '<spotify:track:5A3IdgGphzKS2etiGFB73S>',
        });
        const corruptTxt = JSON.stringify(goldPlaylist([corrupt]));
        const sanitized = api.sanitizePlaylistText(corruptTxt);
        expect(sanitized.changes).toBe(2);
        const v = api.validatePlaylist(sanitized.text);
        expect(v.ok).toBe(true);
        expect(v.songResults[0].errors).toEqual([]);
    });
});

// ------------------------------------------------------------------
// Validator error-message echoes (paste-corruption diagnostics)
// ------------------------------------------------------------------

describe('validator Got: echoes', () => {
    it('includes the bad value in uri_youtube_music errors', () => {
        const s = goldSong({ uri_youtube_music: 'https://youtube.com/notmusic' });
        const r = api.validateSong(s, 0);
        const e = r.errors.find((x) => x.field === 'uri_youtube_music');
        expect(e).toBeTruthy();
        expect(e.message).toContain('Got:');
        expect(e.message).toContain('https://youtube.com/notmusic');
    });

    it('reports "(missing)" when a uri field is undefined', () => {
        const s = goldSong();
        delete s.uri;
        const r = api.validateSong(s, 0);
        const e = r.errors.find((x) => x.field === 'uri');
        expect(e.message).toContain('Got: (missing)');
    });
});
