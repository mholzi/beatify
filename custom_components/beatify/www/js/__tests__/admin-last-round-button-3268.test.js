/**
 * #3268 — on the last reveal the host's primary button said "Next Round",
 * although the server ends the game there (`finalize_and_end` when
 * `last_round` is set) and the podium follows.
 *
 * admin.js is a classic script, so this reads the served source from disk, as
 * admin-invite-in-game-2621 does for its markup half. It pins the label switch
 * to the existing `leaderboard.finalResults` string (the one the host's phone
 * already shows in player-reveal.js) and checks every locale carries it, so no
 * language falls back to a raw key.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const ADMIN_JS = readFileSync(join(__dirname, '..', 'admin.js'), 'utf8');
const PLAYER_REVEAL_JS = readFileSync(join(__dirname, '..', 'player-reveal.js'), 'utf8');
const I18N_DIR = join(__dirname, '..', '..', 'i18n');

function revealViewBody() {
    const start = ADMIN_JS.indexOf('function showAdminRevealView(');
    expect(start).toBeGreaterThan(-1);
    const next = ADMIN_JS.indexOf('\nfunction ', start + 1);
    return ADMIN_JS.slice(start, next === -1 ? undefined : next);
}

describe('#3268 admin last-round button label', () => {
    it('switches #admin-next-round to the final-results label on last_round', () => {
        const body = revealViewBody();
        expect(body).toContain("getElementById('admin-next-round')");
        expect(body).toMatch(
            /data\.last_round\s*\?\s*'leaderboard\.finalResults'\s*:\s*'admin\.nextRound'/,
        );
        // The data-i18n key follows the label, so a language switch keeps it.
        expect(body).toContain("setAttribute('data-i18n', nextKey)");
    });

    it('reuses the string the host phone already shows on the last reveal', () => {
        expect(PLAYER_REVEAL_JS).toContain("utils.t('leaderboard.finalResults')");
    });

    it('has leaderboard.finalResults in every locale', () => {
        const files = readdirSync(I18N_DIR).filter((f) => f.endsWith('.json'));
        expect(files.length).toBeGreaterThan(0);
        for (const f of files) {
            const data = JSON.parse(readFileSync(join(I18N_DIR, f), 'utf8'));
            expect(data.leaderboard?.finalResults, f).toBeTruthy();
        }
    });
});
