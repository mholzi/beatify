/**
 * #2994: the admin leaderboard's "(away)" marker for a disconnected guest was
 * hard-coded English, so it stayed English on a German, Spanish, French,
 * Italian or Dutch admin page. It now reads the same `lobby.away` key the TV
 * (#2982) and the phones use.
 *
 * Runs the real `renderAdminLeaderboard` with a `BeatifyI18n.t()` backed by
 * each shipped locale file.
 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import { renderAdminLeaderboard } from '../admin/sections/render-helpers.js';
import { locale } from './helpers/js-source.js';

const LANGS = ['de', 'en', 'es', 'fr', 'it', 'nl'];

let els;

function useLocale(lang) {
    const pack = locale(lang);
    globalThis.BeatifyI18n = {
        t: (key) => {
            const v = key.split('.').reduce((o, k) => (o ? o[k] : undefined), pack);
            return typeof v === 'string' ? v : key;
        },
    };
}

beforeEach(() => {
    els = {};
    globalThis.window = globalThis;
    globalThis.BeatifyUtils = { escapeHtml: (s) => String(s) };
    globalThis.document = {
        getElementById: (id) => (els[id] || (els[id] = { innerHTML: '' })),
    };
});

afterEach(() => {
    delete globalThis.BeatifyUtils;
    delete globalThis.BeatifyI18n;
    delete globalThis.document;
    delete globalThis.window;
});

function awayBadge() {
    const m = els['admin-playing-leaderboard-list'].innerHTML.match(/<span class="away-badge">([^<]*)<\/span>/);
    return m && m[1];
}

describe('#2994 admin leaderboard away badge', () => {
    it.each(LANGS)('%s shows the translated lobby.away word', (lang) => {
        useLocale(lang);
        renderAdminLeaderboard([{ rank: 1, name: 'A', score: 1, connected: false }]);
        const word = locale(lang).lobby.away;
        expect(word).toBeTruthy();
        expect(awayBadge()).toBe('(' + word + ')');
    });

    it('German does not fall back to English', () => {
        useLocale('de');
        renderAdminLeaderboard([{ rank: 1, name: 'A', score: 1, connected: false }]);
        expect(awayBadge()).not.toBe('(away)');
    });

    it('falls back to "away" when the i18n module is missing', () => {
        renderAdminLeaderboard([{ rank: 1, name: 'A', score: 1, connected: false }]);
        expect(awayBadge()).toBe('(away)');
    });

    it('shows no badge for a connected guest', () => {
        useLocale('de');
        renderAdminLeaderboard([{ rank: 1, name: 'A', score: 1, connected: true }]);
        expect(awayBadge()).toBeNull();
    });
});
