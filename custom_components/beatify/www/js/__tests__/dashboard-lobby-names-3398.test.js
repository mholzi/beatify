/**
 * #3398 - the TV lobby cut "QA-Tester" to "QA-Te…" although the screen had
 * room. A tile is only as wide as its column, so the wall now steps down to
 * fewer, wider columns when a name would not fit. The shipped function is
 * compiled out of dashboard.js (see helpers/js-source.js).
 */
import { describe, it, expect } from 'vitest';
import { declaration, evaluate, readSource } from './helpers/js-source.js';

const DASHBOARD = readSource('dashboard.js');
const lobbyWallColumns = evaluate(declaration(DASHBOARD, 'lobbyWallColumns', 'dashboard.js'), 'lobbyWallColumns');

describe('lobbyWallColumns (#3398)', () => {
    it('keeps the count-based steps for short names', () => {
        expect(lobbyWallColumns(3, ['Anna', 'Max'])).toBe(3);
        expect(lobbyWallColumns(8, ['Anna'])).toBe(4);
        expect(lobbyWallColumns(14, ['Anna'])).toBe(5);
        expect(lobbyWallColumns(2)).toBe(3);
    });

    it('gives a long name a wider column instead of an ellipsis', () => {
        expect(lobbyWallColumns(4, ['QA-Tester', 'Anna'])).toBe(2);
        expect(lobbyWallColumns(8, ['QA-Tester'])).toBe(2);
    });

    it('never goes below three columns on a busy wall', () => {
        expect(lobbyWallColumns(14, ['A-very-long-name-indeed'])).toBe(3);
    });
});
