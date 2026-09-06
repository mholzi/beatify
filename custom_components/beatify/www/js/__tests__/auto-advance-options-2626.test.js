/**
 * #2626 — the reveal auto-advance delays the UI offers must be delays the
 * server actually runs.
 *
 * The list lived in three places: the create-game handler's literal tuple, the
 * wizard's `AUTO_ADVANCE_OPTIONS`, and four hand-written chips in admin.html.
 * The failure mode was silent by construction: a value the server does not know
 * is replaced by 0, so a chip added to either UI list stayed highlighted while
 * the game ran with auto-advance off, and the host found out at the first
 * reveal with no error anywhere.
 *
 * These tests read back what each surface OFFERS and check the normalizer — the
 * client-side twin of the server's rule — accepts every one of them unchanged.
 * That stays meaningful when the list is edited: adding 15s to const.py and to
 * nothing else fails the mirror test; adding it to one UI only cannot happen
 * any more, because neither UI has a list of its own to add it to.
 */
import { describe, it, expect, beforeEach } from 'vitest';

import {
    REVEAL_AUTO_ADVANCE_OPTIONS,
    normalizeRevealAutoAdvance,
    autoAdvanceChipLabel,
} from '../game-constants.js';

// game-settings.js pulls in siblings that read `window` at module load.
globalThis.window = globalThis;
const store = {};
globalThis.localStorage = {
    getItem: (k) => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v); },
    removeItem: (k) => { delete store[k]; },
};

const { autoAdvanceChipsHtml } = await import('../admin/sections/game-settings.js');
const { AUTO_ADVANCE_OPTIONS: WIZARD_OPTIONS } = await import('../wizard.js');

/** A translator that makes an untranslated fragment obvious. */
const t = (key, fallback) => (key ? `«${key}»` : fallback);

/** The delays a chip group actually offers, read back out of its markup. */
function offeredDelays(html) {
    return [...html.matchAll(/data-reveal-advance="(-?\d+)"/g)].map((m) => Number(m[1]));
}

describe('the admin chip group offers exactly the delays the server accepts', () => {
    it('offers every allowed delay and nothing else', () => {
        expect(offeredDelays(autoAdvanceChipsHtml(0, t))).toEqual(REVEAL_AUTO_ADVANCE_OPTIONS);
    });

    it('survives a round trip through the normalizer — no chip becomes Off', () => {
        // The regression in one line: tapping a chip must produce the delay the
        // chip promises, not a silent 0.
        for (const seconds of offeredDelays(autoAdvanceChipsHtml(0, t))) {
            expect(normalizeRevealAutoAdvance(String(seconds))).toBe(seconds);
        }
    });

    it('marks exactly the selected chip as pressed', () => {
        const html = autoAdvanceChipsHtml(REVEAL_AUTO_ADVANCE_OPTIONS[2], t);
        const pressed = [...html.matchAll(/aria-pressed="(\w+)"\s+data-reveal-advance="(\d+)"/g)]
            .filter(([, state]) => state === 'true')
            .map(([, , seconds]) => Number(seconds));
        expect(pressed).toEqual([REVEAL_AUTO_ADVANCE_OPTIONS[2]]);
    });

    it('falls back to Off when the stored value is one the server would reject', () => {
        // A settings blob written by an older build, or by another device.
        const html = autoAdvanceChipsHtml(120, t);
        expect(html).toContain('aria-pressed="true" data-reveal-advance="0"');
    });

    it('leaves no English literal in the group', () => {
        // With this translator every translated fragment is «…»-wrapped, so any
        // bare letter left over is a hard-coded label (#2620's failure mode,
        // guarded here because the chips are now built in JS).
        const labels = [...autoAdvanceChipsHtml(0, t).matchAll(/>([^<]*)</g)]
            .map(([, text]) => text)
            .filter(Boolean);
        for (const label of labels) {
            expect(label).toMatch(/^(«[\w.]+»|\d+s)$/);
        }
    });
});

describe('the wizard offers the same delays', () => {
    it('derives its chips from the shared list', () => {
        expect(WIZARD_OPTIONS.map((o) => o.id)).toEqual(REVEAL_AUTO_ADVANCE_OPTIONS);
    });

    it('gives every chip something to render', () => {
        for (const option of WIZARD_OPTIONS) {
            expect(option.label || option.labelFallback).toBeTruthy();
        }
    });

    it('routes "off" through i18n and the numeric delays through neither', () => {
        // "30s" reads the same in every locale Beatify ships; "Off" does not.
        const off = WIZARD_OPTIONS.find((o) => o.id === 0);
        expect(off.labelKey).toBeTruthy();
        for (const option of WIZARD_OPTIONS.filter((o) => o.id > 0)) {
            expect(option.labelKey).toBeUndefined();
            expect(option.label).toBe(`${option.id}s`);
        }
    });

    it('shares the "off" key with the admin chip group', () => {
        expect(WIZARD_OPTIONS.find((o) => o.id === 0).labelKey)
            .toBe(autoAdvanceChipLabel(0).key);
    });
});

describe('normalizeRevealAutoAdvance mirrors the server fallback', () => {
    beforeEach(() => {
        for (const k of Object.keys(store)) delete store[k];
    });

    it('turns anything outside the list into Off', () => {
        for (const bad of [15, 120, -30, 45.5, 'soon', null, undefined, NaN, {}]) {
            expect(normalizeRevealAutoAdvance(bad)).toBe(0);
        }
    });

    it('accepts the numeric and the string form of every allowed delay', () => {
        for (const seconds of REVEAL_AUTO_ADVANCE_OPTIONS) {
            expect(normalizeRevealAutoAdvance(seconds)).toBe(seconds);
            expect(normalizeRevealAutoAdvance(`${seconds}`)).toBe(seconds);
        }
    });
});
