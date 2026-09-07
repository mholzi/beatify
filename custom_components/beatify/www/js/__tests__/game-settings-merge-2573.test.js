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
 *
 * #2701: this file used to exercise a hand-written copy of the save named
 * `speichern`, with one test grepping `game-settings.js` for the literal
 * `Object.assign({}, bestehend, settings)` to keep the copy honest. That grep
 * went red on a rename of a German local and stayed green on a merge that
 * dropped a key. The real `saveGameSettings` is imported and run instead; the
 * copy and the grep are both gone.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

// The sections this one imports are irrelevant to the storage round-trip, and
// two of them (party-lights, tts-settings) reach for the DOM at call time.
vi.mock('../admin/sections/playlists.js', () => ({ renderPlaylists: () => {} }));
vi.mock('../admin/sections/library.js', () => ({
    setupLibrarySettings: () => {},
    syncLibraryControls: () => {},
    updateLibraryPanelVisibility: () => {},
}));
vi.mock('../tts-settings.js', () => ({ ttsConfig: () => ({ enabled: false }) }));
vi.mock('../party-lights.js', () => ({ partyLightsConfig: () => ({ enabled: false }) }));

const KEY = 'beatify_game_settings';

function makeStore() {
    const data = {};
    return {
        getItem: (k) => (k in data ? data[k] : null),
        setItem: (k, v) => { data[k] = String(v); },
        removeItem: (k) => { delete data[k]; },
    };
}

let store;
globalThis.localStorage = {
    getItem: (k) => store.getItem(k),
    setItem: (k, v) => store.setItem(k, v),
    removeItem: (k) => store.removeItem(k),
};
// saveGameSettings also fires a lobby-update request; it is wrapped in its own
// try/catch and has nothing to do with what lands in storage.
globalThis.window = globalThis.window || {};
globalThis.document = globalThis.document || {
    getElementById: () => null,
    querySelectorAll: () => [],
    querySelector: () => null,
};

const { STORAGE_GAME_SETTINGS } = await import('../admin/constants.js');
const { adminState } = await import('../admin/state.js');
const { saveGameSettings } = await import('../admin/sections/game-settings.js');

/** What the host has picked in the admin, as adminState holds it. */
function pickInAdmin(settings) {
    Object.assign(adminState, settings);
    saveGameSettings();
}

const stored = () => JSON.parse(store.getItem(KEY));

describe('#2573 game settings merge instead of replace', () => {
    beforeEach(() => {
        store = makeStore();
    });

    it('writes to the key admin.js reads at game start', () => {
        // The whole bug is about one blob being shared by two writers, so the
        // key itself is load-bearing.
        expect(STORAGE_GAME_SETTINGS).toBe(KEY);
    });

    it('keeps wizard-only settings when the admin saves', () => {
        store.setItem(
            KEY,
            JSON.stringify({ suddenDeathMode: true, maxRounds: 20, language: 'de' }),
        );

        pickInAdmin({ selectedLanguage: 'en', selectedDifficulty: 'hard' });

        // The two the wizard owns and adminState knows nothing about.
        expect(stored().suddenDeathMode).toBe(true);
        expect(stored().maxRounds).toBe(20);
        // What the admin does own still wins.
        expect(stored().language).toBe('en');
        expect(stored().difficulty).toBe('hard');
    });

    it('survives repeated saves — the wizard settings do not erode', () => {
        store.setItem(KEY, JSON.stringify({ suddenDeathMode: true, maxRounds: 20 }));
        ['easy', 'normal', 'hard', 'easy', 'hard'].forEach((d) => {
            pickInAdmin({ selectedDifficulty: d });
        });
        expect(stored().suddenDeathMode).toBe(true);
        expect(stored().maxRounds).toBe(20);
        expect(stored().difficulty).toBe('hard');
    });

    it('keeps a setting nobody has written yet — the next one, whatever it is', () => {
        // The point of merging rather than listing exceptions: a future wizard
        // setting takes the same route and is already covered.
        store.setItem(KEY, JSON.stringify({ someFutureWizardSetting: 'kept' }));
        pickInAdmin({ selectedLanguage: 'de' });
        expect(stored().someFutureWizardSetting).toBe('kept');
    });

    it('a corrupt blob does not take the save down with it', () => {
        store.setItem(KEY, '{not json');
        pickInAdmin({ selectedLanguage: 'de' });
        expect(stored().language).toBe('de');
    });

    it('writes the admin-owned settings on an empty store', () => {
        pickInAdmin({
            selectedLanguage: 'es',
            selectedDuration: 45,
            selectedDifficulty: 'easy',
            sabotageEnabled: true,
        });
        expect(stored()).toMatchObject({
            language: 'es',
            duration: 45,
            difficulty: 'easy',
            sabotage: true,
        });
    });
});
