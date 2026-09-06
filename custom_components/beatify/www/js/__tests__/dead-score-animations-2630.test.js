/**
 * #2630 — three score-animation helpers that nothing ever called.
 *
 * `animateScoreChange`, `showPointsPopup` and `isStreakMilestone` were exported
 * from player-utils.js, imported by player-game.js and player-reveal.js (which
 * is where ESLint's no-unused-vars fired), mocked in nine vitest files — and
 * called from nowhere. The CSS behind them (`.score-pop`, `.score-burst`,
 * `.points-popup`, …) was unreachable for the same reason.
 *
 * The mocks were the self-sustaining part: every new reveal test copied the
 * block forward, so the dead code kept looking maintained. This test is the
 * replacement for that habit — it fails if any of the three comes back without
 * a caller, and it fails if a new test file re-adds a mock for them.
 */
import { describe, it, expect } from 'vitest';
import { readdirSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const JS = join(__dirname, '..');
const WWW = join(__dirname, '..', '..');

const DEAD = ['animateScoreChange', 'showPointsPopup', 'isStreakMilestone'];
const DEAD_CSS = [
    '.score-animating',
    '.score-pop',
    '.score-shake',
    '.score-flash-red',
    '.score-glow-gold',
    '.score-burst',
    '.points-popup',
    'popup-float',
];

const read = (p) => readFileSync(p, 'utf8');
const PLAYER_UTILS = read(join(JS, 'player-utils.js'));
const PLAYER_GAME = read(join(JS, 'player-game.js'));
const PLAYER_REVEAL = read(join(JS, 'player-reveal.js'));
const STYLES = read(join(WWW, 'css', 'styles.css'));

describe('#2630 the dead score-animation helpers stay gone', () => {
    it('player-utils.js exports none of them', async () => {
        // player-utils.js touches window/document at module load.
        global.window = {
            BeatifyUtils: {},
            location: { search: '' },
            matchMedia: () => ({ matches: false, addEventListener: () => {} }),
            addEventListener: () => {},
        };
        global.document = { getElementById: () => null, addEventListener: () => {}, body: null };
        const utils = await import('../player-utils.js');
        for (const name of DEAD) {
            expect(utils[name], `player-utils exports ${name}`).toBeUndefined();
        }
    });

    it('player-utils.js does not define them either', () => {
        for (const name of DEAD) {
            expect(PLAYER_UTILS, name).not.toContain(name);
        }
        // The lookup table only isStreakMilestone read.
        expect(PLAYER_UTILS).not.toContain('STREAK_MILESTONES');
    });

    it('neither consumer imports them', () => {
        for (const name of DEAD) {
            expect(PLAYER_GAME, `player-game: ${name}`).not.toContain(name);
            expect(PLAYER_REVEAL, `player-reveal: ${name}`).not.toContain(name);
        }
    });

    it('the helper that IS used survived', () => {
        // animateValue lives in the same block and has a real caller
        // (player-game.js score paint) — the deletion must not have taken it.
        expect(PLAYER_UTILS).toContain('export function animateValue');
        expect(PLAYER_GAME).toContain('animateValue(');
    });

    it('their stylesheet rules went with them', () => {
        for (const sel of DEAD_CSS) {
            expect(STYLES, `styles.css still has ${sel}`).not.toContain(sel);
        }
        // The leaderboard animations shared those media blocks and stay.
        expect(STYLES).toContain('.leaderboard-entry--slide-up');
        expect(STYLES).toContain('body.device-tier-low .neon-glow');
    });

    it('no test file mocks them any more', () => {
        const offenders = [];
        for (const f of readdirSync(__dirname).filter((n) => n.endsWith('.test.js'))) {
            if (f === 'dead-score-animations-2630.test.js') continue; // names the symbols on purpose
            const src = read(join(__dirname, f));
            for (const name of DEAD) {
                if (src.includes(name)) offenders.push(`${f}: ${name}`);
            }
        }
        expect(offenders).toEqual([]);
    });
});
