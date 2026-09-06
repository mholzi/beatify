/**
 * #2620 — the host's setup line must not be half-translated.
 *
 * It read "🔊 Wohnzimmer · 3 playlists · normal · 45s · DE · ⏭️ Off": the
 * speaker name and the duration came through i18n, everything else was an
 * English literal in `admin.js`, and this is the line a host reads every single
 * time they set up a game.
 *
 * The guard is a translator that wraps every resolved key in «…». Anything that
 * reaches the screen without passing through it is then visible as bare Latin
 * text — so a literal creeping back in fails here, whatever it says. Asserting
 * the current English wording instead would go green the moment someone adds a
 * fourth literal, which is exactly what happened.
 */
import { describe, it, expect } from 'vitest';

import { buildHomeMeta, playlistDisplayName, tr } from '../admin/util.js';
import { speakerLabelFor } from '../admin/setup-sync.js';

/** Marks every translated fragment, so untranslated ones stand out. */
const t = (key, _fallback, params) => {
    const suffix = params ? `(${Object.values(params).join(',')})` : '';
    return `«${key}${suffix}»`;
};

const BASE = {
    speakerLabel: '🔊 Wohnzimmer',
    playlists: [],
    isLibrary: false,
    difficulty: 'normal',
    roundDurationLabel: '45s',
    language: 'de',
    revealAutoAdvance: 0,
};

/**
 * Everything the line shows that is neither translated nor legitimately
 * untranslatable.
 *
 * Three fragments are proper nouns or codes and must stay as they are: the
 * speaker label (resolved by the caller, see the separate block below), the
 * duration ("45s") and the language code ("DE"). Everything else — "playlists",
 * "normal", "Off", "no playlist" — is a word a German host should not be
 * reading in English.
 */
function untranslatedWords(line) {
    const [, ...rest] = line.split('·');
    return rest
        .map((part) => part.trim())
        .flatMap((part) => part.split(/\s+/))
        .filter((word) => /[A-Za-z]/.test(word))
        .filter((word) => !word.startsWith('«'))
        .filter((word) => !/^\d+s$/.test(word))
        .filter((word) => !/^[A-Z]{2}$/.test(word));
}

describe('every word of the setup line comes from i18n', () => {
    it('leaves nothing untranslated when no playlist is picked', () => {
        const line = buildHomeMeta({ ...BASE }, t);
        expect(untranslatedWords(line)).toEqual([]);
    });

    it('leaves nothing untranslated for several playlists', () => {
        const line = buildHomeMeta({ ...BASE, playlists: ['a.json', 'b.json', 'c.json'] }, t);
        expect(untranslatedWords(line)).toEqual([]);
    });

    it('leaves nothing untranslated with auto-advance on', () => {
        const line = buildHomeMeta({ ...BASE, revealAutoAdvance: 60 }, t);
        expect(untranslatedWords(line)).toEqual([]);
    });

    it('leaves nothing untranslated for the Crate Digger library setup', () => {
        const line = buildHomeMeta({ ...BASE, isLibrary: true }, t);
        expect(untranslatedWords(line)).toEqual([]);
    });

    it('leaves nothing untranslated for each difficulty', () => {
        for (const difficulty of ['easy', 'normal', 'hard']) {
            expect(untranslatedWords(buildHomeMeta({ ...BASE, difficulty }, t))).toEqual([]);
        }
    });
});

describe('the fragments say the right thing', () => {
    it('passes the playlist count into the translation', () => {
        const line = buildHomeMeta({ ...BASE, playlists: ['a', 'b', 'c'] }, t);
        expect(line).toContain('«admin.home.playlistCount(3)»');
    });

    it('shows a single playlist by name rather than as a count', () => {
        const line = buildHomeMeta({ ...BASE, playlists: [{ path: 'party/80s-classics.json' }] }, t);
        expect(line).toContain('80s classics');
    });

    it('accepts both stored playlist shapes', () => {
        expect(playlistDisplayName('party/80s-classics.json')).toBe('80s classics');
        expect(playlistDisplayName({ path: 'party/80s-classics.json' })).toBe('80s classics');
    });

    it('names the Crate Digger library instead of reporting no playlist', () => {
        // The library provider generates its playlist at game start, so it
        // legitimately has none selected — "no playlist" would misreport a
        // fully configured setup.
        const line = buildHomeMeta({ ...BASE, isLibrary: true }, t);
        expect(line).toContain('«admin.home.libraryPlaylistLabel»');
        expect(line).not.toContain('«admin.home.noPlaylist»');
    });

    it('names the chosen difficulty rather than echoing the raw value', () => {
        expect(buildHomeMeta({ ...BASE, difficulty: 'hard' }, t)).toContain('«admin.hard»');
    });

    it('falls back to the default difficulty for an unknown value', () => {
        expect(buildHomeMeta({ ...BASE, difficulty: 'brutal' }, t)).toContain('«admin.normal»');
    });

    it('shows a rejected auto-advance value as Off, not as itself', () => {
        // A stored 120 is not a delay the server runs (#2626), so the line must
        // not promise it.
        const line = buildHomeMeta({ ...BASE, revealAutoAdvance: 120 }, t);
        expect(line).toContain('«admin.revealAdvanceOff»');
        expect(line).not.toContain('120');
    });

    it('keeps the delay in seconds when it is one the server runs', () => {
        expect(buildHomeMeta({ ...BASE, revealAutoAdvance: 90 }, t)).toContain('90s');
    });

    it('still renders with an empty settings blob', () => {
        const line = buildHomeMeta({
            speakerLabel: '🔊 x',
            roundDurationLabel: '45s',
        }, t);
        expect(untranslatedWords(line)).toEqual([]);
    });
});

describe('the speaker fragment (#2620)', () => {
    it('translates the "no speaker" case', () => {
        expect(speakerLabelFor('', [], t)).toBe('🔊 «admin.home.noSpeaker»');
        expect(speakerLabelFor(null, undefined, t)).toBe('🔊 «admin.home.noSpeaker»');
    });

    it('leaves a real speaker name alone — it is a proper noun', () => {
        const players = [{ entity_id: 'media_player.esszimmer', friendly_name: 'Esszimmer' }];
        expect(speakerLabelFor('media_player.esszimmer', players, t)).toBe('🔊 Esszimmer');
    });

    it('still works without a translator, for callers that have none', () => {
        expect(speakerLabelFor('', [])).toBe('🔊 no speaker');
    });
});

describe('the real tr() interpolates the fallback too', () => {
    it('does not leave a raw {count} on screen when i18n is unavailable', () => {
        // The fallback path runs before BeatifyI18n has loaded, which is
        // precisely when a host sees this line for the first time.
        delete globalThis.window;
        expect(tr('admin.home.playlistCount', '{count} playlists', { count: 4 }))
            .toBe('4 playlists');
    });
});
