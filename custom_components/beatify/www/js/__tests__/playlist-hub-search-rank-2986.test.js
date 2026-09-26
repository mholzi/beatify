/**
 * #2986: the hub's search put "70s Hits" before "80s Hits" for "80s".
 *
 * Matching was yes/no and results came out in catalogue order, so a playlist
 * whose description mentions the 80s beat the one called "80s Hits". Results
 * are now ranked: a hit in the title beats a hit elsewhere, and an exact or
 * leading title match beats one mid-title.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { searchRank, rankSearchResults, matchesSearch } from '../playlist-hub.js';
import { REPO_DIR } from './helpers/js-source.js';

const PLAYLISTS = join(REPO_DIR, 'custom_components', 'beatify', 'playlists');
const shipped = (file) => JSON.parse(readFileSync(join(PLAYLISTS, file), 'utf8'));

describe('the shipped 70s and 80s playlists (#2986)', () => {
    const seventies = shipped('70s-hits.json');
    const eighties = shipped('80er-hits.json');

    it('both still match "80s" — the bug is the order, not the filter', () => {
        expect(matchesSearch(seventies, '80s')).toBe(true);
        expect(matchesSearch(eighties, '80s')).toBe(true);
    });

    it('"80s" lists 80s Hits first, whatever the catalogue order', () => {
        const names = rankSearchResults([seventies, eighties], '80s').map((p) => p.name);
        expect(names[0]).toBe('80s Hits');
        expect(names).toContain('70s Hits');
    });

    it('"70s" lists 70s Hits first', () => {
        expect(rankSearchResults([eighties, seventies], '70s')[0].name).toBe('70s Hits');
    });
});

describe('match tiers (#2986)', () => {
    const p = (name, extra) => Object.assign({ name, tags: [], description: '' }, extra);

    it('orders exact > leading > word start > inside the title > other fields', () => {
        const list = [
            p('Rock Classics', { description: 'hits' }),     // 4: description only
            p('Megahits'),                                    // 3: inside a word
            p('Summer Hits 2024'),                            // 2: a word starts with it
            p('Hits of the Year'),                            // 1: title starts with it
            p('Hits'),                                        // 0: exact
        ];
        expect(list.map((x) => searchRank(x, 'hits'))).toEqual([4, 3, 2, 1, 0]);
        expect(rankSearchResults(list, 'hits').map((x) => x.name)).toEqual([
            'Hits', 'Hits of the Year', 'Summer Hits 2024', 'Megahits', 'Rock Classics',
        ]);
    });

    it('is case- and whitespace-insensitive', () => {
        expect(searchRank(p('80s Hits'), '  80S ')).toBe(1);
    });

    it('drops non-matches and keeps catalogue order among equals', () => {
        const list = [p('B Hits'), p('Jazz'), p('A Hits')];
        expect(rankSearchResults(list, 'hits').map((x) => x.name)).toEqual(['B Hits', 'A Hits']);
    });

    it('an empty query keeps every playlist in its order', () => {
        const list = [p('B'), p('A')];
        expect(rankSearchResults(list, '').map((x) => x.name)).toEqual(['B', 'A']);
    });
});
