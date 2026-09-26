/**
 * #2961 — at 1280×720 the TV reveal's big year sat on the bottom edge and the
 * guess dots fell below the screen.
 *
 * The axis reveal is laid out in 1080p pixels, and dashboard.js shares some of
 * those pixels (first dot row at 284 px). Short landscape screens therefore
 * zoom the whole broadcast block instead of resizing single parts. There is no
 * layout engine here, so the media queries are pinned: every step must leave
 * the block at least the ~975 px it needs under the 105 px header, and 1080p
 * must match none of them.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { WWW_DIR } from './helpers/js-source.js';

const CSS = readFileSync(join(WWW_DIR, 'css', 'dashboard.css'), 'utf8').replace(/\/\*[\s\S]*?\*\//g, '');
const HEADER = 105;
const NEEDED = 975;

/** [{maxHeight, zoom}] for every media query that zooms the axis reveal. */
function zoomSteps() {
    const steps = [];
    const re = /@media[^{]*max-height:\s*(\d+)px\)[^{]*\{\s*#dashboard-reveal\.reveal-axis-mode \.reveal-broadcast\s*\{\s*zoom:\s*([\d.]+);/g;
    let m;
    while ((m = re.exec(CSS)) !== null) steps.push({ maxHeight: Number(m[1]), zoom: Number(m[2]) });
    return steps.sort((a, b) => b.maxHeight - a.maxHeight);
}

function zoomAt(height) {
    let zoom = 1;
    for (const s of zoomSteps()) if (height <= s.maxHeight) zoom = s.zoom;
    return zoom;
}

describe('#2961 axis reveal fits short TVs', () => {
    it('has zoom steps', () => {
        expect(zoomSteps().length).toBeGreaterThan(0);
    });

    it('leaves 1080p untouched', () => {
        expect(zoomAt(1080)).toBe(1);
    });

    it.each([720, 768, 800, 900, 1000])('gives the block its 1080p height at %ipx', (h) => {
        expect((h - HEADER) / zoomAt(h)).toBeGreaterThanOrEqual(NEEDED);
    });
});
