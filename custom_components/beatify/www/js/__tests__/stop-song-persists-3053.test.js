/**
 * #3053 — the host's Stop Song was undone by the next guest submission.
 *
 * player-core calls updateControlBarState('PLAYING') on every PLAYING frame,
 * and every guest submission re-broadcasts one. The function reset the
 * stopped state unconditionally, so the "song stopped" chip vanished on every
 * phone and the host's Stop button re-armed. It now resets only when the
 * round changes, and the server's `song_stopped` flag restores the state.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';

global.WebSocket = { OPEN: 1, CONNECTING: 0, CLOSED: 3 };
global.IntersectionObserver = class {
    observe() {}
    disconnect() {}
};
// Translator returns real templates for the sabotage format keys (so {name}/
// {effect} interpolation is exercised) and echoes the key otherwise.
const I18N = {};
global.window = {
    BeatifyUtils: { t: (key) => (key in I18N ? I18N[key] : key) },
    matchMedia: () => ({ matches: true, addEventListener: () => {} }),
};

// Element stub: classList + querySelector + appendChild (records children) +
// addEventListener (so a rendered target row can be "clicked").
function makeEl(id) {
    const classes = new Set();
    const children = {};
    const kids = [];
    const listeners = {};
    let innerHTML = '';
    const el = {
        id,
        className: '',
        textContent: '',
        disabled: false,
        _attrs: {},
        children,
        kids,
        classList: {
            add: (...c) => c.forEach((x) => classes.add(x)),
            remove: (...c) => c.forEach((x) => classes.delete(x)),
            contains: (c) => classes.has(c),
            toggle: (c, on) => {
                const want = on === undefined ? !classes.has(c) : on;
                if (want) classes.add(c); else classes.delete(c);
                return classes.has(c);
            },
        },
        setAttribute: (k, v) => { el._attrs[k] = v; },
        removeAttribute: (k) => { delete el._attrs[k]; },
        getAttribute: (k) => (k in el._attrs ? el._attrs[k] : null),
        querySelector: (sel) => children[sel] || null,
        appendChild: (child) => { kids.push(child); return child; },
        addEventListener: (type, fn) => { (listeners[type] = listeners[type] || []).push(fn); },
        dispatch: (type) => { (listeners[type] || []).forEach((fn) => fn()); },
    };
    Object.defineProperty(el, 'innerHTML', {
        get: () => innerHTML,
        set: (v) => { innerHTML = v; if (v === '') { kids.length = 0; } },
    });
    return el;
}

let els;
global.document = {
    getElementById: (id) => els[id] || null,
    createElement: () => makeEl(),
};

vi.mock('../player-utils.js', () => {
    const state = { ws: null, playerName: null };
    return {
        state,
        escapeHtml: (s) => String(s),
        showConfirmModal: async () => true,
        prefersReducedMotion: () => true,
        animateValue: () => {},
        previousState: {},
        isPreviousStateInitialized: () => false,
        detectRankChanges: () => ({}),
        updatePreviousState: () => {},
        AnimationUtils: {},
        AnimationQueue: { isRunning: () => false, skipAll: () => {} },
        LEADERBOARD_LAZY_CONFIG: {},
        lazyLeaderboardState: {},
        initLeaderboardObserver: () => {},
        renderLazyLeaderboardRange: () => {},
        renderLeaderboardEntry: () => '',
        calculateInitialVisibleRange: () => [0, 0],
        setupLeaderboardResizeHandler: () => {},
        setEnergyLevel: () => {},
        triggerConfetti: () => {},
        stopConfetti: () => {},
        isTitleArtistMode: () => false,
        // #1665: the sabotage modal reuses the steal focus-trap helper.
        createModalFocusTrap: () => ({ activate: () => {}, deactivate: () => {} }),
    };
});

const utilsMod = await import('../player-utils.js');
const {
    updateControlBarState,
    handleSongStopped,
    resetSongStoppedState,
} = await import('../player-game.js');

function setupDom() {
    els = {};
    for (const id of ['stop-song-btn', 'next-round-admin-btn', 'end-game-btn', 'song-stopped-chip']) {
        els[id] = makeEl(id);
    }
    els['song-stopped-chip'].classList.add('hidden');
    els['stop-song-btn'].children['.control-icon'] = makeEl();
    els['stop-song-btn'].children['.control-label'] = makeEl();
}

const chipHidden = () => els['song-stopped-chip'].classList.contains('hidden');

beforeEach(() => {
    vi.useFakeTimers();
    utilsMod.state.playerName = 'Host';
    setupDom();
    resetSongStoppedState();
    // First frame of round 1 arms the round tracker.
    updateControlBarState('PLAYING', { round: 1, song_stopped: false });
});

afterEach(() => {
    vi.runOnlyPendingTimers();
    vi.useRealTimers();
});

describe('Stop Song survives repeated PLAYING frames (#3053)', () => {
    it('keeps the chip and the disabled Stop button on a same-round frame', () => {
        handleSongStopped();
        expect(chipHidden()).toBe(false);
        updateControlBarState('PLAYING', { round: 1, song_stopped: true });
        expect(chipHidden()).toBe(false);
        expect(els['stop-song-btn'].disabled).toBe(true);
    });

    it('keeps it even when the frame carries no song_stopped field', () => {
        handleSongStopped();
        updateControlBarState('PLAYING', { round: 1 });
        expect(chipHidden()).toBe(false);
        expect(els['stop-song-btn'].disabled).toBe(true);
    });

    it('rebuilds the stopped state from the payload after a reload', () => {
        updateControlBarState('PLAYING', { round: 1, song_stopped: true });
        expect(chipHidden()).toBe(false);
        expect(els['stop-song-btn'].disabled).toBe(true);
    });

    it('resets on a new round', () => {
        handleSongStopped();
        updateControlBarState('PLAYING', { round: 2, song_stopped: false });
        expect(chipHidden()).toBe(true);
        expect(els['stop-song-btn'].disabled).toBe(false);
    });
});
