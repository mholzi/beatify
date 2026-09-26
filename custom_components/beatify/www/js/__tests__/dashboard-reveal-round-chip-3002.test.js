/**
 * #3002: a TV that reached REVEAL without living through PLAYING (reload,
 * reconnect, switched on mid-game) showed the HTML placeholder "Round 1 of 10"
 * in the reveal chip. The chip was only ever copied from the PLAYING chip by
 * an observer in dashboard.html; nothing wrote it from the state itself.
 *
 * Runs the shipped phase dispatcher with the shipped `renderRevealRoundChip`
 * on a cold REVEAL payload — the first frame the TV ever renders.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, it, expect } from 'vitest';
import { declaration, evaluate, readSource, WWW_DIR } from './helpers/js-source.js';
import { el } from './helpers/mini-dom.js';

global.window = global.window || {};
await import('../utils.js');
const U = global.window.BeatifyUtils;

const DASHBOARD = readSource('dashboard.js');
const HTML = readFileSync(join(WWW_DIR, 'dashboard.html'), 'utf8');

/** The reveal view's chip as the page ships it: placeholders 1 and 10. */
function revealChip() {
    const chip = el('chip');
    const num = el('num');
    const total = el('total');
    num.textContent = '1';
    total.textContent = '10';
    return { chip, num, total };
}

function coldReveal(data) {
    const { chip, num, total } = revealChip();
    const document = {
        querySelectorAll: (sel) => ({
            '.chip-round': [chip],
            '.reveal-round-num': [num],
            '.reveal-total-num': [total],
        })[sel] || [],
    };
    const renderRevealRoundChip = evaluate(
        declaration(DASHBOARD, 'renderRevealRoundChip', 'dashboard.js'),
        'renderRevealRoundChip',
        { document },
    );
    evaluate(declaration(DASHBOARD, '_applyStateRender', 'dashboard.js'), '_applyStateRender', {
        utils: U,
        document,
        showView: () => {},
        stopCountdown: () => {},
        stopRevealStaging: () => {},
        debug: () => {},
        // The chip part of the real renderRevealView; that it is called from
        // there is asserted below.
        renderRevealView: (d) => renderRevealRoundChip(d),
    })(Object.assign({ phase: 'REVEAL', game_id: 'g1' }, data));
    return { chip, num: num.textContent, total: total.textContent };
}

describe('#3002 TV reveal round chip on a cold REVEAL render', () => {
    it('shows the round and total of the state, not the placeholder', () => {
        const out = coldReveal({ round: 3, total_rounds: 20, max_rounds: 20 });
        expect(String(out.num)).toBe('3');
        expect(String(out.total)).toBe('20');
        expect(out.chip.classList.contains('round-open')).toBe(false);
    });

    it('keeps the total hidden when the game has no round cap (#2958)', () => {
        const out = coldReveal({ round: 7, total_rounds: 266, max_rounds: 0 });
        expect(String(out.num)).toBe('7');
        expect(out.chip.classList.contains('round-open')).toBe(true);
    });

    it('renderRevealView fills the chip on every reveal render', () => {
        const body = declaration(DASHBOARD, 'renderRevealView', 'dashboard.js');
        expect(body).toContain('renderRevealRoundChip(data);');
    });

    it('the markup still carries the hooks the renderer writes to', () => {
        expect(HTML).toMatch(/<strong class="reveal-round-num">/);
        expect(HTML).toMatch(/<strong class="reveal-total-num round-total-part">/);
    });
});
