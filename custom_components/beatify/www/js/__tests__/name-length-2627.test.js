/**
 * #2627 — one name cap has to reach every surface that enforces one.
 *
 * `const.py` defines it and `game/player_registry.py` enforces it, but four
 * other places carried the number 20 by hand: `player-utils.js`, two
 * `name.length > 20` checks behind the admin join button, and a
 * `maxlength="20"` on each of the two name fields. Raising the cap server-side
 * would have left a Join button disabled for names the server accepts, and two
 * input fields silently truncating before the request was ever made.
 *
 * These tests are written against MAX_NAME_LENGTH rather than against 20, so
 * they keep testing the rule after the number changes. Changing the number
 * *without* changing every surface is what `game-constants-mirror.test.js` and
 * the boundary cases below are for.
 */
import { describe, it, expect, vi } from 'vitest';

import { MAX_NAME_LENGTH } from '../game-constants.js';
import { adminJoinNameValid } from '../admin/util.js';

// player-utils.js touches window/document at module load; the vitest env is
// `node`, so the same minimal stubs join-button-reset-2506.test.js uses.
const joinBtn = { id: 'join-btn', disabled: true, textContent: 'Join Game' };
const nameInput = { id: 'name-input', value: '', focus: vi.fn() };

global.window = {
    BeatifyUtils: {
        // The one string these tests care about; everything else echoes its key.
        t: (key) => (key === 'errors.nameTooLong'
            ? 'Name too long (max {max} characters)'
            : key),
        showView: () => {},
    },
    location: { search: '' },
    matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
    addEventListener: () => {},
};
global.document = {
    body: { classList: { toggle() {}, add() {}, remove() {} } },
    getElementById: (id) => {
        if (id === 'join-btn') return joinBtn;
        if (id === 'name-input') return nameInput;
        return null;
    },
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener: () => {},
};
global.URLSearchParams = URLSearchParams;

const { validateName, applyNameLengthCap, showView } = await import('../player-utils.js');

const atLimit = 'a'.repeat(MAX_NAME_LENGTH);
const overLimit = 'a'.repeat(MAX_NAME_LENGTH + 1);

describe('the admin join button follows the shared cap', () => {
    it('accepts a name of exactly the maximum length', () => {
        expect(adminJoinNameValid(atLimit)).toBe(true);
    });

    it('rejects one character more', () => {
        expect(adminJoinNameValid(overLimit)).toBe(false);
    });

    it('rejects an empty or whitespace-only name', () => {
        for (const empty of ['', '   ', '\t', null, undefined]) {
            expect(adminJoinNameValid(empty)).toBe(false);
        }
    });

    it('measures the trimmed name, like the server does', () => {
        expect(adminJoinNameValid(`  ${atLimit}  `)).toBe(true);
    });
});

describe('the player join form follows the same cap', () => {
    it('accepts a name of exactly the maximum length', () => {
        expect(validateName(atLimit).valid).toBe(true);
    });

    it('rejects one character more, and says the limit out loud', () => {
        const result = validateName(overLimit);
        expect(result.valid).toBe(false);
        // The message quotes the live cap, so raising it fixes the wording too.
        expect(result.error).toContain(String(MAX_NAME_LENGTH));
    });

    it('agrees with the admin button on every boundary', () => {
        // The two used to be independent implementations of the same rule.
        for (const name of ['', ' ', 'a', atLimit, overLimit, `  ${atLimit}  `]) {
            expect(validateName(name).valid).toBe(adminJoinNameValid(name));
        }
    });
});

describe('the name field is capped from the constant, not from markup', () => {
    it('stamps the cap onto an input', () => {
        // player.html / admin.html no longer ship `maxlength="20"` — a number
        // there could not be reached by a server-side change (#2627).
        const input = {};
        applyNameLengthCap(input);
        expect(input.maxLength).toBe(MAX_NAME_LENGTH);
    });

    it('does nothing when the field is absent', () => {
        expect(() => applyNameLengthCap(null)).not.toThrow();
    });

    it('caps the field whenever the join view is shown', () => {
        // This is the wiring the removed attribute used to stand in for: every
        // route into the join view goes through showView (#2506).
        nameInput.maxLength = undefined;
        showView('join-view');
        expect(nameInput.maxLength).toBe(MAX_NAME_LENGTH);
    });
});
