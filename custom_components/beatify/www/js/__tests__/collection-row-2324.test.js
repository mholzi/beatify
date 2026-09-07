/**
 * The collected row (#2324, shape E) — what it renders, when, and in what order.
 *
 * #2701: this suite used to assert on the TEXT of `player-reveal.js` — that it
 * contained `renderCollection(currentPlayer);`, `escapeHtml(entry.title`, the
 * string `collection-card--new`, and a regex over the empty-row branch — while
 * re-running a hand-copied comparator to cover the ordering. Every one of those
 * would go red on a rename and stay green on a row rendered in the wrong order,
 * escaped nowhere, or marked on the wrong card.
 *
 * `renderCollection` is imported and run instead, the way
 * `player-reveal-view.test.js` drives `updateRevealView`: vitest's env is `node`
 * with no jsdom, so the elements are hand-rolled and the module's cross-file
 * imports are mocked.
 */
import { describe, it, expect, beforeEach, vi } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { WWW_DIR } from './helpers/js-source.js';
import { doc, el } from './helpers/mini-dom.js';

const HTML = readFileSync(join(WWW_DIR, 'player.html'), 'utf8');

const mockState = { playerName: null, lastRevealContext: null, lastDifficulty: '' };
vi.mock('../player-utils.js', () => ({
    state: mockState,
    // A real (minimal) escaper wrapped in markers: the markers make "did this
    // field go through the escaper?" an observable property of the rendered
    // row, and the escaping keeps the row parseable when a title carries tags.
    escapeHtml: (s) => `«${String(s)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')}»`,
    prefersReducedMotion: () => true,
    animateValue: () => {},
    previousState: {},
    isPreviousStateInitialized: () => false,
    AnimationUtils: {},
    triggerConfetti: () => {},
    stopConfetti: () => {},
    isTitleArtistMode: (data) => !!(data && data.title_artist_mode),
}));
vi.mock('../player-game.js', () => ({
    updateLeaderboard: () => {},
    renderArtistReveal: () => {},
    renderMovieReveal: () => {},
}));

global.window = {
    BeatifyUtils: {
        t: (key, params) => (params && params.count != null ? `${key}:${params.count}` : key),
        getLocalizedSongField: (song, field) => (song ? song[field] : undefined),
    },
    matchMedia: () => ({ matches: true, addEventListener: () => {} }),
};
global.WebSocket = { OPEN: 1 };

let els;
let document_;
global.document = {
    getElementById: (id) => document_.getElementById(id),
    querySelector: (sel) => document_.querySelector(sel),
    querySelectorAll: () => [],
};

const { renderCollection, updateRevealView, stopRevealCountdown } =
    await import('../player-reveal.js');

function reset() {
    els = {
        'collection-section': el('collection-section'),
        'collection-row': el('collection-row'),
        'collection-count': el('collection-count'),
    };
    document_ = doc(els);
}

beforeEach(reset);

/** The cards the row ended up holding, in DOM order. */
function cards() {
    return [...els['collection-row'].innerHTML.matchAll(/<div class="(collection-card[^"]*)"[^>]*>([\s\S]*?)<\/div>/g)]
        .map((m) => ({
            classes: m[1],
            year: /collection-card-year">([^<]*)</.exec(m[2])?.[1],
            title: /collection-card-title">([^<]*)</.exec(m[2])?.[1],
            artist: /collection-card-artist">([^<]*)</.exec(m[2])?.[1],
        }));
}

const kept = (year, round, extra = {}) => ({
    year, round, title: `T${round}`, artist: `A${round}`, ...extra,
});

