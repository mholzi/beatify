/**
 * #2365 — the start-failure banner must dock above the footer, not inside it.
 *
 * Reported from a phone on v4.3.1-rc1: pressing Start with no players joined
 * rendered "Start nicht möglich" as a narrow column between the two footer
 * buttons, wrapping mid-word — `beitrete` / `n`, `scanne` / `n`.
 *
 * The banner was fine. The anchor was wrong. `showBanner` inserts its node
 * *before the anchor, inside the anchor's parent*, so anchoring on the Start
 * button placed the banner **into** `.home-cta-bar` — a flex row in which
 * `.home-cta-start` takes the free space via `flex: 1`, leaving the banner at
 * its min-content width.
 *
 * The bar for these tests: would they have failed on the evening of the
 * report? The first one would.
 */
import { describe, it, expect } from 'vitest';
import { bannerAnchorFor } from '../admin/util.js';

/** Minimal stand-in for the Start button; `closest` is the only call made. */
function startButton(barOrNull) {
    return {
        id: 'home-start-game',
        closest(selector) {
            return selector === '.home-cta-bar' ? barOrNull : null;
        },
    };
}

describe('#2365 bannerAnchorFor', () => {
    it('returns the footer row, not the button inside it', () => {
        const bar = { className: 'home-cta-bar' };
        const btn = startButton(bar);
        // The regression: this used to be the button, which put the banner in
        // the flex row and squeezed it to one character per line.
        expect(bannerAnchorFor(btn)).toBe(bar);
        expect(bannerAnchorFor(btn)).not.toBe(btn);
    });

    it('falls back to the button when the markup has no footer row', () => {
        // A banner in the wrong box still beats no banner at all.
        const btn = startButton(null);
        expect(bannerAnchorFor(btn)).toBe(btn);
    });

    it('falls back to the button when the element has no closest()', () => {
        // Older test doubles and very old engines; must not throw.
        const btn = { id: 'home-start-game' };
        expect(bannerAnchorFor(btn)).toBe(btn);
    });

    it('returns null when there is no button', () => {
        // showSetupError reads this to decide on the toast fallback, so the
        // null must survive rather than become a truthy stand-in.
        expect(bannerAnchorFor(null)).toBe(null);
        expect(bannerAnchorFor(undefined)).toBe(null);
    });
});
