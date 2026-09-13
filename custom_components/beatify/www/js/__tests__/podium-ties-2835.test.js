/**
 * #2835 — a tie inside the top three must not drop anyone from the podium.
 *
 * The server ranks competition-style (`game/state_leaderboard.py`): scores
 * [282, 282, 0] come out as ranks [1, 1, 3]. All three end screens filled their
 * stands with `leaderboard.find(rank === place)`, which assumes one player per
 * rank. So a tie for first put one winner on stand 1, found nobody holding rank
 * 2, and dropped the second winner — and the TV's "Full Rankings", which only
 * listed `rank > 3`, lost everyone else tied inside the top three. The live test
 * of v4.7.0-rc2 walked into it with eleven guests: seven players missing from
 * the Game Over screen.
 *
 * What these tests hold on to:
 *
 *   1. every player appears exactly once — on a stand or in the ranking below;
 *   2. stands are filled by position, and a stand's label and medal follow the
 *      rank of whoever stands on it, so a co-winner on stand 2 still reads "1";
 *   3. the same in all three views, run from the shipped source.
 */
import { describe, it, expect } from 'vitest';
import { declaration, evaluate, readSource } from './helpers/js-source.js';
import { doc, el } from './helpers/mini-dom.js';

// utils.js assigns to window.BeatifyUtils at eval; stub the global first.
global.window = global.window || {};
await import('../utils.js');
const U = global.window.BeatifyUtils;

const noop = () => {};

/** Ranks the way the server does: by score, ties share the rank, then it skips. */
function board(...players) {
    const sorted = players
        .map(([name, score]) => ({ name, score }))
        .sort((a, b) => b.score - a.score || a.name.localeCompare(b.name));
    let rank = 0;
    let previous = null;
    return sorted.map((p, i) => {
        if (p.score !== previous) rank = i + 1;
        previous = p.score;
        return { rank, name: p.name, score: p.score };
    });
}

const TIE_FOR_FIRST = board(['Tie-A', 282], ['Tie-B', 282], ['Low', 0]);
const TIE_FOR_SECOND = board(['Ann', 300], ['Ben', 200], ['Cat', 200]);
const ALL_TIED = board(['Ann', 100], ['Ben', 100], ['Cat', 100], ['Dan', 100]);
const TWO_WINNERS = board(['Sandra', 80], ['Aaron', 80]);
// The eleven-guest game from the issue: two at 255, six at 230, three below.
const ELEVEN = board(
    ['Emil', 255], ['Frieda', 255],
    ['Andreas', 230], ['Anna', 230], ['Ben', 230], ['Bettina', 230], ['Clara', 230], ['Dave', 230],
    ['Gustav', 120], ['Hanna', 120], ['Ida Maria Longname', 120],
);

const names = (entries) => entries.map((e) => (e ? e.name : null));

// ---------------------------------------------------------------------------

describe('#2835 — BeatifyUtils.podiumStands', () => {
    it('puts both winners of a tie for first on the podium', () => {
        const { stands, rest } = U.podiumStands(TIE_FOR_FIRST);
        expect(names(stands)).toEqual(['Tie-A', 'Tie-B', 'Low']);
        expect(stands.map((s) => s.rank)).toEqual([1, 1, 3]);
        expect(rest).toEqual([]);
    });

    it('fills the third stand on a tie for second (ranks 1, 2, 2)', () => {
        const { stands } = U.podiumStands(TIE_FOR_SECOND);
        expect(names(stands)).toEqual(['Ann', 'Ben', 'Cat']);
        expect(stands.map((s) => s.rank)).toEqual([1, 2, 2]);
    });

    it('seats three of an all-tied room and ranks the fourth below', () => {
        const { stands, rest } = U.podiumStands(ALL_TIED);
        expect(stands.map((s) => s.rank)).toEqual([1, 1, 1]);
        expect(names(rest)).toEqual(['Dan']);
    });

    it('accounts for every one of eleven players exactly once', () => {
        const { stands, rest } = U.podiumStands(ELEVEN);
        expect(names(stands)).toEqual(['Emil', 'Frieda', 'Andreas']);
        const everyone = names(stands).concat(names(rest));
        expect(everyone).toHaveLength(11);
        expect(new Set(everyone).size).toBe(11);
        expect(everyone.sort()).toEqual(names(ELEVEN).sort());
    });

    it('leaves a stand empty only when there is nobody left to put on it', () => {
        expect(names(U.podiumStands(TWO_WINNERS).stands)).toEqual(['Aaron', 'Sandra', null]);
        expect(names(U.podiumStands([]).stands)).toEqual([null, null, null]);
        expect(names(U.podiumStands(undefined).stands)).toEqual([null, null, null]);
    });

    it('does not reorder the leaderboard it was given', () => {
        const given = [TIE_FOR_SECOND[2], TIE_FOR_SECOND[0], TIE_FOR_SECOND[1]];
        const before = names(given);
        U.podiumStands(given);
        expect(names(given)).toEqual(before);
    });

    it('gives each rank its medal', () => {
        expect([1, 2, 3].map(U.podiumMedal)).toEqual(['🥇', '🥈', '🥉']);
    });
});

