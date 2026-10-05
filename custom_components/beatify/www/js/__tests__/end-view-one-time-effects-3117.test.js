/**
 * #3117 - the end screen's one-time effects ran on every END frame.
 *
 * END frames repeat (a guest's phone locking is a disconnect, and a disconnect
 * is a broadcast), so the scroll-to-top, the winner confetti and the rematch
 * button's re-enable all fired again while the host was reading the picker.
 *
 * Phone half: the shipped player-end.js and player-next-playlist.js run for
 * real, only their imports and the DOM are stubbed. TV half: the shipped
 * renderEndView is cut out of dashboard.js (helpers/js-source.js).
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { declaration, evaluate, readSource } from './helpers/js-source.js';

// ---- phone: stubs that must exist before the modules are imported ----------
const triggerConfetti = vi.fn();
const scrollTo = vi.fn();
const els = {};
function makeEl() {
    const classes = new Set();
    return {
        textContent: '',
        disabled: false,
        innerHTML: '',
        style: {},
        classList: {
            add: (...c) => c.forEach((x) => classes.add(x)),
            remove: (...c) => c.forEach((x) => classes.delete(x)),
            toggle: (c, f) => { if (f) classes.add(c); else classes.delete(c); },
            contains: (c) => classes.has(c),
        },
        appendChild: () => {},
        querySelector: () => null,
    };
}

global.window = {
    BeatifyUtils: {
        t: (k) => k,
        podiumStands: (lb) => ({ stands: [lb[0], lb[1], lb[2]], rest: lb.slice(3) }),
        podiumMedal: () => '',
    },
    scrollTo,
};
global.document = {
    getElementById: (id) => els[id] || null,
    querySelector: () => null,
    createElement: () => makeEl(),
};
global.WebSocket = { OPEN: 1 };

const playerState = { playerName: 'Ann', ws: { readyState: 1, send: vi.fn() } };
vi.mock('../player-utils.js', () => ({
    state: playerState,
    escapeHtml: (s) => String(s),
    showConfirmModal: () => {},
    joinRejectionMessage: () => '',
    AnimationQueue: {},
    triggerConfetti: (...a) => triggerConfetti(...a),
    stopConfetti: () => {},
    showView: () => {},
}));
vi.mock('../notify.js', () => ({ showToast: () => {} }));
vi.mock('../host-pause.js', () => ({ hostPauseAnnouncement: () => '' }));

const { updateEndView } = await import('../player-end.js');
const picker = await import('../player-next-playlist.js');

function endFrame(gameId, extra) {
    return {
        phase: 'END',
        game_id: gameId,
        total_rounds: 10,
        leaderboard: [
            { name: 'Ann', rank: 1, score: 50, is_admin: true, best_streak: 2 },
            { name: 'Bob', rank: 2, score: 30 },
            { name: 'Cy', rank: 3, score: 10 },
        ],
        ...extra,
    };
}

describe('phone end view (#3117)', () => {
    beforeEach(() => {
        scrollTo.mockClear();
        triggerConfetti.mockClear();
        for (const k of Object.keys(els)) delete els[k];
        els['player-rematch-btn'] = makeEl();
        els['end-admin-controls'] = makeEl();
        els['end-player-message'] = makeEl();
    });

    it('scrolls and fires confetti once for repeated END frames of one game', () => {
        updateEndView(endFrame('g-a'));
        updateEndView(endFrame('g-a'));
        updateEndView(endFrame('g-a'));
        expect(scrollTo).toHaveBeenCalledTimes(1);
        expect(triggerConfetti).toHaveBeenCalledTimes(1);
        expect(triggerConfetti).toHaveBeenCalledWith('winner');
    });

    it('still refreshes the data on later frames', () => {
        els['final-leaderboard-list'] = makeEl();
        updateEndView(endFrame('g-b'));
        const first = els['final-leaderboard-list'].innerHTML;
        const later = endFrame('g-b');
        later.leaderboard[1].connected = false;
        updateEndView(later);
        expect(els['final-leaderboard-list'].innerHTML).not.toBe(first);
        expect(els['final-leaderboard-list'].innerHTML).toContain('final-entry--disconnected');
    });

    it('plays the effects again when a new game ends', () => {
        updateEndView(endFrame('g-c'));
        updateEndView(endFrame('g-d'));
        updateEndView(endFrame('g-d'));
        expect(scrollTo).toHaveBeenCalledTimes(2);
        expect(triggerConfetti).toHaveBeenCalledTimes(2);
    });

    it('keeps the rematch button disabled across a refresh while a request is in flight', async () => {
        await picker.loadNextPlaylists(async () => ({
            tiles: [{ id: 't1', name: 'T', paths: ['a.json'] }],
            all: [], current: ['a.json'], selected: ['a.json'],
        }));
        const btn = els['player-rematch-btn'];
        updateEndView(endFrame('g-e'));
        btn.onclick();
        expect(btn.disabled).toBe(true);
        expect(btn.textContent).toBe('⏳');

        updateEndView(endFrame('g-e'));   // the next END frame
        picker.refreshPicker();
        expect(btn.disabled).toBe(true);
        expect(btn.textContent).toBe('⏳');

        picker.resetGoButton();           // rematch failed / settled
        expect(btn.disabled).toBe(false);
    });
});

// ---- TV half ----------------------------------------------------------------
describe('TV end view (#3117)', () => {
    const DASHBOARD = readSource('dashboard.js');
    const SNIPPETS = [
        'var closingMomentPlayedFor = null;',
        'var endConfettiPlayedFor = null;',
        declaration(DASHBOARD, 'renderEndView', 'dashboard.js'),
    ];

    function setup() {
        const confetti = vi.fn();
        const scope = {
            document: { getElementById: () => null, querySelector: () => null },
            utils: { podiumStands: (lb) => ({ stands: lb.slice(0, 3), rest: lb.slice(3) }), podiumMedal: () => '', t: (k) => k, escapeHtml: (s) => s },
            playClosingMoment: () => false,
            renderSuddenDeathLastStanding: () => {},
            renderStatsComparison: () => {},
            renderSuperlatives: () => {},
            renderHighlights: () => {},
            endAvatarGradient: () => '',
            triggerConfetti: confetti,
            setTimeout: (fn) => fn(),
        };
        const render = evaluate(SNIPPETS, 'renderEndView', scope);
        return { render, confetti };
    }
    const frame = (id) => ({
        game_id: id,
        leaderboard: [{ name: 'Ann', rank: 1, score: 50 }, { name: 'Bob', rank: 2, score: 30 }],
    });

    it('fires the winner confetti once per game, again for the next game', () => {
        const { render, confetti } = setup();
        render(frame('g-1'));
        render(frame('g-1'));
        expect(confetti).toHaveBeenCalledTimes(1);
        render(frame('g-2'));
        expect(confetti).toHaveBeenCalledTimes(2);
    });
});
