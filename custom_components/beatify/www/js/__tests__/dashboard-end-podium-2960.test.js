/**
 * #2960: the TV game-over screen puts the podium first.
 *
 * With four players the podium sat small at the bottom of the middle third
 * while a "Full Rankings" box held a single line (#4 Leo). Now the podium
 * takes the left two thirds with real steps, places 4+ are chips right under
 * it, the average pts/round joins the meta line and the highlights stay on
 * the right. These tests pin the structure and the stylesheet rules the
 * layout depends on.
 */
import { describe, it, expect } from 'vitest';
import { readSource } from './helpers/js-source.js';

const HTML = readSource('../dashboard.html');
const CSS = readSource('../css/dashboard.css');
const JS = readSource('dashboard.js');

const END = HTML.slice(HTML.indexOf('id="dashboard-end"'), HTML.indexOf('id="dashboard-paused"'));

describe('the end screen markup (#2960)', () => {
    it('has no "Full Rankings" box on the TV any more', () => {
        expect(END).not.toContain('leaderboard.fullRankings');
        expect(END).not.toContain('end-panel--standings');
    });

    it('puts places 4+ directly under the podium', () => {
        const wrap = END.slice(END.indexOf('class="end-podium-wrap"'), END.indexOf('end-panel--highlights'));
        expect(wrap).toContain('class="dashboard-podium"');
        expect(wrap).toContain('id="end-leaderboard"');
        expect(wrap.indexOf('class="dashboard-podium"')).toBeLessThan(wrap.indexOf('id="end-leaderboard"'));
    });

    it('moves the average pts/round into the meta line', () => {
        const meta = END.slice(END.indexOf('class="end-meta"'), END.indexOf('</header>'));
        expect(meta).toContain('id="end-stats-comparison"');
    });

    it('keeps the highlights on the right', () => {
        expect(END).toContain('end-panel--highlights');
    });
});

describe('the end screen stylesheet (#2960)', () => {
    it('gives the podium two thirds of the stage', () => {
        const stage = CSS.match(/\.end-stage-layout \.end-stage \{[^}]*\}/)[0];
        expect(stage).toContain('grid-template-columns: minmax(0, 2.4fr) minmax(0, 1fr)');
    });

    it('builds real steps: 1 tallest, then 2, then 3', () => {
        const h = (n) => {
            const m = CSS.match(new RegExp(`\\.end-stage-layout \\.podium-${n} \\.podium-stand \\{[^}]*height: calc\\(([\\d.]+) \\* var\\(--u\\)\\)`));
            return Number(m[1]);
        };
        expect(h(1)).toBeGreaterThan(h(2));
        expect(h(2)).toBeGreaterThan(h(3));
    });

    it('overrides the phone podium (body.theme-dark) with an id-scoped reset', () => {
        // styles.css turns the stands into a poster + chips at (0,3,1)-(0,4,1);
        // on the TV that stacked the three stands on top of each other.
        expect(CSS).toMatch(/#dashboard-end \.end-stage-layout \.podium-place\.podium-1,\s*#dashboard-end \.end-stage-layout \.podium-place\.podium-2,\s*#dashboard-end \.end-stage-layout \.podium-place\.podium-3 \{[^}]*grid-area: auto;[^}]*display: flex;/);
        expect(CSS).toMatch(/#dashboard-end \.end-stage-layout \.podium-place \.podium-stand \{ display: flex; \}/);
    });

    it('zooms the whole end screen on short landscape screens, 1080p untouched', () => {
        const steps = [...CSS.matchAll(/max-height: (\d+)px\) \{\s*#dashboard-end \.dashboard-end-content\.end-stage-layout \{ zoom: ([\d.]+); \}/g)]
            .map((m) => [Number(m[1]), Number(m[2])]);
        expect(steps.length).toBeGreaterThanOrEqual(3);
        for (const [maxH, zoom] of steps) {
            expect(maxH).toBeLessThan(1080);
            // 16:9 at that height still gets a 1920 px wide layout.
            expect((maxH * 16 / 9) / zoom).toBeGreaterThanOrEqual(1920 * 0.97);
        }
    });

    it('gets denser past ten chips and lowers the steps with it', () => {
        expect(JS).toContain("container.classList.toggle('end-rest--dense', rest.length > 10)");
        expect(CSS).toMatch(/\.end-podium-wrap:has\(\.end-rest--dense\) \.podium-1 \.podium-stand/);
    });
});
