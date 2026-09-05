/**
 * #2584: the sabotage hit has to reach the TV, not just the two phones.
 *
 * Anna freezes Ben's timer. Ben swears. The rest of the room looks at the TV
 * and sees nothing — the loudest social moment the game produces happened
 * invisibly. `sabotaged_by` and `sabotage_effect` have ridden along in every
 * broadcast since #1665; the dashboard simply never read them.
 *
 * Design variant B (decided 05.09.2026): the badge sits in the row of the
 * player who was HIT, stays for the whole reveal, and names the culprit.
 *
 * dashboard.js is a DOM-coupled IIFE with no exported helpers, so — like the
 * other dashboard tests here — this asserts the load-bearing pieces: the
 * hydration that carries the fields, and the locale keys the badge renders.
 */
import { describe, it, expect, beforeAll } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));

global.window = global.window || {};
await import('../utils.js');
const U = global.window.BeatifyUtils;

const LOCALES = ['en', 'de', 'es', 'fr', 'nl', 'it'];
const EFFECTS = ['timer_cut', 'forced_bet', 'freeze'];
const i18n = {};
beforeAll(() => {
    for (const l of LOCALES) {
        i18n[l] = JSON.parse(
            readFileSync(join(__dirname, '..', '..', 'i18n', `${l}.json`), 'utf8'),
        );
    }
});

describe('#2584 sabotage badge on the TV', () => {
    it('hydrateLeaderboard carries sabotaged_by and sabotage_effect', () => {
        const leaderboard = [
            { rank: 1, name: 'Anna', rank_change: 0 },
            { rank: 2, name: 'Ben', rank_change: 0 },
        ];
        const players = [
            { name: 'Anna', score: 84, sabotaged: 'Ben', sabotaged_by: null },
            {
                name: 'Ben',
                score: 71,
                sabotaged_by: 'Anna',
                sabotage_effect: 'freeze',
            },
        ];

        const [anna, ben] = U.hydrateLeaderboard(leaderboard, players);

        // The badge belongs to the player who was hit, not the one who hit.
        expect(ben.sabotaged_by).toBe('Anna');
        expect(ben.sabotage_effect).toBe('freeze');
        expect(anna.sabotaged_by).toBeFalsy();
    });

    it('keeps rank fields intact — entry still wins on overlap', () => {
        const out = U.hydrateLeaderboard(
            [{ rank: 2, name: 'Ben', rank_change: -1 }],
            [{ name: 'Ben', rank: 99, score: 71, sabotaged_by: 'Anna' }],
        );
        expect(out[0].rank).toBe(2);
        expect(out[0].rank_change).toBe(-1);
        expect(out[0].sabotaged_by).toBe('Anna');
    });

    it('every effect has a short label in all six locales', () => {
        for (const l of LOCALES) {
            for (const e of EFFECTS) {
                const label = i18n[l].sabotage?.effect?.[e];
                expect(label, `${l}: sabotage.effect.${e}`).toBeTruthy();
                // Four metres away a long word does not read. 24 is the width
                // that still fits beside a name on the TV row; the current
                // outlier is nl "Gedwongen weddenschap" at 21, which fits but
                // is the one worth shortening if the row ever gets tight.
                expect(label.length, `${l}: sabotage.effect.${e} too long`).toBeLessThanOrEqual(24);
            }
        }
    });

    it('a hit without a known effect still names the culprit', () => {
        // The effect is rolled server-side and could gain a fourth value before
        // the locales catch up. The badge has to survive that: the culprit is
        // the part the room cares about, the effect is the detail.
        const out = U.hydrateLeaderboard(
            [{ rank: 2, name: 'Ben', rank_change: 0 }],
            [{ name: 'Ben', score: 71, sabotaged_by: 'Anna', sabotage_effect: 'brand_new' }],
        );
        expect(out[0].sabotaged_by).toBe('Anna');
        expect(out[0].sabotage_effect).toBe('brand_new');
    });
});
