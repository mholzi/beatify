/**
 * #2130, second round — the game-over screen.
 *
 * The August fixes (#2133, #2157) were both scoped to
 * `#dashboard-reveal .reveal-standings-card #reveal-leaderboard`, the standings
 * on the between-rounds REVEAL screen, and they hold. What @boardnick0815
 * reported on v4.3.0 with a screencast is the GAME-OVER screen,
 * `.end-stage-layout` — a separate block that never got the #963 treatment,
 * where the failures are horizontal rather than vertical:
 *
 *   1. the winner's name broke mid-word and left the podium card,
 *   2. the award row wrote its values outside the card border,
 *   3. a two-player game showed a third, empty stand with "---" and 0 PTS.
 *
 * #2701: point 3 used to be covered by a hand-written copy of the podium loop
 * plus three greps over `dashboard.js` that existed to catch the copy drifting.
 * `renderEndView` is compiled out of the shipped file and run here instead —
 * the copy is gone, and with it the greps that guarded it.
 *
 * Points 1 and 2 are still asserted against the stylesheet text, deliberately:
 * see the second block.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { declaration, evaluate, readSource, WWW_DIR } from './helpers/js-source.js';
import { doc, el } from './helpers/mini-dom.js';

const DASHBOARD = readSource('dashboard.js');
const CSS = readFileSync(join(WWW_DIR, 'css', 'dashboard.css'), 'utf8');

/** The three podium slots plus the elements around them, as one document. */
function endScreen() {
    const places = {};
    const elements = {};
    [1, 2, 3].forEach((place) => {
        const placeEl = el(`podium-place-${place}`);
        places[place] = placeEl;
        const under = { selector: '.podium-place', node: placeEl };
        for (const part of ['name', 'score', 'avatar']) {
            elements[`end-podium-${place}-${part}`] = el(
                `end-podium-${place}-${part}`,
                { closest: under },
            );
        }
    });
    elements['end-meta-rounds'] = el('end-meta-rounds');
    elements['end-meta-players'] = el('end-meta-players');
    elements['end-leaderboard'] = el('end-leaderboard');
    return { places, elements, document: doc(elements) };
}

/** Run the shipped `renderEndView` and report what the podium ended up as. */
function renderEnd(leaderboard, { screen = endScreen(), ...extra } = {}) {
    const noop = () => {};
    evaluate(declaration(DASHBOARD, 'renderEndView', 'dashboard.js'), 'renderEndView', {
        document: screen.document,
        utils: { escapeHtml: (s) => String(s) },
        renderSuddenDeathLastStanding: noop,
        renderStatsComparison: noop,
        renderSuperlatives: noop,
        renderHighlights: noop,
        triggerConfetti: noop,
        endAvatarGradient: () => 'linear-gradient(#000,#fff)',
    })({ leaderboard, ...extra });

    const hidden = [1, 2, 3].filter((p) =>
        screen.places[p].classList.contains('podium-place--empty'));
    return { ...screen, hidden };
}

describe('#2130 — no podium stand without a player on it', () => {
    it('hides the third stand in a two-player game', () => {
        // Exactly the game in the reporter's screenshot: Sandra 162, Aaron 128.
        expect(renderEnd([
            { rank: 1, name: 'Sandra', score: 162 },
            { rank: 2, name: 'Aaron', score: 128 },
        ]).hidden).toEqual([3]);
    });

    it('hides the second and third stand in a single-player game', () => {
        expect(renderEnd([{ rank: 1, name: 'Sandra', score: 162 }]).hidden).toEqual([2, 3]);
    });

    it('hides nothing once three players are ranked', () => {
        expect(renderEnd([
            { rank: 1, name: 'Sandra', score: 162 },
            { rank: 2, name: 'Aaron', score: 128 },
            { rank: 3, name: 'Kim', score: 90 },
        ]).hidden).toEqual([]);
    });

    it('hides the stand with a class, not with `hidden`', () => {
        // `.podium-place` is display:flex, which beats the UA rule for
        // [hidden] — a stand hidden that way stays on the screen.
        const out = renderEnd([{ rank: 1, name: 'Sandra', score: 162 }]);
        expect(out.places[3].hidden).toBe(false);
        expect(out.places[3].classList.contains('podium-place--empty')).toBe(true);
    });

    it('still fills the placeholders it always filled', () => {
        // The '---' / '0' assignment predates this fix and stays: hiding the
        // stand is a display decision, not a reason to change what it holds.
        const out = renderEnd([{ rank: 1, name: 'Sandra', score: 162 }]);
        expect(out.elements['end-podium-3-name'].textContent).toBe('---');
        expect(out.elements['end-podium-3-score'].textContent).toBe('0');
        expect(out.elements['end-podium-1-name'].textContent).toBe('Sandra');
    });

    it('re-shows a stand that was empty on the previous game', () => {
        // The toggle has to run in both directions: the dashboard is a
        // long-lived page and renders one game after another into the same
        // elements. A one-way `add` would leave the third stand hidden for the
        // rest of the evening.
        const screen = endScreen();
        renderEnd([
            { rank: 1, name: 'Sandra', score: 162 },
            { rank: 2, name: 'Aaron', score: 128 },
        ], { screen });
        expect(screen.places[3].classList.contains('podium-place--empty')).toBe(true);

        const out = renderEnd([
            { rank: 1, name: 'Sandra', score: 162 },
            { rank: 2, name: 'Aaron', score: 128 },
            { rank: 3, name: 'Kim', score: 90 },
        ], { screen });
        expect(out.hidden).toEqual([]);
    });
});

describe('#2130 — the stylesheet rules the fix depends on', () => {
    /**
     * These four stay assertions on the stylesheet TEXT, and that is the
     * intended shape rather than a leftover.
     *
     * The defect here is a layout one — a name breaking mid-word, an award
     * value drawn outside its card — and reproducing it needs a layout engine.
     * The repo runs vitest in the `node` environment with no jsdom and no CSSOM,
     * so nothing in this process can compute a box. What CAN be checked is that
     * the declarations the fix consists of are still in the stylesheet the
     * browser loads, and that is what these do.
     *
     * The first of them is also the other half of the block above: the JS
     * toggles `.podium-place--empty`, and a class nothing styles hides nothing.
     */
    it('defines the empty-stand rule the toggle depends on (stylesheet guard)', () => {
        expect(CSS).toMatch(/\.end-stage-layout \.podium-place--empty \{\s*display: none;\s*\}/);
    });

    it('keeps the podium from shrinking below its stand (stylesheet guard)', () => {
        // The name broke mid-word because the place could shrink under the
        // stand's fixed 200px, not because the font was too large.
        const place = CSS.match(/\.end-stage-layout \.podium-place \{[^}]*\}/)[0];
        expect(place).toContain('flex: 0 1 200px');
        expect(place).toContain('min-width: 0');
        const name = CSS.match(/\.end-stage-layout \.podium-name \{[^}]*\}/)[0];
        expect(name).toContain('text-overflow: ellipsis');
        expect(name).toContain('white-space: nowrap');
    });

    it('keeps the award cards inside their grid track (stylesheet guard)', () => {
        const card = CSS.match(/\.end-stage-layout \.superlative-card \{[^}]*\}/)[0];
        expect(card).toContain('min-width: 0');
        expect(card).toContain('grid-template-columns: auto minmax(0, 1fr) auto');
    });
});
