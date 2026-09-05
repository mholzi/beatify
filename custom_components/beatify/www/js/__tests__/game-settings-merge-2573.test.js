/**
 * #2573: saving admin settings must not delete the wizard's settings.
 *
 * `saveGameSettings` built a fresh object from 17 adminState fields and wrote
 * it over `beatify_game_settings`. Two settings have no adminState field —
 * `suddenDeathMode` and `maxRounds` — and admin.js reads both straight from
 * localStorage when the game starts; its own comments say so.
 *
 * So the host picked Sudden Death and 20 rounds in the wizard, tapped any chip
 * in the admin afterwards, and played without either of them.
 *
 * The fix merges into the stored blob instead of replacing it, which also
 * covers any future setting that takes the same route.
 */
import { describe, it, expect, beforeEach } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const SRC = readFileSync(
    join(__dirname, '..', 'admin', 'sections', 'game-settings.js'),
    'utf8',
);
const KEY = 'beatify_game_settings';

/** The exact write the fixed `saveGameSettings` performs. */
function speichern(store, settings) {
    let bestehend = {};
    try {
        bestehend = JSON.parse(store.getItem(KEY) || '{}') || {};
    } catch (e) {
        bestehend = {};
    }
    store.setItem(KEY, JSON.stringify(Object.assign({}, bestehend, settings)));
}

function makeStore() {
    const data = {};
    return {
        getItem: (k) => (k in data ? data[k] : null),
        setItem: (k, v) => {
            data[k] = String(v);
        },
    };
}

describe('#2573 game settings merge instead of replace', () => {
    let store;
    beforeEach(() => {
        store = makeStore();
    });

    it('keeps wizard-only settings when the admin saves', () => {
        store.setItem(
            KEY,
            JSON.stringify({ suddenDeathMode: true, maxRounds: 20, language: 'de' }),
        );

        speichern(store, { language: 'en', difficulty: 'hard' });

        const nachher = JSON.parse(store.getItem(KEY));
        expect(nachher.suddenDeathMode).toBe(true);
        expect(nachher.maxRounds).toBe(20);
        // What the admin does own still wins.
        expect(nachher.language).toBe('en');
        expect(nachher.difficulty).toBe('hard');
    });

    it('survives repeated saves — the wizard settings do not erode', () => {
        store.setItem(KEY, JSON.stringify({ suddenDeathMode: true, maxRounds: 20 }));
        for (let i = 0; i < 5; i++) speichern(store, { difficulty: `d${i}` });
        const nachher = JSON.parse(store.getItem(KEY));
        expect(nachher.suddenDeathMode).toBe(true);
        expect(nachher.maxRounds).toBe(20);
        expect(nachher.difficulty).toBe('d4');
    });

    it('a corrupt blob does not take the save down with it', () => {
        store.setItem(KEY, '{not json');
        speichern(store, { language: 'de' });
        expect(JSON.parse(store.getItem(KEY)).language).toBe('de');
    });

    it('the source really merges — a plain setItem would regress this', () => {
        expect(SRC).toContain('Object.assign({}, bestehend, settings)');
        // The old unconditional overwrite must be gone.
        expect(SRC).not.toContain('setItem(STORAGE_GAME_SETTINGS, JSON.stringify(settings))');
    });
});
