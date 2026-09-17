/**
 * #2864 — the Highlights panel on the TV Game Over screen read "🎬 🎬 Highlights".
 *
 * Found in the live test of v4.7.1-rc1. dashboard.html renders the clapperboard in
 * its own `.end-panel-ic` span, and `highlights.highlightsTab` carried it again, so
 * once i18n replaced the fallback text the icon appeared twice. The player end
 * screen used the same key without an icon span, which is why the emoji lived in
 * the string at all.
 *
 * The fix moves the icon out of the string on both surfaces: the translation is
 * plain text (like `leaderboard.fullRankings`), and each page renders the icon in
 * its own span. There is no DOM translation here, so the invariant is pinned on the
 * sources: after i18n runs, each title holds exactly one 🎬.
 */
import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { WWW_DIR } from './helpers/js-source.js';

const ICON = '🎬';
const LOCALES = readdirSync(join(WWW_DIR, 'i18n')).filter((f) => f.endsWith('.json'));

function count(haystack, needle) {
    return haystack.split(needle).length - 1;
}

/** The element carrying data-i18n="highlights.highlightsTab" plus its parent line. */
function titleMarkup(html) {
    const lines = html.split('\n');
    const i = lines.findIndex((l) => l.includes('data-i18n="highlights.highlightsTab"'));
    expect(i, 'highlightsTab title not found').toBeGreaterThanOrEqual(0);
    return lines.slice(Math.max(0, i - 1), i + 1).join('\n');
}

describe('#2864 Highlights title shows the clapperboard once', () => {
    it('finds every locale file', () => {
        expect(LOCALES.length).toBeGreaterThanOrEqual(6);
    });

    for (const file of LOCALES) {
        it(`${file}: highlightsTab carries no icon of its own`, () => {
            const json = JSON.parse(readFileSync(join(WWW_DIR, 'i18n', file), 'utf8'));
            const value = json.highlights.highlightsTab;
            expect(typeof value).toBe('string');
            expect(value.length).toBeGreaterThan(0);
            expect(value.includes(ICON)).toBe(false);
        });
    }

    for (const page of ['dashboard.html', 'player.html']) {
        it(`${page}: the title renders exactly one icon outside the translated span`, () => {
            const markup = titleMarkup(readFileSync(join(WWW_DIR, page), 'utf8'));
            const translated = markup.match(/<span data-i18n="highlights\.highlightsTab">([^<]*)<\/span>/);
            expect(translated, 'translated text must sit in its own span').not.toBeNull();
            expect(translated[1].includes(ICON)).toBe(false);
            expect(count(markup, ICON)).toBe(1);
        });
    }
});
