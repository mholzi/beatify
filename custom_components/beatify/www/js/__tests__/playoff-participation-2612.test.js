/** Regression guards for the player-side finale-playoff spectator state (#2612). */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(__dirname, '..', 'player-game.js'), 'utf8');

describe('#2612 finale-playoff participation', () => {
    it('locks the player UI for both server-side out-of-play states', () => {
        expect(source).toContain('var amOut = amEliminated || amPlayoffSpectator;');
        expect(source).toContain('function meOutOfPlay()');
        expect(source).toContain('if (meOutOfPlay()) return;');
    });

    it('does not count spectators as waiting or submitted players', () => {
        expect(source).toContain('return !p.eliminated && !p.playoff_spectator;');
        expect(source).toContain('(player.submitted && !isOutOfPlay)');
    });
});
