/**
 * #1927 — a stale localStorage speaker outlived a newer pick made on another
 * device, so the game started in the wrong room.
 *
 * The old seed in admin.js only ran for a pristine browser
 * (`if (!hasLocal)`), which meant:
 *   - a device with ANY Beatify state never learned about a newer speaker, and
 *   - a device holding only `beatify_game_settings` lost the saved speaker too.
 *
 * These cover `reconcileSavedSetup()` (server wins for the speaker, seed-only
 * for settings, per-key) and the `speakerLabelFor()` used by the home view to
 * finally NAME the speaker a game would start on.
 */
import { describe, it, expect } from 'vitest';
import { reconcileSavedSetup, speakerLabelFor } from '../admin/setup-sync.js';

function mockStorage(store) {
    return {
        getItem: (k) => (Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null),
        setItem: (k, v) => { store[k] = String(v); },
        removeItem: (k) => { delete store[k]; },
    };
}

describe('#1927 reconcileSavedSetup — speaker', () => {
    it('adopts the server speaker over a stale local one (the reported bug)', () => {
        // Exactly the failing install: wizard on the phone saved Esszimmer, this
        // browser still held the kitchen twin and won.
        const store = { beatify_last_player: 'media_player.kuche_2' };
        const saved = { last_player: 'media_player.esszimmer' };

        const result = reconcileSavedSetup(saved, mockStorage(store));

        expect(result.playerAdopted).toBe('media_player.esszimmer');
        expect(store.beatify_last_player).toBe('media_player.esszimmer');
    });

    it('reports no adoption when local already matches the server', () => {
        const store = { beatify_last_player: 'media_player.esszimmer' };

        const result = reconcileSavedSetup(
            { last_player: 'media_player.esszimmer' },
            mockStorage(store)
        );

        expect(result.playerAdopted).toBeNull();
        expect(store.beatify_last_player).toBe('media_player.esszimmer');
    });

    it('keeps the local speaker when the server blob carries none', () => {
        const store = { beatify_last_player: 'media_player.esszimmer' };

        const result = reconcileSavedSetup({ game_settings: { difficulty: 'hard' } }, mockStorage(store));

        expect(result.playerAdopted).toBeNull();
        expect(store.beatify_last_player).toBe('media_player.esszimmer');
    });

    it('seeds the speaker into a pristine browser (the #1663 behaviour, kept)', () => {
        const store = {};

        const result = reconcileSavedSetup({ last_player: 'media_player.esszimmer' }, mockStorage(store));

        expect(result.playerAdopted).toBe('media_player.esszimmer');
        expect(store.beatify_last_player).toBe('media_player.esszimmer');
    });

    it('seeds the speaker even when only game settings are stored locally', () => {
        // Old `hasLocal` was an OR across both keys, so this browser silently
        // kept no speaker at all.
        const store = { beatify_game_settings: '{"difficulty":"normal"}' };

        const result = reconcileSavedSetup({ last_player: 'media_player.esszimmer' }, mockStorage(store));

        expect(result.playerAdopted).toBe('media_player.esszimmer');
        expect(store.beatify_last_player).toBe('media_player.esszimmer');
    });
});

describe('#1927 reconcileSavedSetup — game settings stay seed-only', () => {
    it('seeds settings when the browser has none', () => {
        const store = {};

        const result = reconcileSavedSetup(
            { last_player: 'media_player.esszimmer', game_settings: { difficulty: 'hard' } },
            mockStorage(store)
        );

        expect(result.settingsSeeded).toBe(true);
        expect(JSON.parse(store.beatify_game_settings)).toEqual({ difficulty: 'hard' });
    });

    it('never overwrites local settings with the server copy', () => {
        const store = { beatify_game_settings: '{"difficulty":"easy"}' };

        const result = reconcileSavedSetup(
            { game_settings: { difficulty: 'hard' } },
            mockStorage(store)
        );

        expect(result.settingsSeeded).toBe(false);
        expect(store.beatify_game_settings).toBe('{"difficulty":"easy"}');
    });
});

describe('#1927 reconcileSavedSetup — defensive', () => {
    it('is a no-op for a missing or malformed blob', () => {
        const store = { beatify_last_player: 'media_player.esszimmer' };
        const storage = mockStorage(store);

        for (const blob of [null, undefined, 'nope', 42]) {
            const result = reconcileSavedSetup(blob, storage);
            expect(result).toEqual({ playerAdopted: null, settingsSeeded: false });
        }
        expect(store.beatify_last_player).toBe('media_player.esszimmer');
    });

    it('survives storage that throws (private mode)', () => {
        const throwing = {
            getItem: () => { throw new Error('denied'); },
            setItem: () => { throw new Error('denied'); },
        };

        expect(() => reconcileSavedSetup({ last_player: 'media_player.esszimmer' }, throwing)).not.toThrow();
    });

    it('is a no-op without a storage object at all', () => {
        expect(reconcileSavedSetup({ last_player: 'media_player.esszimmer' }, null))
            .toEqual({ playerAdopted: null, settingsSeeded: false });
    });
});

describe('#1927 speakerLabelFor', () => {
    it('shows the friendly name of the resolved speaker', () => {
        const players = [
            { entity_id: 'media_player.kuche_2', friendly_name: 'Küche' },
            { entity_id: 'media_player.esszimmer', friendly_name: 'Esszimmer' },
        ];

        expect(speakerLabelFor('media_player.esszimmer', players)).toBe('🔊 Esszimmer');
    });

    it('falls back to the entity_id when the player list has no match yet', () => {
        expect(speakerLabelFor('media_player.kuche_2', [])).toBe('🔊 media_player.kuche_2');
    });

    it('says so when no speaker is resolved', () => {
        expect(speakerLabelFor('', [])).toBe('🔊 no speaker');
        expect(speakerLabelFor(null, undefined)).toBe('🔊 no speaker');
    });
});