// ---------------------------------------------------------------------------
// The three views, run from the shipped source.
// ---------------------------------------------------------------------------

/** A stand with the label and medal elements each page's markup carries. */
function stand(place, labelSelector) {
    const label = el(`label-${place}`);
    const medal = el(`medal-${place}`);
    const node = el(`podium-place-${place}`, {
        children: { [labelSelector]: label, '.podium-medal': medal },
    });
    return { node, label, medal };
}

/** Who ended up where, as the room would read it. */
function readPodium(stands, nameOf, hiddenBy) {
    return [1, 2, 3].map((place) => ({
        name: nameOf(place),
        label: String(stands[place].label.textContent),
        medal: stands[place].medal.textContent,
        hidden: hiddenBy(stands[place].node),
    }));
}

function renderDashboard(leaderboard) {
    const stands = {};
    const elements = {};
    [1, 2, 3].forEach((place) => {
        stands[place] = stand(place, '.podium-place-lbl');
        const under = { selector: '.podium-place', node: stands[place].node };
        for (const part of ['name', 'score', 'avatar']) {
            elements[`end-podium-${place}-${part}`] = el(`end-podium-${place}-${part}`, { closest: under });
        }
    });
    for (const id of ['end-meta-rounds', 'end-meta-players', 'end-leaderboard']) elements[id] = el(id);

    evaluate(declaration(readSource('dashboard.js'), 'renderEndView', 'dashboard.js'), 'renderEndView', {
        document: doc(elements),
        utils: { ...U, escapeHtml: (s) => String(s) },
        renderSuddenDeathLastStanding: noop,
        playClosingMoment: () => false,
        renderStatsComparison: noop,
        renderSuperlatives: noop,
        renderHighlights: noop,
        triggerConfetti: noop,
        endAvatarGradient: () => 'linear-gradient(#000,#fff)',
    })({ leaderboard });

    return {
        podium: readPodium(
            stands,
            (p) => elements[`end-podium-${p}-name`].textContent,
            (node) => node.classList.contains('podium-place--empty'),
        ),
        rankings: elements['end-leaderboard'].innerHTML,
    };
}

function renderAdmin(leaderboard) {
    const stands = {};
    const elements = { 'admin-end-section': el('admin-end-section') };
    [1, 2, 3].forEach((place) => {
        stands[place] = stand(place, '.podium-stand');
        const under = { selector: '.podium-place', node: stands[place].node };
        for (const part of ['name', 'score']) {
            elements[`admin-podium-${place}-${part}`] = el(`admin-podium-${place}-${part}`, { closest: under });
        }
    });
    let rankings = null;

    evaluate(declaration(readSource('admin.js'), 'showAdminEndView', 'admin.js'), 'showAdminEndView', {
        document: doc(elements),
        utils: U,
        adminState: {},
        renderAdminLeaderboard: (lb) => { rankings = lb; },
        countdownInterval: null,
        clearInterval: noop,
    })({ leaderboard });

    return {
        podium: readPodium(
            stands,
            (p) => elements[`admin-podium-${p}-name`].textContent,
            (node) => node.classList.contains('hidden'),
        ),
        rankings,
    };
}

