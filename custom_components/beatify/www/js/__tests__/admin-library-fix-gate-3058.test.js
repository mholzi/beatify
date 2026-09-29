/**
 * #3058: the host's "Wrong year? Fix it" button belongs to My Music (library)
 * songs only. It used to show whenever a title had been cached, i.e. for every
 * provider, and the dialog then failed with "Lookup failed." (404: the song is
 * in no pool).
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { isLibrarySong } from '../admin/util.js';

describe('isLibrarySong (#3058)', () => {
    it('is true for a library URI (PLAYING admin_song)', () => {
        expect(isLibrarySong({ year: 1986, uri_ma_library: 'library://track/1' })).toBe(true);
    });
    it('is true for the REVEAL is_library flag', () => {
        expect(isLibrarySong({ uri_ma_library: null, is_library: true, year: 1986 })).toBe(true);
    });
    it('is false for a Spotify/Apple Music/Alexa song that has a title', () => {
        expect(isLibrarySong({ year: 1986, uri_ma_library: null, title: 'Song' })).toBe(false);
        expect(isLibrarySong({ year: 1986 })).toBe(false);
    });
    it('is false for no song', () => {
        expect(isLibrarySong(null)).toBe(false);
        expect(isLibrarySong(undefined)).toBe(false);
    });
});

describe('admin.js wiring', () => {
    const src = readFileSync(
        join(dirname(fileURLToPath(import.meta.url)), '..', 'admin.js'), 'utf8');
    const fn = src.slice(src.indexOf('function _renderLibraryFixButton('));
    const body = fn.slice(0, fn.indexOf('\n}\n'));

    it('the button is gated on isLibrarySong, not on a cached title', () => {
        expect(body).toContain('isLibrarySong(adminSong)');
        expect(body).not.toContain('haveName');
    });
    it('the REVEAL call marks the song as library', () => {
        expect(src).toContain('is_library: true, year: data.song.year');
    });
});
