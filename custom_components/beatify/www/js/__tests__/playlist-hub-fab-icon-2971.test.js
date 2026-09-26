/**
 * #2971: the "Request a playlist" button in the hub's bottom bar showed an
 * empty cyan square.
 *
 * The icon is an inline SVG and was always in the markup. The generic
 * `button, .btn` rule in styles.css pads every button 8px 24px; with
 * border-box sizing the 44 px FAB had no content box left, and the flex row
 * shrank the 20 px envelope to 0 px wide (measured in Chrome: svg width 0).
 * The FAB now zeroes its padding and the icon may not shrink.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { WWW_DIR, JS_DIR } from './helpers/js-source.js';

const CSS = readFileSync(join(WWW_DIR, 'css', 'styles.css'), 'utf8');
const MIN = readFileSync(join(WWW_DIR, 'css', 'styles.min.css'), 'utf8');
const HUB = readFileSync(join(JS_DIR, 'playlist-hub.js'), 'utf8');

const rule = (src, sel) => {
    const at = src.indexOf(`\n${sel} {`);
    if (at === -1) return null;
    return src.slice(at, src.indexOf('}', at));
};

describe('#2971 the request FAB keeps room for its envelope', () => {
    it('still renders the envelope as an inline SVG', () => {
        const fab = HUB.slice(HUB.indexOf('class="plh-cta-fab"'));
        expect(fab.slice(0, 600)).toMatch(/<svg width="20" height="20"[^>]*>.*<polyline points="22,7 12,14 2,7"\/>/);
    });

    it('explains the trap: the generic button rule pads 24 px on each side', () => {
        const generic = CSS.slice(CSS.indexOf('\nbutton,\n.btn {'), CSS.indexOf('}', CSS.indexOf('\nbutton,\n.btn {')));
        expect(generic).toMatch(/padding:/);
    });

    it('zeroes the FAB padding so a 44 px button has a content box', () => {
        const fab = rule(CSS, '.plh-cta-fab');
        expect(fab).toMatch(/width: 44px;/);
        expect(fab).toMatch(/padding: 0;/);
    });

    it('does not let the flex row shrink the icon', () => {
        expect(rule(CSS, '.plh-cta-fab svg')).toMatch(/flex-shrink: 0;/);
    });

    it('ships the fix in the minified stylesheet the admin page loads', () => {
        expect(MIN).toMatch(/\.plh-cta-fab\{[^}]*padding:0[;}]/);
        expect(MIN).toMatch(/\.plh-cta-fab svg\{[^}]*flex-shrink:0/);
    });
});
