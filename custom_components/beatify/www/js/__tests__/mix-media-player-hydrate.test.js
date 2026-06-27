/**
 * #1619 — "Mix starten" inside the setup wizard falsely reported
 * "Select a media player first" because the wizard saves the chosen speaker
 * only to `localStorage.beatify_last_player`, never to
 * `adminState.selectedMediaPlayer`, and the `BeatifyHome.hydrateFromStorage()`
 * bridge only runs in the post-wizard Home view — not at wizard step 3 where
 * the Mix tab lives.
 *
 * These cover the new `ensureMediaPlayerHydrated()` guard that resolves the
 * player from the unified source (BeatifyHome bridge, then localStorage
 * fallback) before the start gate. vitest env is `node` (no DOM) — the helper
 * deliberately reads `globalThis` so it stays testable here.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { ensureMediaPlayerHydrated } from '../admin/sections/mix.js';
import { adminState } from '../admin/state.js';

function mockLocalStorage(store) {
    globalThis.localStorage = {
        getItem: (k) => (Object.prototype.hasOwnProperty.call(store, k) ? store[k] : null),
        setItem: (k, v) => { store[k] = String(v); },
        removeItem: (k) => { delete store[k]; },
    };
}

beforeEach(() => {
    adminState.selectedMediaPlayer = null;
    delete globalThis.localStorage;
    delete globalThis.BeatifyHome;
});

afterEach(() => {
    adminState.selectedMediaPlayer = null;
    delete globalThis.localStorage;
    delete globalThis.BeatifyHome;
});

describe('#1619 ensureMediaPlayerHydrated', () => {
    it('hydrates the wizard speaker from localStorage when the admin global is empty', () => {
        mockLocalStorage({ beatify_last_player: 'media_player.esszimmer' });

        ensureMediaPlayerHydrated();

        expect(adminState.selectedMediaPlayer).toBeTruthy();
        expect(adminState.selectedMediaPlayer.entityId).toBe('media_player.esszimmer');
    });

    it('leaves the global null when no player is stored anywhere (gate still fires)', () => {
        mockLocalStorage({});

        ensureMediaPlayerHydrated();

        expect(adminState.selectedMediaPlayer).toBeNull();
    });

    it('is idempotent: does not overwrite an already-selected player', () => {
        adminState.selectedMediaPlayer = { entityId: 'media_player.kitchen', state: 'idle', platform: 'spotify' };
        mockLocalStorage({ beatify_last_player: 'media_player.esszimmer' });

        ensureMediaPlayerHydrated();

        // Existing selection wins — no clobbering from the fallback.
        expect(adminState.selectedMediaPlayer.entityId).toBe('media_player.kitchen');
        expect(adminState.selectedMediaPlayer.platform).toBe('spotify');
    });

    it('prefers the BeatifyHome bridge when it populates the player (no stub fallback)', () => {
        const hydrate = vi.fn(() => {
            adminState.selectedMediaPlayer = { entityId: 'media_player.living', state: 'idle', platform: 'tidal' };
        });
        globalThis.BeatifyHome = { hydrateFromStorage: hydrate };
        mockLocalStorage({ beatify_last_player: 'media_player.esszimmer' });

        ensureMediaPlayerHydrated();

        expect(hydrate).toHaveBeenCalledTimes(1);
        // Bridge result kept; the localStorage stub fallback is skipped.
        expect(adminState.selectedMediaPlayer.entityId).toBe('media_player.living');
        expect(adminState.selectedMediaPlayer.platform).toBe('tidal');
    });

    it('survives a throwing storage (private mode) without crashing', () => {
        globalThis.localStorage = {
            getItem: () => { throw new Error('SecurityError: localStorage blocked'); },
        };

        expect(() => ensureMediaPlayerHydrated()).not.toThrow();
        expect(adminState.selectedMediaPlayer).toBeNull();
    });
});
