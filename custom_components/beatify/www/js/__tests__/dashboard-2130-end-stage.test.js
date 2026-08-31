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
 * dashboard.js is a DOM-coupled IIFE with no exported helpers and the vitest
 * env is `node` with no jsdom, so — as in dashboard-b8.test.js and
 * dashboard-sd-ending.test.js — the load-bearing LOGIC is asserted against a
 * verbatim copy. Unlike those files the copy is not kept in sync by hand: the
 * source guards below read dashboard.js and dashboard.css from disk and fail if
 * the shipped code stops carrying the fix.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const JS = readFileSync(join(__dirname, '..', 'dashboard.js'), 'utf8');
const CSS = readFileSync(join(__dirname, '..', '..', 'css', 'dashboard.css'), 'utf8');

/**
 * Minimal stand-in for one podium slot. `closest` walks to the place element
 * exactly as the browser would; `classList.toggle(name, force)` keeps the
 * two-argument form the fix relies on.
 */
function makePodium(place) {
    const classes = new Set(['podium-place', `podium-${place}`]);
    const placeEl = {
        classList: {
            toggle: (name, force) => (force ? classes.add(name) : classes.delete(name)),
            contains: (name) => classes.has(name),
        },
    };
    const child = () => ({ textContent: '', style: {}, closest: (sel) => (sel === '.podium-place' ? placeEl : null) });
    return { placeEl, nameEl: child(), scoreEl: child(), avatarEl: child() };
}

/** Verbatim copy of the per-place body of renderEndView(). */
function renderPlace(slot, player) {
    const { nameEl, scoreEl, avatarEl } = slot;
    if (nameEl) nameEl.textContent = player ? player.name : '---';
    if (scoreEl) scoreEl.textContent = player ? player.score : '0';

    let placeEl = (nameEl || scoreEl || avatarEl);
    placeEl = placeEl && placeEl.closest ? placeEl.closest('.podium-place') : null;
    if (placeEl) placeEl.classList.toggle('podium-place--empty', !player);
}

/** Runs all three slots against a leaderboard, returns which ones are hidden. */
function render(leaderboard) {
    const hidden = [];
    [1, 2, 3].forEach((place) => {
        const slot = makePodium(place);
        const player = leaderboard.find((p) => p.rank === place);
        renderPlace(slot, player);
        if (slot.placeEl.classList.contains('podium-place--empty')) hidden.push(place);
    });
    return hidden;
}

describe('#2130 — no podium stand without a player on it', () => {
    it('hides the third stand in a two-player game', () => {
        // Exactly the game in the reporter's screenshot: Sandra 162, Aaron 128.
        const hidden = render([
            { rank: 1, name: 'Sandra', score: 162 },
            { rank: 2, name: 'Aaron', score: 128 },
        ]);
        expect(hidden).toEqual([3]);
    });

    it('hides the second and third stand in a single-player game', () => {
        expect(render([{ rank: 1, name: 'Sandra', score: 162 }])).toEqual([2, 3]);
    });

    it('hides nothing once three players are ranked', () => {
        expect(render([
            { rank: 1, name: 'Sandra', score: 162 },
            { rank: 2, name: 'Aaron', score: 128 },
            { rank: 3, name: 'Kim', score: 90 },
        ])).toEqual([]);
    });

    it('still fills the placeholders it always filled', () => {
        // The '---' / '0' assignment predates this fix and stays: hiding the
        // stand is a display decision, not a reason to change what it holds.
        const slot = makePodium(3);
        renderPlace(slot, undefined);
        expect(slot.nameEl.textContent).toBe('---');
        expect(slot.scoreEl.textContent).toBe('0');
    });
});

describe('#2130 — the shipped code still carries the fix', () => {
    it('toggles a class on the place element, not `hidden`', () => {
        expect(JS).toContain("closest('.podium-place')");
        expect(JS).toContain("classList.toggle('podium-place--empty', !player)");
        // `.podium-place` is display:flex, which beats the UA rule for [hidden].
        expect(JS).not.toMatch(/placeEl\.hidden\s*=/);
    });

    it('defines the empty-stand rule the toggle depends on', () => {
        expect(CSS).toMatch(/\.end-stage-layout \.podium-place--empty \{\s*display: none;\s*\}/);
    });

    it('keeps the podium from shrinking below its stand', () => {
        // The name broke mid-word because the place could shrink under the
        // stand's fixed 200px, not because the font was too large.
        const place = CSS.match(/\.end-stage-layout \.podium-place \{[^}]*\}/)[0];
        expect(place).toContain('flex: 0 1 200px');
        expect(place).toContain('min-width: 0');
        const name = CSS.match(/\.end-stage-layout \.podium-name \{[^}]*\}/)[0];
        expect(name).toContain('text-overflow: ellipsis');
        expect(name).toContain('white-space: nowrap');
    });

    it('keeps the award cards inside their grid track', () => {
        const card = CSS.match(/\.end-stage-layout \.superlative-card \{[^}]*\}/)[0];
        expect(card).toContain('min-width: 0');
        expect(card).toContain('grid-template-columns: auto minmax(0, 1fr) auto');
    });
});
