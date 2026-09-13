/**
 * #2833 / #2834 — the bottom edge of the TV.
 *
 * Both were measured on a real 1920×1080 TV with eleven guests (live test of
 * v4.7.0-rc2):
 *
 *   #2833  The guess axis sized its rows from the plot width only. With a
 *          banner above it the band was 537 px tall, five 64 px rows needed
 *          588, and the fifth row, where "+N" counts the hidden guesses,
 *          ran off the screen. The join corner also sat over the axis' right end.
 *   #2834  While PLAYING, the fixed join corner covered the score and the
 *          has-guessed dot of the last two or three leaderboard rows.
 *
 * The fix sizes the dots from the band height as well, and keeps the corner's
 * footprint free while it is shown. The geometry and the class switch run
 * here from the shipped source; the footprint itself is CSS and is pinned by
 * its rules.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { declaration, evaluate, locale, readSource, WWW_DIR } from './helpers/js-source.js';
import { doc, el } from './helpers/mini-dom.js';

const DASHBOARD = readSource('dashboard.js');
const CSS = readFileSync(join(WWW_DIR, 'css', 'dashboard.css'), 'utf8');
const SNIPPETS = [
    declaration(DASHBOARD, 'guessAxisInitials'),
    declaration(DASHBOARD, 'layoutGuessAxis'),
];
const layout = evaluate(SNIPPETS, 'layoutGuessAxis');

const ROW0 = 284;

function guesses(correct, pairs) {
    return pairs.map(([name, guess]) => {
        const off = Math.abs(guess - correct);
        return { name, guess, years_off: off, round_score: off === 0 ? 10 : 0 };
    });
}

// The live round: nine guesses, six of them on the answer.
const LIVE = guesses(1985, [
    ['Andreas', 1985], ['Anna', 1985], ['Ben', 1985], ['Bettina', 1985], ['Clara', 1985], ['David', 1985],
    ['Emil', 1979], ['Gustav', 2004], ['Hanna', 2004],
]);

/** Bottom edge of the lowest dot, in band pixels. */
function lastRowBottom(L) {
    return ROW0 + (L.rows - 1) * L.pitch + L.size / 2;
}

describe('#2833 the axis fits the band height', () => {
    it('keeps the fifth row and its "+N" inside a 537 px band', () => {
        const L = layout(LIVE, 1985, 1698, { height: 537 });
        expect(L.rows).toBe(5);
        expect(L.dots.some((d) => d.plus > 0)).toBe(true);
        expect(L.size).toBeLessThan(64);
        expect(lastRowBottom(L)).toBeLessThanOrEqual(537);
    });

    it('leaves the 64 px dots alone when the band has room', () => {
        const L = layout(LIVE, 1985, 1698, { height: 603 });
        expect(L.size).toBe(64);
        expect(L.pitch).toBe(68);
        expect(lastRowBottom(L)).toBeLessThanOrEqual(603);
    });

    it('does not shrink a single row for a short band', () => {
        const L = layout(guesses(1985, [['A', 1970], ['B', 1985], ['C', 2000]]), 1985, 1698, { height: 340 });
        expect(L.rows).toBe(1);
        expect(L.size).toBe(64);
    });

    it('never goes below 40 px, however short the band', () => {
        const L = layout(LIVE, 1985, 1698, { height: 300 });
        expect(L.size).toBe(40);
        expect(L.pitch).toBe(44);
    });

    it('keeps the old behaviour when no height is known', () => {
        const L = layout(LIVE, 1985, 1698);
        expect(L.size).toBe(64);
        expect(L.pitch).toBe(68);
    });

    it('uses the same first-row centre as the stylesheet', () => {
        expect(CSS).toMatch(/--guess-axis-row0:\s*284px/);
        expect(declaration(DASHBOARD, 'layoutGuessAxis')).toMatch(/ROW0 = 284/);
    });

    it('measures the band after the banners that push it down, before the staging', () => {
        // On the live TV the "Close to average!" banner cost the band 64 px. An
        // axis drawn before it measured the taller band and ran off the screen.
        const view = declaration(DASHBOARD, 'renderRevealView');
        const axis = view.indexOf('renderGuessAxis(data, axisMode)');
        expect(axis).toBeGreaterThan(-1);
        expect(view.indexOf('renderGuessAxis(')).toBe(axis);
        for (const banner of ['renderMotivationalMessage(', 'renderRoundVoidedBanner(', 'renderIdleHaltBanner(',
            'renderFinaleDoubleBanner(', 'renderFinalePlayoffBanner(', 'renderSuddenDeathFinalBanner(']) {
            expect(view.indexOf(banner), banner).toBeLessThan(axis);
        }
        expect(view.indexOf('startRevealStaging(')).toBeGreaterThan(axis);
    });

    it('hands the fitted size and pitch to the stylesheet', () => {
        const root = el('reveal-guess-axis');
        root.clientHeight = 537;
        root.style.setProperty = (k, v) => { root.style[k] = v; };
        const band = el(null);
        band.style.setProperty = (k, v) => { band.style[k] = v; };
        root.parentNode = band;
        const plot = el('guess-axis-plot');
        plot.clientWidth = 1698;
        const document = doc({ 'reveal-guess-axis': root, 'guess-axis-plot': plot, 'guess-axis-missed': el('guess-axis-missed') });
        const t = (key, params) => String(locale('en').dashboard[key.split('.').pop()]).replace('{count}', params && params.count);
        const render = evaluate(SNIPPETS.concat(declaration(DASHBOARD, 'renderGuessAxis')), 'renderGuessAxis', {
            document,
            utils: { t, escapeHtml: (s) => String(s) },
        });
        render({ song: { year: 1985 }, round_analytics: { all_guesses: LIVE }, players: [] }, true);
        const size = parseInt(root.style['--guess-axis-dot'], 10);
        const pitch = parseInt(root.style['--guess-axis-pitch'], 10);
        expect(size).toBeLessThan(64);
        expect(pitch).toBe(size + 4);
        expect(ROW0 + 4 * pitch + size / 2).toBeLessThanOrEqual(537);
    });
});

