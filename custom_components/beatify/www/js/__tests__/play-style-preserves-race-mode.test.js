/**
 * Regression: a play style must not silently drop Title & Artist / Race mode.
 * Ported from the fork by @Muggedadscher (#3557).
 *
 * The fork's core game mode (Year vs Title & Artist, with the live Race variant
 * under it) is a separate axis from the year-round bonus layer that upstream's
 * play styles (#2692) configure. But `applyPlayStyle` drives the bonus toggles
 * through `_setGameModeToggle`, and the shared precedence
 * (`applyGameModeTogglePrecedence`) turns Title & Artist OFF the moment a
 * year-round bonus (`artist`, `closest`) goes ON. The `classic` style names
 * `artist`, and step 4 now LEADS with the play-style cards — so a host who
 * picked Race mode and then tapped any play style was thrown back to guessing
 * years the moment the round started. Shipped in v4.7.0; this pins the fix.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

// wizard.js touches browser globals at import time — stub them before importing.
global.window = global.window || {
    BeatifyUtils: { t: (key) => key },
    localStorage: { getItem: () => null, setItem: () => {} },
    matchMedia: () => ({ matches: true, addEventListener: () => {} }),
    location: { search: '' },
};
global.localStorage = global.localStorage || global.window.localStorage;
global.document = global.document || {
    getElementById: () => null,
    querySelector: () => null,
    querySelectorAll: () => [],
    createElement: () => ({ classList: { add() {}, remove() {}, toggle() {} }, style: {} }),
    body: { classList: { add() {}, remove() {} } },
};

const __dirname = dirname(fileURLToPath(import.meta.url));
const WIZARD_SRC = readFileSync(join(__dirname, '..', 'wizard.js'), 'utf8');

const { PLAY_STYLES, applyGameModeTogglePrecedence } = await import('../wizard.js');

describe('the trap: a year bonus turning on clears Title & Artist', () => {
    const inTitleArtist = () => ({
        artistChallenge: false,
        movieQuiz: false,
        introMode: false,
        closestWinsMode: false,
        titleArtistMode: true,
    });

    it('artist ON drops Title & Artist (this is why a play style could break it)', () => {
        const after = applyGameModeTogglePrecedence(inTitleArtist(), 'artist', true);
        expect(after.titleArtistMode).toBe(false);
    });

    it('closest ON drops Title & Artist too', () => {
        const after = applyGameModeTogglePrecedence(inTitleArtist(), 'closest', true);
        expect(after.titleArtistMode).toBe(false);
    });

    it('the classic style names artist — so applying it hits that trap', () => {
        const classic = PLAY_STYLES.find((s) => s.key === 'classic');
        expect(classic.modes).toContain('artist');
    });
});

describe('applyPlayStyle leaves the core mode alone', () => {
    // applyPlayStyle mutates module-internal chosen* state that the module does
    // not export, so the guard is asserted on the function's own source — the
    // same idiom play-styles-2692.test.js uses for the suddenDeath carve-out.
    const fn = WIZARD_SRC.match(/export function applyPlayStyle\([\s\S]*?\n}/);

    it('the function exists', () => {
        expect(fn).not.toBeNull();
    });

    it('snapshots the core Title & Artist / Race flags before touching the modes', () => {
        const body = fn[0];
        const snapAt = body.indexOf('chosenTitleArtistMode');
        const loopAt = body.indexOf('GAME_MODES.forEach');
        expect(snapAt).toBeGreaterThan(-1);
        expect(loopAt).toBeGreaterThan(-1);
        // The read must come before the loop that flips the bonus toggles.
        expect(snapAt).toBeLessThan(loopAt);
    });

    it('restores both core flags after the mode loop', () => {
        const body = fn[0];
        const loopEnd = body.indexOf('});');
        // Assignments back onto the core flags appear after the loop closes.
        const tail = body.slice(loopEnd);
        expect(tail).toMatch(/chosenTitleArtistMode\s*=/);
        expect(tail).toMatch(/chosenTitleArtistRaceMode\s*=/);
    });
});
