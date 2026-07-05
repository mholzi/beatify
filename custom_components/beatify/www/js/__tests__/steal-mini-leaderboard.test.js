/**
 * #1663 item 2 — Steal modal Mini-Leaderboard-Row (Variant B).
 *
 * Each steal target renders as a rank + name + score row; the overall leader
 * (rank 1) gets a crown + glow. The scores already ride along with every
 * state_update, so the modal enriches the name-only steal_targets response from
 * the cached (or supplied) leaderboard — no extra backend call.
 *
 * Imports the real player-game.js (heavy deps mocked) and drives the exported
 * handleStealTargets(), asserting the DOM the modal builds.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';

global.WebSocket = { OPEN: 1, CONNECTING: 0, CLOSED: 3 };
global.IntersectionObserver = class { observe() {} disconnect() {} };
global.window = {
    BeatifyUtils: { t: (key) => key },
    matchMedia: () => ({ matches: true, addEventListener: () => {} }),
};

// --- tiny DOM with createElement so the modal can build its rows ------------
function makeNode(tag) {
    return {
        tagName: (tag || 'div').toUpperCase(),
        children: [],
        parentNode: null,
        _attrs: {},
        style: {},
        textContent: '',
        innerHTML: '',
        classList: (function () {
            const set = new Set();
            return {
                _set: set,
                add() { for (let i = 0; i < arguments.length; i++) set.add(arguments[i]); },
                remove() { for (let i = 0; i < arguments.length; i++) set.delete(arguments[i]); },
                contains: (c) => set.has(c),
                toggle: (c, on) => { if (on) set.add(c); else set.delete(c); return set.has(c); },
            };
        })(),
        get className() { return Array.from(this.classList._set).join(' '); },
        set className(v) {
            this.classList._set.clear();
            String(v).split(/\s+/).filter(Boolean).forEach((c) => this.classList._set.add(c));
        },
        setAttribute(k, v) { this._attrs[k] = String(v); },
        getAttribute(k) { return this._attrs[k]; },
        appendChild(c) { c.parentNode = this; this.children.push(c); return c; },
        addEventListener() {},
        querySelector() { return null; },
    };
}
let els;
global.document = {
    getElementById: (id) => els[id] || null,
    createElement: (tag) => makeNode(tag),
};

vi.mock('../player-utils.js', () => ({
    state: { ws: null, playerName: 'Me' },
    escapeHtml: (s) => String(s),
    showConfirmModal: async () => false,
    prefersReducedMotion: () => true,
    animateValue: () => {},
    animateScoreChange: () => {},
    showPointsPopup: () => {},
    previousState: { players: {} },
    isPreviousStateInitialized: () => false,
    isStreakMilestone: () => false,
    detectRankChanges: () => ({}),
    updatePreviousState: () => {},
    AnimationUtils: {},
    AnimationQueue: {},
    LEADERBOARD_LAZY_CONFIG: { MIN_PLAYERS_FOR_LAZY: 999 },
    lazyLeaderboardState: {},
    initLeaderboardObserver: () => {},
    renderLazyLeaderboardRange: () => {},
    renderLeaderboardEntry: () => '',
    calculateInitialVisibleRange: () => ({}),
    setupLeaderboardResizeHandler: () => {},
    setEnergyLevel: () => {},
    triggerConfetti: () => {},
    stopConfetti: () => {},
    isTitleArtistMode: () => false,
    createModalFocusTrap: () => ({ activate: () => {}, deactivate: () => {} }),
}));
vi.mock('../notify.js', () => ({ showToast: () => {}, showBanner: () => {}, clearBanner: () => {} }));

const { handleStealTargets } = await import('../player-game.js');

function findRows(list) {
    return list.children.filter((c) => c.classList.contains('steal-target-row'));
}
function child(node, cls) {
    return node.children.find((c) => c.classList.contains(cls));
}

describe('#1663 item 2 — steal mini-leaderboard rows', () => {
    let list;
    beforeEach(() => {
        list = makeNode('div');
        els = { 'steal-modal': makeNode('div'), 'steal-target-list': list };
    });

    it('renders a rank + name + score row per target', () => {
        handleStealTargets({
            targets: ['Lena', 'Max'],
            leaderboard: [
                { name: 'Lena', rank: 1, score: 1240 },
                { name: 'Max', rank: 2, score: 980 },
                { name: 'Me', rank: 3, score: 610 },
            ],
        });
        const rows = findRows(list);
        expect(rows.length).toBe(2);
        expect(child(rows[0], 'steal-target-rank').textContent).toBe('1');
        expect(child(rows[0], 'steal-target-name').textContent).toBe('Lena');
        // Score is locale-formatted but always contains the digits.
        expect(child(rows[0], 'steal-target-score').textContent.replace(/\D/g, '')).toBe('1240');
    });

    it('gives the rank-1 leader a crown + leader class', () => {
        handleStealTargets({
            targets: ['Lena', 'Max'],
            leaderboard: [
                { name: 'Lena', rank: 1, score: 1240 },
                { name: 'Max', rank: 2, score: 980 },
            ],
        });
        const rows = findRows(list);
        expect(rows[0].classList.contains('steal-target-row--leader')).toBe(true);
        expect(child(rows[0], 'steal-target-crown')).toBeTruthy();
        // A non-leader gets neither.
        expect(rows[1].classList.contains('steal-target-row--leader')).toBe(false);
        expect(child(rows[1], 'steal-target-crown')).toBeFalsy();
        // Enriched rows carry an aria-label combining name + rank + score.
        expect(rows[0].getAttribute('aria-label')).toContain('Lena');
        expect(rows[0].getAttribute('aria-label')).toContain('#1');
    });

    it('falls back to a plain name row when standings are unknown', () => {
        handleStealTargets({ targets: ['Ghost'] });
        const rows = findRows(list);
        expect(rows.length).toBe(1);
        expect(child(rows[0], 'steal-target-name').textContent).toBe('Ghost');
        // Placeholder rank, no score, no leader styling.
        expect(child(rows[0], 'steal-target-rank').textContent).toBe('–');
        expect(rows[0].classList.contains('steal-target-row--leader')).toBe(false);
    });
});
