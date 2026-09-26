/**
 * #2959: the TV lobby's name wall and the join address.
 *
 * The lobby used to show the joined players as four small chips at the right
 * edge, with the rest of that half empty, and the join URL wrapped wherever
 * its box ran out — in the middle of the game ID. These tests pin the two
 * mechanical rules the redesign rests on (column steps, the URL break) and
 * the markup it replaced.
 */
import { describe, it, expect } from 'vitest';
import { declaration, evaluate, locale, readSource } from './helpers/js-source.js';

const SRC = readSource('dashboard.js');
const HTML = readSource('../dashboard.html');
const CSS = readSource('../css/dashboard.css');
const LOCALES = ['en', 'de', 'es', 'fr', 'it', 'nl'];

const lobbyWallColumns = evaluate(declaration(SRC, 'lobbyWallColumns', 'dashboard.js'), 'lobbyWallColumns');
const splitJoinUrl = evaluate(declaration(SRC, 'splitJoinUrl', 'dashboard.js'), 'splitJoinUrl');

describe('name wall columns grow with the player count (#2959)', () => {
    it('3 columns up to 6 players, 4 from 7, 5 from 13', () => {
        expect([0, 1, 4, 6].map(lobbyWallColumns)).toEqual([3, 3, 3, 3]);
        expect([7, 9, 12].map(lobbyWallColumns)).toEqual([4, 4, 4]);
        expect([13, 20, 40].map(lobbyWallColumns)).toEqual([5, 5, 5]);
    });

    it('every column step has a grid rule in dashboard.css', () => {
        expect(CSS).toMatch(/\.dashboard-player-list \{[^}]*repeat\(3, minmax\(0, 1fr\)\)/);
        expect(CSS).toMatch(/\.dashboard-player-list\[data-cols="4"\] \{[^}]*repeat\(4,/);
        expect(CSS).toMatch(/\.dashboard-player-list\[data-cols="5"\] \{[^}]*repeat\(5,/);
    });
});

describe('the join address breaks before game=, never inside the ID (#2959)', () => {
    it('drops the protocol and splits in front of game=', () => {
        expect(splitJoinUrl('http://homeassistant.local:8123/beatify/play?game=pjdG4N362V0')).toEqual({
            head: 'homeassistant.local:8123/beatify/play?',
            id: 'game=pjdG4N362V0',
        });
        expect(splitJoinUrl('https://ha.example.com/beatify/play?game=abc').head).toBe(
            'ha.example.com/beatify/play?',
        );
    });

    it('keeps a URL without game= on one line', () => {
        expect(splitJoinUrl('http://ha.local:8123/beatify/play')).toEqual({
            head: 'ha.local:8123/beatify/play',
            id: '',
        });
        expect(splitJoinUrl(null)).toEqual({ head: '', id: '' });
    });

    it('the ID line cannot wrap', () => {
        expect(CSS).toMatch(/\.dashboard-join-url \.join-url-id \{[^}]*white-space: nowrap/);
        // The old rule broke anywhere, which is what split the ID.
        expect(CSS).not.toMatch(/\.dashboard-join-url \{[^}]*word-break: break-all/);
    });
});

describe('the lobby markup (#2959)', () => {
    it('drops the "Players" heading and the "N players joined" line', () => {
        expect(HTML).not.toContain('id="dashboard-player-count"');
        expect(HTML).not.toContain('class="players-title"');
        expect(HTML).toContain('id="dashboard-players-in"');
    });

    it('has the new strings in every locale', () => {
        for (const l of LOCALES) {
            const lobby = locale(l).lobby;
            expect(lobby.playersIn, l).toContain('{n}');
            expect(lobby.playersInOne, l).toContain('{n}');
            expect(lobby.waitingForMore, l).toBeTypeOf('string');
            expect(lobby.waitingForMore.length, l).toBeGreaterThan(3);
        }
    });

    it('builds the tiles from text, not from interpolated HTML', () => {
        const fn = declaration(SRC, 'buildPlayerTile', 'dashboard.js');
        expect(fn).toContain('textContent = name');
        expect(fn).not.toContain('innerHTML');
    });
});
