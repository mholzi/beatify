/** Regression guards for the player-side finale-playoff spectator state (#2612). */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(__dirname, '..', 'player-game.js'), 'utf8');

describe('#2612 finale-playoff participation', () => {
    it('locks the player UI for every server-side out-of-play state', () => {
        // #2746 added a third: a guest the host took out of the running game.
        // The pin moves with it rather than being dropped — the point of this
        // test is that the client mirrors the server's out_of_play set exactly,
        // and a stale pin would silently stop checking that.
        expect(source).toContain('var amOut = amEliminated || amPlayoffSpectator || amSatOut;');
        expect(source).toContain('function meOutOfPlay()');
        expect(source).toContain('if (meOutOfPlay()) return;');
    });

    it('does not count spectators or sat-out guests as waiting or submitted', () => {
        expect(source).toContain('return !p.eliminated && !p.playoff_spectator && !p.sat_out_by_host;');
        expect(source).toContain('(player.submitted && !isOutOfPlay)');
    });
});
