/**
 * #2972: on community cards the "+ ADD" pill covered the COMMUNITY badge.
 *
 * The pill sits top-left, the badge used to sit top-right. The pill is 44 px
 * tall — the touch-target minimum of the generic `button, .btn` rule — and
 * with a 160 px card, "+ ADD" (62 px) and "COMMUNITY" (88 px) plus insets
 * cannot share one line; in Chrome at 390 px the pill ran 6 px into the badge.
 * The badge now stacks under the pill. This test reads the shipped numbers
 * and checks the two boxes cannot meet whatever the label widths.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { WWW_DIR } from './helpers/js-source.js';

const CSS = readFileSync(join(WWW_DIR, 'css', 'styles.css'), 'utf8');
const MIN = readFileSync(join(WWW_DIR, 'css', 'styles.min.css'), 'utf8');

const rule = (sel) => {
    const at = CSS.indexOf(`\n${sel} {`);
    if (at === -1) throw new Error(`${sel} not found`);
    return CSS.slice(at, CSS.indexOf('}', at));
};
const num = (block, prop) => {
    const m = block.match(new RegExp(`\\n\\s*${prop}:\\s*(-?\\d+)px;`));
    return m ? Number(m[1]) : null;
};

describe('#2972 the card badge and the "+ Add" pill never overlap', () => {
    const pill = rule('.plh-pill');
    const badge = rule('.plh-cover-badge');
    const generic = CSS.slice(CSS.indexOf('\nbutton,\n.btn {'), CSS.indexOf('}', CSS.indexOf('\nbutton,\n.btn {')));

    it('knows how tall the pill really is (the generic 44 px button minimum)', () => {
        expect(num(generic, 'min-height')).toBe(44);
        expect(pill).not.toMatch(/min-height:/); // nothing lowers it
    });

    it('puts the badge below the pill, in the same corner', () => {
        const pillBottom = num(pill, 'top') + Math.max(44, num(pill, 'height') || 0);
        expect(num(badge, 'top')).toBeGreaterThan(pillBottom);
        expect(num(badge, 'left')).toBe(num(pill, 'left'));
        expect(badge).not.toMatch(/\n\s*right:/);
    });

    it('ships in the minified stylesheet the admin and player pages load', () => {
        expect(MIN).toMatch(/\.plh-cover-badge\{position:absolute;top:58px;left:8px/);
    });
});