describe('#2324 collected row — what it draws', () => {
    it('reads left to right in years, not in the order won', () => {
        renderCollection({ collection: [kept(2004, 1), kept(1968, 2), kept(1991, 3)] });
        expect(cards().map((c) => c.year)).toEqual(['«1968»', '«1991»', '«2004»']);
    });

    it('is stable for two songs from the same year', () => {
        // The reveal re-renders on every reaction; a comparator returning 0 for
        // a tie would let the two cards swap places under the player's thumb.
        renderCollection({ collection: [kept(1985, 7), kept(1985, 2)] });
        expect(cards().map((c) => c.title)).toEqual(['«T2»', '«T7»']);
    });

    it('marks the card won this round, and only that one', () => {
        renderCollection({ collection: [kept(2004, 1), kept(1968, 3), kept(1991, 2)] });
        const marked = cards().filter((c) => c.classes.includes('collection-card--new'));
        expect(marked).toHaveLength(1);
        expect(marked[0].title).toBe('«T3»');  // round 3 is the newest
    });

    it('scrolls the freshly kept card into view', () => {
        // A long row runs off the right edge of a phone, and the one card the
        // player wants to see is the one that just appeared.
        const newCard = el(null);
        els['collection-row'].children['.collection-card--new'] = newCard;
        renderCollection({ collection: [kept(2004, 1), kept(1968, 3)] });
        expect(newCard.scrolledIntoView).toMatchObject({ inline: 'center' });
    });

    it('escapes every field that comes from the catalogue', () => {
        // Titles and artists are user-editable through the library views —
        // they are not safe to interpolate raw.
        renderCollection({
            collection: [{ year: 1999, round: 1, title: '<img src=x>', artist: '"><script>' }],
        });
        const card = cards()[0];
        expect(card.title).toBe('«&lt;img src=x&gt;»');
        expect(card.artist).toBe('«&quot;&gt;&lt;script&gt;»');
        expect(card.year).toBe('«1999»');
        expect(els['collection-row'].innerHTML).not.toContain('<img');
        expect(els['collection-row'].innerHTML).not.toContain('<script');
    });

    it('counts what it drew, through i18n', () => {
        renderCollection({ collection: [kept(2004, 1), kept(1968, 2)] });
        expect(els['collection-count'].textContent).toBe('reveal.collection.count:2');
    });
});

describe('#2324 collected row — when it is there at all', () => {
    it('hides the section while the row is empty', () => {
        // An empty shelf is worse than no shelf: before the first keeper there
        // is nothing to say, and a permanent empty box reads as a broken card.
        renderCollection({ collection: [] });
        expect(els['collection-section'].classList.contains('hidden')).toBe(true);
        expect(els['collection-row'].textContent).toBe('');
    });

    it('hides it for a player payload that has no collection at all', () => {
        renderCollection({});
        renderCollection(null);
        expect(els['collection-section'].classList.contains('hidden')).toBe(true);
    });

    it('shows the section again once the first card is kept', () => {
        renderCollection({ collection: [] });
        renderCollection({ collection: [kept(1977, 1)] });
        expect(els['collection-section'].classList.contains('hidden')).toBe(false);
    });

    it('redraws on a reveal that scored nothing', () => {
        // The row has to redraw on re-broadcasts too (reactions, votes), so it
        // hangs off every reveal rather than off the scoring branch — a reveal
        // that fires twice would otherwise show a stale row on the second frame.
        mockState.playerName = 'Alice';
        updateRevealView({
            round: 4,
            total_rounds: 12,
            song: { title: 'Africa', artist: 'Toto', year: 1982 },
            players: [{ name: 'Alice', score: 0, points_earned: 0, collection: [kept(1982, 4)] }],
        });
        stopRevealCountdown();
        expect(cards().map((c) => c.title)).toEqual(['«T4»']);
    });

    it('asks player.html for elements player.html actually has', () => {
        // Derived, not typed out: whatever ids the renderer looks up must exist
        // in the markup it renders into. A renamed id in either file fails here.
        renderCollection({ collection: [kept(1977, 1)] });
        expect(document_.lookedUp.length).toBeGreaterThan(0);
        for (const id of new Set(document_.lookedUp)) {
            expect(HTML, `player.html has no #${id}`).toContain(`id="${id}"`);
        }
    });
});

describe('#2324 collected row — locales', () => {
    it('has both strings in every shipped locale', () => {
        for (const lang of ['en', 'de', 'es', 'fr', 'nl', 'it']) {
            const dict = JSON.parse(readFileSync(join(WWW_DIR, 'i18n', `${lang}.json`), 'utf8'));
            expect(dict.reveal?.collection?.title, `${lang} missing title`).toBeTruthy();
            expect(dict.reveal?.collection?.count, `${lang} missing count`).toBeTruthy();
            // A missing placeholder does not throw — it renders "kept" with no
            // number, which looks like a label rather than a count.
            expect(dict.reveal.collection.count, `${lang} lost the placeholder`)
                .toContain('{count}');
        }
    });
});
