/**
 * #2578, TV side: the finalists get a badge, nobody gets a skull.
 *
 * Design variant B. The server no longer marks non-leaders `eliminated`, so
 * the skulls disappear on their own; what is added is the positive statement —
 * two players are in the playoff.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const JS = join(__dirname, '..');
const WWW = join(__dirname, '..', '..');

global.window = global.window || {};
await import('../utils.js');
const U = global.window.BeatifyUtils;

describe('#2578 playoff spectators on the TV', () => {
    it('hydrateLeaderboard carries playoff_spectator', () => {
        const out = U.hydrateLeaderboard(
            [
                { rank: 1, name: 'Anna', rank_change: 0 },
                { rank: 3, name: 'Clara', rank_change: 0 },
            ],
            [
                { name: 'Anna', score: 84, playoff_spectator: false },
                { name: 'Clara', score: 66, playoff_spectator: true },
            ],
        );
        expect(out[0].playoff_spectator).toBe(false);
        expect(out[1].playoff_spectator).toBe(true);
    });

    it('the badge marks the finalists, not the spectators', () => {
        const src = readFileSync(join(JS, 'dashboard.js'), 'utf8');
        expect(src).toContain('playoffLaeuft && !entry.playoff_spectator');
        expect(src).toContain('finalist-badge');
    });

    it('the badge only appears while a playoff is running', () => {
        const src = readFileSync(join(JS, 'dashboard.js'), 'utf8');
        // Derived from the data, not from a separate flag that could go stale.
        expect(src).toContain('leaderboard.some(function (x) { return x.playoff_spectator; })');
    });

    it('the label exists in all six locales', () => {
        for (const l of ['en', 'de', 'es', 'fr', 'it', 'nl']) {
            const j = JSON.parse(readFileSync(join(WWW, 'i18n', `${l}.json`), 'utf8'));
            expect(j.reveal?.finalePlayoff, l).toBeTruthy();
        }
    });
});
