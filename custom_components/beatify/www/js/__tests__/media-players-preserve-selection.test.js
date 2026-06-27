/**
 * #1619-followup — renderMediaPlayers() used to blindly null
 * adminState.selectedMediaPlayer on every render and re-derive it from
 * localStorage. That silently dropped a still-valid selection whenever it
 * wasn't re-derivable — most notably a speaker that is transiently
 * `unavailable` (filtered out of the rendered list) during a routine
 * status-poll re-render.
 *
 * `_shouldKeepSelection()` is the pure decision the render now uses: keep the
 * selection as long as the chosen player is still present in the incoming
 * payload (available OR unavailable); only a player that actually disappeared
 * clears it. vitest env is `node` — this covers the pure helper.
 *
 * media-players.js imports playlists.js which reads `window.BeatifyUtils` at
 * module init, so (like media-players-autorestore.test.js) we install the
 * globals first and import the module dynamically.
 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest';

const ESSZIMMER = 'media_player.esszimmer';
const KITCHEN = 'media_player.kitchen';

let shouldKeep;

beforeEach(async () => {
    globalThis.window = globalThis;
    globalThis.BeatifyUtils = { escapeHtml: (s) => String(s) };
    globalThis.BeatifyI18n = { t: (k) => k };
    // Import after globals are installed (module reads window.BeatifyUtils at init).
    const mp = await import('../admin/sections/media-players.js');
    shouldKeep = mp._shouldKeepSelection;
});

afterEach(() => {
    delete globalThis.window;
    delete globalThis.BeatifyUtils;
    delete globalThis.BeatifyI18n;
});

describe('#1619-followup _shouldKeepSelection', () => {
    it('keeps the selection when the chosen player is present and available', () => {
        const players = [{ entity_id: ESSZIMMER, state: 'idle' }, { entity_id: KITCHEN, state: 'playing' }];
        expect(shouldKeep(ESSZIMMER, players)).toBe(true);
    });

    it('keeps the selection when the chosen player is present but transiently unavailable', () => {
        // The core fix: an unavailable speaker is filtered out of the rendered
        // list but is still in the raw payload — the choice must survive.
        const players = [{ entity_id: ESSZIMMER, state: 'unavailable' }];
        expect(shouldKeep(ESSZIMMER, players)).toBe(true);
    });

    it('clears when the chosen player has disappeared from the payload', () => {
        const players = [{ entity_id: KITCHEN, state: 'idle' }];
        expect(shouldKeep(ESSZIMMER, players)).toBe(false);
    });

    it('clears when there was no prior selection', () => {
        const players = [{ entity_id: ESSZIMMER, state: 'idle' }];
        expect(shouldKeep(null, players)).toBe(false);
    });

    it('clears on an empty / missing payload', () => {
        expect(shouldKeep(ESSZIMMER, [])).toBe(false);
        expect(shouldKeep(ESSZIMMER, null)).toBe(false);
        expect(shouldKeep(ESSZIMMER, undefined)).toBe(false);
    });
});
