/**
 * #1402 B7 — last-player auto-restore must select the radio INPUT, not the
 * wrapper div.
 *
 * In the rendered markup both the `.media-player-item` wrapper div AND the
 * `.media-player-radio` input carry `data-entity-id`, and the wrapper comes
 * first in DOM order. The old `container.querySelector('[data-entity-id="…"]')`
 * therefore grabbed the div: setting `.checked` on it is a no-op and
 * handleMediaPlayerSelect() read `radio.dataset.state` === undefined, so
 * `adminState.selectedMediaPlayer.state` ended up undefined and the radio was
 * never actually checked. The fix scopes the selector to
 * `.media-player-radio[data-entity-id="…"]` (mirroring admin.js
 * hydrateFromStorage).
 *
 * The vitest env is `node` (no jsdom), so we hand-roll a minimal DOM whose
 * container.querySelector resolves the two selector shapes the way a browser
 * would: a bare `[data-entity-id]` matches the wrapper div (first in order),
 * while `.media-player-radio[data-entity-id]` matches the radio input. The test
 * then asserts the *radio* (the one carrying data-state) is what got selected.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

// CSS.escape is used by the production code; node has no CSS global.
globalThis.CSS = globalThis.CSS || { escape: (s) => String(s) };

const ENTITY = 'media_player.living_room';

function makeNode(extra = {}) {
    return {
        checked: false,
        dataset: {},
        attributes: {},
        classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
        setAttribute() {},
        removeAttribute() {},
        querySelector: () => null,
        querySelectorAll: () => [],
        closest: () => null,
        addEventListener() {},
        textContent: '',
        ...extra,
    };
}

let store;
let radioNode;
let wrapperNode;
let elements;

beforeEach(() => {
    store = {};
    globalThis.window = globalThis;
    globalThis.BeatifyUtils = { escapeHtml: (s) => String(s) };
    globalThis.BeatifyI18n = { t: (k) => k };
    globalThis.localStorage = {
        getItem: (k) => (k in store ? store[k] : null),
        setItem: (k, v) => { store[k] = String(v); },
    };

    // Radio input: carries BOTH data-entity-id AND data-state (like the real
    // <input class="media-player-radio">).
    radioNode = makeNode({
        dataset: { entityId: ENTITY, state: 'playing', platform: 'sonos' },
        closest: () => wrapperNode,
        querySelector: () => makeNode({ textContent: 'Living Room' }),
    });
    // Wrapper div: carries data-entity-id but NO data-state (the bug bait).
    wrapperNode = makeNode({
        dataset: { entityId: ENTITY }, // no `state`
        classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    });

    // The list container. Its querySelector distinguishes the two selectors:
    //  - radio-scoped selector → the radio input
    //  - any other [data-entity-id] selector → the wrapper div (DOM-first)
    const container = makeNode({
        innerHTML: '',
        querySelector: (sel) => {
            if (sel.includes('.media-player-radio')) return radioNode;
            if (sel.includes('data-entity-id')) return wrapperNode; // pre-fix path
            return null;
        },
        querySelectorAll: () => [],
    });

    elements = {
        'media-players-list': container,
        'media-players': makeNode(),
        'media-players-toggle': makeNode(),
        'media-player-validation-msg': makeNode(),
        'music-service': makeNode(),
        'start-game': makeNode(),
    };

    globalThis.document = {
        getElementById: (id) => elements[id] || null,
        querySelectorAll: () => [],
        querySelector: () => null,
    };
});

afterEach(() => {
    delete globalThis.window;
    delete globalThis.document;
    delete globalThis.localStorage;
    delete globalThis.BeatifyUtils;
    delete globalThis.BeatifyI18n;
    vi.restoreAllMocks();
});

describe('renderMediaPlayers last-player auto-restore (#1402 B7)', () => {
    it('selects the radio input (with data-state), not the bare-data-entity-id wrapper div', async () => {
        store['beatify_last_player'] = ENTITY;
        // import after globals are installed (module reads window.BeatifyUtils at init)
        // Stable (non-cache-busted) paths so media-players.js and this test
        // share the SAME adminState singleton instance.
        const mp = await import('../admin/sections/media-players.js');
        const state = await import('../admin/state.js');

        mp.renderMediaPlayers([
            { entity_id: ENTITY, friendly_name: 'Living Room', state: 'playing', platform: 'sonos',
              supports_spotify: true, supports_apple_music: false, supports_youtube_music: false,
              supports_tidal: false, supports_deezer: false, supports_amazon_music: false },
        ]);

        // The radio (not the wrapper) was the selected source → state is defined.
        expect(radioNode.checked).toBe(true);
        expect(state.adminState.selectedMediaPlayer).toBeTruthy();
        expect(state.adminState.selectedMediaPlayer.entityId).toBe(ENTITY);
        // The load-bearing regression assertion: pre-fix this was `undefined`
        // because the wrapper div has no data-state.
        expect(state.adminState.selectedMediaPlayer.state).toBe('playing');
    });
});
