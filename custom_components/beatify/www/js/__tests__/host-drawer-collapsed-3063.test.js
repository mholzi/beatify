/**
 * #3063 — the reveal's "Next Round" button did nothing on the host's phone.
 *
 * The button itself was fine: it is wired to the same `handleNextRound` as the
 * small ⏭️ Next in the control bar. What broke it was the host drawer (#2723)
 * sitting on top of it. The drawer collapses its body with the `hidden`
 * attribute (`body.hidden = true` in player-game.js), but `.host-drawer__body`
 * declares `display: flex`, and an author `display` beats the UA's
 * `[hidden] { display: none }`. So the "collapsed" drawer was always open,
 * fixed above the control bar with `pointer-events: auto`, and every tap on
 * the big red button landed on the drawer instead.
 *
 * Guarded on the readable source AND the served `.min.css`: player.html loads
 * the minified stylesheet, so a rule that only exists in styles.css reaches
 * no phone.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const WWW_DIR = join(__dirname, '..', '..');

const CSS = readFileSync(join(WWW_DIR, 'css', 'styles.css'), 'utf8');
const MIN = readFileSync(join(WWW_DIR, 'css', 'styles.min.css'), 'utf8');
const PLAYER_GAME = readFileSync(join(WWW_DIR, 'js', 'player-game.js'), 'utf8');

/** Declaration blocks of every rule whose selector list is exactly `selector`. */
function blocksFor(src, selector) {
    const noComments = src.replace(/\/\*[\s\S]*?\*\//g, '');
    const out = [];
    const re = /([^{}]+)\{([^{}]*)\}/g;
    let m;
    while ((m = re.exec(noComments)) !== null) {
        const selectors = m[1].split(',').map((s) => s.trim().replace(/\s+/g, ' '));
        if (selectors.includes(selector)) out.push(m[2]);
    }
    return out;
}

function displayOf(block) {
    const m = /(?:^|;)\s*display\s*:\s*([^;!]+)/.exec(block);
    return m ? m[1].trim() : null;
}

describe('#3063 host drawer body honours the hidden attribute', () => {
    it('player-game.js collapses the drawer body with the hidden attribute', () => {
        // If this ever stops being true the CSS guard below is guarding nothing.
        expect(PLAYER_GAME).toMatch(/body\.hidden\s*=\s*true/);
    });

    it.each([['styles.css', CSS], ['styles.min.css', MIN]])(
        '%s: .host-drawer__body sets a display, so [hidden] needs its own rule',
        (_, src) => {
            const shown = blocksFor(src, '.host-drawer__body').map(displayOf).filter(Boolean);
            expect(shown.length).toBeGreaterThan(0);
            expect(shown).not.toContain('none');

            const collapsed = blocksFor(src, '.host-drawer__body[hidden]').map(displayOf);
            expect(collapsed).toContain('none');
        },
    );
});
