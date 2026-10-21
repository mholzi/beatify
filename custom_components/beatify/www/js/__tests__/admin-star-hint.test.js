/**
 * GitHub star hint under "Start New Game" on the host end screen.
 *
 * Shown from the third finished game on this device, each game counted once
 * by its game_id (a reload of the same END screen must not count again),
 * hidden for good once dismissed, and never shown when storage throws.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import {
    noteFinishedGame, dismissStarHint,
    STAR_HINT_GAMES_KEY, STAR_HINT_DISMISSED_KEY,
} from '../admin/star-hint.js';

function memoryStorage() {
    const data = new Map();
    return {
        data,
        getItem: (k) => (data.has(k) ? data.get(k) : null),
        setItem: (k, v) => { data.set(k, String(v)); },
    };
}

const throwingStorage = {
    getItem() { throw new Error('SecurityError'); },
    setItem() { throw new Error('SecurityError'); },
};

let store;
beforeEach(() => { store = memoryStorage(); });

describe('star hint counting', () => {
    it('stays hidden for the first two games and shows from the third', () => {
        expect(noteFinishedGame('g1', store)).toBe(false);
        expect(noteFinishedGame('g2', store)).toBe(false);
        expect(noteFinishedGame('g3', store)).toBe(true);
        expect(noteFinishedGame('g4', store)).toBe(true);
    });

    it('counts a re-rendered END screen of the same game only once', () => {
        noteFinishedGame('g1', store);
        noteFinishedGame('g1', store);
        noteFinishedGame('g2', store);
        expect(noteFinishedGame('g2', store)).toBe(false);
        expect(JSON.parse(store.getItem(STAR_HINT_GAMES_KEY))).toEqual({ count: 2, last: 'g2' });
    });

    it('does not count an END state without a game_id', () => {
        noteFinishedGame(undefined, store);
        noteFinishedGame(null, store);
        expect(store.getItem(STAR_HINT_GAMES_KEY)).toBeNull();
    });

    it('starts over from a corrupt stored value', () => {
        store.setItem(STAR_HINT_GAMES_KEY, '{not json');
        expect(noteFinishedGame('g1', store)).toBe(false);
        expect(JSON.parse(store.getItem(STAR_HINT_GAMES_KEY))).toEqual({ count: 1, last: 'g1' });
    });
});

describe('star hint dismiss', () => {
    it('hides the hint for good on this device', () => {
        ['g1', 'g2', 'g3'].forEach((id) => noteFinishedGame(id, store));
        dismissStarHint(store);
        expect(store.getItem(STAR_HINT_DISMISSED_KEY)).toBe('1');
        expect(noteFinishedGame('g4', store)).toBe(false);
    });
});

describe('star hint without storage', () => {
    it('stays hidden and does not throw when storage throws', () => {
        expect(noteFinishedGame('g1', throwingStorage)).toBe(false);
        expect(() => dismissStarHint(throwingStorage)).not.toThrow();
    });
});

describe('star hint markup', () => {
    const here = dirname(fileURLToPath(import.meta.url));
    const html = readFileSync(join(here, '..', '..', 'admin.html'), 'utf8');

    it('sits in the host end section, hidden by default, with a safe GitHub link', () => {
        const end = html.slice(html.indexOf('id="admin-end-section"'));
        const hint = end.slice(end.indexOf('id="admin-star-hint"'), end.indexOf('</p>', end.indexOf('id="admin-star-hint"')));
        expect(end.indexOf('id="admin-star-hint"')).toBeGreaterThan(end.indexOf('id="admin-new-game"'));
        expect(hint).toMatch(/\bhidden\b/);
        expect(hint).toContain('href="https://github.com/mholzi/beatify"');
        expect(hint).toContain('target="_blank"');
        expect(hint).toContain('rel="noopener"');
        expect(hint).toContain('data-i18n-aria-label="admin.starHintDismiss"');
    });
});