describe('#2833 / #2834 the join corner keeps its footprint free', () => {
    function run(data) {
        const body = el('body');
        const corner = el('dashboard-join-corner');
        corner.classList.add('hidden');
        const document = doc({ 'dashboard-join-corner': corner, 'join-corner-qr': el('join-corner-qr'), 'join-corner-url': el('join-corner-url') });
        document.body = body;
        const scope = { document, renderQRCode: () => {} };
        evaluate(declaration(DASHBOARD, 'renderJoinCorner'), 'renderJoinCorner', scope)(data);
        return { body, hide: () => evaluate(declaration(DASHBOARD, 'hideJoinCorner'), 'hideJoinCorner', scope)() };
    }
    const OPEN = { join_url: 'http://ha.local/beatify/play?game=g1', songs_remaining: 5, sudden_death_mode: false };

    it('marks the page while the corner is shown', () => {
        expect(run(OPEN).body.classList.contains('join-corner-open')).toBe(true);
    });

    it('clears the mark when the corner hides by rule', () => {
        const { body } = run(OPEN);
        body.classList.add('join-corner-open');
        expect(run({ ...OPEN, songs_remaining: 2 }).body.classList.contains('join-corner-open')).toBe(false);
    });

    it('clears the mark when the view leaves playing and reveal', () => {
        const r = run(OPEN);
        r.hide();
        expect(r.body.classList.contains('join-corner-open')).toBe(false);
    });

    it('moves the leaderboard off the corner while PLAYING', () => {
        expect(CSS).toMatch(/body\.join-corner-open \.playing-right-section \.dashboard-leaderboard\s*\{[^}]*padding-right:/);
        // A narrow column keeps its width; the rows must not be squeezed either.
        expect(CSS).toMatch(/@media \(max-width: 1599px\)\s*\{\s*body\.join-corner-open \.playing-right-section \.dashboard-leaderboard\s*\{\s*padding-right:\s*0;\s*\}/);
    });

    it('ends the axis plot short of the corner at REVEAL, and the year follows', () => {
        expect(CSS).toMatch(/body\.join-corner-open #dashboard-reveal\s*\{[^}]*--guess-axis-inset-right:/);
        expect(CSS).toMatch(/\.guess-axis-plot\s*\{[^}]*right:\s*var\(--guess-axis-inset-right, 110px\)/);
        expect(CSS).toMatch(/\.reveal-year-row\s*\{[^}]*var\(--guess-axis-inset-right, 110px\)/);
    });
});
