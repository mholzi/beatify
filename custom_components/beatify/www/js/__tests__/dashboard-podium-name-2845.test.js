/**
 * #2845 — the winner's name on the TV podium broke in the middle of the word.
 *
 * Measured on a real 1920×1080 TV in the live test of v4.7.0-rc3: "Andreas"
 * rendered as "Andr" / "eas" on the center stand, at 64px, `white-space: normal`,
 * `word-break: break-word`.
 *
 * The dashboard loads styles.css before dashboard.css. styles.css styles the
 * phone's winner name with `body.theme-dark .podium-place.podium-1 .podium-name`
 * (0,4,1), which beat the TV end stage's `.end-stage-layout .podium-1 .podium-name`
 * (0,3,0). The fix is a TV rule with more specificity. There is no layout engine
 * here, so the rules themselves are pinned: the TV rule must outrank the phone
 * rule and must keep the name on one line.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { WWW_DIR } from './helpers/js-source.js';

const STYLES = readFileSync(join(WWW_DIR, 'css', 'styles.css'), 'utf8');
const DASHBOARD = readFileSync(join(WWW_DIR, 'css', 'dashboard.css'), 'utf8');

const PHONE_SELECTOR = 'body.theme-dark .podium-place.podium-1 .podium-name';
const TV_SELECTOR = 'body.theme-dark .end-stage-layout .podium-place.podium-1 .podium-name';

/** Declarations of the first rule whose selector list is exactly `selector`. */
function rule(css, selector) {
    const stripped = css.replace(/\/\*[\s\S]*?\*\//g, '');
    const re = /([^{}]+)\{([^}]*)\}/g;
    let m;
    while ((m = re.exec(stripped)) !== null) {
        if (m[1].trim() === selector) {
            const decls = {};
            for (const part of m[2].split(';')) {
                const i = part.indexOf(':');
                if (i > 0) decls[part.slice(0, i).trim()] = part.slice(i + 1).trim();
            }
            return decls;
        }
    }
    return null;
}

/** [ids, classes, types] for a simple compound-descendant selector. */
function specificity(selector) {
    let ids = 0;
    let classes = 0;
    let types = 0;
    for (const compound of selector.trim().split(/\s+/)) {
        ids += (compound.match(/#/g) || []).length;
        classes += (compound.match(/\./g) || []).length;
        if (/^[a-z]/i.test(compound)) types += 1;
    }
    return [ids, classes, types];
}

function outranks(a, b) {
    for (let i = 0; i < 3; i++) {
        if (a[i] !== b[i]) return a[i] > b[i];
    }
    return false;
}

describe('#2845 the winner name stays on one line on the TV', () => {
    it('still finds the phone rule that caused the break', () => {
        const phone = rule(STYLES, PHONE_SELECTOR);
        expect(phone).not.toBeNull();
        expect(phone['word-break']).toBe('break-word');
    });

    it('has a TV rule that outranks the phone rule', () => {
        expect(rule(DASHBOARD, TV_SELECTOR)).not.toBeNull();
        expect(outranks(specificity(TV_SELECTOR), specificity(PHONE_SELECTOR))).toBe(true);
    });

    it('keeps the name on one line and ends a long one with an ellipsis', () => {
        const tv = rule(DASHBOARD, TV_SELECTOR);
        expect(tv['white-space']).toBe('nowrap');
        expect(tv['word-break']).toBe('normal');
        expect(tv['overflow']).toBe('hidden');
        expect(tv['text-overflow']).toBe('ellipsis');
    });

    it('uses the TV size, not the phone clamp that reaches 64px', () => {
        expect(rule(DASHBOARD, TV_SELECTOR)['font-size']).toBe('38px');
    });
});