function renderPlayer(leaderboard) {
    const stands = {};
    const elements = {};
    [1, 2, 3].forEach((place) => {
        stands[place] = stand(place, '.podium-stand');
        elements[`.podium-place.podium-${place}`] = stands[place].node;
        for (const part of ['name', 'score']) elements[`podium-${place}-${part}`] = el(`podium-${place}-${part}`);
    });
    elements['final-leaderboard-list'] = el('final-leaderboard-list');

    evaluate(declaration(readSource('player-end.js'), 'updateEndView', 'player-end.js'), 'updateEndView', {
        window: { scrollTo: noop },
        document: doc(elements),
        state: { playerName: 'Watching from the sofa' },
        utils: { ...U, t: (key, fallback) => (typeof fallback === 'string' ? fallback : key) },
        escapeHtml: (s) => String(s),
        renderSuperlatives: noop,
        renderHighlights: noop,
        renderShareTab: noop,
        renderGuestWaiting: noop,
        hostNameOf: () => null,
        triggerConfetti: noop,
    })({ leaderboard });

    return {
        podium: readPodium(
            stands,
            (p) => elements[`podium-${p}-name`].textContent,
            (node) => node.classList.contains('hidden'),
        ),
        rankings: elements['final-leaderboard-list'].innerHTML,
    };
}

const VIEWS = [
    { name: 'TV dashboard', render: renderDashboard },
    { name: 'host', render: renderAdmin },
    { name: 'player', render: renderPlayer },
];

describe.each(VIEWS)('#2835 — the $name end screen', ({ render }) => {
    it('shows both winners of a tie for first, each labelled first', () => {
        expect(render(TIE_FOR_FIRST).podium).toEqual([
            { name: 'Tie-A', label: '1', medal: '🥇', hidden: false },
            { name: 'Tie-B', label: '1', medal: '🥇', hidden: false },
            { name: 'Low', label: '3', medal: '🥉', hidden: false },
        ]);
    });

    it('labels a tie for second on stands two and three', () => {
        expect(render(TIE_FOR_SECOND).podium.map((s) => [s.name, s.label, s.medal])).toEqual([
            ['Ann', '1', '🥇'],
            ['Ben', '2', '🥈'],
            ['Cat', '2', '🥈'],
        ]);
    });

    it('seats both players of a two-player tie and hides only the third stand', () => {
        expect(render(TWO_WINNERS).podium.map((s) => [s.name, s.hidden])).toEqual([
            ['Aaron', false],
            ['Sandra', false],
            ['---', true],
        ]);
    });

    it('keeps the ordinary labels and medals when nobody is tied', () => {
        const out = render(board(['Sandra', 162], ['Aaron', 128], ['Kim', 90])).podium;
        expect(out.map((s) => [s.name, s.label, s.medal])).toEqual([
            ['Sandra', '1', '🥇'],
            ['Aaron', '2', '🥈'],
            ['Kim', '3', '🥉'],
        ]);
    });
});

describe('#2835 — nobody tied inside the top three disappears from the TV', () => {
    it('lists every player not on a stand in Full Rankings', () => {
        const { podium, rankings } = renderDashboard(ELEVEN);
        const onStands = podium.map((s) => s.name);
        expect(onStands).toEqual(['Emil', 'Frieda', 'Andreas']);
        for (const entry of ELEVEN) {
            const shownOnStand = onStands.includes(entry.name);
            const shownInRankings = rankings.includes(`>${entry.name}<`);
            expect(shownOnStand !== shownInRankings, `${entry.name} appears exactly once`).toBe(true);
        }
    });

    it('still lists the whole board below a podium of three', () => {
        const { rankings } = renderDashboard(TIE_FOR_FIRST);
        for (const name of ['Tie-A', 'Tie-B', 'Low']) expect(rankings).toContain(`>${name}<`);
    });
});
