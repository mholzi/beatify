/**
 * The Streak-Shield reveal badge must actually be wired (#1666).
 *
 * `renderPersonalResult` is not exported, so this asserts the wiring at the
 * source level instead of rendering: that both reveal paths consult
 * `streak_shield_used`, that the helper exists, and that the i18n key it uses
 * is present in all five locales. The last one matters more than it looks —
 * a missing key does not throw, it renders the raw key string into the card.
 */

import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

const ROOT = path.resolve(__dirname, '../../..');
const REVEAL = fs.readFileSync(
    path.join(ROOT, 'www/js/player-reveal.js'), 'utf8');

describe('Streak-Shield badge (#1666)', () => {
    it('renders on the wrong-answer path', () => {
        expect(REVEAL).toContain("player.streak_shield_used ? renderStreakShieldUsed(player)");
    });

    it('renders on the missed-round path too', () => {
        // A shield only ever fires on a round the player got wrong, and a
        // missed round is one of those — covering only the guessed-wrong path
        // would leave the timeout case silently unexplained.
        expect(REVEAL).toMatch(/if \(player\.streak_shield_used\) \{\s*\n\s*missedHtml \+= renderStreakShieldUsed\(player\);/);
    });

    it('names the streak it saved', () => {
        // "Shield used" alone does not land; the number is the point.
        expect(REVEAL).toContain("utils.t('reveal.streakShieldUsed', { streak: streak })");
    });

    it('has the string in all five locales', () => {
        for (const lang of ['en', 'de', 'es', 'fr', 'nl']) {
            const dict = JSON.parse(fs.readFileSync(
                path.join(ROOT, `www/i18n/${lang}.json`), 'utf8'));
            expect(dict.reveal?.streakShieldUsed, `${lang} missing`).toBeTruthy();
            expect(dict.reveal.streakShieldUsed, `${lang} lost the placeholder`)
                .toContain('{streak}');
        }
    });

    it('has a stylesheet rule so the badge is not unstyled text', () => {
        const css = fs.readFileSync(path.join(ROOT, 'www/css/styles.css'), 'utf8');
        expect(css).toContain('.streak-shield-used {');
        expect(css).toContain('.streak-shield-text {');
    });
});
