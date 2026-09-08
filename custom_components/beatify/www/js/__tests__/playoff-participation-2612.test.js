/** Regression guards for the player-side finale-playoff spectator state (#2612). */
import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(__dirname, '..', 'player-game.js'), 'utf8');

describe('#2612 finale-playoff participation', () => {
    it('locks the player UI for every server-side out-of-play state', () => {
        // #2746 added a third state: a guest the host took out of the running
        // game. #2559 then carved one back OUT of the set — a ghost keeps the
        // guessing UI, because that is the entire feature. The pin moves with
        // both rather than being dropped: the point of this test is that the
        // client mirrors the server's rule exactly, and a stale pin would
        // silently stop checking.
        //
        // Read it as: everyone the server calls out_of_play loses the play UI,
        // EXCEPT an eliminated player who is currently a ghost.
        expect(source).toContain(
            'var amOut = (amEliminated && !amGhost) || amPlayoffSpectator || amSatOut;'
        );
        expect(source).toContain('meEliminated = amEliminated && !amGhost;');
        expect(source).toContain('function meOutOfPlay()');
        expect(source).toContain('if (meOutOfPlay()) return;');
    });

    it('does not count spectators or sat-out guests as waiting or submitted', () => {
        expect(source).toContain('return !p.eliminated && !p.playoff_spectator && !p.sat_out_by_host;');
        expect(source).toContain('(player.submitted && !isOutOfPlay)');
    });
});
